import json
from pathlib import Path
import unittest
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService, file_hash
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.EventRules import iter_event_texts


class PipelineAcceptance(unittest.TestCase):
    setUp = fixtures.AdapterAcceptance.setUp
    write = fixtures.AdapterAcceptance.write
    def test_copy_build_and_source_change_rejection(self):
        base = self.root.parent
        project = base / (self.root.name + '-project')
        output = base / (self.root.name + '-output')
        originals = {str(p.relative_to(self.root)): file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        with GameProjectService.create(self.root, project) as service:
            service.extract()
            unit = next(u for u in service.store.units() if u.source_text == '学校')
            result = service.import_translations({unit.unit_id: '学校（测试）'})
            self.assertEqual(result[0].status, 'accepted')
            with self.assertRaisesRegex(ValueError, 'UNTRANSLATED_UNITS'):
                service.build(output)
            build = service.build(output, test=True)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            self.assertEqual(build['runtime_validation'], 'not_run')
            changed = [r['path'] for r in build['files'] if r['output_sha256'] != r['original_sha256']]
            self.assertEqual(changed, ['data/Map001.json'])
            for rel, digest in originals.items(): self.assertEqual(file_hash(self.root/rel), digest)
            (self.root/'index.html').write_text('changed after scan', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
                service.build(output, test=True)

    def test_nested_choices_and_blank_speaker(self):
        def c(code, params, indent=0): return {'code':code,'parameters':params,'indent':indent}
        cmds=[c(101,['',0,0,2,'先生']), c(401,['一']),
              c(102,[['外部'],0,0,2,0]), c(402,[0,'旧的外部标签']),
              c(102,[['内部'],0,0,2,0],1), c(402,[0,'内部'],1), c(404,[],1),
              c(404,[]), c(101,['',0,0,2,'']), c(401,['二'])]
        texts=iter_event_texts(cmds,'/list')
        outer=[t for t in texts if t.group=='choice:/list/2/parameters/0/0']
        inner=[t for t in texts if t.group=='choice:/list/4/parameters/0/0']
        self.assertEqual([t.text for t in outer],['外部','旧的外部标签'])
        self.assertEqual([t.text for t in inner],['内部','内部'])
        self.assertEqual(next(t for t in texts if t.text=='二').speaker,'')

    def test_new_source_file_after_scan_is_not_silently_omitted(self):
        project=self.root.parent/(self.root.name+'-file-set-project')
        with GameProjectService.create(self.root,project) as service:
            service.extract()
            (self.root/'new-asset.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'SOURCE_FILE_SET_CHANGED'):
                service.build(self.root.parent/(self.root.name+'-file-set-output'),test=True)

    def test_nested_system_terms(self):
        from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonExtractor import extract_game
        self.write('System', {'terms':{'basic':['等级'], 'commands':['战斗'],
                                     'messages':{'actionFailure':'%1失敗'}}})
        texts={u.source_text for u in extract_game(self.root).units}
        self.assertTrue({'等级','战斗','%1失敗'} <= texts)

    def test_runtime_capture_is_explicit_and_manifested(self):
        project=self.root.parent/(self.root.name+'-capture-project')
        output=self.root.parent/(self.root.name+'-capture-output')
        with GameProjectService.create(self.root,project) as service:
            service.extract()
            with self.assertRaisesRegex(ValueError,'RUNTIME_CAPTURE_REQUIRES_TEST_BUILD'):
                service.build(output,runtime_capture=True)
            build=service.build(output,test=True,runtime_capture=True)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            self.assertIn('js/AiNieeCapture.js',{r['path'] for r in build['files']})
            self.assertNotIn('AiNieeCapture',(self.root/'index.html').read_text(encoding='utf-8'))

    def test_font_override_changes_output_only(self):
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        project=self.root.parent/(self.root.name+'-font-project')
        output=self.root.parent/(self.root.name+'-font-output')
        with GameProjectService.create(self.root,project) as service:
            service.extract()
            chars=set('汉化'+''.join(u.source_text for u in service.store.units()))
            names={ord(c):'u'+str(ord(c)) for c in chars}
            order=['.notdef',*names.values()]
            fb=FontBuilder(1024,isTTF=True);fb.setupGlyphOrder(order);fb.setupCharacterMap(names)
            glyph=TTGlyphPen(None).glyph();fb.setupGlyf({n:glyph for n in order})
            fb.setupHorizontalMetrics({n:(600,0) for n in order});fb.setupHorizontalHeader(ascent=800,descent=-200)
            fb.setupNameTable({'familyName':'Fixture','styleName':'Regular'});fb.setupOS2();fb.setupPost();fb.setupMaxp()
            font=self.root.parent/(self.root.name+'.ttf');fb.save(font)
            service.configure_font(font)
            build=service.build(output,test=True)
            system=json.loads((Path(build['output_path'])/'data/System.json').read_text(encoding='utf-8'))
            self.assertEqual(system['advanced']['mainFontFilename'],'AiNiee-Simplified.ttf')
            self.assertTrue(build['font_validation']['passed'])
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            original_system=json.loads((self.root/'data/System.json').read_text(encoding='utf-8'))
            self.assertNotIn('mainFontFilename',original_system['advanced'])
