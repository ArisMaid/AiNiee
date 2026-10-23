"""Read-only comparison report viewer built from validated JSON data only."""

import json

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTableView,
    QVBoxLayout,
)


_CATEGORY_ROWS = (
    ('overlap', '重合'),
    ('backend_only', '后端额外'),
    ('ambiguous', '位置歧义'),
    ('native_only', '原生独有'),
    ('type_conflicts', '字段类型冲突'),
)
_POINTER_PREVIEW_LIMIT = 100
_CELL_PREVIEW_LIMIT = 160


def _text(value):
    return '' if value is None else str(value)


def _preview(value, limit=_CELL_PREVIEW_LIMIT):
    """Collapse one value to a single-line table preview."""
    text = ' '.join(_text(value).split())
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)] + '…'


def _json_text(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return _text(value)


def _nonnegative_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _lookup(mapping, key):
    try:
        return mapping.get(key)
    except TypeError:
        return None


def _contains(values, key):
    try:
        return key in values
    except TypeError:
        return False


class _ComparisonModel(QAbstractTableModel):
    headers = ('状态', '原文', '位置', '角色 / 编码 / 单元')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.DisplayRole:
            values = row['display']
            if 0 <= index.column() < len(values):
                return values[index.column()]
            return None
        if role == Qt.ToolTipRole:
            return row['tooltip']
        return None


class ComparisonReportDialog(QDialog):
    """Read-only view of a coverage comparison report."""

    def __init__(self, report, parent=None):
        super().__init__(parent)
        if not isinstance(report, dict):
            report = {}
        self._report = report
        self.setWindowTitle('提取比较报告（只读）')
        self.resize(1160, 740)

        self._entries = {}
        for category_key, _label in _CATEGORY_ROWS:
            value = report.get(category_key)
            self._entries[category_key] = value if isinstance(value, list) else []

        backend_records = report.get('backend_records')
        self._has_backend_records = isinstance(backend_records, list)
        native_occurrences = report.get('native_occurrences')
        self._has_native_occurrences = isinstance(native_occurrences, list)

        self._backend_by_index = {}
        if self._has_backend_records:
            for annotation in backend_records:
                if not isinstance(annotation, dict):
                    continue
                try:
                    self._backend_by_index[annotation.get('record_index')] = annotation
                except TypeError:
                    pass

        self._native_by_key = {}
        if self._has_native_occurrences:
            for occurrence in native_occurrences:
                if not isinstance(occurrence, dict):
                    continue
                try:
                    self._native_by_key[(occurrence.get('unit_id'), occurrence.get('pointer'))] = occurrence
                except TypeError:
                    pass

        raw_groups = report.get('candidate_pointer_groups')
        raw_groups = raw_groups if isinstance(raw_groups, dict) else {}
        self._group_pointers = {}
        self._group_search_text = {}
        for group_id, pointers in raw_groups.items():
            if isinstance(pointers, (list, tuple)):
                normalized = pointers
            elif isinstance(pointers, str):
                normalized = [pointers]
            else:
                normalized = []
            # Cache each shared group's searchable text once, never per row.
            self._group_pointers[group_id] = normalized
            self._group_search_text[group_id] = ' '.join(
                _text(pointer) for pointer in normalized
            ).casefold()

        self._rows = []
        for category_key, label in _CATEGORY_ROWS:
            for entry in self._entries[category_key]:
                self._rows.append(self._build_row(category_key, label, entry))

        layout = QVBoxLayout(self)
        backend = _text(report.get('backend')) or '（未提供）'
        relative_path = _text(report.get('relative_path')) or '（未提供）'
        counts = report.get('counts')
        counts = counts if isinstance(counts, dict) else {}
        count_parts = []
        for category_key, label in _CATEGORY_ROWS:
            value = counts.get(category_key)
            if not isinstance(value, int) or isinstance(value, bool):
                value = len(self._entries[category_key])
            count_parts.append(f'{label} {value}')
        notice = QLabel(
            f'后端：{backend} · 文件：{relative_path}\n'
            + ' · '.join(count_parts)
            + '\n位置重合不代表已验证显示用途；此窗口不添加规则或回写译文。'
            + ('\n字段类型未检查：旧报告或未提供原始 JSON，请重新比较。' if report.get('type_check') != 'complete' else '')
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel('筛选原文、单元 ID、指针、角色、后端定位或候选组指针：'))
        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        filter_row.addWidget(self.filter_edit)
        self.count_label = QLabel()
        filter_row.addWidget(self.count_label)
        layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Vertical)
        self.model = _ComparisonModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((95, 390, 420, 235)):
            self.table.setColumnWidth(column, width)
        splitter.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        splitter.setSizes([380, 220])
        layout.addWidget(splitter)

        report_path = _text(report.get('report_path')) or '（未提供）'
        path_label = QLabel('本地报告：' + report_path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.filter_edit.textChanged.connect(self._filter)
        self._filter()

    def _build_row(self, category_key, label, entry):
        entry = entry if isinstance(entry, dict) else {}
        record_index = entry.get('record_index')
        unit_id = entry.get('unit_id')
        pointer = entry.get('pointer')
        backend = _lookup(self._backend_by_index, record_index) if record_index is not None else None
        native = None
        native_side = category_key in ('overlap', 'native_only') or (category_key == 'type_conflicts' and entry.get('side') == 'native')
        if native_side:
            native = _lookup(self._native_by_key, (unit_id, pointer))

        group_id = entry.get('candidate_pointer_group')
        group_pointers = None
        group_count = 0
        if group_id is not None:
            group_pointers = _lookup(self._group_pointers, group_id)
            if group_pointers is None:
                group_count = _nonnegative_int(entry.get('candidate_pointer_count'))
            else:
                group_count = len(group_pointers)

        inline_pointers = []
        if group_id is None:
            raw_inline = entry.get('candidate_pointers')
            if isinstance(raw_inline, (list, tuple)):
                inline_pointers = raw_inline
            elif raw_inline is not None:
                inline_pointers = [raw_inline]

        search_parts = [label]
        for value in (unit_id, pointer, record_index, group_id):
            text = _text(value)
            if text:
                search_parts.append(text)
        if backend is not None:
            text = _text(backend.get('text'))
            if text:
                search_parts.append(text)
            locator = backend.get('locator')
            if locator is not None:
                search_parts.append(_json_text(locator))
        if native is not None:
            for key in ('source_text', 'role', 'kind', 'value_codec'):
                text = _text(native.get(key))
                if text:
                    search_parts.append(text)
        for candidate in inline_pointers:
            text = _text(candidate)
            if text:
                search_parts.append(text)
        search_text = ' '.join(search_parts).casefold()

        source_value = ''
        if category_key == 'native_only' or (category_key == 'type_conflicts' and native_side):
            if native is not None and native.get('source_text') is not None:
                source_value = native.get('source_text')
        elif backend is not None and backend.get('text') is not None:
            source_value = backend.get('text')
        elif native is not None and native.get('source_text') is not None:
            source_value = native.get('source_text')

        if native_side:
            location_value = _preview(pointer, 200) or '（未提供位置）'
        else:
            location_parts = []
            if record_index is not None:
                location_parts.append(f'记录 #{_text(record_index)}')
            locator = backend.get('locator') if backend is not None else None
            if locator is not None:
                locator_preview = _preview(_json_text(locator), 90)
                if locator_preview:
                    location_parts.append(locator_preview)
            if group_id is not None:
                location_parts.append(f'候选组 {_preview(group_id, 40)} · {group_count} 个指针')
            elif inline_pointers:
                sample = ', '.join(_preview(item, 36) for item in inline_pointers[:3])
                suffix = f'：{sample}' if sample else ''
                location_parts.append(f'候选指针 {len(inline_pointers)} 个{suffix}')
            else:
                location_parts.append('无候选位置')
            location_value = _preview(' · '.join(location_parts), 240)

        unit_role_parts = []
        if native_side:
            if native is not None:
                if native.get('role') is not None:
                    unit_role_parts.append('角色 ' + _text(native.get('role')))
                if native.get('value_codec') is not None:
                    unit_role_parts.append('编码 ' + _text(native.get('value_codec')))
            if unit_id is not None:
                unit_role_parts.append(_text(unit_id))
        elif record_index is not None:
            unit_role_parts.append(f'记录 #{_text(record_index)}')
        if not unit_role_parts:
            unit_role_parts.append('（未提供）')

        display = (
            label,
            _preview(source_value),
            location_value,
            _preview(' · '.join(unit_role_parts), 80),
        )
        return {
            'category_key': category_key,
            'classification': entry,
            'category': label,
            'backend': backend,
            'native': native,
            'record_index': record_index,
            'unit_id': unit_id,
            'pointer': pointer,
            'group_id': group_id,
            'group_pointers': group_pointers,
            'group_count': group_count,
            'inline_pointers': inline_pointers,
            'search_text': search_text,
            'display': display,
            'tooltip': _preview(f'{label} · {location_value}', 200),
        }

    def _missing_backend_notice(self):
        if not self._has_backend_records:
            return '此旧报告缺少后端记录注释，无法核对后端原文；请重新计算比较报告后再核对。'
        return '此报告中未找到该记录编号的后端注释；请重新计算比较报告后再核对。'

    def _missing_native_notice(self):
        if not self._has_native_occurrences:
            return '此旧报告缺少原生出现注释，无法核对原生逻辑来源；请重新计算比较报告后再核对。'
        return '此报告中未找到该单元与指针对应的原生注释；请重新计算比较报告后再核对。'

    def _location_is_truncated(self, row):
        if row['group_id'] is not None:
            return row['group_pointers'] is not None and len(row['group_pointers']) > _POINTER_PREVIEW_LIMIT
        return len(row['inline_pointers']) > _POINTER_PREVIEW_LIMIT

    def _location_details(self, row):
        category_key = row['category_key']
        if category_key in ('overlap', 'native_only') or (category_key == 'type_conflicts' and row['classification'].get('side') == 'native'):
            location = {'unit_id': row['unit_id'], 'pointer': row['pointer']}
            if category_key == 'overlap' and row['record_index'] is not None:
                location['record_index'] = row['record_index']
            return location

        location = {}
        if row['record_index'] is not None:
            location['record_index'] = row['record_index']

        if row['group_id'] is not None:
            location['candidate_pointer_group'] = row['group_id']
            location['candidate_pointer_count'] = row['group_count']
            pointers = row['group_pointers']
            if pointers is None:
                location['candidate_pointers_available'] = False
                location['location_note'] = '报告中未找到该候选指针组的内容；完整信息仍以原始报告为准。'
            else:
                location['candidate_pointers_preview'] = list(pointers[:_POINTER_PREVIEW_LIMIT])
                if len(pointers) > _POINTER_PREVIEW_LIMIT:
                    location['pointer_preview_truncated'] = True
                    location['pointer_preview_note'] = (
                        f'候选指针共 {len(pointers)} 个，此处仅预览前 {_POINTER_PREVIEW_LIMIT} 个；'
                        '完整地址仍保存在报告文件中。'
                    )
        else:
            pointers = row['inline_pointers']
            location['candidate_pointer_count'] = len(pointers)
            if len(pointers) > _POINTER_PREVIEW_LIMIT:
                location['candidate_pointers_preview'] = list(pointers[:_POINTER_PREVIEW_LIMIT])
                location['pointer_preview_truncated'] = True
                location['pointer_preview_note'] = (
                    f'候选指针共 {len(pointers)} 个，此处仅预览前 {_POINTER_PREVIEW_LIMIT} 个；'
                    '完整地址仍保存在报告文件中。'
                )
            else:
                location['candidate_pointers'] = list(pointers)
        return location

    def _show_row(self, row_index):
        if not 0 <= row_index < len(self.model.rows):
            self.details.clear()
            return
        row = self.model.rows[row_index]
        payload = {
            'category': row['category'],
            'backend': row['backend'],
            'native': row['native'],
            'location': self._location_details(row),
        }
        if row['category_key'] == 'type_conflicts':
            payload['type_conflict'] = row['classification']
            pointers = ([row['pointer']] if row['pointer'] is not None else
                        (row['group_pointers'] or row['inline_pointers'])[:_POINTER_PREVIEW_LIMIT])
            kinds = self._report.get('source_field_types', {})
            payload['source_field_types'] = {pointer:kinds.get(pointer, 'unknown') for pointer in pointers}
        notices = []
        if row['category_key'] in ('overlap', 'backend_only', 'ambiguous') and row['backend'] is None:
            notices.append(self._missing_backend_notice())
        if row['category_key'] in ('overlap', 'native_only') and row['native'] is None:
            notices.append(self._missing_native_notice())
        if notices:
            payload['evidence_notice'] = ' '.join(notices)

        notes = ['此窗口只读；不会添加规则、批准候选或回写译文。']
        notes.extend(notices)
        if self._location_is_truncated(row):
            notes.append('候选指针仅显示前 100 个预览；完整地址仍保存在报告文件中。')
        self.details.setPlainText(
            json.dumps(payload, ensure_ascii=False, indent=2) + '\n\n' + '\n'.join(notes)
        )

    def _selected(self, current, previous=None):
        if current is not None and current.isValid() and 0 <= current.row() < len(self.model.rows):
            self._show_row(current.row())
        else:
            self.details.clear()

    def _filter(self):
        needle = self.filter_edit.text().strip().casefold()
        if needle:
            # Resolve shared-group matches once per filter, not once per row.
            matching_groups = {
                group_id for group_id, group_text in self._group_search_text.items()
                if needle in group_text
            }
            rows = [
                row for row in self._rows
                if needle in row['search_text']
                or (row['group_id'] is not None and _contains(matching_groups, row['group_id']))
            ]
        else:
            rows = list(self._rows)

        self.model.set_rows(rows)
        self.count_label.setText(f'{len(rows)} / {len(self._rows)}')
        self.table.clearSelection()
        self.details.clear()
        if rows:
            self.table.selectRow(0)
            self._show_row(0)
