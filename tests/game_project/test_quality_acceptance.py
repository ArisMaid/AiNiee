import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication
_APP=QApplication.instance() or QApplication([])
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from ModuleFolders.Domain.GameProject.Models import TranslationUnit, Occurrence, TranslationProposal, hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.MigrationService import plan_migration, apply_migration
from ModuleFolders.Service.GameProject.FontInspector import inspect_font, measure_layout


class QualityAcceptance(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[2]/'work/acceptance'
        self.root=Path(tempfile.mkdtemp(prefix='quality-',dir=base))

    def stores(self):
        stores=[]
        for name in ('old','new'):
            s=ProjectStore.create(self.root/name,{'project_id':name,'engine':'rpgmaker-mz','game_id':'42',
                'source_root':str(self.root/(name+'-source'))})
            self.addCleanup(s.close);stores.append(s)
        u=TranslationUnit('one','menu','保存',occurrences=(Occurrence('o','data/System.json',
            {'pointer':'/terms/save'},hash_text('保存')),))
        stores[0].replace_units([u]);stores[1].replace_units([replace(u,unit_id='two')])
        stores[0].commit(TranslationProposal('one','存档',u.source_hash))
        return stores

    def test_migration_revalidates_stale_plan(self):
        a,b=self.stores();plan=plan_migration(a,b)
        self.assertEqual(len(plan['matches']),1)
        b.commit(TranslationProposal('two','人工修改',b.unit('two').source_hash))
        with self.assertRaisesRegex(ValueError,'MIGRATION_PLAN_STALE'):apply_migration(a,b,plan)
        self.assertEqual(b.translation('two')['text'],'人工修改')

    def test_migration_different_id_and_ambiguous_locator(self):
        a,b=self.stores();plan=plan_migration(a,b)
        self.assertEqual(apply_migration(a,b,plan)[0].status,'accepted')
        self.assertEqual(b.translation('two')['text'],'存档')
        moved=replace(b.unit('two'),unit_id='moved',occurrences=(Occurrence('new-o','data/System.json',
            {'pointer':'/terms/other'},hash_text('保存')),))
        b.replace_units([moved]);p=plan_migration(a,b)
        self.assertEqual(p['matches'],[])
        self.assertEqual(p['review'][0]['reason'],'SOURCE_TEXT_AT_DIFFERENT_LOCATOR')

    def test_font_and_layout_evidence(self):
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        fb=FontBuilder(1024,isTTF=True)
        fb.setupGlyphOrder(['.notdef','A']);fb.setupCharacterMap({65:'A'})
        pen=TTGlyphPen(None);glyph=pen.glyph()
        fb.setupGlyf({'.notdef':glyph,'A':glyph})
        fb.setupHorizontalMetrics({'.notdef':(600,0),'A':(600,0)})
        fb.setupHorizontalHeader(ascent=800,descent=-200)
        fb.setupNameTable({'familyName':'Acceptance','styleName':'Regular'})
        fb.setupOS2();fb.setupPost();fb.setupMaxp()
        path=self.root/'tiny.ttf';fb.save(path)
        result=inspect_font(path,['A汉\n\t'])
        self.assertEqual(result['missing_characters'],['汉'])
        self.assertFalse(result['passed'])
        from PyQt5.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
        r=measure_layout('AAAA\nAA',width_px=1,font_family='Arial')
        self.assertTrue(r['overflow']);self.assertEqual(r['line_count'],2)
        self.assertEqual(measure_layout(r'\unknown[1]A',width_px=100,font_family='Arial')['measurement'],
            'unverified-controls')

    def test_gui_editor_rejects_old_revision(self):
        from PyQt5.QtWidgets import QApplication
        from UserInterface.GameProject.GameProjectPage import _GameProjectJob
        from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
        app=QApplication.instance() or QApplication([])
        a,b=self.stores()
        row={'unit_id':'two','source_hash':b.unit('two').source_hash,'expected_revision':0,'text':'旧编辑'}
        b.commit(TranslationProposal('two','新编辑',row['source_hash']))
        with GameProjectService(b.root) as service:
            job=_GameProjectJob('commit_unit',{'row':row,'lock':False})
            with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):job._commit_unit(service)
        self.assertEqual(b.translation('two')['text'],'新编辑')

    def test_legacy_table_slot_restores_rejected_value(self):
        from PyQt5.QtWidgets import QTableWidget,QTableWidgetItem
        from ModuleFolders.Service.Cache.CacheManager import CacheManager
        from ModuleFolders.Service.GameProject.CacheBridge import build_projection,apply_table_edit
        from types import SimpleNamespace
        a,b=self.stores();manager=CacheManager();manager.project=build_projection(b)
        item=next(manager.project.items_iter());table=QTableWidget(1,1)
        cell=QTableWidgetItem(r'\N[2]错误');table.setItem(0,0,cell)
        warnings=[]
        page=SimpleNamespace(cache_manager=manager,table=table,warning_toast=lambda *args:warnings.append(args))
        self.assertFalse(apply_table_edit(page,cell,'data/System.json',item.text_index,'translated_text',cell.text()))
        self.assertEqual(cell.text(),'');self.assertTrue(warnings)
        self.assertIsNone(b.translation('two'))
        manager._cleanup_event_subscriptions()
