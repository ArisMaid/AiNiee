import os
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication
from UserInterface.EditView.Translation.LanguageSettingsCard import LanguageSettingsCard


def test_external_game_config_updates_both_selectors_without_emitting_or_writing():
    app=QApplication.instance() or QApplication([])
    with patch.object(LanguageSettingsCard,'load_config',return_value={'source_language':'auto','target_language':'english'}),patch.object(LanguageSettingsCard,'save_config') as write:
        card=LanguageSettingsCard();changes=[]
        card.source_language_combo.currentTextChanged.connect(changes.append)
        card.target_language_combo.currentTextChanged.connect(changes.append)
        card.apply_config({'source_language':'japanese','target_language':'chinese_simplified'})
        assert card.source_language_pairs[card.source_language_combo.currentIndex()][1]=='japanese'
        assert card.target_language_pairs[card.target_language_combo.currentIndex()][1]=='chinese_simplified'
        assert changes==[];write.assert_not_called()
        assert not card.source_language_combo.signalsBlocked() and not card.target_language_combo.signalsBlocked()
        card.deleteLater();app.processEvents()


def test_unknown_external_language_keeps_current_selection_and_prior_signal_block_state():
    app=QApplication.instance() or QApplication([])
    with patch.object(LanguageSettingsCard,'load_config',return_value={'source_language':'english','target_language':'japanese'}),patch.object(LanguageSettingsCard,'save_config') as write:
        card=LanguageSettingsCard();before=(card.source_language_combo.currentIndex(),card.target_language_combo.currentIndex())
        card.source_language_combo.blockSignals(True)
        card.apply_config({'source_language':'unsupported','target_language':None})
        assert (card.source_language_combo.currentIndex(),card.target_language_combo.currentIndex())==before
        assert card.source_language_combo.signalsBlocked() and not card.target_language_combo.signalsBlocked()
        write.assert_not_called();card.deleteLater();app.processEvents()
