"""Avoid Qt5's lossy plugin path discovery in Windows Unicode source checkouts."""
from pathlib import Path
import os


def configure_qt_paths():
    # The offscreen plugin uses a directory font database, not the native
    # Windows font registry. Its compiled prefix also loses Unicode paths.
    if os.name=='nt' and os.environ.get('QT_QPA_PLATFORM') in {'offscreen','minimal'}:
        fonts=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
        if fonts.is_dir():os.environ.setdefault('QT_QPA_FONTDIR',str(fonts))
    import PyQt5
    from PyQt5.QtCore import QCoreApplication
    plugins = Path(PyQt5.__file__).parent / 'Qt5' / 'plugins'
    if plugins.is_dir():
        current = QCoreApplication.libraryPaths()
        QCoreApplication.setLibraryPaths([str(plugins), *[p for p in current if p != str(plugins)]])


def configure_qt_fonts(app):
    """Use a readable installed face when the Windows offscreen default is absent."""
    if app is None:return ''
    if os.name!='nt' or os.environ.get('QT_QPA_PLATFORM') not in {'offscreen','minimal'}:
        return app.font().family()
    from PyQt5.QtGui import QFont,QFontDatabase
    available={family.casefold():family for family in QFontDatabase().families()}
    for family in ('Microsoft YaHei UI','Microsoft YaHei','Noto Sans CJK SC','SimHei','Segoe UI','Arial'):
        if family.casefold() not in available:continue
        font=QFont(app.font());font.setFamily(available[family.casefold()]);app.setFont(font)
        return font.family()
    return app.font().family()
