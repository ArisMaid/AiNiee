import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ModuleFolders.Domain.GameProject.Models import Occurrence,TranslationUnit,TranslationProposal,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Base.Base import Base


class GameBatchAcceptance(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[2]/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(prefix='batch-',dir=base))
        self.store=ProjectStore.create(self.root/'project',{'project_id':'batch-test',
            'source_root':str(self.root/'source'),'engine':'rpgmaker-mz'})
        self.addCleanup(self.store.close)
        self.units=[TranslationUnit(f'u{i}','menu',text,occurrences=(
            Occurrence(f'o{i}','data/System.json',{'pointer':f'/terms/{i}'},hash_text(text)),))
            for i,text in enumerate(['保存','設定'])]
        self.store.replace_units(self.units)
        self.items=list(build_projection(self.store).items_iter())
        self.config=SimpleNamespace(request_timeout=2,project_terms_data=[],
            get_active_platform_configuration=lambda:{'provider':'test-only'})
        Base.work_status=Base.STATUS.TASKING

    def test_response_order_is_not_identity(self):
        class Requester:
            def sent_request(self,*_):return False,'',json.dumps({'u1':'设置','u0':'存档'}),12,8
        result=GameBatchRunner(self.items,self.config).run(Requester())
        self.assertTrue(result['check_result'])
        self.assertEqual(self.store.translation('u0')['text'],'存档')
        self.assertEqual(self.store.translation('u1')['text'],'设置')

    def test_duplicate_response_id_is_rejected(self):
        class Requester:
            def sent_request(self,*_):return False,'','{"u0":"一","u0":"二","u1":"三"}',1,1
        with self.assertRaises(ValueError):GameBatchRunner(self.items,self.config).run(Requester())
        self.assertIsNone(self.store.translation('u0'))

    def test_cancelled_late_response_is_audit_only(self):
        from ModuleFolders.Service.GameProject.JobControl import request_action
        store=self.store
        class Requester:
            def sent_request(self,*_):
                request_action(store,store.jobs()[-1]['job_id'],'cancel')
                return False,'',json.dumps({'u0':'迟到结果','u1':'设置'}),1,1
        result=GameBatchRunner(self.items,self.config).run(Requester())
        self.assertTrue(result['cancelled'])
        self.assertIsNone(store.translation('u0'))
        self.assertEqual(store.jobs()[-1]['run_state'],'CANCELLED')
        self.assertIn('response_text',store.jobs()[-1]['result'])

    def test_late_response_does_not_override_edit(self):
        store=self.store
        class Requester:
            def sent_request(self,*_):
                store.commit(TranslationProposal('u0','人工',hash_text('保存')))
                return False,'',json.dumps({'u0':'旧结果','u1':'设置'}),1,1
        result=GameBatchRunner(self.items,self.config).run(Requester())
        self.assertFalse(result['check_result'])
        self.assertEqual(self.store.translation('u0')['text'],'人工')

    def test_source_change_keeps_monotonic_revision(self):
        self.store.commit(TranslationProposal('u0','存档',hash_text('保存')))
        old_revision=self.store.translation('u0')['revision']
        changed=TranslationUnit('u0','menu','新原文',occurrences=(
            Occurrence('o0','data/System.json',{'pointer':'/terms/0'},hash_text('新原文')),))
        self.store.replace_units([changed,self.units[1]])
        tr=self.store.translation('u0')
        self.assertTrue(tr['stale'])
        self.assertGreater(tr['revision'],old_revision)

    def test_table_translation_uses_game_commit_boundary(self):
        from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
        manager=SimpleNamespace(project=build_projection(self.store))
        executor=SimpleExecutor(cache_manager=manager)
        class Requester:
            def sent_request(self,*_):return False,'',json.dumps({'u0':'存档','u1':'设置'}),1,1
        rows=[{'text_index':item.text_index} for item in manager.project.items_iter()]
        result=executor._process_game_table({'file_path':'data/System.json','items_to_translate':rows},
            'translate',config=self.config,requester=Requester())
        self.assertEqual(result['row_count'],2)
        self.assertEqual(self.store.translation('u0')['text'],'存档')
        executor._cleanup_event_subscriptions()

    def test_stale_ui_notification_cannot_write_translation(self):
        from ModuleFolders.Service.GameProject.CacheBridge import sync_generated_cache
        self.store.commit(TranslationProposal('u0','人工新稿',hash_text('保存')))
        manager=SimpleNamespace(project=build_projection(self.store))
        item=next(i for i in manager.project.items_iter() if i.get_extra('unit_id')=='u0')
        self.assertFalse(sync_generated_cache(manager,'data/System.json',item.text_index,'迟到旧稿'))
        self.assertEqual(item.translated_text,'人工新稿')
        self.assertEqual(self.store.translation('u0')['text'],'人工新稿')

    def test_actual_opencc_keeps_controls_and_commits_to_sqlite(self):
        from ModuleFolders.Service.TaskExecutor.TaskExecutor import TaskExecutor
        source=r'\N[1]設定'
        unit=TranslationUnit('u0','menu',source,occurrences=(
            Occurrence('o0','data/System.json',{'pointer':'/terms/0'},hash_text(source)),))
        self.store.replace_units([unit,self.units[1]])
        self.store.commit(TranslationProposal('u0',r'\N[1]繁體遊戲',unit.source_hash))
        manager=SimpleNamespace(project=build_projection(self.store))
        host=SimpleNamespace(cache_manager=manager,print=lambda *args:None,
                             info=lambda *args:None,error=lambda *args:None)
        self.assertTrue(TaskExecutor._convert_translated_text_with_opencc(host,'t2s'))
        self.assertEqual(self.store.translation('u0')['text'],r'\N[1]繁体游戏')
        self.assertEqual(self.store.translation('u0')['origin'],'opencc')


if __name__=='__main__':unittest.main()
