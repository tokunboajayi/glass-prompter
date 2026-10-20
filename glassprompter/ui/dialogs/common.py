"""Shared dialog building blocks: label/button helpers, the base glass dialog, settings cards and switches."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget

from ... import APP_NAME
from ..glass import GlassDialog, Switch
from ..theme import DASH


def label(text, role=None, wrap=False):
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    return lab


def button(text, fn, primary=False, danger=False):
    b = QPushButton(text)
    b.clicked.connect(fn)
    if primary:
        b.setProperty("primary", True)
        b.setDefault(True)
    if danger:
        b.setProperty("danger", True)
    return b


class BaseDialog(GlassDialog):
    """Frosted glass, top-most dialog that is also hidden from screen sharing (scripts and PINs stay private)."""

    def __init__(self, parent, title, resizable=False):
        super().__init__(parent, resizable=resizable, title=title)
        self.setWindowTitle("%s %s %s" % (APP_NAME, DASH, title))

    def confirm(self, title, text, ok_text):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.NoIcon)
        ok = box.addButton(ok_text, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        ok.setProperty("danger", True)
        box.exec()
        return box.clickedButton() is ok



class Card(QFrame):
    """Grouped settings surface: rows separated by hairlines (System-Settings style)."""

    def __init__(self, title=None):
        super().__init__()
        self.setProperty("role", "card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 4, 14, 4)
        self.lay.setSpacing(0)
        self.title = title
        self._rows = 0

    def _add(self, w):
        if self._rows:
            line = QFrame()
            line.setProperty("role", "hairline")
            self.lay.addWidget(line)
        self.lay.addWidget(w)
        self._rows += 1

    def row(self, title, control=None, hint=None):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 9, 0, 9)
        h.setSpacing(12)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        txt.addWidget(label(title, "rowtitle"))
        hint_lbl = None
        if hint:
            hint_lbl = label(hint, "muted", True)
            txt.addWidget(hint_lbl)
        h.addLayout(txt, 1)
        if control is not None:
            h.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self._add(w)
        return hint_lbl

    def slider(self, title, lo, hi, val, fmt, apply):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 7, 0, 7)
        h.setSpacing(12)
        name = label(title, "rowtitle")
        name.setFixedWidth(92)
        h.addWidget(name)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        sl.setAccessibleName(title)
        val_lbl = label(fmt(val), "value")
        val_lbl.setFixedWidth(64)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def changed(v):
            val_lbl.setText(fmt(v))
            apply(v)
        sl.valueChanged.connect(changed)
        h.addWidget(sl, 1)
        h.addWidget(val_lbl)
        self._add(w)
        return sl


def _section(lay, card, name):
    head = label(name.upper(), "section")
    head.setContentsMargins(4, 0, 0, 0)
    lay.addWidget(head)
    lay.addSpacing(-2)
    lay.addWidget(card)
    lay.addSpacing(14)


def switch(val, apply):
    sw = Switch()
    sw.setChecked(val)
    sw.toggled.connect(apply)
    return sw
