"""Profile-approved event expressions retain code and raw-source ownership."""
import json,unittest
from pathlib import Path
import test_adapter_acceptance as fixtures
from ModuleFolders.Domain.GameProject.Models import hash_text
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import patch_json,compile_json_changes,semantic_differences
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import validate_profile
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService


class EventLiteralAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def profile(self):
        return {'schema_version':3,'id':'event-expression','engine':'rpgmaker-mz',
            'required_features':['event_js_string_v1','display_value_constraints_v1'],
            'event_literals':[{'id':'search','file':'data/CommonEvents.json','scene_ids':['common_event:1'],
                'variable_id':1938,'role':'display_keyword','kind':'menu','codec':'event-js-json-string-v1',
                'preserve_js_zero':True,'evidence_status':'verified'}]}

    def source(self):
        raw=' \t"\\u65e5\\u672c"\r\n'
        def command(values):return {'code':122,'indent':0,'parameters':values}
        data=[None,{'id':1,'name':'editor','list':[command([1938,1938,0,4,raw]),command([1938,1938,0,4,'"0"']),
            command([1938,1938,1,4,'"加算"']),command([1938,1939,0,4,'"複数"']),
            command([1937,1937,0,4,'"別変数"']),command([1938,1938,0,4,'"text" + call()'])]},
            {'id':2,'name':'other scene','list':[command([1938,1938,0,4,'"別場面"'])]}]
        original=b'\xef\xbb\xbf'+(json.dumps(data,ensure_ascii=False,indent=2)+'\n').replace('\n','\r\n').encode()
        (self.root/'data/CommonEvents.json').write_bytes(original)
        return raw,original,data

    def test_logical_source_raw_noop_and_encoded_native_build(self):
        raw,original,before=self.source()
        project=self.root.parent/(self.root.name+'-event-literal')
        with GameProjectService.create(self.root,project) as service:
            service.extract(self.profile())
            units=[u for u in service.store.units() if any(o.locator.get('value_codec') for o in u.occurrences)]
            self.assertEqual([u.source_text for u in units],['日本','0'])
            unit,zero=units;occurrence=unit.occurrences[0]
            self.assertEqual(occurrence.expected_value_hash,hash_text(raw));self.assertEqual(unit.source_hash,hash_text('日本'))
            self.assertEqual(patch_json(original,[(occurrence,'日本')]),original)
            self.assertEqual(compile_json_changes(original,[(occurrence,'日本')]),[])
            self.assertIn('event_js_string_v1',service.store.metadata()['required_features'])
            self.assertTrue(any(i['code']=='EVENT_LITERAL_UNSUPPORTED' for i in service.store.issues()))
            target='中文";globalThis.pwned=1;//\n\u2028'
            self.assertEqual(service.import_translations({unit.unit_id:target})[0].status,'accepted')
            self.assertEqual(service.import_translations({zero.unit_id:'零'})[0].status,'rejected')
            self.assertEqual(service.import_translations({zero.unit_id:''})[0].status,'rejected')
            compiled=compile_json_changes(original,[(occurrence,target)])
            self.assertEqual(compiled[0]['source_text'],raw);self.assertEqual(json.loads(compiled[0]['text']),target)
            build=service.build(self.root.parent/(self.root.name+'-event-output'),test=True)
            after=json.loads((Path(build['output_path'])/'data/CommonEvents.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(json.loads(after[1]['list'][0]['parameters'][4]),target)
            self.assertEqual(semantic_differences(before,after),{'/1/list/0/parameters/4'})
            self.assertEqual((self.root/'data/CommonEvents.json').read_bytes(),original)

    def test_profile_feature_gate_and_duplicate_address_reject(self):
        raw,original,_=self.source()
        for change in [{'schema_version':2},{'required_features':[]},{'required_features':['future_feature']}]:
            profile=dict(self.profile(),**change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_profile(profile)
        profile=self.profile();profile['event_literals'][0]['variable_id']=True
        with self.assertRaises(ValueError):validate_profile(profile)
        profile=self.profile();profile['json_rules']=[{'id':'overlap','file':'data/CommonEvents.json',
            'selector':'/1/list/0/parameters/4','role':'dialogue','evidence_status':'verified'}]
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-event-conflict')) as service:
            service.extract();before=service.store.metadata();old=[u.to_dict() for u in service.store.units()]
            with self.assertRaisesRegex(ValueError,'EXTRACTION_WRITE_CONFLICT'):service.extract(profile)
            self.assertEqual(service.store.metadata(),before);self.assertEqual([u.to_dict() for u in service.store.units()],old)
            self.assertEqual((self.root/'data/CommonEvents.json').read_bytes(),original)

    def test_scoped_note_line_guard_and_profile_capability_declaration(self):
        script="function Notes(){const args={place:{name:'地名',note:'第一行\\n第二行'}};return args;}"
        (self.root/'js/notes.js').write_text(script,encoding='utf-8')
        profile={'schema_version':3,'id':'notes','engine':'rpgmaker-mz',
            'required_features':['js_scoped_object_v1','display_line_count_v1','display_value_constraints_v1'],
            'js_rules':[{'id':'notes','file':'js/notes.js','scope_function':'Notes','object_path':'args',
                'property_fields':['name','note'],'preserve_newlines':True,'evidence_status':'verified'}]}
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-note-lines')) as service:
            service.extract(profile)
            note=next(u for u in service.store.units() if u.source_text=='第一行\n第二行')
            self.assertEqual(service.import_translations({note.unit_id:'第一行\n第二行\n新增行'})[0].status,'rejected')
            self.assertEqual(service.import_translations({note.unit_id:'中文一行\n中文二行'})[0].status,'accepted')
            self.assertIn('display_line_count_v1',service.store.metadata()['required_features'])
        bad=dict(profile,required_features=['js_scoped_object_v1'])
        with self.assertRaisesRegex(ValueError,'omits active capabilities'):validate_profile(bad)

    def test_format2_capability_increase_keeps_pre_change_database(self):
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-capability-backup')) as service:
            service.extract();before=service.store.metadata();old=[u.to_dict() for u in service.store.units()]
            service.store.replace_units(service.store.units(),extraction_metadata={'profile_features':['event_js_string_v1']})
            backups=list((service.store.root/'migrations/capabilities-v2').glob('*/project.sqlite3'))
            self.assertEqual(len(backups),1)
            with ProjectStore(backups[0].parent,readonly=True) as backup:
                self.assertEqual(backup.metadata(),before);self.assertEqual([u.to_dict() for u in backup.units()],old)
            service.store.replace_units(service.store.units(),extraction_metadata={'profile_features':['event_js_string_v1']})
            self.assertEqual(len(list((service.store.root/'migrations/capabilities-v2').glob('*/project.sqlite3'))),1)


if __name__=='__main__':unittest.main()
