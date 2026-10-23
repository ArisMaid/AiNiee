"""One place to download pinned tools or register a trusted existing installation."""
import threading

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QPlainTextEdit, QFileDialog)
from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools


class _ToolJob(QThread):
    progress = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(self, manager, action, tool, path='', parent=None):
        super().__init__(parent)
        self.manager, self.action, self.tool, self.path = manager, action, tool, path
        self.cancel = threading.Event()

    def run(self):
        try:
            if self.action == 'install':
                result = self.manager.install(self.tool, self.progress.emit, self.cancel)
            elif self.action == 'select':
                result = self.manager.select(self.tool, self.path)
            elif self.action == 'start':
                result = self.manager.start_translatorpp(self.progress.emit, self.cancel)
            else:
                result = self.manager.status(self.tool)
            self.result.emit(result)
        except Exception as exc:
            self.progress.emit(str(exc))


class ExternalToolsDialog(QDialog):
    def __init__(self, parent=None, tool=None):
        super().__init__(parent)
        self.manager = ExternalTools()
        self.worker = None
        self.setWindowTitle('外部工具管理')
        self.resize(850, 590)
        layout = QVBoxLayout(self)
        note = QLabel('工具按需下载，首次配置需要联网。选择已有安装即表示信任该目录中的程序。\n'
            '配置完成后返回原功能继续操作；兼容后端仍需按文件选择路由并校验候选。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tools = QComboBox()
        for key, spec in self.manager.catalog['tools'].items():
            self.tools.addItem(spec['label'], key)
        if tool:
            self.tools.setCurrentIndex(max(0, self.tools.findData(tool)))
        layout.addWidget(self.tools)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setOpenExternalLinks(True)
        layout.addWidget(self.details)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        layout.addWidget(self.status, 1)
        self.buttons = []
        row = QHBoxLayout()
        for text, action in [('一键下载配置', 'install'), ('选择已有安装', 'select'),
                ('检查配置', 'check'), ('启动并检查 T++', 'start')]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, a=action: self.run(a))
            row.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(row)
        self.cancel_button = QPushButton('取消当前配置')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.cancel_button)
        self.close_button = QPushButton('返回')
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)
        self.tools.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        spec = self.manager.catalog['tools'][self.tools.currentData()]
        self.details.setText(f'{spec["description"]}\n固定版本：{spec["version"]}\n'
            f'下载约 {spec["bytes"] / 1048576:.1f} MiB（首次可能另需解压组件或语言包）。\n'
            f'安装位置：{self.manager.home}\n来源：{spec["homepage"]}')
        self.buttons[-1].setEnabled(self.tools.currentData() == 'translatorpp')
        self.status.clear()
        self.run('check')

    def run(self, action):
        if self.worker:
            return
        path = ''
        if action == 'select':
            path = QFileDialog.getExistingDirectory(self, '选择可信工具安装目录（OCR 目录应含 tessdata）')
            if not path:
                return
        self.tools.setEnabled(False)
        for button in self.buttons:
            button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.cancel_button.setEnabled(action in ('install', 'start'))
        self.status.appendPlainText('正在检查…' if action == 'check' else '正在处理，请稍候…')
        self.worker = _ToolJob(self.manager, action, self.tools.currentData(), path, self)
        self.worker.progress.connect(self.status.appendPlainText)
        self.worker.result.connect(self.completed)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def completed(self, result):
        if 'ready' in result:
            self.status.appendPlainText(result['message'] + ('\n' + result['path'] if result['path'] else '')
                + ('\n可以返回原功能继续。' if result['ready'] else '\n请选择“一键下载配置”或“选择已有安装”。'))
        else:
            self.status.appendPlainText('Translator++ 本地 API 已就绪。')

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.appendPlainText('已请求取消；等待当前网络读取或解压步骤结束，保留现场。')

    def finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.tools.setEnabled(True)
        for button in self.buttons:
            button.setEnabled(True)
        self.buttons[-1].setEnabled(self.tools.currentData() == 'translatorpp')
        self.close_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def done(self, result):
        if self.worker:
            self.status.appendPlainText('请取消或等待当前操作完成后返回。')
            return
        super().done(result)

    def closeEvent(self, event):
        if self.worker:
            self.cancel()
            event.ignore()
        else:
            super().closeEvent(event)
