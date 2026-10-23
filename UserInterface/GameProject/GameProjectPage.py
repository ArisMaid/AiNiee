"""Standalone RPG game project page built from plain PyQt5 widgets.

Contract: ``docs/rpg/UI_QUALITY_CONTRACT.md``.

The page owns no store and no SQLite connection: every heavy operation runs in
:class:`_GameProjectJob`, a ``QThread`` that opens its own
:class:`GameProjectService`, performs exactly one operation and closes the
service (and its connection) again.  Only plain JSON-safe dictionaries cross
the thread boundary, so the summary and the issue list always come from SQLite
and never from a second mutable cache.

The page never launches the game, never sends an API request on its own and
never claims runtime validation; the ``送往 AiNiee 翻译`` button only emits
``translateRequested`` with the current ``game-project.json`` path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
    QFrame,
    QGroupBox,
    QInputDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.PathGuard import atomic_write, assert_disjoint, safe_join
from ModuleFolders.Service.GameProject.ProjectLock import ProjectLock

__all__ = ['GameProjectPage']

#: Import files above this size are refused instead of loaded into memory.
MAX_IMPORT_BYTES = 64 * 1024 * 1024

_JSON_FILTER = 'JSON 文件 (*.json)'
_UNIT_HEADERS = ('单元 ID', '类型', '原文', '译文', '状态')
_ISSUE_HEADERS = ('级别', '代码', '文件', '单元 ID', '说明')

_STATUS_LABELS = {'translated': '已翻译', 'untranslated': '未翻译', 'stale': '待重译'}
_COMMIT_LABELS = {
    'accepted': '已接受',
    'duplicate': '重复提交',
    'rejected': '被拒绝',
    'conflict': '冲突',
    'locked': '已锁定',
}
_RUNTIME_LABELS = {
    'not_run': '未执行（本工具不启动游戏）',
    'passed': '已通过',
    'failed': '未通过',
}
_OPERATION_LABELS = {
    'create': '扫描并创建项目',
    'extract': '提取文本',
    'extract_list': '读取提取检查点',
    'extract_resume': '恢复提取',
    'refresh': '刷新',
    'validate': '离线校验',
    'validation_list': '读取校验检查点',
    'validation_resume': '恢复校验',
    'build': '构建',
    'artifact_verify': '核对构建副本',
    'artifact_open': '核对并打开输出目录',
    'export': '导出译文 JSON',
    'import': '导入译文 JSON',
    'commit_unit': '提交译文',
    'tpp_export': '导出 Translator++ 译文工程',
    'tpp_import': '导回 Translator++ 译文',
}


def _status_text(row: dict) -> str:
    label = _STATUS_LABELS.get(str(row.get('status', '')), str(row.get('status', '')))
    if row.get('manual_locked'):
        return f'{label}（锁定）'
    return label


def _runtime_text(value: object) -> str:
    key = str(value or 'not_run')
    return _RUNTIME_LABELS.get(key, f'未知（{key}）')


def _describe_results(results) -> str:
    counts: dict = {}
    for item in results or ():
        status = str(item.get('status', 'unknown'))
        counts[status] = counts.get(status, 0) + 1
    if not counts:
        return '0 条'
    return '，'.join(
        f'{_COMMIT_LABELS.get(status, status)} {count}' for status, count in sorted(counts.items())
    )


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class _UnitTableModel(QAbstractTableModel):
    """Read only row model for translation units; one model, no widget per unit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list = []

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_UNIT_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and 0 <= section < len(_UNIT_HEADERS):
            return _UNIT_HEADERS[section]
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.UserRole:
            return row.get('unit_id', '')
        if role == Qt.ToolTipRole:
            return f"{row.get('unit_id', '')}\n{row.get('source', '')}"
        if role != Qt.DisplayRole:
            return None
        if column == 0:
            return row.get('unit_id', '')
        if column == 1:
            return row.get('kind', '')
        if column == 2:
            return row.get('source', '')
        if column == 3:
            return row.get('translation', '')
        if column == 4:
            return _status_text(row)
        return None

    def row_at(self, row: int):
        if 0 <= row < len(self._rows):
            return dict(self._rows[row])
        return None

    def row_for_unit(self, unit_id: str):
        for row, item in enumerate(self._rows):
            if item.get('unit_id') == unit_id:
                return row
        return None


