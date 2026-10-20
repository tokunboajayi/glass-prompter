"""Dialogs: script library, settings, phone pairing, about, first-run welcome, rehearsal report."""
from .common import BaseDialog, Card, _section, button, label, switch
from .info import AboutDialog, WelcomeDialog
from .library import LibraryDialog, _ago
from .phone import PhoneDialog, QrWidget, _clear_layout
from .report import HistoryBars, ReportDialog, ScoreRing
from .settings import AIKeyPanel, SettingsDialog

__all__ = ["AIKeyPanel", "AboutDialog", "BaseDialog", "Card", "HistoryBars", "LibraryDialog", "PhoneDialog", "QrWidget",
           "ReportDialog", "ScoreRing", "SettingsDialog", "WelcomeDialog", "_ago", "_clear_layout", "_section", "button",
           "label", "switch"]
