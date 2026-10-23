import json
import os
from pathlib import Path
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication,QDialogButtonBox
from PyQt5.QtCore import QTimer
from UserInterface.GameProject.GameProjectPage import GameProjectPage
from ModuleFolders.Service.GameProject.BuildService import BuildService
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
import test_adapter_acceptance as fixtures

_APP=QApplication.instance() or QApplication([])


class GuiWorkflowAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_command_inventory_entry_and_unsupported_issue_open_readonly_locations(self):
        from unittest.mock import patch
        from UserInterface.GameProject.CommandAuditDialog import CommandAuditDialog
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        project=self.root.parent/(self.root.name+'-command-audit-widgets')
        with GameProjectService.create(self.root,project) as service:service.extract()
        page=GameProjectPage();page.set_project(project);self.wait(page)
        seen=[]
        def inspect(dialog):
            self.assertIsInstance(dialog,CommandAuditDialog)
            self.assertGreater(dialog.model.rowCount(),0)
            self.assertTrue(dialog.details.isReadOnly())
            self.assertIn('/events/1/pages/0/list/7',dialog.details.toPlainText())
            seen.append(dialog.model.rowCount())
            return 0
        with patch.object(CommandAuditDialog,'exec_',inspect):
            page.command_audit_button.click();self.wait(page)
            issue_index=next(i for i,row in enumerate(page._issue_rows) if row['code']=='unsupported_command_candidate')
            page.issue_table.doubleClicked.emit(page.issue_model.index(issue_index,0));self.wait(page)
        self.assertEqual(len(seen),2)
        with ProjectStore(project) as store:
            self.assertEqual([j['run_state'] for j in store.jobs() if j['operation']=='COMMAND_AUDIT'],['COMPLETED','COMPLETED'])
        self.assertIn('指令盘点完成',page.status_label.text())
        page.deleteLater();_APP.processEvents()

    def test_comparison_widgets_publish_reference_report_and_support_cancel(self):
        import threading
        from unittest.mock import patch
        from PyQt5.QtWidgets import QComboBox,QLineEdit
        from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import extract_document
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        project=self.root.parent/(self.root.name+'-compare-widgets')
        backend=Path(__file__).resolve().parents[2]/'StevExtraction'
        with GameProjectService.create(self.root,project) as service:service.extract()
        page=GameProjectPage();page.set_project(project);self.wait(page)
        entered=threading.Event();release=threading.Event()
        def controlled(*args):
            entered.set()
            if not release.wait(5):raise RuntimeError('comparison fixture release timed out')
            return extract_document(*args)
        def choose():
            dialog=_APP.activeModalWidget()
            files,backends=dialog.findChildren(QComboBox)
            files.setCurrentText('data/Items.json');backends.setCurrentIndex(backends.findData('stev'))
            dialog.findChild(QLineEdit).setText(str(backend));dialog.accept()
        with patch('ModuleFolders.Service.GameProject.BackendComparisonService.extract_document',side_effect=controlled):
            QTimer.singleShot(30,choose);page.compare_backend_button.click()
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                _APP.processEvents()
                if entered.is_set() and page.cancel_button.isEnabled():break
                time.sleep(.01)
            try:
                self.assertTrue(entered.is_set());self.assertTrue(page.cancel_button.isEnabled())
                page.cancel_button.click()
                # Allow the separate control worker to persist the request.
                deadline=time.monotonic()+3
                with ProjectStore(project) as store:
                    while store.jobs()[-1]['run_state']!='CANCEL_REQUESTED' and time.monotonic()<deadline:
                        _APP.processEvents();time.sleep(.01)
                release.set();self.wait(page)
            finally:
                release.set()
                if page.is_busy():self.wait(page)
        with ProjectStore(project) as store:
            self.assertEqual(store.jobs()[-1]['operation'],'BACKEND_COMPARE')
            self.assertEqual(store.jobs()[-1]['run_state'],'CANCELLED')
            self.assertEqual(store.metadata().get('backend_routes',{}),{})
        from UserInterface.GameProject.ComparisonReportDialog import ComparisonReportDialog
        reviewed=[]
        def inspect_comparison(dialog):
            self.assertGreater(dialog.model.rowCount(),0)
            self.assertTrue(dialog.details.isReadOnly())
            reviewed.append(True)
            return 0
        with patch.object(ComparisonReportDialog,'exec_',inspect_comparison):
            QTimer.singleShot(30,choose);page.compare_backend_button.click();self.wait(page)
        self.assertEqual(reviewed,[True])
        with ProjectStore(project) as store:
            job=store.jobs()[-1];self.assertEqual(job['run_state'],'COMPLETED')
            self.assertTrue(Path(job['result']['report_path']).is_file())
            self.assertTrue(job['result']['reference_only'])
        self.assertIn('提取比较完成',page.status_label.text())
        page.deleteLater();_APP.processEvents()

    def test_backend_route_worker_forwards_control_identity(self):
        import threading
        from unittest.mock import patch
        from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        project=self.root.parent/(self.root.name+'-route-control')
        backend=Path(__file__).resolve().parents[2]/'StevExtraction'
        with GameProjectService.create(self.root,project) as service:
            service.extract();unit=next(u for u in service.store.units() if u.source_text=='回復薬')
            service.import_translations({unit.unit_id:'恢复药'})
        entered=threading.Event();release=threading.Event()
        def controlled(*args):
            entered.set()
            if not release.wait(5):raise RuntimeError('route fixture release timed out')
            return rewrite_document(*args)
        page=GameProjectPage();page.set_project(project);self.wait(page)
        with patch('ModuleFolders.Service.GameProject.BackendCandidateService.rewrite_document',side_effect=controlled):
            page._start_job('backend_route',{'relative_path':'data/Items.json','backend':'stev','backend_root':str(backend)},refresh_after=True)
            try:
                deadline=time.monotonic()+6
                while time.monotonic()<deadline:
                    _APP.processEvents()
                    if entered.is_set() and page.cancel_button.isEnabled():break
                    time.sleep(.01)
                self.assertTrue(entered.is_set());self.assertTrue(page.cancel_button.isEnabled())
                page.cancel_button.click()
                with ProjectStore(project) as store:
                    deadline=time.monotonic()+3
                    while store.jobs()[-1]['run_state']!='CANCEL_REQUESTED' and time.monotonic()<deadline:
                        _APP.processEvents();time.sleep(.01)
                release.set();self.wait(page)
            finally:
                release.set()
                if page.is_busy():self.wait(page)
        with ProjectStore(project) as store:
            self.assertEqual(store.jobs()[-1]['run_state'],'CANCELLED')
            self.assertEqual(store.metadata().get('backend_routes',{}),{})
        page.deleteLater();_APP.processEvents()

    def test_image_ocr_pause_continue_and_cancel_through_widgets(self):
        import io
        import threading
        from unittest.mock import patch
        from PIL import Image
        from UserInterface.GameProject.ImageWorkflowDialog import ImageWorkflowDialog
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        (self.root/'img').mkdir();buffer=io.BytesIO();Image.new('RGB',(100,60),'white').save(buffer,format='PNG')
        (self.root/'img/text.png').write_bytes(buffer.getvalue())
        project=self.root.parent/(self.root.name+'-ocr-widgets')
        with GameProjectService.create(self.root,project) as service:service.extract()
        def wait_until(predicate):
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                _APP.processEvents()
                if predicate():return
                time.sleep(.01)
            self.fail('OCR widget did not reach expected state')
        with ProjectStore(project) as store:
            for cancel in (False,True):
                entered=threading.Event();release=threading.Event()
                def controlled_ocr(*args):
                    entered.set()
                    if not release.wait(5):raise RuntimeError('OCR fixture release timed out')
                    return {'regions':[]}
                dialog=ImageWorkflowDialog(str(project));dialog.show()
                wait_until(lambda:bool(dialog.items) and dialog.worker is None)
                dialog.regions.setPlainText('manual draft retained on cancel')
                with patch('ModuleFolders.Service.GameProject.ImageCodec.ocr_png',side_effect=controlled_ocr):
                    dialog.run('ocr')
                    try:
                        wait_until(lambda:entered.is_set() and dialog.pause_button.isEnabled())
                        dialog.pause_button.click();release.set()
                        wait_until(lambda:dialog.continue_button.isEnabled())
                        self.assertFalse(dialog.pause_button.isEnabled())
                        self.assertTrue(dialog.cancel_button.isEnabled())
                        if cancel:dialog.cancel_button.click()
                        else:dialog.continue_button.click()
                        wait_until(lambda:dialog.worker is None)
                        job=store.jobs()[-1]
                        self.assertEqual(job['operation'],'IMAGE_OCR')
                        self.assertEqual(job['run_state'],'CANCELLED' if cancel else 'COMPLETED')
                        if cancel:
                            self.assertEqual(dialog.regions.toPlainText(),'manual draft retained on cancel')
                            self.assertIn('已取消',dialog.status.text())
                        else:self.assertEqual(json.loads(dialog.regions.toPlainText()),[])
                        self.assertFalse(dialog.cancel_button.isEnabled())
                    finally:
                        release.set()
                        if dialog.worker:
                            dialog._control('cancel');wait_until(lambda:dialog.worker is None)
                dialog.close();dialog.deleteLater();_APP.processEvents()

    def test_backend_selector_offers_verified_common_events_candidate(self):
        from PyQt5.QtWidgets import QComboBox,QLabel
        page=GameProjectPage();page._project_root=str(self.root)
        page._backend_files=['data/CommonEvents.json','data/Items.json'];page._backend_routes={}
        observed=[]
        def inspect_dialog():
            dialog=_APP.activeModalWidget()
            try:
                files,backends=dialog.findChildren(QComboBox)
                index=backends.findData('rpgmtl')
                observed.append(backends.model().item(index).isEnabled())
                observed.append(not any('暂不支持' in label.text() for label in dialog.findChildren(QLabel)))
                files.setCurrentText('data/Items.json')
                observed.append(backends.model().item(index).isEnabled())
            finally:dialog.reject()
        QTimer.singleShot(30,inspect_dialog)
        page._choose_backend()
        self.assertEqual(observed,[True,True,True])
        page.deleteLater();_APP.processEvents()

    def test_backend_selector_limits_js_to_rpgmtl_and_comparison_to_json(self):
        from PyQt5.QtWidgets import QComboBox
        page=GameProjectPage();page._project_root=str(self.root)
        page._backend_files=['js/words.js','data/Items.json'];page._backend_routes={}
        observed=[]
        def inspect_js():
            dialog=_APP.activeModalWidget()
            try:
                files,backends=dialog.findChildren(QComboBox)
                observed.append(files.currentText()=='js/words.js')
                observed.extend(backends.model().item(backends.findData(key)).isEnabled()
                    for key in ('native','rpgmtl','stev','sextractor'))
            finally:dialog.reject()
        QTimer.singleShot(30,inspect_js);page._choose_backend()
        def inspect_comparison():
            dialog=_APP.activeModalWidget()
            try:
                files=dialog.findChildren(QComboBox)[0]
                observed.append([files.itemText(i) for i in range(files.count())]==['data/Items.json'])
            finally:dialog.reject()
        QTimer.singleShot(30,inspect_comparison);page._choose_backend(comparison=True)
        self.assertEqual(observed,[True,True,True,False,False,True])
        page.deleteLater();_APP.processEvents()

    def wait(self,page):
        deadline=time.monotonic()+5
        idle_since=None
        while time.monotonic()<deadline:
            _APP.processEvents()
            if page.is_busy():idle_since=None
            elif idle_since is None:idle_since=time.monotonic()
            elif time.monotonic()-idle_since>.03:break
            time.sleep(.01)
        _APP.processEvents()
        self.assertFalse(page.is_busy())
        self.assertFalse(page.error_label.text(),page.error_label.text())

    def test_create_edit_exchange_and_build_through_widgets(self):
        project=self.root.parent/(self.root.name+'-gui-project')
        output=self.root.parent/(self.root.name+'-gui-output')
        page=GameProjectPage();page.resize(1500,950);page.show()
        page.source_edit.setText(str(self.root));page.project_edit.setText(str(project))
        page.create_button.click();self.wait(page)
        self.assertEqual(Path(page.project_root),project)
        page.extract_button.click();self.wait(page)
        self.assertGreater(page.unit_model.rowCount(),0)
        index=page.unit_model.row_for_unit(next(r['unit_id'] for r in page._unit_rows if r['source']=='学校'))
        def edit():
            dialog=_APP.activeModalWidget()
            dialog.translation_edit.setPlainText('学校（界面测试）')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        QTimer.singleShot(30,edit)
        page.unit_table.doubleClicked.emit(page.unit_model.index(index,0))
        self.wait(page)
        self.assertTrue(any(r['translation']=='学校（界面测试）' for r in page._unit_rows))
        page.tpp_export_button.click();self.wait(page)
        self.assertEqual(page.tpp_binding.count(),1)
        binding=page.tpp_binding.currentText()
        self.assertTrue((project/'interchange/translatorpp'/binding/'translations.trans').is_file())
        page.output_edit.setText(str(output));page.test_build_button.click();self.wait(page)
        builds=list(output.glob('game-zh-CN-*'));self.assertEqual(len(builds),1)
        self.assertTrue(BuildService.verify(builds[0])['passed'])
        translated=json.loads((builds[0]/'data/Map001.json').read_text(encoding='utf-8'))
        self.assertEqual(translated['displayName'],'学校（界面测试）')
        self.assertEqual(json.loads((self.root/'data/Map001.json').read_text(encoding='utf-8'))['displayName'],'学校')
        page.validate_button.click();self.wait(page)
        with GameProjectService(project) as service:
            self.assertEqual(service.store.jobs()[-1]['operation'],'VALIDATE')
            self.assertEqual(service.store.jobs()[-1]['run_state'],'COMPLETED')
        self.assertIn('离线校验通过',page.status_label.text())
        def choose_resume():
            dialog=_APP.activeModalWidget()
            if dialog is not None:dialog.accept()
        QTimer.singleShot(50,choose_resume)
        page.resume_build_button.click();self.wait(page)
        # The selection schedules the actual recovery after the list worker exits.
        _APP.processEvents();self.wait(page)
        self.assertEqual(len(list(output.glob('game-zh-CN-*'))),1)
        with GameProjectService(project) as service:
            self.assertTrue(any(j['operation']=='BUILD_RESUME' and j['run_state']=='COMPLETED' for j in service.store.jobs()))
        page.grab().save(str(project/'gui-workflow.png'))
        page.hide();page.deleteLater();_APP.processEvents()

    def test_resume_validation_through_widgets(self):
        from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        project=self.root.parent/(self.root.name+'-gui-resume-validation')
        with GameProjectService.create(self.root,project) as service:
            service.extract();ids=[]
            def cancel(done,total,label):
                if done>0:
                    with ProjectStore(project) as other:request_action(other,ids[-1],'cancel')
            with self.assertRaises(JobCancelled):
                service.validate(progress=cancel,on_job=lambda j:ids.append(j['job_id']))
        page=GameProjectPage();page.set_project(project);self.wait(page)
        def select_checkpoint():
            dialog=_APP.activeModalWidget()
            if dialog is not None:dialog.accept()
        QTimer.singleShot(60,select_checkpoint)
        page.resume_validation_button.click();self.wait(page)
        _APP.processEvents();self.wait(page)
        with GameProjectService(project) as service:
            final=service.store.jobs()[-1]
            self.assertEqual(final['operation'],'VALIDATE')
            self.assertEqual(final['run_state'],'COMPLETED')
            self.assertGreater(final['result']['reused_units'],0)
        self.assertIn('离线校验通过',page.status_label.text())
        page.deleteLater();_APP.processEvents()

    def test_resume_extraction_through_widgets(self):
        from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
        project=self.root.parent/(self.root.name+'-gui-resume-extraction')
        with GameProjectService.create(self.root,project) as service:
            ids=[]
            def cancel(done,total,label):
                if done==1:
                    with ProjectStore(project) as other:request_action(other,ids[-1],'cancel')
            with self.assertRaises(JobCancelled):
                service.extract(progress=cancel,on_job=lambda j:ids.append(j['job_id']))
            self.assertFalse(service.summary()['extraction_complete'])
        page=GameProjectPage();page.set_project(project);self.wait(page)
        def select_checkpoint():
            dialog=_APP.activeModalWidget()
            if dialog is not None:dialog.accept()
        QTimer.singleShot(60,select_checkpoint)
        page.resume_extract_button.click();self.wait(page)
        _APP.processEvents();self.wait(page)
        with GameProjectService(project) as service:
            final=service.store.jobs()[-1]
            self.assertEqual(final['operation'],'EXTRACT')
            self.assertEqual(final['run_state'],'COMPLETED')
            self.assertEqual(final['result']['reused_json_files'],1)
            self.assertTrue(service.summary()['extraction_complete'])
        self.assertGreater(page.unit_model.rowCount(),0)
        self.assertIn('复用 1 个 JSON',page.status_label.text())
        page.deleteLater();_APP.processEvents()

    def test_image_dialog_confirmation_render_and_approval(self):
        from UserInterface.GameProject.ImageWorkflowDialog import ImageWorkflowDialog
        from PIL import Image
        from test_image_acceptance import font_bytes
        import io
        (self.root/'img').mkdir();image=Image.new('RGBA',(180,70),'white')
        out=io.BytesIO();image.save(out,format='PNG');(self.root/'img/button.png').write_bytes(out.getvalue())
        project=self.root.parent/(self.root.name+'-image-gui')
        with GameProjectService.create(self.root,project) as service:service.extract()
        dialog=ImageWorkflowDialog(str(project));dialog.show();_APP.processEvents()
        def wait():
            deadline=time.monotonic()+5
            while dialog.worker and time.monotonic()<deadline:_APP.processEvents();time.sleep(.01)
            _APP.processEvents();self.assertIsNone(dialog.worker)
        wait();self.assertEqual(dialog.files.currentText(),'img/button.png')
        dialog.run('preview');wait();self.assertIsNotNone(dialog.preview_label.pixmap())
        dialog.regions.setPlainText(json.dumps([{'box':[20,15,140,40],'text':'日本','font_size':24}]))
        dialog.run('regions');wait();self.assertIn('区域已确认',dialog.status.text())
        with GameProjectService(project) as service:
            uid=next(u.unit_id for u in service.store.units() if u.kind=='image-text')
            service.import_translations({uid:'中文'})
        clean=project/'clean.png';clean.write_bytes(out.getvalue());font=project/'font.ttf';font.write_bytes(font_bytes())
        dialog.clean.setText(str(clean));dialog.font.setText(str(font));dialog.run('base');wait()
        dialog.run('render');wait();self.assertIsNotNone(dialog.candidate)
        dialog.run('approve');wait();self.assertIn('此预览已批准',dialog.status.text())
        dialog.grab().save(str(project/'image-dialog.png'));dialog.accept();dialog.deleteLater();_APP.processEvents()
