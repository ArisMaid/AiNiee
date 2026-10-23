import copy
import json
import os
from pathlib import Path
import unittest

import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.TranslatorPlusPlusBridge import (
    CONTEXT_PREFIX, FILE_ID, export_exchange, import_exchange, load_binding)
from ModuleFolders.Service.GameProject.BuildService import file_hash


class TranslatorPlusPlusAcceptance(unittest.TestCase):
    setUp = fixtures.AdapterAcceptance.setUp
    write = fixtures.AdapterAcceptance.write

    def project(self):
        return GameProjectService.create(self.root,self.root.parent/(self.root.name+'-tpp-project'))

    def test_id_context_and_source_guard(self):
        with self.project() as service:
            service.extract()
            exported=export_exchange(service.store)
            snapshot=json.loads(Path(exported['file']).read_text(encoding='utf-8'))
            binding=load_binding(service.store,exported['binding_id'])
            table=snapshot['project']['files'][FILE_ID]
            pair=[(fid,i) for fid,t in snapshot['project']['files'].items() for i,row in enumerate(t['data']) if row[0]=='はい']
            self.assertEqual(len(pair),2)
            for (fid,i),text in zip(pair,['是','好的']):snapshot['project']['files'][fid]['data'][i][1]=text
            # Row positions are not an identity. Reorder both rows and contexts.
            table['data'].reverse();table['context'].reverse()
            result=import_exchange(service.store,exported['binding_id'],snapshot)
            self.assertEqual(result['accepted'],2)
            self.assertEqual({service.store.translation(r['unit_id'])['text'] for r in binding['rows']
                if r['source_text']=='はい'},{'是','好的'})
            tampered=copy.deepcopy(snapshot)
            tampered['project']['files'][FILE_ID]['data'][0][0]+=' changed'
            before=len(service.store.edits())
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
                import_exchange(service.store,exported['binding_id'],tampered)
            self.assertEqual(len(service.store.edits()),before)

    def test_revision_lock_and_control_validation(self):
        with self.project() as service:
            service.extract()
            exported=export_exchange(service.store)
            snapshot=json.loads(Path(exported['file']).read_text(encoding='utf-8'))
            table=snapshot['project']['files'][FILE_ID]
            by_source={r[0]:i for i,r in enumerate(table['data'])}
            unit=next(u for u in service.store.units() if u.source_text=='学校')
            service.import_translations({unit.unit_id:'学校（人工修改）'})
            table['data'][by_source['学校']][1]='学院'
            table['data'][by_source[r'\N[1]こんにちは']][1]='你好'
            results=import_exchange(service.store,exported['binding_id'],snapshot)['results']
            self.assertEqual({r['status'] for r in results},{'conflict','rejected'})
            self.assertEqual(service.store.translation(unit.unit_id)['text'],'学校（人工修改）')
            # The immutable binding is registered in SQLite, not trusted from disk.
            binding=Path(exported['binding_path'])
            binding.write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'BINDING_CHANGED'):
                load_binding(service.store,exported['binding_id'])

    @unittest.skipUnless(os.environ.get('AINIEE_TEST_TRANSLATORPP')=='1','Optional installed official Translator++ integration')
    def test_installed_exchange_and_native_engine_roundtrip(self):
        from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import TranslatorPlusPlusClient
        from ModuleFolders.Service.GameProject.TranslatorPlusPlusBridge import open_exchange,pull_exchange
        client=TranslatorPlusPlusClient()
        self.assertEqual(client.probe()['version'],'8.8.9')
        (self.root/'js/plugins.js').write_text('var $plugins = [];',encoding='utf-8')
        original={p.relative_to(self.root).as_posix():file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        with self.project() as service:
            service.extract()
            exported=export_exchange(service.store)
            open_exchange(service.store,exported['binding_id'],client)
            snapshot=client.snapshot(exported['exchange_project_id'])
            pair=[(fid,i) for fid,t in snapshot['project']['files'].items() for i,row in enumerate(t['data']) if row[0]=='はい']
            self.assertEqual(len(pair),2)
            attack='中文"); throw new Error("must stay text"); //'
            client.write_translation(pair[0][0],pair[0][1],attack,exported['exchange_project_id'])
            self.assertEqual(client.snapshot(exported['exchange_project_id'])['project']['files'][pair[0][0]]['data'][pair[0][1]][1],attack)
            for (file_id,row),text in zip(pair,['是','好的']):
                client.write_translation(file_id,row,text,exported['exchange_project_id'])
            self.assertEqual(pull_exchange(service.store,exported['binding_id'],client)['accepted'],2)
        # A distinct upstream-native extraction/export test uses the synthetic copy.
        extracted=client.extract_rpg(self.root/'index.html')
        project_id=extracted['project']['projectId']
        item_table=extracted['project']['files']['data/Items.json']['data']
        row=next(i for i,value in enumerate(item_table) if value[0]=='回復薬')
        client.write_translation('data/Items.json',row,'恢复药',project_id)
        output=self.root.parent/(self.root.name+'-tpp-native-output')
        client.export_rpg(output,project_id)
        actual=json.loads((output/'data/Items.json').read_text(encoding='utf-8'))
        expected=json.loads((self.root/'data/Items.json').read_text(encoding='utf-8'))
        expected[1]['name']='恢复药'
        self.assertEqual(actual,expected)
        # Upstream drops a standalone 401 in this fixture. The candidate must
        # fail the whole-file audit even though the requested Items edit works.
        from ModuleFolders.Service.GameProject.BackendWriteAudit import audit_json_output
        with GameProjectService(self.root.parent/(self.root.name+'-tpp-project')) as service:
            service.import_translations({u.unit_id:u.source_text for u in service.store.units()
                                         if u.source_text=='はい'})
            item=next(u for u in service.store.units() if u.source_text=='回復薬')
            service.import_translations({item.unit_id:'恢复药'})
            audit=audit_json_output(service.store,output)
            self.assertFalse(audit['passed'])
            by_path={row['path']:row for row in audit['files']}
            self.assertTrue(by_path['data/Items.json']['passed'])
            self.assertEqual(by_path['data/Map001.json']['reason'],'UNAPPROVED_SEMANTIC_DIFF')
            (output.parent/(output.name+'-audit.json')).write_text(json.dumps(audit,indent=2),encoding='utf-8')
        for rel,digest in original.items():self.assertEqual(file_hash(self.root/rel),digest)
