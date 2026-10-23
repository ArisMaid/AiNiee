import json
from pathlib import Path
import unittest

import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BackendCandidateService import generate_candidate
from ModuleFolders.Service.GameProject.BuildService import file_hash

ROOT=Path(__file__).resolve().parents[2]
BACKENDS={'stev':ROOT/'StevExtraction','rpgmtl':ROOT/'work/vendor/RPGMTL','sextractor':ROOT/'work/vendor/SExtractor'}


class BackendWriteAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def check_items(self,backend):
        upstream=BACKENDS[backend]
        if not upstream.is_dir():self.skipTest('Optional pinned upstream is not installed')
        data=[None,{'id':1,'name':'同じ名前','description':'説明','note':'<logic:保持>'},
              {'id':2,'name':'同じ名前','description':'別説明','note':''}]
        raw=b'\xef\xbb\xbf'+(json.dumps(data,ensure_ascii=False,indent=2)+'\n').replace('\n','\r\n').encode()
        (self.root/'data/Items.json').write_bytes(raw)
        before={p.relative_to(self.root).as_posix():file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        watched=[upstream/'jtpp.py'] if backend=='stev' else ([upstream/'plugins/json.py',upstream/'plugins/__init__.py']
            if backend=='rpgmtl' else [upstream/'src/extract_RPGMV.py',upstream/'src/common.py'])
        upstream_hashes={p:file_hash(p) for p in watched}
        project=self.root.parent/(self.root.name+'-后端 空格')
        with GameProjectService.create(self.root,project) as service:
            service.extract()
            translations={}
            for unit in service.store.units():
                for occurrence in unit.occurrences:
                    if occurrence.relative_path=='data/Items.json' and occurrence.locator['pointer'] in ['/1/name','/2/name']:
                        translations[unit.unit_id]='甲名称' if occurrence.locator['pointer']=='/1/name' else '乙名称'
            self.assertEqual(len(translations),2)
            service.import_translations(translations)
            result=generate_candidate(service.store,backend,upstream,'data/Items.json')
            self.assertTrue(result['passed']);self.assertFalse(result['published'])
            output=Path(result['candidate']).read_bytes()
            self.assertTrue(output.startswith(b'\xef\xbb\xbf'))
            expected=json.loads(raw.decode('utf-8-sig'));expected[1]['name']='甲名称';expected[2]['name']='乙名称'
            self.assertEqual(json.loads(output.decode('utf-8-sig')),expected)
            sidecar=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
            self.assertEqual(sidecar['source_sha256'],file_hash(self.root/'data/Items.json'))
            self.assertEqual(list((project/'work/backends').glob('*/cwd/*')),[])
            from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
            route=configure_route(service.store,'data/Items.json',backend,upstream)
            self.assertEqual(route['backend'],backend)
            built=service.build(self.root.parent/(self.root.name+'-routed-build'),test=True)
            item=next(r for r in built['files'] if r['path']=='data/Items.json')
            self.assertEqual(item['writer']['id'],backend)
            from ModuleFolders.Service.GameProject.BuildService import BuildService
            self.assertTrue(BuildService.verify(built['output_path'])['passed'])
        for rel,digest in before.items():self.assertEqual(file_hash(self.root/rel),digest)
        for path,digest in upstream_hashes.items():self.assertEqual(file_hash(path),digest)

    def test_stev_actual_memory_writer(self):self.check_items('stev')
    def test_rpgmtl_local_ids_keep_duplicate_translations(self):self.check_items('rpgmtl')
    def test_sextractor_actual_control_sidecar_writer(self):self.check_items('sextractor')

    def check_map(self,backend):
        upstream=BACKENDS[backend]
        if not upstream.is_dir():self.skipTest('Optional RPGMTL source is not installed')
        path=self.root/'data/Map001.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        data['events'][1]['pages'][0]['list'].insert(-1,{'code':357,'indent':0,
            'parameters':['SyntheticMsg','show','表示',{'text':'案内です','resource':'内部ID'}]})
        self.write('Map001',data)
        profile={'schema_version':1,'id':'synthetic-357','engine':'rpgmaker-mz','json_rules':[],
            'plugin_commands':[{'plugin':'SyntheticMsg','command':'show','fields':['text'],'evidence_status':'verified'}]}
        project=self.root.parent/(self.root.name+'-map-writer')
        with GameProjectService.create(self.root,project) as service:
            service.extract(profile)
            rows={}
            for unit in service.store.units():
                if unit.source_text=='はい':rows[unit.unit_id]='是' if len(unit.occurrences)>1 else '好的'
                elif unit.source_text=='案内です':rows[unit.unit_id]='这是引导'
            service.import_translations(rows)
            result=generate_candidate(service.store,backend,upstream,'data/Map001.json')
            actual=json.loads(Path(result['candidate']).read_text(encoding='utf-8-sig'))
            commands=actual['events'][1]['pages'][0]['list']
            self.assertEqual(commands[2]['parameters'][0][0],'是')
            self.assertEqual(commands[3]['parameters'][1],'是')
            self.assertEqual(commands[4]['parameters'][0],'好的')
            args=next(c['parameters'][3] for c in commands if c['code']==357)
            self.assertEqual(args,{'text':'这是引导','resource':'内部ID'})

    def test_modified_backend_source_blocks_the_routed_build(self):
        from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
        upstream=self.root.parent/(self.root.name+'-isolated-stev')
        upstream.mkdir()
        (upstream/'jtpp.py').write_bytes((BACKENDS['stev']/'jtpp.py').read_bytes())
        (upstream/'config.yaml').write_bytes((BACKENDS['stev']/'config.yaml').read_bytes())
        project=self.root.parent/(self.root.name+'-pin-project')
        with GameProjectService.create(self.root,project) as service:
            service.extract()
            item=next(u for u in service.store.units() if u.source_text=='回復薬')
            service.import_translations({item.unit_id:'恢复药'})
            configure_route(service.store,'data/Items.json','stev',upstream)
            with (upstream/'jtpp.py').open('ab') as stream:stream.write(b'\n# simulate upstream update\n')
            output=self.root.parent/(self.root.name+'-pin-build')
            with self.assertRaisesRegex(ValueError,'BACKEND_SOURCE_CHANGED'):service.build(output,test=True)
            self.assertEqual(list(output.glob('game-zh-CN-*')),[])

    def test_rpgmtl_mz_choice_and_plugin_arguments(self):self.check_map('rpgmtl')
    def test_stev_mz_choice_and_plugin_arguments(self):self.check_map('stev')
    def test_sextractor_mz_choice_and_plugin_arguments(self):self.check_map('sextractor')
