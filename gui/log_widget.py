# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, Slot, QObject, QEvent
from PySide6.QtGui import QFont, QTextCursor
from datetime import datetime

class LogWidget(QWidget):
    """Widget pro zobrazení logů (volitelná hlavička, staré tlačítko 'Vymazat' a nový nenápadný křížek v rohu)."""

    def __init__(self, show_header: bool = False, show_clear: bool = False, show_clear_overlay: bool = True, parent=None):
        super().__init__(parent)
        self._show_header = bool(show_header)
        self._show_clear = bool(show_clear)
        self._show_clear_overlay = bool(show_clear_overlay)
        self.title: QLabel | None = None
        self.btn_clear: QPushButton | None = None
        self.text_area: QTextEdit | None = None
        self.btn_clear_overlay: QPushButton | None = None
        self._overlay_filter: QObject | None = None
        self.init_ui()  # vytvoří plochu logu a případný overlay [3]

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Volitelná hlavička (starý styl)
        if self._show_header or self._show_clear:
            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(6)

            if self._show_header:
                self.title = QLabel("📝 Log aplikace")
                self.title.setFont(QFont("Arial", 12, QFont.Bold))
                header_layout.addWidget(self.title)
            header_layout.addStretch()

            if self._show_clear:
                self.btn_clear = QPushButton("🗑️ Vymazat")
                self.btn_clear.clicked.connect(self.clear)
                header_layout.addWidget(self.btn_clear)

            layout.addLayout(header_layout)

        # Text area pro logy
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setFont(QFont("Consolas", 10))
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: 2px solid #555;
                border-radius: 8px;
                color: #fff;
                padding: 8px;
            }
        """)
        layout.addWidget(self.text_area)

        # Nenápadný křížek „×“ v pravém horním rohu výpisu (overlay)
        if self._show_clear_overlay:
            self.btn_clear_overlay = QPushButton("×", self.text_area)  # dítě výpisu → překryv [3][7]
            self.btn_clear_overlay.setToolTip("Vymazat log")
            self.btn_clear_overlay.setFixedSize(22, 22)
            self.btn_clear_overlay.setFocusPolicy(Qt.NoFocus)
            self.btn_clear_overlay.setStyleSheet("""
                QPushButton {
                    background-color: rgba(0,0,0,0.45);
                    color: #ffffff;
                    border: 1px solid rgba(255,255,255,0.35);
                    border-radius: 11px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover  { background-color: rgba(0,0,0,0.65); }
                QPushButton:pressed{ background-color: rgba(0,0,0,0.80); }
            """)
            self.btn_clear_overlay.clicked.connect(self.clear)

            # Repozice při Resize/Show přes eventFilter (držení rohu) [3][7]
            class _OverlayPosFilter(QObject):
                def __init__(self, outer: "LogWidget"):
                    super().__init__(outer)
                    self.outer = outer
                def eventFilter(self, obj, event):
                    if event.type() in (QEvent.Resize, QEvent.Show):
                        self.outer._reposition_overlay()
                    return False

            self._overlay_filter = _OverlayPosFilter(self)
            # sledovat viewport (scrollovací oblast) kvůli přesnému rohu [7]
            target = self.text_area.viewport() if hasattr(self.text_area, "viewport") else self.text_area
            target.installEventFilter(self._overlay_filter)
            self._reposition_overlay()  # inicialní umístění [7]

    def _reposition_overlay(self, margin: int = 6):
        """Umístí křížek do pravého horního rohu výpisu (s vnitřním okrajem)."""
        if not (self.text_area and self.btn_clear_overlay):
            return
        rect = self.text_area.viewport().rect() if hasattr(self.text_area, "viewport") else self.text_area.rect()
        x = max(0, rect.width() - self.btn_clear_overlay.width() - margin)
        y = margin
        self.btn_clear_overlay.move(x, y)
        self.btn_clear_overlay.raise_()  # zajistí překrytí nad obsahem [3]

    @Slot(str, str)
    def add_log(self, message, log_type="info"):
        """Přidá zprávu (info/success/warning/error) do výpisu s barevným řádkem."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            'info':   '#FFFFFF',  # informativní = bíle
            'success':'#4CAF50',  # pozitivní = zeleně
            'warning':'#FF9800',  # varování = oranžově (ponecháno)
            'error':  '#F44336',  # chyby = červeně
        }
        color = colors.get(log_type, colors['info'])
        # Bezpečné HTML s inline barvou pro daný řádek
        import html
        formatted_message = f'[{timestamp}] {message}'
        line = f'<span style="color:{color}">{html.escape(formatted_message)}</span>'
        self.text_area.append(line)
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_area.setTextCursor(cursor)

    def clear(self):
        """Vymaže výpis a zapíše potvrzení."""
        self.text_area.clear()
        self.add_log("Log vymazán", "info")
