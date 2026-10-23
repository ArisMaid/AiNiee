"""Codex-owned font alias/configuration integration and interrupted build proof."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Service.GameProject import FontService


class FontBuildAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_alias_finalization_failure_resume_and_published_integrity(self):
        font=Path(r'C:\Windows\Fonts\simhei.ttf')
        if not font.exists():self.skipTest('Local Windows font unavailable')
        before=(self.root/'index.html').read_bytes()
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-font-alias')) as service:
            service.extract({'schema_version':2,'id':'font','engine':'rpgmaker-mz','font_aliases':['HSJP-Regular']})
            configured=service.configure_font(font)
            self.assertEqual(configured['settings']['aliases'],['HSJP-Regular'])
            self.assertIn('font_aliases_v1',service.store.metadata()['required_features'])
            actual=FontService.install_aliases
            def fail(*args,**kwargs):actual(*args,**kwargs);raise OSError('injected after alias finalization')
            with patch.object(FontService,'install_aliases',side_effect=fail):
                with self.assertRaisesRegex(OSError,'injected after alias'):
                    service.build(self.root.parent/(self.root.name+'-font-build'),test=True,runtime_capture=True)
            failed=next(j for j in reversed(service.store.jobs()) if j['operation']=='BUILD')
            self.assertEqual(failed['run_state'],'FAILED')
            markers=service.store.root/'builds'/failed['result']['build_id']/'atomic-writes'
            registered={json.loads(path.read_text(encoding='utf-8'))['target'] for path in markers.glob('*.json')}
            self.assertTrue({'fonts/AiNiee-Simplified.ttf','data/System.json',FontService.ALIAS_SCRIPT,'index.html'}<=registered)
            build=service.resume_build(failed['result']['build_id']);output=Path(build['output_path'])
            self.assertTrue(BuildService.verify(output)['passed'])
            self.assertEqual((output/'index.html').read_bytes(),before+FontService.ALIAS_TAG+
                b'\n<script src="js/AiNieeCapture.js"></script>\n')
            self.assertEqual(file_hash(output/'fonts/AiNiee-Simplified.ttf'),file_hash(font))
            self.assertEqual((self.root/'index.html').read_bytes(),before)
            self.assertTrue(service.resume_build(build['build_id'])['recovery_adopted'])
            # A forged file-hash record still cannot authorize different runtime code.
            script=output/FontService.ALIAS_SCRIPT;script.write_bytes(b'// altered runtime')
            path=output/'rpg-build-manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'))
            next(r for r in manifest['files'] if r['path']==FontService.ALIAS_SCRIPT)['output_sha256']=file_hash(script)
            path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            self.assertTrue(BuildService.verify(output)['passed'])
            with self.assertRaisesRegex(ValueError,'BUILD_PUBLISHED_FONT_ALIAS_CHANGED'):service.resume_build(build['build_id'])

    def test_profile_and_settings_reject_unsafe_aliases_before_mutation(self):
        from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import validate_profile
        with self.assertRaisesRegex(ValueError,'FONT_ALIASES_REQUIRE_MZ'):
            validate_profile({'schema_version':2,'id':'font','engine':'rpgmaker-mv','font_aliases':['HSJP-Regular']})
        for version,aliases in [(1,['HSJP-Regular']),(2,['a,b']),(2,['x','x'])]:
            with self.subTest(version=version,aliases=aliases),self.assertRaises(ValueError):
                validate_profile({'schema_version':version,'id':'font','engine':'rpgmaker-mz','font_aliases':aliases})
        with GameProjectService.create(self.root,self.root.parent/(self.root.name+'-font-guard')) as service:
            before=service.store.metadata()
            for changes in [{'font_aliases':['a,b']},{'font_settings':{'aliases':['HSJP-Regular'],'output_file':'../font.ttf'}}]:
                with self.subTest(changes=changes),self.assertRaises(ValueError):service.store.update_metadata(changes)
            self.assertEqual(service.store.metadata(),before)


if __name__=='__main__':unittest.main()
