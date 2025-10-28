# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont


class StatusWidget(QWidget):
    """Kompaktní widget pro zobrazení aktuálního stavu aplikace s lepším využitím prostoru."""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        """Inicializace UI - kompaktní styl a rozvržení."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)     # menší vnější okraje pro lepší využití místa
        layout.setSpacing(4)                       # menší mezery mezi widgety

        frame = QFrame()
        frame.setFrameStyle(QFrame.Box)

        # CSS styl kompaktní, jemně zmenšené paddingy a laděné barvy
        frame.setStyleSheet("""
        QFrame {
            border: 2px solid #555;
            border-radius: 6px;
            background-color: #2b2b2b;
            padding: 6px 8px 6px 8px;
        }
        """)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(6, 6, 6, 6)
        frame_layout.setSpacing(6)

        title = QLabel("📊 Stav aplikace")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Arial", 11, QFont.Bold))
        frame_layout.addWidget(title)

        self.status_label = QLabel("⏸️ Připraveno")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Arial", 13, QFont.Bold))
        self.status_label.setStyleSheet("QLabel { color: #FFC107; padding: 6px 4px; }")
        frame_layout.addWidget(self.status_label)

        self.detail_label = QLabel("Aplikace je připravena k použití")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("QLabel { color: #ccc; padding: 4px 4px; }")
        frame_layout.addWidget(self.detail_label)

        layout.addWidget(frame)

    @Slot(str, str)
    def set_status(self, status_type, message):
        status_configs = {
            'idle':    {'icon': '⏸️', 'color': '#FFC107', 'text': 'Připraveno'},
            'running': {'icon': '⚙️', 'color': '#2196F3', 'text': 'Zpracovávám'},
            'success': {'icon': '✅', 'color': '#4CAF50', 'text': 'Dokončeno'},
            'error':   {'icon': '❌', 'color': '#F44336', 'text': 'Chyba'},
            'warning': {'icon': '⚠️', 'color': '#FF9800', 'text': 'Varování'},
        }
        config = status_configs.get(status_type, status_configs['idle'])
        self.status_label.setText(f"{config['icon']} {config['text']}")
        self.status_label.setStyleSheet(f"QLabel {{ color: {config['color']}; padding: 6px 4px; }}")
        self.detail_label.setText(message)
