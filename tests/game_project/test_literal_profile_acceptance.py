"""Codex-owned tests for audited literals, sentinels and atomic extraction."""
import json
import unittest
from unittest.mock import patch
from pathlib import Path
import test_adapter_acceptance as fixtures
from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
from ModuleFolders.Domain.GameProject.Models import TranslationUnit
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.TranslationCommitter import TranslationCommitter
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import validate_profile


class LiteralProfileAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_explicit_literals_roundtrip_order_and_injection(self):
        self.assertEqual(TokenPolicy().scan('[word]')[0],())
        policy=TokenPolicy(literal_tokens=['[word]','[self]'])
        source=r'[self]日本[word]\V[1]en(v[2]>0)[word]'
        protected=policy.protect(source)
        self.assertFalse(protected.issues)
        self.assertEqual([t.command for t in protected.tokens],['literal','literal','V','choice_condition','literal'])
        self.assertEqual(protected.restore(protected.text)[0],source)
        self.assertFalse(protected.restore(protected.text)[1])
        self.assertFalse(policy.validate(source,source.replace('日本','中文')))
        for changed in [source.replace('[word]','',1),source.replace('[word]','[Word]',1),
                source.replace('[self]','[word]',1),source+'[word]']:
            with self.subTest(changed=changed):self.assertTrue(policy.validate(source,changed))
        prepared=policy.protect('日本[word]')
        for changed in [prepared.text+'[word]',prepared.text+'[self]',prepared.text.replace(prepared.markers[0],'')]:
            with self.subTest(changed=changed):self.assertTrue(prepared.restore(changed)[1])
        for bad in [None,'[word]',[True],[''],['[word]','[word]'],['[a b]'],['[x]\\V[1]'],['[x]\n']]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):TokenPolicy(literal_tokens=bad)

    def profile(self):
        return {'schema_version':2,'id':'literal-test','engine':'rpgmaker-mz','token_literals':['[word]'],
            'json_rules':[{'id':'messages','file':'data/RandomTalk.json','selector':'/*/message','role':'dialogue',
                'evidence_status':'verified','exclude_values':['[なし]'],'exclude_contains':['[stamp]']}]}

    def test_profile_exclusion_and_committer_preserve_markers(self):
        self.write('RandomTalk',[None,{'message':'日本[word]','tag':'logic'},{'message':'[なし]'},
            {'message':'[stamp]file_name'},{'message':'通常'}])
        project=self.root.parent/(self.root.name+'-literals')
        with GameProjectService.create(self.root,project) as service:
            summary=service.extract(self.profile())
            self.assertEqual(summary['stats']['profile_excluded_count'],2)
            self.assertEqual(service.store.metadata()['token_literals'],['[word]'])
            unit=next(u for u in service.store.units() if u.source_text=='日本[word]')
            self.assertEqual(unit.token_policy_id,'rpgmaker-v3')
            self.assertEqual(service.import_translations({unit.unit_id:'中文[word]'})[0].status,'accepted')
            self.assertEqual(service.import_translations({unit.unit_id:'中文[词]'})[0].status,'rejected')
            plain=next(u for u in service.store.units() if u.source_text=='通常')
            for text in ('[なし]','[stamp]another_file'):
                self.assertEqual(service.import_translations({plain.unit_id:text})[0].status,'rejected')
            self.assertEqual(service.store.translation(unit.unit_id)['text'],'中文[word]')
            excluded={u.source_text for u in service.store.units()}
            self.assertNotIn('[なし]',excluded);self.assertNotIn('[stamp]file_name',excluded);self.assertNotIn('logic',excluded)
            build=service.build(self.root.parent/(self.root.name+'-literals-output'),test=True)
            data=json.loads((Path(build['output_path'])/'data/RandomTalk.json').read_text(encoding='utf-8'))
            self.assertEqual(data[1]['message'],'中文[word]');self.assertEqual(data[2]['message'],'[なし]')
            self.assertEqual(data[3]['message'],'[stamp]file_name');self.assertEqual(data[1]['tag'],'logic')

    def test_atomic_policy_and_units_reject_bad_metadata_before_mutation(self):
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-atomic')) as service:
            service.extract();store=service.store;before=store.metadata();ids=[u.unit_id for u in store.units()]
            from dataclasses import replace
            replacement=replace(store.units()[0],unit_id='new')
            with self.assertRaises(ValueError):store.replace_units([replacement],extraction_metadata={'profile_hash':float('nan')})
            self.assertEqual(store.metadata(),before);self.assertEqual([u.unit_id for u in store.units()],ids)
            with self.assertRaises(ValueError):store.replace_units([replacement],extraction_metadata={'token_literals':['bad']})
            self.assertEqual(store.metadata(),before);self.assertEqual([u.unit_id for u in store.units()],ids)
            import importlib
            module=importlib.import_module('ModuleFolders.Service.GameProject.ProjectStore')
            actual=module._write_metadata_value
            def fail(connection,key,value):
                if key=='token_literals':raise OSError('injected policy write failure')
                return actual(connection,key,value)
            with patch.object(module,'_write_metadata_value',side_effect=fail):
                with self.assertRaisesRegex(OSError,'injected policy write failure'):
                    store.replace_units([replacement],extraction_metadata={'token_literals':['[word]']})
            self.assertEqual(store.metadata(),before);self.assertEqual([u.unit_id for u in store.units()],ids)

    def test_profile_bad_filters_and_captured_source_tampering_are_rejected(self):
        for field,value in [('exclude_values','[なし]'),('exclude_contains',[False]),('exclude_values',['x','x'])]:
            profile=self.profile();profile['json_rules'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):validate_profile(profile)
        profile=self.profile();profile['schema_version']=True
        with self.assertRaises(ValueError):validate_profile(profile)
        profile=self.profile();profile['schema_version']=1
        with self.assertRaisesRegex(ValueError,'require profile schema_version 2'):validate_profile(profile)
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-capture-guard')) as service:
            service.extract();old=[u.unit_id for u in service.store.units()]
            captured=service.store.root/'source/data/Items.json';captured.write_text('[null]',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'SNAPSHOT_HASH_MISMATCH'):service.extract(self.profile())
            self.assertEqual([u.unit_id for u in service.store.units()],old)

    def test_zero_guard_matches_actual_node_conversion(self):
        from ModuleFolders.Domain.GameProject.ValueConstraints import js_string_is_zero
        import subprocess,shutil
        examples=['',' ','0','-0','+0.0','0e12','1e-9999','0x00','0b00','0o00','-0x0','0_0',
            '0n','０','NaN','Infinity','word','\u00a00\ufeff','\u00850','\u180e0','\u30000','2.5e-324','2.4e-324']
        node=shutil.which('node')
        if not node:self.skipTest('Node runtime unavailable')
        script='let s="";process.stdin.on("data",x=>s+=x);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(v=>Number(v)===0))));'
        result=subprocess.run([node,'-e',script],input=json.dumps(examples).encode(),capture_output=True,check=True,timeout=10)
        self.assertEqual([js_string_is_zero(v) for v in examples],json.loads(result.stdout))
        profile=self.profile();profile['json_rules'][0]['preserve_js_zero']=True
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-value-guard')) as service:
            service.extract(profile)
            unit=next(u for u in service.store.units() if u.source_text=='元気ですか')
            self.assertEqual(service.import_translations({unit.unit_id:'测试'})[0].status,'accepted')
            self.assertEqual(service.import_translations({unit.unit_id:'0e10'})[0].status,'rejected')


if __name__=='__main__':unittest.main()
