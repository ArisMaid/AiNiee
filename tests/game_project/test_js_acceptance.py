import tempfile
import unittest
from pathlib import Path
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import extract_js_rules,patch_js


class JsAcceptance(unittest.TestCase):
    def test_inherited_node_preload_and_provider_configuration_are_excluded(self):
        import os
        from unittest.mock import patch
        from ModuleFolders.Infrastructure.GameAdapters.JsWorker import JsBridge
        actual=JsBridge.run_json_worker
        with patch.dict(os.environ,{'NODE_OPTIONS':'--not-a-real-node-option',
                'NODE_PATH':'untrusted-module-path','AINIEE_TEST_API_KEY':'test-only-sentinel'}):
            with patch.object(JsBridge,'run_json_worker',wraps=actual) as called:
                nodes=JsBridge._call({'operation':'extract','source':"var Kd={};Kd.words={a:'test'};",'object_path':'Kd.words'})
                self.assertEqual(nodes[0]['value'],'test')
                forwarded=called.call_args.kwargs['env']
                for name in ('NODE_OPTIONS','NODE_PATH','AINIEE_TEST_API_KEY'):
                    self.assertNotIn(name,forwarded)

    def test_unicode_offsets_and_nontext_structure(self):
        root=Path(__file__).resolve().parents[2]/'work/acceptance'
        root.mkdir(parents=True,exist_ok=True)
        root=Path(tempfile.mkdtemp(prefix='js-',dir=root))
        data=b'\xef\xbb\xbf'+"// 😀前置\r\nvar Kd={}; Kd.words={save:'保存', yes:'はい'}; var logic='保持';\r\n".encode('utf-8')
        (root/'words.js').write_bytes(data)
        units,issues,_=extract_js_rules(root,[{'id':'words','file':'words.js',
            'object_path':'Kd.words','evidence_status':'verified'}])
        self.assertFalse(issues)
        self.assertEqual(len(units),2)
        u=next(u for u in units if u.source_text=='保存')
        patched=patch_js(data,[(u.occurrences[0],'存档')])
        self.assertIn('存档',patched.decode('utf-8-sig'))
        self.assertIn("logic='保持'",patched.decode('utf-8-sig'))
        self.assertTrue(patched.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'\r\n',patched)
        with self.assertRaises(ValueError):patch_js(patched,[(u.occurrences[0],'覆盖')])


if __name__=='__main__':unittest.main()
