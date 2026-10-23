"""Background preparation of a detached game-project cache projection."""
from PyQt5.QtCore import QThread, pyqtSignal


class _Cancelled(Exception):
    """Raised inside the worker when cooperative cancellation is requested."""


class GameTranslationLoadJob(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, project_path, parent=None):
        super().__init__(parent)
        self.project_path = project_path

    def _check(self):
        if self.isInterruptionRequested():
            raise _Cancelled()

    def run(self):
        try:
            from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
            from ModuleFolders.Service.GameProject.CacheBridge import build_projection
            self._check()
            with GameProjectService(self.project_path) as service:
                self._check()
                metadata = service.store.metadata()
                if metadata.get('extraction_complete') is not True:
                    raise ValueError(
                        'GAME_EXTRACTION_REQUIRED: 请先完成游戏工程提取，再加载翻译工程。'
                    )
                project = build_projection(service.store, check=self._check)
                self._check()
            self._check()
            self.succeeded.emit(project)
        except _Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.failed.emit(f'{type(exc).__name__}: {exc}')
