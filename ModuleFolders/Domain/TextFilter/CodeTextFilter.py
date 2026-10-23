from __future__ import annotations
import threading

from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
from ModuleFolders.Service.Cache.CacheProject import CacheProject, ProjectType


class CodeTextFilter:
    magika = None
    _magika_lock = threading.Lock()
    SUPPORT_PROJECT_TYPES = frozenset([ProjectType.MTOOL])

    def get_label(self, text: str):
        if self.magika is None:
            with self._magika_lock:
                if type(self).magika is None:
                    from magika import Magika
                    type(self).magika = Magika()
        result = self.magika.identify_bytes(text.encode())
        return result.output.label

    def filter_text(self, event_data: CacheProject):
        if not (event_data.file_project_types & self.SUPPORT_PROJECT_TYPES):
            return
        from magika.types.content_type_label import ContentTypeLabel
        for item in event_data.items_iter(self.SUPPORT_PROJECT_TYPES):
            if item.translation_status != TranslationStatus.UNTRANSLATED:
                continue
            label = self.get_label(item.source_text)
            if label != ContentTypeLabel.TXT:
                item.translation_status = TranslationStatus.QUESTIONABLE
