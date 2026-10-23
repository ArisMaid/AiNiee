"""RPG-focused AiNiee launcher, CLI dispatcher and offline artifact self-check."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    os.environ['AINIEE_RPG_APP']='1'
    args=list(sys.argv[1:] if argv is None else argv)
    if args and args[0]=='--backend-worker':
        from ModuleFolders.Infrastructure.GameAdapters.BackendWorker import main as worker_main
        return worker_main()
    if args and args[0]=='--cli':
        from Tools.rpg_pipeline import main as cli_main
        return cli_main(args[1:])
    if args and args[0]=='--self-check':
        from Tools.rpg_selfcheck import self_check
        result=self_check(Path(args[1]) if len(args)>1 else Path.cwd()/'work'/'selfcheck')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['passed'] else 1
    import argparse
    parser=argparse.ArgumentParser(description='AiNiee RPG desktop')
    parser.add_argument('--project');parser.add_argument('--offline',action='store_true')
    parser.add_argument('--gui-check',help='Run an isolated offscreen GUI smoke and write artifacts here')
    parser.add_argument('--gui-check-verify-build',action='store_true',
        help='With --gui-check --project, verify the registered latest output (records a project job)')
    options=parser.parse_args(args)
    if options.gui_check_verify_build and (not options.gui_check or not options.project):
        parser.error('--gui-check-verify-build requires --gui-check and --project; use a retained project copy')
    if options.gui_check:
        check_root=Path(options.gui_check).absolute()
        check_root.mkdir(parents=True,exist_ok=True)
        os.environ.update(QT_QPA_PLATFORM='offscreen',AINIEE_OFFLINE='1',AINIEE_PORTABLE='1')
        for key,folder in [('AINIEE_USER_DATA_DIR','user'),('AINIEE_CACHE_DIR','cache'),
                ('AINIEE_PROJECT_CACHE_DIR','projects'),('AINIEE_LOG_DIR','logs'),('TIKTOKEN_CACHE_DIR','tiktoken')]:
            os.environ[key]=str(check_root/folder)
    if options.offline:os.environ['AINIEE_OFFLINE']='1'
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication
    from ModuleFolders.Service.Cache.CacheManager import CacheManager
    from ModuleFolders.Domain.FileReader.FileReader import FileReader
    from ModuleFolders.Domain.FileOutputer.FileOutputer import FileOutputer
    from ModuleFolders.Service.TaskExecutor.TaskExecutor import TaskExecutor
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    from UserInterface.AppFluentWindow import AppFluentWindow
    from ModuleFolders.Infrastructure.Tokener.TiktokenLoader import initialize_tiktoken
    app=QApplication([sys.argv[0]])
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_fonts
    configure_qt_fonts(app)
    initialize_tiktoken()
    cache=CacheManager();reader=FileReader();writer=FileOutputer()
    executor=TaskExecutor(cache,reader,writer)
    simple=SimpleExecutor(cache_manager=cache)
    from ModuleFolders.Domain.GameProject.Version import VERSION
    window=AppFluentWindow('AiNiee RPG '+VERSION,cache,reader)
    if options.gui_check:window.resize(1600,1000)
    window.switchTo(window.game_project_page)
    if options.project:window.game_project_page.set_project(options.project)
    window.show()
    if options.gui_check:
        from PyQt5.QtCore import QTimer
        from ModuleFolders.Service.GameProject.BuildService import write_json
        import time
        deadline=time.monotonic()+20
        def check_gui():
            page=window.game_project_page
            if page.is_busy() and time.monotonic()<deadline:
                QTimer.singleShot(50,check_gui);return
            from PyQt5.QtGui import QFontDatabase,QImage,QPainter,QFont,QColor
            font_count=len(QFontDatabase().families())
            probe=QImage(240,50,QImage.Format_RGB32);probe.fill(0xffffff)
            painter=QPainter(probe);painter.setPen(QColor('black'));painter.setFont(QFont('Microsoft YaHei',16))
            painter.drawText(5,30,'AiNiee 汉化');painter.end()
            ink=sum(probe.pixelColor(x,y).lightness()<128 for x in range(240) for y in range(50))
            probe.save(str(check_root/'text-render.png'))
            passed=not page.is_busy() and not page.error_label.text() and font_count>0 and ink>100
            window.grab().save(str(check_root/'gui.png'))
            result={'passed':passed,'main_window':'created','game_page':'created',
                    'model_requests':0,'visible_unit_rows':page.unit_model.rowCount(),
                    'font_families':font_count,'text_ink_pixels':ink}
            from UserInterface.GameProject.MigrationDialog import MigrationDialog
            migration=MigrationDialog(page.project_root,window);migration.show();app.processEvents()
            migration.grab().save(str(check_root/'migration-dialog.png'))
            result['migration_dialog']='created';result['ui_font_family']=app.font().family()
            migration.close();migration.deleteLater();app.processEvents()
            from UserInterface.GameProject.CommandAuditDialog import CommandAuditDialog
            audit_rows=[{'path':'data/Map001.json','scene_id':'Map001:event:7:page:0',
                'pointer':'/events/1/pages/0/list/0','code':357,'plugin':'DisplayPlugin','command':'show',
                'approved_fields':['text'],'unreviewed_fields':['id'],
                'raw_commands':[{'code':357,'parameters':['DisplayPlugin','show','显示',{'text':'显示文字','id':'逻辑标识'}]}]}]
            audit_dialog=CommandAuditDialog({'dataset_revision':1,'documents':[{}],'records':audit_rows},
                '（合成界面验收，无游戏数据）',window)
            audit_dialog.show();app.processEvents()
            audit_dialog.grab().save(str(check_root/'command-audit-dialog.png'))
            result['command_audit_dialog']={'rows':audit_dialog.model.rowCount(),
                'readonly':audit_dialog.details.isReadOnly(),'source_preview':bool(audit_dialog.details.toPlainText())}
            result['passed']=result['passed'] and result['command_audit_dialog']=={'rows':1,'readonly':True,'source_preview':True}
            audit_dialog.close();audit_dialog.deleteLater();app.processEvents()
            from UserInterface.GameProject.ComparisonReportDialog import ComparisonReportDialog
            comparison_report={'backend':'rpgmtl','relative_path':'data/Items.json','report_path':'（合成比较界面验收）','type_check':'complete',
                'counts':{'overlap':1,'backend_only':0,'ambiguous':1,'native_only':1},
                'overlap':[{'unit_id':'u1','record_index':0,'pointer':'/1/name'}], 'backend_only':[],
                'ambiguous':[{'record_index':1,'candidate_pointer_group':'g0','candidate_pointer_count':2}],
                'native_only':[{'unit_id':'u2','pointer':'/2/description'}],
                'backend_records':[{'record_index':0,'text':'原文名称','locator':{'group_index':0}},
                    {'record_index':1,'text':'重复候选','locator':{'group_index':1}}],
                'native_occurrences':[{'unit_id':'u1','pointer':'/1/name','source_text':'原文名称','role':'name','kind':'name','value_codec':None},
                    {'unit_id':'u2','pointer':'/2/description','source_text':'原生说明','role':'description','kind':'description','value_codec':None}],
                'candidate_pointer_groups':{'g0':['/3/name','/4/name']}}
            comparison_report.update(type_conflicts=[{'side':'native','unit_id':'u2','pointer':'/2/description',
                'expected_type':'string','actual_type':'number','reason':'source_field_type'}],
                source_field_types={'/2/description':'number'})
            comparison_dialog=ComparisonReportDialog(comparison_report,window)
            comparison_dialog.show();app.processEvents()
            comparison_dialog.grab().save(str(check_root/'comparison-dialog.png'))
            result['comparison_dialog']={'rows':comparison_dialog.model.rowCount(),
                'readonly':comparison_dialog.details.isReadOnly(),'source_preview':bool(comparison_dialog.details.toPlainText())}
            result['passed']=result['passed'] and result['comparison_dialog']=={'rows':4,'readonly':True,'source_preview':True}
            comparison_dialog.close();comparison_dialog.deleteLater();app.processEvents()
            from UserInterface.GameProject.ExternalToolsDialog import ExternalToolsDialog
            tools_dialog=ExternalToolsDialog(window,'translatorpp');tools_dialog.show();app.processEvents()
            tool_deadline=time.monotonic()+20
            while tools_dialog.worker and time.monotonic()<tool_deadline:
                app.processEvents();time.sleep(.01)
            tools_dialog.grab().save(str(check_root/'external-tools-dialog.png'))
            result['external_tools_dialog']={'tools':tools_dialog.tools.count(),
                'download':tools_dialog.buttons[0].text(),'select':tools_dialog.buttons[1].text(),
                'finished':tools_dialog.worker is None,'without_project':page.external_tools_button.isEnabled()}
            result['passed']=result['passed'] and tools_dialog.worker is None and tools_dialog.tools.count()==5
            tools_dialog.close();tools_dialog.deleteLater();app.processEvents()
            result['action_tabs']=[page.action_tabs.tabText(index) for index in range(page.action_tabs.count())]
            result['build_panel']={'readonly':page.build_output_edit.isReadOnly(),
                'output_present':bool(page.build_output_edit.text())}
            result['passed']=result['passed'] and result['action_tabs']==['常用操作','工具与恢复','Translator++'] and result['build_panel']['readonly']
            def write_and_exit():
                write_json(check_root/'gui-result.json',result)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                window.systemThemeListener.requestInterruption();window.systemThemeListener.quit()
                window.systemThemeListener.wait(3000)
                window.hide();app.exit(0 if result['passed'] else 1)
            def load_translation_view():
                if not page.project_root or not page._unit_rows:
                    write_and_exit();return
                from UserInterface.Native.ControlVisibility import control_visibility
                load_start=time.monotonic();load_deadline=load_start+20;gaps=[];last=[load_start]
                load_cancelled=[False]
                load_heartbeat=QTimer(window);load_heartbeat.setInterval(20)
                def load_tick():
                    now=time.monotonic();gaps.append((now-last[0])*1000);last[0]=now
                load_heartbeat.timeout.connect(load_tick);load_heartbeat.start()
                window.open_game_translation(page.game_project_path)
                click_ms=(time.monotonic()-load_start)*1000
                def capture_controls():
                    translation=window.edit_view_page.translation_page
                    card=translation.language_settings_card
                    widgets={'start':translation.bottom_bar.start_btn,
                        'source':card.source_language_combo,'target':card.target_language_combo}
                    return {name:control_visibility(window,widget) for name,widget in widgets.items()}
                def check_loaded():
                    if page.is_busy():
                        if time.monotonic()>=load_deadline:
                            load_cancelled[0]=True
                            window._cancel_game_translation()
                            result['passed']=False
                        QTimer.singleShot(30,check_loaded);return
                    load_heartbeat.stop();load_heartbeat.deleteLater()
                    loaded=cache.project
                    count=sum(len(file.items) for file in loaded.files.values()) if loaded else 0
                    card=window.edit_view_page.translation_page.language_settings_card
                    source_language=card.source_language_pairs[card.source_language_combo.currentIndex()][1]
                    target_language=card.target_language_pairs[card.target_language_combo.currentIndex()][1]
                    load_error=page.error_label.text()
                    controls=capture_controls()
                    translation_view={'project_type':loaded.project_type if loaded else None,
                        'items':count,'click_return_ms':click_ms,'load_ms':(time.monotonic()-load_start)*1000,
                        'heartbeat_max_ms':max(gaps,default=0),'error':load_error,
                        'source_language':source_language,'target_language':target_language,
                        'controls_visible':False,'controls':controls,'visibility_wait_ms':0.0}
                    result['translation_view']=translation_view
                    load_ok=(not load_cancelled[0] and bool(loaded)
                        and loaded.project_type=='RpgGame' and count==len(page._unit_rows)
                        and not load_error)
                    result['passed']=(result['passed'] and load_ok
                        and source_language=='japanese' and target_language=='chinese_simplified')
                    if not load_ok:
                        write_and_exit();return
                    wait_start=time.monotonic();wait_deadline=wait_start+2.0
                    stable_rects=None;stable_since=None;last_reports=controls
                    def finish_visibility(ok):
                        translation_view['controls_visible']=bool(ok)
                        translation_view['controls']=last_reports
                        translation_view['visibility_wait_ms']=(time.monotonic()-wait_start)*1000
                        if not ok:result['passed']=False
                        window.grab().save(str(check_root/'translation-view.png'))
                        write_and_exit()
                    def check_visibility():
                        nonlocal stable_rects,stable_since,last_reports
                        now=time.monotonic()
                        reports=capture_controls();last_reports=reports
                        all_visible=all(report['fully_visible'] for report in reports.values())
                        rects=tuple((name,tuple(report['rect'])) for name,report in reports.items())
                        if all_visible:
                            if stable_rects==rects:
                                if stable_since is not None and now-stable_since>=0.100:
                                    finish_visibility(True);return
                            else:
                                stable_rects=rects;stable_since=now
                        else:
                            stable_rects=None;stable_since=None
                        if now>=wait_deadline:
                            finish_visibility(False);return
                        QTimer.singleShot(20,check_visibility)
                    if all(report['fully_visible'] for report in controls.values()):
                        stable_rects=tuple((name,tuple(report['rect'])) for name,report in controls.items())
                        stable_since=time.monotonic()
                    QTimer.singleShot(20,check_visibility)
                QTimer.singleShot(30,check_loaded)
            def finish_gui():
                if not options.gui_check_verify_build:
                    load_translation_view();return
                if not page.verify_build_button.isEnabled():
                    result['registered_build']={'passed':False,'error':'No registered completed build is available'}
                    result['passed']=False;write_and_exit();return
                verify_start=time.monotonic();verify_deadline=verify_start+120
                page.verify_build_button.click()
                def check_verified():
                    if page.is_busy():
                        if time.monotonic()>=verify_deadline:
                            page._control_job('cancel');result['passed']=False
                        QTimer.singleShot(50,check_verified);return
                    passed=not page.error_label.text() and '校验通过' in page.status_label.text()
                    result['registered_build']={'passed':passed,'error':page.error_label.text(),
                        'elapsed_ms':(time.monotonic()-verify_start)*1000,
                        'runtime_label':page.last_build_label.text()}
                    result['passed']=result['passed'] and passed
                    if passed:load_translation_view()
                    else:write_and_exit()
                QTimer.singleShot(50,check_verified)
            if page.project_root:
                from UserInterface.GameProject.ImageWorkflowDialog import ImageWorkflowDialog
                image=ImageWorkflowDialog(page.project_root,window);image.show()
                image_deadline=time.monotonic()+10
                def check_image():
                    if image.worker and time.monotonic()<image_deadline:
                        QTimer.singleShot(50,check_image);return
                    result['image_dialog']='created'
                    result['ocr_controls']=[image.pause_button.text(),image.continue_button.text(),image.cancel_button.text()]
                    result['passed']=result['passed'] and image.worker is None
                    image.grab().save(str(check_root/'image-dialog.png'))
                    image.close();finish_gui()
                QTimer.singleShot(100,check_image)
            else:finish_gui()
        QTimer.singleShot(500,check_gui)
    return app.exec_()


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
