import threading
import os

import requests
from PyQt5.QtCore import QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import QAction, QApplication, QMenuBar
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    MessageBox,
    NavigationAvatarWidget,
    NavigationItemPosition,
    Theme,
    setTheme,
    setThemeColor,
)

from ModuleFolders.Base.Base import Base
from ModuleFolders.Config.Config import ConfigMixin
from ModuleFolders.Config.FilePathConfig import resource_path
from ModuleFolders.Domain.PromptBuilder.PromptBuilderExtraction import PromptBuilderExtraction
from ModuleFolders.Infrastructure.Platform.PlatformPaths import is_macos
from ModuleFolders.Log.Log import LogMixin
from UserInterface.BaseNavigationItem import BaseNavigationItem
from UserInterface.EditView.EditViewPage import EditViewPage
from UserInterface.Native.MacOSUI import about_message, app_menu_title, command_shortcut
from UserInterface.Platform.PlatformPage import PlatformPage
from UserInterface.PromptSettings.ExtractionSettings.ExtractionPromptPage import ExtractionPromptPage
from UserInterface.PromptSettings.PolishingSettings.PolishingSystemPromptPage import PolishingSystemPromptPage
from UserInterface.LogView.LogViewPage import LogViewPage
from UserInterface.Settings.AdvancedSettingsPage import AdvancedSettingsPage
from UserInterface.Settings.AppSettingsPage import AppSettingsPage
from UserInterface.Settings.OutputSettingsPage import OutputSettingsPage
from UserInterface.Settings.TaskSettingsPage import TaskSettingsPage
from UserInterface.Table.ExclusionListPage import ExclusionListPage
from UserInterface.Table.PromptDictionaryPage import PromptDictionaryPage
from UserInterface.Table.TextReplaceAPage import TextReplaceAPage
from UserInterface.Table.TextReplaceBPage import TextReplaceBPage
from UserInterface.PromptSettings.TranslationSettings.CharacterizationPromptPage import CharacterizationPromptPage
from UserInterface.PromptSettings.TranslationSettings.SystemPromptPage import SystemPromptPage
from UserInterface.PromptSettings.TranslationSettings.TranslationExamplePromptPage import TranslationExamplePromptPage
from UserInterface.PromptSettings.TranslationSettings.WorldBuildingPromptPage import WorldBuildingPromptPage
from UserInterface.PromptSettings.TranslationSettings.WritingStylePromptPage import WritingStylePromptPage
from UserInterface.VersionManager.VersionManager import VersionManager
from UserInterface.Widget.Toast import ToastMixin
from UserInterface.StoppableThemeListener import StoppableThemeListener


# 自动检查更新线程
class UpdateCheckerThread(QThread):
    update_available_signal = pyqtSignal(bool, str, bool)

    def __init__(self, version_manager):
        super().__init__()
        self.version_manager = version_manager

    def run(self):
        # 在子线程中运行更新检查逻辑
        self.version_manager.check_error = None
        has_update, latest_version = self.version_manager.check_for_updates()
        check_failed = hasattr(self.version_manager, "check_error") and self.version_manager.check_error is not None
        self.update_available_signal.emit(has_update, latest_version, check_failed)


