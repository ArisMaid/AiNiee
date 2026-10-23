"""Real directory/ProgramData bridge, not a memory writer acceptance."""
from pathlib import Path
import hashlib,json,shutil
import pytest

REPO=Path(__file__).resolve().parents[2]
SDK=REPO/'StevExtraction'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def inputs():
    items=[None,{'id':1,'name':'同文','description':'一行\r\n二行','note':''},
        {'id':2,'name':'同文','description':'別説明','note':''},
        {'id':3,'name':'同文','description':'保持','note':''}]
    raw=b'\xef\xbb\xbf'+json.dumps(items,ensure_ascii=False,indent=2).replace('\n','\r\n').encode()
    return {'data/Items.json':raw,'data/System.json':json.dumps({'gameTitle':'原題','flags':[True,1,1.0]}).encode(),
        'js/plugins.js':b'// no auto plugins\r\n','img/untouched.bin':b'asset\x00bytes'},items

def run(tmp_path,changes,backend=SDK):
    from ModuleFolders.Infrastructure.GameAdapters.StevProjectBridge import rewrite_project
    files,items=inputs();before={p:sha(p) for p in (backend/'jtpp.py',backend/'config.yaml')}
    result=rewrite_project(files,changes,tmp_path/'目录 空格',backend)
    assert all(sha(p)==v for p,v in before.items())
    proof=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert proof['entrypoint']=='Jr_Tpp.ReadGame -> Jr_Tpp.InjectGame'
    game=Path(proof['game_root']);assert game.is_relative_to(tmp_path)
    assert {p.relative_to(game).as_posix():p.read_bytes() for p in game.rglob('*') if p.is_file()}==files
    assert proof['config_sha256']==sha(backend/'config.yaml')
    assert proof['source_files']==4 and proof['source_preserved'] and proof['upstream_preserved']
    assert proof['patches']==['utf8-sig-io','disabled-list-cleanup']
    assert result['capabilities']['game_directory_read'] and result['capabilities']['program_data_bridge']
    rows=json.loads((game.parent/proof['program_data']['path']).read_text(encoding='utf-8'))['rows']
    assert all({'original','translation','address','labels','code','name_label','occurrences'}<=r.keys() for r in rows)
    assert any(r['original']=='同文' and len(r['occurrences'])==3 for r in rows)
    for stage in proof['rounds']:
        base=game.parent/stage['root']
        assert {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}==set(result['output_paths'])
        assert all(sha(base/r['path'])==r['sha256'] for r in stage['files'])
    return result,proof,items

def test_real_directory_program_data_roundtrip_separates_duplicate_occurrences(tmp_path):
    changes={'data/Items.json':[{'pointer':'/1/name','source_text':'同文','text':'甲译文'},
        {'pointer':'/2/name','source_text':'同文','text':'乙译文'}]}
    result,proof,expected=run(tmp_path,changes)
    expected[1]['name']='甲译文';expected[2]['name']='乙译文'
    actual=Path(result['output_paths']['data/Items.json']).read_bytes()
    assert actual.startswith(b'\xef\xbb\xbf') and json.loads(actual.decode('utf-8-sig'))==expected
    assert len(proof['rounds'])==2
    assert json.loads(Path(result['sidecars']['data/Items.json']).read_text(encoding='utf-8'))['requested_pointers']==['/1/name','/2/name']

def test_zero_changes_calls_real_directory_injection_and_reports_format_changes(tmp_path):
    result,proof,expected=run(tmp_path,{})
    assert len(proof['rounds'])==1 and proof['rounds'][0]['changes']==[]
    assert json.loads(Path(result['output_paths']['data/Items.json']).read_bytes().decode('utf-8-sig'))==expected
    assert all(not r['semantic_changed'] for r in proof['rounds'][0]['files'])
    assert any(r['byte_changed'] for r in proof['rounds'][0]['files'])

def isolated_sdk(tmp_path,suffix):
    root=tmp_path/'sdk';root.mkdir()
    for name in ('jtpp.py','config.yaml'):shutil.copy2(SDK/name,root/name)
    with (root/'jtpp.py').open('a',encoding='utf-8') as handle:handle.write(suffix)
    return root

def test_directory_extra_write_is_refused_before_file_creation(tmp_path):
    sdk=isolated_sdk(tmp_path,'\n_original_inject=Jr_Tpp.InjectGame\ndef _bad(self,GameDir,path,*args,**kwargs):\n'
        '    result=_original_inject(self,GameDir,path,*args,**kwargs)\n'
        '    with open(os.path.join(path,"unexpected.bin"),"wb") as output: output.write(b"bad")\n'
        '    return result\nJr_Tpp.InjectGame=_bad\n')
    with pytest.raises(ValueError,match='BACKEND_SIDE_EFFECT: open'):run(tmp_path,{},sdk)
    assert not list(tmp_path.rglob('unexpected.bin')) and not list(tmp_path.rglob('project-report.json'))

def test_directory_unapproved_json_semantic_change_is_not_repaired(tmp_path):
    sdk=isolated_sdk(tmp_path,'\n_original_inject=Jr_Tpp.InjectGame\ndef _bad(self,GameDir,path,*args,**kwargs):\n'
        '    result=_original_inject(self,GameDir,path,*args,**kwargs)\n'
        '    target=os.path.join(path,"data","System.json")\n'
        '    with open(target,"w",encoding="utf8") as output: json.dump({"gameTitle":"BAD"},output)\n'
        '    return result\nJr_Tpp.InjectGame=_bad\n')
    with pytest.raises(ValueError,match='BACKEND_UNAPPROVED_DIFF'):run(tmp_path,{},sdk)
    assert not list(tmp_path.rglob('project-report.json'))
    outputs=list(tmp_path.glob('目录 空格/*/pipeline/rounds/*/data/System.json'))
    assert outputs and json.loads(outputs[0].read_text(encoding='utf-8'))=={'gameTitle':'BAD'}

def test_explicit_empty_translation_is_refused_without_xlsx_side_effect(tmp_path):
    with pytest.raises(ValueError,match='BACKEND_EMPTY_TRANSLATION_UNSUPPORTED'):
        run(tmp_path,{'data/Items.json':[{'pointer':'/1/name','source_text':'同文','text':''}]})
    assert not list(tmp_path.rglob('*.xlsx'))
