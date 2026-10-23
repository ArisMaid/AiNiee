"""Read-only event command locations and exact captured parameters."""

import json
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt5.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QSplitter, QTableView, QVBoxLayout)


class _CommandsModel(QAbstractTableModel):
    headers = ('文件', '事件 / 页', '代码', '插件', '命令', '待审字段', '当前提取字段')

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

    def flags(self, index):
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ToolTipRole:
            return row['path'] + '#' + row['pointer']
        if role == Qt.DisplayRole:
            return (row['path'], row['scene_id'], str(row['code']), row['plugin'], row['command'],
                    ', '.join(row['unreviewed_fields']), ', '.join(row['approved_fields']))[index.column()]


class CommandAuditDialog(QDialog):
    def __init__(self, report, report_path, parent=None, initial_filter=''):
        super().__init__(parent)
        self.setWindowTitle('事件指令盘点（只读）')
        self.resize(1160, 740)
        self._records = report['records']
        layout = QVBoxLayout(self)
        notice = QLabel(f"数据集版本 {report['dataset_revision']} · {len(report['documents'])} 个文件 · "
            f"{len(self._records)} 处指令块\n待审字段可能是显示文字、身份标识或逻辑值。此窗口不会生成译文或添加回写规则。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel('筛选文件、事件、插件、参数原文：'))
        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        filter_row.addWidget(self.filter_edit)
        self.count_label = QLabel()
        filter_row.addWidget(self.count_label)
        layout.addLayout(filter_row)
        splitter = QSplitter(Qt.Vertical)
        self.model = _CommandsModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        for column, width in enumerate((175, 245, 55, 170, 160, 190, 160)):
            self.table.setColumnWidth(column, width)
        splitter.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        splitter.setSizes([370, 230])
        layout.addWidget(splitter)
        path_label = QLabel('本地报告：' + report_path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._search = [(row, json.dumps(row, ensure_ascii=False).casefold()) for row in self._records]
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.filter_edit.textChanged.connect(self._filter)
        self.filter_edit.setText(initial_filter)
        self._filter()

    def _filter(self):
        needle = self.filter_edit.text().strip().casefold()
        self.model.set_rows([row for row, text in self._search if not needle or needle in text])
        self.details.clear()
        self.count_label.setText(f'{len(self.model.rows)} / {len(self._records)}')
        if self.model.rows:
            self.table.selectRow(0)

    def _selected(self, current, previous):
        if current.isValid() and 0 <= current.row() < len(self.model.rows):
            self.details.setPlainText(json.dumps(self.model.rows[current.row()], ensure_ascii=False, indent=2))