# 主窗口
class AppFluentWindow(FluentWindow, ConfigMixin, LogMixin, ToastMixin, Base):
    APP_WIDTH = 1600
    APP_HEIGHT = 900
    THEME_COLOR = "#808b9d"

    def __init__(self, version: str, cache_manager, file_reader) -> None:
        super().__init__()
        self.cache_manager = cache_manager
        self._game_translation_loader = None
        self._game_translation_edit_enabled = True
        self._game_translation_cancel_pending = False

        # 启动后台线程发送日活统计，不阻塞 UI
        def report_activity():
            try:
                requests.get("https://ai-niee-vercel.vercel.app/api/track", timeout=5)
            except Exception as error:
                # 统计失败不影响程序运行
                self.debug(f"Activity report failed: {error}")

        # 设置 daemon=True，确保主程序退出时线程也会自动关闭
        if os.environ.get('AINIEE_OFFLINE') != '1':
            threading.Thread(target=report_activity, daemon=True).start()

        # 默认配置
        self.default = {
            "theme": "auto",
            "accent_color": self.THEME_COLOR,
        }

        # 载入并保存默认配置
        config = self.save_config(self.load_config_from_default())

        # 更换界面显示的语言
        ConfigMixin.multilingual_interface_dict = self.load_translations(ConfigMixin.translation_json_file)
        ConfigMixin.current_interface_language = config.get("interface_language_setting", "简中")
        self.info(f"Current Interface Language: {ConfigMixin.current_interface_language}")

        # 设置主题颜色与主题
        self._theme_mode = config.get("theme", "auto")
        setThemeColor(config.get("accent_color", self.THEME_COLOR))
        setTheme(self._theme_for_mode(self._theme_mode))

        self.systemThemeListener = StoppableThemeListener(self)
        self.systemThemeListener.systemThemeChanged.connect(self._on_system_theme_changed)
        if QApplication.platformName() not in {'offscreen','minimal'}:
            self.systemThemeListener.start()

        # 设置窗口属性
        desktop = QApplication.desktop().availableGeometry()
        initial_width = int(desktop.width() * 0.8)
        initial_height = int(desktop.height() * 0.8)
        self.resize(initial_width, initial_height)
        self.setWindowTitle(version)
        self.setWindowIcon(QIcon(str(resource_path("Logo", "Avatar.png"))))
        self.titleBar.iconLabel.hide()

        # 初始化版本管理器，并在应用加载完成后异步检查更新
        self.version_manager = VersionManager(self, version)
        if os.environ.get('AINIEE_OFFLINE') != '1':
            QTimer.singleShot(3000, self.check_for_updates)

        # 设置启动位置
        desktop = QApplication.desktop().availableGeometry()
        self.move(desktop.width() // 2 - self.width() // 2, desktop.height() // 2 - self.height() // 2)

        # 设置侧边栏属性
        self.navigationInterface.setExpandWidth(226)
        if initial_width>=1008:
            self.navigationInterface.expand(useAni=False)
        else:
            self.navigationInterface.panel.collapse()
        self.navigationInterface.setUpdateIndicatorPosOnCollapseFinished(True)
        self.navigationInterface.panel.setReturnButtonVisible(False)

        # 添加页面
        self.add_pages(cache_manager, file_reader)
        self._configure_navigation_compact_threshold()
        self.install_macos_menu()

    def _configure_navigation_compact_threshold(self) -> None:
        """Collapse before the expanded page layout blocks a compact resize."""
        navigation = self.navigationInterface
        expanded_width = int(navigation.panel.expandWidth)
        current_width = int(navigation.width())
        expanded_extra = max(0, expanded_width - current_width)
        expanded_minimum = int(self.minimumSizeHint().width()) + expanded_extra
        threshold = max(1008, expanded_minimum + 1)
        navigation.setMinimumExpandWidth(threshold)
        if self.width() < threshold and not navigation.panel.isCollapsed():
            navigation.panel.collapse()

    # 窗口关闭函数
    def closeEvent(self, event) -> None:
        if hasattr(self,'game_project_page') and self.game_project_page.is_busy():
            self.game_project_page._report_error('游戏工程操作正在进行，请等待完成后退出。')
            event.ignore()
            return
        info_cont = self.tra("确定是否退出程序") + " ... ？"
        message_box = MessageBox("Warning", info_cont, self)
        message_box.yesButton.setText(self.tra("确认"))
        message_box.cancelButton.setText(self.tra("取消"))

        if message_box.exec():
            if hasattr(self, "systemThemeListener"):
                self.systemThemeListener.requestInterruption()
                self.systemThemeListener.quit()
                if not self.systemThemeListener.wait(1200):
                    self.game_project_page._report_error('主题监听正在退出，请稍后再关闭窗口。')
                    event.ignore()
                    return
            self.emit(Base.EVENT.APP_SHUT_DOWN, {})
            self.info(self.tra("主窗口已关闭，稍后应用将自动退出") + " ... ")
            event.accept()
        else:
            event.ignore()

    def _on_system_theme_changed(self) -> None:
        if self._theme_mode == "auto":
            setTheme(Theme.AUTO)

    # 应用主题模式（auto/light/dark），由应用设置页的主题下拉调用
    def apply_theme_mode(self, mode: str) -> None:
        if mode == self._theme_mode:
            return
        self._theme_mode = mode
        setTheme(self._theme_for_mode(mode))
        self.save_config({"theme": mode})
        self.info_toast(self.tra("主题切换"), self._toast_for_mode(mode))

    @staticmethod
    def _theme_for_mode(mode: str) -> Theme:
        return {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}.get(mode, Theme.LIGHT)

    def _toast_for_mode(self, mode: str) -> str:
        return {
            "light": self.tra("已切换至浅色主题"),
            "dark": self.tra("已切换至深色主题"),
            "auto": self.tra("已切换至跟随系统"),
        }.get(mode, "")

    def open_game_translation(self, path):
        if Base.work_status != Base.STATUS.IDLE:
            self.game_project_page._report_error('请先停止当前翻译任务，再切换游戏工程。')
            return
        if self._game_translation_loader is not None or self.game_project_page.is_busy():
            self.game_project_page._report_error('已有游戏工程操作正在进行，请等待完成。')
            return
        from UserInterface.GameProject.GameTranslationLoader import GameTranslationLoadJob
        worker = GameTranslationLoadJob(path, self)
        self._game_translation_loader = worker
        self._game_translation_cancel_pending = False
        self._game_translation_edit_enabled = self.edit_view_page.isEnabled()
        self.edit_view_page.setEnabled(False)
        self.game_project_page.error_label.clear()
        self.game_project_page.error_label.hide()
        self.game_project_page.set_translation_loading(True)
        worker.succeeded.connect(lambda project: self._game_translation_ready(worker, path, project))
        worker.failed.connect(lambda error: self._game_translation_error(worker, error))
        worker.cancelled.connect(lambda: self._game_translation_cancelled(worker))
        worker.finished.connect(lambda: self._finish_game_translation(worker))
        worker.start()

    def _game_translation_ready(self, worker, path, project):
        if worker is not self._game_translation_loader:
            return
        if self._game_translation_cancel_pending or worker.isInterruptionRequested():
            self._game_translation_cancelled(worker)
            return
        if Base.work_status != Base.STATUS.IDLE:
            self.game_project_page._report_error('翻译任务状态已变化，未切换工程；请停止任务后重试。')
            return
        previous = self.cache_manager.project
        try:
            # SQLite preparation ran once on the worker. Only this GUI slot
            # adopts the detached cache and updates widgets.
            self.cache_manager._adopt_prepared_game_projection(project)
            self.edit_view_page.on_folder_selected(project.project_name, 'new')
            config = self.save_config({'translation_project':'RpgGame','label_input_path':path,
                                      'source_language':'japanese','target_language':'chinese_simplified'})
            self.edit_view_page.translation_page.language_settings_card.apply_config(config)
            self.switchTo(self.edit_view_page)
            self.game_project_page._set_status('已载入 AiNiee 翻译视图；可配置并启动翻译。')
        except Exception as error:
            with self.cache_manager.file_lock:
                self.cache_manager.project = previous
            try:
                if previous:
                    self.edit_view_page.on_folder_selected(previous.project_name, 'continue')
                else:
                    self.edit_view_page.on_back_button_clicked()
            except Exception as restore_error:
                self.game_project_page._report_error(f'{error}；视图恢复失败：{restore_error}')
                return
            self.game_project_page._report_error(str(error))

    def _game_translation_error(self, worker, error):
        if worker is self._game_translation_loader:
            self.game_project_page._report_error(error)

    def _game_translation_cancelled(self, worker):
        if worker is self._game_translation_loader:
            self.game_project_page._set_status('已取消载入翻译视图；当前翻译工程保持。')

    def _cancel_game_translation(self):
        if self._game_translation_loader is not None:
            # QThread clears its interruption flag after run() returns. Keep
            # the user's request until queued GUI results have been handled.
            self._game_translation_cancel_pending = True
            self._game_translation_loader.requestInterruption()
            self.game_project_page._set_status('已请求取消载入翻译视图…')

    def _finish_game_translation(self, worker):
        if worker is self._game_translation_loader:
            self._game_translation_loader = None
            self.edit_view_page.setEnabled(self._game_translation_edit_enabled)
            self.game_project_page.set_translation_loading(False)
        worker.deleteLater()

    # 打开项目主页
    def open_project_page(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/NEKOparapa/AiNiee"))

    def install_macos_menu(self) -> None:
        if not is_macos():
            return

        # FluentWindow 不是 QMainWindow，macOS 原生菜单栏用独立 QMenuBar 挂到系统菜单。
        menu_bar = QMenuBar(None)
        menu_bar.setNativeMenuBar(True)
        self.macos_menu_bar = menu_bar

        app_menu = menu_bar.addMenu(app_menu_title())
        about_action = QAction(self.tra("关于 AiNiee"), self)
        about_action.setMenuRole(QAction.AboutRole)
        about_action.triggered.connect(
            lambda: MessageBox(
                self.tra("关于 AiNiee"),
                about_message(self.windowTitle(), self.tra),
                self,
            ).exec()
        )

        preferences_action = QAction(self.tra("偏好设置..."), self)
        preferences_action.setMenuRole(QAction.PreferencesRole)
        preferences_action.setShortcut(command_shortcut(","))
        preferences_action.triggered.connect(lambda: self.switchTo(self.app_settings_page))

        quit_action = QAction(self.tra("退出 AiNiee"), self)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.setShortcut(command_shortcut("Q"))
        quit_action.triggered.connect(self.close)

        app_menu.addAction(about_action)
        app_menu.addSeparator()
        app_menu.addAction(preferences_action)
        app_menu.addSeparator()
        app_menu.addAction(quit_action)

    # 显示更新对话框
    def show_update_dialog(self) -> None:
        self.version_manager.show_update_dialog()

    # 检查更新
    def check_for_updates(self) -> None:
        config = self.load_config()
        if config.get("auto_check_update", True):
            self.update_checker_thread = UpdateCheckerThread(self.version_manager)
            self.update_checker_thread.update_available_signal.connect(self._on_update_check_completed)
            self.update_checker_thread.start()

    # 更新检查完成的回调
    def _on_update_check_completed(self, has_update: bool, latest_version: str, check_failed: bool) -> None:
        if check_failed:
            self.warning_toast(self.tra("更新检查失败"), self.tra("请检查报错信息"))
        elif has_update:
            self.success_toast(
                self.tra("发现新版本"),
                self.tra("当前版本: {0}, 最新版本: {1}, 点击更新按钮进行更新").format(
                    self.version_manager.current_version,
                    latest_version,
                ),
            )
        else:
            self.info_toast(self.tra("更新检查"), self.tra("当前已是最新版本"))

    # 开始添加页面
    def add_pages(self, cache_manager, file_reader) -> None:
        # ===== 快速开始 =====
        self.navigationInterface.addItemHeader(self.tra("快速开始"), NavigationItemPosition.SCROLL)
        self.add_project_pages(cache_manager, file_reader)

        # ===== 任务配置 =====
        self.navigationInterface.addItemHeader(self.tra("任务配置"), NavigationItemPosition.SCROLL)
        self.add_task_setting_pages()

        # ===== 提示词管理 =====
        self.navigationInterface.addItemHeader(self.tra("提示词管理"), NavigationItemPosition.SCROLL)
        self.add_prompt_setting_pages()

        # ===== 公共表格 =====
        self.navigationInterface.addItemHeader(self.tra("公共表格"), NavigationItemPosition.SCROLL)
        self.add_table_pages()

        # 设置默认页面
        self.switchTo(self.edit_view_page)

        # 运行日志按钮（在应用设置上方）
        self.log_view_page = LogViewPage("log_view_page", self)
        self.addSubInterface(
            self.log_view_page,
            FluentIcon.COMMAND_PROMPT,
            self.tra("运行日志"),
            NavigationItemPosition.BOTTOM,
        )

        # 应用设置按钮
        self.app_settings_page = AppSettingsPage("app_settings_page", self)
        self.addSubInterface(
            self.app_settings_page,
            FluentIcon.SETTING,
            self.tra("应用设置"),
            NavigationItemPosition.BOTTOM,
        )

        # 项目主页按钮
        avatar_path = str(resource_path("Logo", "Avatar.png"))
        self.navigationInterface.addWidget(
            routeKey="avatar_navigation_widget",
            widget=NavigationAvatarWidget("NEKOparapa", avatar_path),
            onClick=self.open_project_page,
            position=NavigationItemPosition.BOTTOM,
        )

    # 添加快速开始
    def add_project_pages(self, cache_manager, file_reader) -> None:
        self.platform_page = PlatformPage("platform_page", self)
        self.addSubInterface(self.platform_page, FluentIcon.IOT, self.tra("接口管理"), NavigationItemPosition.SCROLL)

        self.edit_view_page = EditViewPage("edit_view_page", self, cache_manager, file_reader)
        self.addSubInterface(self.edit_view_page, FluentIcon.PLAY, self.tra("开始翻译"), NavigationItemPosition.SCROLL)
        from UserInterface.GameProject.GameProjectPage import GameProjectPage
        self.game_project_page = GameProjectPage(self, on_translate=self.open_game_translation)
        self.game_project_page.translationCancelRequested.connect(self._cancel_game_translation)
        self.game_project_page.setObjectName('game-project')
        self.addSubInterface(self.game_project_page, FluentIcon.GAME, '游戏汉化', NavigationItemPosition.SCROLL)

    # 添加任务设置
    def add_task_setting_pages(self) -> None:
        self.task_settings_page = TaskSettingsPage("task_settings_page", self)
        self.addSubInterface(self.task_settings_page, FluentIcon.ZOOM, self.tra("任务设置"), NavigationItemPosition.SCROLL)

        self.output_settings_page = OutputSettingsPage("output_settings_page", self)
        self.addSubInterface(self.output_settings_page, FluentIcon.ALBUM, self.tra("输出设置"), NavigationItemPosition.SCROLL)

        self.advanced_settings_page = AdvancedSettingsPage("advanced_settings_page", self)
        self.TranslationSettings = self.advanced_settings_page.translation_settings_page
        self.addSubInterface(self.advanced_settings_page,FluentIcon.TILES,self.tra("高级设置"),NavigationItemPosition.SCROLL)

    # 添加提示词设置
    def add_prompt_setting_pages(self) -> None:
        # 提取提示词
        self.extraction_prompt_navigation = BaseNavigationItem("extraction_prompt_navigation", self)
        self.addSubInterface(
            self.extraction_prompt_navigation,
            FluentIcon.SEARCH,
            self.tra("提取提示词"),
            NavigationItemPosition.SCROLL,
        )
        self.extraction_system_prompt_page = ExtractionPromptPage(
            "extraction_system_prompt_page", self, PromptBuilderExtraction.BASIC
        )
        self.addSubInterface(
            self.extraction_system_prompt_page,
            FluentIcon.LABEL,
            self.tra("基础提示"),
            parent=self.extraction_prompt_navigation,
        )
        self.extraction_judgment_prompt_page = ExtractionPromptPage(
            "extraction_judgment_prompt_page", self, PromptBuilderExtraction.JUDGMENT
        )
        self.addSubInterface(
            self.extraction_judgment_prompt_page,
            FluentIcon.LABEL,
            self.tra("裁定提示"),
            parent=self.extraction_prompt_navigation,
        )

        self.prompt_optimization_navigation_item = BaseNavigationItem("prompt_optimization_navigation_item", self)
        self.addSubInterface(
            self.prompt_optimization_navigation_item,
            FluentIcon.BOOK_SHELF,
            self.tra("翻译提示词"),
            NavigationItemPosition.SCROLL,
        )

        # 翻译提示词
        self.system_prompt_page = SystemPromptPage("system_prompt_page", self)
        self.addSubInterface(self.system_prompt_page, FluentIcon.LABEL, self.tra("基础提示"), parent=self.prompt_optimization_navigation_item)
        self.characterization_prompt_page = CharacterizationPromptPage("characterization_prompt_page", self)
        self.addSubInterface(self.characterization_prompt_page, FluentIcon.PEOPLE, self.tra("角色介绍"), parent=self.prompt_optimization_navigation_item)
        self.world_building_prompt_page = WorldBuildingPromptPage("world_building_prompt_page", self)
        self.addSubInterface(self.world_building_prompt_page, FluentIcon.QUICK_NOTE, self.tra("背景设定"), parent=self.prompt_optimization_navigation_item)
        self.writing_style_prompt_page = WritingStylePromptPage("writing_style_prompt_page", self)
        self.addSubInterface(self.writing_style_prompt_page, FluentIcon.PENCIL_INK, self.tra("翻译风格"), parent=self.prompt_optimization_navigation_item)
        self.translation_example_prompt_page = TranslationExamplePromptPage("translation_example_prompt_page", self)
        self.addSubInterface(self.translation_example_prompt_page, FluentIcon.FIT_PAGE, self.tra("翻译示例"), parent=self.prompt_optimization_navigation_item)

        # 润色提示词
        self.polishing_prompt_navigation = BaseNavigationItem("polishing_prompt_navigation", self)
        self.addSubInterface(
            self.polishing_prompt_navigation,
            FluentIcon.PALETTE,
            self.tra("润色提示词"),
            NavigationItemPosition.SCROLL,
        )
        self.polishing_system_prompt_page = PolishingSystemPromptPage("polishing_system_prompt_page", self)
        self.addSubInterface(self.polishing_system_prompt_page, FluentIcon.LABEL, self.tra("基础提示"), parent=self.polishing_prompt_navigation)

    # 添加表格设置
    def add_table_pages(self) -> None:
        self.prompt_dictionary_page = PromptDictionaryPage("prompt_dictionary_page", self)
        self.addSubInterface(self.prompt_dictionary_page, FluentIcon.DICTIONARY, self.tra("术语表"), NavigationItemPosition.SCROLL)

        self.exclusion_list_page = ExclusionListPage("exclusion_list_page", self)
        self.addSubInterface(self.exclusion_list_page, FluentIcon.DICTIONARY, self.tra("禁翻表"), NavigationItemPosition.SCROLL)

        self.text_replace_navigation_item = BaseNavigationItem("text_replace_navigation_item", self)
        self.addSubInterface(self.text_replace_navigation_item, FluentIcon.FONT_SIZE, self.tra("文本替换"), NavigationItemPosition.SCROLL)

        self.text_replace_a_page = TextReplaceAPage("text_replace_a_page", self)
        self.addSubInterface(self.text_replace_a_page, FluentIcon.SEARCH, self.tra("译前替换"), parent=self.text_replace_navigation_item)

        self.text_replace_b_page = TextReplaceBPage("text_replace_b_page", self)
        self.addSubInterface(self.text_replace_b_page, FluentIcon.SEARCH_MIRROR, self.tra("译后替换"), parent=self.text_replace_navigation_item)
