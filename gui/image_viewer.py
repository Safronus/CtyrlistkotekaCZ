# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                              QPushButton, QScrollArea, QTextEdit, QSplitter,
                              QGroupBox, QGridLayout, QFrame, QWidget, QMessageBox, QLineEdit)  # PŘIDÁNO QMessageBox
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QPointF
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication
import json
from PIL import Image, ImageQt
from PIL.PngImagePlugin import PngInfo
from pathlib import Path
import platform  # PŘIDÁNO pro detekci OS
import os  # PŘIDÁNO pro smazání souboru


class ImageViewerDialog(QDialog):
    """Dialog pro zobrazení obrázku s metadaty"""
    
    # NOVÝ SIGNÁL pro oznámení smazání souboru
    file_deleted = Signal(str)
    
    # NOVÝ SIGNÁL: oznamuje aktuálně zobrazený soubor
    current_file_changed = Signal(str)  # absolutní cesta
    file_deleted = Signal(str)
    
    def __init__(self, image_path, parent=None, show_delete_button=False,
                 file_list=None, current_index=0, close_on_space=False):
        super().__init__(parent)
        self.image_path = Path(image_path)
        self.show_delete_button = show_delete_button
        # Nové: volitelně zavřít dialog klávesou SPACE
        self.close_on_space = bool(close_on_space)
        
        # Nové: seznam a index
        self.file_list = list(file_list) if file_list else None
        self.current_index = int(current_index) if file_list else 0
        self.init_ui()
        self.load_image_and_metadata()
        # Auto-fit režim
        self.fit_mode = True
        self._auto_fit_requested = False

        
    def init_ui(self):
        """Inicializace UI s navigací, zoomem a metadaty"""
        self.setWindowTitle(f"Prohlížeč obrázku - {self.image_path.name}")
        self.setGeometry(100, 100, 1800, 1000)
    
        from PySide6.QtWidgets import QSizePolicy  # lokální import kvůli novým politikám
    
        # Hlavní layout
        main_layout = QVBoxLayout(self)
    
        # Splitter pro rozdělení na obrázek a metadata
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)  # nedovolit kolaps panelů
        main_layout.addWidget(self.splitter)
    
        # Levá strana - obrázek (rezervovat si prostor)
        self.image_container = QWidget()
        self.image_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        image_layout = QVBoxLayout(self.image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)
    
        # Scroll area pro obrázek
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)  # důležité pro fit do viewportu
        self.scroll_area.setAlignment(Qt.AlignCenter)  # zarovnání obsahu doprostřed
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("QLabel { background-color: #1e1e1e; }")
        self.image_label.setMinimumSize(1, 1)
        self.scroll_area.setWidget(self.image_label)
        image_layout.addWidget(self.scroll_area)
    
        # Ovládací řádek: navigace + zoom
        zoom_layout = QHBoxLayout()
        # Navigace mezi soubory (aktivní, pokud je dialog otevřen s file_list)
        self.btn_prev = QPushButton("⟵ Předchozí")
        self.btn_next = QPushButton("Další ⟶")
        self.btn_prev.clicked.connect(self.navigate_prev)
        self.btn_next.clicked.connect(self.navigate_next)
        zoom_layout.addWidget(self.btn_prev)
        zoom_layout.addWidget(self.btn_next)
    
        # Zoom tlačítka
        self.btn_zoom_in = QPushButton("🔍+ Přiblížit")
        self.btn_zoom_out = QPushButton("🔍- Oddálit")
        self.btn_zoom_fit = QPushButton("📐 Přizpůsobit")
        self.btn_zoom_100 = QPushButton("1:1 Skutečná velikost")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_zoom_fit.clicked.connect(self.zoom_fit)
        self.btn_zoom_100.clicked.connect(self.zoom_100)
        zoom_layout.addWidget(self.btn_zoom_in)
        zoom_layout.addWidget(self.btn_zoom_out)
        zoom_layout.addWidget(self.btn_zoom_fit)
        zoom_layout.addWidget(self.btn_zoom_100)
        zoom_layout.addStretch()
        image_layout.addLayout(zoom_layout)
    
        # Pravá strana - metadata (přizpůsobuje se)
        self.metadata_widget = QWidget()
        self.metadata_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        metadata_layout = QVBoxLayout(self.metadata_widget)
    
        # Základní informace
        info_group = QGroupBox("📋 Základní informace")
        info_layout = QGridLayout()
        # Název jako read-only QLineEdit (neexpanduje podle délky textu)
        self.edit_filename = QLineEdit()
        self.edit_filename.setReadOnly(True)
        self.edit_filename.setCursorPosition(0)
        self.edit_filename.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # pro kompatibilitu – použij stávající atribut v ostatních funkcích
        self.label_filename = self.edit_filename
    
        self.label_dimensions = QLabel()
        self.label_filesize = QLabel()
        self.label_output_params = QLabel("—")
    
        info_layout.addWidget(QLabel("Název:"), 0, 0)
        info_layout.addWidget(self.edit_filename, 0, 1)
        info_layout.addWidget(QLabel("Rozměry:"), 1, 0)
        info_layout.addWidget(self.label_dimensions, 1, 1)
        info_layout.addWidget(QLabel("Velikost souboru:"), 2, 0)
        info_layout.addWidget(self.label_filesize, 2, 1)
        info_layout.addWidget(QLabel("Výstup (cm/DPI):"), 3, 0)
        info_layout.addWidget(self.label_output_params, 3, 1)
        info_group.setLayout(info_layout)
        metadata_layout.addWidget(info_group)
    
        # GPS informace
        gps_group = QGroupBox("📍 GPS informace")
        gps_layout = QGridLayout()
        self.label_gps_lat = QLabel("---")
        self.label_gps_lon = QLabel("---")
        self.label_gps_source = QLabel("---")
        gps_layout.addWidget(QLabel("Zeměpisná šířka:"), 0, 0)
        gps_layout.addWidget(self.label_gps_lat, 0, 1)
        gps_layout.addWidget(QLabel("Zeměpisná délka:"), 1, 0)
        gps_layout.addWidget(self.label_gps_lon, 1, 1)
        gps_layout.addWidget(QLabel("Zdroj GPS:"), 2, 0)
        gps_layout.addWidget(self.label_gps_source, 2, 1)
        gps_layout.addWidget(QLabel("GPS souřadnice:"), 3, 0)
        self.edit_gps_combined = QLineEdit()
        self.edit_gps_combined.setReadOnly(True)
        self.edit_gps_combined.setPlaceholderText("—")
        gps_layout.addWidget(self.edit_gps_combined, 3, 1)
        gps_group.setLayout(gps_layout)
        metadata_layout.addWidget(gps_group)
    
        # Metadata – textový výpis
        metadata_group = QGroupBox("🏷️ Metadata")
        metadata_group_layout = QVBoxLayout()
        self.metadata_text = QTextEdit()
        self.metadata_text.setMaximumHeight(600)
        if platform.system() == 'Darwin':
            monospace_font = QFont("Monaco", 11)
        elif platform.system() == 'Windows':
            monospace_font = QFont("Consolas", 11)
        else:
            monospace_font = QFont("DejaVu Sans Mono", 11)
        monospace_font.setStyleHint(QFont.Monospace)
        self.metadata_text.setFont(monospace_font)
        metadata_group_layout.addWidget(self.metadata_text)
        metadata_group.setLayout(metadata_group_layout)
        metadata_layout.addWidget(metadata_group)
    
        # Přidání do splitteru a priority
        self.splitter.addWidget(self.image_container)
        self.splitter.addWidget(self.metadata_widget)
        self.splitter.setStretchFactor(0, 1)  # levý má prioritu (drží si šířku)
        self.splitter.setStretchFactor(1, 0)  # pravý se přizpůsobuje
        self.splitter.setSizes([1200, 600])   # počáteční rozdělení
    
        # Spodní tlačítka – MINIMÁLNÍ ÚPRAVA: sjednocený styl + konzistentní pořadí
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(8, 8, 8, 8)
        button_layout.setSpacing(8)
    
        def _style_btn(btn: QPushButton, base: str, hover: str, pressed: str, min_h: int = 32, max_w: int | None = None):
            btn.setMinimumHeight(min_h)
            if max_w:
                btn.setMaximumWidth(max_w)
            btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {base};
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{ background-color: #cccccc; color: #666666; }}
            """)
    
        GREEN = ("#2e7d32", "#388e3c", "#1b5e20")
        RED = ("#e53935", "#d32f2f", "#b71c1c")
    
        button_layout.addStretch()
        self.btn_open_folder = QPushButton("📂 Otevřít složku")
        self.btn_open_folder.clicked.connect(self.open_folder)
        _style_btn(self.btn_open_folder, *GREEN)
        button_layout.addWidget(self.btn_open_folder)
    
        if self.show_delete_button:
            self.btn_delete = QPushButton("🗑️ Smazat soubor")
            self.btn_delete.clicked.connect(self.delete_file)
            _style_btn(self.btn_delete, *RED)
            button_layout.addWidget(self.btn_delete)
    
        self.btn_close = QPushButton("✅ Zavřít")
        self.btn_close.clicked.connect(self.accept)
        _style_btn(self.btn_close, *GREEN)
        button_layout.addWidget(self.btn_close)
        main_layout.addLayout(button_layout)
    
        # Stav zoomu a zkratky
        self.current_scale = 1.0
        self.original_pixmap = None
        
        from PySide6.QtGui import QShortcut, QKeySequence
        
        self._sc_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        self._sc_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        self._sc_left.activated.connect(self.navigate_prev)
        self._sc_right.activated.connect(self.navigate_next)
        
        # NOVÉ: šipky nahoru/dolů jako aliasy pro předchozí/další
        self._sc_up = QShortcut(QKeySequence(Qt.Key_Up), self)
        self._sc_down = QShortcut(QKeySequence(Qt.Key_Down), self)
        self._sc_up.activated.connect(self.navigate_prev)
        self._sc_down.activated.connect(self.navigate_next)
        
        if self.show_delete_button:
            self._sc_del = QShortcut(QKeySequence(Qt.Key_Delete), self)
            self._sc_del.activated.connect(self.delete_file)
        
        # OPRAVENO: CMD+W zkratka pro zavření (mělo by fungovat, ale pro jistotu)
        self._sc_close = QShortcut(QKeySequence.Close, self)  # CMD+W na macOS
        self._sc_close.activated.connect(self.reject)
        
        # PŘIDÁNO: Escape jako další možnost zavření
        self._sc_escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._sc_escape.activated.connect(self.reject)
        
        self.update_nav_buttons()
        
        # Volitelné zavření dialogu klávesou SPACE (pouze když je explicitně požadováno)
        if getattr(self, "close_on_space", False):
            self._sc_space_close = QShortcut(QKeySequence(Qt.Key_Space), self)
            self._sc_space_close.setAutoRepeat(False)
            self._sc_space_close.activated.connect(self.accept)

    # Vložte tuto metodu dovnitř třídy ImageViewerDialog v image_viewer.py
    
    from PySide6.QtGui import QKeySequence
    
    def keyPressEvent(self, event):
        """
        Zachytává stisky kláves na úrovni celého dialogu, aby zkratky
        fungovaly i když je focus na jiném widgetu (např. QLineEdit).
        """
        QShortcut(QKeySequence.Close, self, activated=self.accept)
    
        # Pokud to nebyla naše zkratka, předáme událost dál pro normální zpracování
        # (např. psaní textu do inputu)
        super().keyPressEvent(event)

        
    def update_nav_buttons(self):
        """NOVÁ FUNKCE: Povolí/zakáže Předchozí/Další a šipkové zkratky podle current_index a file_list."""
        total = len(self.file_list) if self.file_list else 0
        has_many = total > 1
    
        # Výchozí stavy
        prev_enabled = has_many and self.current_index > 0
        next_enabled = has_many and self.current_index < (total - 1)
    
        # Tlačítka
        if hasattr(self, 'btn_prev'):
            self.btn_prev.setEnabled(prev_enabled)
            self.btn_prev.setToolTip("" if prev_enabled else "Na začátku seznamu")
        if hasattr(self, 'btn_next'):
            self.btn_next.setEnabled(next_enabled)
            self.btn_next.setToolTip("" if next_enabled else "Na konci seznamu")
    
        # Šipkové zkratky lze také zapnout/vypnout
        if hasattr(self, '_sc_left'):
            self._sc_left.setEnabled(prev_enabled)   # PySide6 QShortcut má setEnabled [2]
        if hasattr(self, '_sc_right'):
            self._sc_right.setEnabled(next_enabled)  # PySide6 QShortcut má setEnabled [2]
            
        if hasattr(self, '_sc_up'):
            self._sc_up.setEnabled(prev_enabled)
        if hasattr(self, '_sc_down'):
            self._sc_down.setEnabled(next_enabled)

    def navigate_prev(self):
        if not self.file_list:
            return
        if self.current_index > 0:
            self.current_index -= 1
            self.image_path = Path(self.file_list[self.current_index])
            self.load_image_and_metadata()
            self.update_nav_buttons()
            # NOVÉ: oznam změnu aktuálního souboru
            self.current_file_changed.emit(str(self.image_path))

    def navigate_next(self):
        if not self.file_list:
            return
        if self.current_index < len(self.file_list) - 1:
            self.current_index += 1
            self.image_path = Path(self.file_list[self.current_index])
            self.load_image_and_metadata()
            self.update_nav_buttons()
            # NOVÉ: oznam změnu aktuálního souboru
            self.current_file_changed.emit(str(self.image_path))

    def delete_file(self):
        """Smazání souboru; v režimu prohlížeče pokračuje dál bez zavření."""
        reply = QMessageBox.question(
            self, "Potvrdit smazání",
            f"Opravdu chcete smazat tento soubor?\n\n{self.image_path.name}\n\nTato akce je nevratná!",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(self.image_path)
            self.file_deleted.emit(str(self.image_path))
            QMessageBox.information(self, "Soubor smazán", f"Soubor {self.image_path.name} byl úspěšně smazán.")
            if self.file_list:
                try:
                    del self.file_list[self.current_index]
                except Exception:
                    pass
                if not self.file_list:
                    self.accept()
                    return
                if self.current_index >= len(self.file_list):
                    self.current_index = len(self.file_list) - 1
                self.image_path = Path(self.file_list[self.current_index])
                self.load_image_and_metadata()
                self.update_nav_buttons()
                # NOVÉ: oznam změnu aktuálního souboru po smazání
                self.current_file_changed.emit(str(self.image_path))
                return
            # Původní chování mimo prohlížeč: zavřít dialog
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Chyba při mazání", f"Nepodařilo se smazat soubor:\n\n{str(e)}")
 
    def set_combined_gps_text(self, text):
        """
        Přidá do panelu informací řádek se spojenými souřadnicemi, např. „49.23091° S, 17.65690° V“.
        Nic neodebírá a nenahrazuje – pouze doplňuje řádek „Souřadnice (spojené): <text>“.
        """
        try:
            from PySide6.QtWidgets import QLabel
    
            # 1) Pokud už máme samostatný štítek pro spojené souřadnice, jen ho aktualizuj
            if hasattr(self, 'label_gps_combined') and isinstance(self.label_gps_combined, QLabel):
                self.label_gps_combined.setText(f"Souřadnice (spojené): {text}")
                return
    
            # 2) Pokud existuje nějaký „info“ layout/panel, přidej do něj nový řádek s QLabel
            #    (název atributu je zvolen tak, aby nenarušil existující logiku)
            new_label = QLabel(f"Souřadnice (spojené): {text}", self)
            new_label.setObjectName("label_gps_combined")
    
            # Heuristicky zkusíme umístění do známých sekcí, aniž bychom narušili existující obsah
            # a bez nutnosti měnit stávající kód (pouze přidáváme widget):
            # - pokud je k dispozici layout s názvem info_layout / meta_layout / right_layout,
            #   vložíme tam; jinak widget přidáme na konec hlavního layoutu dialogu.
            candidate_layouts = []
            for name in ('info_layout', 'meta_layout', 'right_layout', 'details_layout'):
                lay = getattr(self, name, None)
                if lay is not None and hasattr(lay, 'addWidget'):
                    candidate_layouts.append(lay)
    
            if candidate_layouts:
                candidate_layouts.addWidget(new_label)
                self.label_gps_combined = new_label
                return
    
            # 3) Fallback: pokud máme centrální layout dialogu, přidej štítek na konec
            root_layout = getattr(self, 'layout', None)
            if callable(root_layout):
                lay_obj = self.layout()
                if lay_obj is not None and hasattr(lay_obj, 'addWidget'):
                    lay_obj.addWidget(new_label)
                    self.label_gps_combined = new_label
                    return
    
            # 4) Poslední fallback: aktualizuj titulek okna (viditelné a bez změny obsahu panelu)
            self.setWindowTitle(f"{self.windowTitle()} — {text}")
        except Exception:
            # Bez výjimky – necháme dialog běžet dál beze změny
            pass

    def load_image_and_metadata(self):
        """Načtení obrázku a metadat s automatickým 'Přizpůsobit' po načtení"""
        if not self.image_path.exists():
            self.image_label.setText("❌ Soubor nenalezen")
            self.update_nav_buttons()
            return
        try:
            pil_image = Image.open(self.image_path)
            # Konverze na Qt obraz a pixmapu
            if pil_image.mode == 'RGBA':
                qt_image = ImageQt.ImageQt(pil_image)
            else:
                qt_image = ImageQt.ImageQt(pil_image.convert('RGB'))
            self.original_pixmap = QPixmap.fromImage(qt_image)
    
            # Naplánovat 'Přizpůsobit' po načtení
            if self.original_pixmap:
                QTimer.singleShot(0, self.zoom_fit)
                QTimer.singleShot(120, self.zoom_fit)
    
            # Základní informace
            if hasattr(self, "label_filename"):
                # label_filename je QLineEdit (read-only), aby dlouhý název nerozta­hoval panel
                self.label_filename.setText(self.image_path.name)
                try:
                    self.label_filename.setCursorPosition(0)
                except Exception:
                    pass
            self.label_dimensions.setText(f"{pil_image.width} × {pil_image.height} px")
            file_size = self.image_path.stat().st_size
            if file_size > 1024 * 1024:
                size_str = f"{file_size / (1024 * 1024):.2f} MB"
            elif file_size > 1024:
                size_str = f"{file_size / 1024:.2f} KB"
            else:
                size_str = f"{file_size} B"
            self.label_filesize.setText(size_str)
    
            # Metadata
            self.load_metadata(pil_image)
        except Exception as e:
            self.image_label.setText(f"❌ Chyba při načítání: {str(e)}")
        finally:
            self.update_nav_buttons()


            
    def format_czech_coords(self, lat: float, lon: float, decimals: int = 5) -> str:
        """
        Vrátí text ve tvaru '49.23091° S, 17.65690° V'.
        S/J určují znaménko šířky (S = +, J = −), V/Z určují znaménko délky (V = +, Z = −).
        """
        lat_dir = 'J' if lat < 0 else 'S'
        lon_dir = 'Z' if lon < 0 else 'V'
        return f"{abs(lat):.{decimals}f}° {lat_dir}, {abs(lon):.{decimals}f}° {lon_dir}"

            
    def load_metadata(self, pil_image):
        """Načtení a zobrazení metadat"""
        metadata_info = []
        try:
            lat_float = None
            lon_float = None
    
            # Předvyčištění textu s výstupními parametry
            if hasattr(self, "label_output_params"):
                self.label_output_params.setText("—")
    
            # PNG metadata (text)
            png_metadata = {}
            marker_style = None
            marker_size_px = None
            if hasattr(pil_image, 'text'):
                for key, value in pil_image.text.items():
                    png_metadata[key] = value
                    # GPS informace
                    if key == "GPS_Latitude":
                        try:
                            lat = float(value)
                            lat_float = lat
                            lat_dir = 'J' if lat < 0 else 'S'
                            self.label_gps_lat.setText(f"{abs(lat):.6f}° {lat_dir}")
                        except Exception:
                            self.label_gps_lat.setText(value)
                    elif key == "GPS_Longitude":
                        try:
                            lon = float(value)
                            lon_float = lon
                            lon_dir = 'Z' if lon < 0 else 'V'
                            self.label_gps_lon.setText(f"{abs(lon):.6f}° {lon_dir}")
                        except Exception:
                            self.label_gps_lon.setText(value)
                    elif key == "GPS_Source":
                        source_text = "Ze souboru fotky" if value == "F" else "Ruční zadání"
                        self.label_gps_source.setText(source_text)
                    elif key == "Marker_Style":
                        marker_style = str(value).strip()
                    elif key == "Marker_Size_Px":
                        try:
                            marker_size_px = int(str(value).strip())
                        except Exception:
                            marker_size_px = None
    
            # NOVÉ: pokud PNG metadata neobsahují GPS, zkus odvodit z názvu souboru (CZ i EN směry)
            if (lat_float is None) or (lon_float is None):
                try:
                    import re
                    name = self.image_path.stem
                    # „GPS“ je volitelné, oddělovače: + / _ / mezera / čárka / pomlčka / středník
                    pattern = r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])'
                    m = re.search(pattern, name, re.IGNORECASE)
                    if m:
                        lat_val = float(m.group(1).replace(',', '.'))
                        lat_dir = m.group(2).upper()
                        lon_val = float(m.group(3).replace(',', '.'))
                        lon_dir = m.group(4).upper()
                        # Rozhodnutí o EN vs CZ režimu
                        dirs = {lat_dir, lon_dir}
                        english_mode = any(d in {'N', 'E', 'W'} for d in dirs)
                        if english_mode:
                            # EN: N(+), S(-); E(+), W(-)
                            lat_float = -lat_val if lat_dir == 'S' else lat_val
                            lon_float = -lon_val if lon_dir == 'W' else lon_val
                            self.label_gps_source.setText("Název souboru (EN)")
                        else:
                            # CZ: S(+), J(-); V(+), Z(-)
                            lat_float = -lat_val if lat_dir == 'J' else lat_val
                            lon_float = -lon_val if lon_dir == 'Z' else lon_val
                            self.label_gps_source.setText("Název souboru (CZ)")
                        # Aktualizace jednotlivých labelů
                        lat_dir_cz = 'J' if lat_float < 0 else 'S'
                        lon_dir_cz = 'Z' if lon_float < 0 else 'V'
                        self.label_gps_lat.setText(f"{abs(lat_float):.6f}° {lat_dir_cz}")
                        self.label_gps_lon.setText(f"{abs(lon_float):.6f}° {lon_dir_cz}")
                except Exception:
                    pass
    
            # NOVÉ: pokud máme lat/lon (z PNG nebo z názvu), nastav i QLineEdit „GPS souřadnice:“
            if (lat_float is not None) and (lon_float is not None) and hasattr(self, "edit_gps_combined"):
                self.edit_gps_combined.setText(self.format_czech_coords(lat_float, lon_float, decimals=5))
                self.edit_gps_combined.setCursorPosition(0)
    
            # Stručné výstupní parametry (cm/DPI) z PNG metadat + NOVĚ marker
            try:
                w_cm = png_metadata.get("Output_Width_cm")
                h_cm = png_metadata.get("Output_Height_cm")
                out_dpi = png_metadata.get("Output_DPI")
                if w_cm and h_cm and out_dpi and hasattr(self, "label_output_params"):
                    marker_tail = ""
                    if marker_style or marker_size_px:
                        ms_txt = marker_style if marker_style else "—"
                        mz_txt = f"{marker_size_px}px" if marker_size_px else "—"
                        marker_tail = f" • Značka: {ms_txt}, {mz_txt}"
                    self.label_output_params.setText(f"{w_cm} × {h_cm} cm @ {out_dpi} DPI{marker_tail}")
            except Exception:
                pass
    
            if png_metadata:
                metadata_info.append("=== PNG Metadata ===")
                for key, value in png_metadata.items():
                    metadata_info.append(f"{key}: {value}")
                metadata_info.append("")
    
            # EXIF data (pokud existují)
            if hasattr(pil_image, '_getexif') and pil_image._getexif():
                from PIL.ExifTags import TAGS
                exif_data = pil_image._getexif()
                metadata_info.append("=== EXIF Data ===")
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    metadata_info.append(f"{tag}: {value}")
                metadata_info.append("")
    
            # Informace o obrázku
            metadata_info.append("=== Informace o obrázku ===")
            metadata_info.append(f"Formát: {pil_image.format}")
            metadata_info.append(f"Režim: {pil_image.mode}")
            if hasattr(pil_image, 'info'):
                for key, value in pil_image.info.items():
                    if key not in ['dpi', 'transparency']:
                        metadata_info.append(f"{key}: {value}")
    
            # Zobrazení v textovém poli
            self.metadata_text.setPlainText("\n".join(metadata_info))
        except Exception as e:
            self.metadata_text.setPlainText(f"Chyba při načítání metadat: {str(e)}")

    def request_auto_fit(self):
        """Vyžádá jednorázový auto-fit po zobrazení dialogu."""
        self._auto_fit_requested = True
    

    def zoom_in(self):
        """Přiblížení"""
        self.fit_mode = False
        self.current_scale *= 1.25
        self.update_image_display()

    def zoom_out(self):
        """Oddálení"""
        self.fit_mode = False
        self.current_scale /= 1.25
        self.update_image_display()

    def zoom_fit(self):
        """Přizpůsobení velikosti"""
        if self.original_pixmap:
            scroll_size = self.scroll_area.viewport().size()  # přesnější než .size()
            pixmap_size = self.original_pixmap.size()
            # drobná rezerva pro okraje scrollarey
            scale_x = (max(1, scroll_size.width()) - 2) / max(1, pixmap_size.width())
            scale_y = (max(1, scroll_size.height()) - 2) / max(1, pixmap_size.height())
            # nepřibližujeme nad 1.0 (stejně jako dříve)
            self.current_scale = min(scale_x, scale_y, 1.0)
            self.fit_mode = True
            self.update_image_display()


    def zoom_100(self):
        """Skutečná velikost"""
        self.fit_mode = False
        self.current_scale = 1.0
        self.update_image_display()

    def update_image_display(self):
        """Aktualizace zobrazení obrázku + rezervace šířky pro náhled vlevo"""
        if not self.original_pixmap:
            return
        from PySide6.QtCore import QSize
        scaled_pixmap = self.original_pixmap.scaled(
            self.original_pixmap.size() * self.current_scale,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)
        # držet layout v souladu s pixmapou
        self.image_label.setMinimumSize(scaled_pixmap.size())
    
        # „Zarezervovat“ šířku levého panelu, aby info panel vpravo nebbral prostor náhledu
        try:
            if hasattr(self, "image_container"):
                # +2px rezerva proti ořezům/zaokrouhlení
                self.image_container.setMinimumWidth(max(1, scaled_pixmap.width() + 2))
                # volitelně lze i „locknout“ maximum, pak ale okno nepůjde víc rozšířit vlevo:
                # self.image_container.setMaximumWidth(max(1, scaled_pixmap.width() + 2))
        except Exception:
            pass

    def open_folder(self):
        """Otevření složky s obrázkem"""
        import subprocess
        import platform
        
        folder_path = self.image_path.parent
        
        if platform.system() == 'Darwin':  # macOS
            subprocess.Popen(['open', folder_path])
        elif platform.system() == 'Windows':
            subprocess.Popen(['explorer', folder_path])
        else:  # Linux
            subprocess.Popen(['xdg-open', folder_path])

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox, QSpinBox, QMenu

class PolygonCanvas(QWidget):
    """
    Kreslící widget nad bitmapou s interaktivním polygonem s podporou zoomu, přidávání/mazání bodů,
    posunu jednotlivých bodů a posunu celého polygonu myší v rámci hranic obrázku.
    Přidáno: překryvné (cizí) polygony pouze pro vizuální náhled (neukládají se).
    """
    def __init__(self, base_pixmap, points, alpha_percent=15, parent=None, color="#FF0000"):
        super().__init__(parent)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPixmap
        assert isinstance(base_pixmap, QPixmap)
        self._pixmap = base_pixmap
        self.scale = 1.0  # měřítko zobrazení
        self.points = [QPointF(float(x), float(y)) for x, y in (points or [])]
        if len(self.points) < 3:
            self._init_default_triangle()
        self.alpha_percent = max(10, min(20, int(alpha_percent)))
        self.add_mode = False  # True = přidávání bodů
        self.delete_mode = False  # True = mazání bodů
        self.move_mode = False  # True = posun celého polygonu
        self._drag_index = -1
        self._drag_offset = None
        # Stav pro posun celého polygonu
        self._poly_drag_active = False
        self._poly_drag_start = None
        self._poly_points_start = None
        
        self._meters_per_pixel = None
        
        # Barva polygonu (hex)
        self.color_hex = str(color or "#FF0000")
        # NOVĚ: zdroje překryvných polygonů (key -> list[QPointF]) – pouze vizuální
        self._overlay_sources = {}  # key: str (např. cesta souboru) -> list[QPointF]
        self.setMouseTracking(True)
        w, h = self._scaled_size()
        self.setFixedSize(int(round(w)), int(round(h)))
        
        self._edge_label_pt = 5

    # ===== ŠTĚTEC: init po prvním zobrazení =====
    def showEvent(self, ev):
        if not hasattr(self, "_brush_inited"):
            self._brush_inited = True
            self._init_brush_state()
        try:
            super().showEvent(ev)
        except Exception:
            pass
    
    def _init_brush_state(self):
        """Výchozí stav pro brush mód – bez zásahu do původních módů."""
        self.brush_mode = False
        if not hasattr(self, "brush_radius"):
            self.brush_radius = 20
        self._paint_mask = None
        try:
            self.removeEventFilter(self)
        except Exception:
            pass
    
    # ===== ŠTĚTEC: veřejné API =====
def set_brush_mode(self, enabled: bool):
    """
    Zap/vyp 'Vymalovat (štětcem)'.
    V brush módu je kreslení NEZÁVISLÉ na původním polygonu (žádné seedování).
        Po zapnutí: skryj body (self.points = []) a začni s čistou maskou.
        """
        from PySide6.QtCore import Qt
    
        enabled = bool(enabled)
        self.brush_mode = enabled
    
        if enabled:
            # vypni ostatní módy (bez mazání jejich stavů)
            setattr(self, 'add_mode', False)
            setattr(self, 'delete_mode', False)
            setattr(self, 'move_mode', False)
    
            # žádné seedování ze starých bodů – start z prázdna
            self.points = []
            self._ensure_paint_mask(init_from_polygon=False)
    
            # Fallback: pokud sem UI neposlalo radius předem, zajisti minimálně default 5 px
            if not hasattr(self, "brush_radius"):
                self.brush_radius = 5
    
            # kurzor – kolečko podle STÁVAJÍCÍHO radiusu (už může být poslán z UI)
            self._update_brush_cursor()
    
            # fokus + event filter
            try:
                self.setFocusPolicy(Qt.StrongFocus)
                self.setFocus()
                self.installEventFilter(self)
            except Exception:
                pass
        else:
            # vypni event filter
            try:
                self.removeEventFilter(self)
            except Exception:
                pass
    
            # kurzor zpět podle módů
            try:
                if getattr(self, 'move_mode', False):
                    self.setCursor(Qt.OpenHandCursor)
                elif getattr(self, 'add_mode', False) or getattr(self, 'delete_mode', False):
                    self.setCursor(Qt.CrossCursor)
                else:
                    self.unsetCursor()
            except Exception:
                pass
    
        self.update()
    
    
    def set_brush_radius(self, px: int):
        """Poloměr štětce (1–512) + aktualizace kurzoru, je-li štětec aktivní."""
        self.brush_radius = int(max(1, min(512, px)))
        if getattr(self, "brush_mode", False):
            self._update_brush_cursor()
        self.update()
    
    
    def clear_paint(self):
        """
        Vymaže tahy štětcem i aktuální body polygonu.
        DŮLEŽITÉ: neseeduje se ze starých bodů → nic „nevyskočí zpět“.
        """
        # zruš body i masku; masku vytvoříme až při dalším tahu
        self.points = []
        self._paint_mask = None
        self.update()
    
    
    def _ensure_paint_mask(self, init_from_polygon: bool = False):
        """
        Inicializuje masku pro malování.
        Defaultně NEseeduje z polygonu (keep False); kdyby bylo True, vyplní masku body polygonu.
        """
        import numpy as np, cv2
        h = int(self._pixmap.height())
        w = int(self._pixmap.width())
        if getattr(self, "_paint_mask", None) is None or self._paint_mask.shape[:2] != (h, w):
            self._paint_mask = np.zeros((h, w), dtype=np.uint8)
    
        if init_from_polygon:
            pts = getattr(self, 'points', None) or []
            if len(pts) >= 3:
                poly = np.array([[int(p.x()), int(p.y())] for p in pts], dtype=np.int32)
                try:
                    cv2.fillPoly(self._paint_mask, [poly], 255)
                except Exception:
                    pass
    
        if not hasattr(self, 'brush_radius'):
            self.brush_radius = 5  # výchozí 5 px (v3.2)
    
    
    def _update_brush_cursor(self):
        """Kruhový kurzor s průměrem dle brush_radius; barva = barva polygonu; hotspot uprostřed."""
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QCursor
            r = int(max(1, getattr(self, "brush_radius", 5)))
            d = 2 * r + 3
            pm = QPixmap(d, d)
            pm.fill(Qt.transparent)
    
            # barva z polygonu; očekává se např. '#RRGGBB'
            poly_color_hex = None
            for attr in ("color", "color_hex", "_color_hex"):
                if hasattr(self, attr):
                    poly_color_hex = getattr(self, attr)
                    break
            qcol = QColor(poly_color_hex) if poly_color_hex else QColor(255, 255, 255)
    
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(qcol)
            pen.setWidth(1)
            pen.setColor(QColor(qcol.red(), qcol.green(), qcol.blue(), 230))
            p.setPen(pen)
            p.drawEllipse(1, 1, d - 2, d - 2)
            p.end()
            self.setCursor(QCursor(pm, r + 1, r + 1))
        except Exception:
            from PySide6.QtCore import Qt
            self.setCursor(Qt.CrossCursor)
    
    # ===== ŠTĚTEC: event filter – bez zásahu do tvých mouse*Event =====
    def eventFilter(self, obj, event):
        try:
            if obj is self and self.brush_mode:
                et = event.type()
                pos_raw = event.position() if hasattr(event, "position") else (event.pos() if hasattr(event, "pos") else None)
    
                if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    if pos_raw is not None:
                        self._last_paint_logical = self._to_logical(pos_raw)
                        self._paint_at(self._last_paint_logical)
                    return True
    
                if et == QEvent.MouseMove and (event.buttons() & Qt.LeftButton):
                    if pos_raw is not None:
                        lp = self._to_logical(pos_raw)
                        if getattr(self, "_last_paint_logical", None) is None:
                            self._paint_at(lp)
                        else:
                            self._paint_line(self._last_paint_logical, lp)
                        self._last_paint_logical = lp
                    return True
    
                if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    self._last_paint_logical = None
                    return True
    
                if et == QEvent.KeyPress:
                    k = event.key()
                    if k in (ord('['), ord('-')):
                        self.set_brush_radius(self.brush_radius - 2); return True
                    if k in (ord(']'), ord('='), ord('+')):
                        self.set_brush_radius(self.brush_radius + 2); return True
                    if k == ord('C'):
                        self.clear_paint(); return True
            return super().eventFilter(obj, event)
        except Exception:
            return False
    
    # ===== ŠTĚTEC: volitelné kontextové menu (pravý klik) =====
    def contextMenuEvent(self, ev):
        try:
            menu = QMenu(self)
            act_on = menu.addAction("Režim: Vymalovat (štětcem)"); act_on.setCheckable(True)
            act_on.setChecked(bool(getattr(self, "brush_mode", False)))
            menu.addSeparator()
            menu.addAction("Štětec -  ([ / -)")
            menu.addAction("Štětec +  (] / = / +)")
            menu.addSeparator()
            menu.addAction("Vymazat tahy (C)")
            a = menu.exec(ev.globalPos())
            if not a: return
            t = a.text()
            if "Režim" in t:
                self.set_brush_mode(not self.brush_mode)
            elif "Štětec -" in t:
                self.set_brush_radius(self.brush_radius - 2)
            elif "Štětec +" in t:
                self.set_brush_radius(self.brush_radius + 2)
            elif "Vymazat tahy" in t:
                self.clear_paint()
        except Exception:
            pass
    
    # ===== ŠTĚTEC: vnitřnosti =====
    
    def _paint_at(self, p: QPointF):
        import cv2
        self._ensure_paint_mask()
        r = int(self.brush_radius)
        x, y = int(round(p.x())), int(round(p.y()))
        cv2.circle(self._paint_mask, (x, y), r, 255, -1, lineType=cv2.LINE_AA)
        self._update_polygon_from_mask()
    
    def _paint_line(self, p0: QPointF, p1: QPointF):
        import cv2
        self._ensure_paint_mask()
        r = int(self.brush_radius)
        x0, y0 = int(round(p0.x())), int(round(p0.y()))
        x1, y1 = int(round(p1.x())), int(round(p1.y()))
        cv2.line(self._paint_mask, (x0, y0), (x1, y1), 255, thickness=max(1, 2 * r), lineType=cv2.LINE_AA)
        self._update_polygon_from_mask()
    
    def _update_polygon_from_mask(self):
        """Najde největší komponentu v masce, zjednoduší a uloží do self.points."""
        import cv2, numpy as np
        try:
            contours, _ = cv2.findContours(self._paint_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return
            cnt = max(contours, key=cv2.contourArea)
            peri = float(cv2.arcLength(cnt, True))
            eps = max(1.5, 0.002 * peri)
            approx = cv2.approxPolyDP(cnt, eps, True)
            self.points = [QPointF(float(x), float(y)) for [[x, y]] in approx]
            self.update()
        except Exception:
            pass
        
    # --- POMOCNÍCI (PŘIDEJ DO TŘÍDY PolygonCanvas) --------------------------------
    
    def _event_pos_to_image_xy(self, ev) -> tuple[float, float]:
        """Převod souřadnic myši z widgetu do obrazových px (zohlední self.scale)."""
        try:
            p = ev.position()  # Qt6
        except Exception:
            p = ev.pos()       # fallback
        sx = float(getattr(self, "scale", 1.0) or 1.0)
        return (p.x() / sx, p.y() / sx)
    
    def _index_at_image_xy(self, x: float, y: float) -> int:
        """
        Vrátí index vrcholu pod kurzorem. Použije aktuální vizuální poloměr bodu
        (self._point_radius_px), takže je kliknutelná CELÁ plocha kruhu.
        """
        pts = getattr(self, "points", None) or []
        # efektivní rádius pro zásah = max(aktuální poloměr bodu, 8 px) + malá tolerance
        r = float(getattr(self, "_point_radius_px", 3))
        hit_r = max(8.0, r) + 1.0
        hit_r2 = hit_r * hit_r
    
        for i, pt in enumerate(pts):
            try:
                px = float(pt.x()) if hasattr(pt, "x") else float(pt[0])
                py = float(pt.y()) if hasattr(pt, "y") else float(pt[1])
                dx = px - x
                dy = py - y
                if dx*dx + dy*dy <= hit_r2:
                    return i
            except Exception:
                continue
        return -1
        
    # ---- přidejte do třídy PolygonCanvas (např. hned za __init__) ----
    def set_edge_label_point_size(self, pt: int) -> None:
        """Nastaví bodovou velikost textu u popisků hran (1–48 pt) a překreslí plátno."""
        try:
            val = int(pt)
        except Exception:
            return
        val = max(1, min(48, val))
        if getattr(self, "_edge_label_pt", None) == val:
            return
        self._edge_label_pt = val
        self.update()
    
    def get_edge_label_point_size(self) -> int:
        """Vrátí aktuální bodovou velikost textu u popisků hran."""
        return int(getattr(self, "_edge_label_pt", 5))


    def _init_default_triangle(self):
        from PySide6.QtCore import QPointF
        W = self._pixmap.width()
        H = self._pixmap.height()
        self.points = [
            QPointF(W * 0.30, H * 0.30),
            QPointF(W * 0.70, H * 0.30),
            QPointF(W * 0.50, H * 0.70),
        ]

    def set_meters_per_pixel(self, mpp: float | None):
        """Nastaví měřítko (metry na pixel) a překreslí plátno."""
        try:
            self._meters_per_pixel = float(mpp) if (mpp is not None and float(mpp) > 0) else None
        except Exception:
            self._meters_per_pixel = None
        self.update()
    
    def set_geo_scale_from_lat_zoom(self, lat_deg: float, zoom: int):
        """Spočítá m/px pro Web Mercator z šířky a zoomu a uloží do plátna."""
        import math
        try:
            R = 6378137.0  # poloměr sférické Země pro Web Mercator (m)
            lat_rad = math.radians(float(lat_deg))
            z = int(zoom)
            mpp = (2.0 * math.pi * R * math.cos(lat_rad)) / (256.0 * (2 ** z))  # m/px
            self.set_meters_per_pixel(mpp)
        except Exception:
            self.set_meters_per_pixel(None)
    
    def _format_length(self, meters: float) -> str:
        """Formát délky s automatickým přepnutím na km nad 1000 m."""
        try:
            m = float(meters)
            return f"{m:.0f} m" if m < 1000.0 else f"{m/1000.0:.2f} km"
        except Exception:
            return "— m"

    # --- Zoom API ---
    def _scaled_size(self):
        return self._pixmap.width() * self.scale, self._pixmap.height() * self.scale

    def set_scale(self, s: float):
        import math
        try:
            val = float(s)
            if math.isnan(val) or math.isinf(val) or val <= 0.0:
                return  # ignoruj neplatné změny
        except Exception:
            return
        val = max(0.05, min(16.0, val))  # mantinely
        if abs(val - self.scale) < 1e-6:
            return
        self.scale = val
        w, h = self._scaled_size()
        self.setFixedSize(int(round(w)), int(round(h)))
        self.update()


    def zoom_in(self, checked: bool = False):
        self.set_scale(self.scale * 1.25)

    def zoom_out(self, checked: bool = False):
        self.set_scale(self.scale / 1.25)

    def zoom_fit(self, viewport_size):
        """
        Přizpůsobení na dostupný prostor – NOVĚ bez limitu 1.0, aby se obraz mohl zvětšit
        a skutečně vyplnil okno (dle požadavku).
        """
        vw = max(1, viewport_size.width() - 2)
        vh = max(1, viewport_size.height() - 2)
        sx = vw / max(1, self._pixmap.width())
        sy = vh / max(1, self._pixmap.height())
        self.set_scale(min(sx, sy))  # odstraněn limit 1.0

    # --- Režimy ---
    def set_alpha_percent(self, value):
        self.alpha_percent = max(10, min(20, int(value)))
        self.update()

    def set_add_mode(self, enabled: bool):
        self.add_mode = bool(enabled)
        if self.add_mode:
            self.delete_mode = False
            self.move_mode = False
        self.setCursor(Qt.CrossCursor if (self.add_mode or self.delete_mode) else (Qt.OpenHandCursor if self.move_mode else Qt.ArrowCursor))

    def set_delete_mode(self, enabled: bool):
        self.delete_mode = bool(enabled)
        if self.delete_mode:
            self.add_mode = False
            self.move_mode = False
        self.setCursor(Qt.CrossCursor if (self.add_mode or self.delete_mode) else (Qt.OpenHandCursor if self.move_mode else Qt.ArrowCursor))

    def set_move_mode(self, enabled: bool):
        self.move_mode = bool(enabled)
        if self.move_mode:
            self.add_mode = False
            self.delete_mode = False
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def set_color(self, hex_color: str):
        try:
            self.color_hex = str(hex_color).strip() or "#FF0000"
            self.update()
        except Exception:
            pass

    # --- Util ---
    def get_points_tuples(self):
        return [(p.x(), p.y()) for p in self.points]

    def _to_logical(self, p):
        from PySide6.QtCore import QPointF
        return QPointF(p.x() / self.scale, p.y() / self.scale)
    
    # --- přidejte do PolygonCanvas ---
    def _signed_area(self) -> float:
        """Podepsaná plocha polygonu (shoelace), >0 pro CCW, <0 pro CW."""
        area = 0.0
        n = len(self.points)
        for i in range(n):
            a = self.points[i]
            b = self.points[(i + 1) % n]
            area += a.x() * b.y() - b.x() * a.y()
        return 0.5 * area

    def paintEvent(self, event):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF
    
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
    
            # škálování plátna (pokud vaše třída používá self.scale)
            canvas_scale = getattr(self, "scale", 1.0)
            if isinstance(canvas_scale, (int, float)) and canvas_scale != 1.0:
                painter.scale(float(canvas_scale), float(canvas_scale))
    
            # podkladový rastr/obrázek
            pixmap = getattr(self, "_pixmap", None)
            if pixmap is not None:
                painter.drawPixmap(0, 0, pixmap)
    
            # 1) překryvné (cizí) polygony – kreslíme jemně, pokud existují
            overlay_sources = getattr(self, "_overlay_sources", None)
            if isinstance(overlay_sources, dict) and overlay_sources:
                ov_fill = QColor(120, 120, 120, int(255 * 0.15))
                ov_edge = QColor(120, 120, 120, 200)
                painter.setBrush(QBrush(ov_fill))
                painter.setPen(QPen(ov_edge, 2))
                for pts in overlay_sources.values():
                    try:
                        if pts and len(pts) >= 3:
                            painter.drawPolygon(QPolygonF(pts))
                    except Exception:
                        continue
    
            # 2) náš editovaný polygon
            points = getattr(self, "points", []) or []
            if len(points) >= 1:
                # barva + průhlednost výplně
                color_hex = getattr(self, "color_hex", "#ff0000")
                try:
                    col = QColor(color_hex)
                    if not col.isValid():
                        col = QColor(255, 0, 0)
                except Exception:
                    col = QColor(255, 0, 0)
    
                alpha_percent = float(getattr(self, "alpha_percent", 30.0))
                alpha = int(max(0, min(100, alpha_percent)) / 100.0 * 255)
    
                # tloušťka hrany a velikost bodů (ABSOLUTNĚ v px)
                edge_w = int(getattr(self, "_edge_width_px", 2))
                pt_r   = int(getattr(self, "_point_radius_px", 3))
                edge_w = max(1, min(100, edge_w))
                pt_r   = max(2, min(200, pt_r))
    
                # výplň polygonu (až od 3 bodů)
                if len(points) >= 3:
                    painter.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), alpha)))
                    painter.setPen(Qt.NoPen)
                    painter.drawPolygon(QPolygonF(points))
    
                # hrany
                painter.setPen(QPen(col, edge_w))
                for i in range(len(points) - 1):
                    painter.drawLine(points[i], points[i + 1])
                # pokud chcete uzavřený polygon i při >=3 bodech
                if len(points) >= 3:
                    painter.drawLine(points[-1], points[0])
    
                # popisky délek hran
                from PySide6.QtGui import QFont, QFontMetrics
                try:
                    mpp = float(getattr(self, "_meters_per_pixel", None) or 0.0)
                except Exception:
                    mpp = 0.0
                # Nastavení fontu podle bodové velikosti
                try:
                    pt_size = int(getattr(self, "_edge_label_pt", 5))
                except Exception:
                    pt_size = 5
                pt_size = max(1, min(48, pt_size))
                font = QFont()
                font.setPointSize(pt_size)
                painter.setFont(font)
                fm = QFontMetrics(font)
    
                def _draw_edge_label(p1, p2, txt):
                    # střed hrany
                    cx = (p1.x() + p2.x()) * 0.5
                    cy = (p1.y() + p2.y()) * 0.5
                    tw = fm.horizontalAdvance(txt) + 6
                    th = fm.height() + 2
                    rx = int(cx - tw / 2)
                    ry = int(cy - th / 2)
                    from PySide6.QtCore import QRect
                    bg = QColor(255, 255, 255, 220)
                    fg = QColor(0, 0, 0)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(bg))
                    painter.drawRect(QRect(rx, ry, int(tw), int(th)))
                    painter.setPen(QPen(fg, 1))
                    painter.drawText(QRect(rx, ry, int(tw), int(th)), Qt.AlignCenter, txt)
    
                if len(points) >= 2:
                    # mezivrcholy
                    for i in range(len(points) - 1):
                        dx = points[i+1].x() - points[i].x()
                        dy = points[i+1].y() - points[i].y()
                        px_len = (dx*dx + dy*dy) ** 0.5
                        if mpp > 0.0:
                            txt = self._format_length(px_len * mpp)
                        else:
                            txt = f"{px_len:.0f} px"
                        _draw_edge_label(points[i], points[i+1], txt)
                    # uzavírací hrana
                    if len(points) >= 3:
                        dx = points[0].x() - points[-1].x()
                        dy = points[0].y() - points[-1].y()
                        px_len = (dx*dx + dy*dy) ** 0.5
                        if mpp > 0.0:
                            txt = self._format_length(px_len * mpp)
                        else:
                            txt = f"{px_len:.0f} px"
                        _draw_edge_label(points[-1], points[0], txt)
    
                # body (úchopy)
                painter.setBrush(QBrush(col))
                painter.setPen(QPen(col, max(1, edge_w // 2)))
                for p in points:
                    painter.drawEllipse(p, pt_r, pt_r)
        finally:
            # Kritické: vždy ukončit malování, i když něco selže
            painter.end()
    
    def set_point_radius_px(self, px: int) -> None:
        """Absolutní poloměr bodů/úchopů polygonu v pixelech (např. 30 pro HEIC)."""
        try:
            v = int(px)
        except Exception:
            return
        v = max(2, min(200, v))
        self._point_radius_px = v
        try:
            self.update()
        except Exception:
            pass

    # Soubor: image_viewer.py
    # Třída: PolygonCanvas
    # FUNKCE (nahraďte celou existující): mousePressEvent
    
    def mousePressEvent(self, event):
        from PySide6.QtCore import QPointF, Qt
    
        if event.button() == Qt.LeftButton:
            # Pozice kliknutí → logické px (bez zoomu)
            pos_raw = event.position() if hasattr(event, 'position') else event.pos()
            # některé verze Qt vrací QPoint a ne QPointF – sjednotíme
            try:
                pos = self._to_logical(pos_raw)
            except Exception:
                pos = QPointF(float(pos_raw.x()), float(pos_raw.y()))
    
            # Použij větší „zásahový“ rádius, pokud je k dispozici; jinak původních 8 px.
            handle_r = int(getattr(self, "_handle_radius", 8))
    
            # Režim posunu celého polygonu
            if getattr(self, "move_mode", False):
                # Začátek posunu polygonu (ulož výchozí body a místo)
                self._poly_drag_active = True
                self._poly_drag_start = pos
                self._poly_points_start = [QPointF(p.x(), p.y()) for p in self.points]
                try:
                    self.setCursor(Qt.ClosedHandCursor)
                except Exception:
                    pass
                return  # důležité: nepokračovat na super()
    
            # Režim mazání bodu
            if getattr(self, "delete_mode", False):
                idx = self._hit_point(pos, radius=handle_r)
                if idx >= 0:
                    del self.points[idx]
                    self.update()
                return  # důležité: nepokračovat na super()
    
            # Režim přidání bodu
            if getattr(self, "add_mode", False):
                idx = self._find_best_insert_index(pos)
                self.points.insert(idx, pos)
                self.update()
                return  # důležité: nepokračovat na super()
    
            # Běžný režim: případné tažení existujícího bodu
            idx = self._hit_point(pos, radius=handle_r)
            if idx >= 0:
                self._drag_index = idx
                self._drag_offset = self.points[idx] - pos
                return  # důležité: nepokračovat na super()
    
        # Mimo naše scénáře ponecháme původní chování
        super().mousePressEvent(event)
    
    # Soubor: image_viewer.py
    # Třída: PolygonCanvas
    # FUNKCE (přidejte/nahraďte): mouseMoveEvent
    
    def mouseMoveEvent(self, event):
        from PySide6.QtCore import QPointF, Qt
    
        if event.buttons() & Qt.LeftButton:
            # Pozice → logické px
            pos_raw = event.position() if hasattr(event, 'position') else event.pos()
            try:
                pos = self._to_logical(pos_raw)
            except Exception:
                pos = QPointF(float(pos_raw.x()), float(pos_raw.y()))
    
            # 1) Táhneme jednotlivý bod?
            if getattr(self, "_drag_index", None) is not None:
                i = self._drag_index
                try:
                    new_pos = pos + self._drag_offset  # drží relativní offset od prvního stisku
                except Exception:
                    # fallback, kdyby _drag_offset nebyl QPointF
                    new_pos = QPointF(pos.x(), pos.y())
                    try:
                        new_pos.setX(pos.x() + float(self._drag_offset.x()))
                        new_pos.setY(pos.y() + float(self._drag_offset.y()))
                    except Exception:
                        pass
    
                try:
                    if hasattr(self.points[i], "setX"):
                        self.points[i].setX(new_pos.x())
                        self.points[i].setY(new_pos.y())
                    else:
                        self.points[i] = QPointF(new_pos.x(), new_pos.y())
                except Exception:
                    self.points[i] = QPointF(new_pos.x(), new_pos.y())
    
                self.update()
                event.accept()
                return
    
            # 2) Posouváme celý polygon?
            if getattr(self, "_poly_drag_active", False):
                try:
                    dx = pos.x() - self._poly_drag_start.x()
                    dy = pos.y() - self._poly_drag_start.y()
                except Exception:
                    dx = dy = 0.0
    
                if isinstance(getattr(self, "_poly_points_start", None), list) and self._poly_points_start:
                    for i, p0 in enumerate(self._poly_points_start):
                        nx = p0.x() + dx
                        ny = p0.y() + dy
                        try:
                            if hasattr(self.points[i], "setX"):
                                self.points[i].setX(nx)
                                self.points[i].setY(ny)
                            else:
                                self.points[i] = QPointF(nx, ny)
                        except Exception:
                            self.points[i] = QPointF(nx, ny)
    
                    self.update()
                    event.accept()
                    return
    
        # Jinak ponech původní chování (zoom, hover, atd.)
        super().mouseMoveEvent(event)
    
    # Soubor: image_viewer.py
    # Třída: PolygonCanvas
    # FUNKCE (přidejte/nahraďte): mouseReleaseEvent
    
    def mouseReleaseEvent(self, event):
        from PySide6.QtCore import Qt
    
        if event.button() == Qt.LeftButton:
            # Ukončení dragu bodu
            if getattr(self, "_drag_index", None) is not None:
                self._drag_index = None
                self._drag_offset = None
                self.update()
                event.accept()
                return
    
            # Ukončení posunu celého polygonu
            if getattr(self, "_poly_drag_active", False):
                self._poly_drag_active = False
                self._poly_points_start = None
                self._poly_drag_start = None
                try:
                    self.unsetCursor()
                except Exception:
                    pass
                self.update()
                event.accept()
                return
    
        # Ostatní necháme na původní logice
        super().mouseReleaseEvent(event)

    def _hit_point(self, pos, radius=8):
        r2 = radius * radius
        for i, p in enumerate(self.points):
            dx = p.x() - pos.x()
            dy = p.y() - pos.y()
            if (dx * dx + dy * dy) <= r2:
                return i
        return -1

    def _find_best_insert_index(self, pos):
        if len(self.points) < 2:
            return len(self.points)
        best_i = 0
        best_d = float('inf')
        for i in range(len(self.points)):
            a = self.points[i]
            b = self.points[(i + 1) % len(self.points)]
            d = self._point_to_segment_dist(pos, a, b)
            if d < best_d:
                best_d = d
                best_i = i + 1
        return best_i

    @staticmethod
    def _point_to_segment_dist(p, a, b):
        ax, ay = a.x(), a.y()
        bx, by = b.x(), b.y()
        px, py = p.x(), p.y()
        abx, aby = bx - ax, by - ay
        ab2 = abx * abx + aby * aby
        if ab2 == 0:
            import math
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * abx + (py - ay) * aby) / ab2
        t = max(0.0, min(1.0, t))
        cx, cy = ax + t * abx, ay + t * aby
        import math
        return math.hypot(px - cx, py - cy)

    # --- NOVÉ: API pro překryvné polygony (neukládají se) ---
    def set_overlay_sources(self, src_map: dict) -> None:
        """Nahradí všechny překryvné zdroje; hodnoty jsou seznamy (x,y) v pixelech."""
        from PySide6.QtCore import QPointF
        new_map = {}
        for key, pts in (src_map or {}).items():
            try:
                new_map[str(key)] = [QPointF(float(x), float(y)) for x, y in (pts or [])]
            except Exception:
                continue
        self._overlay_sources = new_map
        self.update()

    def add_overlay_source(self, key: str, points) -> None:
        """Přidá/aktualizuje jeden překryvný polygon."""
        from PySide6.QtCore import QPointF
        try:
            self._overlay_sources[str(key)] = [QPointF(float(x), float(y)) for x, y in (points or [])]
            self.update()
        except Exception:
            pass

    def remove_overlay_source(self, key: str) -> None:
        """Odebere jeden překryvný polygon podle klíče."""
        try:
            self._overlay_sources.pop(str(key), None)
            self.update()
        except Exception:
            pass

    def clear_overlay_sources(self) -> None:
        """Vyčistí všechny překryvné polygony."""
        self._overlay_sources.clear()
        self.update()

class PolygonEditorDialog(QDialog):
    """
    Editor oblasti nad PNG: zoom, přidávání/mazání bodů, posun polygonu, volba barvy, uložení do AOI_POLYGON.
    Reorganizace: logické skupiny ovladačů, jednotný styl tlačítek, širší pravý panel a 'Odznačit vše'.
    Překryvné polygony: checkboxy map ze složky 'Neroztříděné' s uloženým AOI_POLYGON (pouze náhled).
    """
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
    
        from pathlib import Path
        from PySide6.QtWidgets import (
            QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
            QGroupBox, QGridLayout, QSpinBox, QCheckBox, QWidget, QFrame,
            QColorDialog, QMessageBox
        )
        from PySide6.QtGui import QPixmap, QGuiApplication, QShortcut, QKeySequence
        from PySide6.QtCore import QTimer, Qt, QPointF
        from PIL import Image, ImageQt
    
        self.image_path = Path(image_path)
        self.setWindowTitle(f"Editor oblasti – {self.image_path.name}")
    
        # Paleta stylů tlačítek
        self._BTN = {
            "PRIMARY": ("#1565C0", "#1976D2", "#0D47A1"),
            "SUCCESS": ("#2e7d32", "#388e3c", "#1b5e20"),
            "DANGER":  ("#e53935", "#d32f2f", "#b71c1c"),
            "MUTED":   ("#616161", "#757575", "#424242"),
            "ACCENT":  ("#00897B", "#009688", "#00695C"),
        }
    
        def style_btn(btn: QPushButton, key: str, min_h: int = 32, max_w: int | None = None):
            base, hover, pressed = self._BTN[key]
            btn.setMinimumHeight(min_h)
            if max_w:
                btn.setMaximumWidth(max_w)
            btn.setStyleSheet(f"""
            QPushButton {{ background-color: {base}; color: white; border: none; border-radius: 6px; font-weight: 600; padding: 6px 12px; font-size: 12px; }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{ background-color: #9e9e9e; color: #e0e0e0; }}
            """)
    
        self.setMinimumSize(1500, 1050)
    
        # Načtení základního obrázku a polygon metadat (pokud jsou)
        with Image.open(self.image_path) as im:
            self._base_pixmap = QPixmap.fromImage(ImageQt.ImageQt(im.convert('RGBA')))
            poly_meta = read_polygon_metadata(self.image_path)
            if poly_meta:
                pts = poly_meta['points']
                alpha = int(round(100.0 * float(poly_meta.get('alpha', 0.15))))
                color_hex = str(poly_meta.get('color', '#FF0000'))
            else:
                pts, alpha, color_hex = [], 15, '#FF0000'
    
        self._current_color_hex = color_hex
    
        # Rozvržení
        root = QVBoxLayout(self)
    
        # Horní řada: plátno vlevo + panel překryvných polygonů vpravo
        top_row = QHBoxLayout()
        root.addLayout(top_row, 1)
    
        # Plátno s polygonem
        self.canvas = PolygonCanvas(self._base_pixmap, pts, alpha_percent=alpha, parent=self, color=color_hex)
    
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.canvas)
        top_row.addWidget(self.scroll, 1)
    
        # Uložit původní styl scroll z důvodu vizuálních indikací
        self._original_scroll_style = self.scroll.styleSheet()
    
        # Panel překryvných polygonů
        self.overlay_panel = QGroupBox("Překryvné polygony", self)
        ovl_layout = QVBoxLayout(self.overlay_panel)
    
        self.btn_deselect_all = QPushButton("Odznačit vše", self.overlay_panel)
        style_btn(self.btn_deselect_all, "ACCENT")
        self.btn_deselect_all.clicked.connect(self._on_deselect_all_overlays)
        ovl_layout.addWidget(self.btn_deselect_all, 0)
    
        self.overlay_scroll = QScrollArea(self.overlay_panel)
        self.overlay_scroll.setWidgetResizable(True)
        self.overlay_scroll.setAlignment(Qt.AlignTop)
    
        self.overlay_container = QWidget(self.overlay_scroll)
        self.overlay_vbox = QVBoxLayout(self.overlay_container)
        self.overlay_vbox.setContentsMargins(4, 4, 4, 4)
        self.overlay_vbox.setSpacing(6)
        self.overlay_scroll.setWidget(self.overlay_container)
        ovl_layout.addWidget(self.overlay_scroll, 1)
    
        self._overlay_points_by_path = {}
        self._overlay_checkbox_bindings = {}
        self._load_overlay_list()
    
        screen_width = QGuiApplication.primaryScreen().availableGeometry().width()
        panel_width = int(screen_width * 0.55) # 55% šířky obrazovky
        self.overlay_panel.setFixedWidth(panel_width)
        top_row.addWidget(self.overlay_panel, 0)
    
        # Oddělovač
        sep = QFrame(self)
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)
    
        # Ovládací lišta
        controls_bar = QHBoxLayout()
        root.addLayout(controls_bar, 0)
    
        # Režimy
        modes_group = QGroupBox("Režimy", self)
        modes_gl = QGridLayout(modes_group)
    
        self.chk_add_mode = QCheckBox('Přidat bod', modes_group)
        self.chk_del_mode = QCheckBox('Mazat bod', modes_group)
        self.chk_move_mode = QCheckBox('Posun polygonu', modes_group)
    
        self.chk_add_mode.toggled.connect(self._on_add_mode_toggled)
        self.chk_del_mode.toggled.connect(self._on_delete_mode_toggled)
        self.chk_move_mode.toggled.connect(self._on_move_mode_toggled)
    
        modes_gl.addWidget(self.chk_add_mode, 0, 0)
        modes_gl.addWidget(self.chk_del_mode, 0, 1)
        modes_gl.addWidget(self.chk_move_mode, 0, 2)
        controls_bar.addWidget(modes_group, 0)
        
        #self.__ensure_brush_panel()
        self._inject_brush_controls(modes_gl, controls_bar)
    
        # Zoom
        zoom_group = QGroupBox("Zoom", self)
        zoom_hl = QHBoxLayout(zoom_group)
    
        self.btn_zoom_in  = QPushButton('🔍+', zoom_group)
        self.btn_zoom_out = QPushButton('🔍-', zoom_group)
        self.btn_zoom_fit = QPushButton('📐 Fit', zoom_group)
        self.btn_zoom_100 = QPushButton('1:1', zoom_group)
    
        for b in (self.btn_zoom_in, self.btn_zoom_out, self.btn_zoom_fit, self.btn_zoom_100):
            style_btn(b, "PRIMARY")
    
        self.btn_zoom_in.clicked.connect(self.canvas.zoom_in)
        self.btn_zoom_out.clicked.connect(self.canvas.zoom_out)
        self.btn_zoom_fit.clicked.connect(self._on_zoom_fit)
        self.btn_zoom_100.clicked.connect(lambda: self.canvas.set_scale(1.0))
    
        zoom_hl.addWidget(self.btn_zoom_in)
        zoom_hl.addWidget(self.btn_zoom_out)
        zoom_hl.addWidget(self.btn_zoom_fit)
        zoom_hl.addWidget(self.btn_zoom_100)
        controls_bar.addWidget(zoom_group, 0)
    
        # Styl polygonu
        style_group = QGroupBox("Styl", self)
        style_gl = QGridLayout(style_group)
        self.spin_alpha = QSpinBox(style_group)
        self.spin_alpha.setRange(10, 20)
        self.spin_alpha.setSingleStep(1)
        self.spin_alpha.setValue(alpha)
        self.spin_alpha.valueChanged.connect(self._on_alpha_changed)
        self.btn_color = QPushButton('Barva…', style_group)
        style_btn(self.btn_color, "MUTED")
        self.btn_color.clicked.connect(self._on_pick_color)
        self.lbl_color_sample = QLabel(' ', style_group)
        self.lbl_color_sample.setMinimumWidth(36)
        self.lbl_color_sample.setStyleSheet(f'background-color: {color_hex}; border: 1px solid #888; border-radius: 4px;')
        style_gl.addWidget(QLabel('Průhlednost (%)', style_group), 0, 0)
        style_gl.addWidget(self.spin_alpha, 0, 1)
        style_gl.addWidget(self.btn_color, 0, 2)
        style_gl.addWidget(self.lbl_color_sample, 0, 3)
        controls_bar.addWidget(style_group, 0)
        
        # >>> NOVÉ: Popisky hran – velikost textu v bodech (1–48 pt)
        edge_labels_group = QGroupBox("Popisky hran", self)
        edge_gl = QGridLayout(edge_labels_group)
        
        lbl_edge_pt = QLabel("Velikost (pt):", edge_labels_group)
        self.spin_edge_label_pt = QSpinBox(edge_labels_group)
        self.spin_edge_label_pt.setRange(1, 48)
        
        # Inicializace ze stávající hodnoty plátna (výchozí 5 pt), aby odpovídalo náhledu
        try:
            current_pt = self.canvas.get_edge_label_point_size()
        except Exception:
            current_pt = 5
        self.spin_edge_label_pt.setValue(current_pt)
        
        # Změna velikosti → okamžitě překreslit popisky u hran
        self.spin_edge_label_pt.valueChanged.connect(
            lambda v: (self.canvas.set_edge_label_point_size(v), self.canvas.update())
        )
        
        edge_gl.addWidget(lbl_edge_pt, 0, 0)
        edge_gl.addWidget(self.spin_edge_label_pt, 0, 1)
        
        controls_bar.addWidget(edge_labels_group, 0)
        # <<< KONEC NOVÉHO ÚSEKU
        
        # Akce
        actions_group = QGroupBox("Akce", self)
        act_hl = QHBoxLayout(actions_group)
        self.btn_reset_poly = QPushButton('Resetovat polygon', actions_group)
        self.btn_clear_poly = QPushButton('Vymazat polygon', actions_group)
        style_btn(self.btn_reset_poly, "MUTED")
        style_btn(self.btn_clear_poly, "DANGER")
        self.btn_reset_poly.clicked.connect(self._on_reset_polygon)
        self.btn_clear_poly.clicked.connect(self._on_clear_polygon)
        act_hl.addWidget(self.btn_reset_poly)
        act_hl.addWidget(self.btn_clear_poly)
        controls_bar.addWidget(actions_group, 1)
    
        # Potvrzovací lišta
        confirm_box = QHBoxLayout()
        self.btn_cancel = QPushButton('Zrušit', self)
        self.btn_ok     = QPushButton('Uložit', self)
        style_btn(self.btn_cancel, "MUTED")
        style_btn(self.btn_ok, "SUCCESS")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_save)
        confirm_box.addWidget(self.btn_cancel)
        confirm_box.addWidget(self.btn_ok)
    
        controls_bar.addStretch(1)
        controls_bar.addLayout(confirm_box)
    
        # NOVĚ: Inicializace měřítka (metry na pixel) z názvu souboru (lat/zoom) pro popisky délek hran
        try:
            lat, lon, zoom = self._extract_lat_lon_zoom_from_filename()
            if (lat is not None) and (zoom is not None):
                # ground resolution (m/px) ~ 156543.04 * cos(lat) / 2^zoom (Web Mercator)
                self.canvas.set_geo_scale_from_lat_zoom(lat, zoom)
            else:
                self.canvas.set_meters_per_pixel(None)
        except Exception:
            self.canvas.set_meters_per_pixel(None)
    
        # Počáteční velikost okna dle obrazovky a vstupního obrázku
        try:
            screen_geo = QGuiApplication.primaryScreen().availableGeometry()
            target_w = min(screen_geo.width() - 20,
                           max(2200, self._base_pixmap.width() + 160 + self.overlay_panel.minimumWidth()))
            target_h = min(screen_geo.height() - 20,
                           max(1100, self._base_pixmap.height() + 280))
            self.resize(target_w, target_h)
        except Exception:
            self.resize(2100, 1200)
    
        # Po otevření dialogu dvoufázový fit
        QTimer.singleShot(0, self._on_zoom_fit)
        QTimer.singleShot(150, self._on_zoom_fit)
    
        # Klávesové zkratky
        sc_close = QShortcut(QKeySequence.Close, self)
        sc_close.activated.connect(self.reject)
    
        copy_shortcut = QShortcut(QKeySequence.Copy, self)
        copy_shortcut.activated.connect(self.copy_polygon_to_clipboard)
    
        paste_shortcut = QShortcut(QKeySequence.Paste, self)
        paste_shortcut.activated.connect(self.paste_polygon_from_clipboard)
    
        # Smazání polygonu (Cmd/Ctrl+Backspace)
        clear_shortcut = QShortcut(QKeySequence("Ctrl+Backspace"), self)
        clear_shortcut.activated.connect(self._on_clear_polygon)
        
    def _inject_brush_controls(self, modes_gl, controls_bar):
        from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QCheckBox, QSpinBox
        self.chk_brush_mode = QCheckBox('Vymalovat (štětcem)', self)
        self.chk_brush_mode.setChecked(False)
        self.chk_brush_mode.toggled.connect(self._on_brush_mode_toggled)
        modes_gl.addWidget(self.chk_brush_mode, 0, 3)
    
        brush_group = QGroupBox("Štětec", self)
        brush_hl = QHBoxLayout(brush_group)
        lbl = QLabel("Velikost:", brush_group)
        self.spin_brush_radius = QSpinBox(brush_group)
        self.spin_brush_radius.setRange(1, 512)
        try:
            init_val = int(getattr(self.canvas, "brush_radius", 5))
        except Exception:
            init_val = 5
        self.spin_brush_radius.setValue(init_val)
        self.spin_brush_radius.setEnabled(False)
        self.spin_brush_radius.valueChanged.connect(self._on_brush_value_changed)
    
        brush_hl.addWidget(lbl)
        brush_hl.addWidget(self.spin_brush_radius)
        controls_bar.addWidget(brush_group, 0)
    
        # exkluzivita – zapnutí jiného režimu vypne štětec
        self.chk_add_mode.toggled.connect(lambda on: on and self._disable_brush_due_to_other_mode())
        self.chk_del_mode.toggled.connect(lambda on: on and self._disable_brush_due_to_other_mode())
        self.chk_move_mode.toggled.connect(lambda on: on and self._disable_brush_due_to_other_mode())
    
    def _on_brush_mode_toggled(self, checked: bool):
        """Zap/vyp štětec, exkluzivně s ostatními režimy. Při zapnutí nejdřív synchronizuje radius z UI, aby kurzor hned seděl."""
        # Exkluzivita – když zapínám štětec, vypnu ostatní režimy (bez emisí kaskádních signálů)
        if checked:
            try:
                self.chk_add_mode.blockSignals(True); self.chk_del_mode.blockSignals(True); self.chk_move_mode.blockSignals(True)
                self.chk_add_mode.setChecked(False);  self.chk_del_mode.setChecked(False);  self.chk_move_mode.setChecked(False)
            finally:
                self.chk_add_mode.blockSignals(False); self.chk_del_mode.blockSignals(False); self.chk_move_mode.blockSignals(False)
    
            # 1) Nejprve nastav radius z UI do canvase (default 5 px), ať má kurzor správnou velikost od první chvíle
            try:
                if hasattr(self, "spin_brush_radius") and hasattr(self.canvas, "set_brush_radius"):
                    self.canvas.set_brush_radius(int(self.spin_brush_radius.value()))
            except Exception:
                pass
    
            # 2) Teď teprve zapni brush mód (uvnitř si vyrobí kurzor podle aktuálního radius)
            if hasattr(self.canvas, "set_brush_mode"):
                self.canvas.set_brush_mode(True)
    
        else:
            # Vypnutí štětce
            if hasattr(self.canvas, "set_brush_mode"):
                self.canvas.set_brush_mode(False)
    
        # UI: povolit/zakázat spinbox
        if hasattr(self, "spin_brush_radius"):
            self.spin_brush_radius.setEnabled(bool(checked))
    
        # Fokus a překreslení
        try:
            self.canvas.setFocus(); self.canvas.update()
        except Exception:
            pass
    
    def _on_brush_value_changed(self, val: int):
        try:
            if hasattr(self.canvas, "set_brush_radius"):
                self.canvas.set_brush_radius(int(val))
            if getattr(self.canvas, "brush_mode", False) and hasattr(self.canvas, "_update_brush_cursor"):
                self.canvas._update_brush_cursor()
            self.canvas.update()
        except Exception as e:
            print("[PolygonEditorDialog] brush size:", e)
    
    def _disable_brush_due_to_other_mode(self):
        try:
            if hasattr(self, "chk_brush_mode"):
                self.chk_brush_mode.blockSignals(True)
                self.chk_brush_mode.setChecked(False)
                self.chk_brush_mode.blockSignals(False)
            if hasattr(self, "spin_brush_radius"):
                self.spin_brush_radius.setEnabled(False)
            if hasattr(self.canvas, "set_brush_mode"):
                self.canvas.set_brush_mode(False)
            self.canvas.update()
        except Exception as e:
            print("[PolygonEditorDialog] disable brush:", e)

    def __ensure_brush_panel(self):
        """Vloží (nebo obnoví) horní panel s režimy (vč. štětce) a velikostí štětce. Panel je vždy jen jeden."""
        # Odstraň starý, pokud existuje
        old = self.findChild(QWidget, "polygonBrushBar")
        if old is not None:
            try:
                old.setParent(None)
                old.deleteLater()
            except Exception:
                pass
    
        # Vytvoř nový panel
        bar = QWidget(self)
        bar.setObjectName("polygonBrushBar")
        row = QHBoxLayout(bar); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
    
        lbl_mode = QLabel("Režim:", bar)
        cb = QComboBox(bar)
        cb.addItems(["Přidat body", "Mazat body", "Posouvat", "Vymalovat (štětcem)"])
    
        lbl_sz = QLabel("Štětec:", bar)
        sb = QSpinBox(bar); sb.setRange(1, 512)
        # výchozí hodnota z canvasu (nebo 20)
        sb.setValue(int(getattr(self.canvas, "brush_radius", 20)))
        sb.setEnabled(bool(getattr(self.canvas, "brush_mode", False)))
    
        row.addWidget(lbl_mode); row.addWidget(cb)
        row.addSpacing(12)
        row.addWidget(lbl_sz); row.addWidget(sb)
        row.addStretch(1)
    
        # Umísti panel nahoru do hlavního layoutu dialogu
        lay = self.layout()
        if lay is not None:
            try:
                lay.insertWidget(0, bar)
            except Exception:
                lay.addWidget(bar)
        else:
            bar.setParent(self); bar.move(0, 0); bar.show()
    
        # Ulož reference a signály
        self._cb_mode = cb
        self._sb_brush = sb
    
        cb.currentIndexChanged.connect(self._on_mode_combo_changed)
        sb.valueChanged.connect(self._on_brush_value_changed)
    
        # Počáteční sync podle canvasu
        idx = 0
        if bool(getattr(self.canvas, "delete_mode", False)):
            idx = 1
        elif bool(getattr(self.canvas, "move_mode", False)):
            idx = 2
        elif bool(getattr(self.canvas, "brush_mode", False)):
            idx = 3; sb.setEnabled(True)
        cb.setCurrentIndex(idx)
    
    def _on_mode_combo_changed(self, idx: int):
        """Přepínač režimů přes ComboBox – volá veřejné API canvasu. Zajišťuje exkluzivitu režimů."""
        try:
            # Nejprve vypni vše
            if hasattr(self.canvas, "set_add_mode"):    self.canvas.set_add_mode(False)
            if hasattr(self.canvas, "set_delete_mode"): self.canvas.set_delete_mode(False)
            if hasattr(self.canvas, "set_move_mode"):   self.canvas.set_move_mode(False)
            if hasattr(self.canvas, "set_brush_mode"):  self.canvas.set_brush_mode(False)
    
            # Zapni jen vybraný
            if   idx == 0 and hasattr(self.canvas, "set_add_mode"):   self.canvas.set_add_mode(True)
            elif idx == 1 and hasattr(self.canvas, "set_delete_mode"):self.canvas.set_delete_mode(True)
            elif idx == 2 and hasattr(self.canvas, "set_move_mode"):  self.canvas.set_move_mode(True)
            elif idx == 3 and hasattr(self.canvas, "set_brush_mode"): self.canvas.set_brush_mode(True)
    
            # Štětec: povolit/zakázat spinbox
            if hasattr(self, "_sb_brush") and self._sb_brush:
                self._sb_brush.setEnabled(idx == 3)
    
            # Fokus do canvasu a redraw
            try:
                self.canvas.setFocus()
                self.canvas.update()
            except Exception:
                pass
        except Exception as e:
            print("[PolygonEditorDialog] _on_mode_combo_changed:", e)
    

        
    def _on_deselect_all_overlays(self):
        """
        Odznačí všechny checkboxy v překryvných polygonech (ve všech skupinách).
        """
        try:
            # Projít všechny uložené checkboxy a odznačit je
            for checkbox, (path, points) in self._overlay_checkbox_bindings.items():
                if checkbox.isChecked():
                    checkbox.setChecked(False)
            
            # Alternativně - projít všechny widgety v overlay_vbox a najít checkboxy
            from PySide6.QtWidgets import QCheckBox, QGroupBox
            
            def uncheck_in_widget(widget):
                """Rekurzivně projde widget a odznačí všechny checkboxy"""
                if isinstance(widget, QCheckBox):
                    widget.setChecked(False)
                elif hasattr(widget, 'children'):
                    for child in widget.children():
                        uncheck_in_widget(child)
            
            # Projít všechny skupiny v overlay_vbox
            for i in range(self.overlay_vbox.count()):
                item = self.overlay_vbox.itemAt(i)
                if item and item.widget():
                    uncheck_in_widget(item.widget())
                    
        except Exception as e:
            print(f"Chyba při odznačování překryvných polygonů: {e}")

    # ---- v PolygonEditorDialog: vložte k ostatním metodám třídy ----
    def _build_edge_labels_group(self):
        """Skupina pro nastavení velikosti popisků hran (v bodech)."""
        from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel, QSpinBox
        box = QGroupBox("Popisky hran", self)
        gl = QGridLayout(box)
    
        lbl = QLabel("Velikost (pt):", box)
        spin = QSpinBox(box)
        spin.setRange(1, 48)
        # Vyčíst aktuální z plátna, jinak 5
        try:
            current_pt = self.canvas.get_edge_label_point_size()
        except Exception:
            current_pt = 5
        spin.setValue(current_pt)
    
        # Při změně aktualizovat plátno
        def _on_size_changed(val: int):
            try:
                self.canvas.set_edge_label_point_size(val)
            except Exception:
                pass
    
        spin.valueChanged.connect(_on_size_changed)
    
        gl.addWidget(lbl, 0, 0)
        gl.addWidget(spin, 0, 1)
    
        return box

        
    def _extract_lat_lon_zoom_from_filename(self):
        """
        Vrátí (lat, lon, zoom) odvozené z názvu souboru:
        - GPS49.23091S+17.65690V (+ odchylky oddělovačů, CZ/EN směry)
        - +Z18+ pro zoom
        """
        import re
        name = self.image_path.stem
    
        # GPS (CZ/EN směry), „GPS“ je volitelné, oddělovače volnější
        pat_gps = r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])'
        m = re.search(pat_gps, name, re.IGNORECASE)
        lat = lon = None
        if m:
            lat_val = float(m.group(1).replace(',', '.'))
            lat_dir = m.group(2).upper()
            lon_val = float(m.group(3).replace(',', '.'))
            lon_dir = m.group(4).upper()
            # EN režim, pokud je v sadě směrů N/E/W
            english_mode = any(d in {'N', 'E', 'W'} for d in {lat_dir, lon_dir})
            if english_mode:
                lat = -lat_val if lat_dir == 'S' else lat_val
                lon = -lon_val if lon_dir == 'W' else lon_val
            else:
                lat = -lat_val if lat_dir == 'J' else lat_val
                lon = -lon_val if lon_dir == 'Z' else lon_val
    
        # Zoom +Z..+
        zoom = None
        mz = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', name, re.IGNORECASE)
        if mz:
            zoom = max(0, min(22, int(mz.group(1))))  # ochrana rozsahu
    
        return lat, lon, zoom

    def copy_polygon_to_clipboard(self):
        try:
            points = self.canvas.get_points_tuples()
            if not points or len(points) < 3: return
            polygon_data = {"type": "AOI_POLYGON_CLIPBOARD", "points": points}
            QApplication.clipboard().setText(json.dumps(polygon_data))
            
            # Vizuální indikace úspěšného zkopírování
            self.scroll.setStyleSheet("QScrollArea { border: 2px solid #4CAF50; }") # Zelený rámeček
            QTimer.singleShot(1000, self._reset_scroll_style)

        except Exception as e: print(f"Chyba při kopírování polygonu: {e}")

    def paste_polygon_from_clipboard(self):
        try:
            json_data = QApplication.clipboard().text()
            if not json_data: return
            data = json.loads(json_data)
            if data.get("type") == "AOI_POLYGON_CLIPBOARD" and "points" in json_data:
                points = data["points"]
                if isinstance(points, list) and len(points) >= 3:
                    from PySide6.QtCore import QPointF
                    self.canvas.points = [QPointF(float(x), float(y)) for x, y in points]
                    self.canvas.update()
                    
                    # Vizuální indikace úspěšného vložení
                    self.scroll.setStyleSheet("QScrollArea { border: 2px solid #2196F3; }") # Modrý rámeček
                    QTimer.singleShot(1000, self._reset_scroll_style)

        except (json.JSONDecodeError, TypeError, KeyError): pass
        except Exception as e: print(f"Chyba při vkládání polygonu: {e}")

    def _reset_scroll_style(self):
        """Vrátí styl ohraničení plátna do původního stavu."""
        self.scroll.setStyleSheet(self._original_scroll_style)
            
    def _on_alpha_changed(self, val): self.canvas.set_alpha_percent(val)
    def _on_add_mode_toggled(self, on):
        self.canvas.set_add_mode(on)
        if on: self.chk_del_mode.setChecked(False); self.chk_move_mode.setChecked(False)
    def _on_delete_mode_toggled(self, on):
        self.canvas.set_delete_mode(on)
        if on: self.chk_add_mode.setChecked(False); self.chk_move_mode.setChecked(False)
    def _on_move_mode_toggled(self, on):
        self.canvas.set_move_mode(on)
        if on: self.chk_add_mode.setChecked(False); self.chk_del_mode.setChecked(False)
    def _on_pick_color(self):
        from PySide6.QtWidgets import QColorDialog
        col = QColorDialog.getColor(options=QColorDialog.DontUseNativeDialog)
        if col.isValid():
            hexc = col.name(); self._current_color_hex = hexc
            self.lbl_color_sample.setStyleSheet(f'background-color: {hexc}; border: 1px solid #888; border-radius: 4px;')
            self.canvas.set_color(hexc)
            
    def _on_overlay_toggled(self, on: bool, path: str, pts) -> None:
        """
        Zapnutí/vypnutí překryvných (okolních) polygonů.
        Přesný převod:
            pixel(zdroj, relativně k centru zdrojové mapy) -> (lon, lat) (WGS84) -> pixel(cílová mapa)
        Využívá Web Mercator (stejnou logiku jako OSM tiles): deg2num/num2deg, TILE_SIZE=256.
        Pokud chybí zásadní údaje (lat/lon/zoom nebo dimenze obrázku), polygon se vloží bez transformace.
    
        Parametry:
            on   : bool  - zobrazit/skrýt polygon
            path : str   - cesta ke zdrojové mapě, z níž pochází polygon (určuje její střed a zoom)
            pts  : list  - body polygonu ve zdrojových PIXEL souřadnicích (relativně k levému hornímu rohu zdrojové mapy)
        """
        try:
            # --- skrýt ---
            if not on:
                if hasattr(self, "canvas") and hasattr(self.canvas, "remove_overlay_source"):
                    self.canvas.remove_overlay_source(path)
                return
    
            # --- Pomocné lokální funkce (uvnitř metody, nic globálně nepřidáváme) ---
            def _coerce_xy(p):
                # tuple/list nebo QPointF
                try:
                    return float(p[0]), float(p[1])
                except Exception:
                    try:
                        return float(p.x()), float(p.y())
                    except Exception:
                        return None
    
            # Parsování lat/lon/zoom ze jména souboru "…GPS49.23091S+17.65690V…+Z18+…"
            def _parse_lat_lon_zoom_from_name(name: str):
                import re
                lat = lon = zoom = None
                # GPS (CZ/EN směry), „GPS“ je volitelné, oddělovače volnější
                pat_gps = r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])'
                m = re.search(pat_gps, name, re.IGNORECASE)
                if m:
                    lat_val = float(m.group(1).replace(',', '.'))
                    lat_dir = m.group(2).upper()
                    lon_val = float(m.group(3).replace(',', '.'))
                    lon_dir = m.group(4).upper()
                    english_mode = any(d in {'N', 'E', 'W'} for d in {lat_dir, lon_dir})
                    if english_mode:
                        lat = -lat_val if lat_dir == 'S' else lat_val
                        lon = -lon_val if lon_dir == 'W' else lon_val
                    else:
                        lat = -lat_val if lat_dir == 'J' else lat_val
                        lon = -lon_val if lon_dir == 'Z' else lon_val
                # Zoom +Z..+
                mz = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', name, re.IGNORECASE)
                if mz:
                    z = int(mz.group(1))
                    zoom = max(0, min(22, z))
                return lat, lon, zoom
    
            # Web Mercator převody (OSM dlaždice)
            TILE_SIZE = 256.0
    
            def _deg2num(lat_deg: float, lon_deg: float, zoom: int):
                import math
                lat_rad = math.radians(lat_deg)
                n = 2.0 ** zoom
                xtile = (lon_deg + 180.0) / 360.0 * n
                ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
                return xtile, ytile
    
            def _num2deg(xtile: float, ytile: float, zoom: int):
                import math
                n = 2.0 ** zoom
                lon_deg = xtile / n * 360.0 - 180.0
                lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n)))
                lat_deg = math.degrees(lat_rad)
                return lat_deg, lon_deg
    
            # --- Získej parametry cílové (aktuálně otevřené) mapy ---
            tgt_lat, tgt_lon, tgt_zoom = self._extract_lat_lon_zoom_from_filename()
            if tgt_lat is None or tgt_lon is None or tgt_zoom is None:
                # Bez georeference cíle nemá smysl transformovat – vlož bez úprav
                if hasattr(self, "canvas") and hasattr(self.canvas, "add_overlay_source"):
                    self.canvas.add_overlay_source(path, pts or [])
                return
    
            # Rozměry cílového obrázku (pixmapa v canvasu)
            try:
                Wt = float(self.canvas._pixmap.width())
                Ht = float(self.canvas._pixmap.height())
            except Exception:
                # Fallback – neznáme rozměr → vlož bez úprav
                if hasattr(self, "canvas") and hasattr(self.canvas, "add_overlay_source"):
                    self.canvas.add_overlay_source(path, pts or [])
                return
    
            # --- Získej parametry zdrojové mapy ze 'path' ---
            from pathlib import Path as _P
            p = _P(path)
            src_lat = src_lon = src_zoom = None
            try:
                src_lat, src_lon, src_zoom = _parse_lat_lon_zoom_from_name(p.stem)
            except Exception:
                pass
    
            if src_lat is None or src_lon is None or src_zoom is None:
                # Bez georeference zdroje nelze provést GPS převod → vlož bez úprav
                if hasattr(self, "canvas") and hasattr(self.canvas, "add_overlay_source"):
                    self.canvas.add_overlay_source(path, pts or [])
                return
    
            # Rozměry zdrojového obrázku (abychom uměli vzít offset od středu)
            Ws = Hs = None
            try:
                # Použij PIL již používané v modulu
                from PIL import Image as _Image
                with _Image.open(p) as _im:
                    Ws, Hs = float(_im.width), float(_im.height)
            except Exception:
                pass
    
            if not Ws or not Hs:
                # Neznáme rozměr zdroje → vlož bez úprav
                if hasattr(self, "canvas") and hasattr(self.canvas, "add_overlay_source"):
                    self.canvas.add_overlay_source(path, pts or [])
                return
    
            # --- PŘEVOD: pixel(zdroj) -> (lon, lat) ---
            src_center_xt, src_center_yt = _deg2num(src_lat, src_lon, int(src_zoom))
    
            lonlat_points = []
            for pxy in (pts or []):
                xy = _coerce_xy(pxy)
                if xy is None:
                    continue
                x_s, y_s = xy
                # Posun bodu od středu zdrojové mapy vyjádřený v "tile-space"
                xt = src_center_xt + (float(x_s) - Ws * 0.5) / TILE_SIZE
                yt = src_center_yt + (float(y_s) - Hs * 0.5) / TILE_SIZE
                lat_deg, lon_deg = _num2deg(xt, yt, int(src_zoom))
                lonlat_points.append((lon_deg, lat_deg))  # (lon, lat)
    
            # --- PŘEVOD: (lon, lat) -> pixel(cíl) ---
            tgt_center_xt, tgt_center_yt = _deg2num(float(tgt_lat), float(tgt_lon), int(tgt_zoom))
    
            transformed = []
            for lon_deg, lat_deg in lonlat_points:
                # souřadnice bodu v tile-space cílového zoomu
                xt, yt = _deg2num(float(lat_deg), float(lon_deg), int(tgt_zoom))
                # rozdíl od středu v "tile-space" → pixely
                dx_px = (xt - tgt_center_xt) * TILE_SIZE
                dy_px = (yt - tgt_center_yt) * TILE_SIZE
                x_t = (Wt * 0.5) + dx_px
                y_t = (Ht * 0.5) + dy_px
                transformed.append((x_t, y_t))
    
            # --- Přidání/aktualizace překryvu ---
            if hasattr(self, "canvas") and hasattr(self.canvas, "add_overlay_source"):
                self.canvas.add_overlay_source(path, transformed)
    
        except Exception:
            # nechceme rozbít editor; v krajním případě beze změny
            try:
                if hasattr(self, "canvas") and hasattr(self.canvas, "add_overlay_source"):
                    self.canvas.add_overlay_source(path, pts or [])
            except Exception:
                pass
        
    def _on_zoom_fit(self): self.canvas.zoom_fit(self.scroll.viewport().size())
    def _reload_from_metadata(self):
        meta = read_polygon_metadata(self.image_path)
        if meta:
            pts, alpha, hexc = meta.get('points',[]), int(round(100.0*float(meta.get('alpha',0.15)))), str(meta.get('color','#FF0000'))
            from PySide6.QtCore import QPointF
            self.canvas.points = [QPointF(float(x), float(y)) for x, y in pts]
            self.canvas.set_alpha_percent(alpha); self.spin_alpha.setValue(alpha)
            self._current_color_hex = hexc; self.lbl_color_sample.setStyleSheet(f'background-color: {hexc}; border: 1px solid #888; border-radius: 4px;'); self.canvas.set_color(hexc)
            self.canvas.update()
        else: self.canvas.points = []; self.canvas.update()
    def _on_save(self):
        try:
            pts = self.canvas.get_points_tuples()
            alpha = int(self.spin_alpha.value())
            color_hex = getattr(self, '_current_color_hex', '#FF0000')
            if len(pts) >= 3: save_polygon_to_png(self.image_path, pts, alpha_percent=alpha, color=color_hex)
            else: save_without_polygon(self.image_path)
            self.accept()
        except Exception as e: from PySide6.QtWidgets import QMessageBox; QMessageBox.critical(self, 'Chyba při ukládání', f'{e}')

    def _on_reset_polygon(self):
        """
        Reset polygonu.
        - Mimo štětec: zachovej původní chování (pokud máš logiku na 'původní body').
        - Ve štětci: VYNULUJ masku i body (žádné staré tvary se nevrátí).
        """
        try:
            if hasattr(self.canvas, "brush_mode") and self.canvas.brush_mode:
                # režim štětec: prázdno
                self.canvas.points = []
                self.canvas._paint_mask = None
                self.canvas.update()
                return
    
            # původní reset (pokud máš uložené počáteční body):
            if hasattr(self, "_initial_points") and self._initial_points:
                self.canvas.points = list(self._initial_points)
            else:
                # fallback: prázdno
                self.canvas.points = []
            # a vždy zruš i masku, aby nic nevyskočilo zpět
            self.canvas._paint_mask = None
            self.canvas.update()
        except Exception as e:
            print("[PolygonEditorDialog] reset polygon:", e)    

    def _on_clear_polygon(self):
        """Vymazání polygonu – vždy vynuluje body i masku (funguje i ve štětci)."""
        try:
            self.canvas.points = []
            self.canvas._paint_mask = None
            self.canvas.update()
        except Exception as e:
            print("[PolygonEditorDialog] clear polygon:", e)
            
    def _find_unsorted_folder(self, start: Path) -> Path:
        # ... (tato metoda zůstává beze změny)
        try:
            import unicodedata; norm = lambda s: unicodedata.normalize('NFC', s).casefold(); candidates = {norm("Neroztříděné"), norm("Neroztridene")}
            if norm(start.name) in candidates: return start
            for child in start.iterdir():
                if child.is_dir() and norm(child.name) in candidates: return child
            cur = start
            for _ in range(4):
                parent = cur.parent;
                if parent == cur: break
                for child in parent.iterdir():
                    if child.is_dir() and norm(child.name) in candidates: return child
                cur = parent
        except Exception: pass
        return start

    def _load_overlay_list(self) -> None:
        """
        Načte seznam překryvných polygonů a v panelu zobrazí pouze ty,
        které lze podle GPS (WGS84) alespoň částečně vykreslit v rámci
        aktuálně otevřené lokační mapy (částečné zobrazení je akceptováno).
        Sbalování/seznam „checkable group“ je odstraněno – položky jsou vždy viditelné.
        """
        try:
            from PySide6.QtWidgets import QLabel, QCheckBox, QGroupBox, QVBoxLayout, QWidget
            from PySide6.QtCore import Qt
            from pathlib import Path as _P
            from PIL import Image as _Image
    
            # --- styling checkboxů (ponechán z původní verze) ---
            checkbox_style = """
            QCheckBox {
                font-size: 75%;
                padding: 2px;
            }
            QCheckBox::indicator {
                width: 14px; height: 14px;
            }
            """
    
            # --- pomocné funkce jen v rámci této metody ---
            TILE_SIZE = 256.0
    
            def _coerce_xy(p):
                try:
                    return float(p[0]), float(p[1])
                except Exception:
                    try:
                        return float(p.x()), float(p.y())
                    except Exception:
                        return None
    
            def _deg2num(lat_deg: float, lon_deg: float, zoom: int):
                import math
                lat_rad = math.radians(lat_deg)
                n = 2.0 ** zoom
                xtile = (lon_deg + 180.0) / 360.0 * n
                ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
                return xtile, ytile
    
            def _num2deg(xtile: float, ytile: float, zoom: int):
                import math
                n = 2.0 ** zoom
                lon_deg = xtile / n * 360.0 - 180.0
                lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n)))
                lat_deg = math.degrees(lat_rad)
                return lat_deg, lon_deg
    
            def _parse_lat_lon_zoom_from_name(name: str):
                import re
                lat = lon = zoom = None
                pat_gps = r'(?:GPS\s*)?([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])\s*[\+\s_,;:-]?\s*([0-9]+(?:[.,][0-9]+)?)\s*([SJNVEWZ])'
                m = re.search(pat_gps, name, re.IGNORECASE)
                if m:
                    lat_val = float(m.group(1).replace(',', '.'))
                    lat_dir = m.group(2).upper()
                    lon_val = float(m.group(3).replace(',', '.'))
                    lon_dir = m.group(4).upper()
                    english_mode = any(d in {'N','E','W'} for d in {lat_dir, lon_dir})
                    if english_mode:
                        lat = -lat_val if lat_dir == 'S' else lat_val
                        lon = -lon_val if lon_dir == 'W' else lon_val
                    else:
                        lat = -lat_val if lat_dir == 'J' else lat_val
                        lon = -lon_val if lon_dir == 'Z' else lon_val
                mz = re.search(r'(?:^|[+\-_\s])Z(\d{1,2})(?=$|[+\-_\s])', name, re.IGNORECASE)
                if mz:
                    zoom = max(0, min(22, int(mz.group(1))))
                return lat, lon, zoom
    
            def _viewport_geo_bounds():
                # Parametry cílové (aktuální) mapy
                tgt_lat, tgt_lon, tgt_zoom = self._extract_lat_lon_zoom_from_filename()
                if tgt_lat is None or tgt_lon is None or tgt_zoom is None:
                    return None
                try:
                    Wt = float(self.canvas._pixmap.width())
                    Ht = float(self.canvas._pixmap.height())
                except Exception:
                    return None
                cx, cy = _deg2num(float(tgt_lat), float(tgt_lon), int(tgt_zoom))
                half_xtiles = (Wt * 0.5) / TILE_SIZE
                half_ytiles = (Ht * 0.5) / TILE_SIZE
                xmin_t, xmax_t = cx - half_xtiles, cx + half_xtiles
                ymin_t, ymax_t = cy - half_ytiles, cy + half_ytiles
                lat_top, lon_left   = _num2deg(xmin_t, ymin_t, int(tgt_zoom))
                lat_bot, lon_right  = _num2deg(xmax_t, ymax_t, int(tgt_zoom))
                lat_min = min(lat_top, lat_bot); lat_max = max(lat_top, lat_bot)
                lon_min = min(lon_left, lon_right); lon_max = max(lon_left, lon_right)
                return (lat_min, lat_max, lon_min, lon_max, int(tgt_zoom))
    
            def _polygon_intersects_view(path: _P, pts, bounds):
                if not bounds:
                    return True
                lat_min, lat_max, lon_min, lon_max, _tgt_zoom = bounds
    
                # Georeference zdroje
                src_lat = src_lon = src_zoom = None
                try:
                    src_lat, src_lon, src_zoom = _parse_lat_lon_zoom_from_name(path.stem)
                except Exception:
                    return False
                if src_lat is None or src_lon is None or src_zoom is None:
                    return False
    
                # Rozměry zdrojové mapy
                try:
                    with _Image.open(path) as _im:
                        Ws, Hs = float(_im.width), float(_im.height)
                except Exception:
                    return False
                if not Ws or not Hs:
                    return False
    
                src_cx, src_cy = _deg2num(float(src_lat), float(src_lon), int(src_zoom))
    
                # Podvzorek bodů + extrémy, kvůli rychlosti
                pts_list = list(pts or [])
                n = len(pts_list)
                if n == 0:
                    return False
                step = max(1, n // 15)
                sample = [pts_list[i] for i in range(0, n, step)]
                sample.append(pts_list[0]); sample.append(pts_list[-1])
    
                for p in sample:
                    xy = _coerce_xy(p)
                    if xy is None:
                        continue
                    x_s, y_s = xy
                    xt = src_cx + (float(x_s) - Ws * 0.5) / TILE_SIZE
                    yt = src_cy + (float(y_s) - Hs * 0.5) / TILE_SIZE
                    lat_deg, lon_deg = _num2deg(xt, yt, int(src_zoom))
                    if (lat_min <= lat_deg <= lat_max) and (lon_min <= lon_deg <= lon_max):
                        return True
                return False
    
            # --- vyčištění panelu ---
            while self.overlay_vbox.count():
                item = self.overlay_vbox.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
    
            # --- vyhledání složky s kandidáty ---
            base = self.image_path.parent
            items = []  # (Path, pts)
    
            # použij existující helper read_polygon_metadata, který už máš v souboru
            def read_polygon_metadata(p):
                try:
                    return globals().get('read_polygon_metadata')(p)
                except Exception:
                    return None
    
            if base.exists() and base.is_dir():
                for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                    try:
                        if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif'}:
                            if p == self.image_path:
                                continue
                            meta = read_polygon_metadata(p)
                            if meta and isinstance(meta.get('points'), list) and len(meta['points']) >= 3:
                                items.append((p, meta['points']))
                    except Exception:
                        continue
    
            # --- spočti bounds aktuální mapy a vyfiltruj relevantní ---
            bounds = _viewport_geo_bounds()
            relevant = []
            for p, pts in items:
                if _polygon_intersects_view(_P(str(p)), pts, bounds):
                    relevant.append((p, pts))
    
            if not relevant:
                self.overlay_vbox.addWidget(QLabel("Žádné relevantní polygony pro aktuální výřez."))
                self.overlay_vbox.addStretch(1)
                return
    
            # --- „plochý“ seznam bez sbalování (bez group togglu) ---
            header = QLabel("✅ Relevantní polygony")
            header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setStyleSheet("font-weight: 600; padding: 2px 0;")
            self.overlay_vbox.addWidget(header)
    
            # mapování pro pozdější práci s checkboxy
            self._overlay_points_by_path = {}
            self._overlay_checkbox_bindings = {}
    
            for p, pts in relevant:
                cb = QCheckBox(_P(str(p)).name)
                cb.setStyleSheet(checkbox_style)
                cb.setChecked(False)
                self._overlay_points_by_path[str(p)] = pts
                cb.toggled.connect(lambda on, path=str(p), pts=pts: self._on_overlay_toggled(on, path, pts))
                self._overlay_checkbox_bindings[cb] = (str(p), pts)
                self.overlay_vbox.addWidget(cb)
    
            self.overlay_vbox.addStretch(1)
    
        except Exception as e:
            print(f"Chyba při načítání overlay seznamu: {e}")
            self.overlay_vbox.addWidget(QLabel("Chyba při načítání polygonů."))
            self.overlay_vbox.addStretch(1)

# --- Polygon metadata I/O helpers ---

def read_polygon_metadata(image_path):
    """
    Načte metadata polygonu z PNG tEXt klíče 'AOI_POLYGON' (JSON).
    Vrací dict: {"points": [[x,y],...], "alpha": 0.15, "color": "#FF0000"} nebo None.
    """
    import json
    from PIL import Image
    from pathlib import Path
    try:
        image_path = Path(image_path)
        with Image.open(image_path) as im:
            text_meta = getattr(im, 'text', {}) or {}
            raw = text_meta.get('AOI_POLYGON')
            if not raw:
                info = getattr(im, 'info', {}) or {}
                raw = info.get('AOI_POLYGON')
            if not raw:
                return None
            data = json.loads(raw)
            pts = data.get('points') or []
            if not isinstance(pts, list) or len(pts) < 3:
                return None
            alpha = float(data.get('alpha', 0.15))
            color = data.get('color', '#FF0000')
            return {'points': pts, 'alpha': alpha, 'color': color}
    except Exception:
        return None

def save_polygon_to_png(image_path, points, alpha_percent=15, color='#FF0000'):
    """
    Vykreslí polygon (výplň + hrany) do obrázku a uloží jej zpět do stejného PNG.
    Uchová existující PNG text metadata a přidá 'AOI_POLYGON' s body pro budoucí editaci.
    """
    import json
    import os
    import tempfile
    from pathlib import Path
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo

    # Body na (float, float) a kontrola počtu
    points = [(float(x), float(y)) for x, y in points]
    if len(points) < 3:
        raise ValueError('Polygon musí mít alespoň 3 body.')

    # Barva z hex (použije se i pro výplň i pro obrys)
    col = str(color or '#FF0000').strip().lstrip('#')
    try:
        if len(col) == 6:
            r = int(col[0:2], 16)
            g = int(col[2:4], 16)
            b = int(col[4:6], 16)
        elif len(col) == 3:
            r = int(col*2, 16)
            g = int(col[2]*2, 16)
            b = int(col[1]*2, 16)
        else:
            r, g, b = 255, 0, 0
    except Exception:
        r, g, b = 255, 0, 0

    image_path = Path(image_path)
    with Image.open(image_path) as im:
        base = im.convert('RGBA')
        W, H = base.size
        overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Alfa 0..1 z procent
        fill_alpha = max(0, min(100, int(alpha_percent))) / 100.0
        fill_rgba = (r, g, b, int(255 * fill_alpha))
        stroke_rgba = (r, g, b, 255)

        # Výplň
        draw.polygon(points, fill=fill_rgba)

        # Obrys – uzavřít polyline přidáním prvního bodu (správně)
        # (původně bylo points + [points], což vytváří vnořený seznam a padá na incorrect coordinate type)
        draw.line(points + [points[0]], fill=stroke_rgba, width=2)

        # Sloučení
        merged = Image.alpha_composite(base, overlay)

        # Přenést existující text metadata + přidat AOI_POLYGON
        text_meta = getattr(im, 'text', {}) or {}
        info_meta = getattr(im, 'info', {}) or {}

        pinfo = PngInfo()
        for k, v in text_meta.items():
            try:
                pinfo.add_text(str(k), str(v))
            except Exception:
                pass

        polygon_json = json.dumps({
            'points': points,
            'alpha': fill_alpha,   # ukládáme 0..1 (čitelné vašimi čtečkami)
            'color': f'#{col.upper()}' if col else '#FF0000',
        })
        pinfo.add_text('AOI_POLYGON', polygon_json)

        # Zachovat DPI, je-li k dispozici
        save_kwargs = {}
        if 'dpi' in info_meta and isinstance(info_meta['dpi'], tuple):
            save_kwargs['dpi'] = info_meta['dpi']

        # Bezpečné uložení přes dočasný soubor
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp_path = Path(tmp.name)
            try:
                merged.save(tmp_path, format='PNG', pnginfo=pinfo, **save_kwargs)
                os.replace(tmp_path, image_path)
            finally:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

def save_without_polygon(image_path):
    """
    Uloží PNG beze změny kresby, ale odstraní AOI_POLYGON z PNG text metadat.
    Zachová ostatní text metadata a DPI (pokud existuje).
    """
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    import tempfile, os
    from pathlib import Path

    image_path = Path(image_path)
    with Image.open(image_path) as im:
        text_meta = getattr(im, 'text', {}) or {}
        info_meta = getattr(im, 'info', {}) or {}
        pinfo = PngInfo()
        for k, v in text_meta.items():
            if str(k) == 'AOI_POLYGON':
                continue
            try:
                pinfo.add_text(str(k), str(v))
            except Exception:
                pass
        save_kwargs = {}
        if 'dpi' in info_meta and isinstance(info_meta['dpi'], tuple):
            save_kwargs['dpi'] = info_meta['dpi']
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            tmp_path = Path(tmp.name)
        # Uložit beze změny pixelů, ale s aktualizovanými text metadaty (bez AOI_POLYGON)
        im.save(tmp_path, format='PNG', pnginfo=pinfo, **save_kwargs)
        os.replace(tmp_path, image_path)

# Soubor: image_viewer.py
# FUNKCE (modulová): open_polygon_editor_for_file  (NÁHRADA CELÉ FUNKCE)

def open_polygon_editor_for_file(image_path, parent=None, point_px=None, edge_px=None, hide_right_panel=False):
    """Otevře modální editor polygonu nad PNG. True při Uložit, jinak False."""
    from PySide6.QtWidgets import QDialog, QWidget
    dlg = PolygonEditorDialog(image_path, parent=parent)

    try:
        # skryj pravý panel s doporučeními (pokud existuje)
        if hide_right_panel:
            for name in ("overlay_panel", "recommendations_panel", "right_overlay_panel", "rightPanel",
                         "side_panel_overlays", "sidebar", "rightSidebar"):
                w = getattr(dlg, name, None)
                if isinstance(w, QWidget):
                    w.setVisible(False)
            # i přes objectName
            for name in ("overlay_panel", "recommendations_panel", "right_overlay_panel", "rightPanel",
                         "side_panel_overlays", "sidebar", "rightSidebar"):
                w = dlg.findChild(QWidget, name)
                if isinstance(w, QWidget):
                    w.setVisible(False)

        # aplikuj velikosti do kreslícího plátna
        canvas = getattr(dlg, "canvas", None)
        if canvas is not None:
            if point_px is not None and hasattr(canvas, "set_point_radius_px"):
                canvas.set_point_radius_px(int(point_px))
            if edge_px is not None and hasattr(canvas, "set_edge_width_px"):
                canvas.set_edge_width_px(int(edge_px))
    except Exception:
        # nechť GUI běží dál i při nenalezení panelu/canvasu
        pass

    return dlg.exec() == QDialog.Accepted

# === VLOŽIT NA KONEC SOUBORU image_viewer.py ===
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QLineEdit, QMessageBox
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QSize
from pathlib import Path
import os, re, json, math, tempfile

class HeicPreviewDialog(QDialog):
    """
    Náhled .HEIC s volbou čísla lokace, přejmenováním na
    <název_mapy_s_ID>_reálné foto.HEIC, doporučením nejbližších map (jen z metadat)
    a úpravou polygonu (editor přes dočasné PNG). Polygon se ukládá do EXIF (AOI_POLYGON=...).
    """
    def __init__(self, image_path: str, maps_root: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Náhled .HEIC — lokace & polygon")
        self.setModal(True)
        self.resize(1000, 720)

        self.image_path = Path(image_path)
        self.maps_root = Path(maps_root)
        self.unsorted_dir = self.maps_root / "Neroztříděné"

        self._orig_qimg: QImage | None = None
        self._poly_cached: list | None = None
        self._gps = self._read_gps_from_heic(self.image_path)

        # --- UI ---
        main = QVBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(8)

        # Náhled (fit-to-window + overlay polygonu)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(360)
        self.preview_label.setStyleSheet("QLabel { background: #111; border: 1px solid #333; }")
        main.addWidget(self.preview_label, 1)

        # Ovládání
        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(QLabel("Číslo lokace:"))
        self.combo_loc = QComboBox()
        self.combo_loc.setMinimumWidth(220)
        row.addWidget(self.combo_loc, 0)

        self.edit_loc = QLineEdit()
        self.edit_loc.setPlaceholderText("např. 00001")
        self.edit_loc.setFixedWidth(100)
        row.addWidget(self.edit_loc, 0)

        self.btn_edit_polygon = QPushButton("Upravit polygon…")
        self.btn_edit_polygon.clicked.connect(self._on_edit_polygon)
        row.addWidget(self.btn_edit_polygon, 0)

        row.addStretch(1)

        self.btn_save = QPushButton("Uložit")
        self.btn_save.clicked.connect(self._on_save)
        row.addWidget(self.btn_save, 0)

        main.addLayout(row)

        near_row = QHBoxLayout()
        near_row.setSpacing(8)
        near_row.addWidget(QLabel("Nejbližší lokační mapy (dle GPS metadat):"), 0, Qt.AlignVCenter)
        self.list_nearby = QListWidget()
        self.list_nearby.setMinimumHeight(160)
        near_row.addWidget(self.list_nearby, 1)
        main.addLayout(near_row)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("QLabel { color: #888; }")
        main.addWidget(self.info_label, 0)

        # Init
        self._ensure_qimage_loaded()
        self._poly_cached = self._read_polygon_from_metadata(self.image_path)
        self._update_preview_pixmap()
        self._populate_location_numbers()
        self._populate_nearby_list()
        self.list_nearby.itemDoubleClicked.connect(self._on_pick_nearby)

        # Cmd+W = zavřít (na macOS Command, v Qt 'Ctrl' mapuje na Command)
        self._sc_close = QShortcut(QKeySequence("Ctrl+W"), self)
        self._sc_close.setAutoRepeat(False)
        self._sc_close.activated.connect(self.close)
        
        self._hide_right_overlay_recommendations_for_heic()
        
        
    # Soubor: image_viewer.py
    # Třída: HeicPreviewDialog
    # NOVÉ: potlačení pravého doporučovacího panelu + úprava vzhledu polygonu v editoru (jen pro HEIC)
    
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QPen
    from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsPathItem
    
    def _hide_right_overlay_recommendations_for_heic(self) -> None:
        """
        Skryje pravý panel s doporučeními „překryvných polygonů“ (pokud existuje).
        NEMĚNÍ nic mimo HEIC dialog.
        """
        # Nejčastější názvy panelů; pokusně projdeme atributy i child widgety
        candidate_names = (
            "recommendations_panel", "right_overlay_panel", "rightPanel",
            "overlay_panel", "side_panel_overlays", "sidebar", "rightSidebar"
        )
        hidden = False
    
        # 1) přímé atributy
        for name in candidate_names:
            w = getattr(self, name, None)
            if isinstance(w, QWidget):
                try:
                    w.setVisible(False)
                    hidden = True
                except Exception:
                    pass
    
        # 2) child lookup podle objectName
        if not hidden:
            for name in candidate_names:
                try:
                    w = self.findChild(QWidget, name)
                    if isinstance(w, QWidget):
                        w.setVisible(False)
                        hidden = True
                except Exception:
                    pass
    
        # Volitelně můžeme upravit rozložení, ale necháme minimalisticky bez dalších zásahů.
    
    
    def _apply_heic_polygon_style(self, editor, handle_scale: float = 5.0, pen_scale: float = 3.0) -> None:
        """
        Zvýrazní polygon při EDITACI v editoru:
          - Úchopy (vrcholy) ~5× větší (handle_scale)
          - Šířka čáry ~3× větší (pen_scale)
        Bez dopadu na editor pro .png (voláme jen v HEIC workflow).
        """
        # 1) Zkus preferované API editoru (pokud existuje)
        try:
            if hasattr(editor, "set_handle_radius"):
                # pokud editor nabízí getter, použijeme stávající hodnotu jako základ
                base = None
                for attr in ("handle_radius", "get_handle_radius"):
                    try:
                        base = getattr(editor, attr) if not callable(getattr(editor, attr)) else getattr(editor, attr)()
                        break
                    except Exception:
                        continue
                if base is None:
                    base = 4  # rozumné minimum
                editor.set_handle_radius(int(round(base * handle_scale)))
        except Exception:
            pass
    
        try:
            if hasattr(editor, "set_pen_width"):
                base_w = None
                for attr in ("pen_width", "get_pen_width"):
                    try:
                        base_w = getattr(editor, attr) if not callable(getattr(editor, attr)) else getattr(editor, attr)()
                        break
                    except Exception:
                        continue
                if base_w is None:
                    base_w = 1.0
                editor.set_pen_width(max(1, int(round(float(base_w) * pen_scale))))
        except Exception:
            pass
    
        # 2) Fallback: přímá manipulace položek ve scéně (QGraphics*)
        try:
            scene = None
            # častá jména view/widgetu
            for attr in ("scene", "graphics_scene", "polygon_scene"):
                if hasattr(editor, attr):
                    scene = getattr(editor, attr)
                    break
            if scene is None and hasattr(editor, "view") and hasattr(editor.view, "scene"):
                try:
                    scene = editor.view.scene()
                except Exception:
                    scene = None
    
            if scene is not None:
                for it in scene.items():
                    # zvětši úchopy (kruhové úchyty na vrcholech bývají QGraphicsEllipseItem)
                    if isinstance(it, QGraphicsEllipseItem):
                        r = it.rect()
                        # zvětšujeme kolem středu
                        cx = r.center().x()
                        cy = r.center().y()
                        new_w = r.width() * handle_scale
                        new_h = r.height() * handle_scale
                        it.setRect(cx - new_w / 2.0, cy - new_h / 2.0, new_w, new_h)
    
                    # tlustší pero pro polygon (QGraphicsPolygonItem/QGraphicsPathItem)
                    if isinstance(it, (QGraphicsPolygonItem, QGraphicsPathItem)):
                        try:
                            pen = it.pen()
                            base_w = max(1.0, float(pen.widthF()) or float(pen.width()))
                            new_w = max(1.0, base_w * pen_scale)
                            new_pen = QPen(pen)
                            new_pen.setWidthF(new_w)
                            it.setPen(new_pen)
                        except Exception:
                            pass
        except Exception:
            pass

    # ---------- Lazy MapProcessor ----------
    def _mp(self):
        """
        Robustní lazy import MapProcessor.
    
        Priority:
          1) běžný import:  from map_processor import MapProcessor
          2) fallbacky podle struktury projektu:
             - <…/gui/>map_processor.py
             - <…/gui/../core/>map_processor.py     ← to je tvůj případ
             - <…/gui/../../core/>map_processor.py  (pro jistotu i o úroveň výš)
    
        Vrací instanci MapProcessor({}) nebo zvedne výjimku (zalogovanou přes _dbg).
        """
        # 1) přímý import
        try:
            from map_processor import MapProcessor  # type: ignore
            return MapProcessor({})
        except Exception as e1:
            pass
            #self._dbg("MapProcessor direct import FAIL:", e1)
    
        # 2) fallbacky přes explicitní soubory
        import importlib.util, sys
        from pathlib import Path
    
        here = Path(__file__).resolve()
        candidates = [
            here.with_name("map_processor.py"),
            here.parent / "core" / "map_processor.py",          # …/Skripty/core/map_processor.py  ← očekávané umístění
            here.parent.parent / "core" / "map_processor.py",   # o úroveň výše pro jistotu
        ]
    
        last_err = None
        for cand in candidates:
            try:
                if cand.exists():
                    spec = importlib.util.spec_from_file_location("map_processor_fallback", str(cand))
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["map_processor_fallback"] = mod
                    spec.loader.exec_module(mod)
                    MapProcessor = getattr(mod, "MapProcessor", None)
                    if MapProcessor is None:
                        raise AttributeError("MapProcessor třída v souboru nebyla nalezena")
                    return MapProcessor({})
            except Exception as e:
                last_err = e
                self._dbg("MapProcessor fallback import FAIL:", str(cand), e)
    
        # pokud nic nevyšlo, vyhoď poslední chybu pro snadné dohledání
        raise RuntimeError(f"MapProcessor not found; tried: {', '.join(map(str, candidates))}") from last_err

    # ---------- GPS ----------
    def _read_gps_from_heic(self, path: Path):
        """
        GPS z metadat .HEIC:
          1) MapProcessor.get_gps_from_image (robustní import),
          2) fallback přes piexif: čtení GPS IFD (bez Pillow EXIF offsetů).
        Včetně DEBUG logu.
        """
        # 1) MapProcessor
        try:
            mp = self._mp()
            res = mp.get_gps_from_image(str(path))
            if isinstance(res, tuple) and len(res) == 2:
                lat, lon = res
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    return (float(lat), float(lon))
        except Exception as e:
            self._dbg("GPS HEIC MapProcessor FAIL:", e)
    
        # 2) EXIF fallback přes piexif
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            import piexif
    
            with Image.open(str(path)) as im:
                exif_bytes = im.info.get("exif", None)
    
            if not exif_bytes:
                return None
    
            exif = piexif.load(exif_bytes)
            gps = exif.get("GPS") or {}
    
            GPSLatitudeRef  = gps.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
            GPSLatitude     = gps.get(piexif.GPSIFD.GPSLatitude)
            GPSLongitudeRef = gps.get(piexif.GPSIFD.GPSLongitudeRef, b"E")
            GPSLongitude    = gps.get(piexif.GPSIFD.GPSLongitude)
    
            if not (GPSLatitude and GPSLongitude):
                return None
    
            # bytes -> str
            if isinstance(GPSLatitudeRef, (bytes, bytearray)):
                GPSLatitudeRef = GPSLatitudeRef.decode("ascii", "ignore")
            if isinstance(GPSLongitudeRef, (bytes, bytearray)):
                GPSLongitudeRef = GPSLongitudeRef.decode("ascii", "ignore")
    
            def _rat_to_float(x):
                # piexif dává tuple(num, den), případně int/float
                try:
                    return float(x[0]) / float(x[1])
                except Exception:
                    try:
                        return float(x)
                    except Exception:
                        return 0.0
    
            def _dms_to_deg(vals):
                d = _rat_to_float(vals[0]); m = _rat_to_float(vals[1]); s = _rat_to_float(vals[2])
                return d + m/60.0 + s/3600.0
    
            lat = _dms_to_deg(GPSLatitude)
            lon = _dms_to_deg(GPSLongitude)
    
            # podpora českých zkratek (J/V/Z) i EN (S/E/W)
            def _norm(c: str) -> str:
                c = (c or "").strip().upper()
                return {"J": "S", "V": "E", "Z": "W"}.get(c, c)
    
            if _norm(GPSLatitudeRef) == "S":
                lat = -lat
            if _norm(GPSLongitudeRef) == "W":
                lon = -lon
    
            return (float(lat), float(lon))
        except Exception as e:
            self._dbg("GPS HEIC piexif FAIL:", e)
    
        self._dbg("GPS HEIC: NOT FOUND")
        return None

    def _get_map_png_gps(self, p: Path):
        """
        GPS lok. mapy (PNG/JPG) pouze z METADAT; když chybí, tak FILENAME fallback:
          1) MapProcessor.get_gps_from_image
          2) piexif (EXIF GPS IFD) – většina PNG nemá EXIF, takže často None
          3) název souboru: ...+GPS49.24173S+17.66780V+...
        """
        # 1) MapProcessor
        try:
            mp = self._mp()
            res = mp.get_gps_from_image(str(p))
            if isinstance(res, tuple) and len(res) == 2:
                lat, lon = res
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    return (float(lat), float(lon))
        except Exception as e:
            self._dbg("GPS MAP MapProcessor FAIL:", p.name, e)
    
        # 2) piexif fallback (PNG většinou neobsahuje EXIF; ponecháme kvůli JPG)
        try:
            from PIL import Image
            import piexif
            with Image.open(str(p)) as im:
                exif_bytes = im.info.get("exif", None)
            if exif_bytes:
                exif = piexif.load(exif_bytes)
                gps = exif.get("GPS") or {}
                lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
                lat_vals = gps.get(piexif.GPSIFD.GPSLatitude)
                lon_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef, b"E")
                lon_vals = gps.get(piexif.GPSIFD.GPSLongitude)
                if isinstance(lat_ref, (bytes, bytearray)):
                    lat_ref = lat_ref.decode("ascii", "ignore")
                if isinstance(lon_ref, (bytes, bytearray)):
                    lon_ref = lon_ref.decode("ascii", "ignore")
                if lat_vals and lon_vals:
                    def _rat_to_float(x):
                        try:
                            return float(x[0]) / float(x[1])
                        except Exception:
                            try:
                                return float(x)
                            except Exception:
                                return 0.0
                    def _dms_to_deg(vals):
                        d = _rat_to_float(vals[0]); m = _rat_to_float(vals[1]); s = _rat_to_float(vals[2])
                        return d + m/60.0 + s/3600.0
                    lat = _dms_to_deg(lat_vals)
                    lon = _dms_to_deg(lon_vals)
                    def _norm(c: str) -> str:
                        c = (c or "").strip().upper()
                        return {"J": "S", "V": "E", "Z": "W"}.get(c, c)
                    if _norm(lat_ref) == "S": lat = -lat
                    if _norm(lon_ref) == "W": lon = -lon
                    return (float(lat), float(lon))
            else:
                pass
                #self._dbg("GPS MAP piexif: no exif bytes", p.name)
        except Exception as e:
            self._dbg("GPS MAP piexif FAIL:", p.name, e)
    
        # 3) Fallback z názvu souboru
        coords = self._parse_gps_from_name(p.stem)
        if coords:
            return coords
    
        self._dbg("NEARBY: no GPS in map meta:", p.name)
        return None
    
    def _parse_gps_from_name(self, stem: str):
        """
        Fallback parsování GPS z názvu mapky (PNG/JPG), např.:
          ...+GPS49.24173S+17.66780V+...
        Znaková konvence:
          S nebo N => kladná šířka (sever),
          J        => záporná šířka (jih),
          V nebo E => kladná délka (východ),
          Z nebo W => záporná délka (západ).
        Vrací (lat, lon) nebo None.
        """
        import re
        s = stem.replace(",", ".")
        m = re.search(r"GPS\s*([0-9]+(?:\.[0-9]+)?)\s*([SNJsjn])\+([0-9]+(?:\.[0-9]+)?)\s*([VEWZvewz])", s)
        if not m:
            return None
        lat = float(m.group(1))
        lat_c = m.group(2).upper()
        lon = float(m.group(3))
        lon_c = m.group(4).upper()
    
        # lat sign
        if lat_c == "J":   # jih
            lat = -lat
        # 'S' i 'N' chápeme jako sever => kladně
    
        # lon sign
        if lon_c in ("W", "Z"):  # west / západ
            lon = -lon
        # 'V' i 'E' => kladně (východ)
    
        return (lat, lon)

    # ---------- Náhled: načtení a vykreslení s overlay ----------
    def _ensure_qimage_loaded(self):
        if self._orig_qimg is not None:
            return
        from PIL import Image
        img = QImage(str(self.image_path))
        if img.isNull():
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
                with Image.open(str(self.image_path)) as im:
                    im = im.convert("RGBA")
                    data = im.tobytes("raw", "RGBA")
                    img = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
            except Exception:
                pass
        self._orig_qimg = img if not img.isNull() else None
        # ← při prvním načtení si rovnou načti polygon z metadat
        try:
            self._poly_cached = self._read_polygon_from_metadata(self.image_path)
        except Exception:
            self._poly_cached = None

    def _update_preview_pixmap(self):
        """
        Fit-to-window náhled + overlay polygonu (pokud je self._poly_cached).
        """
        if self._orig_qimg is None or self.preview_label.width() <= 0 or self.preview_label.height() <= 0:
            self.preview_label.setText("Nelze načíst náhled .HEIC")
            return
    
        avail_w = max(1, self.preview_label.width() - 4)
        avail_h = max(1, self.preview_label.height() - 4)
        scaled = self._orig_qimg.scaled(avail_w, avail_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    
        if self._poly_cached and len(self._poly_cached) >= 3 and self._orig_qimg.width() > 0 and self._orig_qimg.height() > 0:
            try:
                draw_img = QImage(scaled)
                painter = QPainter(draw_img)
                try:
                    sx = scaled.width() / self._orig_qimg.width()
                    sy = scaled.height() / self._orig_qimg.height()
                    pen = QPen(Qt.red)
                    pen.setWidth(max(1, int(2 * (sx + sy) / 2)))
                    painter.setPen(pen)
                    pts = [(float(x) * sx, float(y) * sy) for (x, y) in self._poly_cached]
                    for i in range(len(pts)):
                        x1, y1 = pts[i]
                        x2, y2 = pts[(i + 1) % len(pts)]
                        painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                finally:
                    painter.end()
                self.preview_label.setPixmap(QPixmap.fromImage(draw_img))
                return
            except Exception:
                pass
    
        self.preview_label.setPixmap(QPixmap.fromImage(scaled))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_pixmap()

    # Soubor: image_viewer.py
    # Třída: HeicPreviewDialog
    # FUNKCE: showEvent  ❗️NOVÁ — zajistí, že se polygon z metadat .HEIC načte a zobrazí i v náhledu (mezerník)
    # Pozn.: Zachovává stávající chování dialogu; pouze doplní načtení AOI_POLYGON z EXIF a překreslení náhledu.
    
    from PySide6.QtCore import QEvent
    from pathlib import Path
    
    def showEvent(self, event: "QEvent") -> None:
        """Při zobrazení dialogu se (tiše) pokusí načíst polygon z metadat HEIC a ihned ho vykreslí do náhledu."""
        try:
            # standardní showEvent
            try:
                super(HeicPreviewDialog, self).showEvent(event)
            except Exception:
                try:
                    super().showEvent(event)  # pro jistotu, dle MRO
                except Exception:
                    pass
    
            # Bezpečně ověř cíl
            p = getattr(self, "image_path", None)
            if not p:
                return
            path = Path(str(p))
            if not (path.exists() and path.is_file() and path.suffix.lower() in {".heic", ".heif"}):
                return
    
            # Pokud ještě nemáme polygon v cache, načti ho z EXIF (UserComment / ImageDescription)
            if getattr(self, "_poly_cached", None) is None and hasattr(self, "_read_polygon_from_metadata"):
                try:
                    pts = self._read_polygon_from_metadata(path)
                    if isinstance(pts, list) and len(pts) >= 3:
                        # Ulož do cache (floaty kvůli přesnosti)
                        self._poly_cached = [(float(x), float(y)) for (x, y) in pts]
                except Exception:
                    pass
    
            # Pro zřetelný náhled nastav výchozí šířku hrany (neovlivní uložení ani editor PNG)
            if not hasattr(self, "_edge_width_px"):
                try:
                    self._edge_width_px = 10  # čitelný náhled
                except Exception:
                    pass
    
            # Překresli náhled, pokud funkce existuje
            if hasattr(self, "_update_preview_pixmap"):
                try:
                    self._update_preview_pixmap()
                except Exception:
                    pass
    
            # Aktualizuj popisky (nepovinné)
            if hasattr(self, "_update_info_label"):
                try:
                    self._update_info_label()
                except Exception:
                    pass
    
        except Exception:
            # Tichý návrat – nesmí rozbít původní náhled
            return
        
    # Soubor: image_viewer.py
    # Třída: HeicPreviewDialog
    # FUNKCE: _force_preview_polygon_refresh  ❗️NOVÁ — volitelný helper, můžete volat odkudkoli v dialogu
    #         Znovu načte polygon z metadat a překreslí náhled. Nepovinné, ale praktické pro ruční refresh.
    
    from pathlib import Path
    
    def _force_preview_polygon_refresh(self) -> None:
        """
        Načte AOI_POLYGON z metadat HEIC a překreslí náhled (bez otevření editoru).
        Bezpečné volání – při chybě dělá nic.
        """
        try:
            p = getattr(self, "image_path", None)
            if not p:
                return
            path = Path(str(p))
            if not (path.exists() and path.is_file() and path.suffix.lower() in {".heic", ".heif"}):
                return
    
            if hasattr(self, "_read_polygon_from_metadata"):
                try:
                    pts = self._read_polygon_from_metadata(path)
                    if isinstance(pts, list) and len(pts) >= 3:
                        self._poly_cached = [(float(x), float(y)) for (x, y) in pts]
                    else:
                        self._poly_cached = None
                except Exception:
                    return
    
            if not hasattr(self, "_edge_width_px"):
                self._edge_width_px = 10
    
            if hasattr(self, "_update_preview_pixmap"):
                self._update_preview_pixmap()
            if hasattr(self, "_update_info_label"):
                self._update_info_label()
        except Exception:
            return

    # ---------- Lokace / ComboBox ----------
    def _extract_id_from_name(self, stem: str):
        if '+' not in stem:
            return None
        tail = stem.rsplit('+', 1)[-1].strip()
        m = re.search(r'(\d+)$', tail)
        return int(m.group(1)) if m else None

    def _format_id5(self, v: int) -> str:
        return f"{int(v):05d}"

    def _label_for_id5(self, id5: str) -> str:
        """
        Najde v 'Neroztříděné' mapu, jejíž název končí '+<id5>'.
        Vrátí první část názvu (před prvním '+') jako 'IDLokace'.
        """
        if not self.unsorted_dir.exists():
            return f"IDLokace {id5}"
        for p in self.unsorted_dir.iterdir():
            if not p.is_file():
                continue
            stem = p.stem
            if stem.endswith("+" + id5):
                return stem.split('+', 1)[0]
        return f"IDLokace {id5}"

    def _populate_location_numbers(self):
        self.combo_loc.clear()
        ids = set()
        if self.unsorted_dir.exists():
            for p in self.unsorted_dir.iterdir():
                if p.is_file():
                    v = self._extract_id_from_name(p.stem)
                    if isinstance(v, int):
                        ids.add(v)
        for v in sorted(ids):
            id5 = self._format_id5(v)
            label = self._label_for_id5(id5)
            self.combo_loc.addItem(f"{id5} — {label}", id5)

        # předvyplnění z názvu HEIC (pokud obsahuje +00001 apod.)
        cur = self._extract_id_from_name(self.image_path.stem)
        if isinstance(cur, int):
            s = self._format_id5(cur)
            self.edit_loc.setText(s)
            idx = self.combo_loc.findData(s)
            if idx >= 0:
                self.combo_loc.setCurrentIndex(idx)

    def _on_pick_nearby(self, item: QListWidgetItem):
        val = item.data(Qt.UserRole)
        if isinstance(val, int):
            s = self._format_id5(val)
            self.edit_loc.setText(s)
            idx = self.combo_loc.findData(s)
            if idx >= 0:
                self.combo_loc.setCurrentIndex(idx)

    # ---------- Doporučení: pouze z metadatových GPS ----------
    def _distance_km(self, a, b):
        if not a or not b:
            return float("inf")
        lat1, lon1 = a
        lat2, lon2 = b
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        h = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
        return 2 * R * math.asin(math.sqrt(h))

    def _populate_nearby_list(self):
        """Naplní doporučené mapy (GPS z metadat/názvu) a **předvyplní** číslo lokace do comboboxu i inputu."""
        self.list_nearby.clear()
    
        # bezpečně odpojit staré spojení, pokud existovalo
        try:
            if hasattr(self, "_nearby_conn"):
                try:
                    self.list_nearby.currentItemChanged.disconnect(self._nearby_conn)
                except Exception:
                    pass
                self._nearby_conn = None
        except Exception:
            pass
    
        if not self._gps:
            self.info_label.setText("GPS v .HEIC nenalezena — doporučení nelze.")
            return
    
        if not self.unsorted_dir.exists():
            return
    
        cand = []
        for p in self.unsorted_dir.iterdir():
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                g = self._get_map_png_gps(p)
                if g:
                    d = self._distance_km(self._gps, g)
                    vid = self._extract_id_from_name(p.stem)
                    cand.append((d, p.name, vid, g))
    
        cand.sort(key=lambda x: x[0])
    
        for d, name, vid, _ in cand[:30]:
            item = QListWidgetItem(f"{name} — {d:.2f} km")
            if isinstance(vid, int):
                item.setData(Qt.UserRole, vid)
            self.list_nearby.addItem(item)
    
            if cand:
                # zvol první doporučení
                try:
                    self.list_nearby.setCurrentRow(0)
                except Exception:
                    pass
        
                first_vid = cand[0][2]
                if isinstance(first_vid, int):
                    loc_str = f"{first_vid:05d}"
                    
                    # Stávající logika pro vyplnění polí
                    self._set_location_number_fields(loc_str)
                    if hasattr(self, 'edit_loc'):
                        self.edit_loc.setText(loc_str)
                    if hasattr(self, 'combo_loc'):
                        idx = self.combo_loc.findData(loc_str)
                        if idx >= 0:
                            self.combo_loc.setCurrentIndex(idx)
        
                    # PŘIDÁNO: Přesunout focus pryč z inputu, aby nezachytával klávesové události.
                    # Ideálně na seznam doporučených, pokud existuje.
                    if hasattr(self, 'list_nearby'):
                        self.list_nearby.setFocus()
                    else:
                        self.setFocus() # Alternativně na samotný dialog
    
        # připojit synchronizaci na změnu výběru v „Doporučené"
        try:
            def _on_change(cur, prev):
                self._on_nearby_current_changed(cur, prev)
            self.list_nearby.currentItemChanged.connect(_on_change)
            self._nearby_conn = _on_change
        except Exception:
            self._nearby_conn = None

        
    def _on_nearby_current_changed(self, cur, prev):
        """Při změně výběru v seznamu „Doporučené“ nastav combobox a input čísla lokace."""
        try:
            if not cur:
                return
            vid = cur.data(Qt.UserRole)
            if isinstance(vid, int):
                loc_str = f"{vid:05d}"
                self._set_location_number_fields(loc_str)
        except Exception as e:
            self._dbg("NEARBY selection FAIL:", e)
        
    def _set_location_number_fields(self, loc_str: str):
        """Bezpečně předvyplní combobox i lineedit čísla lokace (zkusí více možných názvů widgetů)."""
        # Kandidáti názvů pro combobox a lineedit (kvůli různým verzím UI)
        combo_candidates = [
            "combo_location_number", "location_number_combo", "combo_loc_number",
            "location_combo", "cb_location_number"
        ]
        lineedit_candidates = [
            "edit_location_number", "location_number_edit", "le_location_number",
            "lineedit_location_number", "loc_number_edit"
        ]
    
        # nastav combobox (pokud existuje)
        for attr in combo_candidates:
            cb = getattr(self, attr, None)
            if cb is None:
                continue
            try:
                blocked = cb.blockSignals(True)
            except Exception:
                blocked = False
            try:
                idx = cb.findText(loc_str)
                if idx >= 0:
                    cb.setCurrentIndex(idx)
                else:
                    # když není v modelu; pokud je combo editovatelné, nastav text
                    try:
                        cb.setCurrentText(loc_str)
                    except Exception:
                        pass
            except Exception as e:
                self._dbg(f"AUTO-FILL combo '{attr}' FAIL:", e)
            try:
                cb.blockSignals(blocked)
            except Exception:
                pass
            # první úspěšný combobox stačí
            break
    
        # nastav lineedit (pokud existuje)
        for attr in lineedit_candidates:
            le = getattr(self, attr, None)
            if le is None:
                continue
            try:
                blocked = le.blockSignals(True)
            except Exception:
                blocked = False
            try:
                le.setText(loc_str)
            except Exception as e:
                self._dbg(f"AUTO-FILL lineedit '{attr}' FAIL:", e)
            try:
                le.blockSignals(blocked)
            except Exception:
                pass
            break

    # ---------- Polygon: čtení / zápis / odstranění ----------
    def _read_polygon_from_metadata(self, path: Path):
        """
        HEIC: čtení AOI_POLYGON z EXIF (nejprve UserComment, pak ImageDescription).
        Vrací list bodů nebo None.
        """
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            import piexif, re, json
    
            with Image.open(str(path)) as im:
                exif_bytes = im.info.get("exif", None)
            if not exif_bytes:
                return None
            exif = piexif.load(exif_bytes)
    
            def _extract(txt):
                if isinstance(txt, bytes):
                    txt = txt.decode("utf-8", "ignore")
                if not isinstance(txt, str):
                    return None
                m = re.search(r"AOI_POLYGON\s*=\s*(\{.*\})", txt, re.DOTALL)
                if not m:
                    return None
                try:
                    data = json.loads(m.group(1))
                    pts = data.get("points")
                    if isinstance(pts, list) and len(pts) >= 3:
                        return pts
                except Exception:
                    return None
                return None
    
            # 1) UserComment
            pts = _extract(exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b""))
            if pts:
                return pts
            # 2) ImageDescription
            pts = _extract(exif.get("0th", {}).get(piexif.ImageIFD.ImageDescription, b""))
            return pts
        except Exception:
            return None

    def _write_polygon_to_metadata(self, path: Path, points):
        """
        HEIC: přepiš polygon do EXIF (0th.ImageDescription a UserComment) jako 'AOI_POLYGON=<json>'.
        Postup:
          - načti existující EXIF,
          - odstraň staré 'AOI_POLYGON=…',
          - vlož nový chunk,
          - ulož do dočasného souboru a atomicky nahraď.
        """
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            import piexif, re, json, tempfile, os
    
            payload = {"points": [(float(x), float(y)) for x, y in points]}
            with Image.open(str(path)) as im:
                exif_bytes = im.info.get("exif", None)
                if exif_bytes:
                    exif = piexif.load(exif_bytes)
                else:
                    exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    
                # --- vyčisti staré AOI_POLYGON v ImageDescription & UserComment
                def _clean(text):
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", "ignore")
                    if not isinstance(text, str):
                        text = ""
                    return re.sub(r"AOI_POLYGON\s*=\s*\{.*?\}", "", text, flags=re.DOTALL).strip()
    
                desc = _clean(exif.get("0th", {}).get(piexif.ImageIFD.ImageDescription, b""))
                ucom = _clean(exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b""))
    
                new_chunk = f"AOI_POLYGON={json.dumps(payload, ensure_ascii=False)}"
                desc = new_chunk if not desc else f"{desc}\n{new_chunk}"
                ucom = new_chunk if not ucom else f"{ucom}\n{new_chunk}"
    
                exif["0th"][piexif.ImageIFD.ImageDescription] = desc.encode("utf-8", "ignore")
                exif["Exif"][piexif.ExifIFD.UserComment] = ucom.encode("utf-8", "ignore")
    
                # ulož
                with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix) as tmp:
                    tmp_path = Path(tmp.name)
                im.save(str(tmp_path), format=im.format, exif=piexif.dump(exif))
            os.replace(str(tmp_path), str(path))
            return True
        except Exception as e:
            QMessageBox.warning(self, "Uložení do metadat", f"Nepodařilo se uložit polygon do EXIF: {e}")
            return False

    def _remove_polygon_from_metadata(self, path: Path):
        """HEIC: smaž AOI_POLYGON z UserComment i ImageDescription."""
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            import piexif, re, tempfile, os
    
            def _clean(txt):
                if isinstance(txt, bytes):
                    txt = txt.decode("utf-8", "ignore")
                if not isinstance(txt, str):
                    return ""
                return re.sub(r"AOI_POLYGON\s*=\s*\{.*?\}", "", txt, flags=re.DOTALL).strip()
    
            with Image.open(str(path)) as im:
                exif_bytes = im.info.get("exif", None)
                if not exif_bytes:
                    return True
                exif = piexif.load(exif_bytes)
                desc = _clean(exif.get("0th", {}).get(piexif.ImageIFD.ImageDescription, b""))
                ucom = _clean(exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b""))
    
                if desc:
                    exif["0th"][piexif.ImageIFD.ImageDescription] = desc.encode("utf-8", "ignore")
                elif piexif.ImageIFD.ImageDescription in exif["0th"]:
                    del exif["0th"][piexif.ImageIFD.ImageDescription]
    
                if ucom:
                    exif["Exif"][piexif.ExifIFD.UserComment] = ucom.encode("utf-8", "ignore")
                elif piexif.ExifIFD.UserComment in exif["Exif"]:
                    del exif["Exif"][piexif.ExifIFD.UserComment]
    
                with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix) as tmp:
                    tmp_path = Path(tmp.name)
                im.save(str(tmp_path), format=im.format, exif=piexif.dump(exif))
            os.replace(str(tmp_path), str(path))
            return True
        except Exception as e:
            QMessageBox.warning(self, "Odstranění polygonu", f"Nepodařilo se odstranit polygon z EXIF: {e}")
            return False
        
    # Soubor: image_viewer.py
    # Třída: HeicPreviewDialog
    # FUNKCE: _on_edit_polygon  (NAHRAĎ TOUTO VERZÍ)
    # Pozn.: Po Uložit vykreslí výplň s pevnou 80% průhledností (alpha=51) a feather přechodem. Bez okraje.
    
    def _on_edit_polygon(self):
        import tempfile
        from PIL import Image, PngImagePlugin
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
    
        # 1) HEIC -> dočasné PNG
        try:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            with Image.open(str(self.image_path)) as im:
                im_rgba = im.convert("RGBA")
                pnginfo = PngImagePlugin.PngInfo()
                if self._poly_cached and isinstance(self._poly_cached, list) and len(self._poly_cached) >= 3:
                    import json as _json
                    payload = {"points": [(float(x), float(y)) for x, y in self._poly_cached]}
                    pnginfo.add_itxt("AOI_POLYGON", _json.dumps(payload, ensure_ascii=False))
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp_png = Path(tmp.name)
                im_rgba.save(str(tmp_png), format="PNG", pnginfo=pnginfo)
        except Exception as e:
            self._dbg("PNG export FAIL:", e)
            QMessageBox.critical(self, "Polygon", f"Nelze připravit dočasný PNG: {e}")
            return
    
        # 2) Otevřít editor
        try:
            from image_viewer import open_polygon_editor_for_file, read_polygon_metadata
        except Exception:
            try:
                import importlib.util, sys
                here = Path(__file__).resolve()
                iv_path = here.with_name("image_viewer.py")
                spec = importlib.util.spec_from_file_location("image_viewer_fallback_poly", str(iv_path))
                if spec is None or spec.loader is None:
                    raise ImportError("Nelze vytvořit import spec pro image_viewer_fallback_poly")
                mod = importlib.util.module_from_spec(spec)
                sys.modules["image_viewer_fallback_poly"] = mod
                spec.loader.exec_module(mod)
                open_polygon_editor_for_file = getattr(mod, "open_polygon_editor_for_file", None)
                read_polygon_metadata = getattr(mod, "read_polygon_metadata", None)
                if open_polygon_editor_for_file is None:
                    raise AttributeError("Chybí funkce open_polygon_editor_for_file v image_viewer.py")
            except Exception as e:
                self._dbg("Editor import FAIL:", e)
                QMessageBox.critical(self, "Polygon", f"Nelze otevřít editor polygonu: {e}")
                try:
                    tmp_png.unlink(missing_ok=True)
                except Exception:
                    pass
                return
    
        accepted = False
        try:
            accepted = bool(open_polygon_editor_for_file(
                str(tmp_png),
                parent=self,
                point_px=30,    # pouze styling editoru
                edge_px=10,     # pouze styling editoru
                hide_right_panel=True
            ))
        except Exception as e:
            self._dbg("Editor run FAIL:", e)
            QMessageBox.critical(self, "Polygon", f"Chyba při otevření editoru polygonu: {e}")
        finally:
            try:
                if accepted:
                    pts = None
                    if callable(read_polygon_metadata):
                        try:
                            meta = read_polygon_metadata(str(tmp_png))
                            if isinstance(meta, dict) and isinstance(meta.get("points"), list):
                                pts = meta["points"]
                        except Exception as e:
                            self._dbg("read_polygon_metadata FAIL:", e)
                            pts = None
                    if pts is None:
                        try:
                            with Image.open(str(tmp_png)) as pim:
                                info = getattr(pim, "text", None) or {}
                                if not info and hasattr(pim, "info"):
                                    info = {k: v for k, v in pim.info.items() if isinstance(v, str)}
                                import re, json as _json
                                joined = "\n".join([f"{k}={v}" for k, v in info.items()])
                                m = re.search(r"AOI_POLYGON\s*=\s*(\{.*\})", joined, re.DOTALL)
                                if not m and "AOI_POLYGON" in info:
                                    try:
                                        data = _json.loads(info["AOI_POLYGON"])
                                        cand = data.get("points")
                                        if isinstance(cand, list) and len(cand) >= 3:
                                            pts = cand
                                    except Exception:
                                        pass
                                elif m:
                                    data = _json.loads(m.group(1))
                                    cand = data.get("points")
                                    if isinstance(cand, list) and len(cand) >= 3:
                                        pts = cand
                        except Exception as e:
                            self._dbg("PNG chunk read FAIL:", e)
                            pts = None
    
                    if pts and len(pts) >= 2:
                        self._poly_cached = [(float(x), float(y)) for (x, y) in pts]
    
                        # Finální parametry: 80 % průhledná výplň, bez obrysu, měkký přechod
                        fill_alpha_final = 51
                        feather_px_final = 14
    
                        # barva z UI (pokud je)
                        fill_hex = None
                        for attr in ("_poly_color_hex", "poly_color_hex", "color_hex"):
                            if hasattr(self, attr):
                                try:
                                    fill_hex = getattr(self, attr)
                                    if fill_hex:
                                        break
                                except Exception:
                                    pass
    
                        ok = self._write_polygon_to_metadata_and_draw(
                            self.image_path,
                            self._poly_cached,
                            edge_px=0,                 # okraj se nekreslí
                            fill_hex=fill_hex,
                            fill_alpha=fill_alpha_final,
                            feather_px=feather_px_final,
                        )
                        if not ok and hasattr(self, "log_widget"):
                            self.log_widget.add_log("⚠️ Vykreslení měkké výplně polygonu do HEIC se nezdařilo; metadata byla uložena.", "warn")
                    else:
                        self._poly_cached = None
                        try:
                            self._remove_polygon_from_metadata(self.image_path)
                        except Exception:
                            pass
            finally:
                try:
                    tmp_png.unlink(missing_ok=True)
                except Exception:
                    pass
    
        try:
            self._update_info_label()
        except Exception:
            pass
        try:
            self._update_preview_pixmap()
        except Exception:
            pass
     
    # Soubor: image_viewer.py
    # Třída: HeicPreviewDialog
    # FUNKCE: _write_polygon_to_metadata_and_draw  (NAHRAĎ TOUTO VERZÍ)
    # Úprava: výplň je pevně ~80 % PRŮHLEDNÁ (≈20 % opacity → alpha=51) uprostřed polygonu a
    #         směrem od hran plynule klesá až na 100 % transparentnost (0). Okraj (čára) se NEKRESLÍ.
    
    def _write_polygon_to_metadata_and_draw(self, path, points, edge_px: int = 0,
                                            fill_hex: str | None = None,
                                            fill_alpha: int = 51,    # 80 % průhledná
                                            feather_px: int = 14) -> bool:
        """
        HEIC: zapíše AOI_POLYGON do EXIF a fyzicky vykreslí pouze měkkou výplň polygonu.
        - fill_alpha je MAX alfa uvnitř (0–255) → 51 ≈ 80 % průhledná.
        - feather_px určuje měkký přechod k 100 % transparentnu.
        - Bez kreslení obrysu/hran.
        """
        from pathlib import Path
        from PIL import Image, ImageDraw, ImageFilter
        import os, tempfile, re, json
    
        path = Path(path)
        if not (path.exists() and path.is_file() and path.suffix.lower() in {".heic", ".heif"}):
            return False
        if not (isinstance(points, list) and len(points) >= 2):
            return False
    
        # Body → int pixely
        try:
            pxy = [(int(round(float(x))), int(round(float(y)))) for (x, y) in points]
        except Exception:
            return False
    
        # Barva z UI (fallback červená)
        stroke_hex = None
        for attr in ("_poly_color_hex", "poly_color_hex", "color_hex"):
            if hasattr(self, attr):
                try:
                    stroke_hex = getattr(self, attr)
                    if stroke_hex:
                        break
                except Exception:
                    pass
        if fill_hex is None:
            fill_hex = stroke_hex or "#ff0000"
    
        def _hex_to_rgb(h: str):
            try:
                hh = str(h).lstrip("#")
                if len(hh) == 3:
                    hh = "".join(c*2 for c in hh)
                return (int(hh[0:2], 16), int(hh[2:4], 16), int(hh[4:6], 16))
            except Exception:
                return (255, 0, 0)
    
        rgb = _hex_to_rgb(fill_hex)
        fill_alpha = max(0, min(255, int(fill_alpha)))
        feather_px = max(0, int(feather_px))
    
        # HEIF registrace
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
    
        try:
            import piexif
            with Image.open(str(path)) as im:
                # EXIF načíst/vytvořit
                exif_bytes = im.info.get("exif", None)
                if exif_bytes:
                    exif = piexif.load(exif_bytes)
                else:
                    exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    
                # EXIF: vyčistit staré AOI_POLYGON a zapsat nový
                def _clean(text):
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", "ignore")
                    if not isinstance(text, str):
                        text = ""
                    return re.sub(r"AOI_POLYGON\s*=\s*\{.*?\}", "", text, flags=re.DOTALL).strip()
    
                desc = _clean(exif.get("0th", {}).get(piexif.ImageIFD.ImageDescription, b""))
                ucom = _clean(exif.get("Exif", {}).get(piexif.ExifIFD.UserComment, b""))
                payload = {"points": [(float(x), float(y)) for (x, y) in points]}
                new_chunk = f"AOI_POLYGON={json.dumps(payload, ensure_ascii=False)}"
                desc = new_chunk if not desc else f"{desc}\n{new_chunk}"
                ucom = new_chunk if not ucom else f"{ucom}\n{new_chunk}"
                exif_dump = piexif.dump(exif | {
                    "0th": {**exif.get("0th", {}), piexif.ImageIFD.ImageDescription: desc.encode("utf-8", "ignore")},
                    "Exif": {**exif.get("Exif", {}), piexif.ExifIFD.UserComment: ucom.encode("utf-8", "ignore")},
                })
    
                # Podklad
                base = im.convert("RGBA")
                W, H = base.size
    
                # 1) Ostrá polygonová maska
                mask = Image.new("L", (W, H), 0)
                ImageDraw.Draw(mask).polygon(pxy, fill=255)
    
                # 2) Feather: Gaussian blur → normalizace tak, aby maximum bylo přesně fill_alpha
                if feather_px > 0:
                    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_px))
                max_val = mask.getextrema()[1] or 1  # ochrana proti 0
                if max_val != fill_alpha:
                    scale = float(fill_alpha) / float(max_val)
                    mask = mask.point(lambda v: int(v * scale + 0.5))
    
                # 3) Barevný overlay s touto maskou (bez čáry/okraje)
                overlay = Image.new("RGBA", (W, H), (rgb[0], rgb[1], rgb[2], 255))
                overlay.putalpha(mask)
                out = Image.alpha_composite(base, overlay)
    
                # 4) Uložit atomicky s EXIF
                with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix) as tmp:
                    tmp_path = Path(tmp.name)
                fmt = getattr(im, "format", None) or "HEIF"
                icc = im.info.get("icc_profile", None)
                save_kwargs = {"format": fmt, "exif": exif_dump}
                if icc:
                    save_kwargs["icc_profile"] = icc
                out.convert("RGB").save(str(tmp_path), **save_kwargs)
    
            os.replace(str(tmp_path), str(path))
            return True
    
        except Exception as e:
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Uložení polygonu do obrázku",
                                    f"Vykreslení měkké výplně do HEIC selhalo: {e}")
            except Exception:
                pass
            return False
        
    # ---------- Uložení / přejmenování ----------
    def _find_map_name_by_id(self, id5: str) -> str | None:
        """
        Najde v 'Neroztříděné' mapu, jejíž NÁZEV (stem) končí '+<id5>'.
        Vrací její stem (bez přípony) nebo None.
        """
        if not self.unsorted_dir.exists():
            return None
        for p in self.unsorted_dir.iterdir():
            if not p.is_file():
                continue
            stem = p.stem
            if stem.endswith("+" + id5):
                return stem
        return None

    def _update_info_label(self):
        parts = []
        if self._poly_cached:
            parts.append(f"Polygon: {len(self._poly_cached)} bodů")
        if self._gps:
            parts.append(f"GPS: {self._gps[0]:.6f}, {self._gps[1]:.6f}")
        self.info_label.setText(" | ".join(parts) if parts else "—")

    def _on_save(self):
        """
        - Pokud je polygon (_poly_cached):
            -> přepiš polygon v EXIF (zůstane jen poslední).
          Pokud polygon není:
            -> vymaž polygon z EXIF.
        - Přejmenuj HEIC dle mapy se shodným ID:
            nový název = <stem_mapky>_reálné foto.HEIC
        """
        # polygon: uložit/odstranit
        if self._poly_cached and len(self._poly_cached) >= 3:
            if not self._write_polygon_to_metadata(self.image_path, self._poly_cached):
                return
        else:
            if not self._remove_polygon_from_metadata(self.image_path):
                return

        # přejmenování
        id_txt = (self.edit_loc.text() or "").strip()
        if not id_txt and self.combo_loc.currentIndex() >= 0:
            id_txt = self.combo_loc.currentData() or self.combo_loc.currentText().strip()
        new_path = self.image_path

        if id_txt:
            try:
                id5 = f"{int(id_txt):05d}"
            except Exception:
                QMessageBox.warning(self, "Uložit", "Číslo lokace musí být číslo (např. 00001).")
                return
            map_stem = self._find_map_name_by_id(id5)
            if not map_stem:
                QMessageBox.warning(self, "Uložit", f"Nebyla nalezena lokační mapa končící '+{id5}' ve složce 'Neroztříděné'.")
                return
            target_stem = f"{map_stem}_reálné foto"
            target_path = self.image_path.with_name(target_stem + self.image_path.suffix)
            try:
                if target_path != self.image_path:
                    os.rename(self.image_path, target_path)
                    new_path = target_path
            except Exception as e:
                QMessageBox.warning(self, "Uložit", f"Přejmenování selhalo: {e}")
                return

        QMessageBox.information(self, "Hotovo", "Změny byly uloženy.")
        self.image_path = new_path
        self.accept()
        
        
        
    def _dbg(self, *args):
        """Jednoduchý konzolový debug s prefixem dialogu."""
        print("[HEIC_PREVIEW]", *args)
