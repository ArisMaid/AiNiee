"""Registered output integrity, stale references and current-project GUI panels."""
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import pytest
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildArtifactService import inspect_registered_build,verify_registered_build
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash


@pytest.fixture
def artifact(tmp_path):
    source=tmp_path/'source';(source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'index.html').write_text('<title>synthetic game</title>',encoding='utf-8')
    (source/'js/rmmz_core.js').write_text('// rmmz_core.js v1.7.0',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'テスト','advanced':{'gameId':1}}),encoding='utf-8')
    with GameProjectService.create(source,tmp_path/'project') as current:
        current.extract();build=current.build(tmp_path/'output',test=True)
        yield current,build,source


def test_registered_inspection_is_readonly_and_does_not_decode_build_history(artifact):
    current,build,source=artifact;reference=current.store.latest_build_summary()
    before=current.store.metadata();jobs=current.store.jobs()
    with patch.object(current.store,'builds',side_effect=AssertionError('history loaded')):
        result=inspect_registered_build(current.store,reference)
    assert result['passed'] and result['runtime_validation']=='not_run'
    assert current.store.metadata()==before and current.store.jobs()==jobs


def test_changed_and_unlisted_files_fail_while_runtime_save_files_are_ignored(artifact):
    current,build,source=artifact;output=Path(build['output_path']);reference=current.store.latest_build_summary()
    (output/'save').mkdir();(output/'save/fixture.rmmzsave').write_bytes(b'synthetic runtime save')
    assert inspect_registered_build(current.store,reference)['passed']
    (output/'index.html').write_text('changed code',encoding='utf-8');(output/'unexpected.dat').write_bytes(b'unknown')
    report=inspect_registered_build(current.store,reference)
    assert not report['passed'] and report['changed_files']==['index.html'] and report['unexpected_files']==['unexpected.dat']
    assert (output/'save/fixture.rmmzsave').exists()


def test_forged_manifest_hashes_cannot_replace_the_registered_record(artifact):
    current,build,source=artifact;output=Path(build['output_path'])
    target=output/'index.html';target.write_bytes(b'changed program')
    manifest_path=output/'rpg-build-manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    next(row for row in manifest['files'] if row['path']=='index.html')['output_sha256']=file_hash(target)
    manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
    assert BuildService.verify(output)['passed']
    with pytest.raises(ValueError,match='BUILD_MANIFEST_CHANGED'):
        inspect_registered_build(current.store,current.store.latest_build_summary())


def test_stale_reference_and_cross_project_identity_are_rejected(artifact,tmp_path):
    current,build,source=artifact;old=current.store.latest_build_summary()
    current.build(tmp_path/'second-output',test=True)
    with pytest.raises(ValueError,match='BUILD_REFERENCE_CHANGED'):inspect_registered_build(current.store,old)
    wrong=dict(current.store.latest_build_summary(),project_id='other')
    with pytest.raises(ValueError,match='BUILD_REFERENCE_CHANGED'):inspect_registered_build(current.store,wrong)


def test_verification_records_cancel_and_keeps_output_and_dataset_unchanged(artifact):
    from ModuleFolders.Service.GameProject.JobControl import request_action,JobCancelled
    current,build,source=artifact;before=current.store.metadata();reference=current.store.latest_build_summary();jobs=[]
    def progress(done,total,label):
        if done==1:request_action(current.store,jobs[0]['job_id'],'cancel')
    with pytest.raises(JobCancelled):
        verify_registered_build(current.store,reference,progress=progress,on_job=jobs.append)
    assert current.store.get_job(jobs[0]['job_id'])['run_state']=='CANCELLED'
    assert current.store.metadata()==before and BuildService.verify(build['output_path'])['passed']


def app_and_page():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication
    from UserInterface.GameProject.GameProjectPage import GameProjectPage
    return QApplication.instance() or QApplication([]),GameProjectPage()


def wait(app,page):
    until=time.monotonic()+10;idle=None
    while time.monotonic()<until:
        app.processEvents()
        if page.is_busy():idle=None
        elif idle is None:idle=time.monotonic()
        elif time.monotonic()-idle>.03:return
        time.sleep(.005)
    raise AssertionError('GUI worker did not settle')


def test_gui_build_panel_restores_on_open_and_clears_when_switching_projects(artifact,tmp_path):
    current,build,source=artifact;app,page=app_and_page()
    try:
        page.set_project(current.store.root);wait(app,page)
        assert page.build_output_edit.text()==build['output_path'] and page.open_output_button.isEnabled()
        page.verify_build_button.click();wait(app,page)
        assert '校验通过' in page.status_label.text() and not page.error_label.text()
        with GameProjectService.create(source,tmp_path/'other-project') as other:other.extract()
        page.set_project(tmp_path/'other-project')
        assert not page.open_output_button.isEnabled() and page.build_output_edit.text()==''
        wait(app,page);assert page._latest_build is None
    finally:
        if page.is_busy():wait(app,page)
        page.deleteLater();app.processEvents()


def test_open_button_dispatches_only_verified_local_folder_and_never_changed_output(artifact):
    current,build,source=artifact;app,page=app_and_page();opened=[]
    from PyQt5.QtGui import QDesktopServices
    try:
        page.set_project(current.store.root);wait(app,page)
        with patch.object(QDesktopServices,'openUrl',side_effect=lambda url:opened.append(url.toLocalFile()) or True):
            page.open_output_button.click();wait(app,page)
            assert [Path(value) for value in opened]==[Path(build['output_path'])]
            (Path(build['output_path'])/'index.html').write_bytes(b'modified')
            page.open_output_button.click();wait(app,page)
            assert [Path(value) for value in opened]==[Path(build['output_path'])] and '拒绝打开' in page.error_label.text()
    finally:
        if page.is_busy():wait(app,page)
        page.deleteLater();app.processEvents()
