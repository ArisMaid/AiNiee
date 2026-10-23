"""Independent lexical-scope, byte-locator and source non-execution acceptance."""
import tempfile,unittest
from pathlib import Path
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import _call,extract_js_rules,patch_js

SOURCE='''// 😀前置\r
var Kd={};Kd.words={save:'保存'};
function A(){const args={same:{name:'甲',note:'说明',id:'logic',dynamic:'x'+'y'},['hidden']:'禁止'};
function Nested(){const args={same:{name:'嵌套'}};Kd.words={wrong:'不可取'};}return args;}
function B(){const args={same:{name:'乙',note:'别处'}};return args;}
throw new Error('SOURCE_MUST_NEVER_EXECUTE');
'''


class JsScopeAcceptance(unittest.TestCase):
    def request(self,**changes):
        payload={'operation':'extract','source':SOURCE,'object_path':'args','scope_function':'A','property_fields':['name','note']}
        payload.update(changes);return _call(payload)

    def test_scoped_fields_and_global_scope_do_not_leak(self):
        nodes=self.request()
        self.assertEqual([n['value'] for n in nodes],['甲','说明'])
        self.assertEqual([n['property_path'] for n in nodes],[['same','name'],['same','note']])
        for n in nodes:self.assertEqual(SOURCE.encode()[n['start']:n['end']].decode(),"'"+n['value']+"'")
        other=self.request(scope_function='B');self.assertEqual([n['value'] for n in other],['乙','别处'])
        global_nodes=_call({'operation':'extract','source':SOURCE,'object_path':'Kd.words'})
        self.assertEqual([n['value'] for n in global_nodes],['保存'])

    def test_bad_and_ambiguous_selectors_fail(self):
        for field,value in [('scope_function','A\n'),('scope_function',False),('object_path','args.data'),
                ('property_fields',[]),('property_fields',['name','name']),('property_fields',['name\n'])]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.request(**{field:value})
        for source in ['function A(){var args={name:"甲"};var args={name:"乙"};}',
                'function A(){const args={name:"甲"};} function A(){const args={name:"乙"};}',
                'function A(){if(true){const args={name:"甲"};}}']:
            with self.subTest(source=source),self.assertRaises(ValueError):self.request(source=source)
        with self.assertRaises(ValueError):_call({'operation':'extract','source':'Kd.words={a:"甲"};Kd.words={a:"乙"};','object_path':'Kd.words'})

    def test_bridge_identity_scope_and_ast_patch_integrity(self):
        base=Path(__file__).resolve().parents[2]/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
        root=Path(tempfile.mkdtemp(prefix='js-scope-',dir=base));original=b'\xef\xbb\xbf'+SOURCE.encode()
        (root/'words.js').write_bytes(original)
        rules=[{'id':scope,'file':'words.js','object_path':'args','scope_function':scope,
            'property_fields':['name'],'evidence_status':'verified'} for scope in ['A','B']]
        units,issues,_=extract_js_rules(root,rules)
        self.assertFalse(issues);self.assertEqual(len(units),2);self.assertNotEqual(units[0].unit_id,units[1].unit_id)
        self.assertEqual([u.context['scope_function'] for u in units],['A','B'])
        self.assertEqual(units[0].occurrences[0].locator['scope_function'],'A')
        patched=patch_js(original,[(units[0].occurrences[0],'中文')])
        self.assertTrue(patched.startswith(b'\xef\xbb\xbf'));self.assertIn(b'\r\n',patched)
        text=patched.decode('utf-8-sig')
        for keep in ["name:'乙'","name:'嵌套'","id:'logic'","SOURCE_MUST_NEVER_EXECUTE"]:self.assertIn(keep,text)
        self.assertIn('中文',text)

    def test_legacy_global_member_iife_and_shadowing(self):
        base="var Kd={}; (()=>{Kd.words={save:'保存'};function Uncalled(){Kd.words={bad:'不可取'};}})();"
        result=_call({'operation':'extract','source':base,'object_path':'Kd.words'})
        self.assertEqual([r['value'] for r in result],['保存'])
        for source in ["((Kd)=>{Kd.words={bad:'局所'};})({});",
                "(()=>{let Kd={};Kd.words={bad:'局所'};})();",
                "(()=>{const {Kd}={Kd:{}};Kd.words={bad:'局所'};})();"]:
            with self.subTest(source=source),self.assertRaises(ValueError):
                _call({'operation':'extract','source':source,'object_path':'Kd.words'})


if __name__=='__main__':unittest.main()
