"""Real pinned SExtractor must locate requested string leaves inside arrays."""
import copy,hashlib,json
from pathlib import Path
import pytest
from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document
from ModuleFolders.Service.GameProject.BuildService import file_hash

UPSTREAM=Path(__file__).resolve().parents[2]/'work/vendor/SExtractor'
pytestmark=pytest.mark.skipif(not (UPSTREAM/'src/extract_RPGMV.py').is_file(),reason='Pinned optional SExtractor is not installed')


def write(tmp_path,document,changes):
    raw=b'\xef\xbb\xbf'+(json.dumps(document,ensure_ascii=False,indent=2)+'\n').replace('\n','\r\n').encode()
    watched=[UPSTREAM/'src'/name for name in ('extract_RPGMV.py','common.py','extract_TXT.py')]
    before={path:file_hash(path) for path in watched}
    result=rewrite_document('sextractor','data/System.json',raw,changes,tmp_path/'后端 写入',UPSTREAM)
    assert result['output_bytes'].startswith(b'\xef\xbb\xbf')
    sidecar=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert sidecar['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert {row['pointer'] for row in sidecar['locators']}=={change['pointer'] for change in changes}
    for row in sidecar['locators']:
        pointer=''.join('/'+str(token).replace('~','~0').replace('/','~1') for token in row['ctrl']['pos'][0])
        assert pointer==row['pointer']
    assert not list((Path(result['sidecar_path']).parent/'cwd').iterdir())
    assert all(file_hash(path)==digest for path,digest in before.items())
    return json.loads(result['output_bytes'].decode('utf-8-sig'))


def test_system_terms_array_duplicates_keep_separate_translations_and_other_types(tmp_path):
    document={'terms':{'commands':['同文😀','同文😀','','設定'],'params':['同文😀']},
        'gameTitle':'未改名','switches':[None,'内部ID'],'flags':[True,1,1.0]}
    expected=copy.deepcopy(document);expected['terms']['commands'][0]='甲菜单';expected['terms']['commands'][1]='乙菜单'
    changes=[{'pointer':'/terms/commands/'+str(i),'source_text':'同文😀','text':text} for i,text in enumerate(('甲菜单','乙菜单'))]
    actual=write(tmp_path,document,changes)
    assert actual==expected and type(actual['flags'][1]) is int and type(actual['flags'][2]) is float


def test_nested_arrays_use_the_owning_dictionary_field_and_keep_unrequested_values(tmp_path):
    document={'terms':{'messages':[['同文','同文'],[]],'commands':['未改动']},'logic':{'messages':['同文']}}
    changes=[{'pointer':'/terms/messages/0/1','source_text':'同文','text':'指定消息'}]
    expected=copy.deepcopy(document);expected['terms']['messages'][0][1]='指定消息'
    assert write(tmp_path,document,changes)==expected


def test_mixed_dictionary_and_array_targets_preserve_resource_identity(tmp_path):
    document={'terms':{'commands':['選択','選択'],'entries':[{'caption':'表示','resource':'内部ID'}]}}
    changes=[{'pointer':'/terms/commands/1','source_text':'選択','text':'选择乙'},
        {'pointer':'/terms/entries/0/caption','source_text':'表示','text':'显示'}]
    expected=copy.deepcopy(document);expected['terms']['commands'][1]='选择乙';expected['terms']['entries'][0]['caption']='显示'
    assert write(tmp_path,document,changes)==expected


@pytest.mark.parametrize('document,pointer',[
    (['未支持'],'/0'),({'mapping':{'0':'未支持'}},'/mapping/0')])
def test_no_dictionary_owner_or_unrepresentable_key_keeps_existing_refusal(tmp_path,document,pointer):
    raw=json.dumps(document,ensure_ascii=False).encode()
    with pytest.raises(ValueError,match='BACKEND_LOCATOR_UNSUPPORTED'):
        rewrite_document('sextractor','data/System.json',raw,[{'pointer':pointer,'source_text':'未支持','text':'不能猜测'}],tmp_path/'refused',UPSTREAM)


@pytest.mark.parametrize('pointer,source,code',[
    ('/terms/commands/00','同文','BACKEND_POINTER_INVALID'),
    ('/terms/commands/0','错误原文','BACKEND_SOURCE_TEXT_MISMATCH')])
def test_array_discovery_keeps_pointer_and_source_guards(tmp_path,pointer,source,code):
    raw=json.dumps({'terms':{'commands':['同文']}},ensure_ascii=False).encode()
    with pytest.raises(ValueError,match=code):
        rewrite_document('sextractor','data/System.json',raw,[{'pointer':pointer,'source_text':source,'text':'译文'}],tmp_path/'invalid',UPSTREAM)