class _IssueTableModel(QAbstractTableModel):
    """Read only row model for the SQLite issue log."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list = []

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_ISSUE_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and 0 <= section < len(_ISSUE_HEADERS):
            return _ISSUE_HEADERS[section]
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.UserRole:
            return row.get('unit_id', '')
        if role == Qt.ToolTipRole:
            return str(row.get('message', ''))
        if role != Qt.DisplayRole:
            return None
        if column == 0:
            return row.get('severity', '')
        if column == 1:
            return row.get('code', '')
        if column == 2:
            return row.get('path', '')
        if column == 3:
            return row.get('unit_id', '')
        if column == 4:
            return row.get('message', '')
        return None

    def row_at(self, row: int):
        if 0 <= row < len(self._rows):
            return dict(self._rows[row])
        return None


class _TranslationDialog(QDialog):
    """Editable translation with a strictly read-only source text."""

    def __init__(self, row: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('编辑译文')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"单元：{row.get('unit_id', '')}    类型：{row.get('kind', '')}    "
            f"状态：{_status_text(row)}"
        ))
        layout.addWidget(QLabel('原文（只读，不允许修改）'))
        source = QPlainTextEdit(str(row.get('source', '')))
        source.setReadOnly(True)
        layout.addWidget(source)
        layout.addWidget(QLabel('译文'))
        self.translation_edit = QPlainTextEdit(str(row.get('translation', '')))
        layout.addWidget(self.translation_edit)
        self.lock_box = QCheckBox('手动锁定该单元（锁定后模型与构建不会覆盖）')
        self.lock_box.setChecked(bool(row.get('manual_locked')))
        layout.addWidget(self.lock_box)
        self.source_lock_button = QPushButton('保留原文并锁定')
        self.source_lock_button.clicked.connect(lambda: (
            self.translation_edit.setPlainText(str(row.get('source', ''))),
            self.lock_box.setChecked(True)))
        layout.addWidget(self.source_lock_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('确定')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 480)

    def values(self):
        return self.translation_edit.toPlainText(), bool(self.lock_box.isChecked())


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------

class _GameProjectJob(QThread):
    """One project operation, one private service/SQLite connection."""

    progressed = pyqtSignal(int, int, str)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    jobStarted = pyqtSignal(dict)

    def __init__(self, operation: str, payload: dict, parent=None) -> None:
        super().__init__(parent)
        self._operation = str(operation)
        self._payload = dict(payload)
        self._project = str(self._payload.get('project', ''))

    # -- thread body ------------------------------------------------------
    def run(self) -> None:
        try:
            result = self._execute()
        except Exception as error:  # every failure is reported to the page
            from ModuleFolders.Service.GameProject.JobControl import JobCancelled
            if isinstance(error,JobCancelled):
                self.succeeded.emit({'operation':'cancelled','job_id':error.job_id})
                return
            self.failed.emit(f'{type(error).__name__}: {error}')
            return
        self.succeeded.emit(result)

    def _progress(self, done, total, label) -> None:
        self.progressed.emit(int(done), int(total), str(label))

    def _execute(self) -> dict:
        operation = self._operation
        if operation == 'create':
            service = GameProjectService.create(
                self._payload['source'],
                self._payload['project_root'],
                progress=self._progress,
                on_job=self.jobStarted.emit,
            )
            try:
                return self._snapshot(service, 'create')
            finally:
                service.close()

        service = GameProjectService(self._project)
        try:
            if operation == 'refresh':
                return self._snapshot(service, 'refresh')
            if operation == 'image':
                from ModuleFolders.Service.GameProject import ImageService as images
                p=self._payload;action=p['action'];rel=p.get('relative_path','')
                if action=='inventory':result=images.inventory(service.store)
                elif action=='preview':result=images.preview(service.store,rel)
                elif action=='ocr':result=images.ocr(service.store,rel,p['executable'],p['tessdata'],p.get('language','jpn+eng'),on_job=self.jobStarted.emit)
                elif action=='regions':result=images.confirm_regions(service.store,rel,p['source_sha256'],p['regions'])
                elif action=='base':result=images.prepare_base(service.store,rel,p['clean_base'],p['font'])
                elif action=='render':result=images.render_candidate(service.store,rel)
                elif action=='approve':result=images.approve_candidate(service.store,rel,p['sha256'])
                else:raise ValueError('IMAGE_ACTION_UNKNOWN')
                return {'operation':operation,'action':action,'result':result}
            if operation == 'extract':
                extracted=service.extract(progress=self._progress,on_job=self.jobStarted.emit)
                return dict(self._snapshot(service,'extract'),recovery=extracted.get('recovery',{}))
            if operation == 'extract_list':
                from ModuleFolders.Service.GameProject.JobController import recover_jobs
                recover_jobs(service.store)
                return {'operation':operation,'items':[j for j in service.store.jobs() if j['operation']=='EXTRACT'
                    and j['run_state'] in {'INTERRUPTED','FAILED','CANCELLED'} and j.get('result',{}).get('descriptor')]}
            if operation == 'extract_resume':
                extracted=service.resume_extract(self._payload['job_id'],progress=self._progress,on_job=self.jobStarted.emit)
                return dict(self._snapshot(service,'extract'),recovery=extracted.get('recovery',{}))
            if operation == 'resume_scan':
                service.resume_scan(progress=self._progress,on_job=self.jobStarted.emit)
                return self._snapshot(service,operation)
            if operation == 'job_action':
                from ModuleFolders.Service.GameProject.JobControl import request_action
                job=request_action(service.store,self._payload['job_id'],self._payload['action'])
                return {'operation':operation,'state':job['run_state']}
            if operation == 'backend_route':
                from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
                result=configure_route(service.store,self._payload['relative_path'],
                    self._payload['backend'],self._payload.get('backend_root'),on_job=self.jobStarted.emit)
                return {'operation':operation,'result':result}
            if operation == 'backend_compare':
                from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
                result=compare_backend(service.store,self._payload['backend'],self._payload['backend_root'],
                    self._payload['relative_path'],on_job=self.jobStarted.emit)
                return {'operation':operation,'result':result}
            if operation == 'command_audit':
                from ModuleFolders.Service.GameProject.CommandAuditService import audit_commands, load_audit_report
                result = audit_commands(service.store, on_job=self.jobStarted.emit)
                return {'operation': operation, 'result': result, 'report': load_audit_report(service.store, result)}
            if operation == 'build_list':
                seen=set();items=[]
                for job in reversed(service.store.jobs()):
                    build_id=job.get('result',{}).get('build_id')
                    if (isinstance(build_id,str) and len(build_id)==32 and all(c in '0123456789abcdef' for c in build_id)
                        and build_id not in seen and safe_join(service.store.root,'builds/'+build_id+'/resume.sqlite3').is_file()):
                        seen.add(build_id);items.append(build_id+' ['+job['run_state']+']')
                return {'operation':operation,'items':items}
            if operation == 'build_resume':
                manifest=service.resume_build(self._payload['build_id'],progress=self._progress,on_job=self.jobStarted.emit)
                return {'operation':'build','manifest':manifest}
            if operation == 'validate':
                return {'operation': 'validate', 'result': service.validate(progress=self._progress,on_job=self.jobStarted.emit)}
            if operation == 'validation_list':
                from ModuleFolders.Service.GameProject.JobController import recover_jobs
                recover_jobs(service.store)
                return {'operation':operation,'items':[j for j in service.store.jobs() if j['operation']=='VALIDATE'
                    and j['run_state'] in {'INTERRUPTED','FAILED','CANCELLED'} and j.get('result',{}).get('descriptor')]}
            if operation == 'validation_resume':
                return {'operation':'validate','result':service.resume_validation(self._payload['job_id'],
                    progress=self._progress,on_job=self.jobStarted.emit)}
            if operation == 'font':
                return {'operation':'font','result':service.configure_font(self._payload['path'])}
            if operation == 'build':
                manifest = service.build(
                    self._payload['output_root'],
                    test=bool(self._payload.get('test')),
                    progress=self._progress,
                    on_job=self.jobStarted.emit,
                )
                return {'operation': 'build', 'manifest': manifest}
            if operation in {'artifact_verify','artifact_open'}:
                from ModuleFolders.Service.GameProject.BuildArtifactService import verify_registered_build
                report=verify_registered_build(service.store,self._payload['reference'],
                    progress=self._progress,on_job=self.jobStarted.emit)
                return {'operation':operation,'result':report}
            if operation == 'export':
                return self._export(service)
            if operation == 'import':
                return self._import(service)
            if operation == 'tpp_export':
                from ModuleFolders.Service.GameProject.TranslatorPlusPlusBridge import export_exchange,open_exchange
                result=export_exchange(service.store)
                if self._payload.get('open'):
                    from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools
                    ExternalTools().start_translatorpp()
                    from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import TranslatorPlusPlusClient
                    open_exchange(service.store,result['binding_id'],TranslatorPlusPlusClient())
                return {'operation':operation,'result':result}
            if operation == 'tpp_import':
                from ModuleFolders.Service.GameProject.TranslatorPlusPlusBridge import pull_exchange,import_exchange_file
                if self._payload.get('path'):
                    result=import_exchange_file(service.store,self._payload['binding'],self._payload['path'])
                else:
                    from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools
                    ExternalTools().start_translatorpp()
                    from ModuleFolders.Infrastructure.GameAdapters.TranslatorPlusPlusClient import TranslatorPlusPlusClient
                    result=pull_exchange(service.store,self._payload['binding'],TranslatorPlusPlusClient())
                return {'operation':operation,'result':result}
            if operation == 'commit_unit':
                return self._commit_unit(service)
            raise ValueError(f'未知操作：{operation}')
        finally:
            service.close()

    # -- operations -------------------------------------------------------
    def _snapshot(self, service, operation: str) -> dict:
        store = service.store
        units = []
        for unit in store.units():
            translation = store.translation(unit.unit_id) or {}
            text = str(translation.get('text') or '')
            if not text.strip():
                status = 'untranslated'
            elif translation.get('stale') or translation.get('status') == 'stale':
                status = 'stale'
            else:
                status = 'translated'
            units.append({
                'unit_id': unit.unit_id,
                'kind': unit.kind,
                'scene_id': unit.scene_id,
                'source': unit.source_text,
                'translation': text,
                'status': status,
                'source_hash': unit.source_hash,
                'expected_revision': int(translation.get('revision', 0) or 0),
                'manual_locked': bool(translation.get('manual_locked')),
            })
        js_paths={occurrence.relative_path for unit in store.units() for occurrence in unit.occurrences
            if occurrence.adapter_id=='js-literal'}
        return {
            'operation': operation,
            'project_root': str(store.root),
            'summary': service.summary(),
            'element_name_sop': store.metadata().get('profile_id') == 'selenoxia-test-0.141',
            'units': units,
            'issues': store.issues(),
            'tpp_bindings': list(reversed(store.metadata().get('translatorpp_bindings',{}))),
            'backend_files':[r['relative_path'] for r in store.files() if (r['relative_path'].startswith('data/')
                and r['relative_path'].endswith('.json')) or r['relative_path'] in js_paths],
            'backend_routes':{rel:{'backend':route['backend'],'backend_root':route['backend_root']}
                for rel,route in store.metadata().get('backend_routes',{}).items()},
            'latest_build':store.latest_build_summary(),
        }

    def _export(self, service) -> dict:
        target = Path(str(self._payload['path']))
        assert_disjoint(service.store.metadata()['source_root'], target.absolute().parent)
        if os.path.lexists(target):
            raise ValueError(f'导出目标已存在，请选择一个新文件：{target}')
        rows = service.export_translations()
        data = (json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        atomic_write(target, data)
        return {'operation': 'export', 'path': str(target), 'row_count': len(rows)}

    def _import(self, service) -> dict:
        source = Path(str(self._payload['path']))
        if not source.is_file():
            raise ValueError(f'导入文件不存在：{source}')
        if source.stat().st_size > MAX_IMPORT_BYTES:
            raise ValueError('导入文件过大，已拒绝加载（上限 64 MiB）')
        try:
            payload = json.loads(source.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError(f'导入文件不是有效的 UTF-8 JSON：{error}') from error
        results = service.import_translations(payload, origin='manual')
        return {
            'operation': 'import',
            'path': str(source),
            'results': [result.to_dict() for result in results],
        }

    def _commit_unit(self, service) -> dict:
        store = service.store
        row = dict(self._payload['row'])
        unit_id = str(row['unit_id'])
        unit = store.unit(unit_id)
        if unit is None:
            raise ValueError(f'UNKNOWN_UNIT：单元 {unit_id} 已不存在，请刷新')
        if str(row.get('source_hash') or '') != unit.source_hash:
            raise ValueError('SOURCE_CHANGED：单元原文已变化，请刷新后重试')
        text = row.get('text')
        if not isinstance(text, str):
            raise ValueError('译文必须是字符串')
        desired_lock = bool(self._payload.get('lock'))
        expected = int(row['expected_revision'])
        from ModuleFolders.Domain.GameProject.Models import TranslationProposal
        from ModuleFolders.Service.GameProject.TranslationCommitter import TranslationCommitter
        with ProjectLock(store.root):
            current = store.translation(unit_id) or {}
            if expected != current.get('revision', 0):
                raise ValueError('REVISION_CONFLICT：译文已被其他操作修改，请刷新')
            before_text = str(current.get('text') or '')
            before_lock = bool(current.get('manual_locked'))
            # One store transaction carries the accepted text and the desired
            # lock; the old unlock/submit/finally-relock sequence is gone.
            result = TranslationCommitter(store).edit_manual(
                TranslationProposal(unit_id, text, row['source_hash'],
                    expected_revision=expected, origin='manual'),
                locked=desired_lock,
            )
        accepted = result.status in {'accepted', 'duplicate'}
        # A metadata-only lock command is reported as accepted with the
        # unchanged text revision. It stays invisible to the results list.
        lock_only = accepted and int(result.revision) == expected and text == before_text
        changed = bool(lock_only and desired_lock != before_lock) or bool(
            accepted and not lock_only)
        results = [] if lock_only else [result]
        return {
            'operation': 'commit_unit',
            'unit_id': unit_id,
            'changed': changed,
            'results': [item.to_dict() for item in results],
        }


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

class GameProjectPage(QWidget):
    """Standalone RPG game project page; the main window wires navigation."""

    translateRequested = pyqtSignal(str)
    translationCancelRequested = pyqtSignal()

    def __init__(self, parent=None, *, on_translate=None) -> None:
        super().__init__(parent)
        self._project_root = ''
        self._game_project_path = ''
        self._unit_rows: list = []
        self._element_name_sop = False
        self._issue_rows: list = []
        self._worker = None
        self._control_worker = None
        self._active_job = None
        self._backend_files=[]
        self._backend_routes={}
        self._busy = False
        self._translation_loading = False
        self._latest_build = None
        self._refresh_after = False
        self._build_ui()
        if on_translate is not None:
            self.translateRequested.connect(on_translate)
        self._update_enabled()

    # -- construction -----------------------------------------------------
    def _path_row(self, caption, button_text, handler, *, read_only=False):
        edit = QLineEdit()
        edit.setReadOnly(read_only)
        button = QPushButton(button_text)
        button.clicked.connect(handler)
        row = QHBoxLayout()
        row.addWidget(QLabel(caption))
        row.addWidget(edit, 1)
        row.addWidget(button)
        return row, edit, button

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName('game-project-content-scroll')
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_widget = QWidget()
        self.content_widget.setObjectName('game-project-content')
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        self.content_scroll.setWidget(self.content_widget)
        root_layout.addWidget(self.content_scroll)

        project_box = QGroupBox('游戏项目')
        project_layout = QVBoxLayout(project_box)
        row, self.source_edit, self.source_button = self._path_row(
            '游戏目录：', '选择游戏目录', self._choose_source)
        project_layout.addLayout(row)
        row, self.project_edit, self.new_project_button = self._path_row(
            '项目目录：', '新建项目目录', self._choose_new_project, read_only=True)
        self.open_button = QPushButton('打开已有项目')
        self.open_button.clicked.connect(self._open_project)
        row.addWidget(self.open_button)
        project_layout.addLayout(row)
        row, self.output_edit, self.output_button = self._path_row(
            '输出目录：', '选择输出目录', self._choose_output, read_only=True)
        project_layout.addLayout(row)
        layout.addWidget(project_box)

        self.create_button = QPushButton('扫描并创建项目')
        self.create_button.clicked.connect(self._create_project)
        self.extract_button = QPushButton('提取文本')
        self.extract_button.clicked.connect(self._extract)
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.clicked.connect(self._refresh)
        self.validate_button = QPushButton('离线校验')
        self.validate_button.clicked.connect(self._validate)
        self.resume_scan_button=QPushButton('恢复未完成的扫描')
        self.resume_scan_button.clicked.connect(lambda:self._start_job('resume_scan',{}) if self._require_project() else None)
        self.resume_extract_button=QPushButton('恢复提取…')
        self.resume_extract_button.clicked.connect(lambda:self._start_job('extract_list',{}) if self._require_project() else None)
        self.resume_validation_button=QPushButton('恢复校验…')
        self.resume_validation_button.clicked.connect(lambda:self._start_job('validation_list',{}) if self._require_project() else None)
        self.test_build_button = QPushButton('测试构建')
        self.test_build_button.clicked.connect(lambda: self._build(test=True))
        self.release_build_button = QPushButton('正式构建')
        self.release_build_button.clicked.connect(lambda: self._build(test=False))
        self.resume_build_button=QPushButton('恢复构建…')
        self.resume_build_button.clicked.connect(lambda:self._start_job('build_list',{}) if self._require_project() else None)
        self.export_button = QPushButton('导出译文 JSON')
        self.export_button.clicked.connect(self._export)
        self.import_button = QPushButton('导入译文 JSON')
        self.import_button.clicked.connect(self._import)
        self.translate_button = QPushButton('送往 AiNiee 翻译')
        self.translate_button.clicked.connect(self._request_translate)
        self.font_button=QPushButton('配置副本字体')
        self.font_button.setToolTip('检查静态字形并配置副本字体。游戏内仍须检查显示；短菜单溢出时优先缩短译文。')
        def choose_font():
            if not self._require_project():return
            path,_=QFileDialog.getOpenFileName(self,'选择支持简体中文的字体','','字体 (*.ttf *.otf *.woff *.woff2)')
            if path:self._start_job('font',{'path':path})
        self.font_button.clicked.connect(choose_font)
        self.backend_button=QPushButton('文件回写后端')
        self.backend_button.setToolTip('外部后端会保留工作文件；Stev 还需一份完整游戏副本。选择前请检查工程盘和输出盘余量，旧目录需自行管理。')
        self.backend_button.clicked.connect(self._choose_backend)
        self.compare_backend_button=QPushButton('比较后端提取…')
        self.compare_backend_button.clicked.connect(lambda:self._choose_backend(comparison=True))
        self.images_button=QPushButton('图片文字…')
        self.images_button.clicked.connect(self._images)
        self.migration_button=QPushButton('迁移旧译文…')
        self.migration_button.clicked.connect(self._migrate)
        self.task_controls=QWidget(self)
        control_row=QHBoxLayout(self.task_controls)
        control_row.setContentsMargins(0,0,0,0)
        self.pause_button=QPushButton('暂停任务')
        self.resume_button=QPushButton('继续任务')
        self.cancel_button=QPushButton('取消任务')
        for button,action in [(self.pause_button,'pause'),(self.resume_button,'resume'),(self.cancel_button,'cancel')]:
            button.clicked.connect(lambda checked=False,action=action:self._control_job(action))
            control_row.addWidget(button)
        layout.addWidget(self.task_controls)

        self.tpp_binding=QComboBox()
        self.tpp_binding.setMinimumContentsLength(10)
        self.tpp_binding.setToolTip('选择本工程导出的交换批次；导回时会检查来源与译文版本')
        self.tpp_export_button=QPushButton('导出 .trans')
        self.tpp_open_button=QPushButton('导出并送往 T++')
        self.tpp_pull_button=QPushButton('从运行中的 T++ 导回')
        self.tpp_import_button=QPushButton('从 .trans 文件导回')
        self.tpp_export_button.clicked.connect(lambda:self._tpp_export(False))
        self.tpp_open_button.clicked.connect(lambda:self._tpp_export(True))
        self.tpp_pull_button.clicked.connect(lambda:self._tpp_import(False))
        self.tpp_import_button.clicked.connect(lambda:self._tpp_import(True))
        self.external_tools_button=QPushButton('外部工具管理')
        self.external_tools_button.clicked.connect(lambda:self._external_tools())
        from .ActionTabs import build_action_tabs
        self.action_tabs=build_action_tabs(self)
        layout.insertWidget(1,self.action_tabs)

        summary_box = QGroupBox('摘要')
        summary_layout = QVBoxLayout(summary_box)
        self.summary_label = QLabel('尚未打开项目')
        self.summary_label.setWordWrap(True)
        self.runtime_label = QLabel(f'运行期校验：{_runtime_text("not_run")}')
        self.runtime_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel('')
        self.progress_label.setWordWrap(True)
        self.progress_label.setVisible(False)
        summary_layout.addWidget(self.summary_label)
        summary_layout.addWidget(self.runtime_label)
        summary_layout.addWidget(self.progress_bar)
        summary_layout.addWidget(self.progress_label)
        layout.addWidget(summary_box)

        build_box=QGroupBox('最近完成的构建')
        build_layout=QVBoxLayout(build_box)
        self.last_build_label=QLabel('暂无完成构建')
        self.last_build_label.setTextFormat(Qt.PlainText)
        self.last_build_label.setWordWrap(True)
        build_layout.addWidget(self.last_build_label)
        output_row=QHBoxLayout()
        self.build_output_edit=QLineEdit();self.build_output_edit.setReadOnly(True)
        self.build_output_edit.setObjectName('rpg-build-output')
        self.verify_build_button=QPushButton('校验副本文件')
        self.open_output_button=QPushButton('打开输出目录')
        self.verify_build_button.clicked.connect(lambda:self._check_build(False))
        self.open_output_button.clicked.connect(lambda:self._check_build(True))
        output_row.addWidget(self.build_output_edit,1)
        output_row.addWidget(self.verify_build_button);output_row.addWidget(self.open_output_button)
        build_layout.addLayout(output_row);layout.addWidget(build_box)

        units_box = QGroupBox('翻译单元')
        units_layout = QVBoxLayout(units_box)
        self.element_name_hint = QLabel('当前游戏的 system.elements 参与属性伤害匹配。翻译前请筛选此类型，双击单元 → 保留原文并锁定 → 确定。')
        self.element_name_hint.setWordWrap(True)
        self.element_name_hint.setVisible(False)
        units_layout.addWidget(self.element_name_hint)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel('筛选：'))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('按单元 ID、类型、原文、译文或状态筛选')
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.element_name_hint.linkActivated.connect(lambda _link: self.filter_edit.setText('header:'))
        filter_row.addWidget(self.filter_edit, 1)
        self.cap_label = QLabel('')
        self.cap_label.setVisible(False)
        filter_row.addWidget(self.cap_label)
        units_layout.addLayout(filter_row)
        self.unit_model = _UnitTableModel(self)
        self.unit_table = QTableView()
        self.unit_table.setModel(self.unit_model)
        self.unit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.unit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.unit_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.unit_table.setWordWrap(False)
        self.unit_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.unit_table.verticalHeader().setVisible(False)
        self.unit_table.horizontalHeader().setStretchLastSection(True)
        self.unit_table.doubleClicked.connect(self._edit_unit)
        for column, width in ((0, 220), (1, 90), (4, 110)):
            self.unit_table.setColumnWidth(column, width)
        units_layout.addWidget(self.unit_table)

        issues_box = QGroupBox('问题历史（数据库审计记录）')
        issues_layout = QVBoxLayout(issues_box)
        audit_row = QHBoxLayout()
        audit_row.addWidget(QLabel('脚本与插件指令需要结合实际消费者审查。'))
        audit_row.addStretch(1)
        self.command_audit_button = QPushButton('定位事件指令…')
        self.command_audit_button.clicked.connect(lambda: self._command_audit())
        audit_row.addWidget(self.command_audit_button)
        issues_layout.addLayout(audit_row)
        self.issue_model = _IssueTableModel(self)
        self.issue_table = QTableView()
        self.issue_table.setModel(self.issue_model)
        self.issue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.issue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.issue_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.issue_table.setWordWrap(False)
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.horizontalHeader().setStretchLastSection(True)
        self.issue_table.selectionModel().currentRowChanged.connect(self._issue_selected)
        self.issue_table.doubleClicked.connect(self._issue_command_audit)
        for column, width in ((0, 80), (1, 200), (2, 240), (3, 200)):
            self.issue_table.setColumnWidth(column, width)
        issues_layout.addWidget(self.issue_table)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(units_box)
        splitter.addWidget(issues_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.error_label = QLabel('')
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.status_label = QLabel('就绪')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        layout.addWidget(self.status_label)

    # -- public API -------------------------------------------------------
    @property
    def project_root(self) -> str:
        """Directory that owns ``project.sqlite3`` (empty string when unset)."""

        return self._project_root

    @property
    def game_project_path(self) -> str:
        """Path handed to the AiNiee integration (``<project root>/game-project.json``)."""

        return self._game_project_path

    def is_busy(self) -> bool:
        """True while a worker operation is running; close is refused meanwhile."""

        dialog=getattr(self,'_migration_dialog',None)
        return (self._busy or self._translation_loading or (dialog is not None and dialog.is_busy()) or (self._worker is not None and self._worker.isRunning()) or
                (self._control_worker is not None and self._control_worker.isRunning()))

    def set_project(self, path) -> bool:
        """Open ``path`` (project directory or ``game-project.json``) and refresh."""

        if self.is_busy():
            self._set_status('已有操作正在进行，暂时不能切换项目')
            return False
        if isinstance(path, (bytes, bytearray)):
            self._report_error('项目路径必须是字符串或 Path')
            return False
        try:
            text = os.fspath(path)
        except TypeError:
            self._report_error('项目路径必须是字符串或 Path')
            return False
        if text == '':
            self._report_error('项目路径不能为空')
            return False
        target = Path(text)
        root = target.parent if target.is_file() else target
        self._adopt_project(str(root))
        return self._start_job('refresh', {})

    def closeEvent(self, event) -> None:
        if self.is_busy():
            self._set_status('操作进行中，已拒绝关闭页面；请等待其完成')
            event.ignore()
            return
        super().closeEvent(event)

    # -- pickers ----------------------------------------------------------
    def _choose_source(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, '选择游戏目录', self.source_edit.text().strip())
        if directory:
            self.source_edit.setText(directory)

    def _choose_new_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, '选择新项目目录（必须是空目录）', self.project_edit.text().strip())
        if directory:
            self.project_edit.setText(directory)

    def _choose_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, '选择构建输出目录', self.output_edit.text().strip())
        if directory:
            self.output_edit.setText(directory)

    def _open_project(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, '打开 game-project.json', '', f'游戏项目 (game-project.json);;{_JSON_FILTER}')
        if path:
            self.set_project(path)

    # -- operations -------------------------------------------------------
    def _create_project(self) -> None:
        source = self.source_edit.text().strip()
        project_root = self.project_edit.text().strip()
        if source == '' or project_root == '':
            self._report_error('请先选择游戏目录和新项目目录')
            return
        self._start_job('create', {'source': source, 'project_root': project_root})

    def _extract(self) -> None:
        if self._require_project():
            self._start_job('extract', {})

    def _refresh(self) -> None:
        if self._require_project():
            self._start_job('refresh', {})

    def _validate(self) -> None:
        if self._require_project():
            self._start_job('validate', {})

    def _build(self, *, test: bool) -> None:
        if not self._check_element_name_sop(require_lock=False):
            return
        if not self._require_project():
            return
        output_root = self.output_edit.text().strip()
        if output_root == '':
            self._report_error('请先选择输出目录')
            return
        self._start_job('build', {'output_root': output_root, 'test': bool(test)})

    def _export(self) -> None:
        if not self._require_project():
            return
        path, _selected = QFileDialog.getSaveFileName(
            self, '导出译文到新文件', '', _JSON_FILTER)
        if path == '':
            return
        if os.path.lexists(path):
            self._report_error(f'导出目标已存在，请选择新文件：{path}')
            return
        self._start_job('export', {'path': path})

    def _import(self) -> None:
        if not self._require_project():
            return
        path, _selected = QFileDialog.getOpenFileName(self, '导入译文 JSON', '', _JSON_FILTER)
        if path:
            self._start_job('import', {'path': path}, refresh_after=True)

    def _request_translate(self) -> None:
        if self._project_root == '':
            self._report_error('请先打开或创建项目')
            return
        if not self._check_element_name_sop(require_lock=True):
            return
        self._set_status(f'已请求翻译：{self._game_project_path}')
        self.translateRequested.emit(self._game_project_path)

    def _check_element_name_sop(self, *, require_lock: bool) -> bool:
        if not self._element_name_sop:
            return True
        rows = [row for row in self._unit_rows if row.get('kind') == 'system.elements']
        pending = [row for row in rows if (
            row.get('translation') and row['translation'] != row.get('source')) or (
            require_lock and (not row.get('manual_locked') or row.get('translation') != row.get('source')))]
        if not pending:
            return True
        self.filter_edit.setText('system.elements')
        self._report_error(f'属性名称同时用于逻辑匹配，尚有 {len(pending)} 项需要保留原文。双击单元，点击“保留原文并锁定”，再确定保存。CLI 和其他入口也须遵守此约定。')
        return False

    def set_translation_loading(self,loading):
        self._translation_loading=bool(loading)
        if loading:self._set_status('正在载入 AiNiee 翻译视图…')
        self.progress_bar.setVisible(bool(loading))
        if loading:self.progress_bar.setRange(0,0)
        else:self._clear_progress()
        self._update_enabled()

    def _check_build(self,open_folder):
        if self._latest_build and self._require_project():
            self._start_job('artifact_open' if open_folder else 'artifact_verify',
                {'reference':dict(self._latest_build)})

    def _set_latest_build(self,reference):
        valid=isinstance(reference,dict) and all(isinstance(reference.get(k),str) and reference[k]
            for k in ('build_id','project_id','input_digest','output_path'))
        self._latest_build=dict(reference) if valid else None
        self.build_output_edit.setText(reference['output_path'] if valid else '')
        self.build_output_edit.setToolTip(self.build_output_edit.text())
        if valid:
            mode='测试构建' if reference.get('mode')=='test' else '正式构建'
            self.last_build_label.setText(f"{mode} · {reference['build_id']} · 运行期校验：{_runtime_text(reference.get('runtime_validation'))}")
        else:self.last_build_label.setText('暂无完成构建')
        self._update_enabled()

    def _tpp_export(self,open_client):
        if open_client and not self._ensure_tool('translatorpp'):return
        if self._require_project():self._start_job('tpp_export',{'open':open_client})

    def _external_tools(self,tool=None):
        from .ExternalToolsDialog import ExternalToolsDialog
        ExternalToolsDialog(self,tool).exec_()

    def _ensure_tool(self,tool):
        from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools
        manager=ExternalTools()
        if not manager.status(tool)['ready']:self._external_tools(tool)
        return manager.status(tool)['ready']

    def _images(self):
        if not self._require_project():return
        from .ImageWorkflowDialog import ImageWorkflowDialog
        dialog=ImageWorkflowDialog(self.project_root,self)
        dialog.exec_()
        self._refresh()

    def _migrate(self):
        if not self._require_project():return
        from .MigrationDialog import MigrationDialog
        dialog=MigrationDialog(self.project_root,self);self._migration_dialog=dialog
        try:dialog.exec_()
        finally:self._migration_dialog=None
        self._pending_migration_target=dialog.selected_target
        self._refresh()

    def _choose_backend(self,comparison=False):
        if not self._require_project():return
        dialog=QDialog(self);dialog.setWindowTitle('比较后端提取' if comparison else '选择文件回写后端')
        layout=QFormLayout(dialog)
        files=QComboBox();files.addItems([path for path in self._backend_files if not comparison or path.endswith('.json')])
        backends=QComboBox()
        from ModuleFolders.Infrastructure.GameAdapters.Capabilities import capability_matrix,route_support
        matrix=capability_matrix()
        for value,cid in [('native','rpgmaker-native'),('stev','stev'),('rpgmtl','rpgmtl'),('sextractor','sextractor')]:
            if comparison and value=='native':continue
            backends.addItem(matrix[cid]['label'],value)
        root=QLineEdit();browse=QPushButton('选择工具源码目录')
        configure=QPushButton('下载 / 配置工具')
        root_row=QHBoxLayout();root_row.addWidget(root);root_row.addWidget(browse);root_row.addWidget(configure)
        from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools
        manager=ExternalTools()
        def configure_tool():
            self._external_tools(backends.currentData())
            status=manager.status(backends.currentData())
            if status['ready']:root.setText(status['path'])
        configure.clicked.connect(configure_tool)
        def choose_root():
            path=QFileDialog.getExistingDirectory(dialog,'选择已安装的可信工具源码目录',root.text())
            if path:root.setText(path)
        browse.clicked.connect(choose_root)
        def changed_file():
            for index in range(backends.count()):
                available=comparison or route_support(backends.itemData(index),files.currentText())['status']!='unsupported'
                backends.model().item(index).setEnabled(available)
            route=self._backend_routes.get(files.currentText(),{})
            index=max(0,backends.findData(route.get('backend','native')))
            backends.setCurrentIndex(index if backends.model().item(index).isEnabled() else 0)
            root.setText(route.get('backend_root',''))
            changed_backend()
        def changed_backend():
            enabled=backends.currentData()!='native'
            root.setEnabled(enabled);browse.setEnabled(enabled);configure.setEnabled(enabled)
            if enabled:
                route=self._backend_routes.get(files.currentText(),{})
                status=manager.status(backends.currentData())
                root.setText(route.get('backend_root','') if route.get('backend')==backends.currentData()
                    else status['path'] if status['ready'] else '')
            note.setText('比较会保存覆盖报告，保留当前译文与回写后端设置。额外提取项仍需核对显示用途。' if comparison else
                ('RPGMTL 仅回写已批准的 JS 文字，候选必须通过源码位置、AST 和区间外字节核对。'
                    if files.currentText().endswith('.js') else
                    '兼容后端需要该文件已有接受的译文，并先通过候选回写校验。'))
        files.currentIndexChanged.connect(changed_file)
        backends.currentIndexChanged.connect(changed_backend)
        layout.addRow('文件',files);layout.addRow('后端',backends);layout.addRow('源码目录',root_row)
        note=QLabel()
        note.setWordWrap(True);layout.addRow(note)
        changed_file()
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addRow(buttons)
        dialog.resize(620,220)
        if dialog.exec_()==QDialog.Accepted:
            if backends.currentData()!='native' and not root.text().strip():
                self._report_error('请选择已安装的后端源码目录');return
            self._start_job('backend_compare' if comparison else 'backend_route',{'relative_path':files.currentText(),
                'backend':backends.currentData(),'backend_root':root.text().strip() or None},refresh_after=not comparison)

    def _tpp_import(self,from_file):
        if not self._require_project():return
        if not from_file and not self._ensure_tool('translatorpp'):return
        binding=self.tpp_binding.currentText()
        if not binding:
            self._report_error('请先从当前工程导出一个 Translator++ 交换批次')
            return
        payload={'binding':binding}
        if from_file:
            path,_=QFileDialog.getOpenFileName(self,'选择 T++ 保存的译文工程','','Translator++ (*.trans)')
            if not path:return
            payload['path']=path
        self._start_job('tpp_import',payload,refresh_after=True)

    # -- table interaction ------------------------------------------------
    def _edit_unit(self, index) -> None:
        if self.is_busy():
            self._set_status('操作进行中，暂时不能编辑译文')
            return
        if not index.isValid():
            return
        row = self.unit_model.row_at(index.row())
        if row is None:
            return
        dialog = _TranslationDialog(row, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        text, locked = dialog.values()
        self._start_job('commit_unit', {
            'row': {
                'unit_id': row.get('unit_id', ''),
                'text': text,
                'source_hash': row.get('source_hash', ''),
                'expected_revision': row.get('expected_revision', 0),
            },
            'lock': locked,
        }, refresh_after=True)

    def _issue_selected(self, current, _previous) -> None:
        if not current.isValid():
            return
        row = self.issue_model.row_at(current.row())
        if row is None:
            return
        unit_id = str(row.get('unit_id') or '')
        if unit_id:
            self._select_unit(unit_id)
        else:
            self._set_status(f"问题 {row.get('code', '')} 未关联单元：{row.get('path', '')}")

    def _command_audit(self, initial_filter=''):
        self._pending_command_filter = initial_filter
        self._start_job('command_audit', {})

    def _issue_command_audit(self, index):
        row = self.issue_model.row_at(index.row()) if index.isValid() else None
        if row and row.get('code') == 'unsupported_command_candidate':
            command = row.get('details', {}).get('command', '')
            needle = command[7:] if command.startswith('plugin:') and command != 'plugin:unknown' else ''
            self._command_audit(needle)

    def _select_unit(self, unit_id: str) -> None:
        if self.unit_model.row_for_unit(unit_id) is None and self.filter_edit.text() != '':
            self.filter_edit.clear()
        row = self.unit_model.row_for_unit(unit_id)
        if row is None:
            self._set_status(f'单元 {unit_id} 不在当前数据集中，请刷新或重新对账')
            return
        self.unit_table.selectRow(row)
        self.unit_table.scrollTo(self.unit_model.index(row, 0), QAbstractItemView.PositionAtCenter)
        self._set_status(f'已选中单元 {unit_id}')

    # -- data application -------------------------------------------------
    def _adopt_project(self, root: str) -> None:
        if root!=self._project_root:self._set_latest_build(None)
        self._project_root = str(root)
        self._game_project_path = os.path.join(self._project_root, 'game-project.json')
        self.project_edit.setText(self._project_root)
        self._update_enabled()

    def _apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().casefold()
        rows = [row for row in self._unit_rows if needle == '' or needle in self._row_text(row)]
        # QTableView requests visible cells from the model. Keep every matching
        # row addressable, including issue navigation beyond the former cap.
        self.unit_model.set_rows(rows)
        self.cap_label.setText(f'{len(rows)} / {len(self._unit_rows)} 行')
        self.cap_label.setVisible(True)

    @staticmethod
    def _row_text(row: dict) -> str:
        return ' '.join((
            str(row.get('unit_id', '')),
            str(row.get('kind', '')),
            str(row.get('scene_id', '')),
            str(row.get('source', '')),
            str(row.get('translation', '')),
            _status_text(row),
        )).casefold()

    def _apply_snapshot(self, result: dict) -> None:
        self._set_latest_build(result.get('latest_build'))
        self._element_name_sop = bool(result.get('element_name_sop'))
        self._unit_rows = list(result.get('units', []))
        hint = '当前游戏的 system.elements 参与属性伤害匹配。翻译前请筛选此类型，双击单元 → 保留原文并锁定 → 确定。'
        if any(str(row.get('scene_id', '')).startswith('header:') for row in self._unit_rows):
            hint += '<br>装饰性英文小标题使用 11 像素高位图，部分简中文字形会裁切。请<a href="headers">筛选装饰标题</a>，保留英文并锁定；Experience 标题短写为 E X P，其余保留原文。CLI 和其他入口也遵守此约定。'
        if any(row.get('scene_id') == 'heart:derived-status' for row in self._unit_rows):
            hint += '<br>人物页“未経験”占位词同时参与比较，译文不要使用伴侣姓名；伴侣姓名仍须保留原文。修改身份或使用改过姓名的存档后须重新核对。可筛选 heart:derived-status 查看这组文字。'
        self.element_name_hint.setText(hint)
        self.element_name_hint.setVisible(self._element_name_sop)
        self._issue_rows = list(result.get('issues', []))
        self._backend_files=list(result.get('backend_files',[]))
        self._backend_routes=dict(result.get('backend_routes',{}))
        self._apply_filter()
        self.issue_model.set_rows(self._issue_rows)
        selected=self.tpp_binding.currentText()
        self.tpp_binding.clear()
        self.tpp_binding.addItems(result.get('tpp_bindings',[]))
        if selected in result.get('tpp_bindings',[]):self.tpp_binding.setCurrentText(selected)
        summary = result.get('summary') or {}
        source_gib=max(0,int(summary.get('source_total_bytes',0) or 0))/(1024**3)
        disk_hint=(f'完整输出副本的资源基线约 {source_gib:.2f} GiB；另需快照、字体/图片和暂存余量。'
            '旧输出及失败目录会保留，请先检查目标盘可用空间。')
        self.test_build_button.setToolTip(disk_hint)
        self.release_build_button.setToolTip(disk_hint)
        self.backend_button.setToolTip(f'Stev 将额外保留一份约 {source_gib:.2f} GiB 的完整工作副本；'
            '其他后端也会保留任务文件。请同时检查工程盘和输出盘余量，旧目录需自行管理。')
        unit_count = int(summary.get('unit_count', len(self._unit_rows)) or 0)
        translated = int(summary.get('translated', 0) or 0)
        incomplete = int(summary.get('untranslated', max(unit_count - translated, 0)) or 0)
        issue_count = int(summary.get('issue_count', len(self._issue_rows)) or 0)
        self.summary_label.setText(
            f"项目：{summary.get('project_id', '')}    引擎：{summary.get('engine', '')}"
            f"    单元：{unit_count}    已翻译：{translated}    未完成翻译：{incomplete}"
            f"    历史问题：{issue_count}    数据集版本：{summary.get('dataset_revision', 0)}"
            f"    提取完成：{'是' if summary.get('extraction_complete') else '否'}"
        )

    def _show_validation(self, result: dict) -> None:
        runtime = result.get('runtime_validation', 'not_run')
        self.runtime_label.setText(f'运行期校验：{_runtime_text(runtime)}')
        issues = list(result.get('issues', []))
        self._issue_rows=issues
        self.issue_model.set_rows(issues)
        codes = '，'.join(sorted({str(issue.get('code', '')) for issue in issues})[:5])
        detail = f'；问题代码：{codes}' if codes else ''
        passed = '通过' if result.get('passed') else '未通过'
        self._set_status(f'离线校验{passed}（{len(issues)} 个问题）{detail}')

    def _show_build(self, manifest: dict) -> None:
        self._set_latest_build({k:manifest.get(k) for k in ('build_id','project_id','input_digest','output_path','mode','runtime_validation')})
        runtime = manifest.get('runtime_validation', 'not_run')
        self.runtime_label.setText(f'运行期校验：{_runtime_text(runtime)}')
        missing = (len(manifest['missing_translation_unit_ids']) if 'missing_translation_unit_ids' in manifest
                   else manifest.get('untranslated_unit_count',0))
        self._set_status(
            f"构建完成：{manifest.get('build_id', '')}    模式：{manifest.get('mode', '')}"
            f"    输出：{manifest.get('output_path', '')}    未翻译单元：{missing}"
        )

    # -- worker plumbing --------------------------------------------------
    def _start_job(self, operation: str, payload: dict, *, refresh_after: bool = False) -> bool:
        if self._busy or self._translation_loading:
            self._set_status('已有操作正在进行，请等待完成')
            return False
        data = dict(payload)
        data['project'] = self._project_root
        worker = _GameProjectJob(operation, data, self)
        self._worker = worker
        self._active_job = None
        self._busy = True
        self._refresh_after = bool(refresh_after)
        self.error_label.setVisible(False)
        worker.progressed.connect(self._on_progress)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.jobStarted.connect(self._job_started)
        worker.finished.connect(self._on_worker_finished)
        self._update_enabled()
        self._set_status(f"正在执行：{_OPERATION_LABELS.get(operation, operation)}")
        worker.start()
        return True

    def _job_started(self,info):
        self._active_job=dict(info)
        self._update_enabled()

    def _control_job(self,action):
        if self._translation_loading:
            if action=='cancel':self.translationCancelRequested.emit()
            return
        if not self._active_job or self._control_worker is not None:return
        info=self._active_job
        worker=_GameProjectJob('job_action',{'project':info['project_root'],
            'job_id':info['job_id'],'action':action},self)
        self._control_worker=worker
        worker.succeeded.connect(lambda result:self._set_status('任务控制：'+result['state']))
        worker.failed.connect(self._report_error)
        def finished():
            self._control_worker=None
            worker.deleteLater()
            self._update_enabled()
        worker.finished.connect(finished)
        worker.start()

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, max(int(total), 0))
        self.progress_bar.setValue(int(done))
        self.progress_label.setVisible(True)
        self.progress_label.setText(f'{done}/{total} {label}')

    def _clear_progress(self) -> None:
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(False)
        self.progress_label.setText('')

    def _on_succeeded(self, result: dict) -> None:
        self._busy = False
        self._active_job = None
        self._clear_progress()
        self._update_enabled()
        operation = str(result.get('operation', ''))
        if result.get('project_root'):
            self._adopt_project(str(result['project_root']))
        if 'units' in result:
            self._apply_snapshot(result)
            target=getattr(self,'_pending_migration_target','')
            if target:self._pending_migration_target='';self._select_unit(target)
        if operation == 'validate':
            self._show_validation(result.get('result') or {})
        elif operation == 'cancelled':
            self._set_status('任务已取消。已有译文和检查点已保留；未发布构建半成品。')
        elif operation == 'font':
            coverage=result['result']['coverage']
            self._set_status(f'字体已配置到工程副本；当前输出文本缺字：{coverage["missing_count"]}。运行期效果尚待验证。')
        elif operation == 'build':
            self._show_build(result.get('manifest') or {})
        elif operation in {'artifact_verify','artifact_open'}:
            report=result['result']
            if not report['passed']:
                self._report_error('副本文件与构建登记不一致；已拒绝打开。变化或额外文件：'+
                    '，'.join((report['changed_files']+report['unexpected_files'])[:5]))
            elif operation=='artifact_open':
                if QDesktopServices.openUrl(QUrl.fromLocalFile(report['output_path'])):
                    self._set_status('已请求文件管理器打开经过校验的输出目录；未启动游戏。')
                else:self._report_error('系统未能打开输出目录，请根据上方路径手动打开')
            else:self._set_status('副本文件校验通过；运行期校验：'+_runtime_text(report['runtime_validation']))
        elif operation == 'export':
            self._set_status(f"已导出 {result.get('row_count', 0)} 条译文到 {result.get('path', '')}")
        elif operation == 'import':
            self._set_status(f"导入完成：{_describe_results(result.get('results'))}")
        elif operation == 'tpp_export':
            exchange=result['result']
            self.tpp_binding.insertItem(0,exchange['binding_id']);self.tpp_binding.setCurrentIndex(0)
            self._set_status(f"已导出 {exchange['unit_count']} 条到 {exchange['file']}")
        elif operation == 'tpp_import':
            self._set_status(f"T++ 导回完成：{_describe_results(result['result'].get('results'))}")
        elif operation == 'backend_route':
            self._set_status(f"回写后端已设置：{result['result']['relative_path']} → {result['result']['backend']}")
        elif operation == 'backend_compare':
            report=result['result'];counts=report['counts']
            self._set_status(f"提取比较完成：重合 {counts['overlap']}，原生独有 {counts['native_only']}，"
                f"后端额外 {counts['backend_only']}，有歧义 {counts['ambiguous']}。报告：{report['report_path']}")
            from .ComparisonReportDialog import ComparisonReportDialog
            ComparisonReportDialog(report, self).exec_()
        elif operation == 'command_audit':
            from .CommandAuditDialog import CommandAuditDialog
            result_info = result['result']
            self._set_status(f"指令盘点完成：{result_info['document_count']} 个文件，{result_info['record_count']} 处指令块。")
            dialog = CommandAuditDialog(result['report'], result_info['report_path'], self,
                                        initial_filter=getattr(self, '_pending_command_filter', ''))
            self._pending_command_filter = ''
            dialog.exec_()
        elif operation == 'commit_unit':
            if result.get('changed'):
                self._set_status(
                    f"单元 {result.get('unit_id', '')} 已提交："
                    f"{_describe_results(result.get('results'))}"
                )
            else:
                self._set_status('译文与锁定状态没有变化')
        elif operation == 'create':
            self._set_status(f'项目已创建：{self._project_root}')
        elif operation == 'extract':
            recovery=result.get('recovery',{})
            self._set_status('提取完成，摘要与问题已刷新；复用 '
                f"{recovery.get('reused_json_files',0)} 个 JSON、{recovery.get('reused_js_rules',0)} 项 JS 规则")
        elif operation == 'build_list':
            if not result['items']:self._set_status('没有可恢复的构建记录')
            else:
                selected,ok=QInputDialog.getItem(self,'恢复构建','选择冻结输入的构建（不会覆盖当前译文）：',result['items'],0,False)
                if ok:QTimer.singleShot(0,lambda:self._start_job('build_resume',{'build_id':selected.split()[0]}))
        elif operation == 'validation_list':
            if not result['items']:self._set_status('没有可恢复的校验记录')
            else:
                labels=[f"{j['job_id']} {j['run_state']} 已检查 {j['checkpoint']} 项" for j in result['items']]
                selected,ok=QInputDialog.getItem(self,'恢复校验','选择检查点；工程有新编辑时须重新校验：',labels,0,False)
                if ok:QTimer.singleShot(0,lambda:self._start_job('validation_resume',{'job_id':selected.split()[0]}))
        elif operation == 'extract_list':
            if not result['items']:self._set_status('没有可恢复的提取记录')
            else:
                labels=[f"{j['job_id']} {j['run_state']} 检查点 {j['checkpoint']}" for j in result['items']]
                selected,ok=QInputDialog.getItem(self,'恢复提取','选择检查点（使用当时冻结的提取规则）：',labels,0,False)
                if ok:QTimer.singleShot(0,lambda:self._start_job('extract_resume',{'job_id':selected.split()[0]}))
        elif operation == 'refresh':
            self._set_status('已从项目数据库刷新')
        if self._refresh_after:
            self._refresh_after = False
            self._start_job('refresh', {})

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self._active_job = None
        self._refresh_after = False
        self._clear_progress()
        self._update_enabled()
        self._report_error(message)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if worker is self._worker:
            self._worker = None
            if self._busy:  # no result arrived; never leave the page stuck busy
                self._busy = False
                self._clear_progress()
                self._update_enabled()
        if worker is not None:
            worker.deleteLater()

    # -- small helpers ----------------------------------------------------
    def _require_project(self) -> bool:
        if self._project_root == '':
            self._report_error('请先打开或创建项目')
            return False
        return True

    def _update_enabled(self) -> None:
        busy = self._busy or self._translation_loading
        self.external_tools_button.setEnabled(not busy)
        has_project = self._project_root != ''
        for button in (self.create_button, self.source_button, self.new_project_button,
                       self.open_button, self.output_button):
            button.setEnabled(not busy)
        self.source_edit.setEnabled(not busy)
        for button in (self.extract_button, self.refresh_button, self.validate_button,
                       self.test_build_button, self.release_build_button,self.resume_build_button, self.export_button,
                       self.import_button,self.font_button,self.images_button,self.tpp_export_button,self.tpp_open_button,
                       self.tpp_pull_button,self.tpp_import_button,self.resume_scan_button,self.resume_extract_button,self.resume_validation_button):
            button.setEnabled(not busy and has_project)
        self.backend_button.setEnabled(not busy and has_project)
        self.compare_backend_button.setEnabled(not busy and has_project)
        self.command_audit_button.setEnabled(not busy and has_project)
        self.migration_button.setEnabled(not busy and has_project)
        for button in (self.pause_button,self.resume_button,self.cancel_button):
            button.setEnabled(self._active_job is not None and self._control_worker is None)
        if self._translation_loading:self.cancel_button.setEnabled(True)
        self.task_controls.setVisible(self._active_job is not None or self._translation_loading)
        for button in (self.verify_build_button,self.open_output_button):
            button.setEnabled(not busy and has_project and self._latest_build is not None)
        # The main window owns translation; hand over only after page work ends.
        self.translate_button.setEnabled(has_project and not busy)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(str(message))

    def _report_error(self, message: str) -> None:
        self.error_label.setText(f'错误：{message}')
        self.error_label.setVisible(True)
        self._set_status('操作未完成')
