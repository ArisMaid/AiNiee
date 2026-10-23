"""Tab layouts for the controls owned by the game project page.

Every widget already exists on ``GameProjectPage``; this module only reparents
and arranges those exact objects.  It never connects signals, invokes handlers
or touches widget state.
"""

from PyQt5.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget


def _row(*widgets) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def _page(rows) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)
    for row in rows:
        layout.addLayout(row)
    return page


def build_action_tabs(page) -> QTabWidget:
    """Arrange the page's existing controls in three action tabs."""

    tabs = QTabWidget(page)
    tabs.setObjectName('rpg-action-tabs')
    tabs.addTab(_page([
        _row(page.create_button, page.extract_button, page.refresh_button, page.validate_button),
        _row(page.test_build_button, page.release_build_button, page.export_button,
             page.import_button, page.translate_button),
    ]), '常用操作')
    tabs.addTab(_page([
        _row(page.resume_scan_button, page.resume_extract_button,
             page.resume_validation_button, page.resume_build_button),
        _row(page.font_button, page.backend_button, page.compare_backend_button,
             page.images_button, page.migration_button),
        _row(page.external_tools_button),
    ]), '工具与恢复')
    translator_page = QWidget()
    translator_layout = QVBoxLayout(translator_page)
    translator_layout.setContentsMargins(8, 8, 8, 8)
    translator_layout.setSpacing(6)
    binding_row = QHBoxLayout()
    binding_row.setContentsMargins(0, 0, 0, 0)
    binding_row.setSpacing(6)
    binding_row.addWidget(page.tpp_binding, 1)
    translator_layout.addLayout(binding_row)
    translator_layout.addLayout(_row(
        page.tpp_export_button, page.tpp_open_button,
        page.tpp_pull_button, page.tpp_import_button,
    ))
    tabs.addTab(translator_page, 'Translator++')
    tabs.setCurrentIndex(0)
    return tabs
