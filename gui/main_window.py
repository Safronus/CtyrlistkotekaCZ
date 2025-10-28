#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Aug 28 23:17:40 2025
@author: safronus
"""

import sys
import json
import os
import shutil
from pathlib import Path
import requests
import tempfile
import math
from PIL import Image, ImageDraw

# OPRAVENÉ IMPORTY - bez duplicit
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
QTabWidget, QLabel, QLineEdit, QPushButton,
QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
QGroupBox, QGridLayout, QFileDialog, QProgressBar,
QSplitter, QMessageBox, QTreeWidget, QTreeWidgetItem, QListWidgetItem,
QHeaderView, QMenu, QInputDialog, QScrollArea, QDialog, QTextEdit, QAbstractItemView, QSizePolicy, QToolBar)

from PySide6.QtCore import Qt, QThread, Signal, Slot, QDir, QTimer, QObject, QEvent
from PySide6.QtGui import QFont, QIcon, QAction, QPixmap

from gui.status_widget import StatusWidget
from gui.log_widget import LogWidget
from gui.image_viewer import ImageViewerDialog, open_polygon_editor_for_file

from gui.pdf_generator_window import PDFGeneratorWindow
from core.map_processor import MapProcessor

from gui.web_photos_window import WebPhotosWindow

# === VLÁKNOVÝ BACKGROUND PROCESSOR ===
class ProcessorThread(QThread):
    """Thread pro zpracování na pozadí"""
    
    def __init__(self, parameters):
        super().__init__()
        self.parameters = parameters
        self.processor = None
        
    def run(self):
        """Spuštění zpracování"""
        self.processor = MapProcessor(self.parameters)
        
        # Připojení signálů
        self.processor.finished.connect(self.finished)
        self.processor.error.connect(self.error)
        self.processor.progress.connect(self.progress)
        self.processor.log.connect(self.log)
        self.processor.status.connect(self.status)
        
        # Spuštění zpracování
        self.processor.run()
        
    def stop(self):
        """Zastavení zpracování"""
        if self.processor:
            self.processor.stop()
    
    # Signály pro přeposílání
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(int)
    log = Signal(str, str)
    status = Signal(str, str)

# TENTO BLOK VLOŽTE DO main_window.py PŘED TŘÍDU MainWindow

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, 
    QMessageBox, QWidget, QFrame, QSpinBox, QComboBox, QGroupBox, QGridLayout, QLineEdit,
    QSpacerItem, QSizePolicy, QProgressDialog
)
from PySide6.QtGui import QPixmap, QFont, QGuiApplication, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from core.map_processor import MapProcessor
import time
import json
import re

class ClickableMapLabel(QFrame):
    """Vlastní widget pro zobrazení klikatelného náhledu mapy s pevnou velikostí."""
    clicked = Signal()

    def __init__(self, zoom, width, height, parent=None):
        super().__init__(parent)
        self.zoom = zoom
        self.meta = None
        self.base_image = None
        self.setFrameShape(QFrame.StyledPanel)
        self.setLineWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("QFrame { border: 1px solid #ccc; border-radius: 6px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.title_label = QLabel(f"<b>Zoom {self.zoom}</b>")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        self._original_title_stylesheet = self.title_label.styleSheet()
        layout.addWidget(self.title_label)

        self.map_display = QLabel("Načítám...")
        self.map_display.setAlignment(Qt.AlignCenter)
        self.map_display.setFixedSize(width, height)
        self.map_display.setStyleSheet("background-color: #f0f0f0; border: 1px dashed #bbb; color: #333;")
        layout.addWidget(self.map_display, 1)
        
        self.adjustSize()

    def set_pixmap_with_marker(self, pixmap):
        self.map_display.setPixmap(pixmap)
        self.map_display.setText("")

    def setText(self, text):
        self.map_display.setText(text)
        self.map_display.setPixmap(QPixmap())
        
    def set_title(self, text):
        self.title_label.setText(text)

    def select(self):
        self.setStyleSheet("QFrame { border: 2px solid #007bff; border-radius: 6px; background-color: #eaf4ff; }")
        self.title_label.setStyleSheet("color: black;")

    def deselect(self):
        self.setStyleSheet("QFrame { border: 1px solid #ccc; border-radius: 6px; }")
        self.title_label.setStyleSheet(self._original_title_stylesheet)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

class MapGenerationThread(QThread):
    """Vlákno generuje mapu s progress reportingem."""
    
    map_generated = Signal(int, object, dict)
    error_occurred = Signal(int, str)
    progress_updated = Signal(int, str)  # progress, message
    finished = Signal()

    def __init__(self, parameters, zooms_to_generate, main_window, parent=None):
        super().__init__(parent)
        self.params = parameters
        self.zooms = zooms_to_generate if isinstance(zooms_to_generate, list) else [zooms_to_generate]
        self.main_window = main_window
        self._is_running = True

    def run(self):
        for z in self.zooms:
            if not self._is_running: 
                break
                
            try:
                self.progress_updated.emit(5, "Příprava...")
                
                local_params = self.params.copy()
                local_params['zoom'] = z
                processor = MapProcessor(local_params)
                
                coords_text = local_params.get('manual_coordinates', '0 0')
                parsed_coords = self.main_window.parse_coordinates(coords_text)
                if not parsed_coords: 
                    raise ValueError("Neplatné souřadnice")

                lat, lon = parsed_coords
                width_px = int(local_params.get('output_width_cm', 10) / 2.54 * local_params.get('output_dpi', 300))
                height_px = int(local_params.get('output_height_cm', 10) / 2.54 * local_params.get('output_dpi', 300))

                self.progress_updated.emit(15, "Stahování dlaždic...")
                
                # Modifikovaná verze download_map_tiles s progress callbackem
                img = self.download_map_tiles_with_progress(processor, lat, lon, z, width_px, height_px)
                
                if img is None: 
                    raise ValueError("Nepodařilo se vygenerovat obrázek.")

                meta = {'zoom': z, 'params': local_params, 'dimensions_px': (width_px, height_px)}
                
                self.progress_updated.emit(100, "Dokončeno")
                self.map_generated.emit(z, img, meta)
                
            except Exception as e:
                if self._is_running: 
                    self.error_occurred.emit(z, str(e))

        self.finished.emit()

    def download_map_tiles_with_progress(self, processor, lat, lon, zoom, width_px, height_px):
        """Stahování dlaždic s progress reportingem."""
        try:
            import math, requests, io
            from PIL import Image as PILImage
            
            tile_size = 256
            n = 2.0 ** zoom
            
            # Výpočet potřebných dlaždic
            lat_rad = math.radians(lat)
            tile_x_f = (lon + 180.0) / 360.0 * n
            tile_y_f = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
            
            center_px_x = tile_x_f * tile_size
            center_px_y = tile_y_f * tile_size
            
            left = int(math.floor(center_px_x - width_px / 2))
            top = int(math.floor(center_px_y - height_px / 2))
            right = left + width_px
            bottom = top + height_px
            
            left_tile = int(math.floor(left / tile_size))
            top_tile = int(math.floor(top / tile_size))
            right_tile = int(math.floor((right - 1) / tile_size))
            bottom_tile = int(math.floor((bottom - 1) / tile_size))
            
            tiles_x = right_tile - left_tile + 1
            tiles_y = bottom_tile - top_tile + 1
            total_tiles = tiles_x * tiles_y
            
            # Vytvoření prázdného obrázku
            full_width = tiles_x * tile_size
            full_height = tiles_y * tile_size
            full_image = PILImage.new('RGB', (full_width, full_height), color='lightgray')
            
            downloaded = 0
            
            # Stahování dlaždic s progress updatem
            for tx in range(left_tile, right_tile + 1):
                for ty in range(top_tile, bottom_tile + 1):
                    if not self._is_running:
                        return None
                        
                    try:
                        xt = int(tx % int(n))
                        if ty < 0 or ty >= int(n):
                            downloaded += 1
                            continue
                            
                        url = f"https://tile.openstreetmap.org/{zoom}/{xt}/{ty}.png"
                        headers = {'User-Agent': 'OSM Map Generator - Preview/1.3'}
                        
                        r = requests.get(url, headers=headers, timeout=8)
                        if r.status_code == 200 and r.content:
                            img = PILImage.open(io.BytesIO(r.content)).convert('RGB')
                            px = (tx - left_tile) * tile_size
                            py = (ty - top_tile) * tile_size
                            full_image.paste(img, (px, py))
                            
                    except Exception:
                        pass  # Ignorovat chyby jednotlivých dlaždic
                        
                    downloaded += 1
                    
                    # Update progress (15% až 85% pro stahování)
                    progress = 15 + int((downloaded / total_tiles) * 70)
                    self.progress_updated.emit(progress, f"Dlaždice {downloaded}/{total_tiles}")
            
            # Výřez na požadovanou velikost
            self.progress_updated.emit(90, "Zpracování...")
            
            crop_left = left - left_tile * tile_size
            crop_top = top - top_tile * tile_size
            
            cropped = full_image.crop((
                crop_left,
                crop_top,
                crop_left + width_px,
                crop_top + height_px
            ))
            
            return cropped
            
        except Exception as e:
            self.progress_updated.emit(0, f"Chyba: {str(e)}")
            return None

    def stop(self):
        """Zastavení vlákna."""
        self._is_running = False


class MultiZoomPreviewDialog(QDialog):
    """Rozšířená verze dialogu s dvěma řadami náhledů - původní DPI a 420 DPI."""
    def __init__(self, parent, parameters, preview_config=None):
        super().__init__(parent)
        self.setWindowTitle("Interaktivní náhled map")
        
        try:
            screen_geo = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(screen_geo.width() * 0.85, screen_geo.height() * 0.9)
        except:
            self.resize(1700, 1000)
    
        self.params = parameters
        self.preview_config = preview_config or {
            'row1_enabled': True, 'row1_dpi': 240,
            'row2_enabled': False, 'row2_dpi': 420
        }
        
        self.previews = {}           # První řada - konfigurované DPI
        self.extra_dpi_previews = {} # Druhá řada - konfigurované DPI (pokud povoleno)
        self.progress_bars = {}      # Progress bary pro každý náhled {(row, zoom): QProgressBar}
        self.threads = {}
        self.selected_zoom = None
        self.selected_row = 0
        self.initial_zoom_to_select = int(self.params.get('zoom', 18))
        self.save_progress_dialog = None
        
        main_layout = QVBoxLayout(self)
    
        # Výpočet rozměrů pro obě DPI
        width_cm = float(parameters.get('output_width_cm', 10))
        height_cm = float(parameters.get('output_height_cm', 10))
        
        # Kontejner pro náhledy
        previews_group = QGroupBox("Náhledy map (kliknutím vyberte)")
        previews_main_layout = QVBoxLayout(previews_group)
        
        # První řada (pokud povolena)
        if self.preview_config['row1_enabled']:
            row1_dpi = self.preview_config['row1_dpi']
            width_px_row1 = int(width_cm / 2.54 * row1_dpi)
            height_px_row1 = int(height_cm / 2.54 * row1_dpi)
            
            row1_label = QLabel(f"<b>Řada 1: {row1_dpi} DPI ({width_px_row1}×{height_px_row1} px)</b>")
            row1_label.setAlignment(Qt.AlignCenter)
            row1_label.setStyleSheet("color: #0066cc; margin: 5px;")
            previews_main_layout.addWidget(row1_label)
            
            row1_layout = QHBoxLayout()
            for col, z in enumerate(self.get_zooms_to_generate()):
                # Kontejner pro preview + progress bar
                preview_container = QWidget()
                preview_layout = QVBoxLayout(preview_container)
                preview_layout.setContentsMargins(4, 4, 4, 4)
                preview_layout.setSpacing(2)
                
                # Preview widget
                preview = ClickableMapLabel(z, width_px_row1, height_px_row1, self)
                preview.clicked.connect(lambda z=z: self.on_preview_selected(z, 0))
                self.previews[z] = preview
                preview_layout.addWidget(preview)
                
                # Progress bar pro tento náhled
                progress = QProgressBar()
                progress.setRange(0, 100)
                progress.setValue(0)
                progress.setMaximumHeight(12)
                progress.setVisible(False)  # Skrytý dokud nezačne načítání
                progress.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #bbb;
                        border-radius: 4px;
                        text-align: center;
                        font-weight: bold;
                        font-size: 9px;
                        background-color: #f0f0f0;
                    }
                    QProgressBar::chunk {
                        background-color: #0066cc;
                        border-radius: 3px;
                    }
                """)
                self.progress_bars[(0, z)] = progress
                preview_layout.addWidget(progress)
                
                row1_layout.addWidget(preview_container)
                
            previews_main_layout.addLayout(row1_layout)
    
        # Druhá řada (pokud povolena)
        if self.preview_config['row2_enabled']:
            row2_dpi = self.preview_config['row2_dpi']
            width_px_row2 = int(width_cm / 2.54 * row2_dpi)
            height_px_row2 = int(height_cm / 2.54 * row2_dpi)
            
            row2_label = QLabel(f"<b>Řada 2: {row2_dpi} DPI ({width_px_row2}×{height_px_row2} px)</b>")
            row2_label.setAlignment(Qt.AlignCenter)
            row2_label.setStyleSheet("color: #cc6600; margin: 5px;")
            previews_main_layout.addWidget(row2_label)
            
            row2_layout = QHBoxLayout()
            for col, z in enumerate(self.get_zooms_to_generate()):
                # Kontejner pro preview + progress bar
                preview_container = QWidget()
                preview_layout = QVBoxLayout(preview_container)
                preview_layout.setContentsMargins(4, 4, 4, 4)
                preview_layout.setSpacing(2)
                
                # Preview widget
                preview = ClickableMapLabel(z, width_px_row2, height_px_row2, self)
                preview.clicked.connect(lambda z=z: self.on_preview_selected(z, 1))
                self.extra_dpi_previews[z] = preview
                preview_layout.addWidget(preview)
                
                # Progress bar pro tento náhled
                progress = QProgressBar()
                progress.setRange(0, 100)
                progress.setValue(0)
                progress.setMaximumHeight(12)
                progress.setVisible(False)
                progress.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #bbb;
                        border-radius: 4px;
                        text-align: center;
                        font-weight: bold;
                        font-size: 9px;
                        background-color: #f0f0f0;
                    }
                    QProgressBar::chunk {
                        background-color: #cc6600;
                        border-radius: 3px;
                    }
                """)
                self.progress_bars[(1, z)] = progress
                preview_layout.addWidget(progress)
                
                row2_layout.addWidget(preview_container)
                
            previews_main_layout.addLayout(row2_layout)
    
        main_layout.addWidget(previews_group, 1)
    
        # Spodní část (controls, info panel, tlačítka) - zůstává stejná
        bottom_splitter = QSplitter(Qt.Horizontal)
        
        controls_group = QGroupBox("Nastavení značky")
        controls_v_layout = QVBoxLayout(controls_group)
        controls_grid_layout = QGridLayout()
        
        controls_grid_layout.addWidget(QLabel("Velikost GPS bodu:"), 0, 0)
        self.spin_marker_size = QSpinBox()
        self.spin_marker_size.setRange(5, 50)
        self.spin_marker_size.setValue(int(self.params.get('marker_size', 7)))
        self.spin_marker_size.setSuffix(" px")
        self.spin_marker_size.valueChanged.connect(self.update_all_markers)
        controls_grid_layout.addWidget(self.spin_marker_size, 0, 1)
    
        controls_grid_layout.addWidget(QLabel("Styl značky:"), 1, 0)
        self.combo_marker_style = QComboBox()
        self.combo_marker_style.addItems(["Puntík", "Křížek"])
        self.combo_marker_style.setCurrentIndex(1 if self.params.get('marker_style') == 'cross' else 0)
        self.combo_marker_style.currentIndexChanged.connect(self.update_all_markers)
        controls_grid_layout.addWidget(self.combo_marker_style, 1, 1)
        
        controls_v_layout.addLayout(controls_grid_layout)
        controls_v_layout.addStretch(1)
        bottom_splitter.addWidget(controls_group)
    
        self.create_info_panel(bottom_splitter)
        main_layout.addWidget(bottom_splitter, 1)
    
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save = QPushButton("Uložit vybranou mapu")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.on_save_clicked)
        btn_layout.addWidget(self.btn_save)
        self.btn_close = QPushButton("Zavřít")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)
        main_layout.addLayout(btn_layout)
    
        sc_close = QShortcut(QKeySequence.Close, self)
        sc_close.activated.connect(self.accept)
    
        self.start_initial_generation()

    def update_preview_progress(self, row, zoom, progress, message=""):
        """Aktualizace progress baru pro konkrétní náhled bez přeskakování layoutu."""
        try:
            key = (row, zoom)
            if key in self.progress_bars:
                progress_bar = self.progress_bars[key]
                
                # Nastavit hodnotu a text
                progress_bar.setValue(progress)
                if message:
                    progress_bar.setFormat(f"{progress}% - {message}")
                else:
                    progress_bar.setFormat(f"{progress}%")
                
                # Zobrazit progress bar při začátku načítání
                if progress > 0 and not progress_bar.isVisible():
                    progress_bar.setVisible(True)
                
                # OPRAVA: Místo okamžitého skrytí použít fade-out efekt
                if progress >= 100:
                    self._fade_out_progress_bar(key, progress_bar)
                    
        except Exception as e:
            if hasattr(self, 'parent') and hasattr(self.parent(), 'log_widget'):
                self.parent().log_widget.add_log(f"⚠️ Chyba při aktualizaci progress: {e}", "warning")
    
    def _fade_out_progress_bar(self, key, progress_bar):
        """Plynulý fade-out efekt pro progress bar bez změny layoutu."""
        try:
            # Zrušit předchozí timer pro tento progress bar
            if hasattr(self, 'progress_hide_timers') and key in self.progress_hide_timers:
                self.progress_hide_timers[key].stop()
            
            # Nejprve změnit text na "Hotovo"
            progress_bar.setFormat("Hotovo")
            progress_bar.setStyleSheet(progress_bar.styleSheet().replace(
                "background-color: #0066cc", "background-color: #4CAF50"
            ).replace(
                "background-color: #cc6600", "background-color: #4CAF50"
            ))
            
            # ALTERNATIVA 1: Postupné zmenšování výšky (plynulejší než okamžité skrytí)
            self._animate_progress_bar_height(key, progress_bar)
            
        except Exception as e:
            # Fallback na obyčejné skrytí po delší době
            if not hasattr(self, 'progress_hide_timers'):
                self.progress_hide_timers = {}
                
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: progress_bar.setVisible(False))
            timer.start(2000)  # Skrýt po 2 sekundách
            self.progress_hide_timers[key] = timer
    
    def _animate_progress_bar_height(self, key, progress_bar):
        """Animace zmenšování výšky progress baru."""
        if not hasattr(self, 'progress_hide_timers'):
            self.progress_hide_timers = {}
        
        original_height = progress_bar.maximumHeight()
        current_height = original_height
        step = 2  # Pixely za krok
        
        def shrink_step():
            nonlocal current_height
            current_height = max(0, current_height - step)
            progress_bar.setMaximumHeight(current_height)
            
            if current_height <= 0:
                progress_bar.setVisible(False)
                progress_bar.setMaximumHeight(original_height)  # Obnovit pro příští použití
                if key in self.progress_hide_timers:
                    del self.progress_hide_timers[key]
            else:
                # Další krok animace
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(shrink_step)
                timer.start(50)  # 50ms mezi kroky = plynulá animace
                self.progress_hide_timers[key] = timer
        
        # Počkat 1 sekundu před začátkem animace
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(shrink_step)
        timer.start(1000)
        self.progress_hide_timers[key] = timer

    
    def show_preview_progress(self, row, zoom, show=True):
        """Zobrazí/skryje progress bar pro konkrétní náhled."""
        try:
            key = (row, zoom)
            if key in self.progress_bars:
                self.progress_bars[key].setVisible(show)
        except Exception:
            pass

    def create_info_panel(self, parent_splitter):
        info_container = QWidget()
        main_info_layout = QVBoxLayout(info_container)
        main_info_layout.setContentsMargins(0, 0, 0, 0)
        
        meta_group = QGroupBox("Detailní informace o vybrané mapě")
        meta_layout = QVBoxLayout(meta_group)
        
        self.info_text_structured = QTextEdit()
        self.info_text_structured.setReadOnly(True)
        self.info_text_structured.setFont(QFont("Monaco", 11))
        meta_layout.addWidget(self.info_text_structured)
        main_info_layout.addWidget(meta_group)
        
        parent_splitter.addWidget(info_container)

    def get_zooms_to_generate(self):
        base_zoom = int(self.params.get('zoom', 18))
        if base_zoom >= 19: return [17, 18, 19]
        if base_zoom <= 2: return [1, 2, 3]
        return [base_zoom - 1, base_zoom, base_zoom + 1]

    def start_initial_generation(self):
        # Generování pro první řadu (pokud povolena)
        if self.preview_config['row1_enabled']:
            for zoom in self.get_zooms_to_generate():
                if preview := self.previews.get(zoom):
                    params_row1 = self.params.copy()
                    params_row1['output_dpi'] = self.preview_config['row1_dpi']
                    
                    # Zobrazit progress bar na začátku
                    self.show_preview_progress(0, zoom, True)
                    self.update_preview_progress(0, zoom, 0, "Čekání...")
                    
                    thread = MapGenerationThread(params_row1, zoom, self.parent(), self)
                    thread.map_generated.connect(lambda z, img, meta, row=0: self.on_map_generated(z, img, meta, row))
                    thread.error_occurred.connect(lambda z, err, row=0: self.on_map_error(z, err, row))
                    thread.progress_updated.connect(lambda p, msg, row=0, z=zoom: self.update_preview_progress(row, z, p, msg))
                    thread.finished.connect(lambda z=zoom: self.threads.pop(f"{z}_0", None))
                    thread.start()
                    self.threads[f"{zoom}_0"] = thread
    
        # Generování pro druhou řadu (pokud povolena)
        if self.preview_config['row2_enabled']:
            for zoom in self.get_zooms_to_generate():
                if preview := self.extra_dpi_previews.get(zoom):
                    params_row2 = self.params.copy()
                    params_row2['output_dpi'] = self.preview_config['row2_dpi']
                    
                    # Zobrazit progress bar na začátku
                    self.show_preview_progress(1, zoom, True)
                    self.update_preview_progress(1, zoom, 0, "Čekání...")
                    
                    thread = MapGenerationThread(params_row2, zoom, self.parent(), self)
                    thread.map_generated.connect(lambda z, img, meta, row=1: self.on_map_generated(z, img, meta, row))
                    thread.error_occurred.connect(lambda z, err, row=1: self.on_map_error(z, err, row))
                    thread.progress_updated.connect(lambda p, msg, row=1, z=zoom: self.update_preview_progress(row, z, p, msg))
                    thread.finished.connect(lambda z=zoom: self.threads.pop(f"{z}_1", None))
                    thread.start()
                    self.threads[f"{zoom}_1"] = thread

    def update_all_markers(self):
        for preview in self.previews.values():
            if preview.base_image:
                self.draw_marker_and_display(preview, preview.base_image)
        for preview in self.extra_dpi_previews.values():
            if preview.base_image:
                self.draw_marker_and_display(preview, preview.base_image)
        
        if self.selected_zoom:
            current_previews = self.previews if self.selected_row == 0 else self.extra_dpi_previews
            if current_previews[self.selected_zoom].meta:
                self.display_detailed_metadata(current_previews[self.selected_zoom].meta)

    def draw_marker_and_display(self, preview_widget, base_image):
        img_with_marker = base_image.copy()
        draw = ImageDraw.Draw(img_with_marker)
        
        # OPRAVA: Použít skutečnou hodnotu ze spinneru místo pevné hodnoty
        marker_diameter = self.spin_marker_size.value()  # Aktuální hodnota z UI
        marker_style = 'cross' if self.combo_marker_style.currentIndex() == 1 else 'dot'
        
        cx, cy = img_with_marker.width // 2, img_with_marker.height // 2
        
        # OPRAVA: Škálovat velikost značky podle DPI náhledu vs. výstupního DPI
        # Zjistit DPI náhledu a výstupní DPI pro správné škálování
        preview_dpi = self._get_preview_dpi_for_widget(preview_widget)
        output_dpi = int(self.params.get('output_dpi', 300))
        
        # Škálovat velikost značky podle poměru DPI
        scale_factor = preview_dpi / output_dpi
        scaled_marker_diameter = int(marker_diameter * scale_factor)
        
        radius = scaled_marker_diameter / 2.0
        
        if marker_style == "cross":
            thickness = max(1, round(scaled_marker_diameter / 7.0))
            draw.line([(cx - radius, cy), (cx + radius, cy)], fill='white', width=thickness + 2)
            draw.line([(cx, cy - radius), (cx, cy + radius)], fill='white', width=thickness + 2)
            draw.line([(cx - radius, cy), (cx + radius, cy)], fill='black', width=thickness)
            draw.line([(cx, cy - radius), (cx, cy + radius)], fill='black', width=thickness)
        else:
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            draw.ellipse([p - 1 for p in bbox[:2]] + [p + 1 for p in bbox[2:]], fill='white')
            draw.ellipse(bbox, fill='black')
        
        qt_image = ImageQt(img_with_marker)
        pixmap = QPixmap.fromImage(qt_image)
        preview_widget.set_pixmap_with_marker(pixmap)

    def _get_preview_dpi_for_widget(self, preview_widget):
        """Zjistí DPI pro daný preview widget podle toho, ve které řadě je."""
        # Zjistit zoom level z preview widgetu
        zoom = preview_widget.zoom
        
        # Najít widget v první nebo druhé řadě
        if zoom in self.previews and self.previews[zoom] == preview_widget:
            return self.preview_config.get('row1_dpi', 240)
        elif zoom in self.extra_dpi_previews and self.extra_dpi_previews[zoom] == preview_widget:
            return self.preview_config.get('row2_dpi', 420)
        
        # Fallback
        return int(self.params.get('output_dpi', 300))

    @Slot(int, object, dict)
    def on_map_generated(self, zoom, img, meta, row=0):
        current_previews = self.previews if row == 0 else self.extra_dpi_previews
        
        if preview := current_previews.get(zoom):
            preview.base_image = img
            preview.meta = meta
            self.draw_marker_and_display(preview, img)
            
            temp_params = meta['params'].copy()
            filename = self._generate_future_filename(temp_params)
            dpi_info = f"{meta['params'].get('output_dpi', 300)} DPI"
            preview.set_title(f"<b>Zoom {zoom}</b><br><small>{dpi_info}</small><br><small>{filename}</small>")

            # Automatický výběr pouze pro první řadu
            if (row == 0 and self.initial_zoom_to_select and 
                zoom == self.initial_zoom_to_select):
                self.on_preview_selected(zoom, 0)
                self.initial_zoom_to_select = None

    def on_preview_selected(self, zoom, row):
        current_previews = self.previews if row == 0 else self.extra_dpi_previews
        preview = current_previews.get(zoom)
        
        if not preview or not preview.base_image: 
            return
        
        # Deselect all previews in both rows
        for p in self.previews.values():
            p.deselect()
        for p in self.extra_dpi_previews.values():
            p.deselect()
            
        # Select current preview
        preview.select()
        self.selected_zoom = zoom
        self.selected_row = row
        
        self.btn_save.setEnabled(True)
        
        if preview.meta:
            self.display_detailed_metadata(preview.meta)
        else:
            self.clear_info_panel()

    def _generate_future_filename(self, params):
        try:
            id_lokace = params.get('id_lokace', 'ID_LOKACE')
            popis = params.get('popis', 'POPIS')
            zoom = params.get('zoom', 18)
            coords_text = params.get('manual_coordinates', '')
            coords_simple = re.sub(r'[^\w.\-]+', '', coords_text).replace('°', '').replace(',', '.')
            cislo_id = params.get('manual_cislo_id', '00001')
            return f"{id_lokace}_{popis}_GPS{coords_simple}_Z{zoom}_{cislo_id}.png"
        except Exception as e:
            return "název_souboru.png"

    def display_detailed_metadata(self, meta):
        params = meta.get('params', {})
        dims = meta.get('dimensions_px', ('N/A', 'N/A'))
        filesize_mb = (dims[0] * dims[1] * 4) / (1024 * 1024) if isinstance(dims[0], int) else 0
        
        if self.selected_row == 0:
            row_dpi = self.preview_config.get('row1_dpi', 240)
            row_info = f"První řada ({row_dpi} DPI)"
        else:
            row_dpi = self.preview_config.get('row2_dpi', 420)
            row_info = f"Druhá řada ({row_dpi} DPI)"
        
        lines = [
            "=== Základní informace ===",
            f"Řada:             {row_info}",
            f"ID Lokace:        {params.get('id_lokace', 'N/A')}",
            f"Popis:            {params.get('popis', 'N/A')}",
            f"Rozměry:          {dims[0]} × {dims[1]} px",
            f"Odh. velikost:    ~{filesize_mb:.2f} MB (nekomprimováno)",
            "",
            "=== Parametry generování ===",
            f"Výstup:           {params.get('output_width_cm')} cm × {params.get('output_height_cm')} cm",
            f"Rozlišení:        {params.get('output_dpi')} DPI",
            f"Přiblížení:       Zoom {meta.get('zoom', 'N/A')}",
            "",
            "=== GPS informace ===",
            f"Souřadnice:       {params.get('manual_coordinates', 'N/A')}",
            "",
            "=== Parametry značky (aktuální) ===",
            f"Styl:             {'Křížek' if self.combo_marker_style.currentIndex() == 1 else 'Puntík'}",
            f"Velikost:         {self.spin_marker_size.value()} px (průměr)",
        ]
        self.info_text_structured.setPlainText("\n".join(lines))

    def clear_info_panel(self):
        if hasattr(self, 'info_text_structured'):
            self.info_text_structured.clear()

    @Slot(int, str)
    def on_map_error(self, zoom, error_message, row=0):
        current_previews = self.previews if row == 0 else self.extra_dpi_previews
        if preview := current_previews.get(zoom):
            preview.setText(f"❌ Chyba\n{error_message}")

    def on_save_clicked(self):
        if not self.selected_zoom: return
        
        current_previews = self.previews if self.selected_row == 0 else self.extra_dpi_previews
        preview = current_previews.get(self.selected_zoom)
        
        if not preview or not preview.meta:
            QMessageBox.warning(self, "Uložit mapu", "Data pro vybranou mapu nejsou k dispozici.")
            return

        params_to_save = preview.meta['params'].copy()
        params_to_save['marker_size'] = self.spin_marker_size.value()
        params_to_save['marker_style'] = 'cross' if self.combo_marker_style.currentIndex() == 1 else 'dot'

        self.save_progress_dialog = QProgressDialog("Generuji a ukládám mapu...", "Zrušit", 0, 100, self)
        self.save_progress_dialog.setWindowModality(Qt.WindowModal)
        self.save_progress_dialog.setMinimumDuration(0)
        self.save_progress_dialog.setValue(0)
        self.save_progress_dialog.show()

        self.parent().processor_thread = ProcessorThread(params_to_save)
        self.parent().processor_thread.progress.connect(self.on_save_progress)
        self.parent().processor_thread.finished.connect(self.on_save_finished)
        self.parent().processor_thread.error.connect(self.on_save_error)
        self.save_progress_dialog.canceled.connect(self.on_save_canceled)
        self.parent().processor_thread.start()
        
        self.btn_save.setEnabled(False)
        self.btn_close.setEnabled(False)

    @Slot(int)
    def on_save_progress(self, progress):
        # Minimalistická oprava: pracuj s lokální referencí `dlg`,
        # ať mezitím někdo nepřepíše self.save_progress_dialog na None.
        try:
            dlg = getattr(self, "save_progress_dialog", None)
            if dlg and dlg.isVisible():
                dlg.setValue(progress)
                if progress < 25:
                    message = "Stahuji mapové dlaždice..."
                elif progress < 75:
                    message = "Zpracovávám mapu..."
                else:
                    message = "Ukládám soubor..."
                dlg.setLabelText(f"Generuji a ukládám mapu...\n{message}")
        except (AttributeError, RuntimeError):
            # AttributeError: dlg se změnil/zmizel; RuntimeError: Qt objekt už je zničen
            pass

    def on_save_canceled(self):
        if hasattr(self.parent(), 'processor_thread') and self.parent().processor_thread:
            self.parent().processor_thread.stop()
        self.cleanup_save_operation()
        
    def cleanup_save_operation(self):
        if self.save_progress_dialog:
            self.save_progress_dialog.close()
            self.save_progress_dialog = None
        
        if hasattr(self.parent(), 'processor_thread') and self.parent().processor_thread:
            try:
                self.parent().processor_thread.progress.disconnect(self.on_save_progress)
            except:
                pass
        
        self.btn_save.setEnabled(True)
        self.btn_close.setEnabled(True)

    def add_size_metadata_to_png(self, png_path, width_cm, height_cm, dpi):
        try:
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
            
            with Image.open(png_path) as img:
                existing_metadata = PngInfo()
                
                if hasattr(img, 'text') and img.text:
                    for key, value in img.text.items():
                        existing_metadata.add_text(key, value)
                
                existing_metadata.add_text("Output_Width_cm", f"{width_cm:.3f}")
                existing_metadata.add_text("Output_Height_cm", f"{height_cm:.3f}")
                existing_metadata.add_text("Output_DPI", str(dpi))
                
                img.save(png_path, "PNG", pnginfo=existing_metadata, dpi=(dpi, dpi))
                
        except Exception as e:
            print(f"Chyba při přidávání metadat velikosti: {e}")

    @Slot(str)
    def on_save_finished(self, path):
        try:
            current_previews = self.previews if self.selected_row == 0 else self.extra_dpi_previews
            preview = current_previews.get(self.selected_zoom)
            if preview and preview.meta:
                params = preview.meta['params']
                width_cm = float(params.get('output_width_cm', 10))
                height_cm = float(params.get('output_height_cm', 10)) 
                dpi = int(params.get('output_dpi', 300))
                
                self.add_size_metadata_to_png(path, width_cm, height_cm, dpi)
            
        except Exception as e:
            self.parent().log_widget.add_log(f"❌ Chyba při přidávání metadat: {e}", "error")
        
        self.cleanup_save_operation()
        QMessageBox.information(self, "Uloženo", f"Mapa byla úspěšně uložena:\n{path}")
        self.parent().refresh_file_tree()
        self.accept()

    @Slot(str)
    def on_save_error(self, msg):
        self.cleanup_save_operation()
        QMessageBox.critical(self, "Chyba", f"Došlo k chybě během ukládání:\n{msg}")

    def closeEvent(self, event):
        for thread in list(self.threads.values()):
            if thread.isRunning():
                thread.stop()
                thread.wait(500)
        
        if hasattr(self.parent(), 'processor_thread') and self.parent().processor_thread and self.parent().processor_thread.isRunning():
            self.parent().processor_thread.stop()
            
        if self.save_progress_dialog:
            self.save_progress_dialog.close()
            
        super().closeEvent(event)

from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QFont, QKeySequence, QShortcut, QImage
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox,
    QCheckBox, QFileDialog, QMessageBox, QScrollArea, QDialog, QSizePolicy
)

APP_VERSION = "3.1a"
FOURLEAF_DEFAULT_DIR = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Čtyřlístky na sušičce/")

class FLClickableLabel(QLabel):
    from PySide6.QtCore import Signal
    clicked = Signal(QPoint)
    rightClicked = Signal(QPoint)
    hovered = Signal(QPoint)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.hovered.emit(event.position().toPoint())
        super().mouseMoveEvent(event)


class FourLeafCounterWidget(QWidget):
    """Interaktivní číslování bodů v obrázku (OpenCV), start, náhled, Undo/Reset, uložení."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._img_bgr: Optional[np.ndarray] = None
        self._points: List[Tuple[int, int]] = []
        self._start_num: int = 1
        self._preview: bool = True
        self._last_dir: Path = FOURLEAF_DEFAULT_DIR if FOURLEAF_DEFAULT_DIR.exists() else Path.home()

        self.btn_open = QPushButton("📂 Otevřít")
        self.btn_save = QPushButton("💾 Uložit"); self.btn_save.setEnabled(False)
        self.spin_start = QSpinBox(); self.spin_start.setRange(-999999, 999999); self.spin_start.setValue(self._start_num); self.spin_start.setPrefix("Start: ")
        self.chk_preview = QCheckBox("Živý náhled"); self.chk_preview.setChecked(True)
        self.btn_undo = QPushButton("↶ Zpět"); self.btn_undo.setEnabled(False)
        self.btn_reset = QPushButton("🗑 Vymazat vše"); self.btn_reset.setEnabled(False)

        top = QHBoxLayout()
        for w in (self.btn_open, self.btn_save, self.spin_start, self.chk_preview, self.btn_undo, self.btn_reset):
            top.addWidget(w)
        top.addStretch(1)

        self.lbl = FLClickableLabel()
        self.lbl.setMinimumSize(320, 240)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.lbl)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.scroll)

        self.btn_open.clicked.connect(self.open_image)
        self.btn_save.clicked.connect(self.save_image)
        self.spin_start.valueChanged.connect(self._on_start_changed)
        self.chk_preview.toggled.connect(self._on_preview_toggled)
        self.btn_undo.clicked.connect(self.undo_last)
        self.btn_reset.clicked.connect(self.reset_points)

        self.lbl.clicked.connect(self._on_image_clicked)
        self.lbl.rightClicked.connect(self._on_right_click)
        self.lbl.hovered.connect(self._on_hover)

    # ----- actions -----
    def has_image(self) -> bool: return self._img_bgr is not None

    def open_image(self) -> None:
        start = str(self._last_dir)
        fname, _ = QFileDialog.getOpenFileName(self, "Otevřít obrázek", start, "Obrázky (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if not fname: return
        img = cv2.imread(fname, cv2.IMREAD_COLOR)
        if img is None:
            QMessageBox.critical(self, "Chyba", "Nelze načíst obrázek.")
            return
        self._img_bgr = img
        self._points.clear()
        self._set_points_enabled(False)
        self._last_dir = Path(fname).parent
        self._render_and_show()

    def save_image(self) -> None:
        if not self.has_image(): return
        out = self._render_image(with_numbers=True)
        start = str(self._last_dir)
        fname, _ = QFileDialog.getSaveFileName(self, "Uložit výsledek", start, "PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if not fname: return
        ok = cv2.imwrite(fname, out)
        if ok: QMessageBox.information(self, "Uloženo", "Obrázek byl uložen.")
        else: QMessageBox.critical(self, "Chyba", "Ukládání selhalo.")

    def _on_start_changed(self, val: int) -> None:
        self._start_num = val; self._render_and_show()

    def _on_preview_toggled(self, on: bool) -> None:
        self._preview = on; self._render_and_show()

    def undo_last(self) -> None:
        if self._points:
            self._points.pop()
            self._set_points_enabled(bool(self._points))
            self._render_and_show()

    def reset_points(self) -> None:
        self._points.clear(); self._set_points_enabled(False); self._render_and_show()

    def _on_right_click(self, _pos: QPoint) -> None: self.undo_last()

    def _on_image_clicked(self, pos: QPoint) -> None:
        if not self.has_image(): return
        x = int(max(0, min(pos.x(), self._img_bgr.shape[1] - 1)))
        y = int(max(0, min(pos.y(), self._img_bgr.shape[0] - 1)))
        self._points.append((x, y)); self._set_points_enabled(True); self._render_and_show()

    def _on_hover(self, _pos: QPoint) -> None:
        if self._preview: self._render_and_show()

    # ----- rendering -----
    def _render_and_show(self) -> None:
        img = self._render_image(with_numbers=self._preview)
        self._show_image(img)

    def _render_image(self, with_numbers: bool) -> np.ndarray:
        if self._img_bgr is None:
            return np.zeros((480, 640, 3), dtype=np.uint8)
        canvas = self._img_bgr.copy()
        if with_numbers and self._points:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = max(0.5, min(canvas.shape[1], canvas.shape[0]) / 800.0)
            thickness = max(1, int(round(font_scale * 2)))
            for idx, (x, y) in enumerate(self._points, start=self._start_num):
                self._put_text_outline(canvas, str(idx), (x, y), font, font_scale, thickness)
        return canvas

    @staticmethod
    def _put_text_outline(img: np.ndarray, text: str, org: Tuple[int, int], font, font_scale: float, thickness: int) -> None:
        cv2.putText(img, text, org, font, font_scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
        cv2.putText(img, text, org, font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _show_image(self, bgr: np.ndarray) -> None:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        self.lbl.setPixmap(pix); self.lbl.resize(pix.size())

    def _set_points_enabled(self, enabled: bool) -> None:
        self.btn_save.setEnabled(self.has_image())
        self.btn_undo.setEnabled(enabled)
        self.btn_reset.setEnabled(enabled)


class FourLeafCounterDialog(QDialog):
    """Nemodální okno s počítadlem; zavírání ⌘W (QKeySequence.Close)."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Počítadlo čtyřlístků")
        lay = QVBoxLayout(self)
        self.widget = FourLeafCounterWidget(self)
        lay.addWidget(self.widget)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Close), self, activated=self.close)
# === HLAVNÍ OKNO A ZÁKLADNÍ UI ===
class MainWindow(QMainWindow):
    """Hlavní okno aplikace"""
    
    def __init__(self):
        super().__init__()
    
        # Perzistentní nastavení aplikace
        from PySide6.QtCore import QSettings
        self.settings = QSettings("Ctyrlístky", "OSMMapGenerator")
    
        # Základní vlastnosti okna (mohou být později přepsány restoreGeometry v init_ui)
        self.setWindowTitle("OSM Map Generator")
        self.setGeometry(100, 100, 1000, 700)
    
        # Běžný runtime stav
        self.map_update_timer = None
        self.map_thread = None
        self.processor_thread = None
        self.last_output_path = None
        self.saved_tree_expansion_state = set()
        self.clipboard_data = None
    
        # Výchozí cesty a konfigurace
        from pathlib import Path
        self.default_maps_path = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/")
        self.config_file = Path.home() / ".config" / "osm_map_generator" / "config.json"
    
        # PLACEHOLDERY pro bezpečný start/ukončení (budou přepsány skutečnými widgety v init_ui)
        from PySide6.QtWidgets import QLabel, QComboBox
        class _NullLog:
            def add_log(self, *args, **kwargs):
                pass
        self.log_widget = _NullLog()                     # dočasný logger, aby load_config nepadal
        try:
            self.label_maps_path = QLabel(str(self.default_maps_path))  # dočasný label cesty
        except Exception:
            self.label_maps_path = QLabel("")
        self.combo_coord_mode = QComboBox()              # dočasný combo pro režim souřadnic
    
        # Přepínání zobrazení (FullHD/4K) – stejný model jako v PDF okně
        self.display_mode = None
        self._current_scale_factor = 1.0                 # globální relativní škálování UI
    
        # Náhled mapy – ochrany proti zacyklení a deduplikace požadavků
        self._map_loading = False                        # právě probíhá načítání
        self._suppress_map_resize = False                # potlačení resize během setPixmap
        self._last_map_req = None                        # poslední obsloužený požadavek (lat,lon,zoom,marker,w,h)
        self._pending_map_req = None                     # naplánovaný/poslední spuštěný požadavek
        self._map_thread = None                          # aktuální vlákno náhledu
    
        # Sestavení UI (vytvoří skutečné widgety včetně log_widget, label_maps_path, combo_coord_mode)
        self.init_ui()                                   # tlačítko „🖥️ FullHD/4K“ je přidáno v create_monitoring_widget[11]
        
    
        # Načtení konfigurace až po sestavení UI (logy a vazby již existují)
        try:
            self.load_config()
        except Exception as e:
            # Tichá ochrana – init nemá spadnout, podrobnosti se zapíšou až po vytvoření reálného log widgetu
            pass
    
        # Úvodní refresh stromu souborů (pokud již existuje)
        if hasattr(self, "file_tree") and self.file_tree is not None:
            try:
                self.refresh_file_tree()
            except Exception:
                pass

    def init_ui(self):
        """Inicializace UI + obnova uložené geometrie okna a šířek sloupců stromu."""
        # Záhlaví a výchozí geometrie (případně bude přepsána restoreGeometry)
        self.setWindowTitle("OpenStreetMap Map Generator v2.0")
        self.setGeometry(100, 100, 1800, 1000) # počáteční rozměr
    
        # Centrální widget a hlavní layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
    
        # Klávesové zkratky
        from PySide6.QtGui import QShortcut, QKeySequence
        copy_shortcut = QShortcut(QKeySequence.Copy, self)
        copy_shortcut.activated.connect(self.copy_selected_item)
    
        paste_shortcut = QShortcut(QKeySequence.Paste, self)
        paste_shortcut.activated.connect(self._on_paste_shortcut)
    
        # Close = Cmd+W/Ctrl+W (zavře všechna QDialog podokna)
        self._sc_close_all = QShortcut(QKeySequence(QKeySequence.Close), self)
        self._sc_close_all.setContext(Qt.ApplicationShortcut)
        self._sc_close_all.activated.connect(self.close_active_child_dialogs)
    
        # Splitter: nastavení vlevo, monitoring vpravo
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
    
        settings_widget = self.create_settings_widget()
        splitter.addWidget(settings_widget)
    
        monitoring_widget = self.create_monitoring_widget()
        splitter.addWidget(monitoring_widget)
    
        splitter.setSizes([800, 600])
    
        # Sekce se stromovou strukturou (vytvoří self.file_tree)
        file_tree_widget = self.create_file_tree_widget()
        main_layout.addWidget(file_tree_widget)
    
        # Spodní panel (váš spacer)
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
    
        # Globální progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
    
        # Obnova uložené geometrie okna a stavu hlavičky stromu
        from PySide6.QtCore import QByteArray
    
        try:
            geo = self.settings.value("window/geometry", QByteArray()) # načti jako QByteArray
            if isinstance(geo, QByteArray):
                self.restoreGeometry(geo) # obnoví velikost/pozici okna
        except Exception:
            pass
    
        try:
            if hasattr(self, "file_tree") and self.file_tree is not None:
                state = self.settings.value("file_tree/header_state", QByteArray()) # načti jako QByteArray
                if isinstance(state, QByteArray):
                    self.file_tree.header().restoreState(state) # obnoví šířky/pořadí/viditelnost
        except Exception:
            pass
    
        # PŘESUNUTO NA KONEC: Nastavení zkratky až na úplném konci, když už jsou všechny widgety vytvořené
        try:
            self.setup_search_shortcut()  # Toto nyní nastaví obě zkratky (F i Z)
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při nastavování zkratek filtru: {e}", "error")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QFont
    from PySide6.QtWidgets import QToolBar
    
    def showEvent(self, event) -> None:
        """Při 1. zobrazení okna injektuje tlačítko 🍀 do monitor_toolbar a aplikuje verzi do titulku."""
        try:
            if not hasattr(self, "_fourleaf_injected"):
                self._fourleaf_injected = True
                self._inject_fourleaf_ui()
                # Verze do titulku
                try:
                    title = self.windowTitle() or "Aplikace"
                    if f"(v{APP_VERSION})" not in title:
                        self.setWindowTitle(f"{title} (v{APP_VERSION})")
                except Exception:
                    pass
        except Exception:
            pass
        super().showEvent(event)
    
    def _inject_fourleaf_ui(self) -> None:
        """
        Přidá tlačítko '🍀 Počítadlo' do self.monitor_toolbar, hned vedle existujících.
        Umístění: po '🧩 Web fotky' a před gapem pro FullHD/4K (pokud gap najdu).
        """
        # style_btn a palety TEAL/PURP atd. máš v modulu; použijeme stejný helper
        try:
            from PySide6.QtWidgets import QPushButton
            # Ověř, že toolbar existuje
            tb = getattr(self, "monitor_toolbar", None)
            if tb is None:
                # Není-li toolbar k dispozici (extrémně), neprovádět nic
                return
    
            # Pokud už tlačítko existuje, neinstaluj znovu
            if hasattr(self, "btn_fourleaf") and self.btn_fourleaf and isinstance(self.btn_fourleaf, QPushButton):
                return
    
            # Vytvoř tlačítko a nasaď styl jako u ostatních (např. TEAL)
            self.btn_fourleaf = QPushButton("🍀 Počítadlo")
            # Existují 2 verze style_btn; obě podporují 'w=' -> žádný problém
            try:
                style_btn(self.btn_fourleaf, *TEAL, w=95)  # šířka podobná jako 'Web fotky'
            except Exception:
                try:
                    style_btn(self.btn_fourleaf, *TEAL, max_w=95)
                except Exception:
                    pass
    
            self.btn_fourleaf.setToolTip("Otevřít počítadlo čtyřlístků (nemodální okno)")
            self.btn_fourleaf.clicked.connect(self.open_fourleaf_counter_window)
    
            # Vložit hned za 'Web fotky', pokud ho najdeme; jinak prostě přidat na konec
            try:
                tb.addWidget(self.btn_fourleaf)
            except Exception:
                pass
    
            # Ujisti se, že toolbar je vidět
            try:
                tb.setVisible(True)
            except Exception:
                pass
    
        except Exception as e:
            print(f"[FourLeaf] Inject UI failed: {e}")
    
    def open_fourleaf_counter_window(self) -> None:
        """Otevře nemodální okno Počítadla; pokud už běží, vyzvedne ho."""
        try:
            win = getattr(self, "_fourleaf_win", None)
            if win is not None and win.isVisible():
                try:
                    win.raise_(); win.activateWindow()
                except Exception:
                    pass
                return
    
            dlg = FourLeafCounterDialog(self)
            self._fourleaf_win = dlg
            try:
                dlg.destroyed.connect(lambda *_: setattr(self, "_fourleaf_win", None))
            except Exception:
                pass
    
            dlg.show()
            try:
                dlg.raise_(); dlg.activateWindow()
            except Exception:
                pass
        except Exception as e:
            print(f"[FourLeaf] Nelze otevřít okno: {e}")
            
    from PySide6.QtCore import QTimer
    
    def setup_file_tree_anonym_column(self) -> None:
        """
        Zajistí viditelný header, názvy sloupců a doplnění ikon/textu:
        - index 4: „Anonymizace“
        - index 5: „Polygon“ (přítomnost AOI_POLYGON)
        """
        tree = getattr(self, "file_tree", None)
        if tree is None:
            return
    
        try:
            tree.header().setVisible(True)
        except Exception:
            pass
    
        # Minimálně 6 sloupců
        if tree.columnCount() < 6:
            tree.setColumnCount(6)
    
        header = tree.headerItem()
        if header is not None:
            if not header.text(0):
                header.setText(0, "Název")
            header.setText(4, "Anonymizace")
            header.setText(5, "Polygon")
    
        try:
            if tree.columnWidth(4) < 100:
                tree.setColumnWidth(4, 130)
            if tree.columnWidth(5) < 90:
                tree.setColumnWidth(5, 110)
        except Exception:
            pass
    
        # Úvodní asynchronní aktualizace po naplnění stromu
        QTimer.singleShot(0, self._update_anonymization_column)
        
    # Soubor: main_window.py
    # Třída: MainWindow
    # FUNKCE: has_aoi_polygon  (NOVÁ)
    # ÚČEL: detekce přítomnosti textového metadata 'AOI_POLYGON' (neprázdná hodnota)
    
    from pathlib import Path
    
    def has_aoi_polygon(self, png_path: str) -> bool:
        """
        Vrací True, pokud PNG obsahuje v textových metadatech klíč 'AOI_POLYGON' s neprázdnou hodnotou.
        """
        p = Path(png_path)
        if p.suffix.lower() != ".png" or not p.exists():
            return False
    
        try:
            from PIL import Image
            with Image.open(str(p)) as img:
                kv = {}
                try:
                    if hasattr(img, "text") and img.text:
                        kv = dict(img.text)
                except Exception:
                    kv = {}
    
                for k, v in kv.items():
                    if str(k).strip() == "AOI_POLYGON":
                        return bool(str(v).strip())
        except Exception:
            return False
    
        return False
        
    # ✅ ÚPRAVA 2 — HELPER: ZAJIŠTĚNÍ SLOUPCE + PŘEKRESLENÍ
    # Soubor: main_window.py
    # Třída: MainWindow
    # PŘIDEJTE TUTO NOVOU FUNKCI
    
    from PySide6.QtGui import QIcon
    
    def _ensure_anonym_column_and_update(self) -> None:
        """
        Zajistí existenci 2. sloupce a přegeneruje ikony/stavy ve sloupci 'Anonymizace'.
        Volá se po refreshi/modelReset/layoutChanged/rowsInserted…
        """
        tree = getattr(self, "file_tree", None)
        if tree is None:
            return
    
        # Neustále drž min. 2 sloupce
        if tree.columnCount() < 2:
            tree.setColumnCount(2)
    
        # Drž text hlavičky
        header = tree.headerItem()
        if header is not None:
            if not header.text(0):
                header.setText(0, "Název")
            header.setText(1, "Anonymizace")
    
        # Sloupec může být nulové šířky po některých operacích -> nastav znovu
        try:
            if tree.columnWidth(1) < 30:
                tree.setColumnWidth(1, 140)
        except Exception:
            pass
    
        # Aktualizuj hodnoty/ikony
        try:
            self._update_anonymization_column()
        except Exception:
            pass

    # Soubor: main_window.py
    # Třída: MainWindow
    # NAHRAĎTE CELOU FUNKCI has_anonymized_location_flag TOUTO VERZÍ
    # (jen drobné zpřesnění vyhodnocení hodnoty metadata)
    from pathlib import Path
    
    def has_anonymized_location_flag(self, png_path: str) -> bool:
        """
        True, pokud PNG obsahuje textové metadata s klíčem 'Anonymizovaná lokace' (nebo bez diakritiky)
        a hodnotou odpovídající „Ano“ (povoleno: 'Ano', 'ano', 'yes', 'true', '1').
        """
        p = Path(png_path)
        if p.suffix.lower() != ".png" or not p.exists():
            return False
    
        try:
            from PIL import Image
            with Image.open(str(p)) as img:
                kv = {}
                try:
                    if hasattr(img, "text") and img.text:
                        kv = dict(img.text)
                    elif "parameters" in img.info:
                        kv = {"parameters": str(img.info.get("parameters", ""))}
                except Exception:
                    kv = {}
    
                def _norm(s: str) -> str:
                    return str(s).strip().lower()
    
                for k, v in kv.items():
                    nk = _norm(k)
                    if nk in ("anonymizovaná lokace", "anonymizovana lokace"):
                        vv = _norm(v)
                        return vv in ("ano", "yes", "true", "1")
        except Exception:
            return False
    
        return False
    
    def _update_anonymization_column(self) -> None:
        """
        Aktualizuje sloupce:
          - sloupec „Anonymizace“: podle metadat 'Anonymizovaná lokace'
          - sloupec „Polygon“: podle metadat 'AOI_POLYGON' + (NOVĚ) zobrazí i AOI_AREA_M2 ve formátu 'Ano (123.45 m²)'
        Sloupce se hledají DYNAMICKY podle textu hlaviček, aby nebyly závislé na pevných indexech.
        """
        tree = getattr(self, "file_tree", None)
        if tree is None or tree.topLevelItemCount() == 0:
            return
    
        # ——— Najdi indexy sloupců podle hlaviček ———
        header = tree.headerItem() if hasattr(tree, "headerItem") else None
        col_anon = None
        col_poly = None
        if header:
            for ci in range(header.columnCount()):
                name = (header.text(ci) or "").strip().lower()
                if name == "anonymizace" and col_anon is None:
                    col_anon = ci
                elif name == "polygon" and col_poly is None:
                    col_poly = ci
        # Fallback pro případ, že hlavička je přejmenovaná/nedostupná (nezmění-li se nic, prostě skončíme)
        if col_anon is None or col_poly is None:
            # Původní odhad (pokud bys je měl na fixních pozicích)
            if col_anon is None: col_anon = 4
            if col_poly is None: col_poly = 5
    
        from PySide6.QtWidgets import QApplication, QStyle, QTreeWidgetItem
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import Qt
        from pathlib import Path
    
        style = self.style() if hasattr(self, "style") else QApplication.style()
        icon_yes = style.standardIcon(QStyle.SP_DialogApplyButton)
        icon_no = style.standardIcon(QStyle.SP_DialogCancelButton)
        empty_icon = QIcon()
    
        def read_meta_map(png_path: str) -> dict:
            try:
                return self._read_png_text_meta(png_path) or {}
            except Exception:
                return {}
    
        def has_anon_flag(meta: dict) -> bool:
            try:
                for k in ("Anonymizovaná lokace", "Anonymizovana lokace"):
                    if k in meta:
                        v = str(meta.get(k) or "").strip().lower()
                        return v in ("ano", "yes", "true", "1")
            except Exception:
                pass
            return False
    
        def has_polygon(meta: dict) -> bool:
            try:
                v = meta.get("AOI_POLYGON")
                if v is None:
                    for k, vv in meta.items():
                        if str(k).strip().upper() == "AOI_POLYGON":
                            v = vv
                            break
                return bool(str(v or "").strip())
            except Exception:
                return False
    
        def parse_area_m2(meta: dict) -> str | None:
            try:
                raw = None
                if "AOI_AREA_M2" in meta:
                    raw = meta.get("AOI_AREA_M2")
                else:
                    for k, v in meta.items():
                        if str(k).strip().upper() == "AOI_AREA_M2":
                            raw = v
                            break
                if raw is None:
                    return None
                s = str(raw).strip()
                try:
                    val = float(s.replace(",", "."))
                    return f"{val:.2f}"
                except Exception:
                    return s if s else None
            except Exception:
                return None
    
        def guess_path(item: QTreeWidgetItem) -> Path | None:
            # preferuj uloženou cestu v UserRole
            for role in (Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2):
                try:
                    val = item.data(0, role)
                    if val:
                        p = Path(str(val))
                        if p.exists():
                            return p
                except Exception:
                    pass
            # fallback z textu/tooltipu (pokud ukládáš)
            try:
                tt = item.toolTip(0)
                if tt:
                    p = Path(tt)
                    if p.exists():
                        return p
            except Exception:
                pass
            return None
    
        def process_item(item: QTreeWidgetItem):
            p = guess_path(item)
            # Neplatné nebo ne-PNG → vyčisti sloupce
            if not p or not p.exists() or p.suffix.lower() != ".png":
                try:
                    item.setIcon(col_anon, empty_icon); item.setText(col_anon, ""); item.setToolTip(col_anon, "")
                except Exception:
                    pass
                try:
                    item.setIcon(col_poly, empty_icon); item.setText(col_poly, ""); item.setToolTip(col_poly, "")
                except Exception:
                    pass
                for i in range(item.childCount()):
                    process_item(item.child(i))
                return
    
            meta = read_meta_map(str(p))
            is_anon = has_anon_flag(meta)
            has_poly = has_polygon(meta)
    
            # Sloupec „Anonymizace“
            try:
                if is_anon:
                    item.setIcon(col_anon, icon_yes)
                    item.setText(col_anon, "Ano")
                    item.setToolTip(col_anon, f"Anonymizovaná lokace: Ano\n{p}")
                else:
                    item.setIcon(col_anon, icon_no)
                    item.setText(col_anon, "Ne")
                    item.setToolTip(col_anon, f"Anonymizovaná lokace: Ne\n{p}")
            except Exception:
                pass
    
            # Sloupec „Polygon“ + plocha AOI_AREA_M2
            try:
                if has_poly:
                    area = parse_area_m2(meta)  # např. '468.58'
                    item.setIcon(col_poly, icon_yes)
                    if area:
                        item.setText(col_poly, f"Ano ({area} m²)")
                        item.setToolTip(col_poly, f"Polygon v metadatech (AOI_POLYGON): Ano\nAOI_AREA_M2: {area} m²\n{p}")
                    else:
                        item.setText(col_poly, "Ano")
                        item.setToolTip(col_poly, f"Polygon v metadatech (AOI_POLYGON): Ano\n{p}")
                else:
                    item.setIcon(col_poly, icon_no)
                    item.setText(col_poly, "Ne")
                    item.setToolTip(col_poly, f"Polygon v metadatech (AOI_POLYGON): Ne\n{p}")
            except Exception:
                pass
    
            for i in range(item.childCount()):
                process_item(item.child(i))
    
        for t in range(tree.topLevelItemCount()):
            process_item(tree.topLevelItem(t))

    
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    
    def add_anonymized_location_flag(self, png_path: str, suppress_ui: bool = False) -> bool:
        """
        Připíše textový příznak 'Anonymizovaná lokace' do metadat PNG (tEXt).
        Zachová stávající textová metadata i DPI.
        """
        try:
            p = Path(png_path)
            if p.suffix.lower() != ".png" or not p.exists():
                return False
    
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
    
            with Image.open(str(p)) as img:
                # existující textová metadata
                existing_text = {}
                try:
                    if hasattr(img, "text") and img.text:
                        existing_text = dict(img.text)
                except Exception:
                    existing_text = {}
    
                pnginfo = PngInfo()
                for k, v in existing_text.items():
                    if str(k).strip().lower() != "anonymizovaná lokace":
                        try:
                            pnginfo.add_text(str(k), str(v))
                        except Exception:
                            continue
    
                try:
                    pnginfo.add_text("Anonymizovaná lokace", "Ano")
                except Exception:
                    pnginfo.add_text("Anonymizovana lokace", "Ano")
    
                dpi = img.info.get("dpi", (72, 72))
                img.save(str(p), "PNG", pnginfo=pnginfo, dpi=dpi)
    
            try:
                if hasattr(self, "log_widget"):
                    self.log_widget.add_log(f"✅ Do metadat přidán příznak „Anonymizovaná lokace“: {p.name}", "success")
            except Exception:
                pass
    
            if not suppress_ui:
                try:
                    self.refresh_file_tree()
                except Exception:
                    pass
                # → pevně zajisti sloupec + ikony i po refreshi
                try:
                    self._ensure_anonym_column_and_update()
                except Exception:
                    pass
                try:
                    QMessageBox.information(self, "Hotovo", f"Do metadat byl přidán příznak:\n{p}")
                except Exception:
                    pass
    
            return True
    
        except Exception as e:
            if not suppress_ui:
                try:
                    QMessageBox.critical(self, "Chyba", f"Nepodařilo se zapsat příznak do PNG:\n{e}")
                except Exception:
                    pass
            try:
                if hasattr(self, "log_widget"):
                    self.log_widget.add_log(f"❌ Chyba při přidávání příznaku do metadat: {e}", "error")
            except Exception:
                pass
            return False
        
    # ✅ ÚPRAVA 6 — HROMADNÁ AKCE (DOPLNĚNO: PEVNÁ RE-AKTUALIZACE PO REFRESHI)
    # Soubor: main_window.py
    # Třída: MainWindow
    # NAHRAĎTE CELOU FUNKCI add_anonymized_location_flag_bulk TOUTO VERZÍ
    
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtCore import Qt
    
    # ✅ ÚPRAVA 1 — Odstranění příznaku u jednoho PNG
    # Soubor: main_window.py
    # Třída: MainWindow
    # PŘIDEJTE TUTO NOVOU FUNKCI (např. pod add_anonymized_location_flag)
    
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    
    def remove_anonymized_location_flag(self, png_path: str, suppress_ui: bool = False) -> bool:
        """
        Odstraní z PNG textové metadata s klíčem 'Anonymizovaná lokace' (případně bez diakritiky).
        Zachová ostatní textová metadata i DPI.
    
        Args:
            png_path: Cesta k PNG souboru.
            suppress_ui: Pokud True, neukazuje dialogy ani neobnovuje strom (vhodné pro hromadné zpracování).
    
        Returns:
            bool: True při úspěchu (i když klíč nebyl přítomen), False při chybě zápisu.
        """
        try:
            p = Path(png_path)
            if p.suffix.lower() != ".png" or not p.exists():
                return False
    
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
    
            with Image.open(str(p)) as img:
                # Načti existující textová metadata
                existing_text = {}
                try:
                    if hasattr(img, "text") and img.text:
                        existing_text = dict(img.text)
                except Exception:
                    existing_text = {}
    
                # Připrav nové PNG info bez našich klíčů
                pnginfo = PngInfo()
                removed = False
                for k, v in existing_text.items():
                    kl = str(k).strip().lower()
                    if kl in ("anonymizovaná lokace", "anonymizovana lokace"):
                        removed = True
                        continue  # přeskočit – tím se příznak odstraní
                    try:
                        pnginfo.add_text(str(k), str(v))
                    except Exception:
                        continue
    
                # Zachovat DPI, pokud existuje
                dpi = img.info.get("dpi", (72, 72))
                img.save(str(p), "PNG", pnginfo=pnginfo, dpi=dpi)
    
            try:
                if hasattr(self, "log_widget"):
                    if removed:
                        self.log_widget.add_log(f"🗑️ Z metadat odstraněn příznak „Anonymizovaná lokace“: {p.name}", "info")
                    else:
                        self.log_widget.add_log(f"ℹ️ Příznak „Anonymizovaná lokace“ nebyl v {p.name} nalezen (soubor přepsán beze změny příznaku).", "warning")
            except Exception:
                pass
    
            if not suppress_ui:
                try:
                    self.refresh_file_tree()
                except Exception:
                    pass
                try:
                    # Aktualizace sloupce „Anonymizace“ (index 4)
                    if hasattr(self, "_update_anonymization_column"):
                        self._update_anonymization_column()
                except Exception:
                    pass
                try:
                    QMessageBox.information(self, "Hotovo", f"Odstranění příznaku dokončeno:\n{p}")
                except Exception:
                    pass
    
            return True
    
        except Exception as e:
            if not suppress_ui:
                try:
                    QMessageBox.critical(self, "Chyba", f"Nepodařilo se odstranit příznak z PNG:\n{e}")
                except Exception:
                    pass
            try:
                if hasattr(self, "log_widget"):
                    self.log_widget.add_log(f"❌ Chyba při odstraňování příznaku z metadat: {e}", "error")
            except Exception:
                pass
            return False
    
    def add_anonymized_location_flag_bulk(self) -> None:
        """
        Projde aktuálně vybrané položky ve stromu a pro všechny .png soubory
        připíše příznak 'Anonymizovaná lokace' do metadat. Nezobrazuje per-soubor dialogy.
        """
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import Qt
        from pathlib import Path
        
        selected = self.file_tree.selectedItems() if hasattr(self, "file_tree") else []
        png_paths = []
        
        for it in selected:
            try:
                fp = it.data(0, Qt.UserRole)
                if not fp:
                    continue
                p = Path(fp)
                if p.is_file() and p.suffix.lower() == ".png" and p.exists():
                    png_paths.append(p)
            except Exception:
                continue
        
        if not png_paths:
            QMessageBox.information(self, "Informace", "Ve výběru nejsou žádné PNG soubory.")
            return
        
        ok, fail = 0, []
        for p in png_paths:
            if self.add_anonymized_location_flag(str(p), suppress_ui=True):
                ok += 1
            else:
                fail.append(p.name)
        
        # Obnov strom jednou
        try:
            self.refresh_file_tree()
        except Exception:
            pass
        
        # Pevně zajisti sloupec + ikony i po refreshi
        try:
            if hasattr(self, "_update_anonymization_column"):
                self._update_anonymization_column()
        except Exception:
            pass
        
        if fail:
            QMessageBox.warning(
                self,
                "Dokončeno s chybami",
                f"Příznak byl úspěšně přidán do {ok} souborů.\n"
                f"Chyba u: {', '.join(fail)}"
            )
        else:
            QMessageBox.information(self, "Hotovo", f"Příznak byl přidán do {ok} PNG souborů.")

    
    from PySide6.QtCore import Qt
    
    def remove_anonymized_location_flag_bulk(self) -> None:
        """
        Projde aktuálně vybrané položky ve stromu a u všech .png souborů
        odstraní z metadat příznak 'Anonymizovaná lokace'. Nezobrazuje per-soubor dialogy.
        """
        selected = self.file_tree.selectedItems() if hasattr(self, "file_tree") else []
        png_paths = []
        for it in selected:
            try:
                fp = it.data(0, Qt.UserRole)
                if not fp:
                    continue
                p = Path(fp)
                if p.is_file() and p.suffix.lower() == ".png" and p.exists():
                    png_paths.append(p)
            except Exception:
                continue
    
        if not png_paths:
            QMessageBox.information(self, "Informace", "Ve výběru nejsou žádné PNG soubory.")
            return
    
        ok, fail = 0, []
        for p in png_paths:
            if self.remove_anonymized_location_flag(str(p), suppress_ui=True):
                ok += 1
            else:
                fail.append(p.name)
    
        # Obnov strom jednou a aktualizuj sloupec „Anonymizace“
        try:
            self.refresh_file_tree()
        except Exception:
            pass
        try:
            if hasattr(self, "_update_anonymization_column"):
                self._update_anonymization_column()
        except Exception:
            pass
    
        if fail:
            QMessageBox.warning(
                self,
                "Dokončeno s chybami",
                f"Příznak byl z metadat odebrán u {ok} souborů.\n"
                f"Chyba u: {', '.join(fail)}"
            )
        else:
            QMessageBox.information(self, "Hotovo", f"Příznak byl z metadat odebrán u {ok} PNG souborů.")
                
    def open_web_photos_window(self):
        """
        Otevře 'Web fotky' jako NEmodální okno (hlavní okno zůstává použitelné).
        - Pokud už okno běží, jen ho vyzvedne do popředí.
        - Logy (pokud je k dispozici self.log_widget.add_log) se přesměrují dovnitř.
        """
        try:
            from PySide6.QtCore import Qt
            # Přesměrování logů do hlavního log widgetu (pokud existuje)
            log_fn = None
            if hasattr(self, 'log_widget') and hasattr(self.log_widget, 'add_log'):
                log_fn = self.log_widget.add_log
    
            # Pokud už máme okno, jen ho vyzvedni
            win = getattr(self, "_web_photos_win", None)
            try:
                if win is not None and win.isVisible():
                    win.raise_()
                    win.activateWindow()
                    return
            except Exception:
                pass
    
            # Nová instance – NEmodální
            dlg = WebPhotosWindow(parent=self, log_fn=log_fn)
    
            # Zajistit nemodalitu a korektní úklid po zavření
            try: dlg.setWindowModality(Qt.NonModal)
            except Exception: pass
            try: dlg.setModal(False)  # pokud je to QDialog
            except Exception: pass
            try: dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            except Exception: pass
    
            # Ulož referenci, ať okno nezmizí garbage collectorem
            self._web_photos_win = dlg
            try:
                dlg.destroyed.connect(lambda *_: setattr(self, "_web_photos_win", None))
            except Exception:
                pass
    
            dlg.show()
            try:
                dlg.raise_()
                dlg.activateWindow()
            except Exception:
                pass
    
        except Exception as e:
            # Fallback – zapiš do logu nebo ukaž message box
            if hasattr(self, 'log_widget') and hasattr(self.log_widget, 'add_log'):
                self.log_widget.add_log(f"❌ Nelze otevřít 'Web fotky': {e}", "error")
            else:
                try:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.critical(self, "Chyba", f"Nelze otevřít 'Web fotky':\n{e}")
                except Exception:
                    pass

    # uvnitř třídy MainWindow
    def _on_viewer_current_file_changed(self, path_str: str):
        """Převezme cestu z náhledu a označí odpovídající položku ve stromu."""
        try:
            # Preferuj robustní expand_and_select_path, případně fallback
            if hasattr(self, "expand_and_select_path"):
                self.expand_and_select_path(path_str)
            elif hasattr(self, "_select_path_in_tree"):
                self._select_path_in_tree(path_str)
        except Exception:
            # Tiché selhání bez pádu UI
            pass

        
    def add_toolbar_gap(toolbar: QToolBar, width_px: int, before_action: QAction | None = None) -> QWidget:
        """Vloží do QToolBar pevnou mezeru (šířka v px); pokud je zadán before_action, vloží před ni, jinak na konec."""
        gap = QWidget(toolbar)
        gap.setFixedWidth(int(width_px))
        gap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        if before_action is None:
            toolbar.addWidget(gap)
        else:
            toolbar.insertWidget(before_action, gap)
        return gap

    def close_active_child_dialogs(self):
        """NOVÁ FUNKCE: Zavře všechna otevřená QDialog podokna (Cmd+W / Close)."""
        try:
            from PySide6.QtWidgets import QApplication, QDialog
            for w in QApplication.topLevelWidgets():
                if isinstance(w, QDialog) and w.isVisible():
                    try:
                        w.reject()  # korektní zavření modálních dialogů
                    except Exception:
                        w.close()
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ CMD+W: Chyba při zavírání podoken: {e}", "warning")
                
    def show_tree_help(self):
        """Zobrazí modální nápovědu s klávesovými zkratkami pro strom souborů/složek."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout
        from PySide6.QtGui import QFont, QShortcut, QKeySequence
        import sys
    
        lines = []
        lines.append("Klávesové zkratky pro stromovou strukturu:\n")
        # Enter/Return → přejmenovat (pokud je k dispozici handler)
        if hasattr(self, 'rename_selected_item'):
            lines.append("Enter / Return — Přejmenovat vybraný soubor (1 položka)")
        # Space → náhled a druhým Space zavřít (při náhledu ze stromu)
        lines.append("Space — Otevřít náhled vybraného obrázku; v náhledu otevřeném ze stromu zavře dialog")
        # Delete → smazat (pozn.: na macOS často fn+Backspace)
        lines.append("Cmd+Backspace — Smazat vybrané položky")
        # Otevřít editor polygonu
        if hasattr(self, 'on_edit_polygon'):
            lines.append("Cmd+O — Otevřít editor polygonu (Upravit oblast) pro vybraný PNG")
        # Copy / Cut / Paste (pokud jsou k dispozici)
        if hasattr(self, 'copy_selected_item'):
            lines.append("Ctrl/Cmd+C — Kopírovat vybrané položky")
        if hasattr(self, 'cut_selected_items'):
            lines.append("Ctrl/Cmd+X — Vyjmout (přesunout) vybrané položky")
        if hasattr(self, 'paste_to_selected_folder'):
            lines.append("Ctrl/Cmd+V — Vložit do aktuálně vybraného cílového umístění")
        # Nová složka v kořeni
        if hasattr(self, 'create_root_folder'):
            lines.append("Cmd+Shift+N — Vytvořit novou složku v kořeni 'mapky lokací'")
            
        # NOVÉ: Přidat informace o filtru
        lines.append("CMD+F / Ctrl+F — Focus na filtr 'Neroztříděné' (rychlé vyhledávání)")
        lines.append("CMD+Z / Ctrl+Z — Vymazat filtr 'Neroztříděné' (zobrazit vše)")
        # Ostatní (implicitní chování stromu)
        lines.append("Šipky ↑/↓/←/→ — Pohyb a rozbalování/sbalování v seznamu")
        lines.append("Home / End — Na začátek / konec seznamu")
        lines.append("Page Up / Page Down — Stránkování seznamu")
        text = "\n".join(lines)
    
        dlg = QDialog(self)
        dlg.setWindowTitle("Nápověda – stromová struktura")
        layout = QVBoxLayout(dlg)
    
        intro = QLabel("Dostupné klávesové zkratky pro práci ve stromu:")
        layout.addWidget(intro)
    
        txt = QTextEdit()
        txt.setReadOnly(True)
        f = QFont("Monaco", 11) if sys.platform == "darwin" else QFont("Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono", 11)
        txt.setFont(f)
        txt.setPlainText(text)
        layout.addWidget(txt, 1)
    
        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_close = QPushButton("Zavřít")
        btn_close.clicked.connect(dlg.accept)
        btns.addWidget(btn_close)
        layout.addLayout(btns)
    
        # Cmd+W / Ctrl+W → zavřít nápovědu
        sc_close = QShortcut(QKeySequence(QKeySequence.Close), dlg)
        sc_close.setAutoRepeat(False)
        sc_close.setContext(Qt.WidgetWithChildrenShortcut)
        sc_close.activated.connect(dlg.accept)
    
        dlg.resize(700, 420)
        dlg.exec()

    def create_file_tree_widget(self):
        """UPRAVENÁ FUNKCE: Stromová struktura + sjednocený styl tlačítek bez nepodporovaných QSS vlastností + tlačítko 'Upravit oblast'"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        title_label = QLabel("📁 Mapky lokací")
        title_label.setStyleSheet("QLabel { font-weight: bold; font-size: 14px; }")
        header_layout.addWidget(title_label)

        base_btn_qss = """
        QPushButton {
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            color: white;
        }
        """
        def style_btn(btn: QPushButton, base: str, hover: str, pressed: str, max_w: int | None = None):
            btn.setMinimumHeight(32)
            if max_w:
                btn.setMaximumWidth(max_w)
            btn.setStyleSheet(
                base_btn_qss
                + f"QPushButton {{ background-color: {base}; }}\n"
                  f"QPushButton:hover {{ background-color: {hover}; }}\n"
                  f"QPushButton:pressed {{ background-color: {pressed}; }}\n"
            )

        LIGHT_BLUE = ("#42A5F5", "#2196F3", "#1976D2")
        TEAL = ("#009688", "#00897B", "#00695C")
        GREEN = ("#2e7d32", "#388e3c", "#1b5e20")
        ORANGE = ("#fb8c00", "#f57c00", "#e65100")
        RED = ("#e53935", "#d32f2f", "#b71c1c")
        YELLOW = ("#FBC02D", "#F9A825", "#F57F17")
        GREY = ("#616161", "#757575", "#424242")

        self.btn_refresh_tree = QPushButton("🔄 Obnovit")
        style_btn(self.btn_refresh_tree, *LIGHT_BLUE, 150)
        self.btn_refresh_tree.clicked.connect(self.refresh_file_tree)
        header_layout.addWidget(self.btn_refresh_tree, 0, Qt.AlignVCenter)

        self.btn_open_folder = QPushButton("📂 Otevřít složku ve Finderu")
        style_btn(self.btn_open_folder, *TEAL, 240)
        self.btn_open_folder.setToolTip("Otevře výchozí složku s mapkami ve Finderu")
        self.btn_open_folder.clicked.connect(self.open_maps_folder)
        header_layout.addWidget(self.btn_open_folder, 0, Qt.AlignVCenter)

        self.btn_expand_all = QPushButton("📖 Rozbalit vše")
        style_btn(self.btn_expand_all, *GREEN, 140)
        self.btn_expand_all.clicked.connect(self.expand_all_items)
        header_layout.addWidget(self.btn_expand_all, 0, Qt.AlignVCenter)

        self.btn_collapse_except_unsorted = QPushButton("📕 Sbalit kromě složky Neroztříděné")
        style_btn(self.btn_collapse_except_unsorted, *GREEN, 300)
        self.btn_collapse_except_unsorted.setToolTip("Sbalí všechny složky kromě složky 'Neroztříděné'")
        self.btn_collapse_except_unsorted.clicked.connect(self.collapse_except_unsorted_fixed)
        header_layout.addWidget(self.btn_collapse_except_unsorted, 0, Qt.AlignVCenter)

        self.btn_collapse_all = QPushButton("📕 Sbalit vše")
        style_btn(self.btn_collapse_all, *GREEN, 140)
        self.btn_collapse_all.clicked.connect(self.collapse_all_items)
        header_layout.addWidget(self.btn_collapse_all, 0, Qt.AlignVCenter)

        self.btn_tree_help = QPushButton("❔ Nápověda stromu")
        style_btn(self.btn_tree_help, *GREY, 180)
        self.btn_tree_help.setToolTip("Zobrazí klávesové zkratky dostupné ve stromu")
        self.btn_tree_help.clicked.connect(self.show_tree_help)
        header_layout.addWidget(self.btn_tree_help, 0, Qt.AlignVCenter)

        header_layout.addStretch()

        self.btn_edit_polygon = QPushButton("🔺 Upravit oblast")
        style_btn(self.btn_edit_polygon, *YELLOW, 170)
        self.btn_edit_polygon.setToolTip("Nakreslí nebo upraví polygonovou vrstvu v PNG mapě")
        self.btn_edit_polygon.clicked.connect(self.on_edit_polygon)
        header_layout.addWidget(self.btn_edit_polygon, 0, Qt.AlignVCenter)

        self.btn_browse_from_00001 = QPushButton("🧭 Prohlížeč od 00001")
        style_btn(self.btn_browse_from_00001, *ORANGE, 240)
        self.btn_browse_from_00001.setToolTip("Otevře prohlížeč mapek seřazeně od nejnižšího ID lokace")
        self.btn_browse_from_00001.clicked.connect(self.open_unsorted_browser_from_min)
        header_layout.addWidget(self.btn_browse_from_00001, 0, Qt.AlignVCenter)

        self.btn_browse_unsorted = QPushButton("🖼️ Prohlížeč Neroztříděné")
        style_btn(self.btn_browse_unsorted, *ORANGE, 240)
        self.btn_browse_unsorted.setToolTip("Otevře prohlížeč všech obrázků ve složce 'Neroztříděné' aktuální výstupní složky")
        self.btn_browse_unsorted.clicked.connect(self.open_unsorted_browser)
        header_layout.addWidget(self.btn_browse_unsorted, 0, Qt.AlignVCenter)

        self.btn_regenerate_selected = QPushButton("♻️ Přegenerovat vybrané")
        style_btn(self.btn_regenerate_selected, *RED, 220)
        self.btn_regenerate_selected.setToolTip("Znovu vygeneruje vybrané lok. mapy s aktuálními výstupními parametry (cm/DPI)")
        self.btn_regenerate_selected.clicked.connect(self.regenerate_selected_items)
        header_layout.addWidget(self.btn_regenerate_selected, 0, Qt.AlignVCenter)

        layout.addLayout(header_layout)

        path_layout = QHBoxLayout()
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)
        path_label = QLabel("📍 Cesta:")
        path_layout.addWidget(path_label)
        self.label_maps_path = QLabel(str(self.default_maps_path))
        self.label_maps_path.setStyleSheet("QLabel { color: #aaa; font-family: monospace; font-size: 10px; }")
        self.label_maps_path.setWordWrap(True)
        path_layout.addWidget(self.label_maps_path)
        layout.addLayout(path_layout)

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(6)
        filter_label = QLabel("🔎 Filtr 'Neroztříděné':")
        self.edit_unsorted_filter = QLineEdit()
        self.edit_unsorted_filter.setPlaceholderText("Zadejte text pro filtrování pouze ve složce 'Neroztříděné'…")
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.edit_unsorted_filter, 1)
        layout.addLayout(filter_layout)

        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(6)

        self.btn_sort_unsorted_by_loc = QPushButton("Seřadit podle čísla lokace")
        self.btn_sort_unsorted_by_loc.setFixedHeight(22)
        self.btn_sort_unsorted_by_loc.setMinimumWidth(160)
        self.btn_sort_unsorted_by_loc.setCursor(Qt.PointingHandCursor)
        self.btn_sort_unsorted_by_loc.setToolTip("Seřadí soubory ve složce 'Neroztříděné' podle posledního 5místného čísla v názvu (00001, 00002, …).")
        self.btn_sort_unsorted_by_loc.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                padding: 2px 8px;
                border-radius: 6px;
                background-color: #eceff1;
                color: #333;
                border: 1px solid #d0d5d8;
            }
            QPushButton:hover { background-color: #e3e7ea; }
            QPushButton:pressed { background-color: #dbe0e4; }
        """)
        self.btn_sort_unsorted_by_loc.clicked.connect(self._on_sort_unsorted_by_location_numbers)
        stats_layout.addWidget(self.btn_sort_unsorted_by_loc, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.btn_sort_unsorted_alpha = QPushButton("Seřadit abecedně")
        self.btn_sort_unsorted_alpha.setFixedHeight(22)
        self.btn_sort_unsorted_alpha.setMinimumWidth(130)
        self.btn_sort_unsorted_alpha.setCursor(Qt.PointingHandCursor)
        self.btn_sort_unsorted_alpha.setToolTip("Seřadí soubory i složky ve složce 'Neroztříděné' čistě abecedně podle názvu.")
        self.btn_sort_unsorted_alpha.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                padding: 2px 8px;
                border-radius: 6px;
                background-color: #f0f3f5;
                color: #333;
                border: 1px solid #d0d5d8;
            }
            QPushButton:hover { background-color: #e7ecef; }
            QPushButton:pressed { background-color: #dfe5e9; }
        """)
        self.btn_sort_unsorted_alpha.clicked.connect(self._on_sort_unsorted_alphabetically)
        stats_layout.addWidget(self.btn_sort_unsorted_alpha, 0, Qt.AlignLeft | Qt.AlignVCenter)

        # ⬇️ NOVÉ MALÉ TLAČÍTKO: seřadí CELÝ strom abecedně (rekurzivně)
        self.btn_sort_tree_alpha = QPushButton("Seřadit strom abecedně")
        self.btn_sort_tree_alpha.setFixedHeight(22)
        self.btn_sort_tree_alpha.setMinimumWidth(170)
        self.btn_sort_tree_alpha.setCursor(Qt.PointingHandCursor)
        self.btn_sort_tree_alpha.setToolTip("Rekurzivně seřadí CELÝ strom podle názvu (složky nad soubory).")
        self.btn_sort_tree_alpha.setStyleSheet("""
            QPushButton {
                font-size: 11px;
                padding: 2px 8px;
                border-radius: 6px;
                background-color: #eef3f6;
                color: #333;
                border: 1px solid #d0d5d8;
            }
            QPushButton:hover { background-color: #e5ebee; }
            QPushButton:pressed { background-color: #dce3e7; }
        """)
        self.btn_sort_tree_alpha.clicked.connect(self._on_sort_tree_globally_by_name)
        stats_layout.addWidget(self.btn_sort_tree_alpha, 0, Qt.AlignLeft | Qt.AlignVCenter)

        # 🔴 NOVÉ: Tlačítko pro přepočítání ploch polygonů
        self.btn_recalculate_areas = QPushButton("Přepočítat plochy polygonů")
        self.btn_recalculate_areas.setFixedHeight(22)
        self.btn_recalculate_areas.setMinimumWidth(210)
        self.btn_recalculate_areas.setCursor(Qt.PointingHandCursor)
        self.btn_recalculate_areas.setToolTip("Přepočítá plochy AOI_AREA_M2 u všech PNG map s polygonem ve složce Neroztříděné")
        self.btn_recalculate_areas.setStyleSheet("""
            QPushButton { 
                font-size: 11px; padding: 2px 8px; border-radius: 6px; 
                background-color: #e53935; color: white; border: 1px solid #d32f2f; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #d32f2f; }
            QPushButton:pressed { background-color: #b71c1c; }
        """)
        self.btn_recalculate_areas.clicked.connect(self.recalculate_unsorted_areas)
        stats_layout.addWidget(self.btn_recalculate_areas, 0, Qt.AlignLeft | Qt.AlignVCenter)

        stats_layout.addStretch()
        self.unsorted_id_label = QLabel("🔢 Neroztříděné: —")
        self.unsorted_id_label.setStyleSheet("QLabel { color: #666; font-weight: 600; }")
        stats_layout.addWidget(self.unsorted_id_label)
        layout.addLayout(stats_layout)

        from PySide6.QtCore import QTimer
        self._unsorted_filter_timer = QTimer(self)
        self._unsorted_filter_timer.setSingleShot(True)
        self._unsorted_filter_timer.timeout.connect(self._apply_unsorted_filter)
        self.edit_unsorted_filter.textChanged.connect(lambda _: self._unsorted_filter_timer.start(200))

        # ⬇️ UPRAVENO: přidán 6. sloupec „Polygon"
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Název", "Typ", "Velikost", "Změněno", "Anonymizace", "Polygon"])
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.setRootIsDecorated(True)
        self.file_tree.setSortingEnabled(True)
        self.file_tree.sortByColumn(0, Qt.AscendingOrder)
        self.file_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.show_context_menu)

        try:
            self.file_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            self.file_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Anonymizace
            self.file_tree.header().setSectionResizeMode(5, QHeaderView.ResizeToContents)  # ⬅️ Polygon
        except AttributeError:
            self.file_tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
            self.file_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            self.file_tree.header().setSectionResizeMode(5, QHeaderView.ResizeToContents)

        self.file_tree.header().setMinimumSectionSize(18)
        self.file_tree.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.file_tree.itemClicked.connect(self.on_file_clicked)
        if self.file_tree.selectionModel() is not None:
            self.file_tree.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)
            self.file_tree.selectionModel().currentChanged.connect(self.on_tree_current_changed)

        self.file_tree.header().sectionResized.connect(self.on_tree_section_resized)

        from PySide6.QtGui import QShortcut, QKeySequence
        self._shortcut_delete = QShortcut(QKeySequence("Ctrl+Backspace"), self.file_tree)
        self._shortcut_delete.setAutoRepeat(False)
        self._shortcut_delete.activated.connect(self.delete_selected_items)

        self._shortcut_space = QShortcut(QKeySequence(Qt.Key_Space), self.file_tree)
        self._shortcut_space.setAutoRepeat(False)
        self._shortcut_space.activated.connect(self.preview_selected_file)

        self._shortcut_enter = QShortcut(QKeySequence(Qt.Key_Return), self.file_tree)
        self._shortcut_enter2 = QShortcut(QKeySequence(Qt.Key_Enter), self.file_tree)
        self._shortcut_enter.setAutoRepeat(False)
        self._shortcut_enter2.setAutoRepeat(False)
        self._shortcut_enter.activated.connect(self.rename_selected_item)
        self._shortcut_enter2.activated.connect(self.rename_selected_item)

        self._shortcut_cut = QShortcut(QKeySequence(QKeySequence.Cut), self.file_tree)
        self._shortcut_cut.setAutoRepeat(False)
        self._shortcut_cut.activated.connect(self.cut_selected_items)

        self._shortcut_new_root_folder = QShortcut(QKeySequence("Ctrl+Shift+N"), self.file_tree)
        self._shortcut_new_root_folder.setAutoRepeat(False)
        self._shortcut_new_root_folder.activated.connect(self.create_root_folder)

        self._shortcut_open_polygon = QShortcut(QKeySequence(QKeySequence.Open), self.file_tree)
        self._shortcut_open_polygon.setAutoRepeat(False)
        self._shortcut_open_polygon.activated.connect(self.on_edit_polygon)

        self._shortcut_edit_polygon_cmd_p = QShortcut(QKeySequence("Ctrl+P"), self.file_tree)
        self._shortcut_edit_polygon_cmd_p.setAutoRepeat(False)
        self._shortcut_edit_polygon_cmd_p.setContext(Qt.WidgetWithChildrenShortcut)
        self._shortcut_edit_polygon_cmd_p.activated.connect(self.open_polygon_editor_shortcut)

        self._shortcut_select_all_unsorted = QShortcut(QKeySequence("Ctrl+A"), self.file_tree)
        self._shortcut_select_all_unsorted.setAutoRepeat(False)
        self._shortcut_select_all_unsorted.setContext(Qt.WidgetWithChildrenShortcut)
        self._shortcut_select_all_unsorted.activated.connect(self.select_all_in_unsorted_shortcut)

        layout.addWidget(self.file_tree)
        return widget

    
    def _sort_tree_globally_by_name(self, ascending: bool = True) -> None:
        """
        Rekurzivně seřadí CELÝ strom (všechny úrovně) podle názvu (sloupec 0).
        - Složky vždy před soubory.
        - Unicode-safe (NFC + casefold).
        - Nemění souborový systém.
        - Během přeuspořádání je Qt auto-řazení vypnuto.
        - Po seřazení sjednotí rozbalení voláním 'Sbalit kromě složky Neroztříděné'
          (tj. stejné chování jako tvoje tlačítko).
        """
        from PySide6.QtWidgets import QTreeWidgetItem
        import unicodedata
    
        tree = getattr(self, "file_tree", None)
        if tree is None:
            return
    
        # Dočasně vypnout auto-řazení (ať Qt nepřebije ruční pořadí)
        try:
            tree.setSortingEnabled(False)
        except Exception:
            pass
    
        def _is_dir(it: QTreeWidgetItem) -> bool:
            # Sloupec "Typ" (index 1) – složky mají prefix "📁"
            t = (it.text(1) or "")
            return t.startswith("📁")
    
        def _key_name(it: QTreeWidgetItem) -> str:
            name = it.text(0) or ""
            return unicodedata.normalize('NFC', name).casefold()
    
        def _sort_children(parent: QTreeWidgetItem):
            count = parent.childCount()
            if count == 0:
                return
            children = [parent.child(i) for i in range(count)]
            folders = [it for it in children if _is_dir(it)]
            files = [it for it in children if not _is_dir(it)]
    
            folders.sort(key=_key_name)
            files.sort(key=_key_name)
    
            if not ascending:
                folders.reverse()
                files.reverse()
    
            # Přeskládat pořadí (stejné itemy, jen jiná posloupnost)
            for _ in range(parent.childCount()):
                parent.takeChild(0)
            for it in folders + files:
                parent.addChild(it)
    
            # Rekurze do poduzlů
            for it in folders + files:
                _sort_children(it)
    
        root = tree.invisibleRootItem()
        _sort_children(root)
    
        # Po seřazení použij stejné chování jako tlačítko
        # "📕 Sbalit kromě složky Neroztříděné"
        try:
            if hasattr(self, "collapse_except_unsorted_fixed") and callable(self.collapse_except_unsorted_fixed):
                self.collapse_except_unsorted_fixed()
        except Exception:
            pass
    
        # Obnovit viewport (nevoláme sortByColumn)
        try:
            tree.viewport().update()
        except Exception:
            pass
        
    def _on_sort_tree_globally_by_name(self) -> None:
        """
        Slot pro tlačítko 'Seřadit strom abecedně'.
        Seřadí CELÝ strom vzestupně podle názvu (složky nad soubory).
        """
        try:
            self._sort_tree_globally_by_name(ascending=True)
        except Exception:
            pass
    
    def _on_sort_unsorted_alphabetically(self) -> None:
        """
        Seřadí ZOBRAZENÍ všech položek (soubory i složky) uvnitř uzlu 'Neroztříděné'
        čistě abecedně podle názvu ve sloupci 0. Nemění souborový systém.
        """
        from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem
        import unicodedata
    
        # 1) najdi top-level uzel 'Neroztříděné'
        root_item = self._find_unsorted_root_item_top_level()
        if root_item is None:
            QMessageBox.information(self, "Seřadit abecedně",
                                    "Uzel 'Neroztříděné' nebyl ve stromu nalezen.")
            return
    
        # 2) Dočasně vypnout Qt auto-řazení, aby nepřepsalo ruční pořadí
        try:
            self.file_tree.setSortingEnabled(False)
        except Exception:
            pass
    
        # 3) Seřadit všechny děti uzlu abecedně podle názvu (Unicode-safe)
        def _key_alpha(item: QTreeWidgetItem):
            name = item.text(0) or ""
            return unicodedata.normalize('NFC', name).casefold()
    
        children = [root_item.child(i) for i in range(root_item.childCount())]
        children_sorted = sorted(children, key=_key_alpha)
    
        total = root_item.childCount()
        for _ in range(total):
            root_item.takeChild(0)
        for it in children_sorted:
            root_item.addChild(it)
    
        # 4) Refresh UI
        try:
            self.file_tree.expandItem(root_item)
        except Exception:
            pass
        self.file_tree.viewport().update()
    
        # [ZÁMĚRNĚ] Nezapínám zde Qt auto-řazení, aby se ruční výsledek nepřebil.
        # Klik na hlavičku řeší _ensure_header_global_sort() → globálně seřadí celý strom na požádání.
            
    def _find_unsorted_root_item_top_level(self):
        """
        Vrátí QTreeWidgetItem top-level uzlu 'Neroztříděné'.
        Hledá:
          1) přes Qt.UserRole (absolutní cesta končí '/Neroztříděné' – Unicode NFC/NFD safe),
          2) podle text(0) s Unicode normalizací (NFC).
        """
        import os, unicodedata
        from PySide6.QtCore import Qt
    
        def _norm_path(p: str) -> str:
            s = unicodedata.normalize('NFC', str(p))
            try: s = os.path.abspath(s)
            except Exception: pass
            try: s = os.path.normpath(s)
            except Exception: pass
            return s
    
        expected_suffix = unicodedata.normalize('NFC', os.sep + "Neroztříděné")
    
        # 1) Qt.UserRole u top-level uzlů
        for i in range(self.file_tree.topLevelItemCount()):
            it = self.file_tree.topLevelItem(i)
            if it is None:
                continue
            role = it.data(0, Qt.UserRole)
            if isinstance(role, str):
                role_n = _norm_path(role)
                if role_n.endswith(expected_suffix):
                    return it
    
        # 2) Fallback: podle názvu s NFC (řeší NFD 'Neroztříděné')
        target_name = unicodedata.normalize('NFC', "Neroztříděné")
        for i in range(self.file_tree.topLevelItemCount()):
            it = self.file_tree.topLevelItem(i)
            if it is None:
                continue
            name_n = unicodedata.normalize('NFC', it.text(0) or "")
            if name_n == target_name:
                return it
    
        return None
    
    def _on_sort_unsorted_by_location_numbers(self) -> None:
        """
        Seřadí zobrazení souborů ve složce 'Neroztříděné' podle posledního
        5místného čísla v názvu (00001, 00002, …). Složky zůstanou nahoře
        v původním pořadí. Nemění souborový systém.
        """
        from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem
        from PySide6.QtCore import Qt
        from pathlib import Path
        import re, os, unicodedata
    
        # 1) Najdi root 'Neroztříděné' přes existující helper
        roots = []
        try:
            if hasattr(self, "_find_unsorted_roots"):
                roots = list(self._find_unsorted_roots()) or []
        except Exception:
            roots = []
    
        if not roots:
            QMessageBox.information(self, "Seřadit pod čísla lokace",
                                    "Uzel 'Neroztříděné' nebyl ve stromu nalezen.")
            return
    
        # Pokud by jich bylo víc, preferuj ten, jehož uložená cesta končí '/Neroztříděné'
        def _norm(p: str) -> str:
            s = unicodedata.normalize('NFC', str(p))
            try: s = os.path.abspath(s)
            except Exception: pass
            try: s = os.path.normpath(s)
            except Exception: pass
            return s
    
        root = None
        suffix = os.sep + "Neroztříděné"
        for it in roots:
            try:
                rp = it.data(0, Qt.UserRole)
                if isinstance(rp, str) and _norm(rp).endswith(suffix):
                    root = it
                    break
            except Exception:
                continue
        if root is None:
            root = roots[0]
    
        # 2) Třídicí klíč
        def _is_dir(item: QTreeWidgetItem) -> bool:
            t = (item.text(1) or "")
            return t.startswith("📁")
    
        def _last5(name: str) -> int | None:
            try:
                if hasattr(self, "_extract_last5_id_from_name"):
                    v = self._extract_last5_id_from_name(name)
                    if v is not None:
                        return v
            except Exception:
                pass
            base = Path(name).stem
            m = re.search(r'(\d+)(?!.*\d)', base)  # poslední běh číslic
            return int(m.group(1)) if m else None
    
        def _key(item: QTreeWidgetItem):
            name = item.text(0) or ""
            v = _last5(name)
            if v is not None:
                return (0, v, name.lower())
            return (1, float('inf'), name.lower())  # bez čísla → až nakonec
    
        # 3) Vypnout Qt auto-řazení, aby nepřebilo ruční pořadí
        try:
            self.file_tree.setSortingEnabled(False)
        except Exception:
            pass
    
        # 4) Přeuspořádání: složky ponech, soubory setřiď
        children = [root.child(i) for i in range(root.childCount())]
        folders = [it for it in children if _is_dir(it)]
        files = [it for it in children if not _is_dir(it)]
        files_sorted = sorted(files, key=_key)
    
        total = root.childCount()
        for _ in range(total):
            root.takeChild(0)
        for it in folders + files_sorted:
            root.addChild(it)
    
        # 5) Obnova zobrazení
        try:
            self.file_tree.expandItem(root)
        except Exception:
            pass
        self.file_tree.viewport().update()
    
        # 6) Aktualizace indikátoru (pokud ji máš)
        try:
            if hasattr(self, 'update_unsorted_id_indicator'):
                self.update_unsorted_id_indicator()
        except Exception:
            pass
    
        # [ZÁMĚRNĚ] Nezapínám zde Qt auto-řazení, aby se ruční výsledek nepřebil.
        # Klik na hlavičku řeší _ensure_header_global_sort() → globálně seřadí celý strom na požádání.
    
    def on_tree_current_changed(self, current, previous):
        """
        Reakce na změnu aktuální položky při navigaci klávesnicí.
        """
        try:
            # Zvýraznění podle polygonů při klávesové navigaci
            self.update_polygon_highlights()
            
            # Aktualizace textového indikátoru (pokud chcete zachovat)
            if hasattr(self, 'update_polygon_indicator'):
                self.update_polygon_indicator()
            
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba při navigaci klávesnicí: {e}", "warning")

    def open_unsorted_browser_from_min(self):
        """
        Otevře prohlížeč obrázků ve složce 'Neroztříděné' seřazených podle ID lokace
        (posledních 5 číslic v názvu) vzestupně; začne od nejmenšího ID.
        """
        try:
            import unicodedata
            base = Path(self.input_output_dir.text().strip()).resolve()
    
            # Normalizace názvu pro porovnání (NFC + casefold)
            def norm(s: str) -> str:
                return unicodedata.normalize('NFC', s).casefold()
    
            # Kandidáti názvů složky 'Neroztříděné'
            unsorted_names = ["Neroztříděné", "Neroztridene"]
    
            # Najdi složku Neroztříděné v okolí base (1. base samotná, 2. pod base)
            if any(norm(base.name) == norm(n) for n in unsorted_names):
                folder = base
            else:
                found = None
                for n in unsorted_names:
                    cand = base / n
                    if cand.exists() and cand.is_dir():
                        found = cand
                        break
                folder = found if found is not None else base
    
            if not folder.exists() or not folder.is_dir():
                QMessageBox.information(self, "Info", f"Složka neexistuje:\n{folder}")
                return
    
            # Výběr obrázků
            exts = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif'}
            files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
            if not files:
                QMessageBox.information(self, "Info", f"Ve složce není žádný podporovaný obrázek:\n{folder}")
                return
    
            # Seřaď podle „ID lokace“ = posledních 5 číslic v názvu (když chybí, přesune na konec)
            import re
            def id_or_big(p: Path):
                m = re.search(r'(\d{5})(?!.*\d)', p.stem)  # posledních 5 číslic ve jménu
                return int(m.group(1)) if m else 10**9
    
            files_sorted = sorted(files, key=id_or_big)
    
            # Start od nejmenšího (index 0)
            start_idx = 0
    
            from gui.image_viewer import ImageViewerDialog
            from PySide6.QtCore import Qt, QEvent, QCoreApplication
            from PySide6.QtGui import QKeySequence, QShortcut, QKeyEvent
    
            dialog = ImageViewerDialog(
                files_sorted[start_idx], self, show_delete_button=True,
                file_list=files_sorted, current_index=start_idx, close_on_space=True
            )
    
            # přemapování ↑/↓ na ←/→, ⌘W zavření, mezerník zavření (fallback)
            def _wire_common_shortcuts(dlg):
                try:
                    sc_close = QShortcut(QKeySequence(QKeySequence.Close), dlg)
                    sc_close.setAutoRepeat(False)
                    sc_close.activated.connect(dlg.close)
                except Exception:
                    pass
                def _post_key(key):
                    try:
                        ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
                        QCoreApplication.postEvent(dlg, ev)
                    except Exception:
                        pass
                try:
                    sc_down = QShortcut(QKeySequence(Qt.Key_Down), dlg)
                    sc_down.setAutoRepeat(True)
                    sc_down.activated.connect(lambda: _post_key(Qt.Key_Right))
                except Exception:
                    pass
                try:
                    sc_up = QShortcut(QKeySequence(Qt.Key_Up), dlg)
                    sc_up.setAutoRepeat(True)
                    sc_up.activated.connect(lambda: _post_key(Qt.Key_Left))
                except Exception:
                    pass
                try:
                    sc_space_close = QShortcut(QKeySequence(Qt.Key_Space), dlg)
                    sc_space_close.setAutoRepeat(False)
                    sc_space_close.activated.connect(dlg.close)
                except Exception:
                    pass
    
            _wire_common_shortcuts(dialog)
    
            # Sync výběru ve stromu při přepínání souborů v dialogu
            if hasattr(dialog, 'current_file_changed'):
                dialog.current_file_changed.connect(self._on_viewer_current_file_changed)
            if hasattr(dialog, 'file_deleted'):
                dialog.file_deleted.connect(lambda _: self.refresh_file_tree())
            if hasattr(dialog, 'request_auto_fit'):
                dialog.request_auto_fit()
    
            dialog.exec_() if hasattr(dialog, 'exec_') else dialog.exec()
    
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nelze otevřít prohlížeč:\n{e}")
    
    def _unsorted_name_variants(self):
        # Varianty a klíčové podřetězce pro 'Neroztříděné'
        return [
            "Neroztříděné", "neroztříděné", "Neroztridene", "neroztridene",
            "Neroztříděné/", "neroztříděné/"
        ], ["neroztříděné", "neroztr"]
        
    def _norm_text(self, s: str) -> str:
        import unicodedata
        s = str(s or "")
        # sjednotit Unicode a snížit (casefold je robustnější než lower)
        s = unicodedata.normalize('NFC', s).casefold()
        # rozložit znaky a odfiltrovat diakritiku (Mn = combining mark)
        s = unicodedata.normalize('NFD', s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        return s
    
    def _tokenize_filter(self, text: str):
        import re
        raw_tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
        return [self._norm_text(t) for t in raw_tokens]
    
    def _find_unsorted_roots(self):
        """Najde root položky stromu, které odpovídají 'Neroztříděné' (včetně variant)."""
        exacts, substrs = self._unsorted_name_variants()
        roots = []
        for i in range(self.file_tree.topLevelItemCount()):
            it = self.file_tree.topLevelItem(i)
            name = (it.text(0) or "").strip()
            name_l = name.lower()
            is_target = any(name == v or name.strip() == v.strip() for v in exacts)
            if not is_target:
                if any(s in name_l for s in substrs):
                    is_target = True
            if is_target:
                roots.append(it)
        return roots
    
    def _item_matches_tokens(self, item, tokens):
        name_raw = (item.text(0) or "")
        name_norm = self._norm_text(name_raw)
        return all(tok in name_norm for tok in tokens)
    
    @Slot()
    def open_polygon_editor_shortcut(self):
        """
        Slot pro klávesovou zkratku CMD+P.
        Spustí editor polygonu pro aktuálně vybranou položku.
        """
        # Volá již existující funkci, která obsluhuje tlačítko "Upravit oblast"
        if hasattr(self, 'on_edit_polygon'):
            self.on_edit_polygon()

    @Slot()
    def select_all_in_unsorted_shortcut(self):
        """
        Slot pro klávesovou zkratku CMD+A.
        Vybere všechny soubory ve složce 'Neroztříděné'.
        """
        try:
            if not hasattr(self, 'file_tree'):
                return

            # Použije existující funkci pro nalezení kořenového uzlu 'Neroztříděné'
            unsorted_roots = self._find_unsorted_roots()
            if not unsorted_roots:
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("CMD+A: Složka 'Neroztříděné' nebyla nalezena.", "info")
                return

            # Obvykle je jen jeden kořen 'Neroztříděné'
            unsorted_root_item = unsorted_roots[0]
            
            # Zrušení předchozího výběru, aby se položky nekumulovaly
            self.file_tree.clearSelection()

            # Vybrání všech přímých potomků
            for i in range(unsorted_root_item.childCount()):
                child_item = unsorted_root_item.child(i)
                if not child_item.isHidden(): # Vybrat pouze viditelné položky
                    child_item.setSelected(True)
            
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"CMD+A: Vybráno {unsorted_root_item.childCount()} položek ve složce 'Neroztříděné'.", "success")

        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"Chyba při výběru všeho v 'Neroztříděné': {e}", "error")
  
    def _on_paste_shortcut(self):
        try:
            target_dir = self.default_maps_path
            item = self.file_tree.currentItem()
            if item is not None:
                p_str = item.data(0, Qt.UserRole)
                if p_str:
                    p = Path(p_str)
                    if p.exists():
                        target_dir = p if p.is_dir() else p.parent
    
            # NOVÉ: rozlišení typu schránky
            if getattr(self, 'clipboard_data', None) and 'paths' in self.clipboard_data:
                self.paste_to_selected_folder()
            else:
                self.paste_file_or_folder(str(target_dir))
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba vložení: {e}", "error")

    def _apply_unsorted_filter(self):
        """Aplikuje/odstraní filtr pouze v podstromu 'Neroztříděné'."""
        try:
            if not hasattr(self, 'file_tree') or not self.file_tree:
                return
            text = self.edit_unsorted_filter.text() if hasattr(self, 'edit_unsorted_filter') else ""
            tokens = self._tokenize_filter(text)
            roots = self._find_unsorted_roots()
            if not roots:
                return
    
            def apply_on_subtree(root_item):
                # Pokud filtr prázdný → vše viditelné v tomto podstromu
                if not tokens:
                    def unhide_all(it):
                        it.setHidden(False)
                        for j in range(it.childCount()):
                            unhide_all(it.child(j))
                    unhide_all(root_item)
                    return
    
                # Rekurzivně vrací True, pokud uzel nebo jeho potomci odpovídají
                def walk(it):
                    is_dir = (it.text(1) or "").startswith("📁")
                    if it.childCount() == 0:
                        match = self._item_matches_tokens(it, tokens)
                        it.setHidden(not match)
                        return match
                    # Složka: odpovídá-li sama, ponecháme ji; jinak zviditelníme jen pokud má shodné potomky
                    self_match = self._item_matches_tokens(it, tokens)
                    any_child = False
                    for j in range(it.childCount()):
                        if walk(it.child(j)):
                            any_child = True
                    visible = self_match or any_child
                    it.setHidden(not visible)
                    return visible
    
                # Aplikovat a pro přehlednost rozbalit root při aktivním filtru
                walk(root_item)
                if tokens:
                    root_item.setExpanded(True)
    
            for rt in roots:
                apply_on_subtree(rt)
    
            # Volitelně: jemný repaint
            try:
                self.file_tree.viewport().update()
            except Exception:
                pass
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba filtru: {e}", "warning")
                
    def _extract_last5_id_from_name(self, name: str) -> int | None:
        """
        Vrátí int(XXXXX) z posledních 5 číslic před příponou názvu souboru,
        např. '...+00027.png' -> 27; jinak None.
        """
        try:
            import re
            m = re.search(r'(\d{5})(?=\.[^.]+$)', name)
            return int(m.group(1)) if m else None
        except Exception:
            return None
    
    def _iter_children_recursive(self, item):
        """Generátor: projde rekurzivně všechny potomky dané položky stromu."""
        try:
            for i in range(item.childCount()):
                ch = item.child(i)
                yield ch
                yield from self._iter_children_recursive(ch)
        except Exception:
            return
    
    def analyze_unsorted_location_ids(self) -> dict:
        """
        Projde všechny kořeny 'Neroztříděné' v QTreeWidget a sesbírá čísla (posledních 5 číslic).
        Vrací { 'count': int, 'max': int|None, 'ids': set[int], 'missing': list[int] }.
        Interval pro chybějící = 1..max (pokud max existuje).
        """
        try:
            roots = self._find_unsorted_roots() if hasattr(self, '_find_unsorted_roots') else []
            ids = set()
            for rt in roots:
                # Projít všechny uzly v podstromu
                for it in self._iter_children_recursive(rt):
                    try:
                        # Sloupec 1 obsahuje typ; složky mají "📁 Složka"
                        typ = (it.text(1) or "")
                        if typ.startswith("📁"):
                            continue
                        name = (it.text(0) or "").strip()
                        if not name:
                            continue
                        # Volitelně: filtrovat jen mapové obrázky (ponecháno tolerantní)
                        # if not self.is_location_map_image(name):
                        #     continue
                        val = self._extract_last5_id_from_name(name)
                        if val is not None:
                            ids.add(val)
                    except Exception:
                        continue
    
            if not ids:
                return {'count': 0, 'max': None, 'ids': set(), 'missing': []}
    
            mx = max(ids)
            # Interval 1..mx
            exp = set(range(1, mx + 1))
            missing = sorted(exp - ids)
            return {'count': len(ids), 'max': mx, 'ids': ids, 'missing': missing}
        except Exception:
            return {'count': 0, 'max': None, 'ids': set(), 'missing': []}
        
    # 1) Bezpečné padování na 5 míst (nikdy nepadá na list/None)
    def _p5(self, x) -> str:
        try:
            return str(int(x)).zfill(5)
        except Exception:
            try:
                # toleruj jednoprvkový list/tuple [3] -> "00010"
                if isinstance(x, (list, tuple)) and len(x) == 1:
                    return str(int(x)).zfill(5)
            except Exception:
                pass
            # poslední možnost: vrátit čitelný string (bez pádu)
            return str(x)
    
    # 2) Robustní komprese – zploští, převede na int, setřídí a sloučí
    def _compress_ranges_safe(self, nums) -> list[tuple[int, int]]:
        if not nums:
            return []
        flat: list[int] = []
        for v in nums:
            if isinstance(v, (list, tuple)):
                for y in v:
                    try:
                        flat.append(int(y))
                    except Exception:
                        pass
            else:
                try:
                    flat.append(int(v))
                except Exception:
                    pass
        if not flat:
            return []
        flat = sorted(set(flat))
        out: list[tuple[int, int]] = []
        s = e = flat
        for x in flat[1:]:
            if x == e + 1:
                e = x
            else:
                out.append((s, e))
                s = e = x
        out.append((s, e))
        return out
    
    # 3) Kompaktní výpis chybějících – bez použití {:05d}, se zpětným fallbackem
    def _format_id_list_compact(self, missing) -> str:
        try:
            rngs = self._compress_ranges_safe(missing)
            parts = []
            for a, b in rngs:
                if a == b:
                    parts.append(self._p5(a))
                else:
                    parts.append(f"{self._p5(a)}–{self._p5(b)}")
            return ", ".join(parts)
        except Exception:
            # fallback: prostý výpis unikátních hodnot seřazených a napadovaných
            try:
                safe = sorted({int(x) for x in missing})
                return ", ".join(self._p5(x) for x in safe)
            except Exception:
                return ", ".join(str(x) for x in missing)
    
    # 4) Úprava update_unsorted_id_indicator – žádné {:05d}, vše přes _p5()
    def update_unsorted_id_indicator(self):
        """
        Získá stav čísel v 'Neroztříděné' a aktualizuje label nad stromem i status widget.
        Používá bezpečné padování (_p5) a kompaktní formát bez přímého {:05d}.
        Navíc při zapnutém automatickém ID průběžně doplňuje první volné číslo do pole.
        """
        try:
            state = self.analyze_unsorted_location_ids()
            cnt = state.get('count', 0)
            mx = state.get('max')
            missing = state.get('missing', [])
    
            def set_label(text: str, color: str):
                if hasattr(self, "unsorted_id_label") and self.unsorted_id_label:
                    self.unsorted_id_label.setText(text)
                    self.unsorted_id_label.setStyleSheet(
                        f"QLabel {{ color: {color}; font-weight: 600; }}"
                    )
    
            if cnt == 0 or mx is None:
                text = "🔢 Neroztříděné: Nalezeno 0 čísel (není co vyhodnotit)"
                try:
                    self.status_widget.set_status("info", text)
                except Exception:
                    pass
                set_label(text, "#666")
                last = getattr(self, "_last_unsorted_id_msg", None)
                if text != last and hasattr(self, "log_widget"):
                    self.log_widget.add_log(text, "info")
                self._last_unsorted_id_msg = text
                # Synchronizace automatického ID (při prázdném stavu = 00001)
                try:
                    if hasattr(self, "check_auto_id") and self.check_auto_id.isChecked():
                        if hasattr(self, "input_manual_id") and self.input_manual_id:
                            self.input_manual_id.setText("00001")
                            if hasattr(self, "label_id_mode"):
                                self.label_id_mode.setText("Automatické ID:")
                except Exception:
                    pass
                return
    
            mx_p = self._p5(mx) if hasattr(self, "_p5") else f"{int(mx):05d}"
    
            if not missing:
                text = f"🔢 Neroztříděné: max {mx_p} • bez mezer (1..{mx_p})"
                try:
                    self.status_widget.set_status("success", text)
                except Exception:
                    pass
                set_label(text, "#2e7d32")
                last = getattr(self, "_last_unsorted_id_msg", None)
                if text != last and hasattr(self, "log_widget"):
                    self.log_widget.add_log(text, "success")
                self._last_unsorted_id_msg = text
                # Synchronizace automatického ID (bez mezer -> použij max+1)
                try:
                    if hasattr(self, "check_auto_id") and self.check_auto_id.isChecked():
                        if hasattr(self, "input_manual_id") and self.input_manual_id:
                            nxt = (int(mx) + 1) if mx is not None else 1
                            self.input_manual_id.setText(self._p5(nxt) if hasattr(self, "_p5") else f"{int(nxt):05d}")
                            if hasattr(self, "label_id_mode"):
                                self.label_id_mode.setText("Automatické ID:")
                except Exception:
                    pass
                return
    
            # Kompaktní výpis chybějících (bez {:05d}, přes _format_id_list_compact s _compress_ranges_safe/_p5)
            try:
                compact = self._format_id_list_compact(missing)
            except Exception:
                # nouzový fallback: seřazené unikátní hodnoty s padováním
                try:
                    uniq = sorted({int(x) for x in (missing or [])})
                    compact = ", ".join(self._p5(x) if hasattr(self, "_p5") else f"{int(x):05d}" for x in uniq)
                except Exception:
                    compact = ", ".join(str(x) for x in (missing or []))
    
            text = f"🔢 Neroztříděné: max {mx_p} • chybí {compact} (celkem {len(missing)})"
            try:
                self.status_widget.set_status("warning", text)
            except Exception:
                pass
            set_label(text, "#c62828")
            last = getattr(self, "_last_unsorted_id_msg", None)
            if text != last and hasattr(self, "log_widget"):
                self.log_widget.add_log(text, "warning")
            self._last_unsorted_id_msg = text
    
            # Synchronizace automatického ID (při mezerách -> první volné, jinak max+1)
            try:
                if hasattr(self, "check_auto_id") and self.check_auto_id.isChecked():
                    if hasattr(self, "input_manual_id") and self.input_manual_id:
                        if missing:
                            first_free = min(int(x) for x in missing if isinstance(x, (int, str)) and str(x).isdigit())
                            self.input_manual_id.setText(self._p5(first_free) if hasattr(self, "_p5") else f"{int(first_free):05d}")
                        else:
                            nxt = (int(mx) + 1) if mx is not None else 1
                            self.input_manual_id.setText(self._p5(nxt) if hasattr(self, "_p5") else f"{int(nxt):05d}")
                        if hasattr(self, "label_id_mode"):
                            self.label_id_mode.setText("Automatické ID:")
            except Exception:
                pass
    
        except Exception as e:
            msg = f"❌ Chyba kontroly čísel v 'Neroztříděné': {e}"
            try:
                self.status_widget.set_status("error", msg)
            except Exception:
                pass
            if hasattr(self, "unsorted_id_label"):
                self.unsorted_id_label.setText(msg)
                self.unsorted_id_label.setStyleSheet("QLabel { color: #c62828; font-weight: 600; }")
            if hasattr(self, "log_widget"):
                self.log_widget.add_log(msg, "error")

    def rename_selected_item(self):
        """Přejmenuje vybraný soubor (1 položka) – vyvolá jednotný dialog se sjednocenou velikostí."""
        try:
            item = self.file_tree.currentItem()
            if item is None:
                sel = self.file_tree.selectedItems()
                if not sel or len(sel) != 1:
                    return
                item = sel
    
            p_str = item.data(0, Qt.UserRole)
            if not p_str:
                return
            p = Path(p_str)
            if not p.exists() or not p.is_file():
                return  # jen soubory
    
            stem = p.stem
            suffix = p.suffix  # včetně tečky
    
            new_stem = self._show_rename_dialog(p.parent, stem, suffix)
            if not new_stem:
                return
    
            new_path = p.with_name(new_stem + suffix)
            if new_path.exists():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Přejmenování", "Cílový název již existuje.")
                return
    
            p.rename(new_path)
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"✏️ Přejmenováno: {p.name} → {new_path.name}", "info")
    
            # Refresh + znovu vybrat novou položku
            self.refresh_file_tree()
            if hasattr(self, '_select_path_in_tree'):
                self._select_path_in_tree(str(new_path))
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba přejmenování: {e}", "error")

    def cut_selected_items(self):
        """Vyjme (Cut) vybrané soubory/složky do interní schránky; následné Vložit je přesune."""
        try:
            items = self.file_tree.selectedItems()
            if not items:
                return
            paths = []
            for it in items:
                p_str = it.data(0, Qt.UserRole)
                if not p_str:
                    continue
                p = Path(p_str)
                if p.exists():
                    paths.append(str(p))
            if not paths:
                return
    
            # Interní schránka
            self.clipboard_data = {'mode': 'cut', 'paths': paths}
    
            # Systémová schránka (volitelné – textový seznam cest)
            try:
                from PySide6.QtWidgets import QApplication
                cb = QApplication.clipboard()
                cb.setText("\n".join(paths))
            except Exception:
                pass
    
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"✂️ Vyjmuto: {len(paths)} položek", "info")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba vyjmutí: {e}", "error")


    def _get_selected_png_path(self):
        """
        Pomocná funkce: vrátí cestu k vybranému PNG souboru ze stromu (preferuje currentItem).
        """
        try:
            item = self.file_tree.currentItem()
            if item is None:
                sel = self.file_tree.selectedItems()
                if sel:
                    item = sel
            if item is None:
                return None
            p_str = item.data(0, Qt.UserRole)
            if not p_str:
                return None
            p = Path(p_str)
            if p.exists() and p.is_file() and p.suffix.lower() == ".png":
                return str(p)
            return None
        except Exception:
            return None
    
    def on_edit_polygon(self):
        """
        Spustí editor polygonu nad aktuálně vybraným PNG ve stromu.
        Po uložení obnoví strom a automaticky přegeneruje daný obrázek.
        """
        png_path = self._get_selected_png_path()
        if not png_path:
            QMessageBox.information(self, "Upravit oblast", "Vyberte prosím PNG soubor ve stromu.")
            return
        try:
            saved = open_polygon_editor_for_file(png_path, parent=self)
            if saved:
                # Obnovit strom (kvůli času změny apod.)
                if hasattr(self, "refresh_file_tree"):
                    self.refresh_file_tree()
                # Log
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"🔺 Uložena polygonová vrstva do: {Path(png_path).name}", "success")
                # Nové: automatické přegenerování souboru po uložení polygonu
                try:
                    self.regenerate_file_in_place(png_path)
                except Exception as e:
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"⚠️ Auto‑přegenerování selhalo: {e}", "warning")
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Editor oblasti selhal:\n{e}")

    def on_edit_polygon_for_path(self, file_path: str):
        """
        Spustí editor polygonu přímo pro danou cestu (používá kontextové menu).
        Po uložení automaticky přegeneruje obrázek na místě.
        """
        p = Path(file_path)
        if not p.exists() or not p.is_file() or p.suffix.lower() != ".png":
            QMessageBox.information(self, "Upravit oblast", "Položka není platný PNG soubor.")
            return
        try:
            saved = open_polygon_editor_for_file(str(p), parent=self)
            if saved:
                if hasattr(self, "refresh_file_tree"):
                    self.refresh_file_tree()
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"🔺 Uložena polygonová vrstva do: {p.name}", "success")
                # Nové: automatické přegenerování souboru po uložení polygonu
                try:
                    self.regenerate_file_in_place(str(p))
                except Exception as e:
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"⚠️ Auto‑přegenerování selhalo: {e}", "warning")
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Editor oblasti selhal:\n{e}")

    def _init_gps_preview_first_show(self):
        """První otevření GPS záložky: zkus načíst cache náhledu, nestahuj automaticky."""
        try:
            self._map_preview_initialized = True
            pix, meta_tuple = self.load_preview_cache()
            if pix is not None and meta_tuple is not None:
                # Zobrazit cache a nastavit last tuple, žádné stahování
                self._suppress_map_resize = True
                self.map_label.setPixmap(pix)
                self.map_label.setMinimumSize(pix.size())
                from PySide6.QtCore import QTimer
                QTimer.singleShot(80, lambda: setattr(self, "_suppress_map_resize", False))
    
                # Handshake + zdroj: cache
                self._last_map_req = meta_tuple
                self._preview_source = "cache"
    
                # Okamžitě nastavit správnou indikaci (podle skutečné shody s GUI)
                try:
                    cur = self._get_normalized_gps_preview_tuple()
                    match = (cur is not None and cur == meta_tuple)
                    if hasattr(self, "_set_consistency_ui"):
                        self._set_consistency_ui("cache", match)
                    else:
                        # Fallback: jen text (bez overlay, pokud helper nebyl přidán)
                        if hasattr(self, "gps_warning_label"):
                            if match:
                                self.gps_warning_label.setStyleSheet("QLabel { color: #2e7d32; font-weight: bold; font-size: 13px; }")
                                self.gps_warning_label.setText("Načten obrázek z cache a odpovídá hodnotám v GUI")
                            else:
                                self.gps_warning_label.setStyleSheet("QLabel { color: #c62828; font-weight: bold; font-size: 13px; }")
                                self.gps_warning_label.setText("Načten obrázek z cache, ale neodpovídá hodnotám v GUI")
                except Exception:
                    pass
    
                # Stavový popisek v sekci náhledu
                if hasattr(self, "map_status_label"):
                    self.map_status_label.setText("🖼️ Zobrazen uložený náhled – pro aktualizaci použijte ↻")
                return
    
            # Cache není → ponech informační text; refresh spustí uživatel
            self.map_label.setText("🗺️ Pro zobrazení/aktualizaci náhledu stiskněte ↻")
            if hasattr(self, "map_status_label"):
                self.map_status_label.setText("ℹ️ Náhled zatím nebyl vykreslen – načte se po stisku ↻")
    
        except Exception:
            # Fallback: i při chybě cache nespouštět stahování; uživatel použije ↻
            self.map_label.setText("🗺️ Pro zobrazení/aktualizaci náhledu stiskněte ↻")

    def on_tree_selection_changed(self, selected, deselected):
        """UPRAVENÁ FUNKCE: Automatické logování + zvýraznění polygonů"""
        try:
            items = self.file_tree.selectedItems()
            total = len(items)
            files_count = 0
            folders_count = 0
            
            for it in items:
                p_str = it.data(0, Qt.UserRole)
                if not p_str:
                    continue
                p = Path(p_str)
                if p.exists():
                    if p.is_dir():
                        folders_count += 1
                    else:
                        files_count += 1
    
            # Potlačení duplicitních záznamů do logu
            if not hasattr(self, '_last_selection_log'):
                self._last_selection_log = {'total': None, 'files': None, 'folders': None}
    
            prev = self._last_selection_log
            if prev['total'] != total or prev['files'] != files_count or prev['folders'] != folders_count:
                self._last_selection_log = {'total': total, 'files': files_count, 'folders': folders_count}
                
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(
                        f"✅ Výběr: {total} položek ({files_count} souborů, {folders_count} složek)",
                        "info"
                    )
    
            # NOVÉ: Zvýraznění podle polygonů
            self.update_polygon_highlights()
            
            # Aktualizace textového indikátoru (pokud chcete zachovat)
            if hasattr(self, 'update_polygon_indicator'):
                self.update_polygon_indicator()
            
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba při sledování výběru: {e}", "warning")

    def collapse_except_unsorted_fixed(self):
        """FLEXIBILNÍ HLEDÁNÍ: Různé varianty názvu složky"""
        try:
            collapsed_count = 0
            target_found = False
            found_name = ""
            
            # Možné varianty názvu
            target_variants = [
                "Neroztříděné",
                "neroztříděné", 
                "Neroztridene",
                "neroztridene",
                "Neroztříděné/",
                "neroztříděné/",
            ]
            
            def process_item(item=None):
                nonlocal collapsed_count, target_found, found_name
                
                if item is None:
                    for i in range(self.file_tree.topLevelItemCount()):
                        process_item(self.file_tree.topLevelItem(i))
                else:
                    item_name = item.text(0)
                    item_type = item.text(1)
                    
                    # Flexibilní kontrola názvu
                    is_target = False
                    for variant in target_variants:
                        if item_name == variant or item_name.strip() == variant.strip():
                            is_target = True
                            found_name = item_name
                            break
                    
                    # Další kontrola - obsahuje klíčová slova
                    if not is_target:
                        name_lower = item_name.lower().strip()
                        if "neroztříděné" in name_lower or "neroztr" in name_lower:
                            is_target = True
                            found_name = item_name
                    
                    if is_target:
                        # Cílová složka nalezena
                        item.setExpanded(True)
                        target_found = True
                        self.log_widget.add_log(f"⭐ NALEZENA CÍLOVÁ SLOŽKA: '{item_name}' (varianta: '{found_name}')", "success")
                    elif item_type.startswith("📁") and item.isExpanded():
                        # Ostatní složky sbalit
                        item.setExpanded(False)
                        collapsed_count += 1
                        self.log_widget.add_log(f"📕 Sbalena: '{item_name}'", "debug")
                    
                    # Rekurze na potomky
                    for i in range(item.childCount()):
                        process_item(item.child(i))
            
            self.log_widget.add_log("🔍 === FLEXIBILNÍ HLEDÁNÍ ===", "info")
            process_item()
            
            if target_found:
                self.log_widget.add_log(f"✅ ÚSPĚCH: Sbaleno {collapsed_count} složek, '{found_name}' ponechána rozbalená", "success")
            else:
                self.log_widget.add_log(f"⚠️ VAROVÁNÍ: Sbaleno {collapsed_count} složek, žádná varianta 'Neroztříděné' nebyla nalezena", "warning")
                
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba: {e}", "error")
    
    def on_tree_section_resized(self, logical_index, old_size, new_size):
        """NOVÁ FUNKCE: Reakce na změnu velikosti sloupců"""
        if logical_index == 0:  # Sloupec "Název"
            # Logování změny velikosti pro debug
            total_width = sum(self.file_tree.columnWidth(i) for i in range(4))
            name_percentage = (new_size / total_width) * 100 if total_width > 0 else 0
                
    def adjust_tree_columns(self):
        """Fixní šířky pro Typ/Velikost/Změněno dle textu, Název jediný Stretch (vyplní zbytek)."""
        try:
            if not hasattr(self, 'file_tree') or not self.file_tree:
                return
            view   = self.file_tree
            header = view.header()
    
            # Hlavička a elipsy
            try:
                header.setMinimumSectionSize(18)
                header.setSectionsMovable(False)
                header.setStretchLastSection(False)  # poslední sloupec nebude roztahován
                view.setTextElideMode(Qt.ElideRight)
            except Exception:
                pass
    
            # Pomocník na šířku textu (včetně rozumné rezervy za padding)
            fm = view.fontMetrics()
            base_padding = 18  # odhad levý+pravý padding u sekce
            def text_w(txt: str) -> int:
                try:
                    return int(fm.horizontalAdvance(txt)) + base_padding
                except Exception:
                    return len(txt) * 8 + base_padding  # fallback
    
            # 1) Typ = šířka pro "🖼️ Obrázek" + 5 % (zahrnuje i jiné typy, protože "Obrázek" je nejširší)
            type_candidates = [
                "🖼️ Obrázek", "📁 Složka", "📷 HEIC", "📄 PDF", "📝 Text", "📦 Archiv", "📄 Soubor"
            ]
            type_base = max(text_w(s) for s in type_candidates)
            type_w    = int(round(type_base * 1.05))  # +5 %
    
            # 2) Velikost = 15 znaků + 5 % (počítáno na nejširší číslice '8')
            size_sample = "8" * 15
            size_w      = int(round(text_w(size_sample) * 1.05))  # +5 %
    
            # 3) Změněno = maximálně 15 znaků (bez přídavného procenta)
            date_sample = "8" * 15
            date_w      = text_w(date_sample)
    
            # Aplikace fixních šířek (Typ=1, Velikost=2, Změněno=3)
            for col, width in ((1, type_w), (2, size_w), (3, date_w)):
                try:
                    header.setSectionResizeMode(col, QHeaderView.Fixed)
                except AttributeError:
                    header.setSectionResizeMode(col, QHeaderView.Fixed)
                try:
                    header.resizeSection(col, width)
                except Exception:
                    pass
    
            # 4) Název = jediný pružný (vyplní zbytek šířky tabulky)
            try:
                header.setSectionResizeMode(0, QHeaderView.Stretch)
            except AttributeError:
                header.setSectionResizeMode(0, QHeaderView.Stretch)
            # Minimální čitelnost názvu
            min_name = 180
            if view.columnWidth(0) < min_name:
                view.setColumnWidth(0, min_name)
    
            # Bezpečnost: pokud by fixní sloupce + minimum pro Název překročily viewport, zmenši fixní sloupce proporcionálně
            vp_w = max(0, view.viewport().width())
            fixed_sum = type_w + size_w + date_w
            if vp_w and fixed_sum + min_name + 4 > vp_w:
                over = fixed_sum + min_name + 4 - vp_w
                weights = {1: type_w, 2: size_w, 3: date_w}
                mins    = {1: 60,     2: 80,     3: 120}  # tvrdé minima pro nouzové smrštění
                for col in (1, 2, 3):
                    share = over * (weights[col] / float(fixed_sum))
                    new_w = max(mins[col], int(round(weights[col] - share)))
                    try:
                        header.resizeSection(col, new_w)
                    except Exception:
                        pass
        except Exception as e:
            if hasattr(self, 'log_widget') and self.log_widget:
                self.log_widget.add_log(f"⚠️ Chyba při přizpůsobení sloupců: {e}", "warning")

    def adjust_tree_columns_delayed(self):
        """Zpožděný přepočet – zmenší sloupce proti skutečnému obsahu a nechá Název vyplnit zbytek."""
        try:
            if hasattr(self, 'file_tree') and self.file_tree and self.file_tree.isVisible():
                self.adjust_tree_columns()
        except Exception:
            pass

    def resizeEvent(self, event):
        """Reakce na změnu velikosti okna – přepočet sloupců stromu a update mapového náhledu (debounce)."""
        super().resizeEvent(event)
        # Už máte sloupcovou logiku; ponechána
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self.adjust_tree_columns_delayed)
        except Exception:
            if hasattr(self, 'log_widget') and self.log_widget is not None:
                self.log_widget.add_log("⚠️ Chyba při resize (tree columns)", "warning")
    
        # Naplánovat pouze, když je GPS tab aktivní a náhled už byl jednou inicializován
        try:
            if (hasattr(self, "_map_resize_timer")
                and getattr(self, "_map_preview_initialized", False)
                and hasattr(self, "tabs") and hasattr(self, "_gps_tab_index")
                and self.tabs.currentIndex() == self._gps_tab_index):
                self._map_resize_timer.start(150)
        except Exception:
            pass

    def refresh_file_tree(self):
        """UPRAVENÁ FUNKCE: stabilní pořadí během session + obnova rozbalení i po restartu (uložený stav), bez hromadného expand/collapse."""
        from PySide6.QtWidgets import QTreeWidgetItem
        from PySide6.QtCore import QTimer, Qt
    
        try:
            # === Stav před rebuiltem ===
            had_prior_tree = self.file_tree.topLevelItemCount() > 0
    
            # 1) Rozbalení – pokud už strom existuje, ulož aktuální; jinak vezmi uložený z konfigurace (po restartu)
            expanded_state = set()
            state_source = "žádný"
            if had_prior_tree:
                try:
                    expanded_state = self.save_tree_expansion_state()
                    state_source = "aktuální stav stromu"
                except Exception:
                    expanded_state = set()
            elif hasattr(self, 'saved_tree_expansion_state') and self.saved_tree_expansion_state:
                expanded_state = self.saved_tree_expansion_state
                state_source = "uložený stav z konfigurace"
    
            # 2) Ulož aktuální pořadí (top-level i děti) – pouze když strom existoval (pro stabilitu během session)
            order_top = []
            order_children = {}  # parent_path -> [child_paths]
    
            def _item_path(it):
                try:
                    return it.data(0, Qt.UserRole)
                except Exception:
                    return None
    
            if had_prior_tree:
                try:
                    for i in range(self.file_tree.topLevelItemCount()):
                        it = self.file_tree.topLevelItem(i)
                        order_top.append(_item_path(it))
                        stack = [it]
                        while stack:
                            parent = stack.pop()
                            pkey = _item_path(parent)
                            child_paths = []
                            for j in range(parent.childCount()):
                                ch = parent.child(j)
                                child_paths.append(_item_path(ch))
                                stack.append(ch)
                            order_children[pkey] = child_paths
                except Exception:
                    pass
    
            # Log (volitelný)
            self.log_widget.add_log(f"🔄 Refresh stromu – zdroj rozbalení: {state_source} ({len(expanded_state)} položek)", "info")
    
            # === Rebuild bez řazení ===
            try:
                prev_sort_enabled = self.file_tree.isSortingEnabled()
                self.file_tree.setSortingEnabled(False)
            except Exception:
                prev_sort_enabled = False
    
            self.file_tree.clear()
    
            if not self.default_maps_path.exists():
                try:
                    self.default_maps_path.mkdir(parents=True, exist_ok=True)
                    self.log_widget.add_log(f"📁 Vytvořena složka: {self.default_maps_path}", "info")
                except Exception as e:
                    error_item = QTreeWidgetItem(["❌ Složka neexistuje a nelze ji vytvořit", "Chyba", "", ""])
                    self.file_tree.addTopLevelItem(error_item)
                    self.log_widget.add_log(f"❌ Chyba při vytváření složky: {e}", "error")
                    try:
                        self.file_tree.setSortingEnabled(prev_sort_enabled)
                    except Exception:
                        pass
                    return
    
            # Naplnění stromu (rekurzivně) – BEZ změny
            self.load_directory_tree(self.default_maps_path, None, max_depth=10)
    
            # === Obnova původního pořadí (jen během session; po restartu neřešíme, protože nemáme zdroj pořadí)
            if had_prior_tree and (order_top or order_children):
                try:
                    # mapuj aktuální strom: path -> item
                    path_to_item = {}
                    for i in range(self.file_tree.topLevelItemCount()):
                        it = self.file_tree.topLevelItem(i)
                        path_to_item[_item_path(it)] = it
                        stack = [it]
                        while stack:
                            cur = stack.pop()
                            for j in range(cur.childCount()):
                                ch = cur.child(j)
                                path_to_item[_item_path(ch)] = ch
                                stack.append(ch)
    
                    # Top-level reordering
                    if order_top:
                        current = [self.file_tree.topLevelItem(i) for i in range(self.file_tree.topLevelItemCount())]
                        new_order = []
                        for p in order_top:
                            it = path_to_item.get(p)
                            if it is not None and it in current:
                                new_order.append(it)
                        for it in current:
                            if it not in new_order:
                                new_order.append(it)
                        if new_order != current:
                            for i in reversed(range(self.file_tree.topLevelItemCount())):
                                self.file_tree.takeTopLevelItem(i)
                            for it in new_order:
                                self.file_tree.addTopLevelItem(it)
    
                    # Děti – reordering pro každého rodiče
                    for parent_path, desired_children in order_children.items():
                        parent_it = path_to_item.get(parent_path)
                        if parent_it is None or not isinstance(desired_children, list):
                            continue
                        current_children = [parent_it.child(i) for i in range(parent_it.childCount())]
                        map_child = {_item_path(it): it for it in current_children}
                        reordered = []
                        for p in desired_children:
                            it = map_child.get(p)
                            if it is not None:
                                reordered.append(it)
                        for it in current_children:
                            if it not in reordered:
                                reordered.append(it)
                        if reordered != current_children:
                            for i in reversed(range(parent_it.childCount())):
                                parent_it.takeChild(i)
                            for it in reordered:
                                parent_it.addChild(it)
                except Exception as _e:
                    self.log_widget.add_log(f"⚠ Obnova pořadí selhala: {_e}", "warn")
    
            # === Obnova rozbalení: použij uložený stav (z aktuální session nebo z konfigurace), jinak NIC nedělej
            if expanded_state:
                try:
                    self.restore_tree_expansion_state(expanded_state)
                    self.log_widget.add_log(f"✅ Obnoveno rozbalení ({len(expanded_state)} položek)", "info")
                except Exception:
                    pass
    
            # Sloupce, počty, indikátory (beze změn)
            self.adjust_tree_columns()
    
            total_items = self.count_tree_items()
            folders_count = self.count_folders()
            files_count = total_items - folders_count
            self.log_widget.add_log(f"📁 Načteno {total_items} položek ({folders_count} složek, {files_count} souborů)", "info")
    
            try:
                self.update_unsorted_id_indicator()
            except Exception:
                pass
    
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při načítání souborů: {e}", "error")
            try:
                error_item = QTreeWidgetItem([f"❌ Chyba: {str(e)}", "Chyba", "", ""])
                self.file_tree.addTopLevelItem(error_item)
            except Exception:
                pass
        finally:
            # Necháme rozbalení tak, jak je – jen dojedeme standardní housekeeping.
            try:
                if hasattr(self, "edit_unsorted_filter") and self.edit_unsorted_filter.text().strip():
                    self._apply_unsorted_filter()
            except Exception:
                pass
    
            QTimer.singleShot(0, self._update_anonymization_column)
    
            try:
                if hasattr(self, 'file_tree') and self.file_tree.selectionModel():
                    try:
                        self.file_tree.selectionModel().currentChanged.disconnect(self.on_tree_current_changed)
                    except Exception:
                        pass
                    self.file_tree.selectionModel().currentChanged.connect(self.on_tree_current_changed)
                self.update_polygon_highlights()
            except Exception:
                pass
    
            try:
                self.file_tree.setSortingEnabled(prev_sort_enabled)
            except Exception:
                pass

    def save_tree_expansion_state(self):
        """Uloží absolutní cesty rozbalených položek (bez položkových debug logů)."""
        expanded_items = set()
        stack = []
    
        # Top-level
        for i in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(i)
            stack.append((item, [item.text(0)]))
    
        # DFS
        while stack:
            item, path_parts = stack.pop()
            if item.isExpanded():
                item_path = "/".join(path_parts)
                expanded_items.add(item_path)
            for i in range(item.childCount()):
                child = item.child(i)
                stack.append((child, path_parts + [child.text(0)]))
    
        if hasattr(self, 'log_widget'):
            self.log_widget.add_log(f"💾 Celkem uloženo {len(expanded_items)} rozbalených položek", "info")
        return expanded_items

    def restore_tree_expansion_state(self, expanded_items):
        """Obnovení stavu rozbalení stromové struktury podle absolutních cest (bez položkových logů)."""
        if not expanded_items:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("📂 Žádné rozbalené položky k obnovení", "info")
            return
    
        restored_count = 0
    
        def get_item_path(item):
            path_parts = []
            current_item = item
            while current_item is not None:
                path_parts.append(current_item.text(0))
                current_item = current_item.parent()
            path_parts.reverse()
            return "/".join(path_parts)
    
        def restore_expanded_items(item):
            nonlocal restored_count
            if item is None:
                # Top-level
                for i in range(self.file_tree.topLevelItemCount()):
                    top_item = self.file_tree.topLevelItem(i)
                    item_path = get_item_path(top_item)
                    should_expand = item_path in expanded_items
                    top_item.setExpanded(should_expand)
                    if should_expand:
                        restored_count += 1
                    restore_expanded_items(top_item)
            else:
                # Children
                for i in range(item.childCount()):
                    child = item.child(i)
                    item_path = get_item_path(child)
                    should_expand = item_path in expanded_items
                    child.setExpanded(should_expand)
                    if should_expand:
                        restored_count += 1
                    restore_expanded_items(child)
    
        # Start s čistým stavem a následně rozbal jen ty, které byly v sadě
        self.file_tree.collapseAll()
        restore_expanded_items(None)
    
        if hasattr(self, 'log_widget'):
            self.log_widget.add_log(f"🔄 Obnoveno {restored_count} z {len(expanded_items)} rozbalených položek", "info")

    def count_folders(self):
        """NOVÁ FUNKCE: Počítání složek ve stromu"""
        count = 0
        
        def count_folders_recursive(item):
            nonlocal count
            # Kontrola, zda je to složka podle typu
            if item.text(1).startswith("📁"):
                count += 1
            for i in range(item.childCount()):
                count_folders_recursive(item.child(i))
        
        for i in range(self.file_tree.topLevelItemCount()):
            count_folders_recursive(self.file_tree.topLevelItem(i))
        
        return count

    def expand_all_items(self):
        """UPRAVENÁ FUNKCE: Rozbalení všech položek s počítadlem"""
        try:
            expanded_count = 0
            
            def expand_recursive(item):
                nonlocal expanded_count
                if item is None:
                    # Rozbalení top-level items
                    for i in range(self.file_tree.topLevelItemCount()):
                        top_item = self.file_tree.topLevelItem(i)
                        expand_recursive(top_item)
                else:
                    if item.text(1).startswith("📁") and not item.isExpanded():
                        item.setExpanded(True)
                        expanded_count += 1
                    
                    # Rekurzivní rozbalení potomků
                    for i in range(item.childCount()):
                        child = item.child(i)
                        expand_recursive(child)
            
            expand_recursive(None)
            self.log_widget.add_log(f"📖 Rozbaleno {expanded_count} složek", "success")
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při rozbalování: {e}", "error")
    
    def collapse_all_items(self):
        """UPRAVENÁ FUNKCE: Sbalení všech položek s počítadlem"""
        try:
            collapsed_count = 0
            
            def collapse_recursive(item):
                nonlocal collapsed_count
                if item is None:
                    # Sbalení top-level items
                    for i in range(self.file_tree.topLevelItemCount()):
                        top_item = self.file_tree.topLevelItem(i)
                        collapse_recursive(top_item)
                else:
                    if item.text(1).startswith("📁") and item.isExpanded():
                        item.setExpanded(False)
                        collapsed_count += 1
                    
                    # Rekurzivní sbalení potomků
                    for i in range(item.childCount()):
                        child = item.child(i)
                        collapse_recursive(child)
            
            collapse_recursive(None)
            self.log_widget.add_log(f"📕 Sbaleno {collapsed_count} složek", "success")
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při sbalování: {e}", "error")
            
    # Soubor: main_window.py
    # Třída: MainWindow
    # FUNKCE: load_directory_tree
    # ÚPRAVA: při vytváření každé PNG položky rovnou nastaví i sloupec 5 „Polygon“ (AOI_POLYGON). Ostatní logika nezměněna.
    
    def load_directory_tree(self, directory_path, parent_item, current_depth=0, max_depth=10):
        """OPTIMALIZOVANÁ FUNKCE: Rychlé načítání adresářové struktury se skrytím systémových/ skrytých souborů"""
        if current_depth > max_depth:
            if parent_item:
                placeholder = QTreeWidgetItem(["⚠️ Příliš hluboko vnořené složky...", "Limit", "", ""])
                parent_item.addChild(placeholder)
            return
    
        try:
            batch_items = []
    
            for item_path in directory_path.iterdir():
                try:
                    name = item_path.name
    
                    if name.startswith(".") or name.lower() in {"thumbs.db", "desktop.ini"}:
                        continue
                    if any(part.startswith(".") for part in item_path.parts):
                        continue
    
                    if item_path.is_file() and item_path.suffix.lower() in {".tmp", ".log"}:
                        continue
    
                    is_dir = item_path.is_dir()
                    stat_info = item_path.stat()
    
                    if is_dir:
                        size_text = "---"
                        type_text = "📁 Složka"
                    else:
                        size = stat_info.st_size
                        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                            if size < 1024.0:
                                size_text = f"{size:.0f} {unit}"
                                break
                            size /= 1024.0
                        suffix = item_path.suffix.lower()
                        type_map = {
                            '.png': "🖼️ Obrázek", '.jpg': "🖼️ Obrázek", '.jpeg': "🖼️ Obrázek",
                            '.heic': "🖼️ HEIC", '.tif': "🖼️ TIF", '.tiff': "🖼️ TIF",
                            '.pdf': "📄 PDF", '.txt': "📝 Text",
                            '.zip': "📦 Archiv", '.rar': "📦 Archiv"
                        }
                        type_text = type_map.get(suffix, "📄 Soubor")
    
                    import datetime
                    date_text = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime("%d.%m.%Y %H:%M")
    
                    batch_items.append({
                        'path': item_path,
                        'name': name,
                        'is_dir': is_dir,
                        'type': type_text,
                        'size': size_text,
                        'date': date_text,
                        'stat': stat_info
                    })
    
                except Exception:
                    continue
    
            for item_info in batch_items:
                tree_item = QTreeWidgetItem([
                    item_info['name'],
                    item_info['type'],
                    item_info['size'],
                    item_info['date']
                ])
                tree_item.setData(0, Qt.UserRole, str(item_info['path']))
    
                # sloupce 4 a 5 pro PNG: Anonymizace + Polygon
                try:
                    if (not item_info['is_dir']) and str(item_info['path']).lower().endswith(".png"):
                        is_anon = False
                        has_poly = False
                        try:
                            from PIL import Image
                            with Image.open(str(item_info['path'])) as img:
                                meta = {}
                                try:
                                    if hasattr(img, "text") and img.text:
                                        meta = dict(img.text)
                                except Exception:
                                    meta = {}
    
                                def _n(s): return str(s).strip().lower()
    
                                # anonymizace
                                for k, v in meta.items():
                                    if _n(k) in ("anonymizovaná lokace", "anonymizovana lokace"):
                                        if _n(v) in ("ano", "yes", "true", "1"):
                                            is_anon = True
                                        break
    
                                # polygon
                                if "AOI_POLYGON" in meta and str(meta["AOI_POLYGON"]).strip():
                                    has_poly = True
                        except Exception:
                            is_anon = False
                            has_poly = False
    
                        try:
                            from PySide6.QtWidgets import QStyle, QApplication
                            style = self.style() if hasattr(self, "style") else QApplication.style()
                            icon_yes = style.standardIcon(QStyle.SP_DialogApplyButton)
                            icon_no = style.standardIcon(QStyle.SP_DialogCancelButton)
    
                            # index 4: Anonymizace
                            tree_item.setIcon(4, icon_yes if is_anon else icon_no)
                            tree_item.setText(4, "Ano" if is_anon else "Ne")
                            tree_item.setToolTip(4, f"Anonymizovaná lokace: {'Ano' if is_anon else 'Ne'}")
    
                            # index 5: Polygon
                            tree_item.setIcon(5, icon_yes if has_poly else icon_no)
                            tree_item.setText(5, "Ano" if has_poly else "Ne")
                            tree_item.setToolTip(5, f"Polygon v metadatech (AOI_POLYGON): {'Ano' if has_poly else 'Ne'}")
                        except Exception:
                            pass
                except Exception:
                    pass
    
                if parent_item is None:
                    self.file_tree.addTopLevelItem(tree_item)
                else:
                    parent_item.addChild(tree_item)
    
                if item_info['is_dir']:
                    try:
                        if item_info['path'].exists():
                            self.load_directory_tree(item_info['path'], tree_item, current_depth + 1, max_depth)
                    except (PermissionError, OSError):
                        placeholder = QTreeWidgetItem(["🔒 Přístup odepřen", "Chyba", "", ""])
                        tree_item.addChild(placeholder)
    
        except Exception as e:
            if parent_item:
                error_item = QTreeWidgetItem([f"❌ Chyba načítání", "Chyba", "", ""])
                parent_item.addChild(error_item)

    def format_file_size(self, size_bytes):
        """OPTIMALIZOVANÁ FUNKCE: Rychlejší formátování velikosti souboru"""
        if size_bytes == 0:
            return "0 B"
        
        # OPTIMALIZACE: Předpočítané hodnoty a přímý výpočet
        size_names = ("B", "KB", "MB", "GB")  # Tuple místo listu
        i = min(3, int(math.log(size_bytes, 1024)))  # Omezení na max GB
        size = size_bytes / (1024 ** i)
        
        # OPTIMALIZACE: Použití f-string s podmíněným formátováním
        return f"{size:.1f} {size_names[i]}" if size >= 10 else f"{size:.2f} {size_names[i]}"

    def count_tree_items(self):
        """OPTIMALIZOVANÁ FUNKCE: Rychlejší počítání položek ve stromu"""
        # OPTIMALIZACE: Použití iterativního přístupu místo rekurze
        count = 0
        stack = []
        
        # Inicializace stacku s top-level items
        for i in range(self.file_tree.topLevelItemCount()):
            stack.append(self.file_tree.topLevelItem(i))
        
        # OPTIMALIZACE: Iterativní procházení místo rekurze
        while stack:
            item = stack.pop()
            count += 1
            
            # Přidání potomků do stacku
            for i in range(item.childCount()):
                stack.append(item.child(i))
        
        return count
    
    def recalculate_unsorted_areas(self) -> None:
        """
        Projde všechny PNG soubory ve složce 'Neroztříděné' a přepočítá jim
        plochu AOI_AREA_M2 na základě existujícího AOI_POLYGON v metadatech.
        Zpracovává pouze mapy s polygonem.
        """
        from PySide6.QtWidgets import QMessageBox, QProgressDialog
        from PySide6.QtCore import Qt
        from pathlib import Path
        
        # Použij self.default_maps_path a přidej Neroztříděné
        try:
            base_path = Path(self.default_maps_path)
            unsorted_folder = base_path / "Neroztříděné"
            
            if not unsorted_folder.exists() or not unsorted_folder.is_dir():
                QMessageBox.information(
                    self,
                    "Informace",
                    f"Složka 'Neroztříděné' nebyla nalezena:\n{unsorted_folder}"
                )
                return
                
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nelze určit složku Neroztříděné:\n{e}")
            return
        
        # Najdi všechny PNG soubory s polygonem
        png_files_with_polygon = []
        try:
            for png_file in unsorted_folder.glob("*.png"):
                if png_file.is_file():
                    # Kontrola, zda má polygon
                    try:
                        if hasattr(self, "has_aoi_polygon") and self.has_aoi_polygon(str(png_file)):
                            png_files_with_polygon.append(png_file)
                    except Exception:
                        continue
                        
        except Exception:
            QMessageBox.critical(self, "Chyba", "Nelze prohledat složku Neroztříděné.")
            return
        
        if not png_files_with_polygon:
            QMessageBox.information(
                self,
                "Informace",
                f"Ve složce 'Neroztříděné' nebyly nalezeny žádné PNG soubory s polygonem."
            )
            return
        
        # Progress dialog
        progress = QProgressDialog(
            f"Přepočítávání ploch u {len(png_files_with_polygon)} PNG map...",
            "Zrušit", 0, len(png_files_with_polygon), self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        
        # Zpracování souborů
        ok_count = 0
        failed_files = []
        
        for i, png_file in enumerate(png_files_with_polygon):
            if progress.wasCanceled():
                break
                
            progress.setValue(i)
            progress.setLabelText(f"Zpracovávání: {png_file.name}")
            
            # Přepočítej plochu
            if hasattr(self, "compute_and_store_aoi_area"):
                if self.compute_and_store_aoi_area(str(png_file), suppress_ui=True):
                    ok_count += 1
                else:
                    failed_files.append(png_file.name)
            else:
                failed_files.append(png_file.name)
        
        progress.setValue(len(png_files_with_polygon))
        
        # Obnov strom
        try:
            self.refresh_file_tree()
        except Exception:
            pass
        
        # Výsledek
        if failed_files:
            QMessageBox.warning(
                self,
                "Dokončeno s chybami",
                f"Plocha byla úspěšně přepočítána u {ok_count} souborů.\n"
                f"Chyby u {len(failed_files)} souborů:\n{', '.join(failed_files[:5])}"
                f"{'...' if len(failed_files) > 5 else ''}"
            )
        else:
            QMessageBox.information(
                self,
                "Hotovo",
                f"Plocha byla úspěšně přepočítána u {ok_count} PNG map s polygonem."
            )


    def compute_and_store_aoi_area(self, png_path: str, suppress_ui: bool = False) -> bool:
        """
        Spočítá plochu polygonu z metadat 'AOI_POLYGON' daného PNG a uloží ji do PNG text metadat
        pod klíčem 'AOI_AREA_M2' (metry čtvereční, s přesností na 2 desetinná místa).
    
        Požadavky:
          - PNG musí existovat a obsahovat 'AOI_POLYGON' v textových metadatech (JSON se seznamem bodů "points": [[x,y], ...] v pixelech).
          - Název souboru musí obsahovat GPS a zoom, např. "...GPS49.23091S+17.65690V...+Z18+..." nebo s EN značením "...GPS49.23091N+17.65690E...".
    
        Vrací:
          - True při úspěchu, jinak False (zaloguje důvody, pokud je k dispozici self.log_widget).
        """
        try:
            from pathlib import Path
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
            import json, math, re, tempfile, os
    
            p = Path(png_path)
            if p.suffix.lower() != ".png" or not p.exists():
                return False
    
            # --- 1) Načtení polygonu z metadat (AOI_POLYGON) ---
            def _read_polygon_points(path: Path):
                try:
                    with Image.open(str(path)) as im:
                        # Primárně img.text, případně fallback na info
                        meta = {}
                        try:
                            if hasattr(im, "text") and im.text:
                                meta = dict(im.text)
                        except Exception:
                            meta = {}
                        if not meta and hasattr(im, "info") and im.info:
                            meta = dict(im.info)
                        raw = meta.get("AOI_POLYGON")
                        if not raw:
                            return None
                        data = json.loads(raw)
                        pts = data.get("points") or []
                        if not isinstance(pts, list) or len(pts) < 3:
                            return None
                        return [(float(x), float(y)) for x, y in pts]
                except Exception:
                    return None
    
            pts = _read_polygon_points(p)
            if not pts:
                try:
                    if hasattr(self, "log_widget"):
                        self.log_widget.add_log(f"⚠️ Nelze spočítat plochu — chybí/poškozený 'AOI_POLYGON' v: {p.name}", "warning")
                    if not suppress_ui:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "AOI plocha", "V PNG nejsou dostupné body polygonu (AOI_POLYGON).")
                except Exception:
                    pass
                return False
    
            # --- 2) Získání GPS (lat, lon) a zoomu ze jména souboru ---
            name = p.stem
    
            # Vzor: "GPS<lat><S/J/N>+<lon><V/Z/E/W>" (CZ i EN směry; GPS prefix volitelný)
            m = re.search(
                r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])',
                name, re.IGNORECASE
            )
            lat = lon = None
            if m:
                lat_val = float(m.group(1).replace(',', '.'))
                lat_dir = m.group(2).upper()
                lon_val = float(m.group(3).replace(',', '.'))
                lon_dir = m.group(4).upper()
                # EN směry mají N/E/W, CZ směry mají S/J/V/Z
                if lat_dir in {'N', 'S'} or lon_dir in {'E', 'W'}:
                    lat = -lat_val if lat_dir == 'S' else lat_val
                    lon = -lon_val if lon_dir == 'W' else lon_val
                else:
                    # CZ: S(+), J(-), V(+), Z(-)
                    lat = -lat_val if lat_dir == 'J' else lat_val
                    lon = -lon_val if lon_dir == 'Z' else lon_val
    
            mz = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', name, re.IGNORECASE)
            zoom = int(mz.group(1)) if mz else None
    
            if (lat is None) or (zoom is None):
                try:
                    if hasattr(self, "log_widget"):
                        self.log_widget.add_log(f"⚠️ Nelze spočítat plochu — v názvu chybí GPS/Zoom: {p.name}", "warning")
                    if not suppress_ui:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "AOI plocha", "V názvu souboru chybí GPS a/nebo Zoom (např. +Z18+).")
                except Exception:
                    pass
                return False
    
            # --- 3) Výpočet měřítka (metry na pixel) pro Web Mercator ---
            try:
                R = 6378137.0  # poloměr sferoidu pro Web Mercator (m)
                z = max(0, min(23, int(zoom)))
                lat_rad = math.radians(float(lat))
                mpp = (2.0 * math.pi * R * math.cos(lat_rad)) / (256.0 * (2 ** z))
            except Exception:
                mpp = None
    
            if not mpp or not math.isfinite(mpp) or mpp <= 0.0:
                try:
                    if hasattr(self, "log_widget"):
                        self.log_widget.add_log(f"⚠️ Nelze spočítat plochu — nepodařilo se odvodit m/px (lat={lat}, zoom={zoom}).", "warning")
                    if not suppress_ui:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "AOI plocha", "Nepodařilo se spočítat měřítko (metry/pixel) z GPS/Zoom.")
                except Exception:
                    pass
                return False
    
            # --- 4) Shoelace v pixelech -> m² ---
            area_px2 = 0.0
            n = len(pts)
            for i in range(n):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % n]
                area_px2 += x1 * y2 - x2 * y1
            area_px2 = 0.5 * abs(area_px2)
            area_m2 = float(area_px2) * (float(mpp) ** 2)
            area_str = f"{area_m2:.2f}"
    
            # --- 5) Zápis 'AOI_AREA_M2' do PNG text metadat ---
            try:
                with Image.open(str(p)) as im:
                    # Načti existující textová metadata
                    existing = {}
                    try:
                        if hasattr(im, "text") and im.text:
                            existing = dict(im.text)
                    except Exception:
                        existing = {}
    
                    pinfo = PngInfo()
                    for k, v in existing.items():
                        # přepiš klíč AOI_AREA_M2, ostatní zkopíruj
                        if str(k).strip().upper() != "AOI_AREA_M2":
                            try:
                                pinfo.add_text(str(k), str(v))
                            except Exception:
                                pass
                    pinfo.add_text("AOI_AREA_M2", area_str)
    
                    save_kwargs = {}
                    dpi = im.info.get("dpi")
                    if isinstance(dpi, tuple):
                        save_kwargs["dpi"] = dpi
    
                    # Bezpečné přepsání přes dočasný soubor
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                        tmp_path = Path(tmp.name)
                    try:
                        im.save(tmp_path, format="PNG", pnginfo=pinfo, **save_kwargs)
                        os.replace(tmp_path, p)
                    finally:
                        try:
                            if tmp_path.exists():
                                tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception as e:
                try:
                    if hasattr(self, "log_widget"):
                        self.log_widget.add_log(f"❌ Chyba při ukládání AOI_AREA_M2 do {p.name}: {e}", "error")
                except Exception:
                    pass
                return False
    
            # --- 6) UI informace + refresh ---
            try:
                if hasattr(self, "log_widget"):
                    self.log_widget.add_log(f"📐 AOI plocha: {float(area_str):.2f} m² uložena do metadat ({p.name})", "success")
            except Exception:
                pass
            if not suppress_ui:
                try:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(self, "AOI plocha", f"Plocha polygonu: {float(area_str):.2f} m²\nUloženo do metadat (AOI_AREA_M2).")
                except Exception:
                    pass
    
            try:
                if hasattr(self, "refresh_file_tree"):
                    self.refresh_file_tree()
            except Exception:
                pass
    
            return True
    
        except Exception as e:
            try:
                if hasattr(self, "log_widget"):
                    self.log_widget.add_log(f"❌ Výjimka při výpočtu AOI plochy: {e}", "error")
            except Exception:
                pass
            return False
        
    def compute_and_store_aoi_area_bulk(self) -> None:
        """
        Projde aktuálně vybrané položky ve stromu a pro všechny .png soubory
        s AOI_POLYGON spočítá plochu a uloží ji do metadat jako AOI_AREA_M2.
        Nezobrazuje per-soubor dialogy.
        """
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import Qt
        from pathlib import Path
        
        selected = self.file_tree.selectedItems() if hasattr(self, "file_tree") else []
        png_paths = []
        
        for it in selected:
            try:
                fp = it.data(0, Qt.UserRole)
                if not fp:
                    continue
                p = Path(fp)
                if p.is_file() and p.suffix.lower() == ".png" and p.exists():
                    # Kontrola, zda má polygon
                    try:
                        if hasattr(self, "has_aoi_polygon") and self.has_aoi_polygon(str(p)):
                            png_paths.append(p)
                    except Exception:
                        continue
            except Exception:
                continue
        
        if not png_paths:
            QMessageBox.information(
                self, 
                "Informace", 
                "Ve výběru nejsou žádné PNG soubory s polygonem (AOI_POLYGON)."
            )
            return
        
        ok, fail = 0, []
        for p in png_paths:
            if self.compute_and_store_aoi_area(str(p), suppress_ui=True):
                ok += 1
            else:
                fail.append(p.name)
        
        # Obnov strom jednou
        try:
            self.refresh_file_tree()
        except Exception:
            pass
        
        if fail:
            QMessageBox.warning(
                self,
                "Dokončeno s chybami",
                f"Plocha byla úspěšně vypočítána a uložena u {ok} souborů.\n"
                f"Chyba u: {', '.join(fail)}"
            )
        else:
            QMessageBox.information(
                self, 
                "Hotovo", 
                f"Plocha byla vypočítána a uložena u {ok} PNG souborů s polygonem."
            )

    def show_context_menu(self, position):
        """Zobrazení kontextového menu včetně hromadných akcí a editoru polygonu pro PNG + HEIC náhled."""
        item = self.file_tree.itemAt(position)
        if not item:
            return
        file_path = item.data(0, Qt.UserRole)
        if not file_path:
            return
        path_obj = Path(file_path)
        if not path_obj.exists():
            return
    
        context_menu = QMenu(self)
    
        # Akce pro výběr (jeden nebo více souborů)
        selected = self.file_tree.selectedItems()
        if selected and len(selected) >= 1:
            # Kopírovat
            if len(selected) > 1:
                copy_multi = QAction(f"📋 Kopírovat vybrané ({len(selected)})", self)
                copy_multi.triggered.connect(self.copy_selected_items)
                context_menu.addAction(copy_multi)
            
            # Smazat
            if len(selected) > 1:
                delete_multi = QAction(f"🗑️ Smazat vybrané ({len(selected)})", self)
                delete_multi.triggered.connect(self.delete_selected_items)
                context_menu.addAction(delete_multi)
    
            # Hromadné akce pro PNG (fungují i pro jeden soubor)
            try:
                png_count = 0
                for it in selected:
                    fp = it.data(0, Qt.UserRole)
                    if not fp:
                        continue
                    p = Path(fp)
                    if p.is_file() and p.suffix.lower() == ".png" and p.exists():
                        png_count += 1
                
                if png_count > 0:
                    # Přípsat příznak
                    label_add = f"🏷️ Připsat příznak 'Anonymizovaná lokace' (PNG: {png_count})"
                    anonym_multi_add = QAction(label_add, self)
                    anonym_multi_add.triggered.connect(self.add_anonymized_location_flag_bulk)
                    context_menu.addAction(anonym_multi_add)
    
                    # Odstranit příznak
                    label_remove = f"🏷️ Odstranit příznak 'Anonymizovaná lokace' (PNG: {png_count})"
                    anonym_multi_remove = QAction(label_remove, self)
                    anonym_multi_remove.triggered.connect(self.remove_anonymized_location_flag_bulk)
                    context_menu.addAction(anonym_multi_remove)
                    
                    # Spočítat plochu AOI
                    label_area = f"📐 Spočítat plochu AOI (PNG: {png_count})"
                    aoi_bulk_action = QAction(label_area, self)
                    aoi_bulk_action.triggered.connect(self.compute_and_store_aoi_area_bulk)
                    context_menu.addAction(aoi_bulk_action)
            except Exception:
                pass
    
            context_menu.addSeparator()
    
        # Jednotlivé akce podle typu položky
        if path_obj.is_file():
            copy_action = QAction("📋 Kopírovat soubor", self)
            copy_action.triggered.connect(lambda: self.copy_file_or_folder(str(path_obj)))
            context_menu.addAction(copy_action)
        else:
            copy_action = QAction("📋 Kopírovat složku", self)
            copy_action.triggered.connect(lambda: self.copy_file_or_folder(str(path_obj)))
            context_menu.addAction(copy_action)
    
        # Vložení (aktivní pouze pro složku)
        if path_obj.is_dir() and hasattr(self, 'clipboard_data') and self.clipboard_data:
            paste_action = QAction("📥 Vložit zde", self)
            paste_action.triggered.connect(lambda: self.paste_file_or_folder(str(path_obj)))
            context_menu.addAction(paste_action)
        elif path_obj.is_dir():
            paste_action = QAction("📥 Vložit zde (prázdná schránka)", self)
            paste_action.setEnabled(False)
            context_menu.addAction(paste_action)
    
        # Přejmenování
        rename_action = QAction("✏️ Přejmenovat", self)
        rename_action.triggered.connect(lambda: self.rename_file_or_folder(str(path_obj)))
        context_menu.addAction(rename_action)
    
        # Vytvoření podsložky (pouze pro složku)
        if path_obj.is_dir():
            create_subfolder_action = QAction("📁➕ Vytvořit podsložku", self)
            create_subfolder_action.triggered.connect(lambda: self.create_subfolder(str(path_obj)))
            context_menu.addAction(create_subfolder_action)
    
        context_menu.addSeparator()
    
        # Akce specifické pro PNG: editor polygonu
        if path_obj.is_file() and path_obj.suffix.lower() == ".png":
            edit_poly_action = QAction("🔺 Upravit oblast (polygon)", self)
            edit_poly_action.triggered.connect(lambda: self.on_edit_polygon_for_path(str(path_obj)))
            context_menu.addAction(edit_poly_action)
    
            context_menu.addSeparator()
    
        # Náhled .HEIC
        if path_obj.is_file() and path_obj.suffix.lower() == ".heic":
            heic_action = QAction("📷 Náhled .HEIC (lokace & polygon)…", self)
            heic_action.triggered.connect(lambda: self._open_heic_preview_dialog_for_path(str(path_obj)))
            context_menu.addAction(heic_action)
            context_menu.addSeparator()
    
        # Smazání jedné položky
        delete_text = "🗑️ Smazat složku" if path_obj.is_dir() else "🗑️ Smazat soubor"
        delete_action = QAction(delete_text, self)
        delete_action.triggered.connect(lambda: self.delete_file_or_folder(str(path_obj)))
        context_menu.addAction(delete_action)
    
        context_menu.addSeparator()
    
        # Otevřít umístění v systému
        open_folder_action = QAction("📂 Otevřít ve Finderu", self)
        open_folder_action.triggered.connect(lambda: self.open_file_location(str(path_obj)))
        context_menu.addAction(open_folder_action)
    
        context_menu.addSeparator()
    
        # Vlastnosti
        info_action = QAction("ℹ️ Vlastnosti", self)
        info_action.triggered.connect(lambda: self.show_file_info(str(path_obj)))
        context_menu.addAction(info_action)
    
        # Zobrazení kontextového menu
        context_menu.exec(self.file_tree.mapToGlobal(position))

        
    def _open_heic_preview_dialog_for_path(self, path: str):
        """
        Toggle náhledu pro .HEIC/.HEIF:
          - 1. stisk SPACE: otevřít ne-modální náhled (polygon z metadat se vykreslí).
          - 2. stisk SPACE: zavřít aktuální náhled.
        Požadovaný podpis HeicPreviewDialog: HeicPreviewDialog(image_path, maps_root, parent=None)
        Cmd+W (QKeySequence.Close) zavře náhled.
        """
        from pathlib import Path
        from PySide6.QtCore import QTimer
        p = Path(path)

        # Toggle: pokud je okno už otevřené -> zavřít
        if hasattr(self, "_heic_preview_dialog") and self._heic_preview_dialog:
            try:
                if self._heic_preview_dialog.isVisible():
                    self._heic_preview_dialog.close()
                    self._heic_preview_dialog = None
                    return
            except Exception:
                self._heic_preview_dialog = None  # pojistka

        # maps_root
        try:
            maps_root = Path(self.default_maps_path) if hasattr(self, "default_maps_path") else p.parent
        except Exception:
            maps_root = p.parent

        # Import dialogu
        HeicPreviewDialog = None
        try:
            from image_viewer import HeicPreviewDialog
        except Exception:
            try:
                from .image_viewer import HeicPreviewDialog  # pokud je v balíčku
            except Exception:
                try:
                    from gui.image_viewer import HeicPreviewDialog
                except Exception:
                    HeicPreviewDialog = None
        if HeicPreviewDialog is None:
            # fallback načtení vedle main_window.py
            try:
                import importlib.util, sys
                here = Path(__file__).resolve()
                iv_path = here.with_name("image_viewer.py")
                spec = importlib.util.spec_from_file_location("image_viewer_heic_preview_fallback", str(iv_path))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["image_viewer_heic_preview_fallback"] = mod
                    spec.loader.exec_module(mod)
                    HeicPreviewDialog = getattr(mod, "HeicPreviewDialog", None)
            except Exception:
                HeicPreviewDialog = None
        if HeicPreviewDialog is None:
            return

        dlg = HeicPreviewDialog(Path(path), Path(maps_root), parent=self)
        self._heic_preview_dialog = dlg
        try:
            dlg.setModal(False)
        except Exception:
            pass

        # Zavření na mezerník (toggle), ESC a Cmd+W
        try:
            from PySide6.QtGui import QKeySequence, QShortcut
            sc_space = QShortcut(QKeySequence("Space"), dlg)
            sc_space.setAutoRepeat(False)
            sc_space.activated.connect(dlg.close)

            sc_esc = QShortcut(QKeySequence("Escape"), dlg)
            sc_esc.setAutoRepeat(False)
            sc_esc.activated.connect(dlg.close)

            sc_close = QShortcut(QKeySequence(QKeySequence.Close), dlg)  # Cmd+W
            sc_close.setAutoRepeat(False)
            sc_close.activated.connect(dlg.close)
        except Exception:
            pass

        # Refresh stromu po zavření + uvolnění reference
        try:
            dlg.finished.connect(lambda _res: self.refresh_file_tree())
            dlg.finished.connect(lambda _res: setattr(self, "_heic_preview_dialog", None))
        except Exception:
            try:
                dlg.finished.connect(lambda _res: setattr(self, "_heic_preview_dialog", None))
            except Exception:
                pass

        # Po zavření znovu vyber původní (nebo přejmenovaný) soubor ve stromu
        try:
            def _reselect_after_close(_res, d=dlg, orig=str(p)):
                final_path = str(getattr(d, "image_path", orig))
                QTimer.singleShot(0, lambda fp=final_path: self._reselect_in_file_tree(fp))
            dlg.finished.connect(_reselect_after_close)
        except Exception:
            pass

        dlg.show()
        try:
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            pass
        
    def _reselect_in_file_tree(self, target_path: str):
        """
        Najde a vybere položku ve stromu souborů dle absolutní cesty (Qt.UserRole).
        Pokud existuje, rozbalí rodiče, vybere ji a posune na ni pohled.
        """
        try:
            from pathlib import Path
            from PySide6.QtCore import Qt
            target = str(Path(target_path))
            if not hasattr(self, "file_tree") or self.file_tree is None:
                return

            def _find_rec(itm):
                if not itm:
                    return None
                data = itm.data(0, Qt.UserRole)
                if data and str(data) == target:
                    return itm
                for j in range(itm.childCount()):
                    f = _find_rec(itm.child(j))
                    if f:
                        return f
                return None

            found = None
            for i in range(self.file_tree.topLevelItemCount()):
                it = self.file_tree.topLevelItem(i)
                found = _find_rec(it)
                if found:
                    break

            if found:
                # rozbalit rodiče, aby byl vidět
                par = found.parent()
                while par:
                    try:
                        par.setExpanded(True)
                    except Exception:
                        pass
                    par = par.parent()
                self.file_tree.setCurrentItem(found)
                try:
                    self.file_tree.scrollToItem(found)
                except Exception:
                    pass
        except Exception:
            pass
        
    def _on_heic_file_renamed(self, old_path: str, new_path: str):
        """
        Po přejmenování .HEIC aktualizuje odpovídající položku ve stromu:
        - nastaví nový text (název),
        - přepíše Qt.UserRole (cestu),
        - zachová výběr.
        """
        try:
            from pathlib import Path
            old_p = str(Path(old_path))
            new_p = str(Path(new_path))
    
            def _find_item_by_path(root_widget):
                # DFS přes top-level položky
                for i in range(self.file_tree.topLevelItemCount()):
                    it = self.file_tree.topLevelItem(i)
                    found = _find_rec(it)
                    if found:
                        return found
                return None
    
            def _find_rec(itm):
                if not itm:
                    return None
                data = itm.data(0, Qt.UserRole)
                if data and str(data) == old_p:
                    return itm
                for j in range(itm.childCount()):
                    c = itm.child(j)
                    f = _find_rec(c)
                    if f:
                        return f
                return None
    
            item = _find_item_by_path(self.file_tree)
            if item:
                # přepiš text a cestu
                item.setText(0, Path(new_p).name)
                item.setData(0, Qt.UserRole, new_p)
                # vyber a posuň se na něj
                self.file_tree.setCurrentItem(item)
            else:
                # když nenalezeno, aspoň full refresh
                self.refresh_file_tree()
        except Exception:
            # poslední záchrana
            self.refresh_file_tree()
        
    def _load_HeicPreviewDialog_class(self):
        """
        Robustní načtení HeicPreviewDialog z image_viewer.py.
        Zkouší postupně:
          1) from image_viewer import HeicPreviewDialog
          2) from .image_viewer import HeicPreviewDialog  (pokud je v balíčku)
          3) importlib ze souboru vedle main_window.py (fallback)
        Vrací objekt třídy HeicPreviewDialog nebo vyhodí výjimku.
        """
        # 1) přímý import (běžné, pokud je image_viewer.py na sys.path)
        try:
            from image_viewer import HeicPreviewDialog  # type: ignore
            return HeicPreviewDialog
        except Exception as e1:
            last_err = e1
    
        # 2) relativní import (pokud je projekt strukturovaný jako balíček)
        try:
            from .image_viewer import HeicPreviewDialog  # type: ignore
            return HeicPreviewDialog
        except Exception as e2:
            last_err = e2
    
        # 3) fallback: načtení souboru image_viewer.py, který leží vedle main_window.py
        try:
            import importlib.util, sys
            from pathlib import Path
            here = Path(__file__).resolve()
            iv_path = here.with_name("image_viewer.py")
            if not iv_path.exists():
                raise FileNotFoundError(f"Soubor image_viewer.py nebyl nalezen vedle {here.name} ({iv_path})")
    
            spec = importlib.util.spec_from_file_location("image_viewer_fallback", str(iv_path))
            if spec is None or spec.loader is None:
                raise ImportError("Nelze vytvořit import spec pro image_viewer_fallback")
    
            mod = importlib.util.module_from_spec(spec)
            sys.modules["image_viewer_fallback"] = mod
            spec.loader.exec_module(mod)
            HeicPreviewDialog = getattr(mod, "HeicPreviewDialog", None)
            if HeicPreviewDialog is None:
                raise AttributeError("V image_viewer.py chybí třída HeicPreviewDialog")
            return HeicPreviewDialog
        except Exception as e3:
            # poskládej užitečnou hlášku
            raise ImportError(
                "Nepodařilo se importovat HeicPreviewDialog z image_viewer.py.\n\n"
                f"1) from image_viewer import HeicPreviewDialog -> {type(last_err).__name__}: {last_err}\n"
                f"2) from .image_viewer import HeicPreviewDialog -> {type(e2).__name__}: {e2}\n"
                f"3) fallback importlib z vedlejšího souboru -> {type(e3).__name__}: {e3}"
            )
        
    class RegenerateProgressDialog(QDialog):
        """Lehký modální dialog s popisem, velkým progress barem a živým logem."""
        def __init__(self, parent=None, total=0):
            super().__init__(parent)
            self.setWindowTitle("Přegenerování vybraných")
            self.setModal(True)
            self.resize(560, 260)
    
            v = QVBoxLayout(self)
    
            # Popisek
            self.label = QLabel("Příprava…")
            self.label.setWordWrap(True)
            v.addWidget(self.label)
    
            # Velký progress bar
            self.progress = QProgressBar()
            self.progress.setRange(0, max(1, total))
            self.progress.setValue(0)
            v.addWidget(self.progress)
    
            # Živý log
            self.text = QTextEdit()
            self.text.setReadOnly(True)
            self.text.setMinimumHeight(120)
            v.addWidget(self.text)
    
            # Spodní lišta
            h = QHBoxLayout()
            h.addStretch()
            self.btn_cancel = QPushButton("Zrušit")
            self.btn_cancel.clicked.connect(self.reject)
            h.addWidget(self.btn_cancel)
            v.addLayout(h)
    
            # Stav zrušení
            self._canceled = False
            self.rejected.connect(lambda: setattr(self, "_canceled", True))
    
            # NOVÉ: Cmd+W / Close – zavři dialog (ekvivalent Zrušit)
            from PySide6.QtGui import QShortcut, QKeySequence
            self._sc_close = QShortcut(QKeySequence(QKeySequence.Close), self)
            self._sc_close.activated.connect(self.reject)
    
        def wasCanceled(self) -> bool:
            return self._canceled
    
        def set_total_range(self, total: int):
            self.progress.setRange(0, max(1, total))
    
        def set_index(self, index: int, total: int, filename: str):
            self.label.setText(f"[{index}/{total}] {filename}")
            self.progress.setValue(index)
    
        def set_percent(self, percent: int, msg: str = ""):
            if self.progress.maximum() != 100:
                self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, int(percent))))
            if msg:
                self.label.setText(msg)
    
        def append_log(self, line: str):
            """Oprava: použít QTextCursor.End místo neexistující .End instance."""
            from PySide6.QtGui import QTextCursor
            self.text.append(line)
            self.text.moveCursor(QTextCursor.End)

    def regenerate_selected_items(self):
        """Hromadné přegenerování vybraných PNG souborů s ponecháním parametrů z názvu a aplikací aktuálních výstupních (cm/DPI)."""
        try:
            items = self.file_tree.selectedItems() if hasattr(self, 'file_tree') else []
            paths = []
            for it in items:
                p_str = it.data(0, Qt.UserRole)
                if not p_str:
                    continue
                p = Path(p_str)
                if p.exists() and p.is_file() and p.suffix.lower() == ".png":
                    paths.append(p)
    
            if not paths:
                QMessageBox.information(self, "Info", "Vyberte prosím v seznamu PNG soubory k přegenerování.")
                return
    
            from PySide6.QtWidgets import QApplication  # kvůli processEvents
            dlg = self.RegenerateProgressDialog(self, total=len(paths))
            dlg.set_total_range(len(paths))
            dlg.show()
            QApplication.processEvents()
    
            import re
            def parse_gps_and_zoom_and_id_from_name(name: str):
                stem = Path(name).stem
                mgps = re.search(r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])', stem, re.IGNORECASE)
                lat = lon = None
                if mgps:
                    lat_val = float(mgps.group(1).replace(',', '.'))
                    lat_dir = mgps.group(2).upper()
                    lon_val = float(mgps.group(3).replace(',', '.'))
                    lon_dir = mgps.group(4).upper()
                    english_mode = any(d in {'N','E','W'} for d in {lat_dir, lon_dir})
                    if english_mode:
                        lat = -lat_val if lat_dir == 'S' else lat_val
                        lon = -lon_val if lon_dir == 'W' else lon_val
                    else:
                        lat = -lat_val if lat_dir == 'J' else lat_val
                        lon = -lon_val if lon_dir == 'Z' else lon_val
                mzoom = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', stem, re.IGNORECASE)
                zoom = max(1, min(19, int(mzoom.group(1)))) if mzoom else None
                manual_id = None
                parts = stem.split('+')
                if parts:
                    last = parts[-1]
                    mid = re.match(r'^\d{5}$', last)
                    if mid:
                        manual_id = mid.group(0)
                if manual_id is None:
                    mend = re.search(r'(\d{5})(?:$|[^0-9])', stem)
                    if mend:
                        manual_id = mend.group(1)
                return lat, lon, zoom, manual_id
    
            def format_cz_coords(lat: float, lon: float) -> str:
                lat_dir = 'J' if lat < 0 else 'S'
                lon_dir = 'Z' if lon < 0 else 'V'
                return f"{abs(lat):.5f}° {lat_dir}, {abs(lon):.5f}° {lon_dir}"
    
            out_w_cm = float(self.spin_width.value())
            out_h_cm = float(self.spin_height.value())
            out_dpi  = int(self.spin_dpi.value())
    
            ok = 0
            fail = 0
    
            for idx, file_path in enumerate(paths, start=1):
                if dlg.wasCanceled():
                    break
    
                dlg.set_index(idx, len(paths), f"Připravuji: {file_path.name}")
                dlg.append_log(f"➡️ Přegenerování: {file_path.name}")
                QApplication.processEvents()
    
                try:
                    # Snapshot textových metadat z původního PNG (před generováním)
                    src_snapshot = self._read_png_text_meta(str(file_path))
    
                    lat, lon, z, manual_id = parse_gps_and_zoom_and_id_from_name(file_path.name)
                    if lat is None or lon is None or z is None:
                        self.log_widget.add_log(f"⚠️ Přeskočeno (nelze vyčíst GPS/Zoom z názvu): {file_path.name}", "warning")
                        dlg.append_log("⚠️ Nelze vyčíst GPS/Zoom z názvu – přeskočeno")
                        fail += 1
                        continue
    
                    extracted = {}
                    try:
                        extracted = self.extract_location_info_from_filename(file_path.name) or {}
                    except Exception:
                        extracted = {}
                    id_lokace = extracted.get('ID Lokace') or self.input_id_lokace.text()
                    popis     = extracted.get('Popis') or self.input_popis.text()
    
                    params = self.get_parameters()
                    params['coordinate_mode']    = 'G'
                    params['manual_coordinates'] = format_cz_coords(lat, lon)
                    params['zoom']               = z
                    params['photo_filename']     = str(file_path)
                    params['output_directory']   = str(file_path.parent)
                    params['output_width_cm']    = out_w_cm
                    params['output_height_cm']   = out_h_cm
                    params['output_dpi']         = out_dpi
                    params['auto_generate_id']   = False
                    if manual_id:
                        params['manual_cislo_id'] = manual_id
                    if id_lokace:
                        params['id_lokace'] = id_lokace
                    if popis:
                        params['popis'] = popis
    
                    # 🔸 nově: volba anonymizace z GUI
                    params['anonymizovana_lokace'] = bool(self.checkbox_anonymni_lokace.isChecked())
    
                    local_thread = ProcessorThread(params)
    
                    def _on_progress(val: int):
                        dlg.set_percent(val, f"[{idx}/{len(paths)}] Generuji: {file_path.name}")
                    local_thread.progress.connect(_on_progress)
    
                    def _on_log(msg: str, level: str):
                        try:
                            self.log_widget.add_log(msg, level)
                        except Exception:
                            pass
                        dlg.append_log(f"{msg}")
                        if "tile" in msg.lower() or "dlažd" in msg.lower() or "stahován" in msg.lower():
                            dlg.label.setText(f"[{idx}/{len(paths)}] {msg}")
                    local_thread.log.connect(_on_log)
    
                    from PySide6.QtCore import QEventLoop
                    loop = QEventLoop()
                    result_container = {'out': None, 'err': None}
                    local_thread.finished.connect(lambda out_path: (result_container.update(out=out_path), loop.quit()))
                    local_thread.error.connect(lambda err: (result_container.update(err=err), loop.quit()))
    
                    self.log_widget.add_log(f"🚀 Přegenerování: {file_path.name} (Z{z}, {params['manual_coordinates']})", "info")
                    dlg.append_log(f"🔍 Parametry: Z{z}, {params['manual_coordinates']}, {out_w_cm:.2f}×{out_h_cm:.2f} cm @ {out_dpi} DPI")
    
                    local_thread.start()
                    loop.exec()
    
                    try:
                        local_thread.quit()
                        local_thread.wait()
                    except Exception:
                        pass
    
                    if result_container['err']:
                        self.log_widget.add_log(f"❌ Chyba generování {file_path.name}: {result_container['err']}", "error")
                        dlg.append_log(f"❌ Chyba: {result_container['err']}")
                        fail += 1
                        continue
    
                    out_path = result_container['out']
                    if not out_path or not Path(out_path).exists():
                        self.log_widget.add_log(f"❌ Chybí výstup pro {file_path.name}", "error")
                        dlg.append_log("❌ Chybí výstupní soubor")
                        fail += 1
                        continue
    
                    try:
                        self.embed_output_params_into_png(out_path)
                    except Exception as e:
                        self.log_widget.add_log(f"⚠️ Metadata (cm/DPI) do PNG selhala pro {Path(out_path).name}: {e}", "warning")
                        dlg.append_log(f"⚠️ Metadata PNG selhala: {e}")
    
                    # Zachovat metadata ze snapshotu → anonymizační příznak kopíruj jen pokud checkbox není zaškrtnutý
                    try:
                        keys_to_copy = []
                        if not self.checkbox_anonymni_lokace.isChecked():
                            keys_to_copy = ["Anonymizovaná lokace", "Anonymizovana lokace"]
                        if keys_to_copy:
                            self._preserve_selected_png_text_metadata(
                                src_png=str(file_path),
                                dst_png=str(out_path),
                                keys=keys_to_copy,
                                src_snapshot=src_snapshot,
                            )
                    except Exception:
                        pass
    
                    import os
                    os.replace(out_path, file_path)
                    self.log_widget.add_log(f"✅ Nahrazen soubor: {file_path.name}", "success")
                    dlg.append_log("✅ Nahrazen původní soubor")
                    ok += 1
    
                    dlg.set_index(idx, len(paths), f"Dokončeno: {file_path.name}")
                    QApplication.processEvents()
                    if dlg.wasCanceled():
                        break
    
                except Exception as e:
                    fail += 1
                    self.log_widget.add_log(f"❌ Chyba při přegenerování {file_path.name}: {e}", "error")
                    dlg.append_log(f"❌ Výjimka: {e}")
    
            # Uzavřít dialog
            dlg.progress.setValue(dlg.progress.maximum())
            dlg.label.setText(f"Hotovo – přegenerováno: {ok}, nezdařilo se: {fail}")
            QApplication.processEvents()
            dlg.accept()
    
            # Refresh stromu a info
            self.refresh_file_tree()
            QMessageBox.information(self, "Hotovo", f"Přegenerováno: {ok}\nNezdařilo se: {fail}")
    
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba přegenerování: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se přegenerovat vybrané soubory:\n{e}")
            
    def regenerate_file_in_place(self, file_path: str):
        """
        Přegeneruje JEDEN PNG 'na místě' s indikací průběhu v RegenerateProgressDialog:
        zachová název a vlastnosti (cm/DPI/marker), změní se jen obsah (např. polygon).
        Použije GPS/Zoom z názvu.
        """
        try:
            p = Path(file_path)
            if not p.exists() or not p.is_file() or p.suffix.lower() != ".png":
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"⚠️ Soubor není platný PNG: {p.name}", "warning")
                return
    
            # Snapshot metadat z původního PNG (před generováním)
            src_snapshot = self._read_png_text_meta(str(p))
    
            # Parsování GPS/Zoom/ID z názvu
            import re
            stem = p.stem
            mgps = re.search(r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])', stem, re.IGNORECASE)
            if not mgps:
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"⚠️ Nelze vyčíst GPS z názvu: {p.name}", "warning")
                return
            lat_val = float(mgps.group(1).replace(',', '.'))
            lat_dir = mgps.group(2).upper()
            lon_val = float(mgps.group(3).replace(',', '.'))
            lon_dir = mgps.group(4).upper()
            english_mode = any(d in {'N','E','W'} for d in {lat_dir, lon_dir})
            if english_mode:
                lat = -lat_val if lat_dir == 'S' else lat_val
                lon = -lon_val if lon_dir == 'W' else lon_val
            else:
                lat = -lat_val if lat_dir == 'J' else lat_val
                lon = -lon_val if lon_dir == 'Z' else lon_val
    
            mzoom = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', stem, re.IGNORECASE)
            if not mzoom:
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"⚠️ Nelze vyčíst Zoom z názvu: {p.name}", "warning")
                return
            z = max(1, min(19, int(mzoom.group(1))))
    
            # Výstupní parametry z GUI
            out_w_cm = float(self.spin_width.value())
            out_h_cm = float(self.spin_height.value())
            out_dpi  = int(self.spin_dpi.value())
    
            # Parametry pro ProcessorThread
            params = self.get_parameters()
            params['coordinate_mode']    = 'G'
            params['manual_coordinates'] = f"{abs(lat):.5f}° {'J' if lat<0 else 'S'}, {abs(lon):.5f}° {'Z' if lon<0 else 'V'}"
            params['zoom']               = z
            params['photo_filename']     = str(p)           # referenční
            params['output_directory']   = str(p.parent)    # výstup do stejné složky
            params['output_width_cm']    = out_w_cm
            params['output_height_cm']   = out_h_cm
            params['output_dpi']         = out_dpi
            params['auto_generate_id']   = False            # název zachováme (nahradíme)
            params['output_filename']    = "mapa_dlazdice.png"  # dočasný výstup (přepíše se do p)
    
            # 🔸 nově: volba anonymizace z GUI
            params['anonymizovana_lokace'] = bool(self.checkbox_anonymni_lokace.isChecked())
    
            # Dialog průběhu (jako u hromadného přegenerování)
            from PySide6.QtWidgets import QApplication
            dlg = self.RegenerateProgressDialog(self, total=1)
            dlg.set_total_range(1)
            dlg.set_index(1, 1, f"Přegenerování: {p.name}")
            dlg.label.setText(f"[1/1] Připravuji: {p.name}")
            dlg.show()
            QApplication.processEvents()
    
            # Vlákno + napojení signálů do dialogu
            local_thread = ProcessorThread(params)
    
            def _on_progress(val: int):
                dlg.set_percent(val, f"[1/1] Generuji: {p.name}")
            local_thread.progress.connect(_on_progress)
    
            def _on_log(msg: str, level: str):
                try:
                    self.log_widget.add_log(msg, level)
                except Exception:
                    pass
                dlg.append_log(f"{msg}")
                # Průběžný popisek dialogu podle stahování
                low = msg.lower()
                if "tile" in low or "dlažd" in low or "stahov" in low:
                    dlg.label.setText(f"[1/1] {msg}")
            local_thread.log.connect(_on_log)
    
            # Zastavení při zrušení dialogu
            try:
                dlg.rejected.connect(local_thread.stop)
            except Exception:
                pass
    
            # Čekání na dokončení (synchronně s lokálním event loopem)
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            result_container = {'out': None, 'err': None}
            local_thread.finished.connect(lambda out_path: (result_container.update(out=out_path), loop.quit()))
            local_thread.error.connect(lambda err: (result_container.update(err=err), loop.quit()))
    
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"🚀 Auto-přegenerování po uložení polygonu: {p.name} (Z{z})", "info")
    
            local_thread.start()
            loop.exec()
    
            # Ukončení vlákna
            try:
                local_thread.quit()
                local_thread.wait()
            except Exception:
                pass
    
            # Pokud uživatel dialog zrušil, ukončit bez nahrazení
            if dlg.wasCanceled():
                dlg.append_log("⏹ Zrušeno uživatelem")
                dlg.accept()
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"⏹ Zrušeno: {p.name}", "warning")
                return
    
            # Chyba
            if result_container['err']:
                dlg.append_log(f"❌ Chyba: {result_container['err']}")
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"❌ Chyba přegenerování {p.name}: {result_container['err']}", "error")
                dlg.accept()
                return
    
            out_path = result_container['out']
            if not out_path or not Path(out_path).exists():
                dlg.append_log("❌ Chybí výstupní soubor")
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"❌ Chybí výstup pro {p.name}", "error")
                dlg.accept()
                return
    
            # Dopsat metadata a atomicky nahradit
            try:
                self.embed_output_params_into_png(out_path)
            except Exception as e:
                dlg.append_log(f"⚠️ Metadata PNG selhala: {e}")
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"⚠️ Metadata (cm/DPI) do PNG selhala pro {Path(out_path).name}: {e}", "warning")
    
            # Zachovat metadata ze snapshotu → anonymizační příznak kopíruj jen pokud checkbox není zaškrtnutý
            try:
                keys_to_copy = []
                if not self.checkbox_anonymni_lokace.isChecked():
                    keys_to_copy = ["Anonymizovaná lokace", "Anonymizovana lokace"]
                if keys_to_copy:
                    self._preserve_selected_png_text_metadata(
                        src_png=str(p),
                        dst_png=str(out_path),
                        keys=keys_to_copy,
                        src_snapshot=src_snapshot,
                    )
            except Exception:
                pass
    
            import os as _os
            _os.replace(out_path, p)
            dlg.append_log("✅ Nahrazen původní soubor")
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"✅ Uložen přegenerovaný soubor (polygon aktualizován): {p.name}", "success")
    
            # Dokončit dialog
            dlg.set_percent(100, f"[1/1] Hotovo: {p.name}")
            dlg.accept()
    
            # Obnovit strom (čas změny apod.)
            try:
                self.refresh_file_tree()
            except Exception:
                pass
    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Výjimka při auto-přegenerování: {e}", "error")
                
    def _preserve_selected_png_text_metadata(self, src_png, dst_png, keys=None, src_snapshot=None):
        """
        Zkopíruje vybraná *textová* metadata ze zdroje (snapshot nebo src_png) do cílového PNG (dst_png),
        při zachování již existujících metadat v cíli. Přepíše/doplní pouze zadané klíče.
        Pro klíče s diakritikou ukládá i iTXt a ASCII fallback jako tEXt.
        """
        try:
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
            from pathlib import Path
            import unicodedata as _ud
            import os
    
            preserve_keys = keys or ["Anonymizovaná lokace", "Anonymizovana lokace", "AOI_AREA_M2"]
    
            def _ascii_fallback(s):
                norm = _ud.normalize("NFKD", s)
                return "".join(ch for ch in norm if not _ud.combining(ch))
    
            def _is_latin1_printable(s):
                try:
                    s.encode("latin-1")
                    if any(ord(c) < 32 or ord(c) == 127 for c in s):
                        return False
                    return len(s) <= 79
                except Exception:
                    return False
    
            def _collect_text_meta(p):
                return self._read_png_text_meta(str(p))
    
            def _casefold_map(d):
                m = {}
                for k in d.keys():
                    m.setdefault(k.casefold(), k)
                return m
    
            src_p = Path(src_png)
            dst_p = Path(dst_png)
            if not dst_p.exists():
                return False
    
            # Zdroj: snapshot (preferováno) nebo soubor
            if src_snapshot is not None:
                src_meta = dict(src_snapshot)
            else:
                if not src_p.exists():
                    return False
                src_meta = _collect_text_meta(src_p)
    
            dst_meta = _collect_text_meta(dst_p)
    
            # Sloučení: ponecháme vše z cíle a přepíšeme/ doplníme požadované klíče ze zdroje
            merged = dict(dst_meta)
            src_cf = _casefold_map(src_meta)
    
            for want in preserve_keys:
                src_key = src_cf.get(want.casefold())
                if not src_key:
                    ascii_want = _ascii_fallback(want)
                    src_key = src_cf.get(ascii_want.casefold())
                if not src_key:
                    continue
                value = src_meta.get(src_key, "")
                if value is None:
                    value = ""
                merged[src_key] = value
                ascii_key = _ascii_fallback(src_key)
                if ascii_key != src_key and _is_latin1_printable(ascii_key):
                    merged[ascii_key] = value
    
            # Zápis — replikujeme VŠECHNA merged metadata (iTXt + tEXt kde lze)
            try:
                with Image.open(str(dst_p)) as im_dst:
                    dpi = im_dst.info.get("dpi", (72, 72))
                    icc = im_dst.info.get("icc_profile")
                    pinfo = PngInfo()
                    for k, v in merged.items():
                        if not isinstance(v, str):
                            v = str(v)
                        try:
                            if hasattr(pinfo, "add_itxt"):
                                pinfo.add_itxt(str(k), v)
                        except Exception:
                            pass
                        if _is_latin1_printable(k):
                            try:
                                pinfo.add_text(str(k), v)
                            except Exception:
                                pass
                    tmp = dst_p.with_suffix(".meta.tmp.png")
                    save_kwargs = {"pnginfo": pinfo, "dpi": dpi}
                    if icc:
                        save_kwargs["icc_profile"] = icc
                    im_dst.save(str(tmp), "PNG", **save_kwargs)
                os.replace(str(tmp), str(dst_p))
            except Exception:
                return False
    
            return True
    
        except Exception:
            return False
        
    def _apply_anonym_flag_from_png_to_gui(self, png_path: str):
        """Načte z PNG metadat příznak anonymizace a promítne do checkboxu v GUI."""
        try:
            meta = self._read_png_text_meta(png_path)
            val = None
            for k in ("Anonymizovaná lokace", "Anonymizovana lokace"):
                if k in meta:
                    val = str(meta.get(k) or "").strip()
                    break
            is_anon = isinstance(val, str) and val.lower() in ("ano", "yes", "true", "1")
            self.checkbox_anonymni_lokace.setChecked(bool(is_anon))
        except Exception:
            try:
                self.checkbox_anonymni_lokace.setChecked(False)
            except Exception:
                pass
        
    def _read_png_text_meta(self, png_path):
        """
        Bezpečně načte textová metadata z PNG (tEXt, zTXt, iTXt) a vrátí je jako dict[str,str].
        """
        try:
            from PIL import Image
            meta = {}
            with Image.open(str(png_path)) as im:
                try:
                    if hasattr(im, "text") and im.text:
                        for k, v in im.text.items():
                            meta[str(k)] = str(v)
                except Exception:
                    pass
                try:
                    info = getattr(im, "info", {}) or {}
                    for k, v in info.items():
                        if isinstance(v, (bytes, bytearray)):
                            try:
                                v = v.decode("utf-8", "ignore")
                            except Exception:
                                try:
                                    v = v.decode("latin-1", "ignore")
                                except Exception:
                                    continue
                        if isinstance(v, str):
                            meta.setdefault(str(k), v)
                except Exception:
                    pass
            return meta
        except Exception:
            return {}

    def preview_selected_file(self):
        """Náhled aktuálně vybraného souboru (mezerník ve stromu).
           Opravy:
             • ↑/↓ přepíná na další/předchozí soubor v náhledu (mapuji přímo na next/prev, nebo emuluji ←/→).
             • ⌘W (QKeySequence.Close) zavírá náhled.
             • druhý stisk mezerníku náhled zavře (QuickLook toggle).
        """
        from pathlib import Path
        from PySide6.QtCore import Qt, QEvent, QCoreApplication
        from PySide6.QtGui import QKeySequence, QShortcut, QKeyEvent
        from gui.image_viewer import ImageViewerDialog
    
        def _wire_viewer_shortcuts(dlg):
            """Pevné zkratky: ⌘W zavřít, Space zavřít (toggle), ↑/↓ = next/prev (robustně)."""
            # Zavřít okno (Cmd+W / Ctrl+W)
            try:
                sc_close = QShortcut(QKeySequence(QKeySequence.Close), dlg)
                sc_close.setAutoRepeat(False)
                sc_close.activated.connect(dlg.close)
            except Exception:
                pass
    
            # Space = zavřít (toggle QuickLook)
            try:
                sc_space = QShortcut(QKeySequence(Qt.Key_Space), dlg)
                sc_space.setAutoRepeat(False)
                sc_space.activated.connect(dlg.close)
            except Exception:
                pass
    
            # ↑/↓ → next/prev (1) zavolej veřejné metody, (2) jinak emuluj ←/→ do aktuálního focus widgetu
            def _invoke_nav(step: int):
                # (1) pokus o volání běžných metod vieweru
                for name in (('next_image', 'prev_image') if step > 0 else ('prev_image', 'next_image')):
                    method = getattr(dlg, name[0], None)
                    if callable(method):
                        try:
                            method()
                            return
                        except Exception:
                            pass
                for name in (('next', 'previous', 'go_next', 'go_prev', 'show_next', 'show_prev',
                              'navigate_next', 'navigate_prev', '_next', '_prev') if step > 0
                             else ('previous', 'next', 'go_prev', 'go_next', 'show_prev', 'show_next',
                                   'navigate_prev', 'navigate_next', '_prev', '_next')):
                    method = getattr(dlg, name, None)
                    if callable(method):
                        try:
                            method()
                            return
                        except Exception:
                            pass
                # (2) fallback – pošli klávesu do aktuálního focus widgetu
                try:
                    target = QCoreApplication.focusWidget() or dlg
                    key = Qt.Key_Right if step > 0 else Qt.Key_Left
                    ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
                    QCoreApplication.postEvent(target, ev)
                except Exception:
                    pass
    
            try:
                sc_down = QShortcut(QKeySequence(Qt.Key_Down), dlg)
                sc_down.setAutoRepeat(True)
                sc_down.activated.connect(lambda: _invoke_nav(+1))
            except Exception:
                pass
            try:
                sc_up = QShortcut(QKeySequence(Qt.Key_Up), dlg)
                sc_up.setAutoRepeat(True)
                sc_up.activated.connect(lambda: _invoke_nav(-1))
            except Exception:
                pass
    
        try:
            # Preferuj currentItem (fokus), jinak první ze selectedItems
            item = self.file_tree.currentItem()
            if item is None:
                sel = self.file_tree.selectedItems()
                if sel:
                    item = sel[0]
            if item is None:
                return
    
            p_str = item.data(0, Qt.UserRole)
            if not p_str:
                return
            path = Path(p_str)
            if not path.exists() or not path.is_file():
                return
    
            # .HEIC/.HEIF → vlastní náhled s polygonem (už má toggle a ⌘W níže)
            if path.suffix.lower() in {".heic", ".heif"}:
                self._open_heic_preview_dialog_for_path(str(path))
                return
    
            # Je soubor uvnitř „Neroztříděné“? → sestav file_list pro prohlížeč
            import unicodedata
            def _casefold(s: str) -> str:
                return unicodedata.normalize('NFC', s).casefold()
    
            UNSORTED = {_casefold("Neroztříděné"), _casefold("Neroztridene")}
            unsorted_parent = None
            cur = path.parent
            while True:
                if _casefold(cur.name) in UNSORTED:
                    unsorted_parent = cur
                    break
                if cur == cur.parent:
                    break
                cur = cur.parent
    
            if unsorted_parent:
                exts = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif'}
                files = [p for p in unsorted_parent.iterdir() if p.is_file() and p.suffix.lower() in exts]
                files.sort(key=lambda x: x.name.lower())
                try:
                    idx = files.index(path)
                except ValueError:
                    idx = 0
                dlg = ImageViewerDialog(
                    str(path), self,
                    show_delete_button=True,
                    file_list=[str(p) for p in files],
                    current_index=idx
                )
                _wire_viewer_shortcuts(dlg)
                if hasattr(dlg, 'current_file_changed'):
                    dlg.current_file_changed.connect(self._on_viewer_current_file_changed)
                dlg.exec()
            else:
                # Jednoduchý náhled jednoho souboru
                dlg = ImageViewerDialog(str(path), self, show_delete_button=True)
                _wire_viewer_shortcuts(dlg)
                if hasattr(dlg, 'current_file_changed'):
                    dlg.current_file_changed.connect(self._on_viewer_current_file_changed)
                dlg.exec()
    
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba náhledu: {e}", "error")
            
    def copy_selected_item(self):
        """Kopírování vybraných položek přes Ctrl/Cmd+C (1 i více kusů)."""
        if not hasattr(self, 'file_tree') or self.file_tree is None:
            return
    
        items = self.file_tree.selectedItems() or []
    
        # Více položek -> hromadné kopírování
        if len(items) > 1:
            self.copy_selected_items()
            return
    
        # Jeden kus -> použij currentItem() s fallbackem na první vybranou položku
        item = self.file_tree.currentItem() or (items if items else None)
        if item is None:
            return
    
        file_path = item.data(0, Qt.UserRole)
        if file_path:
            self.copy_file_or_folder(file_path)

    def copy_selected_items(self):
        """NOVÁ FUNKCE: Uloží více vybraných souborů/složek do interní schránky"""
        try:
            items = self.file_tree.selectedItems()
            paths = []
            for it in items:
                p = it.data(0, Qt.UserRole)
                if not p:
                    continue
                pp = Path(p)
                if pp.exists():
                    paths.append(pp)

            if not paths:
                QMessageBox.information(self, "Info", "Nebyly vybrány žádné existující položky.")
                return

            # Uložit do interní schránky jako seznam
            self.clipboard_data = {
                'items': [{'source_path': str(p), 'is_dir': p.is_dir(), 'name': p.name} for p in paths],
                'operation': 'copy'
            }
            self.log_widget.add_log(f"📋 Do schránky přidáno {len(paths)} položek", "success")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při hromadném kopírování: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se připravit kopírování:\n{e}")

    def paste_to_selected_folder(self):
        """Vloží dříve zkopírované/vyjmuté položky do cílové složky (vybrané ve stromu)."""
        try:
            clip = getattr(self, 'clipboard_data', None)
            if not clip or 'paths' not in clip or not clip['paths']:
                return
            mode = clip.get('mode', 'copy')  # 'copy' | 'cut'
            src_paths = [Path(p) for p in clip['paths']]
    
            # Určit cílovou složku
            target_dir = None
            item = self.file_tree.currentItem()
            if item is not None:
                p_str = item.data(0, Qt.UserRole)
                if p_str:
                    p = Path(p_str)
                    if p.exists():
                        target_dir = p if p.is_dir() else p.parent
            if target_dir is None:
                target_dir = self.default_maps_path
    
            target_dir.mkdir(parents=True, exist_ok=True)
    
            import shutil, os
    
            def ensure_unique_path(dst: Path) -> Path:
                if not dst.exists():
                    return dst
                stem = dst.stem
                suffix = dst.suffix
                parent = dst.parent
                i = 2
                while True:
                    cand = parent / f"{stem} ({i}){suffix}"
                    if not cand.exists():
                        return cand
                    i += 1
    
            moved = 0
            copied = 0
            for sp in src_paths:
                if not sp.exists():
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"⚠️ Neexistuje: {sp.name}", "warning")
                    continue
                dst = target_dir / sp.name
                dst = ensure_unique_path(dst)
    
                try:
                    if mode == 'cut':
                        shutil.move(str(sp), str(dst))
                        moved += 1
                    else:
                        if sp.is_dir():
                            shutil.copytree(str(sp), str(dst))
                        else:
                            shutil.copy2(str(sp), str(dst))
                        copied += 1
                except Exception as e:
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"❌ Nelze přesunout/zkopírovat '{sp.name}': {e}", "error")
    
            # Po cutu vyčistit schránku (aby se omylem nepaste-ovalo podruhé)
            if mode == 'cut':
                self.clipboard_data = None
    
            # Refresh a log
            self.refresh_file_tree()
            if hasattr(self, 'log_widget'):
                if mode == 'cut':
                    self.log_widget.add_log(f"✅ Přesunuto: {moved} položek → {target_dir.name}", "success")
                else:
                    self.log_widget.add_log(f"✅ Zkopírováno: {copied} položek → {target_dir.name}", "success")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při vkládání: {e}", "error")
                
    def create_root_folder(self):
        """Vytvoří novou složku v kořeni 'mapky lokací' (self.default_maps_path)."""
        try:
            from PySide6.QtWidgets import QInputDialog, QMessageBox
            name, ok = QInputDialog.getText(self, "Nová složka (kořen)", "Název složky:")
            if not ok or not name.strip():
                return
            name = name.strip()
            # Očistit nebezpečné znaky
            invalid = set('/\\:*?"<>|')
            if any(ch in invalid for ch in name):
                QMessageBox.warning(self, "Neplatný název", "Název obsahuje nepovolené znaky (/ \\ : * ? \" < > |).")
                return
    
            target = self.default_maps_path / name
            if target.exists():
                # Najít unikátní název
                i = 2
                while True:
                    cand = self.default_maps_path / f"{name} ({i})"
                    if not cand.exists():
                        target = cand
                        break
                    i += 1
    
            target.mkdir(parents=True, exist_ok=False)
    
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"📁 Vytvořena složka v kořeni: {target.name}", "success")
    
            # Refresh a zvolit novou složku
            self.refresh_file_tree()
            self._select_path_in_tree(str(target))
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při vytváření složky: {e}", "error")


    def rename_file_or_folder(self, source_path: str):
        """Přejmenování souboru nebo složky v rámci stejného nadřazeného adresáře"""
        try:
            src = Path(source_path)
            if not src.exists():
                QMessageBox.warning(self, "Chyba", "Položka neexistuje!")
                return

            # Výchozí navržený název (bez zásahu do přípony)
            suggested = src.name

            # Dotaz na nový název
            new_name, ok = QInputDialog.getText(
                self,
                "Přejmenovat",
                f"Zadejte nový název pro:\n{src.name}",
                QLineEdit.Normal,
                suggested
            )
            if not ok:
                return

            new_name = new_name.strip()
            if not new_name:
                QMessageBox.warning(self, "Chyba", "Název nesmí být prázdný!")
                return

            # Zakázané znaky ve jménu souboru/složky
            invalid = ['<', '>', ':', '"', '|', '?', '*', '/', '\\']
            if any(ch in new_name for ch in invalid):
                QMessageBox.warning(self, "Chyba", f"Název obsahuje nepovolené znaky:\n{', '.join(invalid)}")
                return

            # Automatické doplnění přípony, pokud uživatel u souboru neuvedl žádnou
            final_name = new_name
            if src.is_file() and Path(new_name).suffix == "" and src.suffix:
                final_name = f"{new_name}{src.suffix}"

            dst = src.parent / final_name

            # Pokud je cílový název identický, nic nedělat
            if dst == src:
                return

            # Kolize názvů
            if dst.exists():
                # Cross‑platform: soubory lze přepsat Path.replace(), složky bezpečně nepřepisujeme
                if dst.is_dir():
                    QMessageBox.warning(self, "Chyba", "Složka se stejným názvem již existuje, přepsání není povoleno.")
                    return

                reply = QMessageBox.question(
                    self,
                    "Položka existuje",
                    f"Soubor '{final_name}' již existuje.\nChcete jej přepsat?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

                # Přepsání souboru – atomicky a přenositelně (Windows/Unix)
                try:
                    src.replace(dst)  # Path.replace = atomic/overwrite-friendly přes os.replace
                except Exception as e:
                    QMessageBox.critical(self, "Chyba", f"Nepodařilo se přepsat soubor:\n{e}")
                    return
            else:
                # Běžné přejmenování (bez přepsání)
                try:
                    src.rename(dst)
                except Exception as e:
                    QMessageBox.critical(self, "Chyba", f"Nepodařilo se přejmenovat:\n{e}")
                    return

            # Refresh a zvýraznění nové položky
            self.refresh_file_tree()
            try:
                if hasattr(self, 'expand_and_select_path'):
                    self.expand_and_select_path(dst)
                elif dst.is_dir():
                    # fallback – existující pomocník pro složky
                    self.expand_and_select_folder(dst)
            except Exception:
                pass

            item_type = "Složka" if dst.is_dir() else "Soubor"
            self.log_widget.add_log(f"✏️ {item_type} přejmenována/přejmenován na '{dst.name}'", "success")

        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při přejmenování: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se přejmenovat:\n{e}")
            
    def _select_path_in_tree(self, path_str: str):
        """Najde a vybere položku ve stromu podle uložené cesty v Qt.UserRole."""
        try:
            target = str(Path(path_str))
            def walk(item=None):
                if item is None:
                    for i in range(self.file_tree.topLevelItemCount()):
                        if walk(self.file_tree.topLevelItem(i)):
                            return True
                    return False
                p_str = item.data(0, Qt.UserRole)
                if p_str and str(Path(p_str)) == target:
                    self.file_tree.setCurrentItem(item)
                    self.file_tree.scrollToItem(item)
                    return True
                for j in range(item.childCount()):
                    if walk(item.child(j)):
                        return True
                return False
            walk(None)
        except Exception:
            pass

    def _show_rename_dialog(self, parent_path, initial_stem: str, suffix: str):
        """
        Zobrazí jednotný QInputDialog pro přejmenování se stejnou velikostí jako z kontextového menu.
        Vrací nový stem (bez přípony) nebo None při zrušení.
        """
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        from PySide6.QtCore import Qt
    
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Přejmenovat soubor")
        dlg.setLabelText("Nový název (bez přípony):")
        dlg.setInputMode(QInputDialog.TextInput)
        dlg.setTextValue(initial_stem)
        dlg.setOkButtonText("Přejmenovat")
        dlg.setCancelButtonText("Zrušit")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setSizeGripEnabled(True)
    
        # Sjednocená velikost (šířka/ výška) a minimální šířka vstupu
        dlg.resize(640, 160)
        try:
            editor = dlg.findChild(QLineEdit)
            if editor:
                editor.setMinimumWidth(560)
                # Předvybrat pouze stem (bez přípony) pro rychlou editaci
                editor.setSelection(0, len(initial_stem))
                editor.setCursorPosition(len(initial_stem))
        except Exception:
            pass
    
        if dlg.exec():
            new_stem = dlg.textValue().strip()
            if new_stem:
                return new_stem
        return None

    def expand_and_select_path(self, target_path):
        """Rozbalí strom k dané cestě a vybere ji (funguje pro soubory i složky)."""
        try:
            target = Path(target_path).resolve()

            def find_item_recursive(parent_item):
                # Prohledání potomků aktuální položky
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    item_path_str = child.data(0, Qt.UserRole)
                    if item_path_str:
                        item_path = Path(item_path_str).resolve()
                        if item_path == target:
                            return child
                        if target.is_relative_to(item_path) or str(target).startswith(str(item_path)):
                            found = find_item_recursive(child)
                            if found:
                                return found
                return None

            # Prohledání top-level položek
            for i in range(self.file_tree.topLevelItemCount()):
                top_item = self.file_tree.topLevelItem(i)
                item_path_str = top_item.data(0, Qt.UserRole)
                if not item_path_str:
                    continue
                item_path = Path(item_path_str).resolve()
                if item_path == target:
                    self.file_tree.setCurrentItem(top_item)
                    self.file_tree.scrollToItem(top_item)
                    return
                # Pokus o nalezení v potomcích
                found = find_item_recursive(top_item)
                if found:
                    # Rozbalení nadřazených
                    parent = found.parent()
                    while parent:
                        parent.setExpanded(True)
                        parent = parent.parent()
                    self.file_tree.setCurrentItem(found)
                    self.file_tree.scrollToItem(found)
                    return
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Nelze vybrat položku po přejmenování: {e}", "warning")

    def copy_file_or_folder(self, source_path):
        """UPRAVENÁ FUNKCE: Kopírování souboru nebo složky do schránky"""
        try:
            source_obj = Path(source_path)
            
            if not source_obj.exists():
                QMessageBox.warning(self, "Chyba", "Zdrojový soubor nebo složka neexistuje!")
                return
            
            # Uložení do interní schránky
            self.clipboard_data = {
                'source_path': str(source_obj),
                'is_dir': source_obj.is_dir(),
                'name': source_obj.name,
                'operation': 'copy'
            }
            
            item_type = "složka" if source_obj.is_dir() else "soubor"
            icon = "📁" if source_obj.is_dir() else "📄"
            
            self.log_widget.add_log(f"📋 {icon} '{source_obj.name}' zkopírován{'' if source_obj.is_dir() else ''} do schránky", "success")
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při kopírování: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se zkopírovat:\n{e}")

    def paste_file_or_folder(self, target_folder_path):
        """NOVÁ VERZE: Podpora vložení jednoho i více objektů ze schránky (bez chyb „…“ a s bezpečnostmi)."""
        try:
            if not hasattr(self, 'clipboard_data') or not self.clipboard_data:
                QMessageBox.warning(self, "Chyba", "Schránka je prázdná!")
                return
    
            target_folder = Path(target_folder_path)
            if not target_folder.exists() or not target_folder.is_dir():
                QMessageBox.warning(self, "Chyba", "Cílová složka neexistuje!")
                return
    
            import shutil
    
            def find_free_name(base_name: str, is_file: bool, extension: str = "") -> Path:
                """
                Vrátí volnou cestu v cílové složce podle schématu „_kopie“, „_kopie_2“, …
                base_name je stem (u souboru) nebo název složky, extension je přípona včetně tečky.
                """
                candidate = target_folder / (base_name + (extension if is_file else ""))
                if not candidate.exists():
                    return candidate
                counter = 1
                while True:
                    if is_file:
                        new_name = f"{base_name}_kopie{extension}" if counter == 1 else f"{base_name}_kopie_{counter}{extension}"
                    else:
                        new_name = f"{base_name}_kopie" if counter == 1 else f"{base_name}_kopie_{counter}"
                    candidate = target_folder / new_name
                    if not candidate.exists():
                        return candidate
                    counter += 1
                    if counter > 1000:
                        raise RuntimeError("Nelze najít volný název pro kopii.")
    
            # === Více položek ve schránce ===
            if 'items' in self.clipboard_data and isinstance(self.clipboard_data['items'], list):
                items = self.clipboard_data['items']
                if not items:
                    QMessageBox.warning(self, "Chyba", "Schránka neobsahuje žádné položky!")
                    return
    
                first_created = None
                ok = 0
                fail = 0
    
                for it in items:
                    try:
                        source_path = Path(it['source_path'])
                        if not source_path.exists():
                            fail += 1
                            continue
    
                        # Zákaz kopírování složky do sebe/potomka
                        try:
                            if source_path.is_dir() and target_folder.resolve().is_relative_to(source_path.resolve()):
                                if hasattr(self, 'log_widget'):
                                    self.log_widget.add_log(f"⚠️ Nelze kopírovat složku do jejího potomka: {source_path.name}", "warning")
                                fail += 1
                                continue
                        except Exception:
                            if str(target_folder.resolve()).startswith(str(source_path.resolve())):
                                if hasattr(self, 'log_widget'):
                                    self.log_widget.add_log(f"⚠️ Nelze kopírovat složku do jejího potomka: {source_path.name}", "warning")
                                fail += 1
                                continue
    
                        if source_path.is_file():
                            dst = find_free_name(source_path.stem, True, source_path.suffix) \
                                  if (target_folder / source_path.name).exists() else (target_folder / source_path.name)
                            shutil.copy2(source_path, dst)
                        else:
                            dst = find_free_name(source_path.name, False) \
                                  if (target_folder / source_path.name).exists() else (target_folder / source_path.name)
                            shutil.copytree(source_path, dst)
    
                        if first_created is None:
                            first_created = dst
                        ok += 1
                    except Exception as e:
                        fail += 1
                        if hasattr(self, 'log_widget'):
                            self.log_widget.add_log(f"❌ Chyba při kopírování '{it.get('name','?')}': {e}", "error")
    
                # Obnovení a zvýraznění
                self.refresh_file_tree()
                try:
                    from PySide6.QtCore import QTimer
                    if first_created:
                        QTimer.singleShot(100, lambda: self.expand_and_select_folder(first_created if first_created.is_dir() else first_created.parent))
                except Exception:
                    pass
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"📦 Vícenásobné vložení: OK={ok}, FAIL={fail}", "success")
                return
    
            # === Jedna položka ve schránce ===
            source_path = Path(self.clipboard_data['source_path'])
            if not source_path.exists():
                QMessageBox.warning(self, "Chyba", "Zdrojový soubor již neexistuje!")
                self.clipboard_data = None
                return
    
            created = None
            if source_path.is_file():
                dst = target_folder / source_path.name
                if dst.exists():
                    dst = find_free_name(source_path.stem, True, source_path.suffix)
                shutil.copy2(source_path, dst)
                created = dst
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"📄 Soubor '{source_path.name}' vložen jako '{dst.name}'", "success")
            else:
                # Zákaz kopírování složky do sebe/potomka
                try:
                    if target_folder.resolve().is_relative_to(source_path.resolve()):
                        if hasattr(self, 'log_widget'):
                            self.log_widget.add_log(f"⚠️ Nelze kopírovat složku do jejího potomka: {source_path.name}", "warning")
                        return
                except Exception:
                    if str(target_folder.resolve()).startswith(str(source_path.resolve())):
                        if hasattr(self, 'log_widget'):
                            self.log_widget.add_log(f"⚠️ Nelze kopírovat složku do jejího potomka: {source_path.name}", "warning")
                        return
    
                dst = target_folder / source_path.name
                if dst.exists():
                    dst = find_free_name(source_path.name, False)
                shutil.copytree(source_path, dst)
                created = dst
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"📁 Složka '{source_path.name}' vložena jako '{dst.name}'", "success")
    
            self.refresh_file_tree()
            try:
                from PySide6.QtCore import QTimer
                if created is not None:
                    QTimer.singleShot(100, lambda: self.expand_and_select_folder(created))
            except Exception:
                pass
    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při vkládání: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se vložit:\n{e}")

    def create_subfolder(self, parent_folder_path):
        """NOVÁ FUNKCE: Vytvoření nové podsložky"""
        try:
            parent_obj = Path(parent_folder_path)
            
            if not parent_obj.exists() or not parent_obj.is_dir():
                QMessageBox.warning(self, "Chyba", "Nadřazená složka neexistuje!")
                return
            
            # Dialog pro zadání názvu nové složky
            folder_name, ok = QInputDialog.getText(
                self,
                "Vytvořit novou podsložku",
                f"Zadejte název nové podsložky v:\n{parent_obj}\n\nNázev složky:",
                QLineEdit.Normal,
                "Nová složka"
            )
            
            if not ok or not folder_name.strip():
                return  # Uživatel zrušil nebo nezadal název
            
            # Vyčištění názvu
            folder_name = folder_name.strip()
            
            # Kontrola platnosti názvu
            invalid_chars = ['<', '>', ':', '"', '|', '?', '*', '/', '\\']
            if any(char in folder_name for char in invalid_chars):
                QMessageBox.warning(
                    self,
                    "Neplatný název",
                    f"Název složky obsahuje nepovolené znaky:\n{', '.join(invalid_chars)}"
                )
                return
            
            # Vytvoření cesty k nové složce
            new_folder_path = parent_obj / folder_name
            
            # Kontrola, zda složka již neexistuje
            if new_folder_path.exists():
                reply = QMessageBox.question(
                    self,
                    "Složka již existuje",
                    f"Složka '{folder_name}' již existuje.\n"
                    f"Chcete vytvořit složku s jiným názvem?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    # Hledání volného názvu
                    counter = 1
                    while True:
                        new_name = f"{folder_name}_{counter}"
                        new_folder_path = parent_obj / new_name
                        
                        if not new_folder_path.exists():
                            folder_name = new_name
                            break
                        
                        counter += 1
                        
                        # Ochrana před nekonečnou smyčkou
                        if counter > 1000:
                            QMessageBox.warning(self, "Chyba", "Nelze najít volný název pro složku!")
                            return
                else:
                    return
            
            # Vytvoření složky
            new_folder_path.mkdir(parents=True, exist_ok=False)
            
            self.log_widget.add_log(f"📁➕ Vytvořena nová podsložka '{folder_name}' v '{parent_obj.name}'", "success")
            
            # Obnovení stromu
            self.refresh_file_tree()
            
            # Rozbalení nadřazené složky a zvýraznění nové složky
            QTimer.singleShot(100, lambda: self.expand_and_select_folder(new_folder_path))
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při vytváření podsložky: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se vytvořit podsložku:\n{e}")

    def expand_and_select_folder(self, folder_path):
        """POMOCNÁ FUNKCE: Rozbalení stromu a výběr konkrétní složky"""
        try:
            folder_obj = Path(folder_path)
            
            def find_item_recursive(parent_item, target_path):
                """Rekurzivní hledání položky ve stromu"""
                if parent_item is None:
                    # Hledání v top-level items
                    for i in range(self.file_tree.topLevelItemCount()):
                        item = self.file_tree.topLevelItem(i)
                        result = find_item_recursive(item, target_path)
                        if result:
                            return result
                else:
                    # Kontrola aktuální položky
                    item_path = parent_item.data(0, Qt.UserRole)
                    if item_path and Path(item_path) == target_path:
                        return parent_item
                    
                    # Hledání v potomcích
                    for i in range(parent_item.childCount()):
                        child = parent_item.child(i)
                        result = find_item_recursive(child, target_path)
                        if result:
                            return result
                
                return None
            
            # Najití položky ve stromu
            target_item = find_item_recursive(None, folder_obj)
            
            if target_item:
                # Rozbalení nadřazených složek
                parent = target_item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                
                # Výběr a zvýraznění nové složky
                self.file_tree.setCurrentItem(target_item)
                self.file_tree.scrollToItem(target_item)
                
        except Exception as e:
            self.log_widget.add_log(f"⚠️ Nepodařilo se najít novou složku ve stromu: {e}", "warning")

    def delete_file_or_folder(self, file_path):
        """UPRAVENÁ FUNKCE: Smazání souboru nebo složky s lepším potvrzením"""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                QMessageBox.warning(self, "Chyba", "Soubor nebo složka neexistuje!")
                return
            
            # Určení typu a textu
            if path_obj.is_dir():
                item_type = "složku"
                icon = "📁"
                # Počítání obsahu složky
                try:
                    items = list(path_obj.rglob('*'))
                    files_count = len([item for item in items if item.is_file()])
                    dirs_count = len([item for item in items if item.is_dir()])
                    content_info = f"\nObsah: {files_count} souborů, {dirs_count} podsložek"
                except:
                    content_info = "\nObsah: nelze určit"
            else:
                item_type = "soubor"
                icon = "📄"
                # Velikost souboru
                try:
                    size = path_obj.stat().st_size
                    if size < 1024:
                        size_info = f"\nVelikost: {size} B"
                    elif size < 1024 * 1024:
                        size_info = f"\nVelikost: {size / 1024:.1f} KB"
                    else:
                        size_info = f"\nVelikost: {size / (1024 * 1024):.1f} MB"
                except:
                    size_info = "\nVelikost: nelze určit"
                content_info = size_info
            
            # Potvrzovací dialog
            reply = QMessageBox.question(
                self,
                f"Smazat {item_type}",
                f"Opravdu chcete smazat {item_type}:\n"
                f"'{path_obj.name}'{content_info}\n\n"
                f"Cesta: {path_obj.parent}\n\n"
                f"⚠️ Tato akce je nevratná!",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No  # Výchozí je "Ne" pro bezpečnost
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # Smazání
            if path_obj.is_dir():
                import shutil
                shutil.rmtree(path_obj)
                self.log_widget.add_log(f"🗑️ Složka '{path_obj.name}' byla smazána", "success")
            else:
                path_obj.unlink()
                self.log_widget.add_log(f"🗑️ Soubor '{path_obj.name}' byl smazán", "success")
            
            # Obnovení stromu
            self.refresh_file_tree()
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při mazání: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se smazat {item_type}:\n{e}")

    def delete_selected_items(self):
        """Hromadné smazání vybraných položek (soubory i složky) se zamezením duplicit podle podcest."""
        try:
            items = self.file_tree.selectedItems()
            if not items:
                QMessageBox.information(self, "Info", "Nebyly vybrány žádné položky ke smazání.")
                return
    
            # 1) Posbírat platné cesty
            paths = []
            for it in items:
                p = it.data(0, Qt.UserRole)
                if not p:
                    continue
                pp = Path(p)
                if pp.exists():
                    paths.append(pp)
    
            if not paths:
                QMessageBox.information(self, "Info", "Žádná z vybraných položek neexistuje.")
                return
    
            # 2) Dedup: pokud je vybraná složka, smažeme ji a ne jednotlivé potomky
            #    -> odstranit všechny cesty, které jsou potomky jiné vybrané složky
            # Seřadit podle délky (kratší/výše v hierarchii dřív)
            paths = sorted(set(p.resolve() for p in paths), key=lambda x: (len(str(x)), str(x)))
            filtered = []
            for p in paths:
                # je p potomkem některé z již přidaných?
                is_child = False
                for parent in filtered:
                    # kompatibilita pro Python < 3.9 bez is_relative_to
                    try:
                        if p.is_relative_to(parent):
                            is_child = True
                            break
                    except AttributeError:
                        if str(p).startswith(str(parent) + os.sep):
                            is_child = True
                            break
                if not is_child:
                    filtered.append(p)
    
            # 3) Připravit text potvrzení
            files = [p for p in filtered if p.is_file()]
            dirs = [p for p in filtered if p.is_dir()]
            total = len(filtered)
    
            sample_lines = [f"• {p.name}" for p in filtered[:8]]
            if total > 8:
                sample_lines.append(f"… a dalších {total - 8} položek")
    
            confirm_text = (
                "Opravdu chcete smazat vybrané položky?\n\n"
                f"Soubory: {len(files)}\nSložky: {len(dirs)}\nCelkem: {total}\n\n" +
                "\n".join(sample_lines) +
                "\n\n⚠️ Tato akce je nevratná!"
            )
            reply = QMessageBox.question(self, "Potvrdit smazání", confirm_text,
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
    
            # 4) Mazání – pořadí: soubory → složky (složky mohou být neempty)
            ok = 0
            fail = 0
            import shutil
            for p in files:
                try:
                    p.unlink()
                    ok += 1
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"🗑️ Smazán soubor: {p.name}", "success")
                except Exception as e:
                    fail += 1
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"❌ Nelze smazat soubor '{p.name}': {e}", "error")
    
            # Složky maž pomocí rmtree (bez ohledu na obsah)
            for d in dirs:
                try:
                    shutil.rmtree(d)
                    ok += 1
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"🗑️ Smazána složka: {d.name}", "success")
                except Exception as e:
                    fail += 1
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"❌ Nelze smazat složku '{d.name}': {e}", "error")
    
            # 5) Obnovit strom a informovat
            self.refresh_file_tree()
            self.log_widget.add_log(f"📦 Hromadné smazání: Smazáno {ok}, Nezdařilo se {fail}", "success")  # [1]
    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při hromadném mazání: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se smazat vybrané položky:\n{e}")

    def show_file_in_system(self, file_path):
        """UPRAVENÁ FUNKCE: Zobrazení souboru v systémovém prohlížeči"""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                QMessageBox.warning(self, "Chyba", "Soubor neexistuje!")
                return
            
            if not path_obj.is_file():
                QMessageBox.warning(self, "Chyba", "Tato funkce je dostupná pouze pro soubory!")
                return
            
            import platform
            import subprocess
            
            system = platform.system()
            
            try:
                if system == "Darwin":  # macOS
                    subprocess.run(["open", "-R", str(path_obj)], check=True)
                elif system == "Windows":
                    subprocess.run(["explorer", "/select,", str(path_obj)], check=True)
                else:  # Linux a ostatní
                    # Pokus o různé file managery
                    file_managers = ["nautilus", "dolphin", "thunar", "pcmanfm", "nemo"]
                    success = False
                    
                    for fm in file_managers:
                        try:
                            subprocess.run([fm, "--select", str(path_obj)], check=True)
                            success = True
                            break
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            continue
                    
                    if not success:
                        # Fallback - otevření nadřazené složky
                        subprocess.run(["xdg-open", str(path_obj.parent)], check=True)
                
                self.log_widget.add_log(f"👁️ Soubor '{path_obj.name}' zobrazen v systému", "info")
                
            except subprocess.CalledProcessError as e:
                raise Exception(f"Chyba při spouštění systémového příkazu: {e}")
            except FileNotFoundError:
                raise Exception("Systémový file manager nebyl nalezen")
                
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při zobrazování souboru: {e}", "error")
            QMessageBox.warning(self, "Chyba", f"Nepodařilo se zobrazit soubor v systému:\n{e}")

    def open_file_location(self, file_path):
        """UPRAVENÁ FUNKCE: Otevření umístění souboru/složky"""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                QMessageBox.warning(self, "Chyba", "Soubor nebo složka neexistuje!")
                return
            
            # Určení cílové složky
            if path_obj.is_dir():
                target_folder = path_obj
            else:
                target_folder = path_obj.parent
            
            import platform
            import subprocess
            
            system = platform.system()
            
            try:
                if system == "Darwin":  # macOS
                    subprocess.run(["open", str(target_folder)], check=True)
                elif system == "Windows":
                    subprocess.run(["explorer", str(target_folder)], check=True)
                else:  # Linux a ostatní
                    subprocess.run(["xdg-open", str(target_folder)], check=True)
                
                self.log_widget.add_log(f"📂 Otevřena složka: {target_folder.name}", "info")
                
            except subprocess.CalledProcessError as e:
                raise Exception(f"Chyba při spouštění systémového příkazu: {e}")
            except FileNotFoundError:
                raise Exception("Systémový file manager nebyl nalezen")
                
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při otevírání složky: {e}", "error")
            QMessageBox.warning(self, "Chyba", f"Nepodařilo se otevřít složku:\n{e}")
            
    def open_unsorted_browser(self):
        """Otevře prohlížeč všech obrázků ve složce 'Neroztříděné' vzhledem k aktuální výstupní složce (bez zdvojení)."""
        try:
            import unicodedata, re
            base = Path(self.input_output_dir.text().strip()).resolve()
    
            def norm(s: str) -> str:
                return unicodedata.normalize('NFC', s).casefold()
    
            unsorted_names = ["Neroztříděné", "Neroztridene"]
    
            # Najdi složku Neroztříděné (viz výše)
            if any(norm(base.name) == norm(n) for n in unsorted_names):
                folder = base
            else:
                found = None
                for n in unsorted_names:
                    cand = base / n
                    if cand.exists() and cand.is_dir():
                        found = cand
                        break
                folder = found if found is not None else base
    
            if not folder.exists() or not folder.is_dir():
                QMessageBox.information(self, "Info", f"Složka neexistuje:\n{folder}")
                return
    
            # Obrázky
            exts = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif'}
            files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
            if not files:
                QMessageBox.information(self, "Info", f"Ve složce není žádný podporovaný obrázek:\n{folder}")
                return
    
            files.sort(key=lambda x: x.name.lower())
    
            # Urči startovní index podle aktuálního výběru v tree:
            start_idx = 0
            try:
                sel_items = self.file_tree.selectedItems() or []
                # 1) pokud je vybraný soubor z files → použij jeho index
                for it in sel_items:
                    p_str = it.data(0, Qt.UserRole)
                    if not p_str:
                        continue
                    p = Path(p_str)
                    if p.is_file():
                        for i, f in enumerate(files):
                            try:
                                if f.resolve() == p.resolve():
                                    start_idx = i
                                    raise StopIteration
                            except Exception:
                                pass
                # 2) pokud je vybraná složka, zkus první soubor v ní
                for it in sel_items:
                    p_str = it.data(0, Qt.UserRole)
                    if not p_str:
                        continue
                    p = Path(p_str)
                    if p.is_dir():
                        for i, f in enumerate(files):
                            try:
                                if f.parent.resolve() == p.resolve():
                                    start_idx = i
                                    raise StopIteration
                            except Exception:
                                pass
            except StopIteration:
                pass
            except Exception:
                pass
    
            from gui.image_viewer import ImageViewerDialog
            from PySide6.QtCore import Qt, QEvent, QCoreApplication
            from PySide6.QtGui import QKeySequence, QShortcut, QKeyEvent
    
            dialog = ImageViewerDialog(
                files[start_idx], self, show_delete_button=True,
                file_list=files, current_index=start_idx, close_on_space=True
            )
    
            # stejné mapování zkratek jako jinde
            def _wire_common_shortcuts(dlg):
                try:
                    sc_close = QShortcut(QKeySequence(QKeySequence.Close), dlg)
                    sc_close.setAutoRepeat(False)
                    sc_close.activated.connect(dlg.close)
                except Exception:
                    pass
                def _post_key(key):
                    try:
                        ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
                        QCoreApplication.postEvent(dlg, ev)
                    except Exception:
                        pass
                try:
                    sc_down = QShortcut(QKeySequence(Qt.Key_Down), dlg)
                    sc_down.setAutoRepeat(True)
                    sc_down.activated.connect(lambda: _post_key(Qt.Key_Right))
                except Exception:
                    pass
                try:
                    sc_up = QShortcut(QKeySequence(Qt.Key_Up), dlg)
                    sc_up.setAutoRepeat(True)
                    sc_up.activated.connect(lambda: _post_key(Qt.Key_Left))
                except Exception:
                    pass
                try:
                    sc_space_close = QShortcut(QKeySequence(Qt.Key_Space), dlg)
                    sc_space_close.setAutoRepeat(False)
                    sc_space_close.activated.connect(dlg.close)
                except Exception:
                    pass
    
            _wire_common_shortcuts(dialog)
    
            if hasattr(dialog, 'current_file_changed'):
                dialog.current_file_changed.connect(self._on_viewer_current_file_changed)
            if hasattr(dialog, 'file_deleted'):
                dialog.file_deleted.connect(lambda _: self.refresh_file_tree())
            if hasattr(dialog, 'request_auto_fit'):
                dialog.request_auto_fit()
    
            dialog.exec_() if hasattr(dialog, 'exec_') else dialog.exec()
    
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nelze otevřít prohlížeč:\n{e}")

    def show_file_info(self, file_path):
        """UPRAVENÁ FUNKCE: Zobrazení podrobných informací o souboru/složce"""
        try:
            path_obj = Path(file_path)
            
            if not path_obj.exists():
                QMessageBox.warning(self, "Chyba", "Soubor nebo složka neexistuje!")
                return
            
            # Získání statistik
            stat_info = path_obj.stat()
            
            # Základní informace
            info_lines = []
            info_lines.append(f"📍 Název: {path_obj.name}")
            info_lines.append(f"📂 Umístění: {path_obj.parent}")
            info_lines.append(f"🔗 Celá cesta: {path_obj}")
            
            # Typ
            if path_obj.is_dir():
                info_lines.append(f"📁 Typ: Složka")
                
                # Obsah složky
                try:
                    items = list(path_obj.iterdir())
                    files = [item for item in items if item.is_file()]
                    dirs = [item for item in items if item.is_dir()]
                    
                    info_lines.append(f"📊 Obsah:")
                    info_lines.append(f"   • Souborů: {len(files)}")
                    info_lines.append(f"   • Podsložek: {len(dirs)}")
                    info_lines.append(f"   • Celkem položek: {len(items)}")
                    
                    # Celková velikost (pouze přímý obsah)
                    total_size = 0
                    for file in files:
                        try:
                            total_size += file.stat().st_size
                        except:
                            pass
                    
                    if total_size > 0:
                        if total_size < 1024:
                            size_str = f"{total_size} B"
                        elif total_size < 1024 * 1024:
                            size_str = f"{total_size / 1024:.1f} KB"
                        else:
                            size_str = f"{total_size / (1024 * 1024):.1f} MB"
                        info_lines.append(f"💾 Velikost souborů: {size_str}")
                    
                except Exception as e:
                    info_lines.append(f"⚠️ Obsah: Nelze načíst ({e})")
            else:
                info_lines.append(f"📄 Typ: Soubor")
                info_lines.append(f"🏷️ Přípona: {path_obj.suffix or 'žádná'}")
                
                # Velikost souboru
                size = stat_info.st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                info_lines.append(f"💾 Velikost: {size_str}")
            
            # Časové údaje
            import datetime
            
            try:
                created_time = datetime.datetime.fromtimestamp(stat_info.st_ctime)
                modified_time = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                accessed_time = datetime.datetime.fromtimestamp(stat_info.st_atime)
                
                info_lines.append(f"🕐 Časové údaje:")
                info_lines.append(f"   • Vytvořeno: {created_time.strftime('%d.%m.%Y %H:%M:%S')}")
                info_lines.append(f"   • Změněno: {modified_time.strftime('%d.%m.%Y %H:%M:%S')}")
                info_lines.append(f"   • Naposledy otevřeno: {accessed_time.strftime('%d.%m.%Y %H:%M:%S')}")
            except Exception as e:
                info_lines.append(f"⚠️ Časové údaje: Nelze načíst ({e})")
            
            # Oprávnění (pouze na Unix systémech)
            try:
                import stat
                mode = stat_info.st_mode
                permissions = []
                
                # Oprávnění vlastníka
                if mode & stat.S_IRUSR: permissions.append("r")
                else: permissions.append("-")
                if mode & stat.S_IWUSR: permissions.append("w")
                else: permissions.append("-")
                if mode & stat.S_IXUSR: permissions.append("x")
                else: permissions.append("-")
                
                # Oprávnění skupiny
                if mode & stat.S_IRGRP: permissions.append("r")
                else: permissions.append("-")
                if mode & stat.S_IWGRP: permissions.append("w")
                else: permissions.append("-")
                if mode & stat.S_IXGRP: permissions.append("x")
                else: permissions.append("-")
                
                # Oprávnění ostatních
                if mode & stat.S_IROTH: permissions.append("r")
                else: permissions.append("-")
                if mode & stat.S_IWOTH: permissions.append("w")
                else: permissions.append("-")
                if mode & stat.S_IXOTH: permissions.append("x")
                else: permissions.append("-")
                
                perm_str = "".join(permissions)
                info_lines.append(f"🔐 Oprávnění: {perm_str}")
                
            except:
                pass  # Oprávnění nejsou dostupná na všech systémech
            
            # Zobrazení informací
            info_text = "\n".join(info_lines)
            
            # Vytvoření vlastního dialogu s možností kopírování textu
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Vlastnosti - {path_obj.name}")
            dialog.setMinimumSize(500, 400)
            dialog.setModal(True)
            
            layout = QVBoxLayout(dialog)
            
            # Text area s informacemi
            text_edit = QTextEdit()
            text_edit.setPlainText(info_text)
            text_edit.setReadOnly(True)
            text_edit.setFont(QFont("Courier", 10))  # Monospace font pro lepší zarovnání
            layout.addWidget(text_edit)
            
            # Tlačítka
            button_layout = QHBoxLayout()
            
            copy_button = QPushButton("📋 Kopírovat do schránky")
            copy_button.clicked.connect(lambda: QApplication.clipboard().setText(info_text))
            button_layout.addWidget(copy_button)
            
            button_layout.addStretch()
            
            close_button = QPushButton("✅ Zavřít")
            close_button.clicked.connect(dialog.accept)
            close_button.setDefault(True)
            button_layout.addWidget(close_button)
            
            layout.addLayout(button_layout)
            
            # Zobrazení dialogu
            dialog.exec()
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při zobrazování informací: {e}", "error")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se načíst informace o souboru:\n{e}")

    def on_file_clicked(self, item, column):
        """NOVÁ FUNKCE: Kliknutí na soubor"""
        file_path = item.data(0, Qt.UserRole)
        if file_path:
            self.log_widget.add_log(f"📁 Vybrán soubor: {Path(file_path).name}", "info")

    def on_file_double_clicked(self, item, column):
        """UPRAVENÁ FUNKCE: Dvojklik – doplní ID/Popis a nově i GPS+Zoom z názvu, případně EXIF, spustí náhled."""
        file_path = item.data(0, Qt.UserRole)
        if not file_path:
            return
    
        path_obj = Path(file_path)
    
        # Složka: jen rozbalit
        if not path_obj.is_file():
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"📁 Rozbalení složky: {path_obj.name}", "info")
            return
    
        suffix = path_obj.suffix.lower()
        filename = path_obj.name
    
        # 🔄 NOVĚ: rozliš, zda jde o lokační mapu – u ní NEMĚNIT vstupní soubor (aby se nenačetl polygon)
        try:
            is_location_map = self.is_location_map_image(filename)
        except Exception:
            is_location_map = False
    
        # Původní chování: vyplnit vstup a ID/Popis (ALE: pro lokační mapy NEMĚNIT vstupní soubor)
        if not is_location_map:
            self.input_photo.setText(str(path_obj))
        else:
            # Záměrně nezasahujeme do self.input_photo, aby se z PNG nenačetl AOI_POLYGON do nové mapy
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("↪️ Dvojklik na lokační mapu: vstupní soubor ponechán beze změny (polygon se nenačte)", "info")
    
        if suffix in ['.heic', '.heif', '.jpg', '.jpeg', '.png', '.tiff']:
            if is_location_map:
                self.handle_location_map_image(path_obj, filename)
            elif suffix in ['.heic', '.heif']:
                self.handle_gps_photo(path_obj, filename)
            else:
                self.handle_regular_image(path_obj, filename)
        else:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"📄 Vybrán soubor: {path_obj.name}", "info")
            self.extract_location_info_from_filename(filename)
    
        # 🆕 DOPLNĚNO: načtení příznaku anonymizace z PNG metadat do GUI checkboxu
        try:
            if suffix == '.png':
                self._apply_anonym_flag_from_png_to_gui(str(path_obj))
        except Exception:
            # tichý fallback – nic dalšího neměníme
            pass
    
        # NOVÉ: Pokus o GPS z názvu (CZ/EN), jinak z EXIF a spuštění náhledu
        got_gps = False
        try:
            got_gps = self.extract_gps_from_filename(filename)
        except Exception:
            got_gps = False
    
        if not got_gps and suffix in ['.heic', '.heif', '.jpg', '.jpeg', '.tiff']:
            try:
                got_gps = self.extract_gps_from_exif(path_obj)
            except Exception:
                got_gps = False
    
        if not got_gps and hasattr(self, 'log_widget'):
            self.log_widget.add_log("ℹ️ GPS z názvu/EXIF nenalezeny – lze zadat ručně v záložce GPS", "info")
    
        # Aktualizace parsovaného labelu i při změnách z názvu
        try:
            self.test_coordinate_parsing()
        except Exception:
            pass
    
        # ──────────────────────────────────────────────────────────────────────────
        # 🆕 DOPLNĚNO: Načtení DPI z metadat PNG (klíč 'Output_DPI') a nastavení do GUI („Výstup“ → pole DPI)
        # Zachovává veškeré původní chování výše; pouze doplňuje hodnotu DPI, pokud je k dispozici.
        try:
            if suffix == '.png':
                from PIL import Image
                import re
    
                dpi_val = None
                with Image.open(str(path_obj)) as img:
                    # 1) textová metadata (tEXt) – preferovaný klíč 'Output_DPI'
                    txt_meta = {}
                    try:
                        if hasattr(img, "text") and img.text:
                            txt_meta = dict(img.text)
                    except Exception:
                        txt_meta = {}
    
                    raw_val = txt_meta.get("Output_DPI") or txt_meta.get("output_dpi")
    
                    # 2) fallback: z img.info (někdy je Output_DPI tam; případně tuple v klíči 'dpi')
                    if not raw_val:
                        info = img.info or {}
                        raw_val = info.get("Output_DPI") or info.get("output_dpi")
                        if not raw_val:
                            raw_val = info.get("dpi")  # např. (240.0, 240.0)
    
                    # Parsování hodnoty na integer DPI
                    if isinstance(raw_val, (int, float)):
                        dpi_val = int(round(float(raw_val)))
                    elif isinstance(raw_val, (tuple, list)) and len(raw_val) >= 1:
                        try:
                            dpi_val = int(round(float(raw_val[0])))
                        except Exception:
                            dpi_val = None
                    elif isinstance(raw_val, str):
                        try:
                            m = re.search(r"(\d+(?:[.,]\d+)?)", raw_val)
                            if m:
                                dpi_val = int(round(float(m.group(1).replace(',', '.'))))
                        except Exception:
                            dpi_val = None
    
            if dpi_val:
                # Ochranné limity, ať GUI nedostane nesmyslné hodnoty
                dpi_val = max(30, min(2400, dpi_val))
    
                # Nastavení do existujícího pole DPI v záložce „Výstup“
                # (primárně počítám s QSpinBox `self.spin_dpi`; bez zásahu do ostatních částí)
                set_ok = False
                for attr in ("spin_dpi", "output_dpi_spin", "dpiSpin", "dpi_spinbox", "dpi_input", "line_edit_output_dpi"):
                    w = getattr(self, attr, None)
                    if w is None:
                        continue
                    try:
                        if hasattr(w, "setValue"):
                            w.setValue(int(dpi_val))
                        else:
                            w.setText(str(int(dpi_val)))
                        set_ok = True
                        break
                    except Exception:
                        continue
    
                # (nepovinné) uložit i do stavové struktury, pokud existuje
                try:
                    if hasattr(self, "current_settings") and isinstance(self.current_settings, dict):
                        self.current_settings["output_dpi"] = int(dpi_val)
                except Exception:
                    pass
    
                # (nepovinné) log
                try:
                    if set_ok and hasattr(self, "log_widget"):
                        self.log_widget.add_log(f"🔎 Output_DPI z metadatech PNG: {dpi_val}", "info")
                except Exception:
                    pass
        except Exception:
            # Tichý fallback – nechceme rozbít původní dvojklik
            pass

    def extract_gps_from_filename(self, filename):
        """
        Extrakce GPS z názvu: podporuje české (S/J/V/Z) i anglické (N/S/E/W) směry; zapíše do UI bez auto‑refresh.
        Vrací True/False podle úspěchu.
        """
        try:
            import re
            name = Path(filename).stem
            # Povol "GPS" volitelně a různé oddělovače
            pattern = r'(?:GPS\\s*)?([0-9]+(?:[.,][0-9]+)?)\\s*([SJNVEWZ])\\s*[+\\s_,;:-]?\\s*([0-9]+(?:[.,][0-9]+)?)\\s*([SJNVEWZ])'
            m = re.search(pattern, name, re.IGNORECASE)
            if not m:
                return False
    
            lat_val = float(m.group(1).replace(',', '.'))
            lat_dir = m.group(2).upper()
            lon_val = float(m.group(3).replace(',', '.'))
            lon_dir = m.group(4).upper()
    
            english_mode = any(d in {'N', 'E', 'W'} for d in {lat_dir, lon_dir})
            if english_mode:
                # EN: N(+), S(-), E(+), W(-)
                lat = -lat_val if lat_dir == 'S' else lat_val
                lon = -lon_val if lon_dir == 'W' else lon_val
            else:
                # CZ: S(+), J(-), V(+), Z(-)
                lat = -lat_val if lat_dir == 'J' else lat_val
                lon = -lon_val if lon_dir == 'Z' else lon_val
    
            self.set_manual_gps_and_preview(lat, lon)
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"📍 GPS z názvu: {lat:.5f}, {lon:.5f}", "success")
            return True
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba při extrakci GPS z názvu: {e}", "warning")
            return False

        
    def extract_zoom_from_filename(self, filename):
        """Extrakce zoomu z názvu souboru ve formátu ...+Z18+...; vrací int nebo None a nastaví UI."""
        try:
            import re
            name = Path(filename).stem
            # Hledá 'Z' následované 1–2 ciframi, ohraničené zač./koncem nebo oddělovači + _ - mezera
            m = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', name, re.IGNORECASE)
            if not m:
                return None
            z = int(m.group(1))
            # Omezit na rozumný rozsah dlaždic OSM
            z = max(1, min(19, z))
    
            # Nastavit do obou spinnerů, pokud existují
            if hasattr(self, 'spin_zoom'):
                self.spin_zoom.setValue(z)
            if hasattr(self, 'spin_preview_zoom'):
                self.spin_preview_zoom.setValue(z)
    
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"🔍 Zoom z názvu: Z{z}", "info")
            return z
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba při extrakci Zoom z názvu: {e}", "warning")
            return None

    def extract_location_info_from_filename(self, filename):
        """KOMPLETNĚ PŘEPSANÁ FUNKCE: Extrakce informací o lokaci z názvu souboru podle nového formátu"""
        extracted_info = {}
        
        try:
            # Odstranění přípony pro lepší parsing
            name_without_ext = Path(filename).stem
            
            # === NOVÝ FORMÁT S PLUS ZNAKY ===
            if '+' in name_without_ext:
                parts = name_without_ext.split('+')
                
                if len(parts) >= 2:
                    # První část = ID lokace (např. ZLÍN_STŘEDOVÁ001)
                    id_lokace = parts[0].strip()
                    if id_lokace and len(id_lokace) >= 3:
                        self.input_id_lokace.setText(id_lokace)
                        extracted_info['ID Lokace'] = id_lokace
                        self.log_widget.add_log(f"📍 ID Lokace: {id_lokace}", "info")
                    
                    # Druhá část = Popis (např. NejvětšíNalezištěZaDětskýchHřištěm)
                    popis = parts[1].strip()
                    if popis and not popis.lower().startswith('gps') and not popis.isdigit():
                        self.input_popis.setText(popis)
                        extracted_info['Popis'] = popis
                        self.log_widget.add_log(f"📝 Popis: {popis}", "info")
                
                # POZNÁMKA: GPS souřadnice a číselné ID IGNORUJEME podle požadavku
                self.log_widget.add_log("⚠️ GPS souřadnice a číselné ID ponechány beze změny (dle požadavku)", "info")
                
            else:
                # === STARÝ FORMÁT BEZ PLUS ZNAKŮ ===
                # Fallback na původní logiku pro zpětnou kompatibilitu
                
                # Extrakce ID lokace
                id_lokace = self.extract_location_id_old_format(name_without_ext)
                if id_lokace:
                    self.input_id_lokace.setText(id_lokace)
                    extracted_info['ID Lokace'] = id_lokace
                
                # Extrakce popisu
                popis = self.extract_description_old_format(name_without_ext)
                if popis:
                    self.input_popis.setText(popis)
                    extracted_info['Popis'] = popis
            
            return extracted_info
            
        except Exception as e:
            self.log_widget.add_log(f"⚠️ Chyba při extrakci informací z názvu: {e}", "warning")
            return {}

    def extract_location_id_old_format(self, filename):
        """NOVÁ FUNKCE: Extrakce ID lokace ze starého formátu (pro zpětnou kompatibilitu)"""
        import re
        
        # Vzory pro ID lokace
        patterns = [
            # Formát: KAROLÍN_KOT001, BRNO_CENTRUM_001
            r'([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ_]+)(?:[_\-]?[0-9]{3,5})?',
            # Formát: Karolin_Kotkovci, Brno_Centrum
            r'([A-Za-záčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ_]+)(?:[_\-])',
            # Formát: LOKALITA123
            r'([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+)(?:[0-9]{3,5})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                location_id = match.group(1).strip('_-')
                
                # Vyčištění a formátování
                location_id = location_id.replace('_', '_').upper()
                
                # Kontrola, zda to není jen číslo nebo příliš krátké
                if len(location_id) >= 3 and not location_id.isdigit():
                    return location_id
        
        return None

    def extract_description_old_format(self, filename):
        """NOVÁ FUNKCE: Extrakce popisu ze starého formátu (pro zpětnou kompatibilitu)"""
        import re
        
        # Vzory pro popis
        patterns = [
            # Formát: něco+POPIS+něco
            r'\+([^+\d][^+]*?)\+',
            # Formát: ID_POPIS_číslo
            r'[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ_]+[_\-]([A-Za-záčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+)[_\-][0-9]',
            # Formát: LOKACE-Popis-123
            r'[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+[\-_]([A-Za-záčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+)[\-_][0-9]',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                description = match.group(1).strip('_-+')
                
                # Vyčištění popisu
                description = description.replace('_', ' ').replace('-', ' ')
                
                # Kontrola, zda to není GPS nebo číslo
                if (len(description) >= 3 and 
                    not description.lower().startswith('gps') and 
                    not description.isdigit() and
                    not re.match(r'^[0-9.]+$', description)):
                    return description
        
        return None

    # Zachováváme původní funkce pro zpětnou kompatibilitu:
    def extract_info_from_filename(self, filename):
        """ZACHOVANÁ FUNKCE: Bezpečnější fallback extrakce popisu ze staršího formátu názvu (bez indexu 12)."""
        try:
            name_without_ext = Path(filename).stem
            parts = [p.strip() for p in name_without_ext.split('+') if p.strip()]
            if len(parts) >= 2:
                potential_desc = parts[1]
                if (potential_desc
                    and not potential_desc.lower().startswith('gps')
                    and not potential_desc.startswith('20')):  # hrubý filtr na datové prefixy
                    self.input_popis.setText(potential_desc)
                    if hasattr(self, 'log_widget'):
                        self.log_widget.add_log(f"📝 Extrahován popis: {potential_desc}", "info")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba při extrakci informací z názvu: {e}", "warning")


    def test_filename_parsing(self, filename):
        """NOVÁ FUNKCE: Testování parsování názvu souboru (pro debug)"""
        print(f"\n=== TESTOVÁNÍ PARSOVÁNÍ: {filename} ===")
        
        name_without_ext = Path(filename).stem
        
        if '+' in name_without_ext:
            parts = name_without_ext.split('+')
            print(f"Počet částí: {len(parts)}")
            
            for i, part in enumerate(parts):
                print(f"Část {i}: '{part}'")
            
            if len(parts) >= 2:
                id_lokace = parts.strip()
                popis = parts[12].strip()
                
                print(f"\n📍 ID Lokace: '{id_lokace}'")
                print(f"📝 Popis: '{popis}'")
                
                # Nalezení GPS částí
                gps_parts = [p for p in parts if p.startswith('GPS') or any(c in p for c in ['S', 'V', 'J', 'Z']) and any(c.isdigit() for c in p)]
                if gps_parts:
                    print(f"📍 GPS části: {gps_parts}")
                
                # Nalezení číselného ID (poslední část)
                if len(parts) > 2:
                    last_part = parts[-1].strip()
                    if last_part.isdigit():
                        print(f"🔢 Číselné ID: '{last_part}'")
        else:
            print("Starý formát bez '+' znaků")
        
        print("=" * 50)

    # Příklad použití testovací funkce:
    def test_new_format(self):
        """TESTOVACÍ FUNKCE: Test nového formátu"""
        test_filenames = [
            "ZLÍN_STŘEDOVÁ001+NejvětšíNalezištěZaDětskýchHřištěm+GPS49.23588S+17.67175V+Z18+00009.png",
            "BRNO_CENTRUM002+ParkUNádraží+GPS49.19522S+16.60796V+Z17+00010.jpg",
            "PRAHA_VINOHRADY003+NámětíMíru+GPS50.07554S+14.43066V+Z16+00011.heic"
        ]
        
        for filename in test_filenames:
            self.test_filename_parsing(filename)
            print("\nSimulace extrakce:")
            self.extract_location_info_from_filename(filename)
            print("\n" + "="*80 + "\n")

    def is_location_map_image(self, filename):
        """UPRAVENÁ FUNKCE: Rozpoznání, zda se jedná o obrázek lokační mapy"""
        filename_lower = filename.lower()
        
        # Kontrola formátu s plus znaky (nový formát)
        if '+' in filename:
            return True
        
        # Klíčová slova pro lokační mapy
        location_keywords = [
            'mapa', 'map', 'lokace', 'location', 'gps', 'místo', 'place',
            'pozice', 'position', 'bod', 'point', 'souradnice', 'coordinates'
        ]
        
        # Kontrola přítomnosti klíčových slov
        for keyword in location_keywords:
            if keyword in filename_lower:
                return True
        
        # Kontrola formátu názvu - obsahuje GPS souřadnice
        import re
        gps_pattern = r'gps[0-9.]+'
        if re.search(gps_pattern, filename_lower):
            return True
        
        # Kontrola formátu s ID lokace (např. KAROLÍN_KOT001)
        id_pattern = r'[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ_]+[0-9]{3,5}'
        if re.search(id_pattern, filename_lower):
            return True
        else:
            return False
    
    def handle_location_map_image(self, path_obj, filename):
        """Načte Marker_Style/Marker_Size_Px z PNG a nastaví je do GUI; neotevírá GPS tab ani nerefreshuje náhled."""
        self.combo_coord_mode.setCurrentIndex(1)
        self.log_widget.add_log(f"🗺️ Rozpoznána lokační mapa: {filename}", "success")
        extracted_info = self.extract_location_info_from_filename(filename)
        if extracted_info:
            self.log_widget.add_log("📋 Automaticky vyplněny údaje z názvu souboru:", "success")
            for key, value in extracted_info.items():
                if value:
                    self.log_widget.add_log(f" • {key}: {value}", "info")
        try:
            from PIL import Image
            style_val = None
            size_val = None
            with Image.open(path_obj) as im:
                t = getattr(im, "text", {}) or {}
                style_val = t.get("Marker_Style") or t.get("marker_style")
                size_val = t.get("Marker_Size_Px") or t.get("marker_size_px")
                if not style_val or not size_val:
                    info = getattr(im, "info", {}) or {}
                    style_val = style_val or info.get("Marker_Style") or info.get("marker_style")
                    size_val = size_val or info.get("Marker_Size_Px") or info.get("marker_size_px")
            if style_val and hasattr(self, "combo_marker_style"):
                sv = str(style_val).lower().strip()
                self.combo_marker_style.setCurrentIndex(1 if sv == "cross" else 0)
                if hasattr(self, "current_settings") and isinstance(self.current_settings, dict):
                    self.current_settings["marker_style"] = "cross" if sv == "cross" else "dot"
                self.log_widget.add_log(f"🔎 Načten Marker_Style z PNG: {sv}", "info")
            if size_val and hasattr(self, "spin_marker_size"):
                try:
                    mv = max(1, int(str(size_val).strip()))
                    self.spin_marker_size.setValue(mv)
                    if hasattr(self, "current_settings") and isinstance(self.current_settings, dict):
                        self.current_settings["marker_size"] = mv
                    self.log_widget.add_log(f"🔎 Načten Marker_Size_Px z PNG: {mv}", "info")
                except Exception:
                    pass
            # Neprovádět: self.tabs.setCurrentIndex(self._gps_tab_index); ani update_map_preview()
        except Exception:
            pass

    def monitor_gps_preview_consistency(self):
        """Stálá indikace shody/neshody mezi GUI a zobrazeným náhledem (4 varianty textů)."""
        try:
            # Není zobrazený žádný náhled → jen naplánovat další kontrolu
            last = getattr(self, "_last_map_req", None)  # (lat6, lon6, zoom, style, size)
            if not last:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(5000, self.monitor_gps_preview_consistency)
                return
    
            # Aktuální normalizovaná pětice z GUI
            current = self._get_normalized_gps_preview_tuple()
            if current is None:
                # Nevalidní GUI → chováme se jako neshoda, ale texty zůstanou řízené _set_consistency_ui
                current = (None, None, None, None, None)
    
            source = getattr(self, "_preview_source", "generated")  # 'cache' | 'generated'
            match = (current == last)
            self._set_consistency_ui(source, match)
        except Exception:
            pass
        # Periodická kontrola
        from PySide6.QtCore import QTimer
        QTimer.singleShot(5000, self.monitor_gps_preview_consistency)
        
    def _ensure_mismatch_overlay(self):
        """Zajistí existenci překryvné vrstvy s červeným rámem a šikmým šrafováním (bez vertikálních čar)."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPainter, QColor, QPen
    
            if not hasattr(self, "_mismatch_overlay") or self._mismatch_overlay is None:
                class _MismatchOverlay(QWidget):
                    def __init__(self, parent):
                        super().__init__(parent)
                        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                        self.setAttribute(Qt.WA_TranslucentBackground, True)
                        self.setVisible(False)
    
                    def paintEvent(self, ev):
                        w = self.width()
                        h = self.height()
                        if w <= 0 or h <= 0:
                            return
    
                        p = QPainter(self)
                        p.setRenderHint(QPainter.Antialiasing, False)
    
                        # 1) Poloprůhledné červené podbarvení (~80 % transparentní)
                        p.setOpacity(0.2)
                        p.fillRect(self.rect(), QColor(198, 40, 40))
    
                        # 2) Rám (výraznější červený, lehce průhledný)
                        p.setOpacity(0.6)
                        frame_pen = QPen(QColor(198, 40, 40))
                        frame_pen.setWidth(4)
                        p.setPen(frame_pen)
                        p.setBrush(Qt.NoBrush)
                        p.drawRect(2, 2, max(0, w - 5), max(0, h - 5))
    
                        # 3) Šrafování – pouze diagonální čáry z pravého horního dolů vlevo
                        p.setOpacity(0.30)
                        hatch_pen_d = QPen(QColor(198, 40, 40))
                        hatch_pen_d.setWidth(2)
                        p.setPen(hatch_pen_d)
    
                        # Linie jdou z (x,0) k (x-h, h) pro x v [0, w+h] po krocích diag_spacing
                        diag_spacing = 18
                        t = 0
                        max_t = w + h
                        while t <= max_t:
                            x1 = min(w, t)
                            y1 = 0 if t <= w else t - w
                            x2 = max(0, t - h)
                            y2 = h if t >= h else t
                            # Obrat X pro směr z prava nahoře vlevo dolů
                            p.drawLine(w - x1, y1, w - x2, y2)
                            t += diag_spacing
    
                        p.end()
    
                self._mismatch_overlay = _MismatchOverlay(self.map_label)
                self._update_mismatch_overlay_geometry()
        except Exception:
            pass

    def _update_mismatch_overlay_geometry(self):
        """Přizpůsobí překryvnou vrstvu aktuální velikosti náhledu."""
        try:
            if hasattr(self, "_mismatch_overlay") and self._mismatch_overlay is not None and hasattr(self, "map_label"):
                self._mismatch_overlay.setGeometry(self.map_label.rect())
                self._mismatch_overlay.raise_()
        except Exception:
            pass
    
    def _set_consistency_ui(self, source: str, match: bool):
        """
        Nastaví text + barvu upozornění a zobrazí/skrývá šrafovací vrstvu.
        source ∈ {'cache','generated'}; match = True/False.
        """
        try:
            # 4 varianty
            if source == "cache" and match:
                text = "Načten obrázek z cache a odpovídá hodnotám v GUI"
                color = "#2e7d32"  # zelená
                show_overlay = False
            elif source == "cache" and not match:
                text = "Načten obrázek z cache, ale neodpovídá hodnotám v GUI"
                color = "#c62828"  # červená
                show_overlay = True
            elif source != "cache" and match:
                text = "Změněny hodnoty v GUI a náhled odpovídá hodnotám"
                color = "#2e7d32"  # zelená
                show_overlay = False
            else:
                text = "Změněny hodnoty v GUI a náhled neodpovídá hodnotám"
                color = "#c62828"  # červená
                show_overlay = True
    
            # Nastavit text a barvu (stálé, nemazat)
            if hasattr(self, "gps_warning_label") and self.gps_warning_label:
                self.gps_warning_label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: bold; font-size: 13px; }}")
                self.gps_warning_label.setText(text)
    
            # Overlay jen pro neshody (červené stavy)
            self._ensure_mismatch_overlay()
            if hasattr(self, "_mismatch_overlay") and self._mismatch_overlay is not None:
                self._mismatch_overlay.setVisible(bool(show_overlay))
                if show_overlay:
                    self._update_mismatch_overlay_geometry()
        except Exception:
            pass

    def _get_normalized_gps_preview_tuple(self):
        """
        Vrátí normalizovanou pětici (lat6, lon6, zoom, style, size) z GUI:
        - lat/lon zaokrouhlené na 6 des. míst (float → round)
        - zoom a size jako int
        - style jako 'dot' nebo 'cross'
        Pokud nelze korektně parsovat souřadnice, vrátí None.
        """
        try:
            coords_text = (self.input_manual_coords.text() if hasattr(self, "input_manual_coords") else "").strip()
            parsed = self.parse_coordinates(coords_text)
            if not parsed:
                return None
            lat, lon = parsed
            zoom = int(self.spin_preview_zoom.value()) if hasattr(self, "spin_preview_zoom") else 18
            marker_style = self.get_marker_style_from_settings() if hasattr(self, "get_marker_style_from_settings") else "dot"
            marker_size = self.get_marker_size_from_settings() if hasattr(self, "get_marker_size_from_settings") else 10
    
            norm_lat = round(float(lat), 6)
            norm_lon = round(float(lon), 6)
            norm_zoom = int(zoom)
            norm_style = "cross" if str(marker_style).lower().strip() == "cross" else "dot"
            norm_size = int(marker_size)
            return (norm_lat, norm_lon, norm_zoom, norm_style, norm_size)
        except Exception:
            return None


    def handle_gps_photo(self, path_obj, filename):
        """UPRAVENÁ FUNKCE: Zpracování HEIC/HEIF fotky s GPS daty"""
        self.combo_coord_mode.setCurrentIndex(0)  # F - Ze souboru
        self.log_widget.add_log(f"📷 Rozpoznána GPS fotka: {filename}", "success")
        
        # Pokus o extrakci informací z názvu i u GPS fotek
        extracted_info = self.extract_location_info_from_filename(filename)
        
        if extracted_info:
            self.log_widget.add_log("📋 Doplněny údaje z názvu souboru:", "info")

    def handle_regular_image(self, path_obj, filename):
        """UPRAVENÁ FUNKCE: Zpracování obyčejného obrázku"""
        self.log_widget.add_log(f"🖼️ Vybrán obrázek: {filename}", "success")
        
        # Pokus o extrakci informací z názvu
        extracted_info = self.extract_location_info_from_filename(filename)
        
        if extracted_info:
            self.log_widget.add_log("📋 Nalezeny údaje v názvu souboru:", "info")

    def extract_gps_from_filename(self, filename):
        """Rozšířená extrakce GPS z názvu: podporuje české (S/J/V/Z) i anglické (N/S/E/W) směry."""
        try:
            import re
            name = Path(filename).stem
    
            # Příklad: GPS49.23173S+17.42791V nebo GPS50.07554N+14.43066E
            # Povolit i oddělovače jako + / _ / mezery, je-li třeba.
            pattern = r'GPS\s*([0-9]+(?:\.[0-9]+)?)\s*([SJVZNSEW])\s*[\+\s_,-]?\s*([0-9]+(?:\.[0-9]+)?)\s*([SJVZNSEW])'
            m = re.search(pattern, name, re.IGNORECASE)  # vyhledat kdekoliv v názvu [6][9]
            if not m:
                return False
    
            lat_val = float(m.group(1))
            lat_dir = m.group(2).upper()
            lon_val = float(m.group(3))
            lon_dir = m.group(4).upper()
    
            # Aplikace znamének pro CZ i EN směry
            # Šířka: J (jih) nebo S (South) je záporná; S (sever) nebo N (North) je kladná.
            if lat_dir in ('J', 'S') and lon_dir in ('E', 'W', 'N', 'S'):
                lat = -lat_val
            elif lat_dir in ('N', 'S') and lon_dir in ('E', 'W'):
                lat = -lat_val if lat_dir == 'S' else lat_val
            else:
                lat = -lat_val if lat_dir == 'J' else lat_val
    
            # Délka: Z (západ) nebo W (West) je záporná; V (východ) nebo E (East) je kladná.
            if lon_dir in ('Z', 'W'):
                lon = -lon_val
            else:
                lon = lon_val
    
            # Nastavit a spustit náhled
            self.set_manual_gps_and_preview(lat, lon)
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"📍 GPS z názvu: {lat:.5f}, {lon:.5f}", "success")
            return True
    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Chyba při extrakci GPS z názvu: {e}", "warning")
            return False
        
    def _ensure_gps_source_label(self):
        """
        Vloží (pokud ještě není) nový QLabel `self.label_gps_source` hned ZA `self.label_parsed_coords`
        do stejného řádku/layoutu a nastaví oběma stejný „stretch“ (≈ polovina šířky pro každý).
        Funguje pro QHBoxLayout i QGridLayout rodiče.
        """
        from PySide6.QtWidgets import QLabel, QHBoxLayout, QGridLayout, QSizePolicy
        from PySide6.QtCore import Qt
    
        # Musí existovat původní label se souřadnicemi
        if not hasattr(self, "label_parsed_coords") or self.label_parsed_coords is None:
            return
    
        # Už existuje?
        if getattr(self, "label_gps_source", None) and self.label_gps_source.parent() is not None:
            return
    
        parent = self.label_parsed_coords.parentWidget()
        if parent is None or parent.layout() is None:
            return
    
        lay = parent.layout()
    
        # Vytvoř nový label
        src = QLabel(parent)
        src.setObjectName("label_gps_source")
        src.setText("")  # vyplní se při importu HEIC
        src.setToolTip("")  # plní se při importu HEIC
        src.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        # Jednořádkový vzhled a decentní styl
        src.setWordWrap(False)
        src.setTextInteractionFlags(Qt.TextSelectableByMouse)
        src.setStyleSheet("QLabel#label_gps_source { color: #bfbfbf; font-size: 11px; }")
        src.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    
        # Ulož na instanci
        self.label_gps_source = src
    
        # Umístění: hned za label_parsed_coords + rozdělení šířky 1:1
        if isinstance(lay, QHBoxLayout):
            idx = lay.indexOf(self.label_parsed_coords)
            if idx >= 0:
                lay.insertWidget(idx + 1, src)
                # stretch 1:1 (přibližně „polovina“ pro každý)
                lay.setStretch(idx, 1)
                lay.setStretch(idx + 1, 1)
            else:
                lay.addWidget(src)
        elif isinstance(lay, QGridLayout):
            # Najdi pozici původního labelu
            pos_index = lay.indexOf(self.label_parsed_coords)
            if pos_index >= 0:
                r, c, rs, cs = lay.getItemPosition(pos_index)
                lay.addWidget(src, r, c + 1, rs, 1)
                # Stretch 1:1 na sloupcích
                try:
                    lay.setColumnStretch(c, 1)
                    lay.setColumnStretch(c + 1, 1)
                except Exception:
                    pass
            else:
                # nouzově přidej do dalšího řádku
                lay.addWidget(src, 0, 1, 1, 1)
        else:
            # méně běžné layouty – prostě přidáme
            try:
                lay.addWidget(src)
            except Exception:
                pass

    def on_pick_heic_and_fill_manual_coords(self):
        """
        Otevře dialog pro výběr HEIC souboru a při úspěchu vloží
        GPS souřadnice ve formátu '49.234350° S, 17.665314° V' do pole 'Ruční souřadnice:'.
    
        Minimal change:
          - Zachová nativní Finder dialog všude, kromě macOS iCloud cesty
            ('Mobile Documents/com~apple~CloudDocs'), kde se z důvodu lagů
            přepne na rychlý (nenativní) Qt dialog.
          - NEpřepisuje label_parsed_coords; souřadnice zůstanou → klikání do mapy funguje.
          - Název HEIC zobrazíme v novém labelu za label_parsed_coords (přidáno dynamicky).
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from PySide6.QtCore import QDir
        from pathlib import Path
        import sys
    
        base_dir = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Obrázky/")
        start_dir = ""
    
        # 1) Paměť na instanci
        try:
            last_dir_mem = getattr(self, "_last_heic_dir", "")
            if last_dir_mem and Path(last_dir_mem).is_dir():
                start_dir = last_dir_mem
        except Exception:
            start_dir = ""
    
        # 2) Persist v settings (bez skenování)
        if not start_dir:
            try:
                pset = Path("settings/last_heic_dir.txt")
                if pset.exists():
                    sd = pset.read_text(encoding="utf-8").strip()
                    if sd and Path(sd).is_dir():
                        start_dir = sd
            except Exception:
                start_dir = ""
    
        # 3) Fallback na pevnou složku Obrázky (bez rekurze)
        if not start_dir and base_dir.exists() and base_dir.is_dir():
            start_dir = str(base_dir)
    
        # --- options pro rychlejší chování v iCloud složkách ---
        opts = QFileDialog.Options()
        opts |= QFileDialog.DontResolveSymlinks
        opts |= QFileDialog.ReadOnly
        try:
            opts |= QFileDialog.HideNameFilterDetails
        except Exception:
            pass
        # Pouze na macOS a pouze v iCloud cestě přepneme na rychlý nenativní dialog
        try:
            if sys.platform == "darwin" and "Mobile Documents/com~apple~CloudDocs" in (start_dir or ""):
                opts |= QFileDialog.DontUseNativeDialog
                opts |= QFileDialog.DontUseCustomDirectoryIcons
        except Exception:
            pass
    
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Vybrat fotografii (HEIC) se souřadnicemi",
            start_dir,
            "HEIC obrázky (*.heic *.HEIC)",
            options=opts
        )
        if not file_path:
            return
    
        # Ulož poslední úspěšnou složku pro příště (paměť + settings)
        try:
            parent_dir = str(Path(file_path).parent)
            self._last_heic_dir = parent_dir
            Path("settings").mkdir(parents=True, exist_ok=True)
            Path("settings/last_heic_dir.txt").write_text(parent_dir, encoding="utf-8")
        except Exception:
            pass
    
        # --- Extrakce GPS a vyplnění pole ---
        coords = self._heic_extract_gps_decimal(file_path)
        if not coords:
            QMessageBox.warning(self, "GPS nenalezeny", "V souboru nebyly nalezeny GPS souřadnice.")
            return
    
        lat, lon = coords
    
        # Formát na '49.234350° S, 17.665314° V'
        lat_ref = "S" if lat >= 0 else "J"   # Sever / Jih
        lon_ref = "V" if lon >= 0 else "Z"   # Východ / Západ
        lat_abs = abs(lat)
        lon_abs = abs(lon)
        value = f"{lat_abs:.6f}° {lat_ref}, {lon_abs:.6f}° {lon_ref}"
    
        # Vyplnit pole a přegenerovat náhled (využití existující logiky)
        if hasattr(self, "input_manual_coords") and self.input_manual_coords is not None:
            self.input_manual_coords.setText(value)
    
            # ✅ Nově: vytvoř/ukaž label s názvem HEIC za label_parsed_coords a nastav text
            try:
                self._ensure_gps_source_label()  # vloží nový label do stejného řádku a rozdělí šířku 1:1
                if hasattr(self, "label_gps_source") and self.label_gps_source is not None:
                    name = Path(file_path).name
                    self.label_gps_source.setText(name)
                    self.label_gps_source.setToolTip(str(file_path))
            except Exception:
                pass
    
            # Ulož informaci pro status pod mapou (one-shot)
            try:
                self._last_gps_file = file_path
            except Exception:
                pass
    
            if hasattr(self, "_on_gps_param_changed"):
                try:
                    self._on_gps_param_changed()
                except Exception:
                    pass
    
            for fn_name in ("update_map_preview", "refresh_map_preview", "on_gps_refresh_clicked", "_refresh_map_preview"):
                fn = getattr(self, fn_name, None)
                if callable(fn):
                    try:
                        fn()
                        break
                    except Exception:
                        continue
        else:
            # fallback – aspoň ukaž název souboru v novém labelu (pokud existuje)
            try:
                self._ensure_gps_source_label()
                if hasattr(self, "label_gps_source") and self.label_gps_source is not None:
                    name = Path(file_path).name
                    self.label_gps_source.setText(name)
                    self.label_gps_source.setToolTip(str(file_path))
            except Exception:
                pass
    
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Souřadnice", f"Souřadnice: {value}")

    def _heic_extract_gps_decimal(self, heic_path: str):
        """
        Vrátí tuple (lat, lon) v desetinných stupních z HEIC souboru, nebo None pokud GPS není dostupné.
        Využívá pillow_heif + Pillow + piexif (pokud je k dispozici).
        Neprovádí žádné vedlejší efekty mimo čtení souboru.
        """
        try:
            from PIL import Image
            try:
                import pillow_heif  # umožní Pillow otevřít HEIC
                pillow_heif.register_heif_opener()
            except Exception:
                pass  # pokusíme se otevřít i bez registrace (pokud už je registrováno jinde)
    
            with Image.open(heic_path) as im:
                exif_bytes = im.info.get("exif")
                if not exif_bytes:
                    return None
    
            # Přečíst EXIF jako dict (piexif je spolehlivý pro GPS parse)
            try:
                import piexif
                exif_dict = piexif.load(exif_bytes)
                gps_ifd = exif_dict.get("GPS", {})
            except Exception:
                gps_ifd = {}
    
            if not gps_ifd:
                return None
    
            # Helpers
            def _rat_to_float(rat):
                # piexif vrací buď tuple (num, den) nebo objekt s .numerator/.denominator
                try:
                    if isinstance(rat, tuple):
                        num, den = rat
                        return float(num) / float(den) if den else 0.0
                    return float(rat.numerator) / float(rat.denominator)
                except Exception:
                    return 0.0
    
            def _dms_to_deg(dms):
                # očekává trojici racionálních čísel [deg, min, sec]
                if not dms or len(dms) != 3:
                    return None
                d = _rat_to_float(dms[0])
                m = _rat_to_float(dms[1])
                s = _rat_to_float(dms[2])
                return d + (m / 60.0) + (s / 3600.0)
    
            # Tagy podle EXIF specifikace
            lat_ref = gps_ifd.get(1)   # 'N' nebo 'S' (ASCII)
            lat_dms = gps_ifd.get(2)   # ((deg_num,deg_den), (min_num,min_den), (sec_num,sec_den))
            lon_ref = gps_ifd.get(3)   # 'E' nebo 'W'
            lon_dms = gps_ifd.get(4)
    
            if not (lat_ref and lat_dms and lon_ref and lon_dms):
                return None
    
            # piexif vrací bytes pro ref, převedeme na str
            if isinstance(lat_ref, (bytes, bytearray)):
                lat_ref = lat_ref.decode(errors="ignore")
            if isinstance(lon_ref, (bytes, bytearray)):
                lon_ref = lon_ref.decode(errors="ignore")
    
            lat = _dms_to_deg(lat_dms)
            lon = _dms_to_deg(lon_dms)
            if lat is None or lon is None:
                return None
    
            if lat_ref.upper().startswith("S"):
                lat = -lat
            if lon_ref.upper().startswith("W"):
                lon = -lon
    
            return (lat, lon)
        except Exception:
            return None

    @staticmethod
    def _mercator_world_px_to_lonlat(x, y, z):
        """
        'world pixel' souřadnice → WGS84 (lon, lat) pro daný zoom z (256px tiles).
        """
        import math
        s = 256 * (2 ** z)
        lon = x / s * 360.0 - 180.0
        n = math.pi - 2.0 * math.pi * y / s
        lat = math.degrees(math.atan(math.sinh(n)))
        return lon, lat

    @staticmethod
    def _mercator_lonlat_to_world_px(lon, lat, z):
        """
        Web Mercator (EPSG:3857) → 'world pixel' souřadnice pro daný zoom z (256px tiles).
        """
        import math
        s = 256 * (2 ** z)
        x = (lon + 180.0) / 360.0 * s
        # clamp lat to Mercator bounds to avoid inf near poles
        lat = max(min(lat, 85.05112878), -85.05112878)
        rad = math.radians(lat)
        y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * s
        return x, y

    def _get_map_center_from_ui(self):
        """
        Snaží se získat střed mapy (lat, lon) z existujícího UI bez přidávání nové logiky:
        1) label_parsed_coords (text typu 'Parsované: 49.231730° S, 17.427910° V')
        2) input_manual_coords (např. '49.231730, 17.427910')
        Vrac í tuple (lat, lon) nebo None.
        """
        import re
    
        # 1) Zkusit label 'Parsované: ...'
        try:
            if hasattr(self, "label_parsed_coords") and self.label_parsed_coords is not None:
                txt = self.label_parsed_coords.text()
                # očekáváme něco jako: Parsované: 49.231730° S, 17.427910° V
                m = re.search(r'(-?\d+(?:[.,]\d+)?)\s*°?\s*([SJ]|[N])?,\s*(-?\d+(?:[.,]\d+)?)\s*°?\s*([VZ]|[EW])?', txt, re.IGNORECASE)
                if m:
                    lat = float(m.group(1).replace(',', '.'))
                    lat_ref = (m.group(2) or '').upper()
                    lon = float(m.group(3).replace(',', '.'))
                    lon_ref = (m.group(4) or '').upper()
                    # Cz: S=Sever (North, +), J=Jih (South, -), V=Východ (East, +), Z=Západ (West, -)
                    if lat_ref in ('J', 'SOUTH'):  # kdyby někdy bylo anglicky
                        lat = -abs(lat)  # Jih
                    # 'S' v češtině je Sever => + (nedělám nic)
                    if lon_ref in ('Z', 'W', 'WEST'):
                        lon = -abs(lon)  # Západ
                    return (lat, lon)
        except Exception:
            pass
    
        # 2) Zkusit ruční pole (podporujeme 'lat, lon' s tečkou nebo čárkou)
        try:
            if hasattr(self, "input_manual_coords") and self.input_manual_coords is not None:
                t = self.input_manual_coords.text()
                m2 = re.search(r'(-?\d+(?:[.,]\d+)?)\s*,\s*(-?\d+(?:[.,]\d+)?)', t)
                if m2:
                    lat = float(m2.group(1).replace(',', '.'))
                    lon = float(m2.group(2).replace(',', '.'))
                    return (lat, lon)
        except Exception:
            pass
    
        return None

    def _on_map_click_get_coords(self, label_pos):
        """
        Přepočítá pozici kliknutí na QLabel s mapou na GPS souřadnice.
        - Využívá aktuální zoom (self.spin_preview_zoom)
        - Střed mapy odvodí z UI (label_parsed_coords nebo input_manual_coords)
        - Výsledek vloží do self.input_manual_coords ve formátu '49.234350° S, 17.665314° V'
        - Po kliknutí automaticky přegeneruje náhled mapy (využije existující refresh funkce)
        """
        try:
            pm = self.map_label.pixmap()
            if pm is None or pm.isNull():
                return  # není co měřit
    
            # Zjistit, kde je pixmapa uvnitř QLabel (je vystředěná)
            lw, lh = self.map_label.width(), self.map_label.height()
            iw, ih = pm.width(), pm.height()
            offset_x = (lw - iw) // 2
            offset_y = (lh - ih) // 2
    
            # Klik mimo pixmapu ignoruj
            x = label_pos.x() - offset_x
            y = label_pos.y() - offset_y
            if x < 0 or y < 0 or x >= iw or y >= ih:
                return
    
            # Získat střed mapy (lat, lon) z UI
            center = self._get_map_center_from_ui()
            if center is None:
                if hasattr(self, 'map_status_label'):
                    self.map_status_label.setText("⚠️ Nelze určit střed mapy – nastavte souřadnice.")
                return
    
            lat0, lon0 = center
            z = int(self.spin_preview_zoom.value()) if hasattr(self, 'spin_preview_zoom') else 19
    
            # Přepočet: pixelový posun vůči středu obrázku → světové pixely → WGS84
            dx = x - (iw / 2.0)
            dy = y - (ih / 2.0)
    
            wp_cx, wp_cy = self._mercator_lonlat_to_world_px(lon0, lat0, z)
            wp_x = wp_cx + dx
            wp_y = wp_cy + dy
            lon, lat = self._mercator_world_px_to_lonlat(wp_x, wp_y, z)
    
            # Formátování na '49.234350° S, 17.665314° V'
            lat_ref = "S" if lat >= 0 else "J"   # Sever / Jih
            lon_ref = "V" if lon >= 0 else "Z"   # Východ / Západ
            lat_abs = abs(lat)
            lon_abs = abs(lon)
            formatted = f"{lat_abs:.6f}° {lat_ref}, {lon_abs:.6f}° {lon_ref}"
    
            # Vložit do ručního pole
            if hasattr(self, "input_manual_coords") and self.input_manual_coords is not None:
                self.input_manual_coords.setText(formatted)
    
                # Označit, že parametry se změnily (existující chování)
                if hasattr(self, "_on_gps_param_changed"):
                    try:
                        self._on_gps_param_changed()
                    except Exception:
                        pass
    
                # Pokusit se okamžitě přegenerovat náhled mapy využitím existujících funkcí
                for fn_name in ("update_map_preview", "refresh_map_preview", "on_gps_refresh_clicked", "_refresh_map_preview"):
                    fn = getattr(self, fn_name, None)
                    if callable(fn):
                        try:
                            fn()
                            break  # stačí první úspěšný refresh
                        except Exception:
                            continue
    
        except Exception:
            pass
    
    def create_gps_settings_tab(self):
        """GPS tab s náhledem mapy (bez přepínače režimu), kliknutím do mapy lze získat souřadnice."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
            QGroupBox, QGridLayout, QScrollArea, QSizePolicy, QProgressBar, QPushButton
        )
        from PySide6.QtCore import Qt, QTimer, QObject, QEvent
    
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
    
        # — Ruční souřadnice + Zoom (BEZ comboboxu režimu)
        group = QGroupBox("📍 GPS Souřadnice")
        group_layout = QGridLayout()
        group_layout.setContentsMargins(8, 8, 8, 8)
        group_layout.setSpacing(6)
    
        # Řádek: Ruční souřadnice + tlačítko Z HEIC… + Zoom
        group_layout.addWidget(QLabel("Ruční souřadnice:"), 0, 0)
    
        coords_zoom_widget = QWidget()
        coords_zoom_layout = QHBoxLayout(coords_zoom_widget)
        coords_zoom_layout.setContentsMargins(0, 0, 0, 0)
        coords_zoom_layout.setSpacing(10)
    
        self.input_manual_coords = QLineEdit("49,23173° S, 17,42791° V")
        self.input_manual_coords.textChanged.connect(self.test_coordinate_parsing)
        coords_zoom_layout.addWidget(self.input_manual_coords, 1)
    
        self.btn_coords_from_heic = QPushButton("Z HEIC…")
        self.btn_coords_from_heic.setToolTip("Vybrat HEIC soubor a vyplnit GPS do pole Ruční souřadnice")
        self.btn_coords_from_heic.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_coords_from_heic.setFixedHeight(int(self.btn_coords_from_heic.sizeHint().height() * 1.10))  # mírně vyšší kvůli čitelnosti
        self.btn_coords_from_heic.clicked.connect(self.on_pick_heic_and_fill_manual_coords)
        coords_zoom_layout.addWidget(self.btn_coords_from_heic)
    
        coords_zoom_layout.addWidget(QLabel("Zoom:"))
        self.spin_preview_zoom = QSpinBox()
        self.spin_preview_zoom.setRange(10, 19)
        self.spin_preview_zoom.setValue(19)
        self.spin_preview_zoom.setMinimumWidth(60)
        self.spin_preview_zoom.setMinimumHeight(24)
        self.spin_preview_zoom.valueChanged.connect(self._on_gps_param_changed)
        coords_zoom_layout.addWidget(self.spin_preview_zoom)
    
        group_layout.addWidget(coords_zoom_widget, 0, 1)
    
        # Informace o parsovaných souřadnicích (ponecháno)
        self.label_parsed_coords = QLabel("Parsované: 49.231730° S, 17.427910° V")
        self.label_parsed_coords.setStyleSheet("QLabel { color: #2196F3; font-style: italic; }")
        group_layout.addWidget(self.label_parsed_coords, 1, 0, 1, 2)
    
        group.setLayout(group_layout)
        layout.addWidget(group)
    
        # — Náhled mapy
        map_group = QGroupBox("🗺️ Náhled mapy")
        map_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        map_layout = QVBoxLayout()
        map_layout.setContentsMargins(8, 6, 8, 8)
        map_layout.setSpacing(6)
    
        self.map_progress_bar = QProgressBar()
        self.map_progress_bar.setVisible(False)
        self.map_progress_bar.setMinimumHeight(14)
        self.map_progress_bar.setStyleSheet("""
        QProgressBar { border: 1px solid #bbb; border-radius: 4px; text-align: center; font-weight: bold; font-size: 10px; }
        QProgressBar::chunk { background-color: #4CAF50; border-radius: 3px; }
        """)
        map_layout.addWidget(self.map_progress_bar)
    
        self._map_aspect = 1000 / 310
        self.map_scroll_area = QScrollArea()
        self.map_scroll_area.setWidgetResizable(True)
        self.map_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.map_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.map_scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
        self.map_label = QLabel()
        self.map_label.setAlignment(Qt.AlignCenter)
        self.map_label.setMinimumSize(1, 1)
        self.map_label.setStyleSheet("QLabel { border: 1px solid #bbb; background-color: #f5f5f5; font-size: 13px; color: #666; }")
        self.map_label.setText("🗺️ Mapa se načte automaticky při změně souřadnic nebo zoomu")
        self.map_scroll_area.setWidget(self.map_label)
    
        # Klikání do mapy (ponecháno)
        class _MapClickFilter(QObject):
            def __init__(self, outer):
                super().__init__(outer)
                self.outer = outer
            def eventFilter(self, obj, event):
                if event.type() == QEvent.MouseButtonPress and getattr(self.outer, "map_label", None) is obj:
                    try:
                        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                        self.outer._on_map_click_get_coords(pos)
                    except Exception:
                        pass
                return False
        self._map_click_filter = _MapClickFilter(self)
        self.map_label.installEventFilter(self._map_click_filter)
    
        # Překryvné tlačítko ↻ vpravo nahoře (instalováno do viewportu)
        self._install_gps_refresh_button()
        map_layout.addWidget(self.map_scroll_area, 1)
    
        # UPOZORNĚNÍ (indikace nesouladu náhledu s GUI)
        self.gps_warning_label = QLabel("")
        self.gps_warning_label.setStyleSheet("QLabel { color: #c62828; font-weight: bold; font-size: 13px; }")
        self.gps_warning_label.setAlignment(Qt.AlignRight)
        map_layout.addWidget(self.gps_warning_label)
    
        self.map_status_label = QLabel("📍 Zadejte souřadnice pro zobrazení mapy")
        self.map_status_label.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        map_layout.addWidget(self.map_status_label)
    
        map_group.setLayout(map_layout)
        layout.addWidget(map_group, 1)
    
        # Přidat tab a uložit index pro lazy-load
        idx = self.tabs.addTab(tab, "📍 GPS")
        self._gps_tab_index = idx
    
        # Debounce timer pro resize viewportu
        self._map_resize_timer = QTimer(self)
        self._map_resize_timer.setSingleShot(True)
        self._map_resize_timer.timeout.connect(self._on_gps_param_changed)
    
        # Event filter pro viewport (kvůli resize)
        class _MapResizeFilter(QObject):
            def __init__(self, outer):
                super().__init__(outer)
                self.outer = outer
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Resize:
                    if not getattr(self.outer, "_map_preview_initialized", False):
                        return False
                    if getattr(self.outer, "_map_loading", False) or getattr(self.outer, "_suppress_map_resize", False):
                        return False
                    self.outer._map_resize_timer.start(120)
                    try:
                        if hasattr(self.outer, "_position_gps_refresh_button"):
                            self.outer._position_gps_refresh_button()
                        if hasattr(self.outer, "_update_mismatch_overlay_geometry"):
                            self.outer._update_mismatch_overlay_geometry()
                    except Exception:
                        pass
                return False
        self._map_resize_filter = _MapResizeFilter(self)
        self.map_scroll_area.viewport().installEventFilter(self._map_resize_filter)
    
        # Periodická kontrola konzistence náhledu
        QTimer.singleShot(0, self.monitor_gps_preview_consistency)

    def _on_tab_changed(self, index: int):
        """První vstup do záložky GPS jednorázově zkusí načíst cache (bez stahování)."""
        try:
            if hasattr(self, "_gps_tab_index") and index == self._gps_tab_index:
                if not getattr(self, "_map_preview_initialized", False):
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, self._init_gps_preview_first_show)
        except Exception:
            pass

    def _install_gps_refresh_button(self):
        """Vytvoří a ukotví malé kulaté Refresh tlačítko jako překryvné dítě viewportu (pravý horní roh)."""
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtCore import Qt, QObject, QEvent
    
        vp = self.map_scroll_area.viewport()
    
        # vytvořit tlačítko, pokud ještě neexistuje
        if not hasattr(self, "btn_gps_refresh") or self.btn_gps_refresh is None:
            self.btn_gps_refresh = QPushButton("↻", parent=vp)
            self.btn_gps_refresh.setToolTip("Obnovit náhled mapy")
            self.btn_gps_refresh.setFixedSize(28, 28)
            self.btn_gps_refresh.setCursor(Qt.PointingHandCursor)
            # tmavě modrá s 50% transparentností + bílý text/lem
            self.btn_gps_refresh.setStyleSheet("""
                QPushButton {
                    background-color: rgba(10, 36, 99, 128);  /* 50% alpha */
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 180);
                    border-radius: 14px;
                    font-weight: 700;
                }
                QPushButton:hover  { background-color: rgba(10, 36, 99, 160); }
                QPushButton:pressed{ background-color: rgba(10, 36, 99, 200); }
                QPushButton:disabled { background-color: rgba(10, 36, 99, 90); color: rgba(255,255,255,140); }
            """)
            # zachovat klikatelnost a být nad obsahem
            self.btn_gps_refresh.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            self.btn_gps_refresh.clicked.connect(self._on_gps_refresh_click)
            self.btn_gps_refresh.show()
            self.btn_gps_refresh.raise_()
    
        # přesné ukotvení vpravo nahoře uvnitř viewportu
        def _position():
            try:
                margin = 8
                bx = max(0, vp.width() - self.btn_gps_refresh.width() - margin)
                by = margin
                self.btn_gps_refresh.move(bx, by)
                self.btn_gps_refresh.raise_()
            except Exception:
                pass
    
        # zpřístupnit jako metodu instance a okamžitě srovnat
        self._position_gps_refresh_button = _position
        _position()
    
        # event filter pro auto-reposition při Show/Resize viewportu
        class _RefreshPosFilter(QObject):
            def __init__(self, outer):
                super().__init__(outer)
                self.outer = outer
            def eventFilter(self, obj, event):
                if event.type() in (QEvent.Show, QEvent.Resize):
                    try:
                        self.outer._position_gps_refresh_button()
                    except Exception:
                        pass
                return False
    
        # nainstalovat filtr (jen jednou)
        if not hasattr(self, "_gps_refresh_pos_filter"):
            self._gps_refresh_pos_filter = _RefreshPosFilter(self)
            vp.installEventFilter(self._gps_refresh_pos_filter)

    def _on_gps_refresh_click(self):
        """Ruční refresh náhledu mapy podle aktuálních hodnot v GUI (souřadnice, zoom, styl/velikost značky)."""
        try:
            self.update_map_preview()
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("🔄 Ruční refresh náhledu mapy proveden", "info")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při refresh náhledu: {e}", "error")

    def update_map_preview(self):
        """Aktualizuje náhled mapy v záložce GPS a nastaví _pending_map_req na normalizovanou pětici parametrů."""
        try:
            # Kontrola UI prvků
            if not hasattr(self, "map_label") or not hasattr(self, "map_scroll_area"):
                return
    
            # 1) Načti GUI → parsuj do float lat/lon (pro konzistenci s celou app)
            coords_text = (self.input_manual_coords.text() if hasattr(self, "input_manual_coords") else "").strip()
            zoom = int(self.spin_preview_zoom.value()) if hasattr(self, "spin_preview_zoom") else 18
            marker_style = self.get_marker_style_from_settings() if hasattr(self, "get_marker_style_from_settings") else "dot"
            marker_size = self.get_marker_size_from_settings() if hasattr(self, "get_marker_size_from_settings") else 10
    
            parsed = self.parse_coordinates(coords_text)
            if not parsed:
                self.map_label.setText("❌ Neplatné souřadnice. Opravte vstup.")
                self.map_progress_bar.setVisible(False)
                return
            lat, lon = parsed
    
            # 2) Handshake: ULOŽ pending na normalizovanou pětici (zaokrouhlené floaty + inty + styl)
            norm_lat = round(float(lat), 6)
            norm_lon = round(float(lon), 6)
            norm_zoom = int(zoom)
            norm_style = "cross" if str(marker_style).lower().strip() == "cross" else "dot"
            norm_size = int(marker_size)
            self._pending_map_req = (norm_lat, norm_lon, norm_zoom, norm_style, norm_size)
    
            # 3) Rozměry viewportu: SPOČÍTAT DŘÍVE NEŽ ZOBRAZÍME PROGRESS BAR
            target_w, target_h = self._compute_map_target_size()
    
            # 4) Progress bar (až po výpočtu velikosti)
            self.map_progress_bar.setVisible(True)
            self.map_progress_bar.setValue(0)
            self.map_progress_bar.setFormat("Načítám mapu…")
    
            # 5) Asynchronní načtení mapy
            self._map_preview_initialized = True
            self._map_loading = True
            try:
                self.load_map_preview_async(norm_lat, norm_lon, norm_zoom, target_w, target_h)
            except Exception as e:
                self.map_label.setText(f"❌ Mapu nelze načíst: {str(e)}")
            finally:
                self._map_loading = False
    
        except Exception as e:
            if hasattr(self, "map_label"):
                self.map_label.setText(f"❌ Chyba při náhledu: {str(e)}")

    def parse_coords_from_text(self, text: str):
        """
        Wrapper pro jednotné parsování souřadnic — deleguje na self.parse_coordinates,
        aby bylo chování totožné v celé aplikaci.
        Vrací (lat, lon) v desetinných stupních nebo None.
        """
        try:
            return self.parse_coordinates(text)
        except Exception:
            return None

    def _compute_map_target_size(self):
        """
        Cílová velikost náhledu je přesně velikost viewportu ScrollArea
        mínus malá rezerva; pokud je aktuálně viditelný progress bar,
        přičtěte jeho výšku, aby výsledná mozaika pokryla celou sekci i po jeho skrytí.
        """
        vp = self.map_scroll_area.viewport() if hasattr(self, 'map_scroll_area') else None
        if not vp:
            return 1000, 310
        try:
            fw = int(getattr(self.map_scroll_area, "frameWidth", lambda: 0)())
        except Exception:
            fw = 0
    
        avail_w = max(50, vp.width() - 2 * fw - 1)  # -1px rezerva
        avail_h = max(50, vp.height() - 2 * fw - 1) # -1px rezerva
    
        # Kompenzace za progress bar pokud je viditelný
        try:
            if hasattr(self, "map_progress_bar") and self.map_progress_bar.isVisible():
                avail_h = int(avail_h + max(0, self.map_progress_bar.height()))
        except Exception:
            pass
    
        return int(avail_w), int(avail_h)


    def load_map_preview_async(self, lat, lon, zoom, target_w, target_h):
        """Asynchronní načtení mozaiky dlaždic s okrajem a přesným výřezem na velikost viewportu."""
        from PySide6.QtCore import QThread, Signal

        class MapPreviewThread(QThread):
            map_loaded = Signal(object, dict) # PIL Image, metadata
            error_occurred = Signal(str)
            progress_updated = Signal(int, str)

            def __init__(self, lat, lon, zoom, marker_size, marker_style, tw, th, parent=None):
                super().__init__(parent)
                self.lat = float(lat)
                self.lon = float(lon)
                self.zoom = int(zoom)
                self.marker_size = int(marker_size)
                self.marker_style = str(marker_style or "dot")
                self.target_width = int(tw)
                self.target_height = int(th)
                self.tile_size = 256

            def _interrupted(self):
                return self.isInterruptionRequested()

            def run(self):
                try:
                    import math, io, time, requests
                    from PIL import Image
                    from PIL import Image as PILImage

                    t0 = time.time()
                    n = 2.0 ** self.zoom
                    ts = self.tile_size
                    lat_rad = math.radians(self.lat)
                    tile_x_f = (self.lon + 180.0) / 360.0 * n
                    tile_y_f = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n

                    center_px_x = tile_x_f * ts
                    center_px_y = tile_y_f * ts

                    left = int(math.floor(center_px_x - self.target_width / 2))
                    top = int(math.floor(center_px_y - self.target_height / 2))
                    right = left + self.target_width
                    bottom = top + self.target_height

                    left_tile = int(math.floor(left / ts))
                    top_tile = int(math.floor(top / ts))
                    right_tile = int(math.floor((right - 1) / ts))
                    bottom_tile = int(math.floor((bottom - 1) / ts))

                    margin = 1
                    ext_left_tile = left_tile - margin
                    ext_top_tile = top_tile - margin
                    ext_right_tile = right_tile + margin
                    ext_bottom_tile = bottom_tile + margin

                    tiles_x = ext_right_tile - ext_left_tile + 1
                    tiles_y = ext_bottom_tile - ext_top_tile + 1

                    full_width = tiles_x * ts
                    full_height = tiles_y * ts

                    self.progress_updated.emit(10, f"Příprava dlaždic {tiles_x}×{tiles_y}…")

                    full_image = PILImage.new('RGB', (full_width, full_height), color='lightgray')

                    total = tiles_x * tiles_y
                    done = 0
                    ok = 0
                    err = 0
                    bytes_dl = 0
                    headers = {'User-Agent': 'OSM Map Generator - Preview/1.3'}
                    self.progress_updated.emit(20, f"Stahuji {total} dlaždic…")

                    for tx in range(ext_left_tile, ext_right_tile + 1):
                        for ty in range(ext_top_tile, ext_bottom_tile + 1):
                            if self._interrupted(): return

                            xt = int(tx % int(n))
                            if ty < 0 or ty >= int(n):
                                done += 1
                                if done % 3 == 0:
                                    pct = 20 + int(done / max(1, total) * 60)
                                    self.progress_updated.emit(pct, f"Stahování… {done}/{total}")
                                continue
                            
                            url = f"https://tile.openstreetmap.org/{self.zoom}/{xt}/{ty}.png"
                            try:
                                r = requests.get(url, headers=headers, timeout=8)
                                if r.status_code == 200 and r.content:
                                    img = PILImage.open(io.BytesIO(r.content)).convert('RGB')
                                    px = (tx - ext_left_tile) * ts
                                    py = (ty - ext_top_tile) * ts
                                    full_image.paste(img, (px, py))
                                    ok += 1
                                    bytes_dl += len(r.content or b"")
                                else:
                                    err += 1
                            except Exception:
                                err += 1
                            
                            done += 1
                            if done % 3 == 0:
                                pct = 20 + int(done / max(1, total) * 60)
                                self.progress_updated.emit(pct, f"Stahování… {done}/{total}")

                    crop_left = left - ext_left_tile * ts
                    crop_top = top - ext_top_tile * ts
                    
                    cropped = full_image.crop((
                        crop_left,
                        crop_top,
                        crop_left + self.target_width,
                        crop_top + self.target_height
                    ))

                    # === BLOK PRO KRESLENÍ ZNAČKY BYL ODSTRANĚN ===
                    # Vlákno nyní vrací čistý obrázek bez značky.
                    # O vykreslení se postará on_map_preview_loaded.

                    t1 = time.time()
                    meta = {
                        "lat": self.lat,
                        "lon": self.lon,
                        "zoom": self.zoom,
                        "marker_px": self.marker_size,
                        "marker_style": self.marker_style,
                        "target_wh": (self.target_width, self.target_height),
                        "center_tile_frac": (tile_x_f, tile_y_f),
                        "center_px": (center_px_x, center_px_y),
                        "tile_span_xy": (tiles_x, tiles_y),
                        "tile_range": (ext_left_tile, ext_top_tile, ext_right_tile, ext_bottom_tile),
                        "download": {
                            "total_tiles": total,
                            "ok_tiles": ok,
                            "err_tiles": err,
                            "bytes": bytes_dl,
                            "elapsed_ms": int(round((t1 - t0) * 1000)),
                        },
                    }
                    self.progress_updated.emit(100, "Dokončeno")
                    
                    if not self._interrupted():
                        self.map_loaded.emit(cropped, meta) # Emituje čistý PIL.Image

                except Exception as e:
                    if not self._interrupted():
                        self.error_occurred.emit(str(e))

        marker_size = self.get_marker_size_from_settings()
        marker_style = self.get_marker_style_from_settings()
        
        self._map_thread = MapPreviewThread(lat, lon, zoom, marker_size, marker_style, target_w, target_h, parent=self)
        self._map_thread.progress_updated.connect(lambda p, msg: (self.map_progress_bar.setValue(p), self.map_progress_bar.setFormat(msg)))
        self._map_thread.map_loaded.connect(self.on_map_preview_loaded)
        self._map_thread.error_occurred.connect(self.on_map_preview_error)
        self._map_thread.start()

    def on_map_progress_updated(self, progress, message):
        """Handler pro aktualizaci progress baru při načítání mapy"""
        self.map_progress_bar.setValue(progress)
        self.map_progress_bar.setFormat(f"{message} ({progress}%)")
        
        # Aktualizace status labelu
        self.map_status_label.setText(f"⏳ {message}")
    
    def on_map_loaded(self, pixmap):
        """Handler pro úspěšné načtení mapy"""
        self.map_label.setPixmap(pixmap)
        self.map_label.setText("")  # Vymazání textu
    
        # Skrytí progress baru a aktualizace statusu
        self.map_progress_bar.setVisible(False)
    
        # Získání aktuálních souřadnic pro status
        coord_text = self.input_manual_coords.text().strip()
        result = self.parse_coordinates(coord_text)
        if result:
            lat, lon = result
            zoom = self.spin_preview_zoom.value()
            marker_size = self.get_marker_size_from_settings()
    
            # ✅ ZMĚNA: použij (one-shot) uložený zdrojový HEIC soubor, pokud existuje
            heic_note = ""
            try:
                from pathlib import Path
                src_file = getattr(self, "_last_gps_file", None)
                if src_file:  # pokud byl HEIC vybrán před tímto renderem
                    heic_note = f" • soubor: {Path(src_file).name}"
                    # one-shot – po použití vyčisti, ať se název netáhne k dalším refreshům
                    self._last_gps_file = None
            except Exception:
                pass
    
            self.map_status_label.setText(
                f"✅ Mapa načtena: {lat:.6f}°, {lon:.6f}° (zoom: {zoom}, marker: {marker_size}px){heic_note}"
            )
        else:
            self.map_status_label.setText("✅ Mapa úspěšně načtena")
    
    def on_map_error(self, error_message):
        """Handler pro chybu při načítání mapy"""
        self.map_label.setText(f"❌ Chyba při načítání mapy:\n{error_message}")
        
        # Skrytí progress baru a aktualizace statusu
        self.map_progress_bar.setVisible(False)
        self.map_status_label.setText(f"❌ Chyba: {error_message}")
        
        if hasattr(self, 'log_widget'):
            self.log_widget.add_log(f"❌ Chyba při načítání náhledu mapy: {error_message}", "error")
        
    def get_marker_size_from_settings(self):
        """Získání velikosti markeru z nastavení základního tabu"""
        try:
            # Pokud existuje spinner pro velikost bodu v základních nastaveních
            if hasattr(self, 'spin_marker_size'):
                return self.spin_marker_size.value()
            
            # Pokud existuje jiný element pro velikost bodu
            if hasattr(self, 'marker_size_input'):
                return int(self.marker_size_input.text() or 10)
            
            # Pokud existuje v current_settings
            if 'marker_size' in self.current_settings:
                return self.current_settings['marker_size']
            
            # Výchozí velikost
            return 10
            
        except Exception as e:
            print(f"Chyba při získávání velikosti markeru: {e}")
            return 10  # Výchozí velikost při chybě
        
    @Slot(object, dict)
    def on_map_preview_loaded(self, image_data, meta):
        """Zobrazení načtené mapy + vykreslení značky + uložení cache a handshake."""
        # Potřebné importy pro konverzi
        from PIL.ImageQt import ImageQt
        from PySide6.QtCore import QBuffer
        import io

        try:
            pil_image = None
            # OPRAVA: Zjistíme, jestli máme PIL.Image nebo QPixmap z cache
            if isinstance(image_data, Image.Image):
                # Je to PIL obrázek, můžeme ho rovnou použít
                pil_image = image_data.copy()
            elif isinstance(image_data, QPixmap):
                # Je to QPixmap z cache, převedeme ho na PIL obrázek pro kreslení
                qt_image = image_data.toImage()
                buffer = QBuffer()
                buffer.open(QBuffer.OpenModeFlag.ReadWrite)
                qt_image.save(buffer, "PNG")
                pil_image = Image.open(io.BytesIO(buffer.data()))
                # Zajistíme, že je obrázek v RGB formátu pro kreslení
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')

            pixmap = None
            if pil_image:
                # Nyní máme jistotu, že 'pil_image' je platný obrázek pro kreslení
                draw = ImageDraw.Draw(pil_image)

                marker_size_px = meta.get('marker_px', self.get_marker_size_from_settings())
                marker_style = meta.get('marker_style', self.get_marker_style_from_settings())

                radius = marker_size_px / 2.0
                center_x, center_y = pil_image.width // 2, pil_image.height // 2

                if marker_style == "cross":
                    thickness = max(1, round(marker_size_px / 7.0))
                    draw.line([(center_x - radius, center_y), (center_x + radius, center_y)], fill='white', width=thickness + 2)
                    draw.line([(center_x, center_y - radius), (center_x, center_y + radius)], fill='white', width=thickness + 2)
                    draw.line([(center_x - radius, center_y), (center_x + radius, center_y)], fill='black', width=thickness)
                    draw.line([(center_x, center_y - radius), (center_x, center_y + radius)], fill='black', width=thickness)
                else:  # dot
                    bbox = [center_x - radius, center_y - radius, center_x + radius, center_y + radius]
                    draw.ellipse(bbox, fill='black', outline='white', width=1)

                # Převedeme upravený PIL obrázek zpět na QPixmap pro zobrazení
                pixmap = QPixmap.fromImage(ImageQt(pil_image))

            if pixmap:
                self._suppress_map_resize = True
                self.map_label.setPixmap(pixmap)
                self.map_label.setMinimumSize(pixmap.size())
            else:
                self.map_label.setText("Chyba zobrazení")

        finally:
            QTimer.singleShot(80, lambda: setattr(self, "_suppress_map_resize", False))

        self.map_progress_bar.setVisible(False)
        self._map_loading = False
        
        req = getattr(self, "_pending_map_req", None)
        if req is not None:
            self._last_map_req = req
            self._pending_map_req = None

        if pixmap and (self._last_map_req or req):
            self.save_preview_cache(pixmap, self._last_map_req or req)

        self._preview_source = "generated" if isinstance(image_data, Image.Image) else "cache"
        try:
            last = getattr(self, "_last_map_req", None)
            cur = self._get_normalized_gps_preview_tuple()
            self._set_consistency_ui(self._preview_source, (cur is not None and last is not None and cur == last))
        except Exception:
            pass

        self.map_status_label.setText(
            f"✅ Mapa načtena: {self.input_manual_coords.text()} (zoom: {meta.get('zoom')}, bod: {meta.get('marker_px')}px)"
        )

        if hasattr(self, 'log_widget') and self.log_widget is not None and self._preview_source == "generated":
            try:
                tw, th = meta.get("target_wh", (pixmap.width(), pixmap.height()))
                tiles_x, tiles_y = meta.get("tile_span_xy", (0, 0))
                l, t, r, b = meta.get("tile_range", (0, 0, 0, 0))
                d = meta.get("download", {})
                elapsed = d.get("elapsed_ms", 0)
                kb = d.get("bytes", 0) / 1024.0
                ok_tiles = d.get("ok_tiles", 0)
                err_tiles = d.get("err_tiles", 0)
                total_tiles = d.get("total_tiles", 0)
                fracx, fracy = meta.get("center_tile_frac", (0.0, 0.0))

                self.log_widget.add_log(f"🗺️ Náhled mapy: {tw}×{th}px • zoom Z{meta.get('zoom')} • marker {meta.get('marker_px')}px", "success")
                self.log_widget.add_log(f" 📍 Lat/Lon: {meta.get('lat'):.6f}°, {meta.get('lon'):.6f}° • střed tile: x={fracx:.4f}, y={fracy:.4f}", "info")
                self.log_widget.add_log(f" 🧩 Dlaždice: grid {tiles_x}×{tiles_y} (rozsah: x {l}→{r}, y {t}→{b}) • staženo {ok_tiles}/{total_tiles}, chyby {err_tiles}", "info")
                self.log_widget.add_log(f" ⏱️ Čas: {elapsed} ms • {kb:.1f} KB", "info")
            except Exception:
                self.log_widget.add_log("🗺️ Náhled mapy načten.", "success")

    @Slot(str)
    def on_map_preview_error(self, error_message):
        """Chyba při načítání náhledu: bezpečné odemknutí stavů, skrytí progress a čitelný stav UI."""
        try:
            self._map_loading = False
            self._pending_map_req = None
        except Exception:
            pass
    
        try:
            if hasattr(self, "map_label") and self.map_label:
                self.map_label.setText("❌ Chyba při načítání mapy")
            if hasattr(self, "map_status_label") and self.map_status_label:
                self.map_status_label.setText(f"❌ {error_message}")
            if hasattr(self, "map_progress_bar") and self.map_progress_bar:
                self.map_progress_bar.setVisible(False)
        except Exception:
            pass
    
        if hasattr(self, 'log_widget'):
            self.log_widget.add_log(f"❌ Chyba náhledu mapy: {error_message}", "error")
    
        # Indikace neshody náhledu vs GUI (pokud je k dispozici)
        try:
            self._set_consistency_ui(getattr(self, "_preview_source", "generated"), False)
        except Exception:
            pass

    # === OVLÁDACÍ PANEL A PREVIEW ===

    def create_control_panel(self):
        """UPRAVENO: Spodní ovládací panel je zrušen – vrací neviditelný spacer."""
        spacer = QWidget()
        spacer.setFixedHeight(0)  # nezabírá téměř žádné místo [1]
        return spacer

    
    def create_vertical_separator(self):
        """NOVÁ FUNKCE: Vytvoření vertikálního oddělovače"""
        separator = QWidget()
        separator.setFixedWidth(2)
        separator.setStyleSheet("background-color: #cccccc; margin: 5px 10px;")
        return separator
    
    def set_default_values(self):
        """UPRAVENÁ FUNKCE: Nastavení defaultních hodnot podle specifikace včetně značky Puntík 7 px."""
        try:
            self.log_widget.add_log("🔄 Nastavuji defaultní hodnoty...", "info")
    
            # === VÝSTUPNÍ NASTAVENÍ ===
            self.spin_width.setValue(7.1)  # šířka 7,1 cm
            self.spin_height.setValue(5.0)  # výška 5 cm
            self.spin_dpi.setValue(240)  # DPI 420
    
            # Výstupní složka
            default_output = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/"
            self.input_output_dir.setText(default_output)
    
            # Automatické generování ID
            self.check_auto_id.setChecked(True)
            self.on_auto_id_toggled(True)
    
            # === ZÁKLADNÍ NASTAVENÍ ===
            default_file_path = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/ZLíN_JSVAHY-UTB-U5-001+VlevoPredHlavnimVchodem+GPS49.23091S+17.65691V+Z18+00001.png"
            self.input_photo.setText(default_file_path)
            self.input_id_lokace.setText("ZLIN_JSVAHY-UTB-U5-001")
            self.input_popis.setText("Před hlavním vchodem U5 za lavečkama")
            self.spin_watermark.setValue(2.5)  # 2,5 mm
    
            # Velikost a styl GPS značky – NOVÉ defaulty: Puntík, 7 px
            self.spin_marker_size.setValue(7)
            if hasattr(self, "combo_marker_style"):
                try:
                    # 0 = Puntík, 1 = Křížek
                    self.combo_marker_style.setCurrentIndex(0)
                except Exception:
                    pass
    
            # Zoom level
            self.spin_zoom.setValue(18)
    
            # Defaultní GPS souřadnice (z názvu souboru)
            self.input_manual_coords.setText("49.23091° S, 17.65691° V")
            self.test_coordinate_parsing()
    
            # Transparentnost mapy
            self.spin_opacity.setValue(1.0)
    
            # === POKROČILÁ NASTAVENÍ ===
            self.input_app_name.setText("OSM Map Generator - Čtyřlístky")
            self.input_email.setText("safronus@example.com")
            self.spin_delay.setValue(0.1)
            
            if hasattr(self, 'check_preview_row1'):
                self.check_preview_row1.setChecked(True)
            if hasattr(self, 'spin_preview_dpi_row1'):
                self.spin_preview_dpi_row1.setValue(240)
            if hasattr(self, 'check_preview_row2'):
                self.check_preview_row2.setChecked(False)
            if hasattr(self, 'spin_preview_dpi_row2'):
                self.spin_preview_dpi_row2.setValue(420)
                
            # ——— NOVÉ: výchozí stav anonymizace = NEZAŠKRTNUTO ———
            if hasattr(self, "checkbox_anonymni_lokace") and self.checkbox_anonymni_lokace is not None:
                self.checkbox_anonymni_lokace.setChecked(False)
    
            # Logování úspěchu
            self.log_widget.add_log("✅ Defaultní hodnoty nastaveny:", "success")
            self.log_widget.add_log(" 📐 Rozměry: 7,1 × 5,0 cm @ 240 DPI", "info")
            self.log_widget.add_log(" 📍 Lokace: ZLIN_JSVAHY-UTB-U5-001", "info")
            self.log_widget.add_log(" 📝 Popis: Před hlavním vchodem U5 za lavečkama", "info")
            self.log_widget.add_log(" 🔍 Zoom: 18, GPS bod: 7px (Puntík)", "info")
            self.log_widget.add_log(" 🔢 Automatické ID: Zapnuto", "info")
    
            # Kontrola existence referenčního souboru
            if Path(default_file_path).exists():
                self.log_widget.add_log(" 📁 Referenční soubor: Nalezen", "success")
            else:
                self.log_widget.add_log(" ⚠️ Referenční soubor: Nenalezen", "warning")
    
            # Vytvoření výstupní složky pokud neexistuje
            try:
                Path(default_output).mkdir(parents=True, exist_ok=True)
                self.log_widget.add_log(f" 📂 Výstupní složka: Nastavena na iCloud", "info")
                self.log_widget.add_log(f" {default_output}", "info")
            except Exception as e:
                self.log_widget.add_log(f" ❌ Chyba při vytváření výstupní složky: {e}", "error")
                # Fallback na Desktop
                fallback_output = str(Path.home() / "Desktop" / "Mapky_lokací")
                self.input_output_dir.setText(fallback_output)
                try:
                    Path(fallback_output).mkdir(parents=True, exist_ok=True)
                    self.log_widget.add_log(f" 📂 Fallback složka: {fallback_output}", "warning")
                except Exception as e2:
                    self.log_widget.add_log(f" ❌ Chyba i u fallback složky: {e2}", "error")
    
            # Zobrazení potvrzovacího dialogu
            QMessageBox.information(
                self,
                "Defaultní hodnoty nastaveny",
                "✅ Všechny hodnoty byly nastaveny na doporučené defaultní nastavení!\n\n"
                "📐 Rozměry: 7,1 × 5,0 cm @ 420 DPI\n"
                "📍 Lokace: ZLIN_UTB-U5-001\n"
                "📝 Popis: VlevoPredHlavnimVchodem\n"
                "🔍 Zoom: 18, GPS bod: 7px (Puntík)\n"
                "💧 Vodoznak: 2,5mm\n"
                "🔢 Automatické ID: Zapnuto\n"
                "📂 Výstup: iCloud/Čtyřlístky/Neroztříděné/\n\n"
                "Aplikace je připravena k použití!"
            )
    
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při nastavování defaultních hodnot: {e}", "error")
            QMessageBox.critical(
                self,
                "Chyba",
                f"Došlo k chybě při nastavování defaultních hodnot:\n\n{str(e)}"
            )

    def set_manual_gps_and_preview(self, lat: float, lon: float):
        """Pouze vyplní ruční GPS souřadnice v GUI; neotevírá GPS tab a nespouští náhled."""
        try:
            # Přepnout režim na ruční (bez přepnutí tabu)
            self.combo_coord_mode.setCurrentIndex(1)  # G - Ruční zadání
    
            # CZ formát S/J a V/Z
            lat_dir = 'J' if lat < 0 else 'S'
            lon_dir = 'Z' if lon < 0 else 'V'
            coord_text = f"{abs(lat):.5f}° {lat_dir}, {abs(lon):.5f}° {lon_dir}"
    
            # Jen nastavit text do pole a zvalidovat bez refresh
            self.input_manual_coords.setText(coord_text)
            self.test_coordinate_parsing()
    
            # Označit náhled jako zastaralý (uživatel použije ↻)
            self._flag_gps_preview_outdated()
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Nastavení GPS bez refresh: {e}", "warning")

    # PŘIDÁNO: Nové funkce pro preview
    def preview_input_image(self):
        """Zobrazení vstupního obrázku"""
        photo_path = self.input_photo.text()
        if not photo_path or not Path(photo_path).exists():
            QMessageBox.warning(self, "Chyba", "Vstupní soubor neexistuje nebo není zadán!")
            return
            
        try:
            dialog = ImageViewerDialog(photo_path, self)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nelze zobrazit obrázek:\n{str(e)}")

    def preview_result_image(self):
        """UPRAVENÁ FUNKCE: Zobrazení výsledného obrázku s auto 'Přizpůsobit' po otevření"""
        if hasattr(self, 'last_output_path') and self.last_output_path:
            try:
                from gui.image_viewer import ImageViewerDialog
                dialog = ImageViewerDialog(self.last_output_path, self, show_delete_button=True)
    
                # Napojení na smazání (původní kód)
                if hasattr(dialog, 'file_deleted'):
                    dialog.file_deleted.connect(self.on_result_file_deleted)
    
                # Event filter pro auto‑fit po Show/Resize
                class _AutoFitFilter(QObject):
                    def __init__(self, dlg):
                        super().__init__(dlg)
                        self.dialog = dlg
                        self.did_fit = False
    
                    def do_fit(self):
                        if self.did_fit:
                            return
                        # 1) Preferenčně zavolej veřejné metody, pokud existují
                        for attr in ('fit_to_window', 'fitInView', 'adjust_to_window', 'apply_fit'):
                            if hasattr(self.dialog, attr) and callable(getattr(self.dialog, attr)):
                                try:
                                    getattr(self.dialog, attr)()
                                    self.did_fit = True
                                    return
                                except Exception:
                                    pass
                        # 2) Fallback: najdi QAction a triggeruj podle textu
                        for act in self.dialog.findChildren(QAction):
                            try:
                                txt = (act.text() or "").replace("&", "")
                                if "Přizpůsobit" in txt or "Fit" in txt:
                                    act.trigger()
                                    self.did_fit = True
                                    return
                            except Exception:
                                continue
    
                    def eventFilter(self, obj, event):
                        et = event.type()
                        if et in (QEvent.Show, QEvent.ShowToParent):
                            # Hned po zobrazení a s mírným zpožděním znovu
                            QTimer.singleShot(0, self.do_fit)
                            QTimer.singleShot(120, self.do_fit)
                        elif et == QEvent.Resize and not self.did_fit:
                            QTimer.singleShot(0, self.do_fit)
                        return False
    
                f = _AutoFitFilter(dialog)
                dialog.installEventFilter(f)
    
                dialog.exec()
            except Exception as e:
                QMessageBox.critical(self, "Chyba", f"Nelze zobrazit výsledek:\n{str(e)}")
        else:
            QMessageBox.information(self, "Info", "Zatím nebyl vygenerován žádný výsledek.")

    @Slot(str)
    def on_processing_finished(self, output_path):
        # … stávající kód nahoře …
    
        # 1) Zapiš metadata (cm/DPI + marker) do PNG stejně jako u přegenerování
        try:
            self.embed_output_params_into_png(output_path)
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(
                    f"⚠️ Metadata (cm/DPI) do PNG selhala pro {Path(output_path).name}: {e}", "warning"
                )
    
        # 2) Pokračuj jako dříve
        self.processor_thread.quit()
        self.processor_thread.wait()
        self.btn_start_secondary.setEnabled(True)
        self.btn_stop_secondary.setEnabled(False)
        self.tabs.setEnabled(True)
        self.last_output_path = output_path
        self.refresh_file_tree()
        self.progress_bar.setValue(100)
        self.progress_bar.setVisible(False)
        self.status_widget.set_status("success", "Dokončeno!")
        self.log_widget.add_log(f"✅ Mapa úspěšně vygenerována: {output_path}", "success")
    
        reply = QMessageBox.question(
            self,
            "Hotovo",
            f"Mapa byla úspěšně vygenerována!\n\n{output_path}\n\nChcete si prohlédnout výsledek?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.preview_result_image_with_delete()
            
    def embed_output_params_into_png(self, output_path: str):
        """Zapíše do PNG metadat výstupní parametry (cm, DPI) a také Marker_Style a Marker_Size_Px; pouze pro .png."""
        try:
            p = Path(output_path)
            if p.suffix.lower() != ".png" or not p.exists():
                return
    
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
    
            width_cm = float(self.spin_width.value())
            height_cm = float(self.spin_height.value())
            dpi_val = int(self.spin_dpi.value())
            marker_style = self.get_marker_style_from_settings()  # 'dot' | 'cross'
            marker_size_px = int(self.get_marker_size_from_settings())
    
            with Image.open(p) as im:
                if im.format != "PNG":
                    return
    
                pnginfo = PngInfo()
                existing_text = getattr(im, "text", {}) or {}
                for k, v in existing_text.items():
                    try:
                        pnginfo.add_text(str(k), str(v))
                    except Exception:
                        pass
    
                # Původní metadata
                pnginfo.add_text("Output_Width_cm", f"{width_cm:.2f}")
                pnginfo.add_text("Output_Height_cm", f"{height_cm:.2f}")
                pnginfo.add_text("Output_DPI", f"{dpi_val}")
    
                # NOVÉ: typ a velikost značky
                pnginfo.add_text("Marker_Style", marker_style)
                pnginfo.add_text("Marker_Size_Px", f"{marker_size_px}")
    
                tmp_path = p.with_suffix(".tmp.png")
                im.save(tmp_path, format="PNG", pnginfo=pnginfo, dpi=(dpi_val, dpi_val))
                os.replace(tmp_path, p)
        except Exception as e:
            raise

    def preview_result_image_with_delete(self):
        """NOVÁ FUNKCE: Náhled výsledku se smazáním a auto 'Přizpůsobit' po otevření"""
        if hasattr(self, 'last_output_path') and self.last_output_path:
            try:
                from gui.image_viewer import ImageViewerDialog
                dialog = ImageViewerDialog(self.last_output_path, self, show_delete_button=True)
                if hasattr(dialog, 'file_deleted'):
                    dialog.file_deleted.connect(self.on_result_file_deleted)
    
                class _AutoFitFilter(QObject):
                    def __init__(self, dlg):
                        super().__init__(dlg)
                        self.dialog = dlg
                        self.did_fit = False
                    def do_fit(self):
                        if self.did_fit:
                            return
                        for attr in ('fit_to_window', 'fitInView', 'adjust_to_window', 'apply_fit'):
                            if hasattr(self.dialog, attr) and callable(getattr(self.dialog, attr)):
                                try:
                                    getattr(self.dialog, attr)()
                                    self.did_fit = True
                                    return
                                except Exception:
                                    pass
                        for act in self.dialog.findChildren(QAction):
                            try:
                                txt = (act.text() or "").replace("&", "")
                                if "Přizpůsobit" in txt or "Fit" in txt:
                                    act.trigger()
                                    self.did_fit = True
                                    return
                            except Exception:
                                continue
                    def eventFilter(self, obj, event):
                        et = event.type()
                        if et in (QEvent.Show, QEvent.ShowToParent):
                            QTimer.singleShot(0, self.do_fit)
                            QTimer.singleShot(120, self.do_fit)
                        elif et == QEvent.Resize and not self.did_fit:
                            QTimer.singleShot(0, self.do_fit)
                        return False
    
                f = _AutoFitFilter(dialog)
                dialog.installEventFilter(f)
    
                dialog.exec()
            except Exception as e:
                QMessageBox.critical(self, "Chyba", f"Nelze zobrazit výsledek:\n{str(e)}")
        else:
            QMessageBox.information(self, "Info", "Zatím nebyl vygenerován žádný výsledek.")
            
    def on_result_file_deleted(self, file_path):
        """UPRAVENÁ FUNKCE: Reakce na smazání výsledného souboru – bez spodních tlačítek"""
        try:
            # Vymazání cesty k poslednímu výsledku
            self.last_output_path = None
            
            # Refresh stromu
            self.refresh_file_tree()
            
            # Logování
            self.log_widget.add_log(f"🗑️ Vygenerovaný soubor byl smazán: {Path(file_path).name}", "warning")
            
            # Status
            self.status_widget.set_status("idle", "Připraven")
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při zpracování smazání souboru: {e}", "error")


    # === TABY NASTAVENÍ A MONITORING ===

    def create_settings_widget(self):
        """Vytvoření widgetu s nastaveními + lazy‑load pro náhled mapy v GPS záložce."""
        self.tabs = QTabWidget()
        # Guard: dokud není záložka GPS poprvé otevřena, náhled se nenačítá
        self._map_preview_initialized = False
    
        # Taby
        self.create_basic_settings_tab()
        self.create_gps_settings_tab()      # uvnitř se uloží self._gps_tab_index
        self.create_output_settings_tab()
        self.create_advanced_settings_tab()
    
        # První otevření GPS tab spustí náhled jednorázově
        self.tabs.currentChanged.connect(self._on_tab_changed)  # QTabWidget.currentChanged(int)
        return self.tabs

   
    def validate_icloud_path(self, path):
        """NOVÁ FUNKCE: Validace dostupnosti iCloud cesty"""
        try:
            path_obj = Path(path)
            
            # Kontrola existence iCloud složky
            icloud_base = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
            
            if not icloud_base.exists():
                self.log_widget.add_log("⚠️ iCloud Drive není dostupný na tomto systému", "warning")
                return False
                
            # Kontrola existence cílové složky
            if not path_obj.exists():
                self.log_widget.add_log("📁 Vytvářím iCloud složku pro výstup...", "info")
                path_obj.mkdir(parents=True, exist_ok=True)
                
            # Test zápisu
            test_file = path_obj / ".test_write"
            try:
                test_file.write_text("test")
                test_file.unlink()
                self.log_widget.add_log("✅ iCloud složka je dostupná pro zápis", "success")
                return True
            except Exception as e:
                self.log_widget.add_log(f"❌ Nelze zapisovat do iCloud složky: {e}", "error")
                return False
                
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při validaci iCloud cesty: {e}", "error")
            return False
        
    def create_basic_settings_tab(self):
        """Základní nastavení – jemně větší prvky (+5 px) a menší mezery mezi sekcemi pro lepší fit ve FullHD."""
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QGroupBox, QGridLayout, QLabel, QLineEdit,
            QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QSizePolicy, QCheckBox
        )
    
        # Helper: jemně navýšit minimální výšku prvku o ~5 px
        def bump_h(w, extra=5):
            try:
                h = w.sizeHint().height() + int(extra)
                w.setMinimumHeight(h)
            except Exception:
                pass
    
        tab = QWidget()
        layout = QVBoxLayout(tab)
        # Menší vertikální mezery mezi skupinami + menší top/bottom okraje
        layout.setSpacing(4)
        layout.setContentsMargins(8, 6, 8, 6)
    
        # === Skupina - Vstupní soubor ===
        self.group_input_file = QGroupBox("📁 Vstupní soubor")
        self.group_input_layout = QGridLayout()
        # Kompaktní vnitřní odsazení a spacing uvnitř sekce
        self.group_input_layout.setContentsMargins(8, 6, 8, 6)
        self.group_input_layout.setHorizontalSpacing(6)
        self.group_input_layout.setVerticalSpacing(4)
        # Pravý sloupec pružný
        self.group_input_layout.setColumnStretch(0, 0)
        self.group_input_layout.setColumnStretch(1, 1)
    
        self.label_input_file = QLabel("Fotka pro GPS:")
        self.group_input_layout.addWidget(self.label_input_file, 0, 0)
    
        self.input_photo = QLineEdit("1135_2023-07-01_1724.HEIC")
        bump_h(self.input_photo, 5)
        self.btn_browse_photo = QPushButton("Procházet...")
        bump_h(self.btn_browse_photo, 5)
        self.btn_browse_photo.clicked.connect(self.browse_photo)
    
        self.group_input_layout.addWidget(self.input_photo, 0, 1)
        self.group_input_layout.addWidget(self.btn_browse_photo, 0, 2)
    
        self.label_file_purpose = QLabel("📝 Fotka se použije pro získání GPS souřadnic")
        self.label_file_purpose.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        self.group_input_layout.addWidget(self.label_file_purpose, 1, 0, 1, 3)
    
        self.group_input_file.setLayout(self.group_input_layout)
        layout.addWidget(self.group_input_file)
    
        # === Skupina - Nastavení mapy ===
        group = QGroupBox("🔍 Nastavení mapy")
        group_layout = QGridLayout()
        group_layout.setContentsMargins(8, 6, 8, 6)
        group_layout.setHorizontalSpacing(6)
        group_layout.setVerticalSpacing(4)
        # Levý sloupec fixní, pravý pružný
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)
    
        # Zoom
        group_layout.addWidget(QLabel("Zoom level:"), 0, 0)
        self.spin_zoom = QSpinBox()
        self.spin_zoom.setRange(1, 19)
        self.spin_zoom.setValue(17)
        self.spin_zoom.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        bump_h(self.spin_zoom, 5)
        group_layout.addWidget(self.spin_zoom, 0, 1)
    
        # Transparentnost mapy (suffix nahrazen tooltipem kvůli šířce)
        group_layout.addWidget(QLabel("Transparentnost mapy:"), 1, 0)
        self.spin_opacity = QDoubleSpinBox()
        self.spin_opacity.setRange(0.10, 1.00)
        self.spin_opacity.setDecimals(2)
        self.spin_opacity.setSingleStep(0.10)
        self.spin_opacity.setToolTip("1.00 = neprůhledná, 0.10 = silně průhledná")
        self.spin_opacity.setValue(1.00)
        self.spin_opacity.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        bump_h(self.spin_opacity, 5)
        group_layout.addWidget(self.spin_opacity, 1, 1)
    
        # Velikost GPS bodu
        group_layout.addWidget(QLabel("Velikost GPS bodu:"), 2, 0)
        self.spin_marker_size = QSpinBox()
        self.spin_marker_size.setRange(5, 50)
        self.spin_marker_size.setValue(15)
        self.spin_marker_size.setSuffix(" px")
        self.spin_marker_size.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        self.spin_marker_size.valueChanged.connect(self.on_marker_size_changed)
        bump_h(self.spin_marker_size, 5)
        group_layout.addWidget(self.spin_marker_size, 2, 1)
    
        # Typ značky
        group_layout.addWidget(QLabel("Typ značky:"), 3, 0)
        self.combo_marker_style = QComboBox()
        self.combo_marker_style.addItems(["Puntík", "Křížek"])
        self.combo_marker_style.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        self.combo_marker_style.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_marker_style.setMinimumContentsLength(6)
        self.combo_marker_style.currentIndexChanged.connect(self.on_marker_style_changed)
        bump_h(self.combo_marker_style, 5)
        group_layout.addWidget(self.combo_marker_style, 3, 1)
    
        group.setLayout(group_layout)
        layout.addWidget(group)
    
        # === NEJPRVE: Konfigurace DPI pro náhledy ===
        dpi_config_group = QGroupBox("🔍 Konfigurace DPI pro náhledy")
        dpi_config_layout = QGridLayout()
        dpi_config_layout.setContentsMargins(8, 6, 8, 6)
        dpi_config_layout.setHorizontalSpacing(6)
        dpi_config_layout.setVerticalSpacing(4)
    
        # První řada DPI
        self.check_preview_row1 = QCheckBox("Řada 1:")
        self.check_preview_row1.setChecked(True)  # Defaultně zapnuto
        self.check_preview_row1.toggled.connect(self.on_preview_row_toggled)
        dpi_config_layout.addWidget(self.check_preview_row1, 0, 0)
    
        self.spin_preview_dpi_row1 = QSpinBox()
        self.spin_preview_dpi_row1.setRange(240, 420)
        self.spin_preview_dpi_row1.setValue(240)  # Defaultní hodnota
        self.spin_preview_dpi_row1.setSuffix(" DPI")
        self.spin_preview_dpi_row1.setMinimumWidth(80)
        bump_h(self.spin_preview_dpi_row1, 5)
        dpi_config_layout.addWidget(self.spin_preview_dpi_row1, 0, 1)
    
        # Druhá řada DPI
        self.check_preview_row2 = QCheckBox("Řada 2:")
        self.check_preview_row2.setChecked(False)  # Defaultně vypnuto
        self.check_preview_row2.toggled.connect(self.on_preview_row_toggled)
        dpi_config_layout.addWidget(self.check_preview_row2, 1, 0)
    
        self.spin_preview_dpi_row2 = QSpinBox()
        self.spin_preview_dpi_row2.setRange(240, 420)
        self.spin_preview_dpi_row2.setValue(420)  # Defaultní hodnota
        self.spin_preview_dpi_row2.setSuffix(" DPI")
        self.spin_preview_dpi_row2.setMinimumWidth(80)
        self.spin_preview_dpi_row2.setEnabled(False)  # Defaultně vypnuto
        bump_h(self.spin_preview_dpi_row2, 5)
        dpi_config_layout.addWidget(self.spin_preview_dpi_row2, 1, 1)
    
        # Popis
        dpi_desc = QLabel("📝 Zvolte které řady náhledů zobrazit a jejich DPI (240-420)")
        dpi_desc.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        dpi_desc.setWordWrap(True)
        dpi_config_layout.addWidget(dpi_desc, 2, 0, 1, 2)
    
        dpi_config_group.setLayout(dpi_config_layout)
        layout.addWidget(dpi_config_group)
    
        # === POTÉ: Tlačítko pro zobrazení náhledů (pod sekcí DPI) ===
        btn_multi_zoom_preview = QPushButton("Zobrazit náhled všech zoom levelů")
        btn_multi_zoom_preview.setToolTip("Otevře dialog s náhledy mapy pro všechny relevantní zoom levely")
        btn_multi_zoom_preview.clicked.connect(self.show_multi_zoom_preview_dialog)
        bump_h(btn_multi_zoom_preview, 5)
        layout.addWidget(btn_multi_zoom_preview)
    
        # === Skupina - Identifikace lokace ===
        group = QGroupBox("🏷️ Identifikace lokace")
        group_layout = QGridLayout()
        group_layout.setContentsMargins(8, 6, 8, 6)
        group_layout.setHorizontalSpacing(6)
        group_layout.setVerticalSpacing(4)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)
    
        group_layout.addWidget(QLabel("ID lokace:"), 0, 0)
        self.input_id_lokace = QLineEdit("KAROLÍN_KOT001")
        bump_h(self.input_id_lokace, 5)
        group_layout.addWidget(self.input_id_lokace, 0, 1)
    
        group_layout.addWidget(QLabel("Popis:"), 1, 0)
        self.input_popis = QLineEdit("PředVchodemKotkovců")
        bump_h(self.input_popis, 5)
        group_layout.addWidget(self.input_popis, 1, 1)
    
        group_layout.addWidget(QLabel("Vodoznak (mm):"), 2, 0)
        self.spin_watermark = QDoubleSpinBox()
        self.spin_watermark.setRange(0.0, 10.0)
        self.spin_watermark.setSingleStep(0.5)
        self.spin_watermark.setValue(3.0)
        self.spin_watermark.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        bump_h(self.spin_watermark, 5)
        group_layout.addWidget(self.spin_watermark, 2, 1)
    
        # NOVÝ: Indikátor polygonové oblasti
        group_layout.addWidget(QLabel("Polygonová oblast:"), 3, 0)
        self.label_polygon_indicator = QLabel("—")
        self.label_polygon_indicator.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        group_layout.addWidget(self.label_polygon_indicator, 3, 1)
    
        # NOVÝ: Checkbox "Anonymní lokace" (defaultně nezaškrtnutý)
        group_layout.addWidget(QLabel("Anonymní lokace:"), 4, 0)
        self.checkbox_anonymni_lokace = QCheckBox("Zapnout anonymizaci")
        self.checkbox_anonymni_lokace.setChecked(False)
        bump_h(self.checkbox_anonymni_lokace, 5)
        group_layout.addWidget(self.checkbox_anonymni_lokace, 4, 1)
    
        group.setLayout(group_layout)
        layout.addWidget(group)
    
        layout.addStretch()
    
        self.tabs.addTab(tab, "📋 Základní")
        return tab
    
    def check_polygon_in_png(self, png_path):
        """
        Detekce polygonu v PNG souboru podle parametru AOI_POLYGON v metadatech.
        """
        try:
            from PIL import Image
            
            with Image.open(png_path) as img:
                # Kontrola PNG metadat
                info = img.info or {}
                
                # Kontrola konkrétního klíče AOI_POLYGON
                if 'AOI_POLYGON' in info:
                    value = info['AOI_POLYGON']
                    # Kontrola, zda hodnota není prázdná
                    if value and str(value).strip():
                        return True, "Obsahuje polygon"
                    else:
                        return False, "AOI_POLYGON je prázdný"
                
                return False, "Neobsahuje polygon"
                
        except Exception as e:
            return False, f"Chyba při kontrole: {str(e)[:50]}..."
    
    def is_location_map_file(self, file_path):
        """
        Rozpozná, zda je soubor lokační mapou podle názvu a typu.
        """
        try:
            path = Path(file_path)
            if not path.is_file() or path.suffix.lower() not in ['.png', '.jpg', '.jpeg']:
                return False
            
            # Použít existující metodu nebo podobnou logiku
            return self.is_location_map_image(path.name)
        except:
            return False
        
    def update_polygon_highlights(self):
        """
        ALTERNATIVNÍ verze: Použije background barvu místo foreground.
        """
        try:
            if not hasattr(self, 'file_tree') or not self.file_tree:
                return
            
            from PySide6.QtGui import QBrush, QColor
            from PySide6.QtCore import Qt
            
            # Reset všech barev
            def reset_item_colors(item):
                if not item:
                    return
                item.setData(0, Qt.BackgroundRole, None)
                for i in range(item.childCount()):
                    reset_item_colors(item.child(i))
            
            for i in range(self.file_tree.topLevelItemCount()):
                reset_item_colors(self.file_tree.topLevelItem(i))
            
            # Zvýraznit background barvou
            selected_items = self.file_tree.selectedItems() or []
            
            for item in selected_items:
                path_str = item.data(0, Qt.UserRole)
                if not path_str:
                    continue
                
                path = Path(path_str)
                if not path.is_file() or path.suffix.lower() != '.png':
                    continue
                    
                if not self.is_location_map_file(path_str):
                    continue
                
                has_polygon, _ = self.check_polygon_in_png(path_str)
                
                if has_polygon:
                    # Světle červená pro background
                    color = QColor('#FFEBEE')  # velmi světle červená
                    brush = QBrush(color)
                    item.setData(0, Qt.BackgroundRole, brush)
                else:
                    # Světle zelená pro background
                    color = QColor('#E8F5E8')  # velmi světle zelená
                    brush = QBrush(color)
                    item.setData(0, Qt.BackgroundRole, brush)
                    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba background zvýraznění: {e}", "error")


    def update_polygon_indicator(self):
        """
        ZJEDNODUŠENÁ VERZE: Pouze informativní text o počtu souborů s/bez polygonu.
        Hlavní indikace je nyní přímo ve stromu přes barvy.
        """
        try:
            if not hasattr(self, 'label_polygon_indicator'):
                return
            
            selected_items = self.file_tree.selectedItems() if hasattr(self, 'file_tree') else []
            
            if not selected_items:
                self.label_polygon_indicator.setText("Žádný soubor není vybrán")
                self.label_polygon_indicator.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
                return
            
            # Spočítat PNG lokační mapy
            png_with_polygon = 0
            png_without_polygon = 0
            total_png_maps = 0
            
            for item in selected_items:
                path_str = item.data(0, Qt.UserRole)
                if not path_str:
                    continue
                    
                path = Path(path_str)
                if not path.is_file() or path.suffix.lower() != '.png':
                    continue
                    
                if not self.is_location_map_file(path_str):
                    continue
                    
                total_png_maps += 1
                has_polygon, _ = self.check_polygon_in_png(path_str)
                
                if has_polygon:
                    png_with_polygon += 1
                else:
                    png_without_polygon += 1
            
            # Sestavit informativní text
            if total_png_maps == 0:
                text = f"Vybráno: {len(selected_items)} položek (žádné PNG mapy)"
                color = "#666"
            elif len(selected_items) == 1:
                if png_with_polygon > 0:
                    text = "🔴 Obsahuje polygon"
                    color = "#D32F2F"
                else:
                    text = "🟢 Neobsahuje polygon"
                    color = "#388E3C"
            else:
                text = f"PNG mapy: {total_png_maps} • 🔴 s polygonem: {png_with_polygon} • 🟢 bez polygonu: {png_without_polygon}"
                
                if png_with_polygon > 0 and png_without_polygon > 0:
                    color = "#FF9800"  # smíšený stav
                elif png_with_polygon > 0:
                    color = "#D32F2F"  # všechny mají polygon
                else:
                    color = "#388E3C"  # žádný nemá polygon
            
            self.label_polygon_indicator.setText(text)
            self.label_polygon_indicator.setStyleSheet(f"QLabel {{ color: {color}; font-size: 11px; }}")
            
        except Exception as e:
            if hasattr(self, 'label_polygon_indicator'):
                self.label_polygon_indicator.setText("Chyba detekce")
                self.label_polygon_indicator.setStyleSheet("QLabel { color: #f44336; font-size: 11px; }")
                
    def setup_undo_filter_shortcut(self):
        """Nastaví klávesovou zkratku CMD+Z/Ctrl+Z pro vymazání filtru stromové struktury."""
        try:
            # Pokud už zkratky existují, odstraň je
            if hasattr(self, '_shortcut_undo_filter') and self._shortcut_undo_filter:
                self._shortcut_undo_filter.deleteLater()
            if hasattr(self, '_shortcut_undo_filter_win') and self._shortcut_undo_filter_win:
                self._shortcut_undo_filter_win.deleteLater()
            
            # CMD+Z pro macOS
            self._shortcut_undo_filter = QShortcut(QKeySequence(Qt.META | Qt.Key_Z), self)
            self._shortcut_undo_filter.setContext(Qt.ApplicationShortcut)
            self._shortcut_undo_filter.setAutoRepeat(False)
            self._shortcut_undo_filter.activated.connect(self.clear_filter_input)
            
            # Ctrl+Z pro Windows/Linux  
            self._shortcut_undo_filter_win = QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Z), self)
            self._shortcut_undo_filter_win.setContext(Qt.ApplicationShortcut)
            self._shortcut_undo_filter_win.setAutoRepeat(False)
            self._shortcut_undo_filter_win.activated.connect(self.clear_filter_input)
            
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("↩️ Zkratka CMD+Z/Ctrl+Z nastavena pro vymazání filtru", "info")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při nastavování zkratky CMD+Z: {e}", "error")
    
    @Slot()
    def clear_filter_input(self):
        """Vymaže text z filtru a aplikuje prázdný filtr (zobrazí všechny položky)."""
        try:
            if hasattr(self, 'edit_unsorted_filter') and self.edit_unsorted_filter:
                # Vymazat text z filtru
                self.edit_unsorted_filter.clear()
                
                # Spustit timer pro aplikaci filtru (prázdný filtr = zobrazí vše)
                if hasattr(self, '_unsorted_filter_timer') and self._unsorted_filter_timer:
                    self._unsorted_filter_timer.start(50)
                
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("↩️ Filtr stromu vymazán zkratkou CMD+Z/Ctrl+Z", "success")
            else:
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("⚠️ Filtr stromu není k dispozici", "warning")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při vymazání filtru: {e}", "error")

    def setup_search_shortcut(self):
        """Nastaví klávesové zkratky CMD+F/Ctrl+F pro focus na filtr a CMD+Z/Ctrl+Z pro vymazání filtru."""
        try:
            if hasattr(self, 'edit_unsorted_filter') and self.edit_unsorted_filter:
                # === CMD+F / Ctrl+F pro focus na filtr ===
                # Pokud už zkratka existuje, odstraň ji
                if hasattr(self, '_shortcut_search') and self._shortcut_search:
                    self._shortcut_search.deleteLater()
                if hasattr(self, '_shortcut_search_mac') and self._shortcut_search_mac:
                    self._shortcut_search_mac.deleteLater()
                
                # Ctrl+F pro Windows/Linux
                self._shortcut_search = QShortcut(QKeySequence(Qt.CTRL | Qt.Key_F), self)
                self._shortcut_search.setContext(Qt.ApplicationShortcut)
                self._shortcut_search.setAutoRepeat(False)
                self._shortcut_search.activated.connect(self.focus_filter_input)
                
                # Cmd+F pro macOS
                self._shortcut_search_mac = QShortcut(QKeySequence(Qt.META | Qt.Key_F), self)
                self._shortcut_search_mac.setContext(Qt.ApplicationShortcut)
                self._shortcut_search_mac.setAutoRepeat(False)
                self._shortcut_search_mac.activated.connect(self.focus_filter_input)
                
                # === CMD+Z / Ctrl+Z pro vymazání filtru ===
                self.setup_undo_filter_shortcut()
                
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("🔎 Zkratky pro filtr stromu nastaveny:", "success")
                    self.log_widget.add_log("  • CMD+F/Ctrl+F → Focus na filtr", "info") 
                    self.log_widget.add_log("  • CMD+Z/Ctrl+Z → Vymazat filtr", "info")
            else:
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("⚠️ Filtr stromu ještě není vytvořen", "warning")
        
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při nastavování zkratek filtru: {e}", "error")

    def focus_filter_input(self):
        """Nasměruje focus na vstupní pole filtru a vybere jeho obsah."""
        try:
            if hasattr(self, 'edit_unsorted_filter') and self.edit_unsorted_filter:
                # Nasměrovat focus na filtr
                self.edit_unsorted_filter.setFocus()
                
                # Vybrat všechen text pro rychlé přepsání
                self.edit_unsorted_filter.selectAll()
                
                # Volitelně zobrazit tip uživateli
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("🔍 CMD+F: Focus na filtr 'Neroztříděné'", "success")
                    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při nastavování focus na filtr: {e}", "error")

    # TATO METODA ZŮSTÁVÁ UVNITŘ TŘÍDY MainWindow
    def show_multi_zoom_preview_dialog(self):
        try:
            params = self.get_parameters()
            
            # Získání souřadnic
            coord_text = params.get('manual_coordinates')
            if not coord_text or not self.parse_coordinates(coord_text):
                QMessageBox.warning(self, "Chyba", "Zadejte platné GPS souřadnice v záložce 'GPS' pro zobrazení náhledu.")
                return
    
            # Konfigurace řad náhledů
            preview_config = {
                'row1_enabled': getattr(self, 'check_preview_row1', None) and self.check_preview_row1.isChecked(),
                'row1_dpi': getattr(self, 'spin_preview_dpi_row1', None) and self.spin_preview_dpi_row1.value() or 240,
                'row2_enabled': getattr(self, 'check_preview_row2', None) and self.check_preview_row2.isChecked(),
                'row2_dpi': getattr(self, 'spin_preview_dpi_row2', None) and self.spin_preview_dpi_row2.value() or 420,
            }
            
            # Alespoň jedna řada musí být povolena
            if not preview_config['row1_enabled'] and not preview_config['row2_enabled']:
                QMessageBox.warning(self, "Chyba", "Alespoň jedna řada náhledů musí být zvolena.")
                return
    
            dlg = MultiZoomPreviewDialog(self, params, preview_config)
            dlg.exec()
            
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nelze otevřít dialog pro náhled zoomů:\n{e}")
            self.log_widget.add_log(f"❌ Kritická chyba v show_multi_zoom_preview_dialog: {e}", "error")

    
    def on_preview_row_toggled(self):
        """Handler pro změny checkboxů řad náhledů."""
        try:
            # Povolit/zakázat DPI spinery podle checkboxů
            if hasattr(self, 'check_preview_row1') and hasattr(self, 'spin_preview_dpi_row1'):
                self.spin_preview_dpi_row1.setEnabled(self.check_preview_row1.isChecked())
                
            if hasattr(self, 'check_preview_row2') and hasattr(self, 'spin_preview_dpi_row2'):
                self.spin_preview_dpi_row2.setEnabled(self.check_preview_row2.isChecked())
                
            # Alespoň jedna řada musí být zvolena
            if (hasattr(self, 'check_preview_row1') and hasattr(self, 'check_preview_row2') and 
                not self.check_preview_row1.isChecked() and not self.check_preview_row2.isChecked()):
                # Automaticky zapnout první řadu
                self.check_preview_row1.setChecked(True)
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("⚠️ Alespoň jedna řada náhledů musí být zvolena - zapnuta řada 1", "warning")
                    
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při změně konfigurace náhledů: {e}", "error")


    def get_marker_style_from_settings(self) -> str:
        """Vrátí 'dot' nebo 'cross' podle UI, výchozí 'dot'."""
        try:
            if hasattr(self, "combo_marker_style") and self.combo_marker_style:
                txt = (self.combo_marker_style.currentText() or "").strip().lower()
                return "cross" if ("kříž" in txt or "kriz" in txt) else "dot"
        except Exception:
            pass
        try:
            if hasattr(self, "current_settings") and isinstance(self.current_settings, dict):
                val = (self.current_settings.get("marker_style") or "").lower()
                if val in ("dot", "cross"):
                    return val
        except Exception:
            pass
        return "dot"
    
    def on_marker_style_changed(self, *_):
        """Změna typu značky – pouze uloží hodnotu a označí náhled jako zastaralý."""
        try:
            if hasattr(self, "current_settings") and isinstance(self, MainWindow) and isinstance(self.current_settings, dict):
                self.current_settings["marker_style"] = self.get_marker_style_from_settings()
        except Exception:
            pass
        # Nevolat update_map_preview, pouze vyznačit neaktuální náhled
        self._flag_gps_preview_outdated()
        
    def on_marker_size_changed(self):
        """Změna velikosti značky – bez automatického vykreslení, pouze označit zastaralý náhled."""
        try:
            # Zrušit případné dříve plánované autorefreshe
            if hasattr(self, 'marker_update_timer') and self.marker_update_timer:
                self.marker_update_timer.stop()
        except Exception:
            pass
        # Nevolat update_map_preview, pouze vyznačit neaktuální náhled
        self._flag_gps_preview_outdated()


    def open_maps_folder(self):
        """NOVÁ FUNKCE: Otevření složky s mapkami v systémovém prohlížeči"""
        try:
            import subprocess
            import platform
            
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(self.default_maps_path)])
            elif platform.system() == "Windows":
                subprocess.run(["explorer", str(self.default_maps_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(self.default_maps_path)])
                
            self.log_widget.add_log(f"📂 Otevřena složka: {self.default_maps_path}", "info")
            
        except Exception as e:
            self.log_widget.add_log(f"❌ Chyba při otevírání složky: {e}", "error")
            QMessageBox.warning(self, "Chyba", f"Nelze otevřít složku:\n{str(e)}")
        
    def create_output_settings_tab(self):
        """Vytvoření tabu výstupních nastavení včetně dynamického přepínání režimu ID a zobrazení prvního volného čísla."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
    
        # Skupina - Rozměry výstupu (beze změn oproti vaší verzi)
        group = QGroupBox("📐 Rozměry výstupu")
        group_layout = QGridLayout()
        group_layout.addWidget(QLabel("Šířka (cm):"), 0, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(1.0, 100.0)
        self.spin_width.setValue(21.0)
        self.spin_width.setSingleStep(0.1)
        group_layout.addWidget(self.spin_width, 0, 1)
    
        group_layout.addWidget(QLabel("Výška (cm):"), 1, 0)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(1.0, 100.0)
        self.spin_height.setValue(29.7)
        self.spin_height.setSingleStep(0.1)
        group_layout.addWidget(self.spin_height, 1, 1)
    
        group_layout.addWidget(QLabel("DPI:"), 2, 0)
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setValue(300)
        group_layout.addWidget(self.spin_dpi, 2, 1)
        group.setLayout(group_layout)
        layout.addWidget(group)
    
        # Skupina - Výstupní složka (beze změn)
        group = QGroupBox("📁 Výstupní složka")
        group_layout = QGridLayout()
        group_layout.addWidget(QLabel("Složka:"), 0, 0)
        self.input_output_dir = QLineEdit("./output")
        self.btn_browse_output = QPushButton("Procházet...")
        self.btn_browse_output.clicked.connect(self.browse_output_dir)
        group_layout.addWidget(self.input_output_dir, 0, 1)
        group_layout.addWidget(self.btn_browse_output, 0, 2)
        group.setLayout(group_layout)
        layout.addWidget(group)
    
        # Skupina - Číslování souborů (AKTUALIZOVÁNO: první volné číslo + přejmenování labelu)
        group = QGroupBox("🔢 Číslování souborů")
        group_layout = QGridLayout()
    
        self.check_auto_id = QCheckBox("Automatické generování ID")
        self.check_auto_id.setChecked(True)
        self.check_auto_id.toggled.connect(self.on_auto_id_toggled)
        group_layout.addWidget(self.check_auto_id, 0, 0, 1, 2)
    
        auto_id_desc = QLabel("📝 Najde první volné číslo v souborech typu *+Z*+XXXXX.png (1..max; při mezerách použije nejmenší chybějící, jinak max+1).")
        auto_id_desc.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        auto_id_desc.setWordWrap(True)
        group_layout.addWidget(auto_id_desc, 1, 0, 1, 2)
    
        # Uložený label pro dynamickou změnu textu
        self.label_id_mode = QLabel("Automatické ID:" if self.check_auto_id.isChecked() else "Ruční ID:")
        group_layout.addWidget(self.label_id_mode, 2, 0)
    
        self.input_manual_id = QLineEdit("00001")
        # Pole se edituje jen v ručním režimu
        self.input_manual_id.setEnabled(not self.check_auto_id.isChecked())
        group_layout.addWidget(self.input_manual_id, 2, 1)
    
        manual_id_desc = QLabel("📝 V ručním režimu zadejte číslo (převede se na 5-místný formát).")
        manual_id_desc.setStyleSheet("QLabel { color: #666; font-style: italic; font-size: 11px; }")
        group_layout.addWidget(manual_id_desc, 3, 0, 1, 2)
    
        group.setLayout(group_layout)
        layout.addWidget(group)
    
        layout.addStretch()
        self.tabs.addTab(tab, "💾 Výstup")
    
        # Po vytvoření: inicializovat automatické ID podle aktuálního stavu složek
        try:
            if self.check_auto_id.isChecked():
                # Preferuj existující helper, pokud je k dispozici
                if hasattr(self, "find_first_free_location_id"):
                    self.input_manual_id.setText(self.find_first_free_location_id())
                else:
                    # fallback přes analyze_unsorted_location_ids
                    st = self.analyze_unsorted_location_ids()
                    mx = st.get('max')
                    missing = st.get('missing') or []
                    if missing:
                        val = min(int(x) for x in missing if isinstance(x, (int, str)) and str(x).isdigit())
                    else:
                        val = (int(mx) + 1) if mx is not None else 1
                    if hasattr(self, "_p5"):
                        self.input_manual_id.setText(self._p5(val))
                    else:
                        self.input_manual_id.setText(f"{int(val):05d}")
                # Ujistit se o textu labelu
                self.label_id_mode.setText("Automatické ID:")
        except Exception:
            pass
    
        return tab

    def create_advanced_settings_tab(self):
        """Vytvoření tabu pokročilých nastavení"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Skupina - OSM nastavení
        group = QGroupBox("🌐 OpenStreetMap nastavení")
        group_layout = QGridLayout()
        
        group_layout.addWidget(QLabel("Název aplikace:"), 0, 0)
        self.input_app_name = QLineEdit("OSM Map Generator")
        group_layout.addWidget(self.input_app_name, 0, 1)
        
        group_layout.addWidget(QLabel("Kontaktní email:"), 1, 0)
        self.input_email = QLineEdit("your.email@example.com")
        group_layout.addWidget(self.input_email, 1, 1)
        
        group_layout.addWidget(QLabel("Zpoždění mezi požadavky (s):"), 2, 0)
        self.spin_delay = QDoubleSpinBox()
        self.spin_delay.setRange(0.0, 5.0)
        self.spin_delay.setSingleStep(0.1)
        self.spin_delay.setValue(0.1)
        group_layout.addWidget(self.spin_delay, 2, 1)
        
        group.setLayout(group_layout)
        layout.addWidget(group)
        
        layout.addStretch()
        self.tabs.addTab(tab, "⚙️ Pokročilé")
        
    # V metodě create_menu_bar() přidejte novou položku menu
    def create_menu_bar(self):
        """Vytvoření menu baru s nabídkou nástrojů a PDF generátorem."""
        menubar = self.menuBar()
        tools_menu = menubar.addMenu("🔧 Nástroje")
    
        pdf_generator_action = tools_menu.addAction("📄 Generátor PDF z čtyřlístků")
        pdf_generator_action.triggered.connect(self.open_pdf_generator)

    def open_pdf_generator(self):
        """Otevře okno PDF generátoru jako NEmodální (hlavní okno zůstává použitelné)."""
        try:
            from PySide6.QtCore import Qt
    
            # Pokud už běží, jen ho vyzvedni
            win = getattr(self, "_pdf_gen_win", None)
            try:
                if win is not None and win.isVisible():
                    win.raise_()
                    win.activateWindow()
                    return
            except Exception:
                pass
    
            dlg = PDFGeneratorWindow(self)
    
            # Nemodalita + úklid po zavření
            try: dlg.setWindowModality(Qt.NonModal)
            except Exception: pass
            try: dlg.setModal(False)  # pokud je to QDialog
            except Exception: pass
            try: dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            except Exception: pass
    
            # Držet referenci, ať okno vydrží žít
            self._pdf_gen_win = dlg
            try:
                dlg.destroyed.connect(lambda *_: setattr(self, "_pdf_gen_win", None))
            except Exception:
                pass
    
            dlg.show()
            try:
                dlg.raise_()
                dlg.activateWindow()
            except Exception:
                pass
    
        except Exception as e:
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Chyba", f"Nelze otevřít PDF generátor:\n{str(e)}")
            except Exception:
                pass
            
    def create_monitoring_widget(self):
        """Monitoring: centrovaná tlačítková lišta, kompaktní svislé mezery a sjednocený styl tlačítek."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QToolBar, QPushButton
        from PySide6.QtCore import QTimer, Qt
    
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8) # tenké okraje celé sekce
        layout.setSpacing(6) # menší svislé mezery mezi bloky
    
        # 1) Status
        self.status_widget = StatusWidget()
        self.status_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addWidget(self.status_widget)
    
        # 2) Centrovaná lišta tlačítek — QToolBar s QPushButton a pevnými "gap" mezerami
        top_panel = QWidget()
        top_panel_layout = QHBoxLayout(top_panel)
        top_panel_layout.setContentsMargins(0, 2, 0, 2)
        top_panel_layout.setSpacing(0)
        top_panel_layout.addStretch(1)
    
        # Vytvoření toolbaru (text-only, ale přidáváme vlastní QPushButton kvůli CSS vzhledu)
        self.monitor_toolbar = QToolBar("Monitoring", top_panel)
        self.monitor_toolbar.setMovable(False)
        self.monitor_toolbar.setFloatable(False)
        self.monitor_toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
    
        # Zrušit linku/rám a pozadí, aby nebyla vidět čára nad gapem
        self.monitor_toolbar.setContentsMargins(0, 0, 0, 0)
        self.monitor_toolbar.setStyleSheet("""
        QToolBar {
            border: 0px; /* zruší horní/dolní linku toolbaru */
            background: transparent; /* prázdné pozadí */
            padding: 0px;
        }
        QToolBar::separator {
            width: 0px;
            height: 0px;
            background: transparent;
            margin: 0px;
        }
        """)
    
        # Pomocník: pevná mezera (gap) v toolbaru
        def _add_toolbar_gap(toolbar, width_px: int):
            gap = QWidget(toolbar)
            gap.setFixedWidth(int(width_px))
            gap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            toolbar.addWidget(gap)
            return gap
    
        # Style helper (zachovává vzhled původních tlačítek)
        def style_btn(btn: QPushButton, base: str, hover: str, pressed: str, h: int = 35, w: int | None = None):
            btn.setMinimumHeight(h)
            if w:
                btn.setMinimumWidth(w)
            btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {base};
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{ background-color: #cccccc; color: #666666; }}
            """)
    
        # Paleta barev sjednocená s oknem
        BLUE = ("#2196F3", "#1976D2", "#1565C0") # Defaultní hodnoty
        GREEN = ("#4CAF50", "#45a049", "#3d8b40") # Spustit
        RED = ("#f44336", "#da190b", "#c1170a") # Zastavit
        ORNG = ("#FF9800", "#F57C00", "#E65100") # PDF
        PURP = ("#8e44ad", "#7d3c98", "#6c3483") # 4K/FullHD
        TEAL = ("#009688", "#00796B", "#00695C") # Web fotky
    
        # 🔄 Defaultní hodnoty
        self.btn_set_defaults_secondary = QPushButton("🔄 Defaultní hodnoty")
        style_btn(self.btn_set_defaults_secondary, *BLUE)
        self.btn_set_defaults_secondary.setMaximumWidth(160)  # Změněno z 160 na 80
        self.btn_set_defaults_secondary.setToolTip("Rychlé nastavení defaultních hodnot")
        self.btn_set_defaults_secondary.clicked.connect(self.set_default_values)
        self.monitor_toolbar.addWidget(self.btn_set_defaults_secondary)
    
        # Gap po „Defaultní hodnoty"
        _add_toolbar_gap(self.monitor_toolbar, 14)  # Změněno z 28 na 14
    
        # 🚀 Spustit generování
        self.btn_start_secondary = QPushButton("🚀 Spustit generování")
        style_btn(self.btn_start_secondary, *GREEN)
        self.btn_start_secondary.clicked.connect(self.start_processing)
        self.monitor_toolbar.addWidget(self.btn_start_secondary)
    
        # ⏹ Zastavit
        self.btn_stop_secondary = QPushButton("⏹ Zastavit")
        style_btn(self.btn_stop_secondary, *RED)
        self.btn_stop_secondary.setEnabled(False)
        self.btn_stop_secondary.clicked.connect(self.stop_processing)
        self.monitor_toolbar.addWidget(self.btn_stop_secondary)
    
        # Gap mezi „Zastavit" a „PDF Generátor"
        _add_toolbar_gap(self.monitor_toolbar, 14)  # Změněno z 28 na 14
    
        # 📄 PDF Generátor
        self.btn_pdf_generator_monitor = QPushButton("📄 PDF Generátor")
        style_btn(self.btn_pdf_generator_monitor, *ORNG, w=95)  # Změněno z 190 na 95
        self.btn_pdf_generator_monitor.setToolTip("Otevře okno pro generování PDF z čtyřlístků")
        self.btn_pdf_generator_monitor.clicked.connect(self.open_pdf_generator)
        self.monitor_toolbar.addWidget(self.btn_pdf_generator_monitor)
    
        # 🧩 Web fotky - NOVÉ TLAČÍTKO
        self.btn_web_photos = QPushButton("🧩 Web fotky")
        style_btn(self.btn_web_photos, *TEAL, w=75)  # Změněno z 150 na 75
        self.btn_web_photos.setToolTip("Příprava fotek pro web: kontrola, přejmenování a správa")
        self.btn_web_photos.clicked.connect(self.open_web_photos_window)
        self.monitor_toolbar.addWidget(self.btn_web_photos)
    
        # Gap před „FullHD/4K"
        _add_toolbar_gap(self.monitor_toolbar, 6)  # Změněno z 12 na 6
    
        # 🖥️ FullHD/4K
        self.btn_toggle_display = QPushButton("🖥️ FullHD")
        style_btn(self.btn_toggle_display, *PURP, w=60)  # Změněno z 120 na 60
        self.btn_toggle_display.setToolTip("Přepnout mezi 4K a FullHD")
        self.btn_toggle_display.clicked.connect(self.toggle_display_mode)
        self.monitor_toolbar.addWidget(self.btn_toggle_display)
    
        top_panel_layout.addWidget(self.monitor_toolbar)
        top_panel_layout.addStretch(1)
        layout.addWidget(top_panel)
    
        # 3) Log výpis (bez nadpisu a bez tlačítka 'Vymazat' – křížek řeší přímo LogWidget)
        self.log_widget = LogWidget(show_header=False, show_clear=False, show_clear_overlay=True)
        self.log_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.log_widget)
    
        # 4) Autodetekce režimu po vytvoření panelu
        QTimer.singleShot(0, self.auto_select_display_mode)
    
        return widget

    # === PŘEPÍNÁNÍ 4K / FULLHD ===
    def toggle_display_mode(self):
        """Přepíná mezi 4K a FullHD režimem (stejně jako v PDF okně)."""
        current = getattr(self, 'display_mode', '4k')
        new_mode = 'fhd' if current == '4k' else '4k'
        self.apply_display_mode(new_mode)
        # Text tlačítka ukazuje „druhý režim“ (stejný pattern jako v PDF okně)
        if hasattr(self, 'btn_toggle_display'):
            self.btn_toggle_display.setText("🖥️ 4K" if new_mode == 'fhd' else "🖥️ FullHD")
    
    
    def auto_select_display_mode(self):
        """
        Automaticky zvolí 4K/FullHD dle efektivního rozlišení (availableGeometry × devicePixelRatio),
        a aktualizuje text tlačítka stejně jako PDF okno.
        """
        mode = self._detect_screen_mode()
        self.apply_display_mode(mode)
        if hasattr(self, 'btn_toggle_display'):
            self.btn_toggle_display.setText("🖥️ 4K" if mode == 'fhd' else "🖥️ FullHD")
    
    
    def _detect_screen_mode(self):
        """
        Vrátí '4k' nebo 'fhd' podle efektivního rozlišení obrazovky.
        Pravidlo: pokud efektivní šířka >= 3200 nebo výška >= 1800 → 4K, jinak FullHD.
        """
        from PySide6.QtGui import QGuiApplication
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return 'fhd'
        geom = screen.availableGeometry()
        w = geom.width()
        h = geom.height()
        try:
            dpr = float(screen.devicePixelRatio())
        except Exception:
            dpr = 1.0
        eff_w = int(round(w * dpr))
        eff_h = int(round(h * dpr))
        return '4k' if (eff_w >= 3200 or eff_h >= 1800) else 'fhd'
    
    
    def apply_display_mode(self, mode):
        """
        Aplikuje zvolený režim zobrazení ('4k' nebo 'fhd') v celém UI,
        škáluje fonty, min/max rozměry a px hodnoty ve stylech (analogicky k PDF oknu).
        """
        # Inicializace scale faktoru, pokud chybí
        if not hasattr(self, '_current_scale_factor'):
            self._current_scale_factor = 1.0
        if mode == getattr(self, 'display_mode', None):
            return
    
        target = 0.75 if mode == 'fhd' else 1.0
        relative = target / float(self._current_scale_factor or 1.0)
    
        # Rekurzivní škálování celé widgetové hierarchie
        self._scale_widget_tree(self, relative)
    
        # Volitelná úprava velikosti okna (bez změny rozvržení UI)
        try:
            from PySide6.QtGui import QGuiApplication
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                if mode == 'fhd':
                    w = min(1500, max(1100, avail.width() - 40))
                    h = min(950, max(780, avail.height() - 80))
                    self.setMinimumSize(1000, 780)
                    self.resize(w, h)
                else:
                    # Větší prostor pro 4K (hodnoty voleny obdobně jako v PDF okně)
                    self.setMinimumSize(1800, 1200)
                    self.resize(min(avail.width() - 20, 2200), min(avail.height() - 40, 1600))
        except Exception:
            pass
    
        # Uložení stavu
        self._current_scale_factor = target
        self.display_mode = mode
    
        # Aktualizace textu tlačítka (ukazuje „druhý režim“)
        if hasattr(self, 'btn_toggle_display'):
            self.btn_toggle_display.setText("🖥️ 4K" if mode == 'fhd' else "🖥️ FullHD")
    
    
    def _scale_widget_tree(self, root_widget, factor):
        """Rekurzivně škáluje fonty, min/max rozměry a px hodnoty v CSS pro celý strom widgetů (analogicky k PDF oknu)."""
        if factor == 1.0 or root_widget is None:
            return
    
        processed_layouts = set()
    
        def scale_layout(layout):
            if layout is None or layout in processed_layouts:
                return
            processed_layouts.add(layout)
            try:
                sp = layout.spacing()
                if sp >= 0:
                    layout.setSpacing(max(0, int(round(sp * factor))))
                l, t, r, b = layout.getContentsMargins()
                layout.setContentsMargins(
                    max(0, int(round(l * factor))),
                    max(0, int(round(t * factor))),
                    max(0, int(round(r * factor))),
                    max(0, int(round(b * factor))),
                )
            except Exception:
                pass
    
        def scale_widget(w):
            # Font
            try:
                f = w.font()
                ps = f.pointSizeF()
                if ps > 0:
                    f.setPointSizeF(max(1.0, ps * factor))
                    w.setFont(f)
            except Exception:
                pass
            # Min/Max rozměry
            try:
                mh = w.minimumHeight()
                if mh > 0:
                    w.setMinimumHeight(max(1, int(round(mh * factor))))
                mw = w.minimumWidth()
                if mw > 0:
                    w.setMinimumWidth(max(1, int(round(mw * factor))))
                xh = w.maximumHeight()
                if xh > 0:
                    w.setMaximumHeight(max(1, int(round(xh * factor))))
                xw = w.maximumWidth()
                if xw > 0:
                    w.setMaximumWidth(max(1, int(round(xw * factor))))
            except Exception:
                pass
            # Stylesheet čísla v px
            try:
                ss = w.styleSheet()
                if ss:
                    new_ss = self._scale_stylesheet_px(ss, factor)
                    if new_ss != ss:
                        w.setStyleSheet(new_ss)
            except Exception:
                pass
            # Layout (spacings + margins)
            try:
                lay = w.layout()
                if lay:
                    scale_layout(lay)
            except Exception:
                pass
    
        from PySide6.QtWidgets import QWidget
        scale_widget(root_widget)
        for child in root_widget.findChildren(QWidget):
            scale_widget(child)
            try:
                lay = child.layout()
                if lay:
                    scale_layout(lay)
            except Exception:
                pass
    
    
    def _scale_stylesheet_px(self, stylesheet_text, factor):
        """Škáluje hodnoty v px v CSS (font-size, padding, margin, border, radius, atd.)."""
        import re
        def repl(m):
            val = int(m.group(1))
            new_val = max(1, int(round(val * factor)))
            return f"{new_val}px"
        return re.sub(r"(\d+)\s*px", repl, stylesheet_text)


    # === PARSOVÁNÍ SOUŘADNIC A REŽIM ===

    def parse_coordinates(self, coord_text):
        """Vlastní parser GPS souřadnic s českými směrovými zkratkami"""
        try:
            import re
            
            # Odstranění bílých znaků
            coord_text = coord_text.strip()
            
            # Vzory pro různé formáty souřadnic
            patterns = [
                # Formát: "49,23173° S, 17,42791° V" (české zkratky)
                r'([0-9]+[,.]?[0-9]*)°?\s*([SJVZ])[,\s]+([0-9]+[,.]?[0-9]*)°?\s*([SJVZ])',
                # Formát: "49.23173, 17.42791" (bez směrů)
                r'([0-9]+[,.]?[0-9]*)[,\s]+([0-9]+[,.]?[0-9]*)',
                # Formát: "S49.23173 V17.42791" (české prefixy)
                r'([SJVZ])([0-9]+[,.]?[0-9]*)\s*([SJVZ])([0-9]+[,.]?[0-9]*)',
                # Formát: "N49.23173 E17.42791" (anglické zkratky)
                r'([NSEW])([0-9]+[,.]?[0-9]*)\s*([NSEW])([0-9]+[,.]?[0-9]*)',
                # Formát: "49,23173° N, 17,42791° E" (anglické zkratky)
                r'([0-9]+[,.]?[0-9]*)°?\s*([NSEW])[,\s]+([0-9]+[,.]?[0-9]*)°?\s*([NSEW])'
            ]
            
            for pattern in patterns:
                match = re.match(pattern, coord_text, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    
                    if len(groups) == 4 and groups[1] in 'SJVZNSEW':
                        # Formát s postfix směry: "49.23173° S, 17.42791° V"
                        lat_val = float(groups[0].replace(',', '.'))
                        lat_dir = groups[1].upper()
                        lon_val = float(groups[2].replace(',', '.'))
                        lon_dir = groups[3].upper()
                        
                        # Převod českých směrů na souřadnice
                        lat = lat_val
                        lon = lon_val
                        
                        # České směry: S=sever(+), J=jih(-), V=východ(+), Z=západ(-)
                        if lat_dir == 'J':  # Jih = záporná zeměpisná šířka
                            lat = -lat_val
                        elif lat_dir == 'S':  # Sever = kladná zeměpisná šířka
                            lat = lat_val
                        
                        if lon_dir == 'Z':  # Západ = záporná zeměpisná délka
                            lon = -lon_val
                        elif lon_dir == 'V':  # Východ = kladná zeměpisná délka
                            lon = lon_val
                        
                        # Anglické směry: N=north(+), S=south(-), E=east(+), W=west(-)
                        if lat_dir == 'S' and groups[3] in 'EW':  # Anglické S = South = jih
                            lat = -lat_val
                        elif lat_dir == 'N':  # North = sever
                            lat = lat_val
                        
                        if lon_dir == 'W':  # West = západ
                            lon = -lon_val
                        elif lon_dir == 'E':  # East = východ
                            lon = lon_val
                        
                        return (lat, lon)
                        
                    elif len(groups) == 2:
                        # Jednoduchý formát bez směrů: "49.23173, 17.42791"
                        lat = float(groups[0].replace(',', '.'))
                        lon = float(groups[1].replace(',', '.'))
                        return (lat, lon)
                        
                    elif len(groups) == 4 and groups[0] in 'SJVZNSEW':
                        # Formát s prefix směry: "S49.23173 V17.42791"
                        lat_dir = groups[0].upper()
                        lat_val = float(groups[1].replace(',', '.'))
                        lon_dir = groups[2].upper()
                        lon_val = float(groups[3].replace(',', '.'))
                        
                        lat = lat_val
                        lon = lon_val
                        
                        # České směry
                        if lat_dir == 'J':  # Jih
                            lat = -lat_val
                        elif lat_dir == 'S':  # Sever
                            lat = lat_val
                        
                        if lon_dir == 'Z':  # Západ
                            lon = -lon_val
                        elif lon_dir == 'V':  # Východ
                            lon = lon_val
                        
                        # Anglické směry
                        if lat_dir == 'S' and lon_dir in 'EW':  # Anglické S = South
                            lat = -lat_val
                        elif lat_dir == 'N':  # North
                            lat = lat_val
                        
                        if lon_dir == 'W':  # West
                            lon = -lon_val
                        elif lon_dir == 'E':  # East
                            lon = lon_val
                        
                        return (lat, lon)
            
            return None
            
        except Exception as e:
            print(f"Chyba při parsování souřadnic: {e}")
            return None

    def test_coordinate_parsing(self):
        """Real‑time kontrola souřadnic; neplánuje náhled, pouze validuje a informuje."""
        coord_text = self.input_manual_coords.text()
        if coord_text.strip():
            try:
                result = self.parse_coordinates(coord_text)
                if result:
                    lat, lon = result
                    lat_dir = 'J' if lat < 0 else 'S'
                    lon_dir = 'Z' if lon < 0 else 'V'
                    self.label_parsed_coords.setText(f"Parsované: {abs(lat):.6f}° {lat_dir}, {abs(lon):.6f}° {lon_dir}")
                    self.label_parsed_coords.setStyleSheet("QLabel { color: #4CAF50; font-style: italic; }")
                    # Jen označit, že náhled už neodpovídá GUI hodnotám
                    self._flag_gps_preview_outdated()
                else:
                    self.label_parsed_coords.setText("❌ Neplatný formát souřadnic")
                    self.label_parsed_coords.setStyleSheet("QLabel { color: #f44336; font-style: italic; }")
            except Exception as e:
                self.label_parsed_coords.setText(f"❌ Chyba: {str(e)}")
                self.label_parsed_coords.setStyleSheet("QLabel { color: #f44336; font-style: italic; }")
        else:
            self.label_parsed_coords.setText("Zadejte souřadnice...")
            self.label_parsed_coords.setStyleSheet("QLabel { color: #666; font-style: italic; }")
            
    def _on_gps_param_changed(self, *_):
        """Reakce na změnu parametrů – pouze označí náhled jako neaktuální (žádné automatické stahování)."""
        self._flag_gps_preview_outdated()

    
    def _flag_gps_preview_outdated(self):
        """Označí náhled vs GUI; NEmaže _last_map_req, pouze aktualizuje indikaci."""
        try:
            last = getattr(self, "_last_map_req", None)
            if not last:
                return
            current = self._get_normalized_gps_preview_tuple()
            if current is None:
                # Chovej se jako neshoda (neplatné GUI) – overlay ON
                self._set_consistency_ui(getattr(self, "_preview_source", "generated"), False)
                return
            self._set_consistency_ui(getattr(self, "_preview_source", "generated"), current == last)
        except Exception:
            pass
    
    def on_auto_id_toggled(self, checked):
        """Přepnutí automatického ID – nyní s prvním volným číslem a přejmenováním labelu."""
        # Povolení/zakázání ručního editování
        if hasattr(self, "input_manual_id"):
            self.input_manual_id.setEnabled(not checked)
    
        # Přejmenovat label podle režimu
        try:
            if hasattr(self, "label_id_mode") and self.label_id_mode:
                self.label_id_mode.setText("Automatické ID:" if checked else "Ruční ID:")
        except Exception:
            pass
    
        # Při automatickém režimu dosadit první volné číslo do pole (zobrazení, které se použije)
        if checked:
            try:
                auto_id = self.find_first_free_location_id()
                if hasattr(self, "input_manual_id") and self.input_manual_id:
                    self.input_manual_id.setText(auto_id)
            except Exception:
                # V krajním případě ponechat stávající hodnotu
                pass
    
        # Původní logování ponecháno
        if checked:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("🔢 Automatické ID: Hledá se první volné číslo v existujících souborech", "info")
        else:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("✏️ Ruční ID: Použije se zadané číslo", "info")

    def browse_photo(self):
        """Procházení fotky - AKTUALIZOVÁNO s lepšími filtry"""
        mode = self.combo_coord_mode.currentIndex()
        
        if mode == 0:  # F - Ze souboru fotky
            title = "Vyberte fotografii s GPS daty"
            filters = "Fotografie (*.heic *.jpg *.jpeg *.png *.tiff);;Všechny soubory (*)"
        else:  # G - Ruční zadání
            title = "Vyberte existující lokační mapu"
            filters = "Obrázky map (*.png *.jpg *.jpeg *.tiff);;Všechny soubory (*)"
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            filters
        )
        if file_path:
            self.input_photo.setText(file_path)
            
    def browse_output_dir(self):
        """Procházení výstupní složky"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Vyberte výstupní složku"
        )
        if dir_path:
            self.input_output_dir.setText(dir_path)

    # === PARAMETRY A ZPRACOVÁNÍ ===

    def get_parameters(self):
        """Získání všech parametrů z GUI"""
        coord_mode = "F" if self.combo_coord_mode.currentIndex() == 0 else "G"
        return {
            'coordinate_mode': coord_mode,
            'manual_coordinates': self.input_manual_coords.text(),
            'zoom': self.spin_zoom.value(),
            'photo_filename': self.input_photo.text(),
            'output_filename': "mapa_dlazdice.png",
            'app_name': self.input_app_name.text(),
            'contact_email': self.input_email.text(),
            'watermark_size_mm': self.spin_watermark.value(),
            'id_lokace': self.input_id_lokace.text(),
            'popis': self.input_popis.text(),
            'auto_generate_id': self.check_auto_id.isChecked(),
            'manual_cislo_id': self.input_manual_id.text(),
            'output_width_cm': self.spin_width.value(),
            'output_height_cm': self.spin_height.value(),
            'output_dpi': self.spin_dpi.value(),
            'output_directory': self.input_output_dir.text(),
            'map_opacity': self.spin_opacity.value(),
            'request_delay': self.spin_delay.value(),
            'marker_size': self.spin_marker_size.value(),
            'marker_style': self.get_marker_style_from_settings(),  # 'dot' | 'cross'
            # 🔸 NOVÉ: přepínač anonymizace z GUI, aby se propsal i při "Spustit generování"
            'anonymizovana_lokace': bool(self.checkbox_anonymni_lokace.isChecked()),
        }

    def start_processing(self):
        """UPRAVENÁ FUNKCE: Spuštění zpracování – pouze sekundární ovládání"""
        # Validace parametrů
        params = self.get_parameters()
        coord_mode = params['coordinate_mode']  # 'F' nebo 'G'
    
        # 1) Vstupní soubor je POVINNÝ jen v režimu F (Ze souboru fotky)
        if coord_mode == 'F':
            if not params['photo_filename'] or not Path(params['photo_filename']).exists():
                QMessageBox.warning(self, "Chyba", "Vyberte fotografii s GPS daty!")
                return
        else:
            # Režim G: soubor je VOLITELNÝ; pokud je vyplněn a neexistuje, jen varuj do logu
            if params['photo_filename'] and not Path(params['photo_filename']).exists():
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log("ℹ️ Referenční soubor nebyl nalezen – pokračuji bez něj.", "warning")
            # Režim G stále vyžaduje ruční souřadnice
            if coord_mode == 'G' and not params['manual_coordinates'].strip():
                QMessageBox.warning(self, "Chyba", "Zadejte GPS souřadnice pro ruční režim!")
                return
    
        # 2) Validace výstupní složky (beze změny)
        output_dir = Path(params['output_directory'])
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "Chyba", f"Nelze vytvořit výstupní složku:\n{str(e)}")
            return
    
        # 3) NOVĚ: Při zapnutém „Automatické ID“ dosadit PRVNÍ VOLNÉ číslo a přepnout na ruční pro tento běh
        try:
            if params.get('auto_generate_id', False):
                try:
                    next_id = self.find_first_free_location_id()  # vrací '00001', nebo nejmenší díru, jinak max+1
                except Exception:
                    # Fallback: vezmi hodnotu v UI nebo '00001'
                    next_id = (self.input_manual_id.text().strip() if hasattr(self, 'input_manual_id') else "") or "00001"
                # Přinutit generátor použít právě toto číslo pro tento běh
                params['manual_cislo_id'] = next_id
                params['auto_generate_id'] = False
                # Volitelně: zalogovat použitou strategii
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"🔢 Automatické ID → použito první volné: {next_id}", "info")
        except Exception:
            pass
    
        # 4) Validace ručního ID pokud je použito (proběhne i pro „nově dosazené“)
        if not params['auto_generate_id']:
            try:
                manual_id_num = int(params['manual_cislo_id'])
                if manual_id_num < 1 or manual_id_num > 99999:
                    QMessageBox.warning(self, "Chyba", "Ruční ID musí být číslo mezi 1 a 99999!")
                    return
            except ValueError:
                QMessageBox.warning(self, "Chyba", "Ruční ID musí být platné číslo!")
                return
    
        # 5) Uložení konfigurace (beze změny – UI režim zůstává, override je jen pro tento běh)
        self.save_config()
    
        # 6) Vytvoření a spuštění threadu (beze změny)
        self.processor_thread = ProcessorThread(params)
        self.processor_thread.finished.connect(self.on_processing_finished)
        self.processor_thread.error.connect(self.on_processing_error)
        self.processor_thread.progress.connect(self.on_progress_update)
        self.processor_thread.log.connect(self.log_widget.add_log)
        self.processor_thread.status.connect(self.status_widget.set_status)
    
        # UI změny – pouze sekundární tlačítka (beze změny)
        self.btn_start_secondary.setEnabled(False)
        self.btn_stop_secondary.setEnabled(True)
        self.tabs.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_widget.set_status("processing", "Zpracovávám...")
    
        # Logování začátku – zobraz „ruční (XXXXX)“, protože jsme číslo právě dosadili
        try:
            mode_text = "ze souboru fotky" if params['coordinate_mode'] == 'F' else "ruční zadání"
            id_text = f"ruční ({params.get('manual_cislo_id', '00001')})" if not params.get('auto_generate_id', False) else "automatické"
            self.log_widget.add_log(f"🚀 Spouštím generování - GPS: {mode_text}, ID: {id_text}", "info")
        except Exception:
            pass
    
        # Spuštění
        self.processor_thread.start()

    def stop_processing(self):
        """UPRAVENÁ FUNKCE: Zastavení zpracování – pouze sekundární ovládání"""
        if self.processor_thread:
            self.processor_thread.stop()
            self.processor_thread.quit()
            self.processor_thread.wait()
            
        # Sekundární tlačítka
        self.btn_start_secondary.setEnabled(True)
        self.btn_stop_secondary.setEnabled(False)
        
        self.tabs.setEnabled(True)
        
        self.progress_bar.setVisible(False)
        self.status_widget.set_status("idle", "Připraven")
        
        self.log_widget.add_log("⏹ Zpracování zastaveno uživatelem", "warning")

    @Slot(str)
    def on_processing_error(self, error_message):
        """UPRAVENÁ FUNKCE: Chyba – bez spodních tlačítek"""
        self.processor_thread.quit()
        self.processor_thread.wait()
        
        # Sekundární ovládání
        self.btn_start_secondary.setEnabled(True)
        self.btn_stop_secondary.setEnabled(False)
        
        self.tabs.setEnabled(True)
        
        self.progress_bar.setVisible(False)
        self.status_widget.set_status("error", "Chyba!")
        
        self.log_widget.add_log(f"❌ Chyba: {error_message}", "error")
        
        QMessageBox.critical(self, "Chyba", f"Došlo k chybě:\n\n{error_message}")

        
    @Slot(int)
    def on_progress_update(self, value):
        """Aktualizace progress baru"""
        self.progress_bar.setValue(value)

    # === KONFIGURACE A UKONČENÍ ===
        
    def save_config(self):
        """Uložení konfigurace včetně marker_style a GPS preview zoomu."""
        config = self.get_parameters()
        config['maps_folder_path'] = str(self.default_maps_path)
        if hasattr(self, 'file_tree') and self.file_tree is not None:
            try:
                expanded_state = self.save_tree_expansion_state()
                config['tree_expanded_state'] = list(expanded_state)
                self.log_widget.add_log(f"💾 Uložen stav rozbalení ({len(expanded_state)} položek)", "info")
            except Exception as e:
                self.log_widget.add_log(f"⚠️ Chyba při ukládání stavu rozbalení: {e}", "warning")
                config['tree_expanded_state'] = []
        else:
            config['tree_expanded_state'] = []
        try:
            if hasattr(self, "spin_preview_zoom"):
                z = int(self.spin_preview_zoom.value())
                config.setdefault("gps", {})
                if isinstance(config["gps"], dict):
                    config["gps"]["preview_zoom"] = z
                config["gps_preview_zoom"] = z
        except Exception:
            pass
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self.log_widget.add_log("💾 Konfigurace uložena", "info")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"❌ Chyba při ukládání konfigurace: {e}", "error")
    
    def load_config(self):
        """Načtení konfigurace včetně marker_style (bez okamžitého spuštění náhledu)."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                if 'maps_folder_path' in config:
                    self.default_maps_path = Path(config['maps_folder_path'])
                    self.label_maps_path.setText(str(self.default_maps_path))
                if 'tree_expanded_state' in config and config['tree_expanded_state']:
                    self.saved_tree_expansion_state = set(config['tree_expanded_state'])
                    self.log_widget.add_log(
                        f"📂 Načten uložený stav rozbalení ({len(self.saved_tree_expansion_state)} položek)", "info"
                    )
                else:
                    self.saved_tree_expansion_state = set()
                    self.log_widget.add_log("📂 Žádný uložený stav rozbalení nenalezen", "info")
                if 'coordinate_mode' in config:
                    self.combo_coord_mode.setCurrentIndex(0 if config['coordinate_mode'] == 'F' else 1)
                if 'manual_coordinates' in config:
                    self.input_manual_coords.setText(config['manual_coordinates'])
                if 'zoom' in config:
                    self.spin_zoom.setValue(config['zoom'])
                if 'photo_filename' in config:
                    self.input_photo.setText(config['photo_filename'])
                if 'app_name' in config:
                    self.input_app_name.setText(config['app_name'])
                if 'contact_email' in config:
                    self.input_email.setText(config['contact_email'])
                if 'watermark_size_mm' in config:
                    self.spin_watermark.setValue(config['watermark_size_mm'])
                if 'id_lokace' in config:
                    self.input_id_lokace.setText(config['id_lokace'])
                if 'popis' in config:
                    self.input_popis.setText(config['popis'])
                if 'auto_generate_id' in config:
                    self.check_auto_id.setChecked(config['auto_generate_id'])
                if 'manual_cislo_id' in config:
                    self.input_manual_id.setText(config['manual_cislo_id'])
                if 'output_width_cm' in config:
                    self.spin_width.setValue(config['output_width_cm'])
                if 'output_height_cm' in config:
                    self.spin_height.setValue(config['output_height_cm'])
                if 'output_dpi' in config:
                    self.spin_dpi.setValue(config['output_dpi'])
                if 'output_directory' in config:
                    self.input_output_dir.setText(config['output_directory'])
                if 'map_opacity' in config:
                    self.spin_opacity.setValue(config['map_opacity'])
                if 'request_delay' in config:
                    self.spin_delay.setValue(config['request_delay'])
                if 'marker_size' in config:
                    self.spin_marker_size.setValue(config['marker_size'])
                try:
                    z = None
                    if isinstance(config.get("gps"), dict) and "preview_zoom" in config["gps"]:
                        z = int(config["gps"]["preview_zoom"])
                    elif "gps_preview_zoom" in config:
                        z = int(config["gps_preview_zoom"])
                    if z is not None and hasattr(self, "spin_preview_zoom"):
                        self.spin_preview_zoom.blockSignals(True)
                        self.spin_preview_zoom.setValue(z)
                        self.spin_preview_zoom.blockSignals(False)
                except Exception:
                    pass
                # marker_style -> ComboBox
                try:
                    ms = (config.get("marker_style") or "").lower()
                    if hasattr(self, "combo_marker_style"):
                        if ms == "cross":
                            self.combo_marker_style.setCurrentIndex(1)
                        else:
                            self.combo_marker_style.setCurrentIndex(0)
                except Exception:
                    pass
                self.on_auto_id_toggled(self.check_auto_id.isChecked())
                self.test_coordinate_parsing()
                self.log_widget.add_log("✅ Konfigurace načtena (náhled GPS se načte při otevření záložky)", "success")
            except Exception as e:
                if hasattr(self, 'log_widget'):
                    self.log_widget.add_log(f"❌ Chyba při načítání konfigurace: {e}", "error")
                self.saved_tree_expansion_state = set()
        else:
            self.saved_tree_expansion_state = set()
            self.log_widget.add_log("📂 Konfigurační soubor neexistuje - použit výchozí stav", "info")

    def _get_preview_cache_paths(self):
        """Vrátí (img_path, meta_path) do per‑user cache pro náhled mapy."""
        from pathlib import Path
        base = Path.home() / ".cache" / "osm_map_generator"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base / "gps_preview.png", base / "gps_preview.json"
    
    def save_preview_cache(self, pixmap, meta_tuple):
        """
        Uloží náhled do cache jako PNG + JSON s normalizovanou pěticí (lat6, lon6, zoom, style, size).
        meta_tuple = (lat6, lon6, zoom, style, size)
        """
        try:
            if pixmap is None:
                return
            img_path, meta_path = self._get_preview_cache_paths()
            # Ulož PNG (zkontrolovat výsledek)
            ok = pixmap.save(str(img_path), "PNG")
            if not ok:
                raise RuntimeError(f"QPixmap.save selhalo pro {img_path}")
            # Ulož JSON metadata se správnými indexy
            import json
            lat6, lon6, zoom, style, size = meta_tuple
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "lat": float(lat6),
                    "lon": float(lon6),
                    "zoom": int(zoom),
                    "style": "cross" if str(style).lower().strip() == "cross" else "dot",
                    "size": int(size),
                }, f, ensure_ascii=False, indent=2)
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"💾 Cache náhledu uložena: {img_path.name}", "info")
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Uložení cache náhledu selhalo: {e}", "warning")

    def load_preview_cache(self):
        """
        Načte náhled z cache. Vrací (QPixmap, meta_tuple) nebo (None, None),
        kde meta_tuple = (lat6, lon6, zoom, style, size).
        """
        try:
            from PySide6.QtGui import QPixmap
            import json
            img_path, meta_path = self._get_preview_cache_paths()
            if not img_path.exists() or not meta_path.exists():
                return None, None
            pix = QPixmap(str(img_path))
            if pix.isNull():
                return None, None
            with open(meta_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            meta_tuple = (
                round(float(d.get("lat")), 6),
                round(float(d.get("lon")), 6),
                int(d.get("zoom")),
                "cross" if str(d.get("style")).lower().strip() == "cross" else "dot",
                int(d.get("size")),
            )
            return pix, meta_tuple
        except Exception as e:
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log(f"⚠️ Načtení cache náhledu selhalo: {e}", "warning")
            return None, None
        
    def find_first_free_location_id(self) -> str:
        """
        Najde první volné číslo lokace podle stromu 'Neroztříděné':
        - pokud existují mezery v 1..max, vrátí nejmenší chybějící,
        - jinak vrátí max+1,
        - při chybě vrátí "00001".
        """
        try:
            state = self.analyze_unsorted_location_ids()
            ids = state.get('ids', set()) or set()
            if not ids:
                return "00001"
            mx = int(state.get('max') or 0)
            missing = list(state.get('missing', [])) or []
            if missing:
                return f"{int(min(missing)):05d}"
            return f"{mx + 1:05d}"
        except Exception:
            return "00001"


    def closeEvent(self, event):
        """Zavření aplikace + uložení cache náhledu (pokud existuje pixmapa)."""
        try:
            # Uložení cache náhledu (pokud máme pixmapu a last tuple)
            try:
                pm = self.map_label.pixmap() if hasattr(self, "map_label") else None
            except Exception:
                pm = None
            tpl = getattr(self, "_last_map_req", None)
            if pm is not None and not pm.isNull() and tpl is not None:
                self.save_preview_cache(pm, tpl)
        except Exception:
            pass
        """Zavření aplikace s uložením geometrie okna, stavu sloupců stromu a konfigurace."""
        try:
            # 1) Uložení geometrie hlavního okna (QByteArray do QSettings)
            if hasattr(self, "settings"):
                self.settings.setValue("window/geometry", self.saveGeometry())  # uloží QByteArray [2]
            
            # 2) Uložení stavu hlavičky stromu (šířky/pořadí/viditelnost sloupců)
            if hasattr(self, 'file_tree') and self.file_tree is not None:
                try:
                    header_state = self.file_tree.header().saveState()  # QByteArray [3]
                    if hasattr(self, "settings"):
                        self.settings.setValue("file_tree/header_state", header_state)  # uložit do QSettings [1]
                except Exception:
                    pass
    
            # 3) (Váš existující) uložený stav rozbalení
            try:
                if hasattr(self, 'file_tree') and self.file_tree is not None:
                    current_expanded_state = self.save_tree_expansion_state()
                    if current_expanded_state:
                        self.saved_tree_expansion_state = current_expanded_state
                        self.log_widget.add_log(f"💾 Uložen aktuální stav rozbalení před zavřením ({len(current_expanded_state)} položek)", "info")
            except Exception as e:
                self.log_widget.add_log(f"⚠️ Chyba při ukládání stavu před zavřením: {e}", "warning")
    
            # 4) Uložení konfigurace (váš původní mechanismus)
            self.save_config()
    
            # 5) Zastavení běžícího zpracování
            if self.processor_thread and self.processor_thread.isRunning():
                self.processor_thread.stop()
                self.processor_thread.quit()
                self.processor_thread.wait()
    
            # 6) Zapsat QSettings na disk
            if hasattr(self, "settings"):
                self.settings.sync()  # jistota zapsání před ukončením [1]
    
            self.log_widget.add_log("👋 Aplikace se zavírá - konfigurace a rozměry uloženy", "info")
    
        except Exception as e:
            print(f"Chyba při zavírání aplikace: {e}")
    
        # Nechat QMainWindow dokončit zavření
        super().closeEvent(event)  # místo event.accept() je korektnější volat parent implementaci [4]
