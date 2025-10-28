#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# --- Version & Changelog ---
__version__ = "3.1b"
__changelog__ = """
v3.1a (2025-10-28)
- Oprava integrace: tlačítko 🍀 je v horním toolbaru 'Monitoring'.
- Počítadlo jako nemodální okno; zavírání Cmd+W; výchozí složka dialogů nastavena.
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from gui.main_window import MainWindow

def apply_dark_theme(app):
    """Aplikace vlastního dark theme bez externí závislosti"""
    dark_stylesheet = """
    QMainWindow {
        background-color: #2b2b2b;
        color: #ffffff;
    }
    
    QWidget {
        background-color: #2b2b2b;
        color: #ffffff;
        selection-background-color: #4CAF50;
    }
    
    QTabWidget::pane {
        border: 1px solid #555555;
        background-color: #2b2b2b;
    }
    
    QTabWidget::tab-bar {
        alignment: center;
    }
    
    QTabBar::tab {
        background-color: #3c3c3c;
        color: #ffffff;
        padding: 8px 16px;
        margin-right: 2px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }
    
    QTabBar::tab:selected {
        background-color: #4CAF50;
        color: #ffffff;
    }
    
    QTabBar::tab:hover {
        background-color: #555555;
    }
    
    QGroupBox {
        font-weight: bold;
        border: 2px solid #555555;
        border-radius: 8px;
        margin-top: 1ex;
        padding-top: 10px;
        background-color: #353535;
    }
    
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
        color: #4CAF50;
    }
    
    QLineEdit {
        border: 2px solid #555555;
        border-radius: 4px;
        padding: 5px;
        background-color: #404040;
        color: #ffffff;
    }
    
    QLineEdit:focus {
        border-color: #4CAF50;
    }
    
    QSpinBox, QDoubleSpinBox {
        border: 2px solid #555555;
        border-radius: 4px;
        padding: 5px;
        background-color: #404040;
        color: #ffffff;
    }
    
    QSpinBox:focus, QDoubleSpinBox:focus {
        border-color: #4CAF50;
    }
    
    QComboBox {
        border: 2px solid #555555;
        border-radius: 4px;
        padding: 5px;
        background-color: #404040;
        color: #ffffff;
        min-width: 6em;
    }
    
    QComboBox:focus {
        border-color: #4CAF50;
    }
    
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 15px;
        border-left-width: 1px;
        border-left-color: #555555;
        border-left-style: solid;
        border-top-right-radius: 3px;
        border-bottom-right-radius: 3px;
        background-color: #555555;
    }
    
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid #ffffff;
        width: 0;
        height: 0;
    }
    
    QComboBox QAbstractItemView {
        border: 2px solid #555555;
        background-color: #404040;
        color: #ffffff;
        selection-background-color: #4CAF50;
    }
    
    QPushButton {
        border: 2px solid #555555;
        border-radius: 6px;
        background-color: #4CAF50;
        color: #ffffff;
        padding: 8px 16px;
        font-weight: bold;
    }
    
    QPushButton:hover {
        background-color: #45a049;
        border-color: #45a049;
    }
    
    QPushButton:pressed {
        background-color: #3d8b40;
    }
    
    QPushButton:disabled {
        background-color: #666666;
        color: #999999;
        border-color: #666666;
    }
    
    QTextEdit {
        border: 2px solid #555555;
        border-radius: 4px;
        background-color: #1e1e1e;
        color: #ffffff;
        padding: 5px;
    }
    
    QProgressBar {
        border: 2px solid #555555;
        border-radius: 5px;
        text-align: center;
        background-color: #404040;
        color: #ffffff;
    }
    
    QProgressBar::chunk {
        background-color: #4CAF50;
        border-radius: 3px;
    }
    
    QCheckBox {
        color: #ffffff;
        spacing: 5px;
    }
    
    QCheckBox::indicator {
        width: 18px;
        height: 18px;
    }
    
    QCheckBox::indicator:unchecked {
        border: 2px solid #555555;
        background-color: #404040;
        border-radius: 3px;
    }
    
    QCheckBox::indicator:checked {
        border: 2px solid #4CAF50;
        background-color: #4CAF50;
        border-radius: 3px;
    }
    
    QLabel {
        color: #ffffff;
    }
    
    QFrame {
        background-color: #2b2b2b;
        border: 1px solid #555555;
    }
    
    QSplitter::handle {
        background-color: #555555;
    }
    
    QSplitter::handle:horizontal {
        width: 3px;
    }
    
    QSplitter::handle:vertical {
        height: 3px;
    }
    
    QScrollBar:vertical {
        border: none;
        background-color: #404040;
        width: 14px;
        border-radius: 7px;
    }
    
    QScrollBar::handle:vertical {
        background-color: #666666;
        border-radius: 7px;
        min-height: 20px;
    }
    
    QScrollBar::handle:vertical:hover {
        background-color: #888888;
    }
    
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    
    QScrollBar:horizontal {
        border: none;
        background-color: #404040;
        height: 14px;
        border-radius: 7px;
    }
    
    QScrollBar::handle:horizontal {
        background-color: #666666;
        border-radius: 7px;
        min-width: 20px;
    }
    
    QScrollBar::handle:horizontal:hover {
        background-color: #888888;
    }
    
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    
    QStatusBar {
        background-color: #353535;
        color: #ffffff;
        border-top: 1px solid #555555;
    }
    
    QMenuBar {
        background-color: #353535;
        color: #ffffff;
        border-bottom: 1px solid #555555;
    }
    
    QMenuBar::item {
        background-color: transparent;
        padding: 4px 8px;
    }
    
    QMenuBar::item:selected {
        background-color: #4CAF50;
    }
    
    QMenu {
        background-color: #404040;
        color: #ffffff;
        border: 1px solid #555555;
    }
    
    QMenu::item {
        padding: 4px 20px;
    }
    
    QMenu::item:selected {
        background-color: #4CAF50;
    }
    """
    
    app.setStyleSheet(dark_stylesheet)

def main():
    """Hlavní funkce aplikace"""
    # Vytvoření Qt aplikace
    app = QApplication(sys.argv)
    
    # Nastavení vlastního dark theme
    apply_dark_theme(app)
    
    # Nastavení vlastností aplikace
    app.setApplicationName("OpenStreetMap Map Generator")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Ctyrlistkoteka.cz")
    
    # Vytvoření a zobrazení hlavního okna
    window = MainWindow()
    window.show()
    
    # Spuštění aplikace
    sys.exit(app.exec())

if __name__ == "__main__":
    main()