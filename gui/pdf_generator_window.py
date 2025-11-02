# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QTabWidget, QGroupBox, QLabel, QLineEdit, QPushButton, QTextEdit,
    QCheckBox, QSpinBox, QProgressBar, QFileDialog, QMessageBox,
    QComboBox, QFrame, QListWidget, QListWidgetItem, QPlainTextEdit,
    QDialog, QTreeView, QMenu, QInputDialog, QGridLayout,  # <- PŘIDÁNO QGridLayout
    QFileSystemModel, QSizePolicy, QAbstractItemView
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QTimer, QDir, QSize, QFileSystemWatcher,
    QObject, QEvent, QRect  # <- PŘIDÁNO pro event filtry
)
from PySide6.QtGui import (
    QFont, QAction, QPainter, QColor, QTextFormat, QSyntaxHighlighter, 
    QTextCharFormat, QShortcut, QKeySequence, QFontMetrics
)

from pathlib import Path
import json
import os
import sys
import datetime
import shutil
import time

# Import hlavní funkce z PDF generátoru
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_generator import main as generate_pdf_main

from PySide6.QtWidgets import QRubberBand
from PySide6.QtGui import QImage, QPainter

try:
    from shapely.geometry import Point, Polygon
except ImportError:
    # Vytvoříme dummy třídy, aby aplikace nespadla, pokud shapely chybí.
    # Uživatel bude upozorněn chybovou hláškou.
    class Point:
        def __init__(self, *args): pass
        def within(self, other): return False
    class Polygon:
        def __init__(self, *args): pass

class PDFGeneratorThread(QThread):
    """Thread pro generování PDF na pozadí - opravená verze"""
    progress_updated = Signal(str)
    finished_success = Signal(object)
    finished_error = Signal(str)

    def __init__(self, n, m, location_config, def_cesta_lokaci, cesta_ctyrlistky, output_pdf, poznamky_dict, copy_folder, pages_per_pdf, status_dict=None, parent=None):
        super().__init__(parent)
        self.n = n
        self.m = m
        self.location_config = location_config
        self.location_path = def_cesta_lokaci
        self.clover_path = cesta_ctyrlistky
        self.output_pdf = output_pdf
        self.poznamky_dict = poznamky_dict
        self.copy_folder = copy_folder
        self.pages_per_pdf = pages_per_pdf
        self.status_dict = status_dict  # NOVÉ: stavový slovník

    def run(self):
        """Spustí generování PDF s detailními progress indikátory."""
        import sys
        class _SignalLogWriter:
            def __init__(self, emitter):
                self._emit = emitter
                self._buf = ""
            def write(self, s):
                self._buf += str(s)
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    if line.strip():
                        self._emit.emit(line.strip())
            def flush(self):
                if self._buf.strip():
                    self._emit.emit(self._buf.strip())
                    self._buf = ""
        old_out, old_err = sys.stdout, sys.stderr
        proxy = _SignalLogWriter(self.progress_updated)
        try:
            sys.stdout = proxy
            sys.stderr = proxy
            try:
                import platform
                if platform.system() == 'Darwin':
                    import resource
                    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                    target_soft = max(int(soft), 10240)
                    RLIM_INFINITY = getattr(resource, "RLIM_INFINITY", (1 << 63) - 1)
                    if hard != RLIM_INFINITY and target_soft > int(hard):
                        target_soft = int(hard)
                    if target_soft > int(soft):
                        resource.setrlimit(resource.RLIMIT_NOFILE, (target_soft, hard))
                    self.progress_updated.emit(f"🔧 macOS: Zvýšen limit otevřených souborů: {soft} → {target_soft}")
            except Exception:
                pass
            generated_pdfs = generate_pdf_main(
                n=self.n,
                m=self.m,
                location_config=self.location_config,
                def_cesta_lokaci=self.location_path,
                cesta_ctyrlistky=self.clover_path,
                output_pdf=self.output_pdf,
                poznamky_dict=self.poznamky_dict,
                copy_folder=self.copy_folder,
                pages_per_pdf=self.pages_per_pdf,
                status_dict=self.status_dict,                # NOVÉ: předání stavů
                progress_callback=self.progress_updated.emit
            )
            proxy.flush()
            self.progress_updated.emit("phase_done:✅ Generování PDF dokončeno!")
            self.finished_success.emit(generated_pdfs)
        except Exception as e:
            proxy.flush()
            err = f"❌ Chyba při generování PDF: {e}"
            self.progress_updated.emit(err)
            self.finished_error.emit(str(e))
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            
# Ujistěte se, že na začátku souboru pdf_generator_window.py máte tyto importy
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence, QImage
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QApplication, QMessageBox, QRubberBand
from PySide6.QtCore import Qt, QSize, QRect, QPoint
import os
import shutil
import time
import sys
import io

# Tento blok zajistí, že aplikace nespadne, pokud chybí potřebné knihovny
try:
    from PIL import Image, ImageQt
    import piexif
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ImagePreviewDialog(QDialog):
    # Ve třídě ImagePreviewDialog
    def __init__(self, image_paths, start_index, parent=None, crop_status_dict=None):
        super().__init__(parent)
        self.setWindowTitle("Náhled fotografie")
        self.setModal(True)
        self.image_paths = image_paths
        self.current_index = start_index
        
        # NOVÉ: Převzetí slovníku pro stav ořezání
        self.crop_status = crop_status_dict if crop_status_dict is not None else {}
    
        self.rubber_band = None
        self.crop_origin = None
        self.original_pixmap = None
        self.is_moving_selection = False
        self.move_offset = QPoint()
        self.undo_backups = {}
        self.scroll_action_performed_in_gesture = False
        self.handle_size = 12
    
        self.setup_ui()
        self.shortcut_crop = QShortcut(QKeySequence("Ctrl+K"), self)
        self.shortcut_crop.activated.connect(self.crop_image)
        self.shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.shortcut_undo.activated.connect(self.undo_crop)
        self.load_current_image()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        controls_layout = QHBoxLayout()

        self.crop_button = QPushButton("✂️ Ořezat obrázek (⌘K)")
        self.crop_button.setToolTip("Přepíše původní soubor čtvercovým výřezem.\nZachovává všechna metadata.")
        self.crop_button.clicked.connect(self.crop_image)

        self.undo_button = QPushButton("↩️ Vrátit zpět (⌘Z)")
        self.undo_button.setToolTip("Vrátí poslední ořezání tohoto obrázku.")
        self.undo_button.clicked.connect(self.undo_crop)
        self.undo_button.setEnabled(False)

        controls_layout.addWidget(self.crop_button)
        controls_layout.addWidget(self.undo_button)
        main_layout.addLayout(controls_layout)

        self.image_label = QLabel("Načítání obrázku...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMouseTracking(True) # Důležité pro sledování kurzoru
        main_layout.addWidget(self.image_label)

        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 10px; color: #b0b0b0; margin-top: 5px;")
        main_layout.addWidget(self.info_label)
        
    def wheelEvent(self, event):
        """
        Zpracuje skrolování kolečkem myši nebo gestem na touchpadu pro navigaci.
        Využívá sledování fází gesta, aby se zajistil posun pouze o jeden obrázek na gesto.
        """
        phase = event.phase()
    
        # Na začátku gesta (prsty se dotknou touchpadu) resetujeme zámek.
        if phase == Qt.ScrollPhase.ScrollBegin:
            self.scroll_action_performed_in_gesture = False
            event.accept()
            return
    
        # Na konci gesta (prsty se zvednou) také resetujeme zámek.
        if phase == Qt.ScrollPhase.ScrollEnd:
            self.scroll_action_performed_in_gesture = False
            event.accept()
            return
    
        # Pokud je zámek aktivní (akce již byla v tomto gestu provedena), ignorujeme další pohyb.
        if self.scroll_action_performed_in_gesture:
            event.accept()
            return
    
        # Pro plynulá zařízení (touchpad) preferujeme pixelDelta. Pro kolečka myši použijeme angleDelta.
        delta = event.pixelDelta().y() if not event.pixelDelta().isNull() else event.angleDelta().y()
    
        action_taken = False
        # Dostatečná změna pro vyvolání akce (chrání před náhodnými mikropohyby).
        if delta < -5:  # Pohyb dolů (prsty nahoru na touchpadu) -> Další obrázek
            if self.current_index < len(self.image_paths) - 1:
                self.current_index += 1
                self.load_current_image()
                action_taken = True
        elif delta > 5:  # Pohyb nahoru (prsty dolů na touchpadu) -> Předchozí obrázek
            if self.current_index > 0:
                self.current_index -= 1
                self.load_current_image()
                action_taken = True
    
        # Pokud byla provedena akce, zamkneme možnost další akce v rámci tohoto gesta.
        if action_taken:
            self.scroll_action_performed_in_gesture = True
    
        event.accept()

    def _load_orientation_corrected_pil_image(self, path):
        if not PIL_AVAILABLE:
            return None, None, None

        pil_img = Image.open(path)
        exif_dict = None
        icc_profile = pil_img.info.get("icc_profile")

        if "exif" in pil_img.info and pil_img.info['exif']:
            try:
                exif_dict = piexif.load(pil_img.info["exif"])
                orientation = exif_dict["0th"].get(piexif.ImageIFD.Orientation, 1)
                
                if orientation > 1:
                    if   orientation == 2: pil_img = pil_img.transpose(Image.FLIP_LEFT_RIGHT)
                    elif orientation == 3: pil_img = pil_img.transpose(Image.ROTATE_180)
                    elif orientation == 4: pil_img = pil_img.transpose(Image.FLIP_TOP_BOTTOM)
                    elif orientation == 5: pil_img = pil_img.transpose(Image.TRANSPOSE)
                    elif orientation == 6: pil_img = pil_img.transpose(Image.ROTATE_270)
                    elif orientation == 7: pil_img = pil_img.transpose(Image.TRANSVERSE)
                    elif orientation == 8: pil_img = pil_img.transpose(Image.ROTATE_90)
                
                exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
            except Exception:
                exif_dict = None

        return pil_img, exif_dict, icc_profile

    def load_current_image(self):
        self.original_pixmap = self.pil_image_oriented = self.pil_exif_info = self.pil_icc_profile = None
        if self.rubber_band:
            self.rubber_band.hide()
        self.is_moving_selection = self.is_resizing_selection = False
        self.undo_button.setEnabled(self.current_index in self.undo_backups)

        if not self.image_paths or not (0 <= self.current_index < len(self.image_paths)):
            self.image_label.setText("Chyba: Neplatný index obrázku.")
            self.crop_button.setEnabled(False)
            return

        image_path = self.image_paths[self.current_index]

        if not PIL_AVAILABLE:
            self.image_label.setText("❌ Knihovny Pillow a piexif nejsou dostupné.\nNainstalujte je: pip install Pillow piexif")
            self.crop_button.setEnabled(False)
            return

        try:
            self.pil_image_oriented, self.pil_exif_info, self.pil_icc_profile = self._load_orientation_corrected_pil_image(image_path)
            if self.pil_image_oriented is None:
                raise ValueError("Nepodařilo se načíst obrázek pomocí Pillow.")
            
            q_image = ImageQt.ImageQt(self.pil_image_oriented.convert("RGBA"))
            pixmap = QPixmap.fromImage(q_image)

        except Exception as e:
            self.image_label.setText(f"❌\nNelze načíst obrázek:\n{os.path.basename(image_path)}\n{e}")
            self.crop_button.setEnabled(False)
            self.setMinimumSize(400, 200)
            return
            
        self.setWindowTitle(f"Náhled - {os.path.basename(image_path)}")
        self.info_label.setText(f"{self.current_index + 1} / {len(self.image_paths)}")
        
        self.original_pixmap = pixmap
        self.crop_button.setEnabled(True)

        screen_geometry = QApplication.primaryScreen().availableGeometry()
        max_width, max_height = screen_geometry.width() * 0.8, screen_geometry.height() * 0.8
        scaled_pixmap = pixmap.scaled(int(max_width), int(max_height), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        self.image_label.setPixmap(scaled_pixmap)
        self.resize(scaled_pixmap.width() + 40, scaled_pixmap.height() + 110)
        

    def _get_pixmap_rect_in_label(self):
        if not self.image_label.pixmap() or self.image_label.pixmap().isNull():
            return QRect()
        pm_size = self.image_label.pixmap().size()
        lbl_size = self.image_label.size()
        x = (lbl_size.width() - pm_size.width()) // 2
        y = (lbl_size.height() - pm_size.height()) // 2
        return QRect(x, y, pm_size.width(), pm_size.height())

    def _get_corner_at_pos(self, pos):
        if not self.rubber_band or not self.rubber_band.isVisible():
            return None
        
        geom = self.rubber_band.geometry()
        s = self.handle_size
        
        if QRect(geom.topLeft(), QSize(s, s)).contains(pos): return "top_left"
        if QRect(geom.topRight() - QPoint(s, 0), QSize(s, s)).contains(pos): return "top_right"
        if QRect(geom.bottomLeft() - QPoint(0, s), QSize(s, s)).contains(pos): return "bottom_left"
        if QRect(geom.bottomRight() - QPoint(s, s), QSize(s, s)).contains(pos): return "bottom_right"
        
        return None

    # Ve třídě ImagePreviewDialog
    def crop_image(self):
        if not self.original_pixmap or self.original_pixmap.isNull(): return
        if not self.rubber_band or not self.rubber_band.isVisible():
            QMessageBox.information(self, "Ořez", "Nejprve myší vyberte oblast pro ořez.")
            return
    
        try:
            from PIL import Image
            import piexif
        except ImportError as e:
            QMessageBox.critical(self, "Chybí knihovna", f"Pro ořez je vyžadována knihovna Pillow a piexif.\nChyba: {e}")
            return
    
        image_path = self.image_paths[self.current_index]
        try:
            if self.current_index not in self.undo_backups:
                backup_path = image_path + f".{int(time.time())}.bak"
                shutil.copy2(image_path, backup_path)
                self.undo_backups[self.current_index] = backup_path
        except Exception as e:
            QMessageBox.critical(self, "Chyba zálohování", f"Nepodařilo se vytvořit zálohu originálu:\n{e}")
            return
    
        selection_in_label = self.rubber_band.geometry()
        pixmap_rect_in_label = self._get_pixmap_rect_in_label()
        if pixmap_rect_in_label.width() <= 0 or pixmap_rect_in_label.height() <= 0:
            QMessageBox.critical(self, "Chyba výpočtu", "Nelze určit rozměry zobrazeného obrázku pro ořez.")
            return
    
        selection_on_pixmap = selection_in_label.translated(-pixmap_rect_in_label.topLeft())
        x_ratio = self.original_pixmap.width() / pixmap_rect_in_label.width()
        y_ratio = self.original_pixmap.height() / pixmap_rect_in_label.height()
        left = selection_on_pixmap.left() * x_ratio
        top = selection_on_pixmap.top() * y_ratio
        right = (selection_on_pixmap.left() + selection_on_pixmap.width()) * x_ratio
        bottom = (selection_on_pixmap.top() + selection_on_pixmap.height()) * y_ratio
        crop_box = (max(0, int(left)), max(0, int(top)), min(self.original_pixmap.width(), int(right)), min(self.original_pixmap.height(), int(bottom)))
    
        try:
            with Image.open(image_path) as pil_img:
                params = {"quality": 95}
                if "exif" in pil_img.info:
                    try:
                        exif_dict = piexif.load(pil_img.info["exif"])
                        if piexif.ImageIFD.Orientation in exif_dict["0th"]: exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
                        exif_dict["Exif"].pop(piexif.ExifIFD.PixelXDimension, None)
                        exif_dict["Exif"].pop(piexif.ExifIFD.PixelYDimension, None)
                        params["exif"] = piexif.dump(exif_dict)
                    except Exception:
                        params["exif"] = pil_img.info["exif"]
                if "icc_profile" in pil_img.info:
                    params["icc_profile"] = pil_img.info["icc_profile"]
                
                cropped_pil_img = pil_img.crop(crop_box)
                cropped_pil_img.save(image_path, **params)
                
                if sys.platform == 'darwin' and self.current_index in self.undo_backups:
                    backup_for_attrs = self.undo_backups[self.current_index]
                    try:
                        xattrs = {name: os.getxattr(backup_for_attrs, name) for name in os.listxattr(backup_for_attrs)}
                        for name, value in xattrs.items():
                            try: os.setxattr(image_path, name, value)
                            except OSError: continue
                    except (OSError, AttributeError): pass
    
            self.rubber_band.hide()
            self.undo_button.setEnabled(True)
            
            # NOVÉ: Aktualizace stavu ořezání
            photo_number_str = os.path.basename(image_path).split('+')[0]
            self.crop_status[photo_number_str] = True
            
            self.load_current_image()
        except Exception as e:
            QMessageBox.critical(self, "Chyba při ořezu", f"Nepodařilo se oříznout a uložit obrázek:\n{e}")
            self.undo_crop()

    # Ve třídě ImagePreviewDialog
    def undo_crop(self):
        backup_path = self.undo_backups.get(self.current_index)
        if not backup_path or not os.path.exists(backup_path):
            return
    
        current_image_path = self.image_paths[self.current_index]
        try:
            shutil.copy2(backup_path, current_image_path)
            self.undo_button.setEnabled(False)
            
            # NOVÉ: Aktualizace stavu ořezání
            photo_number_str = os.path.basename(current_image_path).split('+')[0]
            if photo_number_str in self.crop_status:
                self.crop_status[photo_number_str] = False
                
            self.load_current_image()
        except Exception as e:
            QMessageBox.critical(self, "Chyba při obnově", f"Nepodařilo se obnovit obrázek ze zálohy:\n{e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.image_label.underMouse():
            pixmap_rect = self._get_pixmap_rect_in_label()
            pos_in_label = self.image_label.mapFrom(self, event.pos())
            
            if not pixmap_rect.contains(pos_in_label):
                super().mousePressEvent(event)
                return
            
            corner = self._get_corner_at_pos(pos_in_label)
            if self.rubber_band and self.rubber_band.isVisible() and corner:
                self.is_resizing_selection = True
                self.resize_corner = corner
            elif self.rubber_band and self.rubber_band.isVisible() and self.rubber_band.geometry().contains(pos_in_label):
                self.is_moving_selection = True
                self.move_offset = pos_in_label - self.rubber_band.geometry().topLeft()
            else:
                self.crop_origin = event.pos()
                if not self.rubber_band:
                    self.rubber_band = QRubberBand(QRubberBand.Rectangle, self.image_label)
                self.rubber_band.setGeometry(QRect(pos_in_label, QSize()))
                self.rubber_band.show()
                
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pixmap_rect = self._get_pixmap_rect_in_label()
        if not pixmap_rect.isValid():
            super().mouseMoveEvent(event)
            return

        pos_in_label = self.image_label.mapFrom(self, event.pos())
        
        # Změna kurzoru při najetí na rohy
        if not (self.is_moving_selection or self.is_resizing_selection or self.crop_origin):
            corner = self._get_corner_at_pos(pos_in_label)
            if corner in ("top_left", "bottom_right"):
                self.image_label.setCursor(Qt.SizeFDiagCursor)
            elif corner in ("top_right", "bottom_left"):
                self.image_label.setCursor(Qt.SizeBDiagCursor)
            else:
                self.image_label.setCursor(Qt.ArrowCursor)

        if self.is_resizing_selection:
            current_geom = self.rubber_band.geometry()
            new_rect = QRect(current_geom)

            if self.resize_corner == "bottom_right":
                fixed_point = current_geom.topLeft()
                side = max(pos_in_label.x() - fixed_point.x(), pos_in_label.y() - fixed_point.y())
                new_rect.setSize(QSize(side, side))
            elif self.resize_corner == "top_left":
                fixed_point = current_geom.bottomRight()
                side = max(fixed_point.x() - pos_in_label.x(), fixed_point.y() - pos_in_label.y())
                new_rect.setTopLeft(QPoint(fixed_point.x() - side, fixed_point.y() - side))
            elif self.resize_corner == "top_right":
                fixed_point = current_geom.bottomLeft()
                side = max(pos_in_label.x() - fixed_point.x(), fixed_point.y() - pos_in_label.y())
                new_rect.setTopRight(QPoint(fixed_point.x() + side, fixed_point.y() - side))
            elif self.resize_corner == "bottom_left":
                fixed_point = current_geom.topRight()
                side = max(fixed_point.x() - pos_in_label.x(), pos_in_label.y() - fixed_point.y())
                new_rect.setBottomLeft(QPoint(fixed_point.x() - side, fixed_point.y() + side))
            
            self.rubber_band.setGeometry(new_rect.intersected(pixmap_rect))

        elif self.is_moving_selection:
            new_top_left = pos_in_label - self.move_offset
            moved_rect = QRect(new_top_left, self.rubber_band.size())
            # Omezení pohybu v rámci hranic pixmapy
            moved_rect.moveLeft(max(pixmap_rect.left(), moved_rect.left()))
            moved_rect.moveTop(max(pixmap_rect.top(), moved_rect.top()))
            moved_rect.moveRight(min(pixmap_rect.right(), moved_rect.right()))
            moved_rect.moveBottom(min(pixmap_rect.bottom(), moved_rect.bottom()))
            self.rubber_band.setGeometry(moved_rect)
        
        elif self.crop_origin:
            start_pos_in_label = self.image_label.mapFrom(self, self.crop_origin)
            rect = QRect(start_pos_in_label, pos_in_label).normalized()
            side = max(rect.width(), rect.height())
            
            top_left = rect.topLeft()
            if top_left.x() + side > pixmap_rect.right(): top_left.setX(pixmap_rect.right() - side)
            if top_left.y() + side > pixmap_rect.bottom(): top_left.setY(pixmap_rect.bottom() - side)
            
            final_rect = QRect(top_left, QSize(side, side))
            self.rubber_band.setGeometry(final_rect.intersected(pixmap_rect))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.crop_origin = None
            self.is_moving_selection = False
            self.is_resizing_selection = False
            self.resize_corner = None
            self.image_label.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Space, Qt.Key_Escape): self.accept()
        elif key == Qt.Key_Down:
            if self.current_index < len(self.image_paths) - 1:
                self.current_index += 1; self.load_current_image()
        elif key == Qt.Key_Up:
            if self.current_index > 0:
                self.current_index -= 1; self.load_current_image()
        else: super().keyPressEvent(event)

    def closeEvent(self, event):
        # Automatický úklid všech vytvořených záložních souborů.
        for backup_path in self.undo_backups.values():
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    # Ignorujeme chyby při zavírání, abychom nezablokovali aplikaci.
                    pass
        super().closeEvent(event)
        
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self._editor.lineNumberAreaPaintEvent(event)


class JSONCodeEditor(QPlainTextEdit):
    """QPlainTextEdit s levým sloupcem čísel řádků a vložením 2 mezer na Tab."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lineNumberArea = LineNumberArea(self)
        # Signály pro udržení šířky a přemalování
        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)
        # Výchozí font konzistentní s ostatními editory
        self.setFont(QFont("Consolas", 11))
        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()
        # Vypnutí zalamování řádků (JSON je přehlednější po řádcích)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    # Šířka levého sloupce podle počtu číslic
    def lineNumberAreaWidth(self):
        digits = len(str(max(1, self.blockCount())))
        space = 3 + self.fontMetrics().horizontalAdvance('9') * digits
        return space + 6  # malé odsazení

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self._lineNumberArea.scroll(0, dy)
        else:
            self._lineNumberArea.update(0, rect.y(), self._lineNumberArea.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._lineNumberArea.setGeometry(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height())

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self._lineNumberArea)
        # Dark theme kompatibilní barvy (drží se stávajícího vzhledu)
        bg = QColor("#2b2b2b")
        fg = QColor("#b0b0b0")
        painter.fillRect(event.rect(), bg)

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(blockNumber + 1)
                painter.setPen(fg)
                fm = self.fontMetrics()
                x = self._lineNumberArea.width() - fm.horizontalAdvance(number) - 3
                painter.drawText(x, bottom - fm.descent(), number)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            blockNumber += 1

    def highlightCurrentLine(self):
        # Jemné zvýraznění aktuálního řádku (není agresivní, drží dark theme)
        selection = QTextEdit.ExtraSelection()
        lineColor = QColor("#303030")
        selection.format.setBackground(lineColor)
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def keyPressEvent(self, event):
        # Vloží dvě mezery místo standardního Tab
        if event.key() == Qt.Key_Tab and not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            self.insertPlainText("  ")
            return
        super().keyPressEvent(event)

# FILE: gui/pdf_generator_window.py
# CLASS: AnonymPhotosWidget (NOVÁ TŘÍDA)
# UMÍSTI vedle NotesPhotosWidget / PhotosStatusWidget.
class AnonymPhotosWidget(QWidget):
    """Widget pro zobrazení fotek bez anonymizace s jedinou akcí 'Anonymizovat'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Nadpis
        label = QLabel("📸 Seznam fotek:")
        label.setStyleSheet("font-weight: bold; font-size: 12px; color: #e6e6e6;")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(label)

        # Seznam
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                color: #e6e6e6;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: monospace;
                font-size: 10px;
            }
            QListWidget::item { padding: 2px 6px; border-bottom: 1px solid #333333; }
            QListWidget::item:selected { background-color: #2a3b4f; }
        """)
        layout.addWidget(self.list_widget, stretch=1)

        # Info
        self.info_label = QLabel("Načítání...")
        self.info_label.setStyleSheet("font-size: 10px; color: #b0b0b0; font-style: italic;")
        self.info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

    # --- PUBLIC API ---
    def update_photos_list(self, folder_path, crop_status=None):
        """Aktualizuje seznam fotek, které NEJSOU v JSONu anonymizace."""
        import os, json
        self.list_widget.clear()
        if crop_status is None:
            crop_status = {}

        if not folder_path or not os.path.isdir(folder_path):
            self.list_widget.addItem("❌ Složka neexistuje nebo není zadána")
            self.info_label.setText("Zkontrolujte cestu k fotkám čtyřlístků")
            return

        try:
            files = os.listdir(folder_path)
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            photos_in_folder = set()
            invalid_files = []
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in photo_extensions:
                    try:
                        number_part = filename.split('+')[0]
                        photo_number = int(number_part)
                        photos_in_folder.add(photo_number)
                    except (ValueError, IndexError):
                        invalid_files.append(filename)

            photos_anon = self.get_anonymized_numbers()
            show = photos_in_folder - photos_anon

            if not photos_in_folder:
                self.list_widget.addItem("ℹ️ Ve složce nejsou žádné fotky čtyřlístků")
                self.info_label.setText("Složka je prázdná nebo neobsahuje platné soubory")
            elif not show:
                self.list_widget.addItem("✅ Všechny fotky jsou anonymizované")
                self.info_label.setText(f"Celkem: {len(photos_in_folder)} fotek – vše anonymizováno")
            else:
                for photo_num in sorted(show):
                    is_cropped = crop_status.get(str(photo_num), False)
                    icon = "✂️" if is_cropped else "🖼️"
                    item = QListWidgetItem(f"{icon} {photo_num}")
                    tip = "Ořezaná" if is_cropped else "Neupravená"
                    item.setToolTip(f"Fotka číslo {photo_num} ({tip})\nNení anonymizovaná.")
                    self.list_widget.addItem(item)
                self.info_label.setText(f"Bez anonymizace: {len(show)} z {len(photos_in_folder)} fotek")

            if invalid_files:
                self.list_widget.addItem("")
                self.list_widget.addItem("⚠️ Neplatné názvy souborů:")
                for invalid_file in invalid_files[:5]:
                    self.list_widget.addItem(f" {invalid_file}")
                if len(invalid_files) > 5:
                    self.list_widget.addItem(f" ... a {len(invalid_files) - 5} dalších")
        except Exception as e:
            self.list_widget.addItem(f"❌ Chyba při čtení složky: {str(e)}")
            self.info_label.setText("Chyba při analýze fotek")

    # --- INTERNÍ ---
    def show_context_menu(self, position):
        """Kontextové menu s JEDINOU akcí 'Anonymizovat'."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        photo_items = [it for it in selected_items if it.text().startswith(("🖼️", "✂️", "📷"))]
        if not photo_items:
            return

        menu = QMenu(self.list_widget)
        act = menu.addAction("🛡️ Anonymizovat")
        act.triggered.connect(lambda: self._action_anonymize(photo_items))
        menu.exec(self.list_widget.mapToGlobal(position))

    def _action_anonymize(self, photo_items):
        """Přidá vybraná čísla do JSONu anonymizace (sloučí do intervalů)."""
        import json
        from PySide6.QtWidgets import QMessageBox

        ids = []
        for it in photo_items:
            try:
                ids.append(int(it.text().split()[-1]))
            except Exception:
                continue
        if not ids:
            QMessageBox.information(self, "Anonymizovat", "Ve výběru nebyla rozpoznána žádná čísla.")
            return

        win = self.window()
        if win is None or not hasattr(win, "anonym_config_text"):
            QMessageBox.warning(self, "Anonymizovat", "Nenalezen editor '🛡️ JSON anonymizace'.")
            return

        # Načti JSON
        try:
            raw = win.anonym_config_text.toPlainText() or "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Kořen JSONu musí být objekt ({}).")
        except Exception as e:
            QMessageBox.warning(self, "Anonymizovat", f"Editor '🛡️ JSON anonymizace' obsahuje neplatný JSON.\n{e}")
            return

        # Vezmi aktuální pole pro klíč "ANONYMIZOVANE"
        arr = data.get("ANONYMIZOVANE", [])
        existing = self._expand_intervals(arr)
        all_numbers = existing.union(set(ids))
        intervals = self._merge_to_intervals(sorted(all_numbers))
        data["ANONYMIZOVANE"] = intervals

        # Zapiš zpět (kompaktní formát jako jinde)
        try:
            formatted = self._format_json_compact_fixed(data)
        except Exception:
            formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        win.anonym_config_text.setPlainText(formatted)

        # Refresh seznamu
        try:
            win.update_anonym_photos_list()
        except Exception:
            pass

        QMessageBox.information(self, "Anonymizovat", f"Anonymizováno: {len(ids)} položek.")

    # === Pomocné metody: práce s intervaly a formátování (lokální kopie, žádné zásahy do ostatních tříd) ===
    def _expand_intervals(self, intervals_list) -> set[int]:
        numbers = set()
        for item in intervals_list or []:
            s = str(item).strip()
            if not s:
                continue
            if '-' in s:
                try:
                    a, b = s.split('-', 1)
                    ai = int(a.strip()); bi = int(b.strip())
                    if ai > bi: ai, bi = bi, ai
                    numbers.update(range(ai, bi + 1))
                except Exception:
                    continue
            else:
                if s.isdigit():
                    numbers.add(int(s))
        return numbers

    def _merge_to_intervals(self, numbers) -> list[str]:
        if not numbers:
            return []
        numbers = sorted(set(numbers))
        out = []
        start = end = numbers[0]
        for n in numbers[1:]:
            if n == end + 1:
                end = n
            else:
                out.append(str(start) if start == end else f"{start}-{end}")
                start = end = n
        out.append(str(start) if start == end else f"{start}-{end}")
        return out

    def _format_json_compact_fixed(self, data: dict) -> str:
        import json
        if not data:
            return "{}"
        keys = list(data.keys())
        keys.sort(key=lambda x: str(x))
        max_key_len = max(len(f'"{k}":') for k in keys)
        lines = ["{"]
        for i, k in enumerate(keys):
            v = data[k]
            v_json = json.dumps(v, ensure_ascii=False, separators=(',', ' '))
            comma = "," if i < len(keys) - 1 else ""
            key_pad = f'"{k}":'.ljust(max_key_len + 2)
            lines.append(f"  {key_pad} {v_json}{comma}")
        lines.append("}")
        return "\n".join(lines)

    def get_anonymized_numbers(self) -> set[int]:
        """Vrátí množinu čísel, která JSOU anonymizovaná podle editoru v okně."""
        import json
        win = self.window()
        if win is None or not hasattr(win, "anonym_config_text"):
            return set()
        try:
            raw = win.anonym_config_text.toPlainText().strip()
            if not raw:
                return set()
            data = json.loads(raw)
            if not isinstance(data, dict):
                return set()
            arr = data.get("ANONYMIZOVANE", [])
            return self._expand_intervals(arr)
        except Exception:
            return set()
        
# FILE: gui/pdf_generator_window.py
# CLASS: NotesPhotosWidget (NOVÁ TŘÍDA)
# UMÍSTI vedle PhotosStatusWidget (stejná úroveň). Styl a logika výpisu převzata,
# kontextové menu obsahuje JEDINOU akci „📝 Zapsat poznámku“.
class NotesPhotosWidget(QWidget):
    """Widget pro zobrazení fotek bez zapsané Nastavení poznámek s jedinou akcí 'Zapsat poznámku'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Nadpis
        label = QLabel("📸 Seznam fotek:")
        label.setStyleSheet("font-weight: bold; font-size: 12px; color: #e6e6e6;")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(label)

        # Seznam fotek s multi-select
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)

        # Kontextové menu
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)

        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                color: #e6e6e6;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: monospace;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 2px 6px;
                border-bottom: 1px solid #333333;
            }
            QListWidget::item:selected {
                background-color: #2a3b4f;
            }
        """)
        layout.addWidget(self.list_widget, stretch=1)

        # Info label
        self.info_label = QLabel("Načítání...")
        self.info_label.setStyleSheet("font-size: 10px; color: #b0b0b0; font-style: italic;")
        self.info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

    # --- PUBLIC API ---
    def update_photos_list(self, folder_path, crop_status=None):
        """Aktualizuje seznam fotek BEZ poznámky (stejná logika čtení složky jako ve 'Stavech')."""
        import os
        self.list_widget.clear()
        if crop_status is None:
            crop_status = {}

        if not folder_path or not os.path.isdir(folder_path):
            self.list_widget.addItem("❌ Složka neexistuje nebo není zadána")
            self.info_label.setText("Zkontrolujte cestu k fotkám čtyřlístků")
            return

        try:
            files = os.listdir(folder_path)
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            photos_in_folder = set()
            invalid_files = []
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in photo_extensions:
                    try:
                        number_part = filename.split('+')[0]
                        photo_number = int(number_part)
                        photos_in_folder.add(photo_number)
                    except (ValueError, IndexError):
                        invalid_files.append(filename)

            photos_with_notes = self.get_numbers_with_notes()
            photos_without_note = photos_in_folder - photos_with_notes

            if not photos_in_folder:
                self.list_widget.addItem("ℹ️ Ve složce nejsou žádné fotky čtyřlístků")
                self.info_label.setText("Složka je prázdná nebo neobsahuje platné soubory")
            elif not photos_without_note:
                self.list_widget.addItem("✅ Všechny fotky mají poznámku")
                self.info_label.setText(f"Celkem: {len(photos_in_folder)} fotek – všechny mají poznámku")
            else:
                for photo_num in sorted(photos_without_note):
                    is_cropped = crop_status.get(str(photo_num), False)
                    icon = "✂️" if is_cropped else "🖼️"
                    item = QListWidgetItem(f"{icon} {photo_num}")
                    tip = "Ořezaná" if is_cropped else "Neupravená"
                    item.setToolTip(f"Fotka číslo {photo_num} ({tip})\nNemá zapsanou poznámku.")
                    self.list_widget.addItem(item)
                self.info_label.setText(f"Bez Nastavení poznámek: {len(photos_without_note)} z {len(photos_in_folder)} fotek")

            if invalid_files:
                self.list_widget.addItem("")
                self.list_widget.addItem("⚠️ Neplatné názvy souborů:")
                for invalid_file in invalid_files[:5]:
                    self.list_widget.addItem(f" {invalid_file}")
                if len(invalid_files) > 5:
                    self.list_widget.addItem(f" ... a {len(invalid_files) - 5} dalších")
        except Exception as e:
            self.list_widget.addItem(f"❌ Chyba při čtení složky: {str(e)}")
            self.info_label.setText("Chyba při analýze fotek")

    # --- INTERNÍ ---
    def show_context_menu(self, position):
        """Kontextové menu s JEDINOU akcí 'Zapsat poznámku' (funguje 1:1 jako ve Web fotky)."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return

        # Pouze položky reprezentující fotky
        photo_items = [it for it in selected_items if it.text().startswith(("🖼️", "✂️", "📷"))]
        if not photo_items:
            return

        menu = QMenu(self.list_widget)
        act_note = menu.addAction("📝 Zapsat poznámku")
        act_note.triggered.connect(lambda: self._action_write_note(photo_items))
        menu.exec(self.list_widget.mapToGlobal(position))

    def _action_write_note(self, photo_items):
        """Otevře modální vstup a zapíše poznámku do <PdfGeneratorWindow>.notes_text pro vybraná čísla."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        # Sesbírej čísla
        ids = []
        for it in photo_items:
            try:
                num = int(it.text().split()[-1])
                ids.append(str(num))
            except Exception:
                continue

        if not ids:
            QMessageBox.information(self, "Zapsat poznámku", "Ve výběru nebyla rozpoznána žádná čísla.")
            return

        # Dialog
        note_text, ok = QInputDialog.getMultiLineText(
            self, "Zapsat poznámku", "Poznámka pro vybrané položky:", ""
        )
        if not ok:
            return
        note_text = (note_text or "").strip()
        if not note_text:
            QMessageBox.information(self, "Zapsat poznámku", "Poznámka je prázdná – nic se nezapsalo.")
            return

        # Editor v hlavním okně
        win = self.window()
        if win is None or not hasattr(win, "notes_text"):
            QMessageBox.warning(self, "Zapsat poznámku", "Nenalezen editor '📝 JSON Nastavení poznámek'.")
            return

        try:
            raw = win.notes_text.toPlainText() or "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Kořen JSONu musí být objekt ({}).")
        except Exception as e:
            QMessageBox.warning(self, "Zapsat poznámku", f"Editor '📝 JSON Nastavení poznámek' obsahuje neplatný JSON.\n{e}")
            return

        # Zapiš poznámku pro všechna čísla
        for cid in ids:
            data[str(cid)] = note_text

        # Formátování: preferuj projektový formatter, jinak kompaktní fallback
        try:
            formatted = self.format_json_compact_fixed(data)
        except Exception:
            formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

        win.notes_text.setPlainText(formatted)

        # Refresh pravého seznamu + případné globální refreshe
        try:
            self.update_photos_list(win.edit_clover_path.text().strip(), getattr(win, 'crop_status', {}))
        except Exception:
            pass
        try:
            win.update_missing_photos_list()
        except Exception:
            pass

        QMessageBox.information(self, "Zapsat poznámku", f"Zapsána poznámka pro {len(ids)} položek.")

    def get_numbers_with_notes(self) -> set[int]:
        """Vrátí množinu čísel, která MAJÍ poznámku v editoru notes_text."""
        win = self.window()
        if win is None or not hasattr(win, "notes_text"):
            return set()
        try:
            raw = win.notes_text.toPlainText().strip()
            if not raw:
                return set()
            data = json.loads(raw)
            if not isinstance(data, dict):
                return set()
            out = set()
            for k in data.keys():
                try:
                    out.add(int(str(k).strip()))
                except Exception:
                    continue
            return out
        except Exception:
            return set()

    # Reuse stejného formátu jako PhotosStatusWidget (bez závislosti na main window)
    def format_json_compact_fixed(self, data):
        """Formátuje JSON v kompaktním stylu – každý klíč na jeden řádek se zarovnáním."""
        if not data:
            return "{}"
        lines = ["{"]
        keys_list = list(data.keys())
        keys_list.sort(key=lambda x: (str(x)))
        max_key_len = max(len(f'"{key}":') for key in keys_list)
        for i, key in enumerate(keys_list):
            value = data[key]
            value_json = json.dumps(value, ensure_ascii=False, separators=(',', ' '))
            comma = "," if i < len(keys_list) - 1 else ""
            key_padded = f'"{key}":'.ljust(max_key_len + 2)
            lines.append(f"  {key_padded} {value_json}{comma}")
        lines.append("}")
        return "\n".join(lines)        
        
class PhotosStatusWidget(QWidget):
    """Widget pro zobrazení fotek ze složky čtyřlístků s možností přiřazování stavů"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Nadpis
        label = QLabel("📸 Seznam fotek:")
        label.setStyleSheet("font-weight: bold; font-size: 12px; color: #e6e6e6;")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(label)

        # Seznam fotek s multi-select
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)

        # Kontextové menu
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                color: #e6e6e6;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: monospace;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 2px 6px;
                border-bottom: 1px solid #333333;
            }
            QListWidget::item:selected {
                background-color: #2a3b4f;
            }
        """)

        layout.addWidget(self.list_widget, stretch=1)

        # Info label
        self.info_label = QLabel("Načítání...")
        self.info_label.setStyleSheet("font-size: 10px; color: #b0b0b0; font-style: italic;")
        self.info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

    def show_context_menu(self, position):
        """Zobrazí kontextové menu s dostupnými stavy s hezkými ikonkami"""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
    
        # Filtruj pouze fotky (ne chybové zprávy)
        photo_items = []
        for item in selected_items:
            # OPRAVA: Zkontroluj všechny možné ikony fotek
            if item.text().startswith(("🖼️", "✂️", "📷")):
                photo_items.append(item)
    
        if not photo_items:
            return
    
        # Získej dostupné stavy z JSON konfigurace
        available_states = self.get_available_states()
    
        if not available_states:
            # Pokud nejsou žádné stavy, nabídni vytvoření nového
            menu = QMenu(self.list_widget)
            no_states_action = menu.addAction("⚠️ Nejsou definované žádné stavy")
            no_states_action.setEnabled(False)
            menu.addSeparator()
            add_bezfotky_action = menu.addAction("➕ Přidat BEZFOTKY stav")
            add_bezfotky_action.triggered.connect(lambda: self.assign_to_state(photo_items, "BEZFOTKY"))
            menu.exec(self.list_widget.mapToGlobal(position))
            return
    
        # Definice ikon a tooltipů pro každý stav
        state_config = {
            "BEZFOTKY": {
                "icon": "📷",
                "tooltip": "Označit jako BEZFOTKY - fotka nebyla pořízena"
            },
            "DAROVANY": {
                "icon": "🎁",
                "tooltip": "Označit jako DAROVANY - čtyřlístek byl darován"
            },
            "ZTRACENY": {
                "icon": "❌",
                "tooltip": "Označit jako ZTRACENY - čtyřlístek se ztratil"
            },
            "BEZGPS": {  # NOVÉ: Přidán stav BEZGPS
                "icon": "📍",
                "tooltip": "Označit jako BEZGPS - fotka nemá GPS souřadnice"
            }
        }
    
        menu = QMenu(self.list_widget)
        menu.setTitle(f"Přiřadit stav k {len(photo_items)} fotkám")
    
        # Přidej akce pro každý dostupný stav s hezkými ikonkami
        for state in sorted(available_states):
            if state in state_config:
                config = state_config[state]
                action_text = f"{config['icon']} {state}"
                action = menu.addAction(action_text)
                action.setToolTip(config['tooltip'])
            else:
                # Fallback pro neznámé stavy
                action = menu.addAction(f"📋 {state}")
                action.setToolTip(f"Označit jako {state}")
    
            action.triggered.connect(lambda checked, s=state: self.assign_to_state(photo_items, s))
    
        menu.exec(self.list_widget.mapToGlobal(position))

    def get_available_states(self):
        """Získá seznam dostupných stavů - kombinace předdefinovaných stavů a stavů z JSON"""
        # Předdefinované povolené stavy z kódu
        ALLOWED_STATES = {"BEZFOTKY", "DAROVANY", "ZTRACENY", "BEZGPS"}
        
        main_window = self.find_main_window()
        if not main_window:
            return ALLOWED_STATES
        
        try:
            config_text = main_window.status_config_text.toPlainText().strip()
            if not config_text:
                # Pokud není JSON, vracíme pouze povolené stavy
                return ALLOWED_STATES
            
            data = json.loads(config_text)
            if isinstance(data, dict):
                # Vracíme sjednocení klíčů z JSON a povolených stavů
                json_states = set(data.keys())
                # Filtrujeme pouze platné stavy z JSON
                valid_json_states = json_states.intersection(ALLOWED_STATES)
                return ALLOWED_STATES.union(valid_json_states)
            else:
                return ALLOWED_STATES
        except json.JSONDecodeError:
            # Pokud je JSON neplatný, vracíme povolené stavy
            return ALLOWED_STATES

    # FILE: gui/pdf_generator_window.py
    # CLASS: PhotosStatusWidget
    # FUNCTION: assign_to_state
    # ÚPRAVA: Po přiřazení stavu zobraz modální zápis Nastavení poznámek nejen pro "DAROVANY",
    #         ale i pro "BEZFOTKY". Jinak beze změn.
    
    def assign_to_state(self, photo_items, state_name):
        """Přiřadí vybrané fotky k zadanému stavu; pro 'DAROVANY' a 'BEZFOTKY' následně vyžádá a zapíše poznámku."""
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        import json
    
        # Získej čísla fotek
        photo_numbers = []
        for item in photo_items:
            try:
                # Extrakce čísla z textu "📷 12345" / "🖼️ 12345" / "✂️ 12345"
                number = int(item.text().split()[-1])
                photo_numbers.append(number)
            except (ValueError, IndexError):
                continue
    
        if not photo_numbers:
            return
    
        main_window = self.find_main_window()
        if not main_window:
            QMessageBox.warning(self, "Chyba", "Nepodařilo se najít hlavní okno")
            return
    
        try:
            # Převeď čísla fotek na intervaly pro zobrazení
            photo_intervals = self.merge_numbers_to_intervals(sorted(photo_numbers))
            photo_display = ", ".join(photo_intervals)
    
            # Potvrzovací dialog
            reply = QMessageBox.question(
                self,
                "Potvrzení přiřazení",
                f"Přiřadit stav '{state_name}' k {len(photo_numbers)} fotkám?\n\n"
                f"Fotky: {photo_display}",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
    
            # === ZÍSKEJ A UPRAV JSON STAVŮ ===
            config_text = main_window.status_config_text.toPlainText().strip()
            if config_text:
                data = json.loads(config_text)
            else:
                data = {}
    
            # Získej existující čísla pro daný stav
            existing_numbers = self.get_existing_numbers_for_state(data.get(state_name, []))
    
            # Slouč s novými čísly
            all_numbers = existing_numbers.union(set(photo_numbers))
    
            # Vytvoř intervaly
            intervals = self.merge_numbers_to_intervals(sorted(list(all_numbers)))
            data[state_name] = intervals
    
            # Formátuj a aktualizuj JSON stavů
            formatted_json = self.format_json_compact_fixed(data)
            main_window.status_config_text.setPlainText(formatted_json)
    
            added_count = len(set(photo_numbers) - existing_numbers)
            main_window.update_log(f"📋 Přiřazen stav '{state_name}' k {len(photo_numbers)} fotkám")
    
            # === DOPLNĚNO: pro 'DAROVANY' a 'BEZFOTKY' následně nabídni zápis Nastavení poznámek ===
            if state_name in ("DAROVANY", "BEZFOTKY"):
                dialog_title = f"Zapsat poznámku ({state_name})"
                note_text, ok = QInputDialog.getMultiLineText(
                    self,
                    dialog_title,
                    "Poznámka pro vybrané položky:",
                    ""
                )
                if ok:
                    note_text = (note_text or "").strip()
                    if note_text:
                        # Editor „📝 JSON Nastavení poznámek“ v hlavním okně
                        notes_editor = getattr(main_window, "notes_text", None)
                        if notes_editor and hasattr(notes_editor, "toPlainText") and hasattr(notes_editor, "setPlainText"):
                            try:
                                raw_notes = notes_editor.toPlainText() or "{}"
                                notes_data = json.loads(raw_notes)
                                if not isinstance(notes_data, dict):
                                    raise ValueError("Kořen JSONu musí být objekt ({}).")
                            except Exception:
                                # pokud neplatný JSON, nezapisuj poznámky, ale zachovej přiřazení stavu
                                notes_data = None
    
                            if isinstance(notes_data, dict):
                                for cid in photo_numbers:
                                    notes_data[str(int(cid))] = note_text
                                # Formátování: preferuj projektový formatter, jinak kompaktní fallback
                                try:
                                    formatted_notes = self.format_json_compact_fixed(notes_data)
                                except Exception:
                                    formatted_notes = json.dumps(notes_data, ensure_ascii=False, indent=2, sort_keys=True)
                                notes_editor.setPlainText(formatted_notes)
                                # případný refresh seznamů
                                try:
                                    main_window.update_missing_photos_list()
                                except Exception:
                                    pass
    
            # Úspěšná zpráva (původní chování zachováno)
            QMessageBox.information(
                self,
                "Úspěch",
                f"✅ Přiřazen stav '{state_name}' k {len(photo_numbers)} fotkám\n"
                f"Fotky: {photo_display}\n"
                f"Nově přidáno: {added_count} fotek\n"
                f"Výsledné intervaly: {', '.join(intervals)}"
            )
    
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{str(e)}")

    def get_existing_numbers_for_state(self, intervals_list):
        """Rozbalí seznam intervalů na množinu čísel"""
        numbers = set()
        for item in intervals_list:
            item_str = str(item).strip()
            if not item_str:
                continue
            
            if '-' in item_str:
                try:
                    start_str, end_str = item_str.split('-', 1)
                    start_num = int(start_str.strip())
                    end_num = int(end_str.strip())
                    if start_num > end_num:
                        start_num, end_num = end_num, start_num
                    numbers.update(range(start_num, end_num + 1))
                except ValueError:
                    continue
            else:
                try:
                    numbers.add(int(item_str))
                except ValueError:
                    continue
        
        return numbers

    def merge_numbers_to_intervals(self, numbers):
        """Spojí čísla do intervalů (např. [1,2,3,5] -> ["1-3", "5"])"""
        if not numbers:
            return []

        # Seřaď a odstraň duplicity
        numbers = sorted(set(numbers))
        intervals = []
        start = numbers[0]
        end = numbers[0]

        for n in numbers[1:]:
            if n == end + 1:  # Navazující číslo
                end = n
            else:  # Mezera v sekvenci
                if start == end:
                    intervals.append(str(start))
                else:
                    intervals.append(f"{start}-{end}")
                start = n
                end = n

        # Zpracování posledního intervalu
        if start == end:
            intervals.append(str(start))
        else:
            intervals.append(f"{start}-{end}")

        return intervals

    def format_json_compact_fixed(self, data):
        """Formátuje JSON v kompaktním stylu - každý stav na jeden řádek se zarovnáním"""
        if not data:
            return "{}"

        lines = ["{"]
        keys_list = list(data.keys())
        
        # Seřazení klíčů alfabeticky
        keys_list.sort()

        # Najdi nejdelší klíč pro zarovnání
        max_key_len = max(len(f'"{key}":') for key in keys_list)

        for i, key in enumerate(keys_list):
            value = data[key]
            value_json = json.dumps(value, ensure_ascii=False, separators=(',', ' '))
            comma = "," if i < len(keys_list) - 1 else ""
            
            # Zarovnání klíčů pro lepší čitelnost
            key_padded = f'"{key}":'.ljust(max_key_len + 2)
            lines.append(f"  {key_padded} {value_json}{comma}")

        lines.append("}")
        return "\n".join(lines)
    
    def get_photos_with_assigned_states(self):
        """Získá seznam fotek, které už mají přiřazený stav z JSON konfigurace"""
        # Najdi hlavní okno přes hierarchii parent widgets
        parent = self.parent()
        while parent:
            if hasattr(parent, 'status_config_text'):
                main_window = parent
                break
            parent = parent.parent()
        else:
            return set()
    
        try:
            config_text = main_window.status_config_text.toPlainText().strip()
            if not config_text:
                return set()
    
            data = json.loads(config_text)
            if not isinstance(data, dict):
                return set()
    
            photos_with_states = set()
            
            for state_name, number_list in data.items():
                if not isinstance(number_list, list):
                    continue
                    
                for item in number_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
                        
                    if '-' in item_str:
                        try:
                            start_str, end_str = item_str.split('-', 1)
                            start_num = int(start_str.strip())
                            end_num = int(end_str.strip())
                            if start_num > end_num:
                                start_num, end_num = end_num, start_num
                            for num in range(start_num, end_num + 1):
                                photos_with_states.add(num)
                        except ValueError:
                            continue
                    else:
                        try:
                            num = int(item_str)
                            photos_with_states.add(num)
                        except ValueError:
                            continue
            
            return photos_with_states
    
        except json.JSONDecodeError:
            return set()
        except Exception:
            return set()

    def find_main_window(self):
        """Najde hlavní okno aplikace"""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'status_config_text'):
                return parent
            parent = parent.parent()
        return None

    # Ve třídě PhotosStatusWidget
    def update_photos_list(self, folder_path, crop_status=None):
        """Aktualizuje seznam fotek bez přiřazeného stavu ze složky s indikací ořezu."""
        self.list_widget.clear()
        if crop_status is None:
            crop_status = {}
    
        if not folder_path or not os.path.isdir(folder_path):
            self.list_widget.addItem("❌ Složka neexistuje nebo není zadána")
            self.info_label.setText("Zkontrolujte cestu k fotkám čtyřlístků")
            return
    
        try:
            files = os.listdir(folder_path)
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            photos_in_folder = set()
            invalid_files = []
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in photo_extensions:
                    try:
                        number_part = filename.split('+')[0]
                        photo_number = int(number_part)
                        photos_in_folder.add(photo_number)
                    except (ValueError, IndexError):
                        invalid_files.append(filename)
            
            photos_with_states = self.get_photos_with_assigned_states()
            photos_without_state = photos_in_folder - photos_with_states
    
            if not photos_in_folder:
                self.list_widget.addItem("ℹ️ Ve složce nejsou žádné fotky čtyřlístků")
                self.info_label.setText("Složka je prázdná nebo neobsahuje platné soubory")
            elif not photos_without_state:
                self.list_widget.addItem("✅ Všechny fotky mají přiřazený stav")
                self.info_label.setText(f"Celkem: {len(photos_in_folder)} fotek - všechny mají stav")
            else:
                # OPRAVA: Přidání ikony podle stavu ořezu
                for photo_num in sorted(photos_without_state):
                    is_cropped = crop_status.get(str(photo_num), False)
                    icon = "✂️" if is_cropped else "🖼️"
                    item = QListWidgetItem(f"{icon} {photo_num}")
                    crop_tooltip_text = "Ořezaná" if is_cropped else "Neupravená"
                    item.setToolTip(f"Fotka číslo {photo_num} ({crop_tooltip_text})\nNemá přiřazený stav.")
                    self.list_widget.addItem(item)
                self.info_label.setText(f"Bez stavu: {len(photos_without_state)} z {len(photos_in_folder)} fotek")
    
            if invalid_files:
                self.list_widget.addItem("")
                self.list_widget.addItem("⚠️ Neplatné názvy souborů:")
                for invalid_file in invalid_files[:5]:
                    self.list_widget.addItem(f" {invalid_file}")
                if len(invalid_files) > 5:
                    self.list_widget.addItem(f" ... a {len(invalid_files) - 5} dalších")
        except Exception as e:
            self.list_widget.addItem(f"❌ Chyba při čtení složky: {str(e)}")
            self.info_label.setText("Chyba při analýze fotek")

from PySide6.QtCore import QObject, QThread, Signal

class _AnnotateWorker(QObject):
    progress = Signal(int, str, str)  # row, date_str ("" pokud nedostupné), path_str ("" pokud nedostupné)
    finished = Signal()

    def __init__(self, rows_info, source_root_str):
        super().__init__()
        self._rows_info = rows_info  # list[tuple[row:int, num:int]]
        self._source_root_str = source_root_str

    def _get_taken_datetime(self, path):
        """
        Vrátí datetime pro anotaci položek.
        1) Pokus o EXIF DateTimeOriginal (pokud dostupný).
        2) Jinak DATUM VYTVOŘENÍ SOUBORU (birthtime / getctime).
        3) Poslední fallback: mtime.
    
        Pozn.: Na macOS (a některých BSD) je k dispozici st_birthtime.
              Na Windows os.path.getctime vrací creation time.
              Na Linuxu creation time typicky není, proto padáme na mtime.
        """
        from datetime import datetime
        import os
    
        if path is None:
            return None
    
        # 1) EXIF (pokud k dispozici)
        try:
            try:
                import pillow_heif  # type: ignore
                try:
                    pillow_heif.register_heif_opener()
                except Exception:
                    pass
            except Exception:
                pass
    
            from PIL import Image, ExifTags  # type: ignore
            exif_tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            dt_tag = exif_tag_map.get("DateTimeOriginal")
            with Image.open(str(path)) as im:
                exif = im.getexif()
                if exif and dt_tag in exif:
                    raw = exif.get(dt_tag)
                    try:
                        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
                    except Exception:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                            try:
                                return datetime.strptime(str(raw), fmt)
                            except Exception:
                                continue
        except Exception:
            pass
    
        # 2) DATUM VYTVOŘENÍ SOUBORU
        try:
            st = os.stat(str(path))
            # macOS/FreeBSD: st_birthtime (skutečné creation time)
            if hasattr(st, "st_birthtime") and st.st_birthtime:
                return datetime.fromtimestamp(st.st_birthtime)
            # Windows: getctime = creation time
            return datetime.fromtimestamp(os.path.getctime(str(path)))
        except Exception:
            pass
    
        # 3) Fallback: mtime
        try:
            return datetime.fromtimestamp(os.path.getmtime(str(path)))
        except Exception:
            return None

    def run(self):
        import os
        from pathlib import Path
    
        source_root = Path(self._source_root_str) if self._source_root_str else None
        id_to_path = {}
    
        # jednorázově projdi kořenovou složku (nererekurzivně) pro rychlé mapování
        if source_root and source_root.is_dir():
            photo_ext = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            try:
                for entry in os.scandir(source_root):
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in photo_ext:
                            head = entry.name.split('+')[0]
                            if head.isdigit():
                                id_to_path[int(head)] = Path(entry.path)
            except Exception:
                pass
    
        # zpracuj jednotlivé řádky
        for row, num in self._rows_info:
            path = id_to_path.get(num)
            if path is None and source_root and source_root.is_dir():
                # opatrný fallback: rekurzivní dohledání pouze pro chybějící kusy
                try:
                    for candidate in source_root.rglob(f"{num}*"):
                        if candidate.is_file():
                            path = candidate
                            break
                except Exception:
                    path = None
    
            dt = self._get_taken_datetime(path) if path else None
            # >>> ZMĚNA: plný čas – dny, hodiny, minuty, sekundy; bez mezery (podtržítko), ať je to jeden token
            date_str = dt.strftime("%Y-%m-%d_%H:%M:%S") if dt else ""
            self.progress.emit(row, date_str, str(path) if path else "")
    
        self.finished.emit()

class MissingPhotosWidget(QWidget):
    """Widget pro zobrazení nepřiřazených fotek čtyřlístků s multi-select a kontextovým menu"""

    # Ve třídě MissingPhotosWidget
    def __init__(self, parent=None):
        super().__init__(parent)
        # ZMĚNA: Budeme si pamatovat číslo fotky, ne objekt položky
        self.last_selected_photo_num = None 
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
    
        # Nadpis - jen potřebná výška
        label = QLabel("📸 Nepřiřazené fotky čtyřlístků:")
        label.setStyleSheet("font-weight: bold; font-size: 12px; color: #e6e6e6;")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(label)
    
        # Seznam - zabere hlavní část prostoru + multi-select
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(150)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # NOVÉ: Povolit multi-select
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        # NOVÉ: Kontextové menu
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                color: #e6e6e6;
                border: 1px solid #555555;
                border-radius: 4px;
                font-family: monospace;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 2px 6px;
                border-bottom: 1px solid #333333;
            }
            QListWidget::item:selected {
                background-color: #2a3b4f;
            }
        """)
        
        layout.addWidget(self.list_widget, stretch=1)
    
        # Info label - jen potřebná výška + NOVĚ: povolit HTML
        self.info_label = QLabel("Načítání...")
        self.info_label.setStyleSheet("font-size: 10px; color: #b0b0b0; font-style: italic;")
        self.info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.info_label.setWordWrap(True)
        
        self.list_widget.keyPressEvent = self.list_key_press_event
        
        # NOVÉ: Povolit HTML formátování pro červený text
        self.info_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.info_label)
        
    def _get_taken_datetime(self, path):
        """
        Vrátí datetime pro anotaci položek.
        1) Pokus o EXIF DateTimeOriginal (pokud dostupný).
        2) Jinak DATUM VYTVOŘENÍ SOUBORU (birthtime / getctime).
        3) Poslední fallback: mtime.
    
        Pozn.: Na macOS (a některých BSD) je k dispozici st_birthtime.
              Na Windows os.path.getctime vrací creation time.
              Na Linuxu creation time typicky není, proto padáme na mtime.
        """
        from datetime import datetime
        import os
    
        if path is None:
            return None
    
        # 1) EXIF (pokud k dispozici)
        try:
            try:
                import pillow_heif  # type: ignore
                try:
                    pillow_heif.register_heif_opener()
                except Exception:
                    pass
            except Exception:
                pass
    
            from PIL import Image, ExifTags  # type: ignore
            exif_tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            dt_tag = exif_tag_map.get("DateTimeOriginal")
            with Image.open(str(path)) as im:
                exif = im.getexif()
                if exif and dt_tag in exif:
                    raw = exif.get(dt_tag)
                    try:
                        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
                    except Exception:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                            try:
                                return datetime.strptime(str(raw), fmt)
                            except Exception:
                                continue
        except Exception:
            pass
    
        # 2) DATUM VYTVOŘENÍ SOUBORU
        try:
            st = os.stat(str(path))
            # macOS/FreeBSD: st_birthtime (skutečné creation time)
            if hasattr(st, "st_birthtime") and st.st_birthtime:
                return datetime.fromtimestamp(st.st_birthtime)
            # Windows: getctime = creation time
            return datetime.fromtimestamp(os.path.getctime(str(path)))
        except Exception:
            pass
    
        # 3) Fallback: mtime
        try:
            return datetime.fromtimestamp(os.path.getmtime(str(path)))
        except Exception:
            return None
        
    def annotate_photo_items_with_taken_date(self):
        """
        Spustí neblokující anotaci položek o měsíc/datum pořízení v QThread.
        Poslední token v textu zůstává číslo fotky (kompatibilní s existující logikou).
        """
        from pathlib import Path
    
        main_window = getattr(self, "find_main_window", None)
        if callable(main_window):
            mw = self.find_main_window()
        else:
            mw = self.window()
    
        source_root = ""
        if mw is not None and hasattr(mw, "edit_clover_path"):
            source_root = (mw.edit_clover_path.text() or "").strip()
    
        # připrav seznam (row, num) pro položky, které chceme anotovat
        rows_info = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item:
                continue
            text = (item.text() or "").strip()
            # zajímají nás pouze fotky (🖼️ / ✂️)
            if not (text.startswith("🖼️") or text.startswith("✂️")):
                continue
            parts = text.split()
            if not parts:
                continue
            # pokud už obsahuje [YYYY-MM], přeskoč (abychom zbytečně neanotovali znova)
            if len(parts) >= 3 and parts[1].startswith('[') and parts[1].endswith(']'):
                continue
            # číslo fotky je poslední token
            num_str = parts[-1]
            if not num_str.isdigit():
                continue
            rows_info.append((i, int(num_str)))
    
        if not rows_info:
            return
    
        # spustíme worker v QThread
        self._annot_thread = QThread(self)
        self._annot_worker = _AnnotateWorker(rows_info, source_root)
        self._annot_worker.moveToThread(self._annot_thread)
        self._annot_thread.started.connect(self._annot_worker.run)
        self._annot_worker.progress.connect(self._on_item_annotation_progress)
        self._annot_worker.finished.connect(self._annot_thread.quit)
        self._annot_worker.finished.connect(self._annot_worker.deleteLater)
        self._annot_thread.finished.connect(self._annot_thread.deleteLater)
        self._annot_thread.start()
        
    def _on_item_annotation_progress(self, row, date_str, path_str):
        """
        Průběžně aktualizuje položku v seznamu:
        - vloží '[YYYY-MM-DD_HH:MM:SS]' PŘED číslo fotky (poslední token zůstává číslo),
        - uloží cestu do Qt.UserRole pro další akce.
        """
        from PySide6.QtCore import Qt
    
        item = self.list_widget.item(row)
        if item is None:
            return
    
        text = (item.text() or "").strip()
        parts = text.split()
        if not parts:
            return
    
        # poslední token musí zůstat číslo fotky
        num_str = parts[-1]
        if not num_str.isdigit():
            return
    
        icon = parts[0] if parts else "🖼️"
    
        # Pokud už položka má jedntokenovou anotaci v hranatých závorkách (bez mezer uvnitř),
        # přepiš ji; jinak vlož novou. (Používáme '_' místo mezery, takže je to pořád jeden token.)
        if len(parts) >= 3 and parts[1].startswith('[') and parts[1].endswith(']'):
            if date_str:
                parts[1] = f'[{date_str}]'
            new_text = " ".join(parts)
        else:
            if date_str:
                new_text = f"{icon} [{date_str}] {num_str}"
            else:
                new_text = text  # bez změny, když datum nemáme
    
        item.setText(new_text)
    
        if path_str:
            item.setData(Qt.UserRole, path_str)
    
    def read_polygon_from_metadata(self, image_path, main_window):
        """
        Robustně načte a parsuje data polygonu z metadat PNG obrázku.
        Tato verze je navržena tak, aby byla kompatibilní se způsobem,
        jakým editor v 'image_viewer.py' ukládá data do iTXt chunků.
        """
        from PIL import Image
        import json
        from pathlib import Path
    
        try:
            with Image.open(image_path) as img:
                # Zkontrolujeme, zda má obrázek 'text' atribut, kde Pillow ukládá
                # iTXt/tEXt/zTXt chunky.
                if hasattr(img, 'text') and isinstance(img.text, dict):
                    # Projdeme všechny textové chunky
                    for key, value in img.text.items():
                        # Hledáme náš specifický klíč
                        if key == 'AOI_POLYGON':
                            if main_window:
                                main_window.update_log(f"  ✔️ Nalezen polygon v .text chunk pro: {Path(image_path).name}")
                            
                            # Hodnota by měla být JSON string
                            if value and isinstance(value, str):
                                polygon_data = json.loads(value)
                                # Zkontrolujeme, zda JSON obsahuje klíč 'points'
                                if isinstance(polygon_data, dict) and 'points' in polygon_data:
                                    points = polygon_data['points']
                                    # Ujistíme se, že body tvoří validní polygon
                                    if isinstance(points, list) and len(points) >= 3:
                                        return [{'points': points}]
                
                # Záložní kontrola pro standardní .info slovník, pro jistotu
                if 'AOI_POLYGON' in img.info:
                    polygon_json_str = img.info['AOI_POLYGON']
                    if main_window:
                        main_window.update_log(f"  ✔️ Nalezen polygon v .info slovníku pro: {Path(image_path).name}")
    
                    if polygon_json_str and isinstance(polygon_json_str, str):
                        polygon_data = json.loads(polygon_json_str)
                        if isinstance(polygon_data, dict) and 'points' in polygon_data:
                            points = polygon_data['points']
                            if isinstance(points, list) and len(points) >= 3:
                                return [{'points': points}]
    
        except Exception as e:
            if main_window:
                main_window.update_log(f"  ⚠️ Varování při čtení polygonu pro {Path(image_path).name}: {e}")
        
        # Pokud se nic nepodařilo, vrátíme None
        return None


    def _piexif_dms_to_degrees(self, dms_tuple):
        """Převede GPS souřadnice z formátu piexif (tuple racionálních čísel) na desetinné stupně."""
        try:
            d = float(dms_tuple[0][0]) / float(dms_tuple[0][1])
            m = float(dms_tuple[1][0]) / float(dms_tuple[1][1])
            s = float(dms_tuple[2][0]) / float(dms_tuple[2][1])
            return d + (m / 60.0) + (s / 3600.0)
        except:
            return 0.0
        
    def calculate_distance_to_polygons(self, photo_coords, polygons):
        """
        Vypočítá vzdálenosti k více polygonům a vrátí nejlepší výsledek.
        NOVÉ: Preferuje záporné vzdálenosti (uvnitř polygonů) před kladnými.
        """
        if not polygons:
            return float('inf')
    
        best_distance = float('inf')
        
        for polygon_data in polygons:
            polygon_points = polygon_data.get('points', [])
            if not polygon_points:
                continue
                
            distance = self.calculate_distance_to_polygon(photo_coords, polygon_points)
            
            # Preferujeme záporné vzdálenosti (uvnitř polygonu)
            if distance < 0:  # Bod je uvnitř polygonu
                if best_distance >= 0:  # Dosud jsme našli jen body mimo polygony
                    best_distance = distance  # Preferujeme bod uvnitř
                else:  # Oba body jsou uvnitř polygonů
                    best_distance = max(best_distance, distance)  # Méně záporná = blíž ke středu
            elif best_distance >= 0:  # Oba body jsou mimo polygony
                best_distance = min(best_distance, distance)  # Menší kladná vzdálenost
            # Pokud best_distance < 0 a distance >= 0, necháváme best_distance (preferujeme uvnitř)
    
        return best_distance

        
    def get_photos_with_states(self):
        """Získá seznam fotek, které už mají přiřazený nějaký stav"""
        main_window = self.find_main_window()
        if not main_window or not hasattr(main_window, 'get_photo_to_state_mapping'):
            return set()
            
        photo_to_state = main_window.get_photo_to_state_mapping()
        return set(photo_to_state.keys())

    # Nahraďte metodu list_key_press_event ve třídě MissingPhotosWidget
    def list_key_press_event(self, event):
        """Handler pro stisk klávesy v seznamu fotek."""
        if event.key() == Qt.Key_Space:
            current_item = self.list_widget.currentItem()
            if current_item:
                try:
                    # Uložíme si číslo fotky, ne samotný item
                    self.last_selected_photo_num = int(current_item.text().split()[-1])
                except (ValueError, IndexError):
                    self.last_selected_photo_num = None
                
                self.show_photo_preview()
            event.accept()
        else:
            # Zavolání původního handleru pro ostatní klávesy
            QListWidget.keyPressEvent(self.list_widget, event)

    # Ve třídě MissingPhotosWidget, nahraďte metodu show_photo_preview()
    
    def show_photo_preview(self):
        """Zobrazí náhled, ořízne fotku a po zavření spolehlivě obnoví výběr a pozici v seznamu."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
    
        main_window = self.find_main_window()
        if not main_window:
            QMessageBox.warning(self, "Chyba", "Nepodařilo se najít hlavní okno aplikace.")
            return
    
        clover_path = main_window.edit_clover_path.text().strip()
        if not clover_path or not os.path.isdir(clover_path):
            QMessageBox.warning(self, "Chyba", "Cesta ke složce s fotkami není nastavena.")
            return
    
        # Sestavení seřazeného seznamu platných fotek pro navigaci v dialogu
        valid_photos = []
        photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
        try:
            files_in_dir = os.listdir(clover_path)
            photo_files_map = {int(f.split('+')[0]): os.path.join(clover_path, f)
                              for f in files_in_dir
                              if f.split('+')[0].isdigit() and os.path.splitext(f)[1].lower() in photo_extensions}
        except (OSError, ValueError):
            photo_files_map = {}
    
        # Projdeme položky v list widgetu a vytvoříme seřazený seznam cest
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            try:
                if item.text().startswith(("🖼️", "✂️")):
                    photo_num = int(item.text().split()[-1])
                    if photo_num in photo_files_map:
                        valid_photos.append((photo_num, photo_files_map[photo_num]))
            except (ValueError, IndexError):
                continue
    
        if not valid_photos:
            QMessageBox.information(self, "Náhled nenalezen", "Nebyly nalezeny žádné platné soubory pro zobrazení.")
            return
    
        # Seřadíme cesty podle čísla fotky
        ordered_photos = sorted(valid_photos, key=lambda p: p[0])
        ordered_paths = [photo[1] for photo in ordered_photos]
        ordered_numbers = [photo[0] for photo in ordered_photos]
    
        start_index = 0
        try:
            current_photo_number = int(selected_items[0].text().split()[-1])
            if current_photo_number in ordered_numbers:
                start_index = ordered_numbers.index(current_photo_number)
        except (ValueError, IndexError):
            pass
    
        # Uložíme si číslo aktuálně vybrané fotky
        self.last_selected_photo_num = ordered_numbers[start_index] if ordered_numbers else None
    
        # =================================================================
        # --- ZAČÁTEK ŘÍZENÉ SEKCE ---
        # =================================================================
        main_window.disable_photo_list_updates()
    
        dialog = ImagePreviewDialog(ordered_paths, start_index, self, crop_status_dict=main_window.crop_status)
        dialog.exec()
    
        # --- Po zavření dialogu ---
        self.list_widget.setFocus()
    
        # 1. Určíme, které číslo fotky se má po obnovení vybrat (poslední zobrazená v dialogu)
        last_viewed_index = dialog.current_index
        if 0 <= last_viewed_index < len(ordered_numbers):
            photo_num_to_restore = ordered_numbers[last_viewed_index]
        else:
            photo_num_to_restore = self.last_selected_photo_num
    
        # 2. Manuálně spustíme aktualizaci seznamu, aby se projevily změny (ikona ořezu)
        main_window.update_missing_photos_list()
        main_window.update_status_photos_list() # Pro jistotu i druhý seznam
        
        # 3. PO AKTUALIZACI najdeme položku v nově vytvořeném seznamu a vybereme ji
        if photo_num_to_restore is not None:
            photo_found_and_selected = False
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                try:
                    if item.text().endswith(f" {photo_num_to_restore}"):
                        self.list_widget.setCurrentItem(item)
                        self.list_widget.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                        photo_found_and_selected = True
                        # LOG AŽ PO ÚSPĚŠNÉM OZNAČENÍ
                        main_window.update_log(f"🎯 Označena fotka {photo_num_to_restore} v seznamu")
                        break
                except (ValueError, IndexError):
                    continue
            
            if not photo_found_and_selected:
                main_window.update_log(f"⚠️ Fotka {photo_num_to_restore} nebyla nalezena v aktualizovaném seznamu")
        
        # 4. Znovu povolíme automatické aktualizace
        main_window.enable_photo_list_updates(photo_num_to_restore)
    
        # =================================================================
        # --- KONEC ŘÍZENÉ SEKCE ---
        # =================================================================
    
    # Přidejte tuto novou pomocnou metodu do třídy MissingPhotosWidget:
    
    def _select_photo_in_list(self, photo_number):
        """Najde a označí fotku s daným číslem v seznamu."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None:
                continue
            
            try:
                # Extrakce čísla z textu položky (např. "🖼️ 12345" nebo "✂️ 12345")
                text_parts = item.text().split()
                if len(text_parts) >= 2:
                    item_photo_num = int(text_parts[-1])  # Poslední část by mělo být číslo
                    if item_photo_num == photo_number:
                        # Označení a scroll k položce
                        self.list_widget.setCurrentItem(item)
                        self.list_widget.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                        
                        # Debug log
                        main_window = self.find_main_window()
                        if main_window:
                            main_window.update_log(f"🎯 Označena fotka {photo_number} v seznamu")
                        return True
            except (ValueError, IndexError):
                continue
        
        # Pokud se nepodařilo najít fotku
        main_window = self.find_main_window()
        if main_window:
            main_window.update_log(f"⚠️ Nepodařilo se najít fotku {photo_number} v seznamu pro označení")
        return False

    def update_list_selection(self, photo_number):
        """Najde položku podle čísla fotky a vybere ji v seznamu."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.text().endswith(str(photo_number)):
                self.list_widget.setCurrentRow(i) 
                return

    def show_context_menu(self, position):
        """Zobrazí kontextové menu pro vybrané fotky v seznamu 'Analýza fotek'."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
    
        # Pouze položky, které skutečně reprezentují fotky (ikonky 🖼️ / ✂️)
        photo_items = [item for item in selected_items if item.text().startswith(("🖼️", "✂️"))]
        if not photo_items:
            return
    
        menu = QMenu(self.list_widget)
    
        # PŮVODNÍ AKCE (zachováno)
        assign_action = menu.addAction("📍 Přiřadit lokaci")
        assign_action.triggered.connect(lambda: self.assign_to_location(photo_items))
    
        recommend_action = menu.addAction("🎯 Doporučit blízké lokace")
        recommend_action.triggered.connect(lambda: self.recommend_nearby_locations(photo_items))
    
        menu.addSeparator()
    
        mark_cropped_action = menu.addAction("✂️ Označit jako ořezané")
        mark_cropped_action.triggered.connect(lambda: self.mark_photos_as_cropped(photo_items))
    
        move_action = menu.addAction("📁 Přesunout do „Ořezy“")
        move_action.triggered.connect(lambda: self.move_photos_to_orezy(photo_items))
    
        # NOVÁ AKCE (požadavek): Kopírovat do zvolené složky (přepis existujících souborů)
        copy_action = menu.addAction("📋 Kopírovat do složky…")
        copy_action.triggered.connect(lambda: self.copy_photos_to_folder(photo_items))
    
        menu.exec(self.list_widget.mapToGlobal(position))
        
    def copy_photos_to_folder(self, photo_items):
        """
        Zkopíruje vybrané fotky do uživatelem zvolené složky.
        Pokud cílový soubor existuje, je PŘEPSÁN.
        """
        from pathlib import Path
        import shutil
        import re
        from PySide6.QtCore import Qt, QDir
        from PySide6.QtWidgets import QFileDialog, QMessageBox
    
        # Najdi okno s polem pro cestu ke složce s fotkami čtyřlístků
        win = getattr(self, "get_pdf_window_parent", None)
        if callable(win):
            win = self.get_pdf_window_parent()
        else:
            win = self.window()
    
        if win is None or not hasattr(win, "edit_clover_path"):
            QMessageBox.warning(self, "Kopírovat fotky", "Nepodařilo se najít zdrojovou složku s fotkami (edit_clover_path).")
            return
    
        source_root = Path((win.edit_clover_path.text() or "").strip())
        if not source_root.is_dir():
            QMessageBox.warning(self, "Kopírovat fotky", f"Složka s fotkami neexistuje:\n{source_root}")
            return
    
        # --- DEFAULTNÍ STARTOVACÍ SLOŽKA PRO DIALOG ---
        DEFAULT_COPY_DIR = "/Users/safronus/Library/Mobile Docum...e~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Originály/"
        if hasattr(self, "_last_copy_dir") and self._last_copy_dir:
            start_dir = str(self._last_copy_dir)
        elif QDir(DEFAULT_COPY_DIR).exists():
            start_dir = DEFAULT_COPY_DIR
        else:
            start_dir = QDir.homePath()
    
        # Vyber cílovou složku
        target_dir_str = QFileDialog.getExistingDirectory(self, "Vyber cílovou složku pro kopírování", start_dir)
        if not target_dir_str:
            return
        target_dir = Path(target_dir_str)
        self._last_copy_dir = str(target_dir)
    
        # Pomocná funkce: pokusit se určit zdrojový soubor z položky seznamu
        def _extract_path(item) -> Path | None:
            # 1) Preferuj cestu uloženou v uživatelských rolích (pokud už je známa/uložena)
            for role in (Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2):
                try:
                    p = item.data(role)
                    if p:
                        p = Path(str(p))
                        if p.exists():
                            return p
                except Exception:
                    pass
    
            # 2) ToolTip může obsahovat kompletní cestu
            try:
                tip = item.toolTip()
                if isinstance(tip, str) and tip:
                    p = Path(tip)
                    if p.exists():
                        return p
            except Exception:
                pass
    
            # 3) fallback: odvození ze zdrojové složky a čísla v textu
            if not source_root.exists():
                return None
    
            # 3a) pokus: číselné ID na konci textu položky
            import re as _re
            text = item.text().strip()
            m = _re.search(r'(\d+)\s*$', text)
            cid = m.group(1) if m else None
            if not cid:
                return None
    
            # Nejprve bez rekurze
            try:
                for child in source_root.iterdir():
                    if child.is_file() and child.name.startswith(cid):
                        return child
            except Exception:
                pass
    
            # Rekurzivní fallback
            try:
                for child in source_root.rglob(f"{cid}*"):
                    if child.is_file():
                        return child
            except Exception:
                pass
    
            return None
    
        copied, failed = 0, 0
        failed_list = []
    
        for it in photo_items:
            src = _extract_path(it)
            if not src or not src.exists():
                failed += 1
                failed_list.append(it.text())
                continue
    
            dst = target_dir / src.name
            try:
                # PŘEPIS EXISTUJÍCÍHO SOUBORU
                shutil.copy2(src, dst)
    
                # === NOVĚ: Defaultní přejmenování po kopírování (stejný styl jako ve web_photos_window.py) ===
                # Pravidlo: <id_bez_nul>++++NE+.HEIC ; kolize -> _2, _3, ...
                id_str = None
                m = re.match(r'^(\d+)[_+]', src.name)      # preferovaný default: číslo na začátku před '_' nebo '+'
                if m:
                    id_str = m.group(1)
                else:
                    m2 = re.match(r'^(\d+)', src.stem)     # fallback: číslo na začátku bez ohledu na oddělovač
                    if m2:
                        id_str = m2.group(1)
    
                if id_str:
                    try:
                        id_clean = str(int(id_str))        # odstraní případné počáteční nuly
                        base = f"{id_clean}++++NE+"
                        target_renamed = target_dir / (base + ".HEIC")
    
                        if target_renamed.exists() and target_renamed != dst:
                            i_cnt = 1
                            found = None
                            while i_cnt <= 999:
                                cand = target_dir / f"{base}_{i_cnt}.HEIC"
                                if not cand.exists():
                                    found = cand
                                    break
                                i_cnt += 1
                            if found is not None:
                                target_renamed = found
    
                        if target_renamed != dst:
                            try:
                                dst.rename(target_renamed)
                            except Exception:
                                pass
                    except Exception:
                        pass
    
                copied += 1
            except Exception as e:
                failed += 1
                failed_list.append(f"{it.text()} ({e})")
    
        # Shrnutí operace
        if failed == 0:
            QMessageBox.information(self, "Kopírovat fotky", f"Hotovo. Zkopírováno: {copied} souborů.")
        else:
            detail = "\n".join(failed_list[:10])
            if failed > 10:
                detail += f"\n… a dalších {failed - 10}"
            QMessageBox.warning(self, "Kopírovat fotky",
                                f"Zkopírováno: {copied}\nNepodařilo se: {failed}\n\n{detail}")
            
    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    def remove_from_locations_by_ids(self, ids: list[str]) -> None:
        """
        Odstraní daná čísla nálezů z JSONu „Konfigurace lokací“ (včetně intervalů) a smaže prázdné lokace.
        Použije stejný editor a uložení jako zbytek okna (pokud dostupné).
        """
        import json
    
        # 1) Najdi editor „Konfigurace lokací“
        ed = None
        for name in ("ed_lokace", "ed_locations", "ed_konfigurace_lokaci"):
            ed = getattr(self, name, None)
            if ed is not None and hasattr(ed, "toPlainText") and hasattr(ed, "setPlainText"):
                break
        if ed is None:
            return  # editor nenašel -> tiše skončit
    
        raw = (ed.toPlainText() or "").strip()
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            return
    
        # 2) Pomocné lokální funkce
        def _parse_range(token: str):
            t = (str(token) if token is not None else "").strip()
            if not t or "-" not in t:
                return None
            a, b = t.split("-", 1)
            a = a.strip(); b = b.strip()
            if not (a.isdigit() and b.isdigit()):
                return None
            ai, bi = int(a), int(b)
            if ai > bi:
                ai, bi = bi, ai
            return (ai, bi)
    
        def _fmt(a: int, b: int) -> str:
            return str(a) if a == b else f"{a}-{b}"
    
        def _subtract(arr, ids_to_remove: set[int]):
            out = []
            for tok in arr:
                s = str(tok).strip()
                if not s:
                    continue
                if s.isdigit():
                    if int(s) not in ids_to_remove:
                        out.append(s)
                    continue
                rng = _parse_range(s)
                if rng is None:
                    out.append(s)  # neznámý formát necháme být
                    continue
                a, b = rng
                hits = sorted([v for v in ids_to_remove if a <= v <= b])
                if not hits:
                    out.append(_fmt(a, b))
                    continue
                cur = a
                for h in hits:
                    if cur <= h - 1:
                        out.append(_fmt(cur, h - 1))
                    cur = h + 1
                if cur <= b:
                    out.append(_fmt(cur, b))
            return out
    
        ids_int = {int(x) for x in ids if str(x).isdigit()}
        keys_to_delete = []
        for k, arr in list(data.items()):
            if isinstance(arr, list):
                new_arr = _subtract(arr, ids_int)
                if len(new_arr) == 0:
                    keys_to_delete.append(k)
                else:
                    data[k] = new_arr
        for k in keys_to_delete:
            data.pop(k, None)
    
        # 3) Zapiš zpět – preferuj projektový formatter, jinak JSON s indent
        fmt = getattr(self, "_format_singleline_dict", None)
        if callable(fmt):
            try:
                ed.setPlainText(fmt(data, sort_numeric_keys=True, align_values=True))
            except TypeError:
                ed.setPlainText(fmt(data))
        else:
            ed.setPlainText(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    
        # 4) Ulož stejným mechanismem jako zbytek okna (vezmeme první existující)
        for saver_name in ("_save_editors_to_settings", "save_settings", "save_location_config", "_save_location_config"):
            saver = getattr(self, saver_name, None)
            if callable(saver):
                try:
                    saver()
                except Exception:
                    pass
                break  
        
    # FILE: gui/pdf_generator_window.py
    # CLASS: MissingPhotosWidget
    # FUNCTION: move_photos_to_orezy
    # NAHRAĎ CELÝ OBSAH FUNKCE TOUTO VERZÍ.
    # ZMĚNA: Po úspěšném přesunu/přejmenování také volá:
    #        - self.remove_numbers_from_location_config(moved_ids)
    #        - self.remove_numbers_from_notes_config(moved_ids)
    #        - self.remove_numbers_from_states_config(moved_ids)
    from pathlib import Path
    import shutil
    
    def move_photos_to_orezy(self, photo_items):
        import re
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox
    
        target_dir = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Ořezy/")
        source_root = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/")
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "Přesun do „Ořezy“", f"Nepodařilo se vytvořit cílovou složku:\n{target_dir}\n\n{e}")
            return
    
        def _extract_path(item) -> Path | None:
            # 1) data() v běžných rolích
            for role in (Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2):
                try:
                    val = item.data(role)
                except Exception:
                    val = None
                if isinstance(val, str) and val:
                    p = Path(val)
                    if p.exists():
                        return p
    
            # 2) atribut file_path
            fp = getattr(item, "file_path", None)
            if isinstance(fp, (str, Path)):
                p = Path(fp)
                if p.exists():
                    return p
    
            # 3) tooltip
            try:
                tip = item.toolTip()
                if isinstance(tip, str) and tip:
                    p = Path(tip)
                    if p.exists():
                        return p
            except Exception:
                pass
    
            # 4) číslo z textu položky → hledej soubor začínající tímto číslem ve zdrojové složce
            raw_txt = (item.text() or "").strip()
            for pref in ("🖼️", "✂️"):
                if raw_txt.startswith(pref):
                    raw_txt = raw_txt[len(pref):].lstrip()
    
            m = re.search(r"\d+", raw_txt)
            if not m or not source_root.exists():
                return None
    
            cid = m.group(0)
    
            # Nejprve bez rekurze
            try:
                for child in source_root.iterdir():
                    if child.is_file() and child.name.startswith(cid):
                        return child
            except Exception:
                pass
    
            # Rekurzivní fallback
            try:
                for child in source_root.rglob(f"{cid}*"):
                    if child.is_file():
                        return child
            except Exception:
                pass
    
            return None
    
        moved = 0
        skipped = 0
        failed = 0
        moved_items = []
        moved_ids: list[int] = []  # čísla nálezů, které jsme úspěšně přesunuli (int)
    
        for it in photo_items:
            try:
                src = _extract_path(it)
                if src is None or not src.is_file():
                    failed += 1
                    continue
    
                dst = target_dir / src.name
                # kolize v cíli: _001.._999 — přidávej suffix jen pokud v cíli už je SOUBOR
                if dst.is_file():  # ⟵ změna z .exists() na .is_file()
                    stem, suf = dst.stem, dst.suffix
                    i = 1
                    while i <= 999:
                        cand = target_dir / f"{stem}_{i}{suf}"
                        if not cand.is_file():  # ⟵ změna z .exists() na .is_file()
                            dst = cand
                            break
                        i += 1
                    if i > 999:
                        failed += 1
                        continue
    
                # 1) Přesun
                shutil.move(str(src), str(dst))
    
                # 2) Získat číslo nálezu
                cid_val = None
                m = re.match(r"(\d+)", src.stem)
                if m:
                    cid_val = int(m.group(1))
                else:
                    raw_txt = (it.text() or "").strip()
                    for pref in ("🖼️", "✂️"):
                        if raw_txt.startswith(pref):
                            raw_txt = raw_txt[len(pref):].lstrip()
                    m = re.search(r"\d+", raw_txt)
                    if m:
                        cid_val = int(m.group(0))
    
                # 3) Přejmenování v cíli na „<číslo>++++NE+.HEIC“
                if cid_val is not None:
                    target_renamed = target_dir / f"{cid_val}++++NE+.HEIC"
                    if target_renamed.is_file():  # ⟵ změna z .exists() na .is_file()
                        base = target_renamed.stem
                        ext = target_renamed.suffix
                        i = 1
                        while i <= 999:
                            cand = target_dir / f"{base}_{i}{ext}"
                            if not cand.is_file():  # ⟵ změna z .exists() na .is_file()
                                target_renamed = cand
                                break
                            i += 1
                    try:
                        (target_dir / dst.name).rename(target_renamed)
                        dst = target_renamed
                        moved_ids.append(cid_val)
                    except Exception:
                        # ponecháme původní název, když přejmenování selže
                        pass
    
                moved += 1
                moved_items.append(it)
    
            except Exception:
                failed += 1
    
        # Odstraň přesunuté položky ze seznamu
        for it in moved_items:
            try:
                row = self.list_widget.row(it)
                self.list_widget.takeItem(row)
            except Exception:
                pass
    
        # === Odstranění čísel ze všech dotčených JSONů v aktuálním PDF okně ===
        if moved_ids:
            try:
                self.remove_numbers_from_location_config(moved_ids)
            except Exception:
                pass
            try:
                self.remove_numbers_from_notes_config(moved_ids)
            except Exception:
                pass
            try:
                self.remove_numbers_from_states_config(moved_ids)
            except Exception:
                pass
    
            # === anonymizace: odebrat čísla i z „🛡️ JSON anonymizace“
            try:
                self.remove_numbers_from_anonym_config(moved_ids)
            except Exception:
                pass
    
        QMessageBox.information(
            self,
            "Přesun do „Ořezy“",
            f"Přesunuto: {moved}\nPřeskočeno: {skipped}\nChyb: {failed}\nCíl: {target_dir}"
        )

    def remove_numbers_from_anonym_config(self, numbers: list[int]) -> None:
        """
        Odebere daná čísla z „🛡️ JSON anonymizace“.
        Editor: <PdfGeneratorWindow>.anonym_config_text (vytvořen v create_anonymization_tab)
        Intervaly v 'ANONYMIZOVANE' jsou rozšířeny a znovu složeny (stejně jako v _action_anonymize).
        Formátování: self._format_json_compact_fixed
        Refresh: window.update_anonym_photos_list() (pokud existuje)
        """
        import json
        from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
    
        window = self.window()  # rodičovské PDF okno
        if window is None:
            return
    
        editor = getattr(window, "anonym_config_text", None)
        if not isinstance(editor, (QPlainTextEdit, QTextEdit)) or not hasattr(editor, "toPlainText"):
            return
    
        raw = (editor.toPlainText() or "").strip()
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            return
        if not isinstance(data, dict):
            return
    
        # vstupní čísla
        ids = {int(n) for n in numbers if str(n).isdigit()}
        if not ids:
            return
    
        # získej stávající pole a rozšiř na množinu čísel
        intervals = data.get("ANONYMIZOVANE", [])
        try:
            existing = self._expand_intervals(intervals)
        except Exception:
            # bezpečný fallback
            existing = set()
            for tok in intervals or []:
                s = str(tok).strip()
                if not s:
                    continue
                if "-" in s:
                    try:
                        a, b = s.split("-", 1)
                        ai, bi = int(a.strip()), int(b.strip())
                        if ai > bi:
                            ai, bi = bi, ai
                        existing.update(range(ai, bi + 1))
                    except Exception:
                        pass
                elif s.isdigit():
                    existing.add(int(s))
    
        # odečti čísla a znovu slož do intervalů
        remain = sorted(existing - ids)
        try:
            merged = self._merge_to_intervals(remain)
        except Exception:
            # jednoduchý fallback
            if not remain:
                merged = []
            else:
                # sloučení sousedních hodnot
                out, start = [], remain[0]
                prev = start
                for v in remain[1:]:
                    if v == prev + 1:
                        prev = v
                    else:
                        out.append(str(start) if start == prev else f"{start}-{prev}")
                        start = prev = v
                out.append(str(start) if start == prev else f"{start}-{prev}")
                merged = out
    
        data["ANONYMIZOVANE"] = merged
    
        # zapiš zpět v kompaktním formátu
        try:
            formatted = self._format_json_compact_fixed(data)
        except Exception:
            formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        editor.setPlainText(formatted)
    
        # refresh případných navázaných seznamů
        refresher = getattr(window, "update_anonym_photos_list", None)
        if callable(refresher):
            try:
                refresher()
            except Exception:
                pass        
    # FILE: gui/pdf_generator_window.py
    # CLASS: MissingPhotosWidget
    # FUNCTION: remove_numbers_from_location_config
    # NOVÁ FUNKCE – vlož vedle assign_to_location (NIC dalšího NEMĚŇ).
    def remove_numbers_from_location_config(self, numbers: list[int]) -> None:
        """
        Odebere z „JSON konfigurace lokací“ daná čísla (včetně uvnitř intervalů) a smaže prázdné lokace.
        Používá stejné prvky jako assign_to_location:
          - editor: main_window.location_config_text
          - formátování: self.format_json_compact_fixed
          - refresh: main_window.update_missing_photos_list()
        """
        import json
    
        main_window = self.find_main_window()
        if not main_window or not hasattr(main_window, "location_config_text"):
            return
    
        editor = main_window.location_config_text
        if not hasattr(editor, "toPlainText") or not hasattr(editor, "setPlainText"):
            return
    
        raw = (editor.toPlainText() or "").strip()
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            return
        if not isinstance(data, dict):
            return
    
        ids = {int(n) for n in numbers if str(n).isdigit()}
        if not ids:
            return
    
        def _parse_range(s: str):
            s = (s or "").strip()
            if "-" not in s:
                return None
            a, b = s.split("-", 1)
            if a.strip().isdigit() and b.strip().isdigit():
                ai, bi = int(a.strip()), int(b.strip())
                if ai > bi:
                    ai, bi = bi, ai
                return ai, bi
            return None
    
        def _fmt(a: int, b: int) -> str:
            return str(a) if a == b else f"{a}-{b}"
    
        def _subtract(arr, rm: set[int]):
            out = []
            for tok in arr:
                s = str(tok).strip()
                if not s:
                    continue
                if s.isdigit():
                    if int(s) not in rm:
                        out.append(s)
                    continue
                rng = _parse_range(s)
                if rng is None:
                    out.append(s)
                    continue
                a, b = rng
                hits = sorted([v for v in rm if a <= v <= b])
                if not hits:
                    out.append(_fmt(a, b))
                    continue
                cur = a
                for h in hits:
                    if cur <= h - 1:
                        out.append(_fmt(cur, h - 1))
                    cur = h + 1
                if cur <= b:
                    out.append(_fmt(cur, b))
            return out
    
        keys_to_delete = []
        for loc_key, arr in list(data.items()):
            if isinstance(arr, list):
                new_arr = _subtract(arr, ids)
                if len(new_arr) == 0:
                    keys_to_delete.append(loc_key)
                else:
                    data[loc_key] = new_arr
        for k in keys_to_delete:
            data.pop(k, None)
    
        try:
            formatted = self.format_json_compact_fixed(data)
        except Exception:
            formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        editor.setPlainText(formatted)
    
        try:
            main_window.update_missing_photos_list()
        except Exception:
            pass
        
    # FILE: gui/pdf_generator_window.py
    # CLASS: MissingPhotosWidget
    # FUNCTION: remove_numbers_from_states_config
    # NAHRAĎ CELÝ OBSAH FUNKCE touto verzí.
    # ZMĚNA: editor hledám PŘÍMO v rodičovském PDF okně přes self.window().
    #        Používá atribut `status_config_text` vytvořený v create_status_config_tab(). Ostatní chování zachováno.
    
    def remove_numbers_from_states_config(self, numbers: list[int]) -> None:
        """
        Odebere daná čísla z „⚙️ JSON Nastavení stavů“ (samostatná čísla i uvnitř intervalů 'A-B').
        Prázdné klíče (stavy) smaže.
        Editor: <PdfGeneratorWindow>.status_config_text (viz create_status_config_tab)
        Formátování: self.format_json_compact_fixed
        Refresh: window.update_missing_photos_list() (pokud existuje)
        """
        import json
        from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
    
        window = self.window()  # <- rodičovské PDF okno
        if window is None:
            return
    
        editor = getattr(window, "status_config_text", None)
        if not isinstance(editor, (QPlainTextEdit, QTextEdit)) or not hasattr(editor, "toPlainText"):
            return
    
        raw = (editor.toPlainText() or "").strip()
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            return
        if not isinstance(data, dict):
            return
    
        ids = {int(n) for n in numbers if str(n).isdigit()}
        if not ids:
            return
    
        def _parse_range(s: str):
            s = (s or "").strip()
            if "-" not in s:
                return None
            a, b = s.split("-", 1)
            if a.strip().isdigit() and b.strip().isdigit():
                ai, bi = int(a.strip()), int(b.strip())
                if ai > bi:
                    ai, bi = bi, ai
                return ai, bi
            return None
    
        def _fmt(a: int, b: int) -> str:
            return str(a) if a == b else f"{a}-{b}"
    
        def _subtract(arr, rm: set[int]):
            out = []
            for tok in arr:
                s = str(tok).strip()
                if not s:
                    continue
                if s.isdigit():
                    if int(s) not in rm:
                        out.append(s)
                    continue
                r = _parse_range(s)
                if r is None:
                    out.append(s)
                    continue
                a, b = r
                hits = sorted([v for v in rm if a <= v <= b])
                if not hits:
                    out.append(_fmt(a, b))
                    continue
                cur = a
                for h in hits:
                    if cur <= h - 1:
                        out.append(_fmt(cur, h - 1))
                    cur = h + 1
                if cur <= b:
                    out.append(_fmt(cur, b))
            return out
    
        changed = False
        keys_to_delete = []
        for state, arr in list(data.items()):
            if isinstance(arr, list):
                new_arr = _subtract(arr, ids)
                if new_arr != arr:
                    changed = True
                if len(new_arr) == 0:
                    keys_to_delete.append(state)
                else:
                    data[state] = new_arr
        for k in keys_to_delete:
            data.pop(k, None)
            changed = True
    
        if not changed:
            return
    
        try:
            formatted = self.format_json_compact_fixed(data)
        except Exception:
            formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        editor.setPlainText(formatted)
    
        refresher = getattr(window, "update_missing_photos_list", None)
        if callable(refresher):
            try:
                refresher()
            except Exception:
                pass
        
    # FILE: gui/pdf_generator_window.py
    # CLASS: MissingPhotosWidget
    # FUNCTION: remove_numbers_from_notes_config
    # NAHRAĎ CELÝ OBSAH FUNKCE touto verzí.
    # ZMĚNA: editor hledám PŘÍMO v rodičovském PDF okně přes self.window() (spolehlivější než find_main_window).
    #        Používá atribut `notes_text` vytvořený v create_notes_tab(). Ostatní chování zachováno.
    
    def remove_numbers_from_notes_config(self, numbers: list[int]) -> None:
        """
        Odebere daná čísla z „📝 JSON poznámky“ (maže klíče = čísla nálezů).
        Editor: <PdfGeneratorWindow>.notes_text (viz create_notes_tab)
        Formátování: self.format_json_compact_fixed
        Refresh: window.update_missing_photos_list() (pokud existuje)
        """
        import json
        from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
    
        window = self.window()  # <- rodičovské PDF okno
        if window is None:
            return
    
        editor = getattr(window, "notes_text", None)
        if not isinstance(editor, (QPlainTextEdit, QTextEdit)) or not hasattr(editor, "toPlainText"):
            return
    
        raw = (editor.toPlainText() or "").strip()
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            return
        if not isinstance(data, dict):
            return
    
        ids = {str(int(n)) for n in numbers if str(n).isdigit()}
        changed = False
        for cid in list(ids):
            if cid in data:
                data.pop(cid, None)
                changed = True
    
        if not changed:
            return
    
        try:
            formatted = self.format_json_compact_fixed(data)
        except Exception:
            formatted = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        editor.setPlainText(formatted)
    
        refresher = getattr(window, "update_missing_photos_list", None)
        if callable(refresher):
            try:
                refresher()
            except Exception:
                pass

    def assign_to_location(self, photo_items):
        """Přiřadí vybrané fotky k zadané lokaci - OPRAVENO s CMD+W, prázdným polem a zobrazením intervalů"""
        # Získej čísla fotek
        photo_numbers = []
        for item in photo_items:
            try:
                # Extrakce čísla z textu "📷 12345"
                number = int(item.text().split()[-1])
                photo_numbers.append(number)
            except (ValueError, IndexError):
                continue
    
        if not photo_numbers:
            return
    
        # Převeď čísla fotek na intervaly pro zobrazení
        photo_intervals = self.merge_numbers_to_intervals(sorted(photo_numbers))
        photo_display = ", ".join(photo_intervals)
    
        # Vytvoř vlastní dialog s QLineEdit
        dialog = QDialog(self)
        dialog.setWindowTitle("Přiřadit lokaci")
        dialog.setMinimumSize(450, 200)  # Zvětšeno kvůli více textu
        
        layout = QVBoxLayout(dialog)
        
        # Hlavní popisek
        label = QLabel(f"Zadejte číslo lokace pro {len(photo_numbers)} fotek:")
        label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(label)
        
        # NOVÉ: Zobrazení intervalů fotek
        photos_label = QLabel(f"Fotky k přiřazení: {photo_display}")
        photos_label.setStyleSheet("color: #666666; font-size: 11px; margin: 5px 0px;")
        photos_label.setWordWrap(True)  # Pro dlouhé seznamy
        layout.addWidget(photos_label)
        
        # QLineEdit pro zadání lokace
        line_edit = QLineEdit()
        line_edit.setPlaceholderText("Zadejte číslo lokace (1-9999)")
        line_edit.setFocus()  # Automatické zaměření na pole
        layout.addWidget(line_edit)
        
        buttons_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Zrušit")
        
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        
        buttons_layout.addWidget(btn_ok)
        buttons_layout.addWidget(btn_cancel)
        layout.addLayout(buttons_layout)
    
        # Přidání CMD+W zkratky
        from PySide6.QtGui import QShortcut, QKeySequence
        shortcut = QShortcut(QKeySequence.Close, dialog)
        shortcut.activated.connect(dialog.reject)
        
        # Enter také potvrdí dialog
        line_edit.returnPressed.connect(dialog.accept)
    
        # Spuštění dialogu
        if dialog.exec() != QDialog.Accepted:
            return
    
        # Validace textového vstupu
        try:
            location_id = int(line_edit.text().strip())
            if location_id < 1 or location_id > 9999:
                QMessageBox.warning(self, "Chyba", "Číslo lokace musí být mezi 1 a 9999")
                return
        except (ValueError, TypeError):
            QMessageBox.warning(self, "Chyba", "Zadejte platné číslo")
            return
    
        # Zbytek kódu zůstává stejný...
        main_window = self.find_main_window()
        if not main_window:
            QMessageBox.warning(self, "Chyba", "Nepodařilo se najít hlavní okno")
            return
    
        try:
            # Získej aktuální JSON konfiguraci
            config_text = main_window.location_config_text.toPlainText().strip()
            if config_text:
                data = json.loads(config_text)
            else:
                data = {}
    
            # Přidej fotky do lokace
            loc_key = str(location_id)
            
            # Získej existující čísla v lokaci
            existing_numbers = self.get_existing_numbers_for_location(data.get(loc_key, []))
            
            # Slouč s novými čísly
            all_numbers = existing_numbers.union(set(photo_numbers))
            
            # Vytvoř intervaly
            intervals = self.merge_numbers_to_intervals(sorted(list(all_numbers)))
            
            data[loc_key] = intervals
            
            # Formátování JSON
            formatted_json = self.format_json_compact_fixed(data)
            
            main_window.location_config_text.setPlainText(formatted_json)
            
            # Aktualizuj seznam
            main_window.update_missing_photos_list()
            
            added_count = len(set(photo_numbers) - existing_numbers)
            
            # UPRAVENO: Zobrazení intervalů i v úspěšné zprávě
            QMessageBox.information(
                self,
                "Úspěch",
                f"✅ Přiřazeno {len(photo_numbers)} fotek do lokace {location_id}\n"
                f"Fotky: {photo_display}\n"  # Zobrazení intervalů
                f"Nově přidáno: {added_count} fotek\n"
                f"Výsledné intervaly v lokaci: {', '.join(intervals)}"
            )
    
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{str(e)}")

    # Nahraďte tuto metodu ve třídě MissingPhotosWidget
    
    def recommend_nearby_locations(self, photo_items):
        """
        Spustí doporučení nejbližších lokací pro vybrané fotografie.
        Celý proces je nyní opraven a správně volá interní metody.
        """
        from PySide6.QtWidgets import QProgressDialog, QMessageBox
        from PySide6.QtCore import Qt
        import re
        from pathlib import Path
    
        main_window = self.find_main_window()
        if not main_window:
            QMessageBox.critical(self, "Chyba", "Kritická chyba: Nelze najít hlavní okno aplikace.")
            return
    
        photo_numbers = []
        for item in photo_items:
            try:
                number_str = item.text().split()[-1]
                if number_str.isdigit():
                    photo_numbers.append(int(number_str))
            except (ValueError, IndexError):
                continue
    
        if not photo_numbers:
            # OPRAVA: Volání update_log pouze s jedním argumentem
            main_window.update_log("Pro doporučení nebyly vybrány žádné platné fotky.")
            return
        
        progress = QProgressDialog("Spouštím doporučení lokací...", "Zrušit", 0, 100, self)
        progress.setWindowTitle("Vyhledávání")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
    
        try:
            QApplication.processEvents()
            progress.setLabelText("Načítám GPS z fotek...")
            progress.setValue(10)
            
            photo_coords = self.get_photo_gps_coordinates(photo_numbers, main_window)
            if not photo_coords:
                progress.close()
                QMessageBox.information(self, "Chybí GPS", "Žádná z vybraných fotek neobsahuje GPS data.")
                return
    
            QApplication.processEvents()
            if progress.wasCanceled(): return
            progress.setLabelText("Analyzuji lokační mapy a polygony...")
            progress.setValue(30)
            
            location_maps_data = self.get_available_location_maps(main_window)
            
            if not location_maps_data:
                progress.close()
                QMessageBox.information(self, "Chybí mapy", "Nebyly nalezeny žádné lokační mapy pro porovnání.")
                return
    
            QApplication.processEvents()
            if progress.wasCanceled(): return
            progress.setLabelText("Počítám nejlepší shody...")
            progress.setValue(80)
    
            recommendations = self.calculate_nearest_locations(photo_coords, location_maps_data)
            
            progress.setValue(100)
            progress.close()
    
            if recommendations:
                enriched_recommendations = []
                for loc_id, filename, dist in recommendations:
                    info = next((m for m in location_maps_data if m['filename'] == filename), {})
                    if info:
                        enriched_recommendations.append((loc_id, filename, dist, info))
                
                self.show_enhanced_location_selection_dialog(photo_numbers, enriched_recommendations)
            else:
                # OPRAVA: Volání update_log pouze s jedním argumentem
                main_window.update_log("Nepodařilo se doporučit žádnou vhodnou lokaci.")
                QMessageBox.information(self, "Nenalezeno", "Pro dané fotky se nepodařilo najít žádné blízké lokace.")
    
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Chyba při doporučování", f"Došlo k neočekávané chybě:\n{str(e)}")
            # OPRAVA: Volání update_log pouze s jedním argumentem
            main_window.update_log(f"Chyba při doporučování lokací: {e}")

    # Ve třídě MissingPhotosWidget
    def mark_photos_as_cropped(self, photo_items):
        """Označí vybrané fotky jako ořezané v hlavním slovníku 'crop_status'."""
        main_window = self.find_main_window()
        if not main_window:
            QMessageBox.warning(self, "Chyba", "Nepodařilo se najít hlavní okno aplikace.")
            return
    
        updated_count = 0
        for item in photo_items:
            try:
                # Extrakce čísla fotky z textu položky (např. "🖼️ 12345")
                photo_num_str = item.text().split()[-1]
                if photo_num_str.isdigit():
                    main_window.crop_status[photo_num_str] = True
                    updated_count += 1
            except (ValueError, IndexError):
                continue
    
        if updated_count > 0:
            main_window.update_log(f"✂️ Manuálně označeno {updated_count} fotek jako ořezané.")
            
            # Po změně stavu je nutné okamžitě uložit nastavení a aktualizovat UI
            main_window.save_settings()
            main_window.update_missing_photos_list()

    def parse_location_info(self, filename):
        """Parsuje informace o lokaci z názvu souboru - ROZŠÍŘENO o debug"""
        try:
            parts = filename.split('+')
            
            location_info = {
                'id': '',
                'description': '',
                'number': '',
                'number_display': ''
            }
            
            # Debug výpis
            main_window = self.find_main_window()
            if main_window:
                main_window.update_log(f"🔍 Parsuju soubor: {filename}")
                main_window.update_log(f"📋 Části: {parts}")
            
            if len(parts) >= 1:
                location_info['id'] = parts[0]
            
            if len(parts) >= 2:
                location_info['description'] = parts[1]
            
            # Hledej 5-ti místné číslo za posledním +
            for part in reversed(parts):
                part_clean = part.split('.')[0] if '.' in part else part
                import re
                match = re.search(r'(\d{5})$', part_clean)
                if match:
                    location_info['number'] = match.group(1)
                    location_info['number_display'] = str(int(match.group(1)))
                    if main_window:
                        main_window.update_log(f"🎯 Nalezeno číslo mapy: {match.group(1)} -> {location_info['number_display']}")
                    break
            
            return location_info
            
        except Exception as e:
            main_window = self.find_main_window()
            if main_window:
                main_window.update_log(f"❌ Chyba při parsování {filename}: {e}")
            
            return {
                'id': filename.split('+')[0] if '+' in filename else filename,
                'description': 'Chyba při načítání popisu',
                'number': '',
                'number_display': ''
            }
        
    # Vložte nebo nahraďte tuto metodu ve třídě MissingPhotosWidget v souboru pdf_generator_window.py
    
    def show_enhanced_location_selection_dialog(self, photo_numbers, recommendations):
        """
        Zobrazí vylepšený dialog s doporučenými lokacemi, který lépe formátuje informace
        a vizuálně odlišuje shodu uvnitř polygonu.
        """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton, QHBoxLayout, QListWidgetItem
        from PySide6.QtCore import Qt, QSize
        from PySide6.QtGui import QFont, QAction, QKeySequence
    
        dialog = QDialog(self)
        dialog.setWindowTitle("Doporučené lokace")
        dialog.setMinimumSize(1000, 600)
        dialog.resize(1100, 650)
    
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
    
        # Zobrazení intervalů čísel fotek
        photo_intervals = self.merge_numbers_to_intervals(sorted(photo_numbers))
        photo_display = ", ".join(photo_intervals)
        if len(photo_display) > 100: # Zkrácení pro zobrazení
            photo_display = photo_display[:97] + "..."
    
        header_label = QLabel(f"🎯 Doporučené lokace pro fotky: {photo_display}")
        header_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
        header_label.setWordWrap(True)
        header_label.setToolTip(f"Všechny fotky: {', '.join(photo_intervals)}")
        layout.addWidget(header_label)
    
        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(True)
        list_widget.setUniformItemSizes(False)
        font = QFont()
        font.setFamily("Segoe UI") # Můžete změnit na jiný preferovaný font
        font.setPointSize(10)
        list_widget.setFont(font)
    
        for i, (location_id, filename, distance, location_info) in enumerate(recommendations):
            rank = i + 1
            numeric_id = self.extract_numeric_location_id_from_filename(filename)
            numeric_display = f" (ID: {numeric_id})" if numeric_id is not None else " (ID: ?)"
            
            main_text = f"{rank}. {location_info['id']}{numeric_display}"
            
            if location_info['description']:
                desc = location_info['description']
                # Jednoduché zkrácení popisu, pokud je příliš dlouhý
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                main_text += f"\n 📄 {desc}"
    
            # ====================================================================
            # ZDE JE KLÍČOVÁ ÚPRAVA PRO ZOBRAZENÍ STAVU POLYGONU
            # ====================================================================
            if distance == 0.0:
                distance_text = "UVNITŘ POLYGONU"
            else:
                distance_text = f"{distance:.2f} km"
            
            details = f"\n 📍 {distance_text}"
            # ====================================================================
    
            if location_info['number_display']:
                details += f" • Mapa číslo: {location_info['number_display']}"
    
            main_text += details
            item = QListWidgetItem(main_text)
            item.setData(Qt.UserRole, filename) # Ukládáme celý název souboru
    
            # Dynamická výška položky podle počtu řádků
            line_count = main_text.count('\n') + 1
            item.setSizeHint(QSize(-1, max(60, line_count * 20 + 10)))
    
            # Detailní tooltip
            tooltip_lines = [
                f"Textové ID: {location_id}",
                f"Číselné ID lokace: {numeric_id if numeric_id is not None else 'N/A'}",
                f"Popis: {location_info['description']}",
            ]
            if distance == 0.0:
                tooltip_lines.append("📍 Status: FOTKY JSOU UVNITŘ POLYGONU")
            else:
                tooltip_lines.append(f"Vzdálenost: {distance:.3f} km")
                
            tooltip_lines.append(f"Soubor: {filename}")
            item.setToolTip("\n".join(tooltip_lines))
    
            # Barevné odlišení nejlepších výsledků
            if i == 0:
                item.setBackground(QColor("#d4edda")) # Jemná zelená
                item.setForeground(QColor("#155724"))
            elif i < 3:
                item.setBackground(QColor("#fff3cd")) # Jemná žlutá
                item.setForeground(QColor("#856404"))
    
            list_widget.addItem(item)
    
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)
    
        # Info text pod seznamem
        info_text = f"💡 Bude přiřazeno {len(photo_numbers)} fotek."
        info_label = QLabel(info_text)
        info_label.setStyleSheet("font-style: italic; color: #666666; margin-top: 5px; font-size: 11px;")
        layout.addWidget(info_label)
    
        # Tlačítka
        buttons_layout = QHBoxLayout()
        btn_assign = QPushButton("📍 Přiřadit k vybrané lokaci")
        btn_assign.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        btn_cancel = QPushButton("❌ Zrušit")
        btn_cancel.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
    
        btn_assign.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        list_widget.itemDoubleClicked.connect(dialog.accept)
    
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_assign)
        buttons_layout.addWidget(btn_cancel)
        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)
    
        # Zkratka pro zavření okna
        close_action = QAction("Zavřít", dialog)
        close_action.setShortcut(QKeySequence.Close)
        close_action.triggered.connect(dialog.reject)
        dialog.addAction(close_action)
    
        if dialog.exec() == QDialog.Accepted:
            selected_items = list_widget.selectedItems()
            if selected_items:
                filename = selected_items[0].data(Qt.UserRole)
                self.assign_photos_to_location_by_filename(photo_numbers, filename)


    def assign_photos_to_location_by_filename(self, photo_numbers, filename):
        """Přiřadí fotky k lokaci na základě celého názvu souboru"""
        main_window = self.find_main_window()
        if not main_window:
            return
    
        try:
            main_window.update_log(f"🔄 Přiřazuji fotky {photo_numbers} k souboru '{filename}'")
            
            # Extrakce číselného ID z celého názvu souboru
            numeric_location_id = self.extract_numeric_location_id_from_filename(filename)
            
            if numeric_location_id is None:
                main_window.update_log(f"❌ Nepodařilo se najít číselné ID v souboru: {filename}")
                QMessageBox.warning(self, "Chyba", f"Nepodařilo se najít číselné ID v souboru: {filename}")
                return
    
            main_window.update_log(f"✅ Převedeno '{filename}' -> číselné ID: {numeric_location_id}")
    
            # Zbytek logiky zůstává stejný
            config_text = main_window.location_config_text.toPlainText().strip()
            data = json.loads(config_text) if config_text else {}
            
            loc_key = str(numeric_location_id)
            existing_numbers = self.get_existing_numbers_for_location(data.get(loc_key, []))
            all_numbers = existing_numbers.union(set(photo_numbers))
            intervals = self.merge_numbers_to_intervals(list(all_numbers))
            data[loc_key] = intervals
    
            formatted_json = self.format_json_compact(data)
            main_window.location_config_text.setPlainText(formatted_json)
            main_window.update_missing_photos_list()
    
            QMessageBox.information(
                self, 
                "Úspěch", 
                f"✅ Přiřazeno {len(photo_numbers)} fotek do lokace {numeric_location_id}\n"
                f"Soubor: {filename.split('+')[0]}...\n"
                f"Fotky: {', '.join(map(str, photo_numbers))}"
            )
    
        except Exception as e:
            main_window.update_log(f"❌ Chyba při přiřazování: {e}")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{str(e)}")


    def get_photo_gps_coordinates(self, photo_numbers, main_window):
        """Získá GPS souřadnice z fotek čtyřlístků"""
        import os
        from pathlib import Path
        
        clover_path = main_window.edit_clover_path.text().strip()
        if not clover_path or not os.path.isdir(clover_path):
            return []
    
        coords = []
        photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
        
        main_window.update_log(f"🔍 Hledám GPS souřadnice pro fotky: {photo_numbers}")
        
        try:
            for filename in os.listdir(clover_path):
                if Path(filename).suffix.lower() not in photo_extensions:
                    continue
                
                try:
                    # Extrakce čísla ze jména souboru
                    number_part = filename.split('+')[0]
                    photo_number = int(number_part)
                    
                    if photo_number in photo_numbers:
                        main_window.update_log(f"📷 Zpracovávám fotku {photo_number}: {filename}")
                        
                        # Čti GPS souřadnice ze souboru
                        gps_coord = self.extract_gps_from_file(os.path.join(clover_path, filename))
                        if gps_coord:
                            coords.append((photo_number, gps_coord))
                            main_window.update_log(f"✅ GPS fotky {photo_number}: {gps_coord[0]:.6f}°N, {gps_coord[1]:.6f}°E")
                        else:
                            main_window.update_log(f"❌ Nepodařilo se načíst GPS z fotky {photo_number}")
                            
                except (ValueError, IndexError):
                    continue
                    
        except Exception as e:
            main_window.update_log(f"❌ Chyba při čtení GPS souřadnic: {e}")
            
        main_window.update_log(f"📊 Nalezeno GPS souřadnic: {len(coords)} z {len(photo_numbers)} fotek")
        return coords
    
    def calculate_distance_to_polygon(self, photo_coords, polygon_points):
        """
        Vypočítá nejkratší vzdálenost od bodů fotek k polygonu.
        NOVÉ: Vrací zápornou hodnotu pro body uvnitř polygonu, kladnou pro body mimo.
        """
        import math
    
        if not polygon_points or not photo_coords:
            return float('inf')
    
        min_distance = float('inf')
        any_point_inside = False
    
        for photo_coord in photo_coords:
            _, (photo_lat, photo_lon) = photo_coord
    
            # Kontrola, zda je bod uvnitř polygonu
            is_inside = self.point_in_polygon((photo_lat, photo_lon), polygon_points)
            
            if is_inside:
                any_point_inside = True
                # Pro body uvnitř polygonu vypočítáme vzdálenost ke středu
                # a vrátíme ji jako zápornou hodnotu
                center_lat = sum(p[0] for p in polygon_points) / len(polygon_points)
                center_lon = sum(p[1] for p in polygon_points) / len(polygon_points)
                distance_to_center = self.haversine_distance(photo_lat, photo_lon, center_lat, center_lon)
                
                # Čím blíž ke středu, tím více záporná hodnota
                if distance_to_center < min_distance:
                    min_distance = distance_to_center
            else:
                # Pro body mimo polygon vypočítáme vzdálenost k nejbližší hraně
                edge_distance = float('inf')
                for i in range(len(polygon_points)):
                    p1 = polygon_points[i]
                    p2 = polygon_points[(i + 1) % len(polygon_points)]
                    distance = self.distance_point_to_line_segment(
                        (photo_lat, photo_lon), p1, p2
                    )
                    edge_distance = min(edge_distance, distance)
                
                min_distance = min(min_distance, edge_distance)
    
        # Vrátit zápornou hodnotu pro body uvnitř, kladnou pro body mimo
        return -min_distance if any_point_inside else min_distance

# Nahraďte tuto metodu ve třídě MissingPhotosWidget v pdf_generator_window.py

    def point_in_polygon(self, point, polygon):
        """
        Spolehlivý Ray-Casting algoritmus pro zjištění, zda je GPS bod uvnitř polygonu.
        Tato verze je matematicky korektní pro geografické souřadnice.
        """
        lat, lon = point
        num_vertices = len(polygon)
        
        if num_vertices < 3:
            return False
            
        inside = False
        
        # Vezmeme první bod polygonu
        p1_lat, p1_lon = polygon[0]
        
        # Projdeme všechny hrany polygonu
        for i in range(1, num_vertices + 1):
            p2_lat, p2_lon = polygon[i % num_vertices]
            
            # Zkontrolujeme, zda horizontální "paprsek" z našeho bodu protíná hranu
            if lon > min(p1_lon, p2_lon):
                if lon <= max(p1_lon, p2_lon):
                    if lat <= max(p1_lat, p2_lat):
                        # Vypočítáme průsečík paprsku s hranou
                        if p1_lon != p2_lon:
                            lat_intersection = (lon - p1_lon) * (p2_lat - p1_lat) / (p2_lon - p1_lon) + p1_lat
                        
                        # Pokud je náš bod pod průsečíkem, došlo k protnutí
                        if p1_lon == p2_lon or lat <= lat_intersection:
                            inside = not inside
                            
            # Posuneme se na další hranu
            p1_lat, p1_lon = p2_lat, p2_lon
            
        return inside

    def distance_to_polygon(self, point, polygon):
        """
        Vypočítá nejkratší vzdálenost od GPS bodu k polygonu v kilometrech.
        1. Pokud je bod uvnitř, vrátí 0.0.
        2. Pokud je vně, vypočítá vzdálenost k nejbližší hraně.
    
        Tato metoda používá lokální aproximaci na metry, což je pro tyto vzdálenosti
        matematicky mnohem stabilnější a správnější než předchozí pokusy.
        """
        import math
        
        # KROK 1: Nejdříve zkontrolujeme, jestli je bod uvnitř.
        if self.point_in_polygon(point, polygon):
            return 0.0
    
        # KROK 2: Pokud je bod vně, najdeme nejkratší vzdálenost k hraně.
        min_dist_sq = float('inf')
        R_METERS = 6371000  # Poloměr Země v metrech
    
        for i in range(len(polygon)):
            p1 = polygon[i]
            p2 = polygon[(i + 1) % len(polygon)]
    
            # Převod úsečky a bodu na lokální metrický systém (x, y)
            # Toto je klíčová oprava, která řeší nesmyslné vzdálenosti.
            px, py = (
                (point[1] - p1[1]) * math.cos(math.radians((p1[0] + point[0]) / 2)),
                point[0] - p1[0]
            )
            p2x, p2y = (
                (p2[1] - p1[1]) * math.cos(math.radians((p1[0] + p2[0]) / 2)),
                p2[0] - p1[0]
            )
            
            px_m = px * R_METERS
            py_m = py * R_METERS
            p2x_m = p2x * R_METERS
            p2y_m = p2y * R_METERS
    
            edge_len_sq = p2x_m**2 + p2y_m**2
            if edge_len_sq == 0.0:
                dist_sq = px_m**2 + py_m**2
            else:
                t = max(0, min(1, (px_m * p2x_m + py_m * p2y_m) / edge_len_sq))
                proj_x = t * p2x_m
                proj_y = t * p2y_m
                dist_sq = (px_m - proj_x)**2 + (py_m - proj_y)**2
            
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                
        return math.sqrt(min_dist_sq) / 1000.0 # Převedeme zpět na kilometry

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """Haversine formula pro vzdálenost mezi GPS body"""
        import math
        
        R = 6371.0  # Poloměr Země v km
        
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = (math.sin(dlat/2)**2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * 
             math.sin(dlon/2)**2)
        
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c
    
    
    def analyze_location_map_for_polygons(self, file_path, main_window):
        """Analyzuje lokační mapu pro detekci polygonů a extrakci jejich souřadnic"""
        import cv2
        import numpy as np
        from PIL import Image, ExifTags
        import re
        
        try:
            main_window.update_log(f"🔍 Analyzujem polygony v mapě: {os.path.basename(file_path)}")
            
            # Načti obrázek
            img = cv2.imread(file_path)
            if img is None:
                return None
                
            # Převeď na grayscale pro lepší detekci
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Detekce kontur/polygonů
            # Použij adaptivní threshold pro lepší detekci
            thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                         cv2.THRESH_BINARY_INV, 11, 2)
            
            # Morfologické operace pro vyčištění
            kernel = np.ones((3,3), np.uint8)
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            # Najdi kontury
            contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filtruj kontury podle velikosti a tvaru
            polygons = []
            min_area = 1000  # Minimální plocha polygonu
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area:
                    continue
                    
                # Aproximace polygonu
                epsilon = 0.02 * cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, epsilon, True)
                
                # Kontrola zda je to rozumný polygon (3-20 vrcholů)
                if 3 <= len(approx) <= 20:
                    # Převeď pixel koordináty na GPS souřadnice
                    gps_polygon = self.convert_pixel_to_gps_coords(approx, file_path, img.shape)
                    if gps_polygon:
                        polygons.append({
                            'points': gps_polygon,
                            'area': area,
                            'center': self.calculate_polygon_center(gps_polygon)
                        })
            
            if polygons:
                main_window.update_log(f"✅ Nalezeno {len(polygons)} polygonů v mapě")
                return polygons
            else:
                main_window.update_log(f"ℹ️ Žádné polygony nenalezeny, použiju GPS bod")
                return None
                
        except Exception as e:
            main_window.update_log(f"❌ Chyba při analýze polygonů: {e}")
            return None
    
    def convert_pixel_to_gps_coords(self, pixel_points, file_path, img_shape):
        """Převede pixel souřadnice na GPS souřadnice na základě EXIF dat a kalibrace"""
        try:
            # Získej GPS souřadnice z názvu souboru (referenční bod)
            filename = os.path.basename(file_path)
            gps_match = re.search(r'GPS([0-9.]+)S\+([0-9.]+)V', filename)
            if not gps_match:
                return None
                
            ref_lat = float(gps_match.group(1))
            ref_lon = float(gps_match.group(2))
            
            # Pokus o získání měřítka z EXIF dat
            scale_factor = self.estimate_map_scale(file_path, img_shape)
            
            # Převeď pixel souřadnice na GPS
            gps_points = []
            img_height, img_width = img_shape[:2]
            
            for point in pixel_points:
                px, py = point[0]
                
                # Převod pixel → metry → GPS souřadnice
                # Předpokládáme, že střed obrázku odpovídá referenčnímu GPS bodu
                center_x, center_y = img_width // 2, img_height // 2
                
                # Vzdálenost od středu v pixelech
                dx_pixels = px - center_x
                dy_pixels = center_y - py  # Y je obrácený
                
                # Převod na metry (závisí na měřítku mapy)
                dx_meters = dx_pixels * scale_factor
                dy_meters = dy_pixels * scale_factor
                
                # Převod na GPS souřadnice (přibližný výpočet)
                lat_per_meter = 1.0 / 111320.0  # přibližně 1 stupeň = 111.32 km
                lon_per_meter = 1.0 / (111320.0 * np.cos(np.radians(ref_lat)))
                
                new_lat = ref_lat + (dy_meters * lat_per_meter)
                new_lon = ref_lon + (dx_meters * lon_per_meter)
                
                gps_points.append((new_lat, new_lon))
            
            return gps_points
            
        except Exception as e:
            return None
    
    def estimate_map_scale(self, file_path, img_shape):
        """Odhadne měřítko mapy na základě velikosti obrázku a jiných indikátorů"""
        try:
            # Pokus o detekci měřítka z textu na mapě pomocí OCR
            import pytesseract
            from PIL import Image
            
            img = Image.open(file_path)
            text = pytesseract.image_to_string(img, lang='ces+eng')
            
            # Hledej měřítko v textu (např. "1:10000", "100m")
            scale_patterns = [
                r'1:(\d+)',  # měřítko 1:X
                r'(\d+)\s*m',  # X metrů
                r'(\d+)\s*km'  # X kilometrů
            ]
            
            for pattern in scale_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    scale_value = int(matches[0])
                    if '1:' in pattern:
                        # Měřítko 1:X znamená X metrů na jednotku
                        return scale_value / max(img_shape[:2])
                    elif 'km' in pattern:
                        return (scale_value * 1000) / max(img_shape[:2])
                    elif 'm' in pattern:
                        return scale_value / max(img_shape[:2])
            
            # Fallback: předpokládej standardní měřítko podle velikosti obrázku
            img_height, img_width = img_shape[:2]
            if max(img_width, img_height) > 2000:
                return 2.0  # 2 metry na pixel pro velké obrázky
            else:
                return 1.0  # 1 metr na pixel pro menší obrázky
                
        except Exception:
            # Fallback měřítko
            return 1.0
    
    def calculate_polygon_center(self, gps_points):
        """Vypočítá střed polygonu"""
        if not gps_points:
            return None
            
        lat_sum = sum(point[0] for point in gps_points)
        lon_sum = sum(point[1] for point in gps_points)
        
        return (lat_sum / len(gps_points), lon_sum / len(gps_points))
    
    def extract_gps_from_file(self, file_path):
        """
        Extrahuje GPS souřadnice z EXIF dat souboru.
        Optimalizováno pro HEIC pomocí pillow-heif a piexif, s fallbackem na exifread.
        """
        main_window = self.find_main_window()

        # Metoda 1: Pillow + pillow-heif + piexif (nejspolehlivější)
        try:
            from PIL import Image
            import piexif
            try:
                # Import je nutný pro automatickou registraci HEIF/HEIC podpory v Pillow
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                if file_path.lower().endswith(('.heic', '.heif')) and main_window:
                    main_window.update_log("⚠️ Pro HEIC je nutné nainstalovat: pip install pillow-heif")
            
            with Image.open(file_path) as img:
                if "exif" in img.info:
                    exif_dict = piexif.load(img.info["exif"])
                    if "GPS" in exif_dict and exif_dict["GPS"]:
                        gps_data = exif_dict["GPS"]
                        lat_dms = gps_data.get(piexif.GPSIFD.GPSLatitude)
                        lon_dms = gps_data.get(piexif.GPSIFD.GPSLongitude)
                        lat_ref_b = gps_data.get(piexif.GPSIFD.GPSLatitudeRef)
                        lon_ref_b = gps_data.get(piexif.GPSIFD.GPSLongitudeRef)

                        if lat_dms and lon_dms and lat_ref_b and lon_ref_b:
                            lat = self._piexif_dms_to_degrees(lat_dms)
                            lon = self._piexif_dms_to_degrees(lon_dms)

                            if lat_ref_b == b'S': lat = -lat
                            if lon_ref_b == b'W': lon = -lon
                            
                            return (lat, lon)
        except Exception as e:
            if main_window:
                main_window.update_log(f"ℹ️ Pillow/piexif selhalo pro {os.path.basename(file_path)}: {e}")
            pass

        # Metoda 2: exifread (fallback pro ostatní formáty)
        try:
            import exifread
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                    lat_dms_exifread = tags['GPS GPSLatitude'].values
                    lon_dms_exifread = tags['GPS GPSLongitude'].values
                    
                    lat = self._dms_to_decimal(lat_dms_exifread)
                    lon = self._dms_to_decimal(lon_dms_exifread)

                    lat_ref_tag = tags.get('GPS GPSLatitudeRef')
                    lon_ref_tag = tags.get('GPS GPSLongitudeRef')

                    if lat_ref_tag and str(lat_ref_tag.values) == 'S': lat = -lat
                    if lon_ref_tag and str(lon_ref_tag.values) == 'W': lon = -lon

                    return (lat, lon)
        except Exception as e:
            if main_window:
                main_window.update_log(f"ℹ️ exifread selhal pro {os.path.basename(file_path)}: {e}")
            pass

        return None
    def _convert_to_degrees(self, value):
        """Převede GPS souřadnice z EXIF formátu na desetinné stupně"""
        try:
            if isinstance(value, (list, tuple)) and len(value) >= 3:
                d = float(value[0])
                m = float(value[1]) 
                s = float(value[2])
                return d + (m / 60.0) + (s / 3600.0)
            return float(value)
        except:
            return 0.0
    
    def _dms_to_decimal(self, dms_values):
        """Převede DMS hodnoty na desetinné stupně"""
        try:
            if len(dms_values) >= 3:
                d = float(dms_values[0].num) / float(dms_values[0].den)
                m = float(dms_values[1].num) / float(dms_values[1].den)
                s = float(dms_values[2].num) / float(dms_values[2].den)
                return d + (m / 60.0) + (s / 3600.0)
            return 0.0
        except:
            return 0.0

    # Nahraďte tuto metodu ve třídě MissingPhotosWidget v pdf_generator_window.py
    
    def get_available_location_maps(self, main_window):
        import os
        from pathlib import Path
        import re
        from PIL import Image
    
        location_path = main_window.edit_location_path.text().strip()
        if not os.path.isdir(location_path):
            return []
    
        maps = []
        map_extensions = {'.png'}
        gps_pattern = re.compile(r'GPS([0-9.]+)S\+([0-9.]+)V')
        zoom_pattern = re.compile(r'\+Z(\d+)\+')
    
        folders_to_search = [os.path.join(location_path, "Neroztříděné"), location_path]
        processed_files = set()
    
        for folder_path in folders_to_search:
            if not os.path.isdir(folder_path): continue
            for filename in os.listdir(folder_path):
                full_file_path = os.path.join(folder_path, filename)
                if full_file_path in processed_files or not os.path.isfile(full_file_path) or Path(filename).suffix.lower() not in map_extensions:
                    continue
                processed_files.add(full_file_path)
    
                gps_match = gps_pattern.search(filename)
                zoom_match = zoom_pattern.search(filename)
                
                if gps_match and zoom_match:
                    try:
                        with Image.open(full_file_path) as img:
                            width, height = img.size
                            polygons = self.read_polygon_from_metadata(full_file_path, main_window)
                        
                        map_data = {
                            'location_id': filename.split('+')[0],
                            'gps_point': (float(gps_match.group(1)), float(gps_match.group(2))),
                            'filename': filename,
                            'filepath': full_file_path,
                            'zoom_level': int(zoom_match.group(1)),
                            'width': width,
                            'height': height,
                            'has_polygons': bool(polygons),
                            'polygons': polygons if polygons else [],
                            'description': self.parse_location_info(filename).get('description', ''),
                            'number_display': self.parse_location_info(filename).get('number_display', ''),
                            'id': self.parse_location_info(filename).get('id', filename.split('+')[0]),
                        }
                        maps.append(map_data)
                    except Exception as e:
                        if main_window: main_window.update_log(f"❌ Chyba při zpracování mapy {filename}: {e}")
        return maps


    def _check_opencv_availability(self):
        """Kontroluje dostupnost OpenCV"""
        try:
            import cv2
            import numpy as np
            return True
        except ImportError:
            return False
    
    def detect_polygon_indicators_simple(self, filename, file_path, main_window):
        """Jednoduchá heuristická detekce indikátorů polygonů bez OpenCV"""
        try:
            # Heuristika 1: Klíčová slova v názvu souboru
            polygon_keywords = [
                'polygon', 'area', 'zone', 'region', 'boundary', 'outline',
                'oblast', 'zóna', 'hranice', 'obvod', 'území', 'perimeter'
            ]
            
            filename_lower = filename.lower()
            for keyword in polygon_keywords:
                if keyword in filename_lower:
                    main_window.update_log(f"🔍 Detekce polygonu z názvu: {keyword}")
                    return True
            
            # Heuristika 2: Velikost souboru (polygonové mapy bývají větší)
            file_size = os.path.getsize(file_path)
            if file_size > 2 * 1024 * 1024:  # Větší než 2MB
                main_window.update_log(f"🔍 Velký soubor ({file_size//1024//1024}MB) - možný polygon")
                return True
            
            # Heuristika 3: Analýza bez OpenCV pomocí PIL
            return self.analyze_image_basic_pil(file_path, main_window)
            
        except Exception as e:
            main_window.update_log(f"⚠️ Chyba při heuristické detekci: {e}")
            return False
    
    def analyze_image_basic_pil(self, file_path, main_window):
        """Základní analýza obrázku pomocí PIL"""
        try:
            from PIL import Image
            import colorsys
            
            with Image.open(file_path) as img:
                # Zmenši obrázek pro rychlejší analýzu
                img_small = img.resize((200, 200))
                
                # Převeď na RGB pokud není
                if img_small.mode != 'RGB':
                    img_small = img_small.convert('RGB')
                
                # Analýza barevné distribuce
                colors = img_small.getcolors(maxcolors=50000)
                if not colors:
                    return False
                
                # Hledej výrazné barevné bloky (možné polygony)
                total_pixels = img_small.width * img_small.height
                color_blocks = []
                
                for count, color in colors:
                    if count > total_pixels * 0.05:  # Barva zabírá víc než 5%
                        # Kontrola jestli není šedá (mapa na pozadí)
                        r, g, b = color[:3]
                        if not (abs(r-g) < 30 and abs(g-b) < 30 and abs(r-b) < 30):
                            color_blocks.append((count, color))
                
                # Pokud je víc než 2 výrazné barevné bloky, pravděpodobně polygon
                if len(color_blocks) >= 2:
                    main_window.update_log(f"🎨 Detekce {len(color_blocks)} barevných bloků - možný polygon")
                    return True
                    
            return False
            
        except Exception as e:
            main_window.update_log(f"⚠️ Chyba PIL analýzy: {e}")
            return False
    
    def analyze_location_map_for_polygons_opencv(self, file_path, main_window):
        """Pokročilá analýza pomocí OpenCV - pouze pokud je dostupný"""
        try:
            import cv2
            import numpy as np
            
            main_window.update_log(f"🔬 OpenCV analýza: {os.path.basename(file_path)}")
            
            # Načti obrázek
            img = cv2.imread(file_path)
            if img is None:
                return None
                
            # Převeď na grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Detekce hran
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            
            # Najdi kontury
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            polygons = []
            min_area = 1000
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area:
                    continue
                    
                # Aproximace polygonu
                epsilon = 0.02 * cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, epsilon, True)
                
                if 3 <= len(approx) <= 20:
                    # Převeď na GPS souřadnice (zjednodušeně)
                    gps_polygon = self.convert_pixels_to_gps_simple(approx, file_path, img.shape)
                    if gps_polygon:
                        polygons.append({
                            'points': gps_polygon,
                            'area': area,
                            'center': self.calculate_polygon_center(gps_polygon)
                        })
            
            if polygons:
                main_window.update_log(f"✅ OpenCV: nalezeno {len(polygons)} polygonů")
                
            return polygons if polygons else None
            
        except Exception as e:
            main_window.update_log(f"❌ Chyba OpenCV analýzy: {e}")
            return None
    
    def convert_pixels_to_gps_simple(self, pixel_points, file_path, img_shape):
        """Jednoduchý převod pixel → GPS bez složité kalibrace"""
        try:
            filename = os.path.basename(file_path)
            gps_match = re.search(r'GPS([0-9.]+)S\+([0-9.]+)V', filename)
            if not gps_match:
                return None
                
            ref_lat = float(gps_match.group(1))
            ref_lon = float(gps_match.group(2))
            
            # Jednoduché odhady - předpokládáme standardní měřítko
            img_height, img_width = img_shape[:2]
            
            # Odhadované měřítko: 1 pixel = 2 metry (typické pro lokační mapy)
            meters_per_pixel = 2.0
            
            gps_points = []
            center_x, center_y = img_width // 2, img_height // 2
            
            for point in pixel_points:
                px, py = point[0]
                
                # Vzdálenost od středu v pixelech → metry
                dx_meters = (px - center_x) * meters_per_pixel  
                dy_meters = (center_y - py) * meters_per_pixel  # Y je obrácený
                
                # Převod na GPS (zjednodušený)
                lat_per_meter = 1.0 / 111320.0
                lon_per_meter = 1.0 / (111320.0 * abs(np.cos(np.radians(ref_lat))))
                
                new_lat = ref_lat + (dy_meters * lat_per_meter)
                new_lon = ref_lon + (dx_meters * lon_per_meter)
                
                gps_points.append((new_lat, new_lon))
            
            return gps_points
            
        except Exception as e:
            return None
    # Nahraďte tuto metodu ve třídě MissingPhotosWidget v pdf_generator_window.py
    
    def calculate_nearest_locations(self, photo_coords, location_maps):
        if not photo_coords or not location_maps: return []
    
        main_window = self.find_main_window()
        avg_lat = sum(pc[1][0] for pc in photo_coords) / len(photo_coords)
        avg_lon = sum(pc[1][1] for pc in photo_coords) / len(photo_coords)
        avg_point_gps = (avg_lat, avg_lon)
    
        if main_window: main_window.update_log(f"🛰️ Průměrná GPS pozice fotek: {avg_lat:.5f}, {avg_lon:.5f}")
    
        maps_inside_polygon = []
        for map_data in location_maps:
            if map_data.get('has_polygons'):
                try:
                    map_center_gps = map_data['gps_point']
                    map_zoom = map_data['zoom_level']
                    map_width = map_data['width']
                    map_height = map_data['height']
                    
                    photo_pixel_x, photo_pixel_y = self.gps_to_pixel(
                        avg_point_gps[0], avg_point_gps[1],
                        map_center_gps[0], map_center_gps[1],
                        map_zoom, map_width, map_height
                    )
                    
                    pixel_polygon = map_data['polygons'][0]['points']
                    
                    if self.is_point_in_polygon(photo_pixel_x, photo_pixel_y, pixel_polygon):
                        if main_window: main_window.update_log(f"✔️ PRIORITNÍ SHODA: Fotka je uvnitř polygonu mapy {map_data['filename']}.")
                        maps_inside_polygon.append((0.0, map_data['location_id'], map_data['filename']))
                except Exception as e:
                    if main_window: main_window.update_log(f" Chyba při pixelové analýze pro {map_data['filename']}: {e}")
    
        if maps_inside_polygon:
            maps_inside_polygon.sort(key=lambda x: x[1])
            return [(loc_id, filename, dist) for dist, loc_id, filename in maps_inside_polygon]
    
        if main_window: main_window.update_log("ℹ️ Žádná shoda uvnitř polygonu. Počítám vzdálenosti.")
        
        all_distances = []
        for map_data in location_maps:
            dist = float('inf')
            if map_data.get('has_polygons'):
                try:
                    map_center_gps = map_data['gps_point']; map_zoom = map_data['zoom_level']
                    map_width = map_data['width']; map_height = map_data['height']
                    
                    photo_pixel_x, photo_pixel_y = self.gps_to_pixel(avg_point_gps[0], avg_point_gps[1], map_center_gps[0], map_center_gps[1], map_zoom, map_width, map_height)
                    pixel_polygon = map_data['polygons'][0]['points']
                    
                    pixel_dist = self.point_to_polygon_dist((photo_pixel_x, photo_pixel_y), pixel_polygon)
                    meters_per_pixel = self.get_pixel_to_meter_ratio(map_center_gps[0], map_zoom)
                    dist = (pixel_dist * meters_per_pixel) / 1000.0
                except Exception:
                    dist = float('inf')
            
            if dist == float('inf'):
                map_gps = map_data.get('gps_point')
                if map_gps:
                    dist = self.haversine_distance(avg_lat, avg_lon, map_gps[0], map_gps[1])
    
            if dist != float('inf'):
                all_distances.append((dist, map_data['location_id'], map_data['filename']))
    
        all_distances.sort(key=lambda x: x[0])
        return [(loc_id, filename, dist) for dist, loc_id, filename in all_distances[:5]]

    
    def gps_to_pixel(self, target_lat, target_lon, center_lat, center_lon, zoom, map_width_px, map_height_px):
        import math
        def deg2num(lat_deg, lon_deg, zoom):
            lat_rad = math.radians(lat_deg)
            n = 2.0 ** zoom
            xtile = (lon_deg + 180.0) / 360.0 * n
            ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
            return (xtile, ytile)
    
        center_tile_x, center_tile_y = deg2num(center_lat, center_lon, zoom)
        target_tile_x, target_tile_y = deg2num(target_lat, target_lon, zoom)
    
        pixel_dx = (target_tile_x - center_tile_x) * 256
        pixel_dy = (target_tile_y - center_tile_y) * 256
    
        pixel_x = (map_width_px / 2) + pixel_dx
        pixel_y = (map_height_px / 2) + pixel_dy
        return pixel_x, pixel_y
    
    def get_pixel_to_meter_ratio(self, latitude, zoom):
        import math
        try:
            lat_rad = math.radians(latitude)
            meters_per_pixel = 156543.03 * math.cos(lat_rad) / (2 ** zoom)
            return meters_per_pixel
        except Exception:
            return 1.0
    
    def is_point_in_polygon(self, x, y, polygon_points):
        n = len(polygon_points)
        if n < 3:
            return False
        inside = False
        p1x, p1y = polygon_points[0]
        for i in range(n + 1):
            p2x, p2y = polygon_points[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside
    
    def point_to_segment_dist(self, p, a, b):
        import math
        px, py = p
        ax, ay = a
        bx, by = b
        abx, aby = bx - ax, by - ay
        ab2 = abx**2 + aby**2
        if ab2 == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * abx + (py - ay) * aby) / ab2
        t = max(0, min(1, t))
        closest_x = ax + t * abx
        closest_y = ay + t * aby
        return math.hypot(px - closest_x, py - closest_y)
    
    def point_to_polygon_dist(self, point, polygon_points):
        min_dist = float('inf')
        if len(polygon_points) < 2:
            return min_dist
        for i in range(len(polygon_points)):
            p1 = polygon_points[i]
            p2 = polygon_points[(i + 1) % len(polygon_points)]
            dist = self.point_to_segment_dist(point, p1, p2)
            if dist < min_dist:
                min_dist = dist
        return min_dist


    def distance_to_polygon_edge(self, point, polygon):
        """
        Vypočítá nejkratší vzdálenost od bodu k nejbližší hraně polygonu v km.
        """
        min_dist = float('inf')
        for i in range(len(polygon)):
            p1 = polygon[i]
            p2 = polygon[(i + 1) % len(polygon)]
            dist = self.distance_point_to_line_segment(point, p1, p2)
            if dist < min_dist:
                min_dist = dist
        return min_dist


    def show_location_selection_dialog(self, photo_numbers, recommendations):
        """Zobrazí dialog pro výběr doporučené lokace"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Vyberte lokaci")
        dialog.setMinimumSize(600, 400)  # Větší šířka pro dlouhé názvy
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel(f"Doporučené lokace pro {len(photo_numbers)} fotek:")
        layout.addWidget(label)
        
        list_widget = QListWidget()
        for location_id, filename, distance in recommendations:
            # Zkrácení dlouhého názvu pro zobrazení
            display_name = location_id
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."
            
            item_text = f"{display_name} - {distance:.1f} km"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, location_id)
            item.setToolTip(f"Celý název: {location_id}\nSoubor: {filename}")
            list_widget.addItem(item)
            
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)
        
        buttons_layout = QHBoxLayout()
        btn_ok = QPushButton("Přiřadit")
        btn_cancel = QPushButton("Zrušit")
        
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        
        buttons_layout.addWidget(btn_ok)
        buttons_layout.addWidget(btn_cancel)
        layout.addLayout(buttons_layout)
        
        if dialog.exec() == QDialog.Accepted:
            selected_items = list_widget.selectedItems()
            if selected_items:
                location_id = selected_items[0].data(Qt.UserRole)
                self.assign_photos_to_location_by_text_id(photo_numbers, location_id)
                
    def assign_photos_to_location_by_text_id(self, photo_numbers, location_id):
        """Přiřadí fotky k lokaci s textovým ID - OPRAVENO pro správné slučování intervalů a formát JSON"""
        main_window = self.find_main_window()
        if not main_window:
            return
        
        try:
            # DEBUG: Zobraz co se děje
            main_window.update_log(f"🔄 Přiřazuji fotky {photo_numbers} k lokaci '{location_id}'")
            
            config_text = main_window.location_config_text.toPlainText().strip()
            if config_text:
                data = json.loads(config_text)
            else:
                data = {}
            
            # Parsování číselného ID z textového ID
            numeric_location_id = self.extract_numeric_location_id(location_id)
            if numeric_location_id is None:
                main_window.update_log(f"❌ Nepodařilo se najít číselné ID pro: {location_id}")
                QMessageBox.warning(self, "Chyba", f"Nepodařilo se najít číselné ID pro lokaci: {location_id}")
                return
            
            main_window.update_log(f"✅ Převedeno '{location_id}' → číselné ID: {numeric_location_id}")
            
            # Konverze na string klíč pro JSON
            loc_key = str(numeric_location_id)
            main_window.update_log(f"📝 Klíč pro JSON: '{loc_key}'")
            
            # Získej existující čísla v lokaci
            existing_numbers = self.get_existing_numbers_for_location(data.get(loc_key, []))
            main_window.update_log(f"📋 Existující čísla v lokaci {loc_key}: {sorted(existing_numbers) if existing_numbers else 'žádná'}")
            
            # Slouč s novými čísly
            all_numbers = existing_numbers.union(set(photo_numbers))
            main_window.update_log(f"📊 Všechna čísla po sloučení: {sorted(all_numbers)}")
            
            # OPRAVENO: Vytvoř optimální intervaly
            intervals = self.merge_numbers_to_intervals(sorted(list(all_numbers)))
            main_window.update_log(f"🎯 Vytvořené intervaly: {intervals}")
            
            # Aktualizuj JSON data
            data[loc_key] = intervals
            
            # OPRAVENO: Použij správné kompaktní formátování (jednořádkový)
            formatted_json = self.format_json_compact_fixed(data)
            
            # Aktualizuj editor
            main_window.location_config_text.setPlainText(formatted_json)
            
            # Aktualizuj seznam nepřiřazených fotek
            main_window.update_missing_photos_list()
            
            main_window.update_log(f"✅ Úspěšně přiřazeno do lokace {loc_key}")
            
            # Zobraz úspěšné dokončení
            added_count = len(set(photo_numbers) - existing_numbers)
            QMessageBox.information(
                self,
                "Úspěch",
                f"✅ Přiřazeno {len(photo_numbers)} fotek do lokace {numeric_location_id}\n"
                f"Textové ID: {location_id}\n"
                f"Fotky: {', '.join(map(str, sorted(photo_numbers)))}\n"
                f"Nově přidáno: {added_count} fotek\n"
                f"Celkem čísel v lokaci: {len(all_numbers)}\n"
                f"Intervaly: {', '.join(intervals)}"
            )
        
        except Exception as e:
            main_window.update_log(f"❌ Chyba při přiřazování: {e}")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{str(e)}")

    def format_json_compact_fixed(self, data):
        """Formátuje JSON v kompaktním stylu - každá lokace na jeden řádek se zarovnáním"""
        if not data:
            return "{}"
        
        lines = ["{"]
        keys_list = list(data.keys())
        
        # Seřazení klíčů numericky
        try:
            keys_list.sort(key=lambda x: int(x))
        except ValueError:
            keys_list.sort() # Fallback na alfabetické řazení
        
        # Najdi nejdelší klíč pro zarovnání
        max_key_len = max(len(f'"{key}":') for key in keys_list)
        
        for i, key in enumerate(keys_list):
            value = data[key]
            value_json = json.dumps(value, ensure_ascii=False, separators=(',', ' '))
            comma = "," if i < len(keys_list) - 1 else ""
            
            # Zarovnání klíčů pro lepší čitelnost
            key_padded = f'"{key}":'.ljust(max_key_len + 2)
            lines.append(f"  {key_padded} {value_json}{comma}")
        
        lines.append("}")
        return "\n".join(lines)


    def extract_numeric_location_id(self, location_text_id):
        """Extrahuje číselné ID lokace z textového ID - OPRAVENO"""
        import re
        
        # Debug výpis
        main_window = self.find_main_window()
        if main_window:
            main_window.update_log(f"🔍 Extrahuji číselné ID z: {location_text_id}")
        
        # Metoda 1: Hledej 5-ti místné číslo za posledním +
        parts = location_text_id.split('+')
        if len(parts) >= 2:
            # Projdi části odzadu a hledej 5-ti místné číslo
            for part in reversed(parts):
                # Odstraň příponu souboru pokud existuje
                part_clean = part.split('.')[0] if '.' in part else part
                # Hledej 5-ti místné číslo na konci části
                match = re.search(r'(\d{5})$', part_clean)
                if match:
                    numeric_id = int(match.group(1))
                    if main_window:
                        main_window.update_log(f"✅ Nalezeno číselné ID: {numeric_id}")
                    return numeric_id
        
        # Metoda 2: Pokud je celý text jen číslo
        if location_text_id.strip().isdigit():
            numeric_id = int(location_text_id.strip())
            if main_window:
                main_window.update_log(f"✅ Přímé číselné ID: {numeric_id}")
            return numeric_id
        
        # Metoda 3: Hledej jakékoliv číslo v názvu lokace
        first_part = parts[0] if parts else location_text_id
        numbers = re.findall(r'\d+', first_part)
        if numbers:
            # Vezmi největší číslo (pravděpodobně ID lokace)
            numeric_id = int(max(numbers, key=lambda x: int(x)))
            if main_window:
                main_window.update_log(f"✅ ID z názvu lokace: {numeric_id}")
            return numeric_id
        
        # OPRAVENÝ fallback: Najdi nejvyšší existující ID a přidej 1
        if main_window:
            try:
                config_text = main_window.location_config_text.toPlainText().strip()
                if config_text:
                    data = json.loads(config_text)
                    existing_ids = [int(k) for k in data.keys() if k.isdigit()]
                    if existing_ids:
                        new_id = max(existing_ids) + 1
                        main_window.update_log(f"⚠️ Použito nové ID: {new_id} (max existujících + 1)")
                        return new_id
            except:
                pass
        
        # Úplný fallback
        if main_window:
            main_window.update_log(f"⚠️ Použito výchozí ID: 999 pro: {location_text_id}")
        return 999

    def extract_numeric_location_id_from_filename(self, filename):
        """Extrahuje číselné ID lokace z CELÉHO názvu souboru lokační mapy"""
        import re
        
        main_window = self.find_main_window()
        if main_window:
            main_window.update_log(f"🔍 Extrahuji číselné ID z celého souboru: {filename}")
        
        try:
            # Rozdělení podle '+' znaků
            parts = filename.split('+')
            if len(parts) < 2:
                return None
            
            # Poslední část před příponou (např. "00026.png" → "00026")
            last_part = parts[-1]
            base_name = last_part.split('.')[0] if '.' in last_part else last_part
            
            # Hledání číselné části na konci
            match = re.search(r'(\d{1,5})$', base_name)
            if match:
                numeric_id = int(match.group(1))
                if main_window:
                    main_window.update_log(f"✅ Nalezeno číselné ID: {numeric_id} z části '{base_name}'")
                return numeric_id
            
            if main_window:
                main_window.update_log(f"❌ Nenalezeno číselné ID v části '{base_name}'")
            return None
            
        except Exception as e:
            if main_window:
                main_window.update_log(f"❌ Chyba při extrakci ID: {e}")
            return None
    
    
    def get_existing_numbers_for_location(self, intervals_list):
        """Rozbalí seznam intervalů na množinu čísel"""
        numbers = set()
        
        for item in intervals_list:
            item_str = str(item).strip()
            if not item_str:
                continue
                
            if '-' in item_str:
                try:
                    start_str, end_str = item_str.split('-', 1)
                    start_num = int(start_str.strip())
                    end_num = int(end_str.strip())
                    if start_num > end_num:
                        start_num, end_num = end_num, start_num
                    numbers.update(range(start_num, end_num + 1))
                except ValueError:
                    continue
            else:
                try:
                    numbers.add(int(item_str))
                except ValueError:
                    continue
                    
        return numbers
    
    def merge_numbers_to_intervals(self, numbers):
        """Spojí čísla do intervalů (např. [1,2,3,5] -> ["1-3", "5"]) - OVĚŘENO"""
        if not numbers:
            return []
        
        # Seřaď a odstraň duplicity
        numbers = sorted(set(numbers))
        intervals = []
        
        start = numbers[0]
        end = numbers[0]
        
        for n in numbers[1:]:
            if n == end + 1:  # Navazující číslo
                end = n
            else:  # Mezera v sekvenci
                if start == end:
                    intervals.append(str(start))
                else:
                    intervals.append(f"{start}-{end}")
                start = n
                end = n
        
        # Zpracování posledního intervalu
        if start == end:
            intervals.append(str(start))
        else:
            intervals.append(f"{start}-{end}")
        
        return intervals

    def format_json_compact(self, data):
        """Formátuje JSON kompaktně - každá lokace na jeden řádek"""
        if not data:
            return "{}"
        
        lines = ["{"]
        keys_list = list(data.keys())
        
        # Seřazení klíčů numericky
        try:
            keys_list.sort(key=lambda x: int(x))
        except ValueError:
            keys_list.sort()  # Fallback na alfabetické řazení
        
        for i, key in enumerate(keys_list):
            value = data[key]
            value_json = json.dumps(value, ensure_ascii=False, separators=(',', ': '))
            comma = "," if i < len(keys_list) - 1 else ""
            key_padded = f'"{key}":'.ljust(6)  # Zarovnání klíčů
            lines.append(f"  {key_padded} {value_json}{comma}")
        
        lines.append("}")
        return "\n".join(lines)

    def assign_photos_to_location(self, photo_numbers, location_id):
        """Přiřadí fotky k vybrané lokaci"""
        main_window = self.find_main_window()
        if not main_window:
            return

        try:
            config_text = main_window.location_config_text.toPlainText().strip()
            if config_text:
                data = json.loads(config_text)
            else:
                data = {}

            loc_key = str(location_id)
            if loc_key not in data:
                data[loc_key] = []

            # Přidej fotky
            data[loc_key].extend([str(num) for num in photo_numbers])

            # Aktualizuj JSON
            formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
            main_window.location_config_text.setPlainText(formatted_json)
            main_window.update_missing_photos_list()

            QMessageBox.information(
                self, 
                "Úspěch", 
                f"Přiřazeno {len(photo_numbers)} fotek do lokace {location_id}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{str(e)}")

    def find_main_window(self):
        """Najde hlavní okno aplikace"""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'location_config_text'):
                return parent
            parent = parent.parent()
        return None

    def update_missing_photos(self, folder_path, json_numbers, crop_status=None):
        """
        Aktualizuje seznam fotek, které NEMAJÍ PŘIŘAZENOU LOKACI.
        Pokud je json_numbers prázdný, zobrazí všechny fotky.
        """
        self.list_widget.clear()
        if crop_status is None:
            crop_status = {}
    
        if not folder_path or not os.path.isdir(folder_path):
            self.list_widget.addItem("❌ Složka neexistuje nebo není zadána")
            self.info_label.setText("Zkontrolujte cestu k fotkám čtyřlístků")
            return
    
        try:
            # Získání všech fotek ze složky
            files = os.listdir(folder_path)
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            photos_in_folder = set()
            invalid_files = []
    
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in photo_extensions:
                    try:
                        number_part = filename.split('+')[0]
                        photo_number = int(number_part)
                        photos_in_folder.add(photo_number)
                    except (ValueError, IndexError):
                        invalid_files.append(filename)
    
            # ✅ NOVÉ: Rozlišení režimů zobrazení
            if not json_numbers:  # Prázdný seznam = zobraz všechny fotky
                photos_to_display = photos_in_folder
                mode_text = "všechny fotky"
            else:  # Neprázdný seznam = zobraz jen fotky bez lokace
                json_numbers_set = set(json_numbers)
                photos_to_display = photos_in_folder - json_numbers_set
                mode_text = "fotky bez lokace"
    
            # Zobrazení výsledků
            if not photos_in_folder:
                self.list_widget.addItem("ℹ️ Ve složce nejsou žádné fotky čtyřlístků")
                self.info_label.setText("Složka je prázdná nebo neobsahuje platné soubory")
            elif not photos_to_display and json_numbers:  # Jen když filtrujeme podle lokací
                self.list_widget.addItem("✅ Všechny fotky mají přiřazenou lokaci")
                self.info_label.setText(f"Celkem {len(photos_in_folder)} fotek – všechny přiřazeny v lokacích")
            else:
                # Přidání fotek do seznamu
                for photo_num in sorted(photos_to_display):
                    is_cropped = crop_status.get(str(photo_num), False)
                    icon = "✂️" if is_cropped else "🖼️"
                    item = QListWidgetItem(f"{icon} {photo_num}")
                    crop_tooltip_text = "Ořezaná" if is_cropped else "Neupravená"
    
                    # ✅ NOVÉ: Různý tooltip podle režimu
                    if not json_numbers:
                        tooltip_detail = "Zobrazeny všechny fotky"
                    else:
                        tooltip_detail = "Nemá přiřazenou lokaci"
    
                    item.setToolTip(f"Fotka číslo {photo_num} ({crop_tooltip_text})\n{tooltip_detail}.")
                    self.list_widget.addItem(item)
    
                # ✅ NOVÉ: Různý info text podle režimu
                if not json_numbers:
                    self.info_label.setText(f"Zobrazeno: {len(photos_to_display)} z {len(photos_in_folder)} fotek (všechny)")
                else:
                    self.info_label.setText(f"Bez lokace: {len(photos_to_display)} z {len(photos_in_folder)} fotek")
    
            # Zobrazení neplatných souborů (beze změny)
            if invalid_files:
                self.list_widget.addItem("")
                self.list_widget.addItem("⚠️ Neplatné názvy souborů:")
                for invalid_file in invalid_files[:5]:
                    self.list_widget.addItem(f"  {invalid_file}")
                if len(invalid_files) > 5:
                    self.list_widget.addItem(f"  ... a {len(invalid_files) - 5} dalších")
    
            # 🔴 DOPLNĚNO: po naplnění seznamu doplň datum/měsíc pořízení,
            # přičemž číslo fotky zůstane POSLEDNÍ token.
            self.annotate_photo_items_with_taken_date()
    
        except Exception as e:
            self.list_widget.addItem(f"❌ Chyba při čtení složky: {str(e)}")
            self.info_label.setText("Chyba při analýze fotek")

class PDFGeneratorWindow(QDialog):
    """Okno pro generování PDF z čtyřlístků"""

    # Ve třídě PDFGeneratorWindow
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📄 Generátor PDF čtyřlístků")
        self.setMinimumSize(1600, 880)
        self.resize(1800, 940)
    
        # NOVÉ: Inicializace slovníku pro stav ořezání fotek a zámku aktualizací
        self.crop_status = {}
        
        # PŘIDEJTE TENTO ŘÁDEK:
        from pathlib import Path
        self.crop_status_file = Path("settings") / "crop_status.json"
        
        self._photo_updates_enabled = True # ZÁMEK pro automatické aktualizace
    
        # Timer pro validaci (beze změny)
        self.clover_validation_timer = QTimer(self)
        self.clover_validation_timer.setSingleShot(True)
        self.clover_validation_timer.timeout.connect(self.validate_clover_range)
        self.clover_validation_enabled = False
    
        # Inicializace watcherů pro sledování složek
        self._clover_watcher = QFileSystemWatcher(self)
        self._clover_watcher.directoryChanged.connect(self._on_clover_dir_changed)
        self._clover_watcher.fileChanged.connect(self._on_clover_dir_changed)
    
        self._output_watcher = QFileSystemWatcher(self)
        self._output_watcher.directoryChanged.connect(self.update_full_pdf_path_preview)
        self._output_watcher.fileChanged.connect(self.update_full_pdf_path_preview)
    
        # UI a nastavení (beze změny)
        self.init_ui()
        self.load_settings()
        self.finished.connect(self.save_settings)
    
        QTimer.singleShot(100, self.validate_clover_range)
        QTimer.singleShot(300, self.initial_sync_trees)
        QTimer.singleShot(200, self.adopt_dark_theme_after_ui)
        
    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: export_json_settings
    # NAHRAĎ TOUTO VERZÍ (doplněn export a slučování sekce „anonymizace“ s klíčem "ANONYMIZOVANE")
    
    def export_json_settings(self):
        """Exportuje nastavení lokací, stavů, poznámek a anonymizace do jednoho JSON souboru - POUZE PŘIDÁVÁ, NIKDY NEUBÍRÁ"""
        try:
            # Cesta k exportnímu souboru
            export_path = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Skripty/gui/settings/LokaceStavyPoznamky.json"
            export_path = os.path.expanduser(export_path)
            
            # Vytvoření složky pokud neexistuje
            export_dir = os.path.dirname(export_path)
            os.makedirs(export_dir, exist_ok=True)
            
            # Načtení dat z GUI
            try:
                lokace_text = self.location_config_text.toPlainText().strip()
                stavy_text = self.status_config_text.toPlainText().strip()
                poznamky_text = self.notes_text.toPlainText().strip()
    
                # ⬇️ NOVĚ: anonymizace – pokud editor existuje
                anonym_text = ""
                if hasattr(self, "anonym_config_text") and hasattr(self.anonym_config_text, "toPlainText"):
                    anonym_text = (self.anonym_config_text.toPlainText() or "").strip()
                
                # Parsování JSON dat (s kontrolou validity)
                lokace_data = json.loads(lokace_text) if lokace_text else {}
                stavy_data = json.loads(stavy_text) if stavy_text else {}
                poznamky_data = json.loads(poznamky_text) if poznamky_text else {}
    
                # ⬇️ NOVĚ: anonymizace – očekává se dict s klíčem "ANONYMIZOVANE": list[str]
                anonym_data_raw = json.loads(anonym_text) if anonym_text else {}
                if anonym_data_raw and not isinstance(anonym_data_raw, dict):
                    raise json.JSONDecodeError("Kořen JSON anonymizace není objekt {}", anonym_text, 0)
                # Převedeme na tvar stejné úrovně jako ostatní sekce => {"ANONYMIZOVANE": [...]}
                anonymizace_data = {}
                if isinstance(anonym_data_raw, dict) and "ANONYMIZOVANE" in anonym_data_raw:
                    anonymizace_data = {"ANONYMIZOVANE": anonym_data_raw.get("ANONYMIZOVANE", [])}
    
            except json.JSONDecodeError as e:
                QMessageBox.critical(self, "Chyba JSON", 
                                   f"Neplatný JSON formát v některé ze záložek:\n{str(e)}\n\n"
                                   "Prosím opravte JSON před exportem.")
                return
            
            # Načtení existujících dat ze souboru
            existing_data = {}
            if os.path.exists(export_path):
                try:
                    with open(export_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                    self.update_log(f"📂 Načtena existující data z: {os.path.basename(export_path)}")
                except (json.JSONDecodeError, IOError) as e:
                    # Pokud soubor existuje ale je poškozený, vytvoříme zálohu
                    backup_path = export_path + f".backup_{int(time.time())}"
                    try:
                        shutil.copy2(export_path, backup_path)
                        self.update_log(f"⚠️ Poškozený soubor zálohován jako: {os.path.basename(backup_path)}")
                    except:
                        pass
                    existing_data = {}
    
            # OPRAVENÉ: Pomocné funkce definované správně
            def expand_interval_to_numbers(intervals_list):
                """Rozbalí seznam intervalů na množinu čísel"""
                numbers = set()
                for item in intervals_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
                    if '-' in item_str:
                        try:
                            start_str, end_str = item_str.split('-', 1)
                            start_num = int(start_str.strip())
                            end_num = int(end_str.strip())
                            if start_num > end_num:
                                start_num, end_num = end_num, start_num
                            numbers.update(range(start_num, end_num + 1))
                        except ValueError:
                            continue
                    else:
                        try:
                            numbers.add(int(item_str))
                        except ValueError:
                            continue
                return numbers
    
            def merge_interval_lists(existing_list, new_list):
                """Sloučí dva seznamy intervalů/čísel bez ztráty, s optimalizací"""
                # Převeď oba seznamy na množiny čísel
                existing_numbers = expand_interval_to_numbers(existing_list)
                new_numbers = expand_interval_to_numbers(new_list)
                
                # Sloučení všech čísel
                all_numbers = existing_numbers.union(new_numbers)
                
                # Převod zpět na optimalizované intervaly
                if not all_numbers:
                    return []
                
                sorted_numbers = sorted(all_numbers)
                intervals = []
                start = sorted_numbers[0]
                end = sorted_numbers[0]
                
                for n in sorted_numbers[1:]:
                    if n == end + 1:  # Navazující číslo
                        end = n
                    else:  # Mezera v sekvenci
                        if start == end:
                            intervals.append(str(start))
                        else:
                            intervals.append(f"{start}-{end}")
                        start = n
                        end = n
                
                # Zpracování posledního intervalu
                if start == end:
                    intervals.append(str(start))
                else:
                    intervals.append(f"{start}-{end}")
                
                return intervals
    
            def safe_merge_section(merged_data, section_data, section_name):
                """Bezpečné sloučení sekce s inteligentním slučováním intervalů/čísel"""
                if not section_data:
                    return 0, 0
                
                if section_name not in merged_data:
                    merged_data[section_name] = {}
                
                added_items = 0
                merged_items = 0
                
                for key, value in section_data.items():
                    key_str = str(key)
                    
                    if key_str not in merged_data[section_name]:
                        # Nový klíč - přidat celý
                        merged_data[section_name][key_str] = value
                        added_items += 1
                        if isinstance(value, list):
                            total_numbers = len(expand_interval_to_numbers(value))
                            self.update_log(f"  ➕ Nový {section_name} klíč: {key_str} ({total_numbers} čísel)")
                        else:
                            self.update_log(f"  ➕ Nový {section_name} klíč: {key_str}")
                    else:
                        # Existující klíč - sloučit hodnoty
                        existing_value = merged_data[section_name][key_str]
                        
                        if isinstance(value, list) and isinstance(existing_value, list):
                            # Sloučení seznamů intervalů/čísel
                            old_count = len(expand_interval_to_numbers(existing_value))
                            merged_list = merge_interval_lists(existing_value, value)
                            new_count = len(expand_interval_to_numbers(merged_list))
                            
                            merged_data[section_name][key_str] = merged_list
                            merged_items += 1
                            added_numbers = new_count - old_count
                            self.update_log(f"  🔄 Sloučen {section_name} klíč: {key_str} (+{added_numbers} čísel, celkem {new_count})")
                        elif isinstance(value, str) and isinstance(existing_value, str):
                            # Pro stringy (Nastavení poznámek) - nepřepisovat pokud jsou rozdílné
                            if value != existing_value:
                                self.update_log(f"  ⏭️ Přeskočena poznámka pro klíč {key_str} (už existuje jiná: '{existing_value}')")
                            else:
                                self.update_log(f"  ✓ Poznámka pro klíč {key_str} je stejná")
                        else:
                            # Pro jiné typy - nepřepisovat
                            self.update_log(f"  ⏭️ Přeskočen {section_name} klíč: {key_str} (už existuje)")
                
                return added_items, merged_items
    
            # Bezpečné sloučení dat - inteligentní slučování na úrovni jednotlivých klíčů
            merged_data = existing_data.copy()
            
            total_added = 0
            total_merged = 0
            
            # Sloučení lokací
            if lokace_data:
                self.update_log("🗺️ Zpracovávám lokace...")
                added, merged = safe_merge_section(merged_data, lokace_data, "lokace")
                total_added += added
                total_merged += merged
            
            # Sloučení stavů
            if stavy_data:
                self.update_log("⚙️ Zpracovávám stavy...")
                added, merged = safe_merge_section(merged_data, stavy_data, "stavy")
                total_added += added
                total_merged += merged
            
            # Sloučení poznámek
            if poznamky_data:
                self.update_log("📝 Zpracovávám poznámky...")
                added, merged = safe_merge_section(merged_data, poznamky_data, "poznamky")
                total_added += added
                total_merged += merged
    
            # ⬇️ NOVĚ: Sloučení anonymizace (sekce "anonymizace" s klíčem "ANONYMIZOVANE")
            if anonymizace_data:
                self.update_log("🛡️ Zpracovávám anonymizaci...")
                added, merged = safe_merge_section(merged_data, anonymizace_data, "anonymizace")
                total_added += added
                total_merged += merged
            
            # Metadata se vždy aktualizují (ale neubírají předchozí metadata klíče)
            if "metadata" not in merged_data:
                merged_data["metadata"] = {}
            
            merged_data["metadata"]["last_export"] = datetime.datetime.now().isoformat()
            merged_data["metadata"]["export_source"] = "PDF Generator Window"
            merged_data["metadata"]["version"] = "1.0"
            
            # Zápis sloučených dat do souboru
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, ensure_ascii=False, indent=2, sort_keys=True)
            
            # Statistiky pro uživatele
            final_lokace = len(merged_data.get("lokace", {}))
            final_stavy = len(merged_data.get("stavy", {}))
            final_poznamky = len(merged_data.get("poznamky", {}))
            final_anonym = len(merged_data.get("anonymizace", {}))  # očekává jeden klíč "ANONYMIZOVANE"
            
            success_message = (
                f"✅ JSON nastavení bylo inteligentně sloučeno!\n\n"
                f"📁 Soubor: {os.path.basename(export_path)}\n"
                f"➕ Nově přidáno klíčů: {total_added}\n"
                f"🔄 Sloučeno existujících klíčů: {total_merged}\n\n"
                f"📊 Celkový stav souboru:\n"
                f"🗺️ Lokace: {final_lokace}\n"
                f"⚙️ Stavy: {final_stavy}\n"
                f"📝 Nastavení poznámek: {final_poznamky}\n"
                f"🛡️ Anonymizace (sekcí): {final_anonym}\n\n"
                f"💾 Velikost souboru: {os.path.getsize(export_path)} bytů\n\n"
                f"🔒 ŽÁDNÁ ČÍSLA/INTERVALY NEBYLY ODEBRÁNY\n"
                f"🎯 INTERVALY BYLY INTELIGENTNĚ OPTIMALIZOVÁNY"
            )
            
            self.update_log(f"✅ Inteligentní export dokončen - {total_added} nových, {total_merged} sloučených")
            QMessageBox.information(self, "Inteligentní export dokončen", success_message)
            
        except Exception as e:
            error_message = f"Nepodařilo se exportovat JSON nastavení:\n{str(e)}"
            self.update_log(f"❌ Chyba exportu JSON: {str(e)}")
            QMessageBox.critical(self, "Chyba exportu", error_message)

    def check_states_without_notes_real_time(self):
        """Real-time kontrola, zda fotky se stavem mají také poznámku."""
        try:
            states_config_text = self.status_config_text.toPlainText().strip()
            notes_text = self.notes_text.toPlainText().strip()
    
            # Pokud je stav konfigurace prázdná, skryjeme indikaci
            if not states_config_text:
                self._update_states_without_notes_indicator(None)
                return
    
            states_data = {}
            notes_data = {}
    
            try:
                states_data = json.loads(states_config_text)
                if notes_text:
                    notes_data = json.loads(notes_text)
            except json.JSONDecodeError:
                # Chybný JSON - nevykresluj nic
                self._update_states_without_notes_indicator(None)
                return
    
            if not isinstance(states_data, dict):
                self._update_states_without_notes_indicator(None)
                return
    
            # Získat všechna čísla čtyřlístků se stavem (kromě BEZGPS a ZTRACENY)
            photos_with_states = set()
            for state_name, number_list in states_data.items():
                # NOVÉ: Ignorovat stavy, které nevyžadují poznámku
                if str(state_name).upper() in ["BEZGPS", "ZTRACENY"]:
                    continue
                    
                if not isinstance(number_list, list):
                    continue
    
                for item in number_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
    
                    if '-' in item_str:
                        try:
                            start_str, end_str = item_str.split('-', 1)
                            start_num = int(start_str.strip())
                            end_num = int(end_str.strip())
                            if start_num > end_num:
                                start_num, end_num = end_num, start_num
                            photos_with_states.update(range(start_num, end_num + 1))
                        except ValueError:
                            continue
                    else:
                        try:
                            num = int(item_str)
                            photos_with_states.add(num)
                        except ValueError:
                            continue
    
            # Získat všechna čísla čtyřlístků s poznámkou
            photos_with_notes = set()
            for key in notes_data.keys():
                try:
                    photos_with_notes.add(int(key))
                except ValueError:
                    continue
    
            # Najít čísla se stavem, která nemají poznámku (kromě BEZGPS a ZTRACENY)
            missing_notes = photos_with_states - photos_with_notes
    
            # Aktualizovat indikátor
            if len(missing_notes) == 0 and len(photos_with_states) > 0:
                self._update_states_without_notes_indicator(set(), all_ok=True)
                # NOVÉ: Aktualizovat i indikátor v záložce Poznámky
                self._update_notes_states_without_notes_indicator(set(), all_ok=True)
            elif len(missing_notes) > 0:
                self._update_states_without_notes_indicator(missing_notes, all_ok=False)
                # NOVÉ: Aktualizovat i indikátor v záložce Poznámky
                self._update_notes_states_without_notes_indicator(missing_notes, all_ok=False)
            else:
                # Žádné fotky se stavem
                self._update_states_without_notes_indicator(None)
                # NOVÉ: Aktualizovat i indikátor v záložce Poznámky
                self._update_notes_states_without_notes_indicator(None)
    
        except Exception:
            # Tichá chyba - nenarušuj uživatelské rozhraní
            pass

    def _update_states_without_notes_indicator(self, missing_notes_set, all_ok=False):
        """Aktualizuje indikátor chybějících poznámek pro fotky se stavem."""
        if not hasattr(self, 'states_without_notes_indicator'):
            return
    
        if missing_notes_set is None:
            self.states_without_notes_indicator.setVisible(False)
            return
    
        if all_ok:
            self.states_without_notes_indicator.setText("✅ Všechny fotky se stavem mají poznámku")
            self.states_without_notes_indicator.setStyleSheet("""
                QLabel {
                    color: #27ae60;
                    background-color: #d5f4e6;
                    border: 1px solid #27ae60;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.states_without_notes_indicator.setVisible(True)
        else:
            missing_list = sorted(list(missing_notes_set))
            if len(missing_list) <= 12:
                missing_str = ", ".join(str(x) for x in missing_list)
            else:
                missing_str = ", ".join(str(x) for x in missing_list[:10]) + f", ... (+{len(missing_list)-10})"
    
            self.states_without_notes_indicator.setText(f"⚠️ Chybějící poznámky pro fotky: {missing_str}")
            self.states_without_notes_indicator.setToolTip(
                f"Celkem {len(missing_list)} fotek se stavem nemá poznámku.\n"
                f"Fotky: {', '.join(str(x) for x in missing_list)}"
            )
            self.states_without_notes_indicator.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    background-color: #fadbd8;
                    border: 1px solid #e74c3c;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.states_without_notes_indicator.setVisible(True)

    # Přidejte tyto dvě metody kamkoliv do třídy PDFGeneratorWindow
    def disable_photo_list_updates(self):
        """Dočasně zakáže automatické obnovování seznamů fotek."""
        self._photo_updates_enabled = False
        self.update_log("⏸️ Automatické obnovování seznamu fotek pozastaveno.")
    
    def enable_photo_list_updates(self, photo_number_to_reselect=None):
        """Znovu povolí automatické obnovování seznamů fotek a spustí jednorázovou kontrolu.
    
        Pokud je zadáno číslo fotky, po jednorázové kontrole bude tato fotka znovu označena v seznamu.
        """
        self._photo_updates_enabled = True
        # Uložení pending reselectu; atribut je vytvořen on‑the‑fly, není nutné nic v __init__.
        try:
            self._pending_reselect_photo_number = int(photo_number_to_reselect) if photo_number_to_reselect is not None else None
        except Exception:
            self._pending_reselect_photo_number = None
    
        self.update_log("▶️ Automatické obnovování seznamu fotek obnoveno.")
        # Po odemčení pro jistotu jednorázově zaktualizujeme vše, abychom nezmeškali změny
        QTimer.singleShot(50, lambda: self._on_clover_dir_changed(""))

    # Ve třídě PDFGeneratorWindow (přidejte tuto novou metodu)
    def _update_crop_status(self, photo_number_str, is_cropped):
        """Aktualizuje stav ořezu pro danou fotku a obnoví seznamy."""
        self.crop_status[photo_number_str] = is_cropped
        self.update_log(f"✂️ Stav ořezu pro fotku {photo_number_str} aktualizován na: {'Ořezaná' if is_cropped else 'Neupravená'}")
        # Okamžitá aktualizace obou seznamů, které zobrazují fotky
        self.update_missing_photos_list()
        self.update_status_photos_list()

    def update_crop_status(self, photo_path, is_cropped):
        """Aktualizuje stav ořezu pro danou fotku a obnoví UI."""
        try:
            filename = os.path.basename(photo_path)
            photo_number_str = filename.split('+')[0]
            if photo_number_str.isdigit():
                self.crop_status[photo_number_str] = is_cropped
                self.update_log(f"✂️ Stav ořezu pro fotku {photo_number_str} aktualizován na: {is_cropped}")
                # Okamžitá aktualizace seznamu fotek
                self.update_missing_photos_list()
        except (ValueError, IndexError) as e:
            self.update_log(f"❌ Chyba při aktualizaci stavu ořezu pro {photo_path}: {e}")
        
    def extract_numbers_from_location_json(self):
        """Extrahuje všechna čísla čtyřlístků z JSON konfigurace lokací"""
        try:
            config_text = self.location_config_text.toPlainText().strip()
            if not config_text:
                return []
            
            data = json.loads(config_text)
            all_numbers = set()
            
            for location_id, number_list in data.items():
                if not isinstance(number_list, list):
                    continue
                    
                for item in number_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
                        
                    if '-' in item_str:
                        try:
                            start_str, end_str = item_str.split('-', 1)
                            start_num = int(start_str.strip())
                            end_num = int(end_str.strip())
                            if start_num > end_num:
                                start_num, end_num = end_num, start_num
                            
                            for num in range(start_num, end_num + 1):
                                all_numbers.add(num)
                        except ValueError:
                            continue
                    else:
                        try:
                            num = int(item_str)
                            all_numbers.add(num)
                        except ValueError:
                            continue
            
            return sorted(list(all_numbers))
            
        except json.JSONDecodeError:
            return []
        except Exception:
            return []
    
    def update_missing_photos_list(self):
        """Aktualizuje seznam nepřiřazených fotek a zobrazuje chybná čísla přiřazená v JSON, která nejsou ve složce"""
        if not hasattr(self, 'missing_photos_widget'):
            return
    
        clover_path = self.edit_clover_path.text().strip()
        
        # ✅ NOVÉ: Rozlišení podle stavu checkboxu
        if hasattr(self, 'show_all_photos_checkbox') and self.show_all_photos_checkbox.isChecked():
            # Zobraz všechny fotky - předej prázdný seznam jako json_numbers
            json_numbers = []
            self.missing_photos_widget.update_missing_photos(clover_path, json_numbers, self.crop_status)
        else:
            # Původní chování - zobraz jen fotky bez přiřazené lokace
            json_numbers = self.extract_numbers_from_location_json()
            self.missing_photos_widget.update_missing_photos(clover_path, json_numbers, self.crop_status)
    
        # NOVÉ: Aktualizace stavu tlačítka rychlého ořezu
        QTimer.singleShot(50, self.update_quick_crop_button_state)
    
        # Následující kód pro real-time kontrolu chybějících souborů je v pořádku,
        # ale vylepšíme manipulaci s textem v informačním labelu.
    
        if not clover_path or not os.path.isdir(clover_path):
            return
    
        try:
            # Získej seznam skutečně existujících fotek ve složce
            existing_photos = self._get_existing_photo_numbers(clover_path)
    
            # Najdi čísla v JSON, která nejsou ve složce
            json_numbers_set = set(json_numbers) if json_numbers else set()
            assigned_not_in_folder = sorted(json_numbers_set - existing_photos)
    
            # Aktualizuj info_label s červenou hláškou, pokud jsou chybějící fotky
            current_text = self.missing_photos_widget.info_label.text()
    
            # OPRAVA: Robustnější oddělení hlavního textu od varování
            base_text_parts = []
            for line in current_text.splitlines():
                # Ignorovat staré varování
                if 'Přiřazeny fotky, které ve složce nejsou' not in line:
                    base_text_parts.append(line)
    
            base_text = '\n'.join(base_text_parts).strip()
    
            if assigned_not_in_folder:
                # Přidej červenou hlášku pomocí HTML
                missing_str = ", ".join(str(n) for n in assigned_not_in_folder[:10])
                if len(assigned_not_in_folder) > 10:
                    missing_str += f"... a dalších {len(assigned_not_in_folder)-10}"
    
                error_html = f'❌ Přiřazeny fotky, které ve složce nejsou: {missing_str}'
                final_text = f"{base_text}{error_html}"
                self.missing_photos_widget.info_label.setText(final_text)
            else:
                # Pouze základní text bez chybové hlášky
                self.missing_photos_widget.info_label.setText(base_text)
    
        except Exception as e:
            self.update_log(f"⚠️ Chyba při kontrole chybějících fotek: {e}")
            pass

    def _on_clover_dir_changed(self, _path: str):
        """Při změně obsahu složky čtyřlístků aktualizuj přehled i validaci."""
        try:
            # Tyto rychlé operace mohou běžet vždy
            self.update_clover_stats_label()
            self.validate_clover_range()
    
            # Zkontrolujeme zámek, než spustíme náročné aktualizace seznamů
            if not self._photo_updates_enabled:
                self.update_log("ℹ️ Změna ve složce detekována, ale obnova seznamu je pozastavena.")
                return
    
            # Pokud není zamčeno, aktualizujeme oba seznamy fotek
            self.update_missing_photos_list()
            self.update_status_photos_list()
    
            # NOVÉ: po refreshi případně znovu označit požadovanou fotku
            try:
                pending_num = getattr(self, "_pending_reselect_photo_number", None)
                if pending_num is not None and hasattr(self, "missing_photos_widget") and self.missing_photos_widget:
                    # Provést reselect v seznamu „Analýza fotek“
                    self.missing_photos_widget._select_photo_in_list(int(pending_num))
                # Vyčistit pending reselect
                self._pending_reselect_photo_number = None
            except Exception:
                # Bezpečný no‑op; reselect nesmí shodit UI
                pass
    
        except Exception:
            # Tichá chyba, aby aplikace nespadla při rychlých změnách
            pass

    def get_photo_to_state_mapping(self):
        """Získá mapování foto_číslo -> stav z JSON konfigurace stavů"""
        try:
            config_text = self.status_config_text.toPlainText().strip()
            if not config_text:
                return {}
                
            data = json.loads(config_text)
            if not isinstance(data, dict):
                return {}
                
            photo_to_state = {}
            
            for state_name, number_list in data.items():
                if not isinstance(number_list, list):
                    continue
                    
                for item in number_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
                        
                    if '-' in item_str:
                        try:
                            start_str, end_str = item_str.split('-', 1)
                            start_num = int(start_str.strip())
                            end_num = int(end_str.strip())
                            if start_num > end_num:
                                start_num, end_num = end_num, start_num
                                
                            for num in range(start_num, end_num + 1):
                                if num in photo_to_state:
                                    # Duplikátní přiřazení - označíme speciálně
                                    if isinstance(photo_to_state[num], str):
                                        photo_to_state[num] = [photo_to_state[num], state_name]
                                    else:
                                        photo_to_state[num].append(state_name)
                                else:
                                    photo_to_state[num] = state_name
                        except ValueError:
                            continue
                    else:
                        try:
                            num = int(item_str)
                            if num in photo_to_state:
                                # Duplikátní přiřazení
                                if isinstance(photo_to_state[num], str):
                                    photo_to_state[num] = [photo_to_state[num], state_name]
                                else:
                                    photo_to_state[num].append(state_name)
                            else:
                                photo_to_state[num] = state_name
                        except ValueError:
                            continue
                            
            return photo_to_state
            
        except json.JSONDecodeError:
            return {}
        except Exception as e:
            self.update_log(f"❌ Chyba při parsování stavů: {e}")
            return {}
    
    def check_duplicate_states_real_time(self):
        """Real-time kontrola duplikátních stavů přiřazených jedné fotce"""
        try:
            photo_to_state = self.get_photo_to_state_mapping()
            
            # Najdi fotky s více stavy
            duplicate_states = {}
            for photo_num, state_info in photo_to_state.items():
                if isinstance(state_info, list):  # Více stavů
                    duplicate_states[photo_num] = state_info
                    
            self._update_duplicate_states_indicator(duplicate_states)
            
        except Exception:
            # Tichá chyba - nenarušuj UI
            pass
    
    def _update_duplicate_states_indicator(self, duplicate_states: dict):
        """Aktualizuj indikátor duplikátních stavů"""
        if not hasattr(self, 'duplicate_states_indicator'):
            return
            
        if duplicate_states:
            duplicates_list = sorted(duplicate_states.keys())
            if len(duplicates_list) <= 10:
                duplicates_str = ", ".join(str(num) for num in duplicates_list)
            else:
                duplicates_str = ", ".join(str(num) for num in duplicates_list[:8]) + f", ... (+{len(duplicates_list)-8})"
                
            # Vytvoř detail string pro tooltip
            detail_lines = []
            for photo_num in sorted(duplicate_states.keys())[:5]:  # Max 5 pro tooltip
                states = duplicate_states[photo_num]
                detail_lines.append(f"Fotka {photo_num}: {', '.join(states)}")
            if len(duplicate_states) > 5:
                detail_lines.append(f"... a dalších {len(duplicate_states)-5} fotek")
                
            self.duplicate_states_indicator.setText(f"⚠️ Duplikátní stavy: {duplicates_str}")
            self.duplicate_states_indicator.setToolTip("Fotky s více přiřazenými stavy:\n" + "\n".join(detail_lines))
            self.duplicate_states_indicator.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    background-color: #fadbd8;
                    border: 1px solid #e74c3c;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.duplicate_states_indicator.setVisible(True)
        else:
            self.duplicate_states_indicator.setVisible(False)

    # TUTO CELOU FUNKCI ODSTRAŇTE ZE SOUBORU
    def update_state_photos_list(self):
        """Aktualizuje seznam fotek, které ještě nemají přiřazený stav"""
        if not hasattr(self, 'missing_photos_widget'):
            return
        # Získej fotky se stavem
        photo_to_state = self.get_photo_to_state_mapping()
        photos_with_states = set()
        for photo_num, state_info in photo_to_state.items():
            if isinstance(state_info, str):
                photos_with_states.add(photo_num)
            elif isinstance(state_info, list):
                photos_with_states.add(photo_num) # I duplikátní stavy počítáme jako "má stav"
        # Aktualizuj missing photos widget s excludovanými fotkami
        clover_path = self.edit_clover_path.text().strip()
        json_numbers = self.extract_numbers_from_location_json()
        # Rozšiř json_numbers o fotky se stavem (aby nebyly v missing)
        json_numbers_with_states = set(json_numbers).union(photos_with_states)
        self.missing_photos_widget.update_missing_photos(clover_path, list(json_numbers_with_states))

    def _refresh_clover_watcher(self):
        """Sleduj aktuální cestu k čtyřlístkům a ihned aktualizuj přehled."""
        if not hasattr(self, '_clover_watcher'):
            return
        
        try:
            old_dirs = self._clover_watcher.directories()
            if old_dirs:
                self._clover_watcher.removePaths(old_dirs)
        except Exception:
            pass
        
        new_path = (self.edit_clover_path.text() or "").strip()
        if new_path and os.path.isdir(new_path):
            self._clover_watcher.addPath(new_path)
        
        # Po přepnutí cesty ihned přepočítej přehled a validaci
        self._on_clover_dir_changed(new_path)

    def _refresh_output_watcher(self):
        """Sleduj aktuální výstupní složku a průběžně aktualizuj kontrolu výstupu."""
        if not hasattr(self, '_output_watcher'):
            return
        try:
            old_dirs = self._output_watcher.directories()
            if old_dirs:
                self._output_watcher.removePaths(old_dirs)
        except Exception:
            pass
        new_path = (self.edit_output_folder.text() or "").strip()
        if new_path and os.path.isdir(new_path):
            self._output_watcher.addPath(new_path)
        # Po přepnutí cesty ihned přepočítej “Kontrola výstupní složky PDF”
        self.update_full_pdf_path_preview()

    # ========== DARK THEME FUNCTIONS (z pdf_generator_window2.py) ==========
    
    def _dark_palette(self):
        """
        Paleta pro dark-theme MacOS vzhled, sladěná s hlavním oknem (StatusWidget/LogWidget).
        Používána pouze pro QSS; nezasahuje do logiky.
        """
        return {
            'bg': '#1e1e1e',  # hlavní tmavé pozadí
            'bg2': '#2b2b2b',  # sekundární panelové pozadí
            'text': '#e6e6e6',
            'muted': '#b0b0b0',
            'frame': '#555555',
            'frame2': '#888888',
            'accent': '#2196F3',  # modrý akcent (focus, aktivní tab)
            'accent_hover': '#90CAF9',
            'group_border': '#555555',
            # Palety tlačítek (konzistentní s hlavním oknem)
            'GREEN': ("#4CAF50", "#45a049", "#3d8b40"),
            'RED': ("#f44336", "#da190b", "#c1170a"),
            'BLUE': ("#2196F3", "#1976D2", "#1565C0"),
            'ORNG': ("#FF9800", "#F57C00", "#E65100"),
            'PURP': ("#8e44ad", "#7d3c98", "#6c3483"),
            'TEAL': ("#009688", "#00897B", "#00695C"),
            'GRAY': ("#616161", "#757575", "#424242"),
            # Strom souborů
            'tree_bg': '#1f1f1f',
            'tree_alt': '#242424',
            'tree_text': '#e6e6e6',
            'tree_sel': '#2a3b4f',
            'tree_sel_text': '#ffffff',
        }

    def _style_btn(self, btn, base, hover, pressed, min_w=None, min_h=32):
        """
        Sjednocený vzhled tlačítek ve stylu hlavního okna (dark-theme).
        Pouze QSS; žádná změna logiky nebo signálů.
        """
        if not btn:
            return
        if min_h:
            btn.setMinimumHeight(int(min_h))
        if min_w:
            btn.setMinimumWidth(int(min_w))
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {base};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{ background-color: #3a3a3a; color: #777777; }}
        """)

    def _apply_dark_theme_base_qss(self):
        """
        Základní dark QSS pro dialog – kompaktnější: menší písmo, menší paddingy/margins.
        """
        C = self._dark_palette()
        self.setStyleSheet(f"""
        /* Okno */
        QDialog {{
            background-color: {C['bg']};
            color: {C['text']};
            font-size: 11px;
        }}
        /* Skupiny */
        QGroupBox {{
            font-weight: bold;
            font-size: 12px;
            color: {C['text']};
            border: 1px solid {C['group_border']};
            border-radius: 6px;
            margin-top: 6px;
            padding-top: 6px;
            background-color: {C['bg2']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }}
        /* Tab widget a záložky */
        QTabWidget::pane {{
            border: 1px solid {C['group_border']};
            border-radius: 5px;
            background-color: {C['bg2']};
        }}
        QTabBar::tab {{
            background-color: #303030;
            color: {C['text']};
            padding: 6px 12px;
            margin-right: 1px;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
            font-weight: bold;
            font-size: 12px;
        }}
        QTabBar::tab:selected {{ background-color: {C['accent']}; color: #ffffff; }}
        QTabBar::tab:hover {{ background-color: {C['accent_hover']}; color: #000000; }}
    
        /* Textové vstupy */
        QLineEdit, QPlainTextEdit, QTextEdit {{
            padding: 4px 8px;
            border: 1px solid {C['frame']};
            border-radius: 4px;
            font-size: 11px;
            background-color: #212121;
            color: {C['text']};
            selection-background-color: {C['accent']};
            selection-color: #ffffff;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
            border: 1px solid {C['accent']};
            background-color: #252525;
        }}
    
        /* Číselníky */
        QSpinBox, QDoubleSpinBox {{
            padding: 3px 6px;
            border: 1px solid {C['frame']};
            border-radius: 4px;
            font-size: 11px;
            background-color: #212121;
            color: {C['text']};
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {C['accent']};
            background-color: #252525;
        }}
    
        /* Checkboxy a labely */
        QCheckBox {{ font-size: 11px; color: {C['text']}; }}
        QLabel {{ font-size: 11px; color: {C['text']}; }}
    
        /* Progress bar – kompaktnější výška */
        QProgressBar {{
            border: 1px solid {C['frame']};
            border-radius: 5px;
            text-align: center;
            font-weight: bold;
            font-size: 11px;
            background-color: #212121;
            color: {C['muted']};
            min-height: 14px;
        }}
        QProgressBar::chunk {{
            background-color: {C['accent']};
            border-radius: 4px;
        }}
        """)

    def _style_file_trees_dark(self):
        """
        Dark-theme vzhled QTreeView stromů (souborový prohlížeč) v PDF okně,
        včetně hlaviček; bez zásahu do modelů, D&D nebo kontextových nabídek.
        """
        C = self._dark_palette()
        from PySide6.QtWidgets import QTreeView

        trees = []
        for gb in [getattr(self, 'location_tree', None),
                   getattr(self, 'clover_tree', None),
                   getattr(self, 'output_tree', None),
                   getattr(self, 'copy_tree', None)]:
            if gb:
                tv = gb.findChild(QTreeView)
                if tv:
                    trees.append(tv)

        tree_qss = f"""
            QTreeView {{
                background-color: {C['tree_bg']};
                alternate-background-color: {C['tree_alt']};
                color: {C['tree_text']};
                border: 1px solid {C['frame']};
                border-radius: 6px;
                selection-background-color: {C['tree_sel']};
                selection-color: {C['tree_sel_text']};
                show-decoration-selected: 1;
            }}
            QTreeView::item:hover {{ background-color: #2a2a2a; }}
            QHeaderView::section {{
                background-color: #2a2a2a;
                color: {C['text']};
                padding: 4px 6px;
                border: 1px solid {C['frame']};
            }}
        """

        for tv in trees:
            try:
                tv.setAlternatingRowColors(True)
                tv.setStyleSheet(tree_qss)
            except Exception:
                pass

        # Cesty (labely nad stromy) – zjemnit; ponechat monospace
        from PySide6.QtWidgets import QLabel
        for gb in [getattr(self, 'location_tree', None),
                   getattr(self, 'clover_tree', None),
                   getattr(self, 'output_tree', None),
                   getattr(self, 'copy_tree', None)]:
            try:
                if not gb:
                    continue
                labels = gb.findChildren(QLabel)
                for lb in labels:
                    lb.setStyleSheet(f"""
                        QLabel {{
                            background-color: #252525;
                            border: 1px solid {C['frame']};
                            border-radius: 4px;
                            padding: 6px 12px;
                            font-size: 12px;
                            color: {C['muted']};
                            font-family: monospace;
                        }}
                    """)
            except Exception:
                pass
            
    def update_log_and_progress(self, message: str):
        """
        Zpracuje zprávu z vlákna. Pokud obsahuje prefix pro progress bar,
        aktualizuje ho. Jinak zprávu zapíše do logu.
        """
        if message.startswith("phase_"):
            try:
                phase, val_str = message.split(':', 1)
                val = int(val_str)
                
                if phase == "phase_loading":
                    self.progress_bar_loading.setValue(val)
                elif phase == "phase_combining":
                    self.progress_bar_combining.setValue(val)
                elif phase == "phase_saving":
                    self.progress_bar_saving.setValue(val)
            except (ValueError, IndexError):
                self.update_log(message) # Pokud parsování selže, zapíšeme jako log
        else:
            self.update_log(message)
        
    
    def update_progress_bars(self, message: str):
        """
        Aktualizuje tři progress bary podle zprávy ve formátu:
        \"phase_name:value\", například \"phase_loading:50\".
        """
        try:
            if ':' not in message:
                return
            phase, val_str = message.split(':', 1)
            val = int(val_str)
            
            # Zobrazit progress bary pokud nejsou viditelné
            if not self.progress_bar_loading.isVisible():
                self.progress_bar_loading.setVisible(True)
            if not self.progress_bar_combining.isVisible():
                self.progress_bar_combining.setVisible(True)
            if not self.progress_bar_saving.isVisible():
                self.progress_bar_saving.setVisible(True)
            
            if phase == "phase_loading":
                self.progress_bar_loading.setValue(val)
            elif phase == "phase_combining":
                self.progress_bar_combining.setValue(val)
            elif phase == "phase_saving":
                self.progress_bar_saving.setValue(val)
    
            # Skrytí progress barů, když jsou 100 % u všech
            if (self.progress_bar_loading.value() == 100 and
                self.progress_bar_combining.value() == 100 and
                self.progress_bar_saving.value() == 100):
                self.progress_bar_loading.setVisible(False)
                self.progress_bar_combining.setVisible(False)
                self.progress_bar_saving.setVisible(False)
        except Exception:
            pass

            
    def _install_log_clear_button(self, parent_container):
        """Vytvoří a ukotví malé kulaté Clear tlačítko jako překryvné dítě v pravém horním rohu log oblasti."""
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtCore import Qt, QObject, QEvent
    
        if not hasattr(self, "btn_log_clear") or self.btn_log_clear is None:
            self.btn_log_clear = QPushButton("✕", parent=parent_container)
            self.btn_log_clear.setToolTip("Vymazat všechny logy")
            self.btn_log_clear.setFixedSize(28, 28)
            self.btn_log_clear.setCursor(Qt.PointingHandCursor)
            
            # Tmavý styl konzistentní s PDF oknem
            self.btn_log_clear.setStyleSheet("""
            QPushButton {
                background-color: rgba(198, 40, 40, 160);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 180);
                border-radius: 14px;
                font-weight: 700;
                font-size: 14px;
            }
            QPushButton:hover { 
                background-color: rgba(198, 40, 40, 200); 
            }
            QPushButton:pressed { 
                background-color: rgba(198, 40, 40, 240); 
            }
            QPushButton:disabled {
                background-color: rgba(198, 40, 40, 90);
                color: rgba(255,255,255,140);
            }
            """)
            
            self.btn_log_clear.clicked.connect(self._on_log_clear_click)
            self.btn_log_clear.show()
            self.btn_log_clear.raise_()
    
            def _position_clear_button():
                try:
                    margin = 8
                    bx = max(0, parent_container.width() - self.btn_log_clear.width() - margin)
                    by = margin
                    self.btn_log_clear.move(bx, by)
                    self.btn_log_clear.raise_()
                except Exception:
                    pass
    
            self._position_log_clear_button = _position_clear_button
            _position_clear_button()
    
            # Event filter pro auto-reposition při Show/Resize
            class _ClearPosFilter(QObject):
                def __init__(self, outer):
                    super().__init__(outer)
                    self.outer = outer
    
                def eventFilter(self, obj, event):
                    if event.type() in (QEvent.Show, QEvent.Resize):
                        try:
                            self.outer._position_log_clear_button()
                        except Exception:
                            pass
                    return False
    
            if not hasattr(self, "_log_clear_pos_filter"):
                self._log_clear_pos_filter = _ClearPosFilter(self)
                parent_container.installEventFilter(self._log_clear_pos_filter)

    
    def _on_log_clear_click(self):
        """Handler pro kliknutí na tlačítko vymazání logu - bez potvrzovacího dialogu."""
        try:
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.clear()
                self.update_log("🗑️ Log vymazán uživatelem")
        except Exception as e:
            print(f"Chyba při mazání logu: {e}")


    def _setup_dynamic_tab_widths(self):
        """Nastavení dynamické šířky záložek - jiný přístup"""
        try:
            # 1) Zakázání scroll tlačítek
            self.tabs.setUsesScrollButtons(False)
            
            # 2) Nastavení tab bar policy
            tab_bar = self.tabs.tabBar()
            if tab_bar:
                tab_bar.setExpanding(False)
                tab_bar.setDrawBase(False)
                
                # 3) Nastavení minimální šířky pro každou záložku
                tab_texts = []
                for i in range(self.tabs.count()):
                    tab_texts.append(self.tabs.tabText(i))
                
                # 4) Výpočet potřebné šířky podle nejdelšího textu
                font = tab_bar.font()
                font.setBold(True)
                font.setPointSize(12)
                
                from PySide6.QtGui import QFontMetrics
                font_metrics = QFontMetrics(font)
                
                max_width = 0
                for text in tab_texts:
                    text_width = font_metrics.horizontalAdvance(text)
                    needed_width = text_width + 40  # padding
                    max_width = max(max_width, needed_width)
                
                # 5) Nastavení minimální šířky celého tab widgetu
                total_width = max_width * len(tab_texts) + 20  # +20 pro okraje
                self.tabs.setMinimumWidth(total_width)
                
                # 6) Nastavení tab size policy
                for i in range(self.tabs.count()):
                    tab_bar.setTabData(i, max_width)
                    
        except Exception as e:
            if hasattr(self, 'update_log'):
                self.update_log(f"⚠️ Chyba při nastavování šířky záložek: {e}")

    def adopt_dark_theme_after_ui(self):
        """
        Aplikuje dark-theme vzhled; kompaktnější záložky a ovládací prvky.
        """
        C = self._dark_palette()
        self._apply_dark_theme_base_qss()
    
        # Kompaktní záložky – bez elide, menší padding
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.ElideNone)
        tab_qss = f"""
        QTabWidget::pane {{
            border: 1px solid {C['group_border']};
            border-radius: 5px;
            background-color: {C['bg2']};
        }}
        QTabBar::tab {{
            background-color: #303030;
            color: {C['text']};
            padding: 6px 10px;
            margin-right: 1px;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
            font-weight: bold;
            font-size: 12px;
        }}
        QTabBar::tab:selected {{
            background-color: {C['accent']};
            color: #ffffff;
        }}
        QTabBar::tab:hover {{
            background-color: {C['accent_hover']};
            color: #000000;
        }}
        """
        self.tabs.setStyleSheet(tab_qss)
    
        # Stromy souborů – zachovat, jen se volá stávající styling
        self._style_file_trees_dark()
    
        # Kompaktnější lineedity
        def _style_lineedit(w):
            if not w:
                return
            w.setStyleSheet(w.styleSheet() + f"""
            QLineEdit {{
                background-color: #212121;
                color: {C['text']};
                border: 1px solid {C['frame']};
                border-radius: 4px;
                padding: 4px 8px;
                selection-background-color: {C['accent']};
                selection-color: #ffffff;
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C['accent']};
                background-color: #252525;
            }}
            """)
            try:
                if w.minimumHeight() > 34:
                    w.setMinimumHeight(28)
            except Exception:
                pass
    
        for name in ['edit_location_path', 'edit_clover_path', 'edit_output_folder',
                     'edit_pdf_filename', 'edit_copy_folder']:
            _style_lineedit(getattr(self, name, None))
    
        # Tlačítka – mírně menší výšky a šířky
        GREEN, RED, BLUE, ORNG, PURP, TEAL, GRAY = (
            C['GREEN'], C['RED'], C['BLUE'], C['ORNG'], C['PURP'], C['TEAL'], C['GRAY']
        )
        self._style_btn(getattr(self, 'btn_generate', None), *GREEN, min_w=150, min_h=36)
        self._style_btn(getattr(self, 'btn_stop', None), *RED, min_w=120, min_h=36)
        self._style_btn(getattr(self, 'btn_export_json', None), *BLUE, min_w=180, min_h=36)
        self._style_btn(getattr(self, 'btn_toggle_display', None), *PURP, min_w=120, min_h=34)
        self._style_btn(getattr(self, 'btn_open_output', None), *TEAL, min_w=170, min_h=30)
        self._style_btn(getattr(self, 'btn_close', None), *GRAY, min_w=120, min_h=30)
    
        # Browse tlačítka kompaktnější
        for attr_name in dir(self):
            if attr_name.startswith('btn_browse') or attr_name == 'btn_generate_filename':
                btn = getattr(self, attr_name, None)
                if btn:
                    if attr_name == 'btn_generate_filename':
                        self._style_btn(btn, *ORNG, min_w=40, min_h=28)
                    else:
                        self._style_btn(btn, *BLUE, min_w=40, min_h=28)
    
        # Log panel – menší písmo, již nastaveno jinde; jen QSS pro jistotu
        if hasattr(self, 'log_text') and self.log_text:
            self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: #1a1a1a;
                color: {C['text']};
                border: 1px solid {C['frame']};
                border-radius: 6px;
                font-family: monospace;
                font-size: 9px;
                selection-background-color: {C['accent']};
                selection-color: #ffffff;
            }}
            """)

    # ========== PŮVODNÍ FUNKCIONALITA (z pdf_generator_window.py) ==========
        
    def initial_sync_trees(self):
        """Počáteční synchronizace stromových struktur po spuštění aplikace"""
        try:
            if hasattr(self, 'location_tree') and hasattr(self, 'clover_tree') and \
               hasattr(self, 'output_tree') and hasattr(self, 'copy_tree'):
                self.sync_paths_to_trees()
                self.update_log("🚀 Aplikace spuštěna - stromové struktury synchronizovány")
            else:
                # Pokud stromy ještě nejsou vytvořené, zkusíme to znovu za chvíli
                QTimer.singleShot(200, self.initial_sync_trees)
        except Exception as e:
            self.update_log(f"⚠️ Chyba při počáteční synchronizaci: {str(e)}")

        
    def validate_clover_range(self):
        """Real-time validace existence čtyřlístků v rozsahu N-M."""
        if not hasattr(self, 'clover_validation_label'): 
            return
            
        n, m = self.spin_n.value(), self.spin_m.value()
        clover_path = self.edit_clover_path.text().strip()
        
        if not clover_path or not os.path.isdir(clover_path):
            self.clover_validation_label.setText("📁 Zadejte platnou cestu k čtyřlístkům.")
            return
            
        if n > m:
            self.clover_validation_label.setText("❌ Chyba: N nemůže být větší než M.")
            return
            
        try:
            files = os.listdir(clover_path)
            exts = {'.jpg', '.jpeg', '.png', '.heic', '.heif'}
            found_numbers = set()
            
            for file in files:
                if Path(file).suffix.lower() in exts:
                    try:
                        num_part = file.split('+')[0]
                        found_numbers.add(int(num_part))
                    except (ValueError, IndexError):
                        continue
            
            required = set(range(n, m + 1))
            missing = required - found_numbers
            
            if not missing:
                self.clover_validation_label.setText(f"✅ Všech {len(required)} čtyřlístků nalezeno.")
            else:
                missing_str = ", ".join(map(str, sorted(list(missing))[:5]))
                if len(missing) > 5: 
                    missing_str += "..."
                self.clover_validation_label.setText(f"⚠️ Chybí {len(missing)} čtyřlístků: {missing_str}")
                
        except Exception as e:
            self.clover_validation_label.setText(f"❌ Chyba při kontrole: {e}")

    def create_log_area(self):
        log_group = QGroupBox("📋 Log generování")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(6)
    
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        # jemně menší font
        self.log_text.setFont(self._get_monospace_font(size=9))
    
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        return log_group

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNKCE: create_file_browser_tab
    # NAHRAĎ TOUTO VERZÍ (sjednocená záložka, bez vnořování dalších groupboxů;
    #                     DnD funguje díky FileTreeView z create_file_tree_widget)
    
    def create_file_browser_tab(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
        from PySide6.QtWidgets import QTreeView  # pro nalezení vnořeného stromu
    
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setSpacing(6)
        tab_layout.setContentsMargins(8, 8, 8, 8)
    
        # Fixní cesty panelů
        output_path  = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/PDF k vytištění/"
        printed_path = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Vytištěné PDF/"
    
        # POUŽIJEME PŘÍMO jednotný widget (groupbox) z create_file_tree_widget – žádné další obaly
        left_widget  = self.create_file_tree_widget("💾 Výstupní složka", output_path)
        right_widget = self.create_file_tree_widget("🖨️ Vytištěné PDF", printed_path)
    
        # Vedle sebe, stejná velikost, plná výška
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 0, 0, 0)
    
        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
        row.addWidget(left_widget, 1)
        row.addWidget(right_widget, 1)
    
        tab_layout.addLayout(row, 1)
        tab_layout.setStretch(0, 1)
    
        # Ulož reference na vnořené stromy (FileTreeView je potomkem QTreeView)
        self.output_tree  = left_widget.findChild(QTreeView)
        self.printed_tree = right_widget.findChild(QTreeView)
    
        self.tabs.addTab(tab, "📂 Přehled vygenerovaných PDF")

    def sync_paths_to_trees(self):
        """(removed) Dřívější tlačítko 'Synchronizovat cesty' bylo odstraněno."""
        return

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: create_file_tree_widget
    # NAHRAĎ CELÝ OBSAH FUNKCE TOUTO VERZÍ (oprava: QAbstractItemView.ExtendedSelection)
    
    def create_file_tree_widget(self, title, path):
        """Vytvoří widget se stromovou strukturou souborů – jednotný vzhled, plná výška, funkční DnD (FileTreeView)."""
        from PySide6.QtWidgets import (
            QGroupBox, QVBoxLayout, QLabel, QSizePolicy, QFileSystemModel, QHeaderView, QAbstractItemView
        )
        from PySide6.QtCore import Qt, QSize
        import os
    
        group = QGroupBox(title)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
    
        # 1) Hlavička s plnou cestou (jednořádková, kopírovatelná)
        path_label = QLabel()
        path_label.setWordWrap(False)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if path and os.path.exists(path):
            path_label.setText(f"📂 {path}")
            path_label.setToolTip(path)
        else:
            path_label.setText("📂 Cesta není nastavena nebo neexistuje")
        layout.addWidget(path_label)
    
        # 2) Strom – použití FileTreeView (má implementovaný hromadný Drag&Drop MOVE)
        tree = FileTreeView()
        tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tree.setUniformRowHeights(True)
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(False)
        tree.setIndentation(18)
        tree.setIconSize(QSize(16, 16))
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)  # ← FIX: použít enum z QAbstractItemView
    
        # Jednotný stylesheet (obě strany identicky)
        tree.setStyleSheet("""
            QTreeView {
                background-color: #1f1f1f;
                color: #e6e6e6;
                border: 1px solid #555;
                outline: none;
            }
            QTreeView::item { padding: 2px 6px; }
            QTreeView::item:selected { background-color: #2a3b4f; }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #cccccc;
                padding: 2px 6px;
                border: 1px solid #444;
            }
        """)
    
        # 3) Model + filtry
        model = QFileSystemModel()
        model.setRootPath(path if path and os.path.exists(path) else "")
    
        tl = (title or "").lower()
        if "čtyřlíst" in tl or "clover" in tl:
            model.setNameFilters(["*.jpg", "*.jpeg", "*.png", "*.heic", "*.heif", "*.tiff", "*.tif", "*.bmp"])
            model.setNameFilterDisables(False)
        elif "mapky" in tl or "location" in tl:
            model.setNameFilters(["*.jpg", "*.jpeg", "*.png", "*.pdf"])
            model.setNameFilterDisables(False)
        elif "výstup" in tl or "output" in tl or "pdf" in tl or "vytištěné" in tl:
            model.setNameFilters(["*.pdf"])
            model.setNameFilterDisables(False)
    
        tree.setModel(model)
        if path and os.path.exists(path):
            root_index = model.index(path)
            tree.setRootIndex(root_index)
    
        # Sloupce + header – sjednocené
        header = tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        tree.hideColumn(1)  # Size
        tree.hideColumn(2)  # Type
        tree.hideColumn(3)  # Date Modified
    
        # Kontextové menu – zachováno
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda pos: self.show_tree_context_menu(tree, pos, model)
        )
    
        # Reference (pro refresh po DnD ve FileTreeView)
        tree.file_model = model
        tree.root_path = path or ""
        tree.path_label = path_label
    
        layout.addWidget(tree, stretch=1)
        group.setLayout(layout)
        return group
    
    def show_tree_context_menu(self, tree, position, model):
        """Zobrazí kontextové menu pro stromovou strukturu"""

        indexes = tree.selectedIndexes()
        if not indexes:
            return

        menu = QMenu(tree)

        # Získání cesty k souboru
        index = indexes[0]
        file_path = model.filePath(index)
        is_dir = model.isDir(index)

        # Akce menu
        if not is_dir:
            # Otevřít soubor
            open_action = QAction("📂 Otevřít", menu)
            open_action.triggered.connect(lambda: self.open_file(file_path))
            menu.addAction(open_action)

            menu.addSeparator()

        # Přejmenovat
        rename_action = QAction("✏️ Přejmenovat", menu)
        rename_action.triggered.connect(lambda: self.rename_file(tree, model, index))
        menu.addAction(rename_action)

        # Kopírovat
        copy_action = QAction("📋 Kopírovat", menu)
        copy_action.triggered.connect(lambda: self.copy_files(tree, model))
        menu.addAction(copy_action)

        # Vložit (pokud je něco ve schránce)
        if hasattr(self, 'clipboard_files') and self.clipboard_files:
            paste_action = QAction("📥 Vložit", menu)
            paste_action.triggered.connect(lambda: self.paste_files(tree, model, index))
            menu.addAction(paste_action)

        menu.addSeparator()

        # Smazat
        delete_action = QAction("🗑️ Smazat", menu)
        delete_action.triggered.connect(lambda: self.delete_files(tree, model))
        menu.addAction(delete_action)

        menu.addSeparator()

        # Obnovit
        refresh_action = QAction("🔄 Obnovit", menu)
        refresh_action.triggered.connect(lambda: self.refresh_tree(tree))
        menu.addAction(refresh_action)

        menu.exec_(tree.mapToGlobal(position))

    def open_file(self, file_path):
        """Otevře soubor v defaultní aplikaci"""
        import subprocess
        import platform

        try:
            if platform.system() == 'Darwin':  # macOS
                subprocess.Popen(['open', file_path])
            elif platform.system() == 'Windows':
                subprocess.Popen(['start', file_path], shell=True)
            else:  # Linux
                subprocess.Popen(['xdg-open', file_path])
            self.update_log(f"📂 Otevřen soubor: {os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.warning(self, "Chyba", f"Nepodařilo se otevřít soubor:\n{str(e)}")

    def rename_file(self, tree, model, index):
        """Přejmenuje soubor nebo složku"""
        from PySide6.QtWidgets import QInputDialog

        old_path = model.filePath(index)
        old_name = os.path.basename(old_path)

        new_name, ok = QInputDialog.getText(
            self,
            "Přejmenovat",
            "Nový název:",
            text=old_name
        )

        if ok and new_name and new_name != old_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            try:
                os.rename(old_path, new_path)
                self.update_log(f"✏️ Přejmenováno: {old_name} → {new_name}")
                self.refresh_tree(tree)
            except Exception as e:
                QMessageBox.warning(self, "Chyba", f"Nepodařilo se přejmenovat:\n{str(e)}")

    def copy_files(self, tree, model):
        """Zkopíruje vybrané soubory do schránky"""
        indexes = tree.selectedIndexes()
        if not indexes:
            return

        # Získání unikátních cest (každý soubor má 4 indexy - název, velikost, typ, datum)
        paths = list(set([model.filePath(idx) for idx in indexes if idx.column() == 0]))

        self.clipboard_files = paths
        self.clipboard_operation = 'copy'
        self.update_log(f"📋 Zkopírováno {len(paths)} položek do schránky")

    def _get_monospace_font(self, size=11):
        """Vrátí platformově-specifický monospace font."""
        if sys.platform == "darwin":
            return QFont("Monaco", size)
        elif sys.platform.startswith("win"):
            return QFont("Consolas", size)
        else:
            return QFont("DejaVu Sans Mono", size)

    def paste_files(self, tree, model, index):
        """Vloží soubory ze schránky"""
        import shutil

        if not hasattr(self, 'clipboard_files') or not self.clipboard_files:
            return

        # Určení cílové složky
        target_path = model.filePath(index)
        if not model.isDir(index):
            target_path = os.path.dirname(target_path)

        success_count = 0
        for source_path in self.clipboard_files:
            try:
                filename = os.path.basename(source_path)
                dest_path = os.path.join(target_path, filename)

                # Kontrola duplicity
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dest_path):
                        dest_path = os.path.join(target_path, f"{base}_{counter}{ext}")
                        counter += 1

                if os.path.isdir(source_path):
                    shutil.copytree(source_path, dest_path)
                else:
                    shutil.copy2(source_path, dest_path)
                success_count += 1

            except Exception as e:
                self.update_log(f"❌ Chyba při kopírování {filename}: {str(e)}")

        if success_count > 0:
            self.update_log(f"✅ Vloženo {success_count} položek")
            self.refresh_tree(tree)

    def delete_files(self, tree, model):
        """Smaže vybrané soubory"""
        import shutil

        indexes = tree.selectedIndexes()
        if not indexes:
            return

        # Získání unikátních cest
        paths = list(set([model.filePath(idx) for idx in indexes if idx.column() == 0]))

        # Potvrzení
        reply = QMessageBox.question(
            self,
            "Potvrzení smazání",
            f"Opravdu chcete smazat {len(paths)} položek?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            success_count = 0
            for path in paths:
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    success_count += 1
                except Exception as e:
                    self.update_log(f"❌ Chyba při mazání {os.path.basename(path)}: {str(e)}")

            if success_count > 0:
                self.update_log(f"🗑️ Smazáno {success_count} položek")
                self.refresh_tree(tree)

    def refresh_tree(self, tree):
        """Obnoví stromovou strukturu"""
        if hasattr(tree, 'file_model'):
            # Trigger refresh modelu
            tree.file_model.setRootPath("")
            tree.file_model.setRootPath(tree.root_path)
            if tree.root_path and os.path.exists(tree.root_path):
                tree.setRootIndex(tree.file_model.index(tree.root_path))

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # (POKUD V TÉTO TŘÍDĚ EXISTUJÍ NÁSLEDUJÍCÍ HANDLERY, NAHRAĎ JE NO-OP VERZÍ)
    # Důvod: tlačítka byla odstraněna, ať nic jiného v kódu nespadne při případných odkazech.
    
    def refresh_all_trees(self):
        """(removed) Dřívější tlačítko 'Obnovit všechny stromy' bylo odstraněno."""
        return
        
    def init_ui(self):
        """
        Sestavení kompletního uživatelského rozhraní okna pro generátor PDF – kompaktnější rozvržení.
        """
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(14, 14, 14, 14)
    
        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)
    
        # Levá část
        left_widget = QWidget()
        self.left_layout = QVBoxLayout(left_widget)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(12)
    
        self.tabs = QTabWidget()
        self.create_basic_settings_tab()
        self.create_location_config_tab()
        self.create_notes_tab()          # ✅ Nejdříve vytvořit notes_text
        self.create_status_config_tab()  # ✅ Teprve pak na něj odkazovat
        self.create_file_browser_tab()
        self.left_layout.addWidget(self.tabs)
    
        # Kompaktnější progress bary
        self.progress_bar_loading = QProgressBar()
        self.progress_bar_loading.setFormat("📥 Načítání dat: %p%")
        self.progress_bar_loading.setVisible(False)
        self.progress_bar_loading.setMinimumHeight(16)
    
        self.progress_bar_combining = QProgressBar()
        self.progress_bar_combining.setFormat("🎨 Kombinování obrázků: %p%")
        self.progress_bar_combining.setVisible(False)
        self.progress_bar_combining.setMinimumHeight(16)
    
        self.progress_bar_saving = QProgressBar()
        self.progress_bar_saving.setFormat("💾 Ukládání PDF: %p%")
        self.progress_bar_saving.setVisible(False)
        self.progress_bar_saving.setMinimumHeight(16)
    
        self.left_layout.addWidget(self.progress_bar_loading)
        self.left_layout.addWidget(self.progress_bar_combining)
        self.left_layout.addWidget(self.progress_bar_saving)
    
        # Ovládací tlačítka
        button_widget = self.create_control_buttons()
        self.left_layout.addWidget(button_widget)
    
        # Pravá část – log panel užší
        log_group = self.create_log_area()
        log_group.setMinimumWidth(520)
        log_group.setMaximumWidth(640)
    
        content_layout.addWidget(left_widget, stretch=3)
        content_layout.addWidget(log_group, stretch=1)
        main_layout.addLayout(content_layout)
    
        self._mark_log_ready()
    
        # Signály (beze změn)
        self.spin_n.valueChanged.connect(self.update_pdf_filename)
        self.spin_m.valueChanged.connect(self.update_pdf_filename)
        self.edit_output_folder.textChanged.connect(self.update_full_pdf_path_preview)
    
        from PySide6.QtGui import QShortcut, QKeySequence
        sc_close = QShortcut(QKeySequence(QKeySequence.Close), self)
        sc_close.activated.connect(self.reject)
    
        self.setMinimumWidth(1400)
        self.tabs.setMinimumWidth(1100)
        
        if hasattr(self, 'notes_text'):
            self.notes_text.textChanged.connect(self.check_states_without_notes_real_time)


    def start_clover_validation_timer(self):
        """Spuštění automatické validace čtyřlístků každých 5 sekund"""
        if not self.clover_validation_enabled:
            self.clover_validation_enabled = True
            if not self.clover_validation_timer.isActive():
                self.clover_validation_timer.start(5000)  # 5 sekund = 5000ms
                if hasattr(self, 'update_log'):
                    self.update_log("🔄 Spuštěna automatická validace čtyřlístků (každých 5s)")

    def stop_clover_validation_timer(self):
        """Zastavení automatické validace čtyřlístků"""
        if self.clover_validation_enabled:
            self.clover_validation_enabled = False
            if self.clover_validation_timer.isActive():
                self.clover_validation_timer.stop()
                if hasattr(self, 'update_log'):
                    self.update_log("⏹️ Zastavena automatická validace čtyřlístků")

    def toggle_clover_validation_timer(self):
        """Přepnutí automatické validace čtyřlístků"""
        if self.clover_validation_enabled:
            self.stop_clover_validation_timer()
        else:
            # Spustí se automatically v validate_clover_range() pokud jsou podmínky splněny
            self.validate_clover_range()

    def create_control_buttons(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setSpacing(10)
        
        self.btn_generate = QPushButton("🚀 Generovat PDF")
        self.btn_stop = QPushButton("⏹️ Zastavit")
        self.btn_stop.setEnabled(False)
        
        # NOVÉ: Tlačítko pro export JSON nastavení
        self.btn_export_json = QPushButton("📤 Exportovat JSON nastavení")
        self.btn_export_json.setToolTip("Exportuje nastavení lokací, stavů a poznámek do jednoho JSON souboru")
        
        layout.addStretch()
        layout.addWidget(self.btn_generate)
        layout.addWidget(self.btn_stop)
        layout.addStretch()  # Oddělí levá tlačítka od pravého
        layout.addWidget(self.btn_export_json)  # Umístí zcela vpravo
        
        # Propojení signálů
        self.btn_generate.clicked.connect(self.generate_pdf)
        self.btn_stop.clicked.connect(self.stop_generation)
        self.btn_export_json.clicked.connect(self.export_json_settings)  # NOVÉ
        
        return widget

    # Ve třídě PDFGeneratorWindow v souboru pdf_generator_window.py

    def update_pdf_filename(self):
        """Aktualizuje název souboru v editovatelném poli podle rozsahu a počtu stránek."""
        if not self.checkbox_auto_filename.isChecked():
            self.label_pdf_filename.setText("Ruční název PDF")
            return
    
        n = self.spin_n.value()
        m = self.spin_m.value()
    
        if m < n:
            self.edit_pdf_filename.setText("Chybný rozsah N > M")
            self.label_pdf_filename.setText("Automatický název PDF (i při chybě)")
            self.update_full_pdf_path_preview()
            return
    
        pages_per_pdf = self.spin_pages_per_pdf.value()
        total_images = m - n + 1
        IMAGES_PER_PAGE = 5
        IMAGES_PER_PDF = IMAGES_PER_PAGE * pages_per_pdf
    
        if total_images <= 0:
            num_pdfs = 0
        else:
            num_pdfs = (total_images + IMAGES_PER_PDF - 1) // IMAGES_PER_PDF
    
        # ZDE JE POŽADOVANÁ ZMĚNA
        base_prefix = "F"
    
        filenames = []
        if num_pdfs <= 1:
            filenames.append(f"{base_prefix}-{n}-{m}.pdf")
            self.label_pdf_filename.setText("Automatický název PDF")
        else:
            for i in range(num_pdfs):
                start_num = n + (i * IMAGES_PER_PDF)
                end_num = min(m, start_num + IMAGES_PER_PDF - 1)
                filenames.append(f"{base_prefix}-{start_num}-{end_num}.pdf")
            self.label_pdf_filename.setText("Automatické názvy PDF")
    
        self.edit_pdf_filename.setText(", ".join(filenames))
        self.update_full_pdf_path_preview()


    def update_full_pdf_path_preview(self):
        """Aktualizuje náhled cesty k PDF a reaguje na změnu počtu stran."""
        output_folder = self.edit_output_folder.text().strip()
        
        if not self.checkbox_auto_filename.isChecked() or not output_folder:
            # ... (stávající kód pro manuální režim nebo chybějící složku) ...
            return

        n = self.spin_n.value()
        m = self.spin_m.value()
        pages_per_pdf = self.spin_pages_per_pdf.value()
        
        if m < n:
            self.label_full_pdf_path.setText("❌ Chybný rozsah (N > M)")
            self.label_full_pdf_path.setToolTip("")
            return
        
        total_images = m - n + 1
        IMAGES_PER_PAGE = 5
        IMAGES_PER_PDF = IMAGES_PER_PAGE * pages_per_pdf
        num_pdfs = (total_images + IMAGES_PER_PDF - 1) // IMAGES_PER_PDF if total_images > 0 else 1
        
        base_prefix = "E"
        future_files = []
        if num_pdfs <= 1:
            future_files.append(f"{base_prefix}-{n}-{m}.pdf")
        else:
            for i in range(num_pdfs):
                start_num = n + i * IMAGES_PER_PDF
                end_num = min(m, start_num + IMAGES_PER_PDF - 1)
                future_files.append(f"{base_prefix}-{start_num}-{end_num}.pdf")

        folder_exists = os.path.isdir(output_folder)
        existing_files = []
        non_existing_files = []
        
        if folder_exists:
            for fname in future_files:
                if os.path.exists(os.path.join(output_folder, fname)):
                    existing_files.append(fname)
                else:
                    non_existing_files.append(fname)

        # Sestavení zprávy pro UI
        tooltip_lines = [f"Výstupní složka: {output_folder}"]
        
        if not folder_exists:
            icon, color, bg_color, status = "❌", "#e74c3c", "#fadbd8", "Složka neexistuje!"
            tooltip_lines.append(f"Status: {status}")
        elif existing_files:
            icon, color, bg_color, status = "⚠️", "#f39c12", "#fef9e7", "Některé soubory budou přepsány!"
            tooltip_lines.append(f"Status: {status}")
            if existing_files:
                tooltip_lines.append("\nSoubory k přepsání:")
                tooltip_lines.extend([f"  - {f}" for f in existing_files])
            if non_existing_files:
                tooltip_lines.append("\nNové soubory k vytvoření:")
                tooltip_lines.extend([f"  - {f}" for f in non_existing_files])
        else:
            icon, color, bg_color, status = "✅", "#27ae60", "#d5f4e6", "Připraveno k vytvoření"
            tooltip_lines.append(f"Status: {status}")
            tooltip_lines.append("\nSoubory k vytvoření:")
            tooltip_lines.extend([f"  - {f}" for f in non_existing_files])
            
        main_text = f"{icon} {status}"
        if len(future_files) > 1:
            main_text = f"{icon} Celkem {len(future_files)} souborů. {status}"

        self.label_full_pdf_path.setText(main_text)
        self.label_full_pdf_path.setToolTip("\n".join(tooltip_lines))
        self.label_full_pdf_path.setStyleSheet(f"""
            QLabel {{
                color: {color}; font-style: italic; font-size: 12px; font-weight: bold;
                padding: 10px 15px; background-color: {bg_color}; border: 2px solid {color};
                border-radius: 6px; margin: 5px 0px;
            }}""")

    def on_auto_filename_toggled(self, checked):
        """Přepíná editovatelnost pole a aktualizuje název a label."""
        self.edit_pdf_filename.setEnabled(not checked)
        # Zavoláme hlavní metodu, která se postará o nastavení názvu i labelu
        self.update_pdf_filename()

    def create_basic_settings_tab(self):
        """Vytvoření tabu základních nastavení s novým rozvržením."""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(25)

        # Skupina: Rozsah čtyřlístků
        range_group = QGroupBox("🔢 Rozsah a stránkování") # Změněn název
        range_layout = QGridLayout(range_group)
        range_layout.setSpacing(15)
        
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 200000)
        self.spin_m = QSpinBox()
        self.spin_m.setRange(1, 200000)
        
        # NOVÝ PRVEK: Počet stran na PDF
        self.spin_pages_per_pdf = QSpinBox()
        self.spin_pages_per_pdf.setRange(1, 1000) # Rozsah 1-1000 stran
        self.spin_pages_per_pdf.setValue(10) # Výchozí hodnota

        range_layout.addWidget(QLabel("První čtyřlístek (N):"), 0, 0)
        range_layout.addWidget(self.spin_n, 0, 1)
        range_layout.addWidget(QLabel("Poslední čtyřlístek (M):"), 1, 0)
        range_layout.addWidget(self.spin_m, 1, 1)
        range_layout.addWidget(QLabel("Max. stran na jedno PDF:"), 2, 0)
        range_layout.addWidget(self.spin_pages_per_pdf, 2, 1)

        self.clover_validation_label = QLabel("Pro validaci zadejte cesty a rozsah.")
        self.clover_validation_label.setWordWrap(True)
        range_layout.addWidget(self.clover_validation_label, 3, 0, 1, 2)
        
        # --- Přehled min/max/počet ve složce čtyřlístků (nové) ---
        stats_row = 4  # další volný řádek v gridu
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(6)
        
        self.clover_stats_label = QLabel("Nalezeno: — (0)")
        self.clover_stats_label.setToolTip("Přehled čísel ve složce 'Obrázky ke zpracování'")
        
        btn_refresh_stats = QPushButton("↻")
        btn_refresh_stats.setFixedSize(28, 28)
        btn_refresh_stats.setToolTip("Obnovit přehled min–max–počet")
        btn_refresh_stats.clicked.connect(self.update_clover_stats_label)
        
        stats_layout.addWidget(self.clover_stats_label)
        stats_layout.addStretch()
        stats_layout.addWidget(btn_refresh_stats)
        
        range_layout.addLayout(stats_layout, stats_row, 0, 1, 2)

        # ✅ NOVÉ: Přehled stránek PDF
        pdf_stats_row = 5  # další volný řádek
        self.pdf_pages_stats_label = QLabel("Celkem stran: — | Poslední PDF: — stran")
        self.pdf_pages_stats_label.setToolTip("Přehled celkového počtu stran a stran v posledním PDF")
        self.pdf_pages_stats_label.setStyleSheet("""
            QLabel {
                color: #2196F3;
                font-weight: bold;
                padding: 4px 8px;
                background-color: #1e3a5f;
                border: 1px solid #2196F3;
                border-radius: 4px;
            }
        """)
        range_layout.addWidget(self.pdf_pages_stats_label, pdf_stats_row, 0, 1, 2)

        # Skupina: Cesty k souborům
        paths_group = QGroupBox("📁 Cesty k souborům a složkám")
        paths_layout = QGridLayout(paths_group)
        paths_layout.setSpacing(15)
        
        self.edit_location_path = QLineEdit()
        self.edit_clover_path = QLineEdit()
        self.edit_output_folder = QLineEdit()
        
        paths_layout.addWidget(QLabel("Cesta k mapkám lokací:"), 0, 0)
        paths_layout.addWidget(self._create_path_widget(self.edit_location_path), 0, 1)
        paths_layout.addWidget(QLabel("Cesta k fotkám čtyřlístků:"), 1, 0)
        paths_layout.addWidget(self._create_path_widget(self.edit_clover_path), 1, 1)
        paths_layout.addWidget(QLabel("Výstupní složka pro PDF:"), 2, 0)
        paths_layout.addWidget(self._create_path_widget(self.edit_output_folder), 2, 1)
        
        top_layout.addWidget(range_group)
        top_layout.addWidget(paths_group)
        main_layout.addLayout(top_layout)

        # Název PDF souboru (zbytek zůstává stejný)
        filename_group = QGroupBox("📄 Název PDF souboru")
        filename_layout = QGridLayout(filename_group)
        filename_layout.setSpacing(10)
        self.checkbox_auto_filename = QCheckBox("Generovat název automaticky (např. F-N-M.pdf)")
        self.checkbox_auto_filename.setChecked(True)
        self.checkbox_auto_filename.toggled.connect(self.on_auto_filename_toggled)
        self.edit_pdf_filename = QLineEdit()
        self.edit_pdf_filename.setEnabled(False)
        self.label_full_pdf_path = QLabel("Zadejte výstupní složku a název souboru")
        self.label_full_pdf_path.setWordWrap(True)
        filename_layout.addWidget(self.checkbox_auto_filename, 0, 0, 1, 2)
        self.label_pdf_filename = QLabel("Ruční název PDF:") # Uložíme si referenci
        filename_layout.addWidget(self.label_pdf_filename, 1, 0)
        filename_layout.addWidget(self.edit_pdf_filename, 1, 1)
        filename_layout.addWidget(QLabel("Kontrola výstupní složky PDF:"), 2, 0)
        filename_layout.addWidget(self.label_full_pdf_path, 2, 1)
        main_layout.addWidget(filename_group)

        copy_group = QGroupBox("📋 Kopírování a přejmenování miniatur")
        copy_layout = QHBoxLayout(copy_group)
        copy_layout.setSpacing(10)
        self.checkbox_copy_enabled = QCheckBox("Povolit kopírování")
        self.checkbox_copy_enabled.toggled.connect(lambda checked: self.edit_copy_folder.setEnabled(checked))
        self.edit_copy_folder = QLineEdit()
        self.edit_copy_folder.setEnabled(False)
        copy_layout.addWidget(self.checkbox_copy_enabled)
        copy_layout.addWidget(QLabel("Cílová složka pro kopie:"))
        copy_layout.addWidget(self._create_path_widget(self.edit_copy_folder))
        main_layout.addWidget(copy_group)
        main_layout.addStretch()

        self.tabs.addTab(tab, "⚙️ Základní nastavení")

        # Propojení signálů
        self.spin_n.valueChanged.connect(self._trigger_clover_validation)
        self.spin_m.valueChanged.connect(self._trigger_clover_validation)
        self.edit_clover_path.textChanged.connect(self.update_clover_stats_label)
        # NOVÉ: Přidejte tento řádek
        self.edit_clover_path.textChanged.connect(self.update_missing_photos_list)
        # NOVÉ: Připojení watcheru při změně cesty
        self.edit_clover_path.textChanged.connect(self._refresh_clover_watcher)
        self.edit_output_folder.textChanged.connect(self._refresh_output_watcher)
        
        # Všechny relevantní změny nyní volají JEDNU metodu pro aktualizaci názvu
        self.spin_n.valueChanged.connect(self.update_pdf_filename)
        self.spin_m.valueChanged.connect(self.update_pdf_filename)
        self.spin_pages_per_pdf.valueChanged.connect(self.update_pdf_filename)

        # ✅ NOVÉ: Připojení aktualizace statistik stránek PDF
        self.spin_n.valueChanged.connect(self.update_pdf_pages_stats)
        self.spin_m.valueChanged.connect(self.update_pdf_pages_stats)
        self.spin_pages_per_pdf.valueChanged.connect(self.update_pdf_pages_stats)

        # Náhled cesty se aktualizuje pouze při změně složky, nebo jako důsledek změny názvu
        self.edit_output_folder.textChanged.connect(self.update_full_pdf_path_preview)
        # Tento signál už není potřeba, protože `update_pdf_filename` volá `update_full_pdf_path_preview`
        # self.edit_pdf_filename.textChanged.connect(self.update_full_pdf_path_preview) 

    def calculate_pdf_pages_stats(self):
        """Vypočítá celkový počet stran PDF a počet stran posledního PDF."""
        try:
            n = self.spin_n.value()
            m = self.spin_m.value()
            pages_per_pdf = self.spin_pages_per_pdf.value()
            
            if m < n:
                return None, None, "Chybný rozsah (N > M)"
            
            total_images = m - n + 1
            IMAGES_PER_PAGE = 5
            IMAGES_PER_PDF = IMAGES_PER_PAGE * pages_per_pdf
            
            if total_images <= 0:
                return 0, 0, "Žádné obrázky"
            
            # Výpočet počtu PDF souborů
            num_pdfs = (total_images + IMAGES_PER_PDF - 1) // IMAGES_PER_PDF
            
            if num_pdfs <= 1:
                # Jen jeden PDF
                pages_needed = (total_images + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE
                total_pages = pages_needed
                last_pdf_pages = pages_needed
            else:
                # Více PDF souborů
                # Počet plných PDF (kromě posledního)
                full_pdfs = num_pdfs - 1
                total_pages_in_full_pdfs = full_pdfs * pages_per_pdf
                
                # Zbývající obrázky pro poslední PDF
                remaining_images = total_images - (full_pdfs * IMAGES_PER_PDF)
                last_pdf_pages = (remaining_images + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE
                
                total_pages = total_pages_in_full_pdfs + last_pdf_pages
            
            return total_pages, last_pdf_pages, None
            
        except Exception as e:
            return None, None, f"Chyba výpočtu: {e}"
    
    def update_pdf_pages_stats(self):
        """Aktualizuje zobrazení statistik stránek PDF."""
        if not hasattr(self, 'pdf_pages_stats_label'):
            return
        
        total_pages, last_pdf_pages, error = self.calculate_pdf_pages_stats()
        
        if error:
            self.pdf_pages_stats_label.setText(f"❌ {error}")
            self.pdf_pages_stats_label.setStyleSheet("""
                QLabel {
                    color: #f44336;
                    font-weight: bold;
                    padding: 4px 8px;
                    background-color: #4a1a1a;
                    border: 1px solid #f44336;
                    border-radius: 4px;
                }
            """)
        elif total_pages is None or last_pdf_pages is None:
            self.pdf_pages_stats_label.setText("Celkem stran: — | Poslední PDF: — stran")
            self.pdf_pages_stats_label.setStyleSheet("""
                QLabel {
                    color: #888888;
                    font-weight: bold;
                    padding: 4px 8px;
                    background-color: #2a2a2a;
                    border: 1px solid #888888;
                    border-radius: 4px;
                }
            """)
        else:
            # Zjistí počet PDF souborů pro lepší popis
            n = self.spin_n.value()
            m = self.spin_m.value()
            pages_per_pdf = self.spin_pages_per_pdf.value()
            total_images = m - n + 1
            IMAGES_PER_PDF = 5 * pages_per_pdf
            num_pdfs = (total_images + IMAGES_PER_PDF - 1) // IMAGES_PER_PDF if total_images > 0 else 1
            
            if num_pdfs <= 1:
                self.pdf_pages_stats_label.setText(f"📄 Celkem: {total_pages} stran (1 PDF)")
            else:
                self.pdf_pages_stats_label.setText(f"📄 Celkem: {total_pages} stran | Poslední PDF: {last_pdf_pages} stran")
            
            self.pdf_pages_stats_label.setStyleSheet("""
                QLabel {
                    color: #4CAF50;
                    font-weight: bold;
                    padding: 4px 8px;
                    background-color: #1a4a2a;
                    border: 1px solid #4CAF50;
                    border-radius: 4px;
                }
            """)
        
        # Tooltip s detailními informacemi
        if total_pages is not None and last_pdf_pages is not None and not error:
            n = self.spin_n.value()
            m = self.spin_m.value()
            pages_per_pdf = self.spin_pages_per_pdf.value()
            total_images = m - n + 1
            IMAGES_PER_PDF = 5 * pages_per_pdf
            num_pdfs = (total_images + IMAGES_PER_PDF - 1) // IMAGES_PER_PDF if total_images > 0 else 1
            
            tooltip_lines = [
                f"Rozsah čtyřlístků: {n} - {m} ({total_images} obrázků)",
                f"Obrázků na stránku: 5",
                f"Max. stran na PDF: {pages_per_pdf}",
                f"Obrázků na PDF: {IMAGES_PER_PDF}",
                f"Počet PDF souborů: {num_pdfs}",
                f"Celkový počet stran: {total_pages}",
                f"Stran v posledním PDF: {last_pdf_pages}"
            ]
            self.pdf_pages_stats_label.setToolTip("\n".join(tooltip_lines))
        else:
            self.pdf_pages_stats_label.setToolTip("Nastavte platný rozsah čtyřlístků pro výpočet stránek PDF")


    def scan_clover_numbers(self):
        r"""
        Prohledá složku se čtyřlístky a vrátí (min_n, max_m, count).
        Robustní: používá os.scandir, rozpozná úvodní čísla regexem ^(\d+),
        a bere jen podporované obrazové přípony (case-insensitive).
        """
        import re, unicodedata
        path = (self.edit_clover_path.text() or "").strip()
        if not path or not os.path.isdir(path):
            return None, None, 0
    
        # Normalizace cesty kvůli NFD/NFC na macOS (iCloud Drive s diakritikou)
        try:
            path = unicodedata.normalize("NFC", path)
        except Exception:
            pass
    
        exts = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
        rx_leading_num = re.compile(r'^(\d+)')
        min_n = None
        max_m = None
        count = 0
    
        try:
            with os.scandir(path) as it:
                for de in it:
                    if not de.is_file():
                        continue
                    name = de.name
                    # Normalizace názvu kvůli diakritice v NFD
                    try:
                        name = unicodedata.normalize("NFC", name)
                    except Exception:
                        pass
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in exts:
                        continue
                    m = rx_leading_num.match(name)
                    if not m:
                        continue
                    try:
                        num = int(m.group(1))
                    except Exception:
                        continue
                    count += 1
                    if (min_n is None) or (num < min_n):
                        min_n = num
                    if (max_m is None) or (num > max_m):
                        max_m = num
        except Exception:
            return None, None, 0
    
        return min_n, max_m, count
    
    
    def update_clover_stats_label(self):
        """
        Aktualizuje štítek s přehledem podle obsahu složky čtyřlístků.
        Nezasahuje do validace ani do spinboxů N/M.
        """
        min_n, max_m, count = self.scan_clover_numbers()
        if count <= 0 or min_n is None or max_m is None:
            self.clover_stats_label.setText("Nalezeno: — (0)")
            self.clover_stats_label.setToolTip("Ve složce nebyly nalezeny žádné soubory čtyřlístků nebo chybí úvodní číslo v názvu")
            return
        self.clover_stats_label.setText(f"Nalezeno: {min_n} – {max_m} ({count})")
        self.clover_stats_label.setToolTip(f"Nejmenší: {min_n}\nNejvětší: {max_m}\nPočet souborů: {count}")

    def update_clover_stats_label(self):
        """
        Aktualizuje štítek s přehledem podle obsahu složky čtyřlístků.
        Nezasahuje do validace ani do spinboxů N/M.
        """
        min_n, max_m, count = self.scan_clover_numbers()
        if count <= 0 or min_n is None or max_m is None:
            self.clover_stats_label.setText("Nalezeno: — (0)")
            self.clover_stats_label.setToolTip("Ve složce nebyly nalezeny žádné soubory čtyřlístků")
            return
    
        self.clover_stats_label.setText(f"Nalezeno: {min_n} – {max_m} ({count})")
        self.clover_stats_label.setToolTip(f"Nejmenší: {min_n}\nNejvětší: {max_m}\nPočet souborů: {count}")

    def _trigger_clover_validation(self):
        """Pomocná metoda pro debounce validace."""
        self.clover_validation_timer.start(500)

    def browse_folder(self, target_edit):
        directory = QFileDialog.getExistingDirectory(self, "Vyberte složku", target_edit.text())
        if directory:
            target_edit.setText(directory)

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: create_location_config_tab
    # NAHRAĎ TOUTO VERZÍ (odstraněna tlačítka: „📊 Seřadit lokace vzestupně“, „🧹 Vyčistit neexistující fotky“, „🗑️ Uklidit .bak soubory“)
    
    def create_location_config_tab(self):
        """Vytvoření tabu 'Nastavení lokací' s JSON editorem a sekcí 'Analýza fotek' včetně tlačítka ✂️ Rychlý ořez."""
        # Kořen tabu
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
    
        # Indikátory (beze změny)
        indicators_layout = QVBoxLayout()
        indicators_layout.setSpacing(5)
    
        self.duplicates_indicator = QLabel()
        self.duplicates_indicator.setVisible(False)
        self.duplicates_indicator.setWordWrap(True)
        indicators_layout.addWidget(self.duplicates_indicator)
    
        self.missing_locations_indicator = QLabel()
        self.missing_locations_indicator.setVisible(False)
        self.missing_locations_indicator.setWordWrap(True)
        indicators_layout.addWidget(self.missing_locations_indicator)
    
        self.conflicts_indicator = QLabel()
        self.conflicts_indicator.setVisible(False)
        self.conflicts_indicator.setWordWrap(True)
        indicators_layout.addWidget(self.conflicts_indicator)
    
        layout.addLayout(indicators_layout)
    
        # Dvě sloupce vedle sebe
        horizontal_layout = QHBoxLayout()
        horizontal_layout.setSpacing(15)
    
        # === Levý sloupec: Konfigurace lokací (JSON) ===
        config_group = QGroupBox("⚙️ Konfigurace lokací (JSON)")
        config_layout = QVBoxLayout()
        config_layout.setContentsMargins(8, 8, 8, 8)
        config_group.setLayout(config_layout)
    
        self.location_config_text = QPlainTextEdit()
        self.location_config_text.setPlaceholderText(
            "{\n  \"36\": [\"13600-13680\", \"13681\"],\n  \"8\": [\"13300-13301\"]\n}\n"
        )
        # 2 mezery za tab
        self.location_config_text.setTabStopDistance(
            2 * self.location_config_text.fontMetrics().horizontalAdvance(' ')
        )
        self.location_config_text.setStyleSheet(
            "QPlainTextEdit {"
            "  font-family: Consolas, Menlo, Monaco, 'Courier New', monospace;"
            "  font-size: 11px;"
            "  background: #1e1e1e;"
            "  color: #dcdcdc;"
            "  border: 1px solid #3a3a3a;"
            "  border-radius: 6px;"
            "}"
        )
        config_layout.addWidget(self.location_config_text)
    
        # Ovládání/validace JSON (beze změny)
        validate_layout = QHBoxLayout()
        self.btn_validate_config = QPushButton("✅ Validovat JSON")
        self.btn_validate_config.clicked.connect(self.validate_location_config)
        validate_layout.addWidget(self.btn_validate_config)
        validate_layout.addStretch()
        config_layout.addLayout(validate_layout)
    
        # Propojení – pouze jednou (žádné duplikace signálů)
        self.location_config_text.textChanged.connect(self.update_missing_photos_list)
        self.location_config_text.textChanged.connect(self.trigger_all_location_checks)
    
        # === Pravý sloupec: Analýza fotek ===
        missing_photos_group = QGroupBox("📋 Analýza fotek")
        missing_layout = QVBoxLayout()
        missing_layout.setContentsMargins(8, 8, 8, 8)
        missing_photos_group.setLayout(missing_layout)
    
        # Horní řádek se checkboxem a ✂️ Rychlý ořez (jako ve staré verzi)
        top_controls_layout = QHBoxLayout()
        top_controls_layout.setSpacing(20)
    
        self.show_all_photos_checkbox = QCheckBox("Zobrazit všechny fotky (nezávisle na přiřazení lokací)")
        self.show_all_photos_checkbox.setChecked(False)
        self.show_all_photos_checkbox.setToolTip(
            "Po zaškrtnutí zobrazí všechny fotky ve složce, nezávisle na tom, zda mají přiřazenou lokaci"
        )
        self.show_all_photos_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 10px;
            }
            QCheckBox::indicator {
                width: 10px;
                height: 10px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #555555;
                background-color: #2b2b2b;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #3498db;
                background-color: #3498db;
                border-radius: 2px;
            }
        """)
        self.show_all_photos_checkbox.stateChanged.connect(self.on_toggle_show_all_photos)
        top_controls_layout.addWidget(self.show_all_photos_checkbox, 0)
    
        # ✂️ Rychlý ořez – tlačítko (volá původní handler)
        self.btn_quick_crop = QPushButton("✂️ Rychlý ořez")
        self.btn_quick_crop.setToolTip("Otevřít první neořezanou fotku pro rychlý ořez")
        # Pokud stará verze používala konkrétní styl, ponecháme jednoduchý (nezpůsobuje problémy)
        self.btn_quick_crop.setCursor(Qt.PointingHandCursor)
        # Základní šířka; případné povolení/zakázání řeší tvoje existující logika
        
        
        # Jednoduchý stylesheet bez problematických vlastností
        self.btn_quick_crop.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                padding: 2px 6px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #888888;
                color: #cccccc;
            }
        """)
        
        self.btn_quick_crop.setEnabled(True)
        # Původní handler ze staré verze:
        if hasattr(self, "open_first_uncropped_photo"):
            self.btn_quick_crop.clicked.connect(self.open_first_uncropped_photo)
        elif hasattr(self, "find_first_uncropped_photo"):
            self.btn_quick_crop.clicked.connect(self.find_first_uncropped_photo)
    
        top_controls_layout.addStretch(1)
        top_controls_layout.addWidget(self.btn_quick_crop, 0)
        missing_layout.addLayout(top_controls_layout)
    
        # Seznam/obsah analýzy fotek (beze změny)
        self.photos_container = QWidget()
        photos_container_layout = QVBoxLayout(self.photos_container)
        photos_container_layout.setContentsMargins(0, 0, 0, 0)
    
        self.missing_photos_widget = MissingPhotosWidget()
        photos_container_layout.addWidget(self.missing_photos_widget)
        missing_layout.addWidget(self.photos_container)
    
        # Sestavení sloupců
        horizontal_layout.addWidget(config_group, stretch=7)
        horizontal_layout.addWidget(missing_photos_group, stretch=3)
        layout.addLayout(horizontal_layout)
    
        # Přidání tabu
        self.tabs.addTab(tab, "🗺️ Nastavení lokací")
        
    def on_toggle_show_all_photos(self, state):
        """Handler pro změnu checkboxu zobrazení všech fotek."""
        if state == 2:  # Qt.Checked
            self.update_log("📋 Zobrazuji všechny fotky (včetně přiřazených lokací)")
        else:  # Qt.Unchecked
            self.update_log("📋 Zobrazuji pouze fotky bez přiřazené lokace")
        
        # Okamžitá aktualizace seznamu
        self.update_missing_photos_list()
        
        # ✅ NOVÉ: Aktualizace stavu tlačítka podle nového režimu
        QTimer.singleShot(100, self.update_quick_crop_button_state)

    def find_first_uncropped_photo(self):
        """
        Najde první fotku v seznamu nepřiřazených fotek, která není ořezaná.
        Vrací tuple (photo_number, photo_path) nebo (None, None) pokud žádná není nalezena.
        """
        try:
            clover_path = self.edit_clover_path.text().strip()
            if not clover_path or not os.path.isdir(clover_path):
                return None, None
    
            # Získej seznam nepřiřazených fotek
            json_numbers = self.extract_numbers_from_location_json()
            existing_photos = self._get_existing_photo_numbers(clover_path)
            missing_location_photos = existing_photos - set(json_numbers)
    
            if not missing_location_photos:
                return None, None
    
            # Najdi první neořezanou fotku v seřazeném seznamu
            sorted_photos = sorted(missing_location_photos)
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
    
            for photo_number in sorted_photos:
                # Zkontroluj, zda fotka není ořezaná
                is_cropped = self.crop_status.get(str(photo_number), False)
                if not is_cropped:
                    # Najdi soubor s tímto číslem
                    try:
                        files = os.listdir(clover_path)
                        for filename in files:
                            if filename.startswith(f"{photo_number}+"):
                                ext = os.path.splitext(filename)[1].lower()
                                if ext in photo_extensions:
                                    photo_path = os.path.join(clover_path, filename)
                                    return photo_number, photo_path
                    except Exception:
                        continue
    
            return None, None
    
        except Exception as e:
            self.update_log(f"❌ Chyba při hledání neořezané fotky: {e}")
            return None, None

    def open_first_uncropped_photo(self):
        """Otevře první neořezanou fotku ze seznamu 'Analýza fotek' pro rychlý ořez."""
        try:
            # ✅ NOVÁ LOGIKA: Vezmi první neořezanou fotku přímo ze seznamu MissingPhotosWidget
            first_uncropped_item = None
            first_uncropped_number = None
            
            # Projdi seznam a najdi první neořezanou fotku (ikona 🖼️)
            for i in range(self.missing_photos_widget.list_widget.count()):
                item = self.missing_photos_widget.list_widget.item(i)
                if item is None:
                    continue
                    
                # Kontrola ikony: "🖼️" = neořezaná
                if item.text().startswith("🖼️"):
                    first_uncropped_item = item
                    # Extrakce čísla fotky z textu "🖼️ 12345"
                    try:
                        first_uncropped_number = int(item.text().split()[-1])
                        break
                    except (ValueError, IndexError):
                        continue
            
            # Pokud nebyla nalezena žádná neořezaná fotka
            if first_uncropped_item is None or first_uncropped_number is None:
                # JEDNODUCHÉ: Tlačítko by nemělo být aktivní, ale pro jistotu
                QMessageBox.information(
                    self,
                    "Rychlý ořez",
                    "✂️ V seznamu nejsou žádné neořezané fotky."
                )
                return
    
            self.update_log(f"✂️ Otevírám první neořezanou fotku ze seznamu: {first_uncropped_number}")
    
            # Sestavení cesty k fotce
            clover_path = self.edit_clover_path.text().strip()
            if not clover_path or not os.path.isdir(clover_path):
                QMessageBox.warning(self, "Chyba", "❌ Cesta ke složce s fotkami čtyřlístků není nastavena nebo neexistuje.")
                return
    
            # Najdi skutečný soubor s tímto číslem
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            target_photo_path = None
            
            try:
                files_in_dir = os.listdir(clover_path)
                for filename in files_in_dir:
                    if filename.startswith(f"{first_uncropped_number}+"):
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in photo_extensions:
                            target_photo_path = os.path.join(clover_path, filename)
                            break
            except Exception as e:
                QMessageBox.critical(self, "Chyba", f"Nepodařilo se najít soubor fotky {first_uncropped_number}:\n{str(e)}")
                return
    
            if not target_photo_path or not os.path.exists(target_photo_path):
                QMessageBox.critical(self, "Chyba", f"Soubor fotky {first_uncropped_number} nebyl nalezen ve složce.")
                return
    
            # Sestavení seznamu všech fotek pro navigaci v dialogu (stejná logika jako předtím)
            try:
                photo_files_map = {}
                for f in files_in_dir:
                    try:
                        number_part = f.split('+')[0]
                        if number_part.isdigit():
                            num = int(number_part)
                            ext = os.path.splitext(f)[1].lower()
                            if ext in photo_extensions:
                                photo_files_map[num] = os.path.join(clover_path, f)
                    except (ValueError, IndexError):
                        continue
    
                # Seřazení fotek podle čísel
                ordered_photos = sorted(photo_files_map.items(), key=lambda x: x[0])
                ordered_paths = [photo[1] for photo in ordered_photos]
                ordered_numbers = [photo[0] for photo in ordered_photos]
    
                # Najdi index aktuální fotky
                start_index = 0
                if first_uncropped_number in ordered_numbers:
                    start_index = ordered_numbers.index(first_uncropped_number)
    
                # Dočasně zakázat automatické aktualizace
                self.disable_photo_list_updates()
    
                # Otevři ImagePreviewDialog
                dialog = ImagePreviewDialog(ordered_paths, start_index, self, crop_status_dict=self.crop_status)
                dialog.exec()
    
                # Po zavření dialogu aktualizuj seznamy
                self.update_missing_photos_list()
                self.update_status_photos_list()
    
                # Znovu povolit automatické aktualizace
                self.enable_photo_list_updates(first_uncropped_number)
    
                # Informace o dokončení
                self.update_log(f"✅ Náhled fotky {first_uncropped_number} dokončen")
    
            except Exception as e:
                self.update_log(f"❌ Chyba při sestavování seznamu fotek: {e}")
                QMessageBox.critical(self, "Chyba", f"Nepodařilo se sestavit seznam fotek pro navigaci:\n{str(e)}")
    
        except Exception as e:
            self.update_log(f"❌ Chyba při otevírání rychlého ořezu: {e}")
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se otevřít fotku:\n{str(e)}")

    def update_quick_crop_button_state(self):
        """Aktualizuje stav tlačítka rychlého ořezu podle stavu checkboxu a dostupných neořezaných fotek."""
        try:
            if not hasattr(self, 'btn_quick_crop'):
                return
    
            # Zkontroluj stav checkboxu
            show_all = hasattr(self, 'show_all_photos_checkbox') and self.show_all_photos_checkbox.isChecked()
            
            if show_all:
                # ✅ NOVÉ: Checkbox zaškrtnutý - kontroluj seznam "Analýza fotek" na neořezané fotky
                any_uncropped = False
                
                # Projdi všechny položky v seznamu MissingPhotosWidget
                for i in range(self.missing_photos_widget.list_widget.count()):
                    item = self.missing_photos_widget.list_widget.item(i)
                    if item is None:
                        continue
                    
                    # Kontrola ikony: "🖼️" = neořezaná, "✂️" = ořezaná
                    if item.text().startswith("🖼️"):
                        any_uncropped = True
                        break
                
                # Nastavení stavu tlačítka
                if any_uncropped:
                    self.btn_quick_crop.setEnabled(True)
                    self.btn_quick_crop.setToolTip("Otevřít první neořezanou fotku ze seznamu")
                else:
                    self.btn_quick_crop.setEnabled(False)
                    self.btn_quick_crop.setToolTip("Všechny fotky v seznamu jsou již ořezané")
                    
            else:
                # ✅ PŮVODNÍ: Checkbox nezaškrtnutý - původní logika jen pro nepřiřazené fotky
                photo_number, photo_path = self.find_first_uncropped_photo()
    
                if photo_number is not None:
                    self.btn_quick_crop.setEnabled(True)
                    self.btn_quick_crop.setToolTip(f"Otevřít první neořezanou fotku: {photo_number}")
                else:
                    self.btn_quick_crop.setEnabled(False)
                    
                    # Zjisti důvod nedostupnosti
                    clover_path = self.edit_clover_path.text().strip()
                    if not clover_path or not os.path.isdir(clover_path):
                        self.btn_quick_crop.setToolTip("Cesta ke složce s fotkami není nastavena")
                    else:
                        json_numbers = self.extract_numbers_from_location_json()
                        existing_photos = self._get_existing_photo_numbers(clover_path)
                        missing_location_photos = existing_photos - set(json_numbers)
                        
                        if not missing_location_photos:
                            self.btn_quick_crop.setToolTip("Všechny fotky jsou přiřazené k lokacím")
                        else:
                            self.btn_quick_crop.setToolTip("Všechny nepřiřazené fotky jsou již ořezané")
    
        except Exception:
            # Tichá chyba - nezastavuj UI
            pass

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: cleanup_bak_files
    # NAHRAĎ TOUTO „NO-OP“ VERZÍ (bezpečné odstranění handleru; úklid .bak probíhá při zavření okna)
    def cleanup_bak_files(self):
        """(removed) Dřívější tlačítko '🗑️ Uklidit .bak soubory' bylo odstraněno (úklid probíhá při zavření okna)."""
        return

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: cleanup_nonexistent_photos
    # NAHRAĎ TOUTO „NO-OP“ VERZÍ (bezpečné odstranění handleru; nikde se už nevolá)
    def cleanup_nonexistent_photos(self):
        """(removed) Dřívější tlačítko '🧹 Vyčistit neexistující fotky' bylo odstraněno."""
        return
    
    def _get_existing_photo_numbers(self, clover_path):
        """Získá seznam čísel skutečně existujících fotek ve složce"""
        try:
            existing_photos = set()
            photo_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}
            
            for filename in os.listdir(clover_path):
                ext = os.path.splitext(filename)[1].lower()
                if ext in photo_extensions:
                    try:
                        # Extrakce čísla ze začátku názvu souboru (před prvním '+')
                        number_part = filename.split('+')[0]
                        photo_number = int(number_part)
                        existing_photos.add(photo_number)
                    except (ValueError, IndexError):
                        continue
            
            return existing_photos
        
        except Exception as e:
            self.update_log(f"❌ Chyba při skenování složky: {e}")
            return set()

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: sort_locations_json
    # NAHRAĎ TOUTO „NO-OP“ VERZÍ (bezpečné odstranění handleru; nikde se už nevolá)
    def sort_locations_json(self):
        """(removed) Dřívější tlačítko '📊 Seřadit lokace vzestupně' bylo odstraněno."""
        return

    def _create_path_widget(self, line_edit):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        layout.addWidget(line_edit)

        browse_btn = QPushButton("...")
        browse_btn.setFixedSize(30, 30)
        browse_btn.clicked.connect(lambda: self.browse_folder(line_edit))
        layout.addWidget(browse_btn)

        return widget
    
    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: set_notes_watch_path
    # NOVÁ FUNKCE – vlož do třídy PdfGeneratorWindow. Slouží k bezpečné změně sledované složky.
    def set_notes_watch_path(self, path: str):
        """Nastaví/obmění sledovanou složku pro záložku 'Nastavení poznámek' (bez podsložek)."""
        from PySide6.QtCore import QFileSystemWatcher
        import os
    
        self.notes_watch_path = path or ""
        if not hasattr(self, "notes_fs_watcher") or not isinstance(self.notes_fs_watcher, QFileSystemWatcher):
            return
    
        try:
            # Zruš staré cesty
            for p in list(self.notes_fs_watcher.directories()):
                self.notes_fs_watcher.removePath(p)
        except Exception:
            pass
    
        # Přidej novou (jen pokud existuje a je složka)
        if self.notes_watch_path and os.path.isdir(self.notes_watch_path):
            try:
                self.notes_fs_watcher.addPath(self.notes_watch_path)
            except Exception:
                pass
    
        # Po změně cesty hned obnov seznam
        try:
            self.update_notes_photos_list()
        except Exception:
            pass

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: update_notes_photos_list
    # NOVÁ FUNKCE – vlož do třídy PdfGeneratorWindow (např. hned pod update_status_photos_list). Nic jiného NEMĚŇ.
    def update_notes_photos_list(self):
        """Aktualizuje seznam fotek v záložce Nastavení poznámek (zobrazuje fotky bez zapsané Nastavení poznámek)."""
        if not hasattr(self, 'notes_photos_widget'):
            return
        folder = getattr(self, "notes_watch_path", "") or ""
        crop = getattr(self, "crop_status", {})
        self.notes_photos_widget.update_photos_list(folder, crop)

     # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: create_notes_tab
    # NAHRAĎ CELÝ OBSAH FUNKCE TOUTO VERZÍ.
    # ZMĚNY:
    # - Přidán pravý panel se seznamem fotek (NotesPhotosWidget).
    # - Přidán QFileSystemWatcher pro real-time sledování složky s fotkami jen v této složce (bez podsložek).
    # - Sledovaná složka nastavena na: `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/`
    # - Napojení na update_notes_photos_list() při změně složky i při změně JSONu poznámek.
    def create_notes_tab(self):
        """Záložka 'Nastavení poznámek' s JSON editorem a pravým seznamem fotek (real-time sledování složky)."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QPushButton
        from PySide6.QtGui import QFont
        from PySide6.QtCore import QTimer, QFileSystemWatcher
    
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
    
        # Indikátor nad obsahem (ponecháno)
        self.notes_states_without_notes_indicator = QLabel()
        self.notes_states_without_notes_indicator.setVisible(False)
        self.notes_states_without_notes_indicator.setWordWrap(True)
        layout.addWidget(self.notes_states_without_notes_indicator)
    
        # === LEVÁ STRANA: Editor „📝 JSON Nastavení poznámek“ ===
        notes_group = QGroupBox("📝 JSON nastavení poznámek")
        notes_layout = QVBoxLayout()
    
        editor_container = QWidget()
        editor_container_layout = QVBoxLayout(editor_container)
        editor_container_layout.setContentsMargins(0, 0, 0, 0)
    
        # JSONCodeEditor
        self.notes_text = JSONCodeEditor()
        self.notes_text.setFont(QFont("Consolas", 11))
    
        if not self.notes_text.toPlainText().strip():
            self.notes_text.setPlainText('{\n "13302": "DAR - BIP 2025"\n}')
    
        # Live kontrola a refresh pravého seznamu
        self.notes_text.textChanged.connect(self.check_states_without_notes_real_time)
        self.notes_text.textChanged.connect(self.update_notes_photos_list)
    
        help_btn = QPushButton("?")
        help_btn.setParent(editor_container)
        help_btn.setFixedSize(24, 24)
        help_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        help_btn.setToolTip(
            "Nastavení poznámek ve formátu JSON: { \"ČísloNálezu\": \"text poznámky\" }.\n"
            "Editor zobrazuje čísla řádků; klávesa Tab vloží 2 mezery."
        )
    
        def position_help_button():
            help_btn.move(editor_container.width() - 30, 5)
            help_btn.raise_()
    
        original_resize = editor_container.resizeEvent
        def new_resize_event(event):
            if original_resize:
                original_resize(event)
            position_help_button()
        editor_container.resizeEvent = new_resize_event
        QTimer.singleShot(100, position_help_button)
    
        editor_container_layout.addWidget(self.notes_text)
        notes_layout.addWidget(editor_container)
    
        validate_layout = QHBoxLayout()
        self.btn_validate_notes = QPushButton("✅ Validovat JSON")
        self.btn_validate_notes.clicked.connect(self.validate_notes)
        validate_layout.addWidget(self.btn_validate_notes)
        validate_layout.addStretch()
    
        notes_layout.addLayout(validate_layout)
        notes_group.setLayout(notes_layout)
    
        # === PRAVÁ STRANA: Seznam fotek (jen akce „Zapsat poznámku“) ===
        photos_group = QGroupBox("📋 Seznam fotek")
        photos_layout = QVBoxLayout(photos_group)
        photos_layout.setContentsMargins(8, 8, 8, 8)
    
        self.notes_photos_widget = NotesPhotosWidget()
        photos_layout.addWidget(self.notes_photos_widget)
    
        # === HORIZONTÁLNÍ ROZVRŽENÍ ===
        horizontal_layout = QHBoxLayout()
        horizontal_layout.setSpacing(15)
        horizontal_layout.addWidget(notes_group, stretch=7)
        horizontal_layout.addWidget(photos_group, stretch=3)
        layout.addLayout(horizontal_layout)
    
        # === QFileSystemWatcher pro real-time sledování složky (bez podsložek) ===
        self.notes_watch_path = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/"
        # Pokud watcher už existuje (opakované volání), nejprve odpoj a uvolni
        if hasattr(self, "notes_fs_watcher") and isinstance(self.notes_fs_watcher, QFileSystemWatcher):
            try:
                for p in self.notes_fs_watcher.directories():
                    self.notes_fs_watcher.removePath(p)
            except Exception:
                pass
        self.notes_fs_watcher = QFileSystemWatcher(self)
        # přidej, pokud existuje
        self.set_notes_watch_path(self.notes_watch_path)
        # změny ve složce -> refresh pravého seznamu
        self.notes_fs_watcher.directoryChanged.connect(lambda _: self.update_notes_photos_list())
    
        # První načtení seznamu
        self.update_notes_photos_list()
    
        self.tabs.addTab(tab, "📝 Nastavení poznámek")

    def _update_notes_states_without_notes_indicator(self, missing_notes_set, all_ok=False):
        """Aktualizuje indikátor chybějících poznámek v záložce Nastavení poznámek."""
        if not hasattr(self, 'notes_states_without_notes_indicator'):
            return
    
        if missing_notes_set is None:
            self.notes_states_without_notes_indicator.setVisible(False)
            return
    
        if all_ok:
            self.notes_states_without_notes_indicator.setText("✅ Všechny fotky se stavem mají poznámku")
            self.notes_states_without_notes_indicator.setStyleSheet("""
            QLabel {
                color: #27ae60;
                background-color: #d5f4e6;
                border: 1px solid #27ae60;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            """)
            self.notes_states_without_notes_indicator.setVisible(True)
        else:
            missing_list = sorted(list(missing_notes_set))
            if len(missing_list) <= 12:
                missing_str = ", ".join(str(x) for x in missing_list)
            else:
                missing_str = ", ".join(str(x) for x in missing_list[:10]) + f", ... (+{len(missing_list)-10})"
            
            self.notes_states_without_notes_indicator.setText(f"⚠️ Chybějící poznámky pro fotky: {missing_str}")
            self.notes_states_without_notes_indicator.setToolTip(
                f"Celkem {len(missing_list)} fotek se stavem nemá poznámku.\n"
                f"Fotky: {', '.join(str(x) for x in missing_list)}"
            )
            self.notes_states_without_notes_indicator.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                background-color: #fadbd8;
                border: 1px solid #e74c3c;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            """)
            self.notes_states_without_notes_indicator.setVisible(True)


    def create_status_config_tab(self):
        """Záložka 'Nastavení stavů' s JSON editorem a real-time indikacemi"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
    
        # Real-time indikace (nad hlavním obsahem)
        indicators_layout = QVBoxLayout()
        indicators_layout.setSpacing(5)
    
        # Indikátor duplikátních stavů
        self.duplicate_states_indicator = QLabel()
        self.duplicate_states_indicator.setVisible(False)
        self.duplicate_states_indicator.setWordWrap(True)
        indicators_layout.addWidget(self.duplicate_states_indicator)
    
        # NOVÉ: Indikátor chybějících poznámek pro stavy
        self.states_without_notes_indicator = QLabel()
        self.states_without_notes_indicator.setVisible(False)
        self.states_without_notes_indicator.setWordWrap(True)
        indicators_layout.addWidget(self.states_without_notes_indicator)
    
        layout.addLayout(indicators_layout)
    
        horizontal_layout = QHBoxLayout()
        horizontal_layout.setSpacing(15)
    
        config_group = QGroupBox("⚙️ JSON Nastavení stavů")
        config_layout = QVBoxLayout()
    
        editor_container = QWidget()
        editor_container_layout = QVBoxLayout(editor_container)
        editor_container_layout.setContentsMargins(0, 0, 0, 0)
    
        # JSONCodeEditor
        self.status_config_text = JSONCodeEditor()
        self.status_config_text.setFont(QFont("Consolas", 11))
    
        if not self.status_config_text.toPlainText().strip():
            self.status_config_text.setPlainText('{\n "BEZFOTKY": ["13600-13602", "13603"],\n "BEZGPS": ["13700-13702"]\n}')  # NOVÉ: Přidán příklad BEZGPS

    
        # Help tlačítko
        help_btn = QPushButton("?")
        help_btn.setParent(editor_container)
        help_btn.setFixedSize(24, 24)
        help_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db; color: white; border: none;
                border-radius: 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
    
        help_tooltip = (
            "JSON pro Nastavení stavů (nový formát):\n"
            "Formát: { \"STAV\": [\"start-end\", \"cislo\", ...] }\n"
            "Povolené stavy: \"BEZFOTKY\", \"DAROVANY\", \"ZTRACENY\", \"BEZGPS\".\n\n"
            "Příklad:\n"
            "{ \"BEZFOTKY\": [\"13600-13602\", \"13603\"],\n"
            "  \"DAROVANY\": [\"13610-13615\"],\n"
            "  \"ZTRACENY\": [\"13620-13625\"],\n"
            "  \"BEZGPS\": [\"13630-13635\"] }\n\n"
            "Stav BEZFOTKY:\n"
            "• Do PDF se vloží BEZ_FOTKY.png místo fotky čtyřlístku\n"
            "• GPS souřadnice se zobrazí jako: \"N ??° ??' ??.??\\\"\" a \"E ??° ??' ??.??\\\"\"\n"
            "• Kopírování/přejmenování se pro tento záznam přeskočí\n"
            "• Vyžaduje poznámku\n\n"
            "Stav DAROVANY:\n"
            "• Fotka, GPS souřadnice a datum se zpracovávají normálně\n"
            "• Do bílého prostoru vedle se vloží obrázek DAROVANY.png\n"
            "• Poznámka se zobrazí nad tento obrázek\n"
            "• Kopírování/přejmenování se pro tento záznam přeskočí\n"
            "• Vyžaduje poznámku\n\n"
            "Stav ZTRACENY:\n"
            "• Fotka, GPS souřadnice a datum se zpracovávají normálně\n"
            "• Do bílého prostoru vedle se vloží obrázek ZTRACENY.png\n"
            "• Automatická poznámka: \"Ztracený 🥺🥺🥺\" (nad obrázek)\n"  # ← Změna zde
            "• Kopírování/přejmenování se pro tento záznam přeskočí\n"
            "• Poznámka není vyžadována (automatická)\n\n"
            "Stav BEZGPS:\n"
            "• Fotka, lokační mapa, datum a čas se zpracovávají normálně\n"
            "• GPS souřadnice se zobrazí jako: \"N ??° ??' ??.??\\\"\" a \"E ??° ??' ??.??\\\"\"\n"
            "• Automatická poznámka: \"Fotka byla vyfocena bez GPS souřadnic\"\n"
            "• Kopírování/přejmenování se pro tento záznam přeskočí\n"
            "• Poznámka není vyžadována (automatická)\n\n"
            "• Lze kombinovat intervaly i jednotlivá čísla\n"
            "• Editor zobrazuje čísla řádků; klávesa Tab vloží 2 mezery"
        )

        help_btn.setToolTip(help_tooltip)
    
        def position_help_button():
            help_btn.move(editor_container.width() - 30, 5)
            help_btn.raise_()
    
        original_resize = editor_container.resizeEvent
        def new_resize_event(event):
            if original_resize: original_resize(event)
            position_help_button()
        editor_container.resizeEvent = new_resize_event
    
        QTimer.singleShot(100, position_help_button)
    
        editor_container_layout.addWidget(self.status_config_text)
        config_layout.addWidget(editor_container)
    
        # Tlačítka pro validaci a seřazení
        validate_layout = QHBoxLayout()
    
        self.btn_validate_status = QPushButton("✅ Validovat JSON")
        self.btn_validate_status.clicked.connect(self.validate_status_config)
    
        self.btn_sort_status = QPushButton("📊 Seřadit stavy vzestupně")
        self.btn_sort_status.clicked.connect(self.sort_status_json)
    
        validate_layout.addWidget(self.btn_validate_status)
        validate_layout.addWidget(self.btn_sort_status)
        validate_layout.addStretch()
    
        config_layout.addLayout(validate_layout)
        config_group.setLayout(config_layout)
    
        # === PRAVÁ STRANA: Seznam fotek ===
        photos_group = QGroupBox("📋 Seznam fotek")
        photos_layout = QVBoxLayout(photos_group)
        photos_layout.setContentsMargins(8, 8, 8, 8)
    
        self.photos_status_widget = PhotosStatusWidget()
        photos_layout.addWidget(self.photos_status_widget)
    
        # === HORIZONTÁLNÍ ROZVRŽENÍ ===
        horizontal_layout.addWidget(config_group, stretch=7)
        horizontal_layout.addWidget(photos_group, stretch=3)
    
        layout.addLayout(horizontal_layout)
    
        # Propojení signálů
        self.status_config_text.textChanged.connect(self.update_status_photos_list)
        self.status_config_text.textChanged.connect(self.check_duplicate_states_real_time)
        self.status_config_text.textChanged.connect(self.check_states_without_notes_real_time)
    
        self.tabs.addTab(tab, "⚙️ Nastavení stavů")

        # ✅ JEDINÝ DOPLNĚNÝ ŘÁDEK: hned po přidání „Nastavení stavů“ vytvoř i záložku anonymizace (a tím ji zařaď hned za stavy)
        self.create_anonymization_tab()

    # Ve třídě PDFGeneratorWindow
    def update_status_photos_list(self):
        """Aktualizuje seznam fotek v záložce Nastavení stavů a předává stav ořezu."""
        if not hasattr(self, 'photos_status_widget'):
            return
        clover_path = self.edit_clover_path.text().strip()
        # OPRAVA: Předání `self.crop_status`
        self.photos_status_widget.update_photos_list(clover_path, self.crop_status)
        
    def sort_status_json(self):
        """Seřadí JSON s nastavením stavů podle názvů stavů vzestupně a naformátuje každý stav na nový řádek"""
        try:
            # Získání aktuálního JSON textu
            current_json_text = self.status_config_text.toPlainText().strip()
            
            if not current_json_text:
                QMessageBox.warning(self, "Varování", "JSON konfigurace stavů je prázdná")
                return
            
            # Parsování JSON
            try:
                status_data = json.loads(current_json_text)
            except json.JSONDecodeError as e:
                QMessageBox.critical(self, "Chyba", f"Neplatný JSON formát:\n{str(e)}")
                return
            
            if not isinstance(status_data, dict):
                QMessageBox.critical(self, "Chyba", "JSON musí být objekt s klíči jako názvy stavů")
                return
            
            # Seřazení podle názvů stavů (abecedně)
            sorted_keys = sorted(status_data.keys())
            sorted_data = {key: status_data[key] for key in sorted_keys}
            
            # Vlastní formátování - každý stav na novém řádku
            lines = ["{"]
            keys_list = list(sorted_data.keys())
            
            for i, key in enumerate(keys_list):
                value = sorted_data[key]
                # Převést hodnotu na JSON string
                value_json = json.dumps(value, ensure_ascii=False)
                
                # Přidat čárku na konec, kromě posledního řádku
                comma = "," if i < len(keys_list) - 1 else ""
                
                # Zarovnání klíčů pro lepší čitelnost
                key_padded = f'"{key}":'.ljust(12)  # zarovnání na 12 znaků (delší než u lokací)
                
                lines.append(f"  {key_padded} {value_json}{comma}")
            
            lines.append("}")
            
            # Spojení do finálního textu
            sorted_json_text = "\n".join(lines)
            
            # Aktualizace text editoru
            self.status_config_text.setPlainText(sorted_json_text)
            
            # Zobrazení úspěchu v logu
            self.update_log("📊 Stavy byly seřazeny vzestupně podle názvů")
            QMessageBox.information(self, "Úspěch", 
                                   f"✅ Stavy byly seřazeny vzestupně podle názvů\n"
                                   f"Počet stavů: {len(sorted_data)}\n"
                                   f"Formátováno po řádcích")
            
        except Exception as e:
            error_msg = f"Došlo k chybě při seřazování: {str(e)}"
            self.update_log(f"❌ {error_msg}")
            QMessageBox.critical(self, "Chyba", error_msg)
            
    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: set_anonym_watch_path
    # NOVÁ FUNKCE – bezpečné přenastavení sledované složky pro anonymizační seznam.
    def set_anonym_watch_path(self, path: str):
        from PySide6.QtCore import QFileSystemWatcher
        import os
    
        self.anonym_watch_path = path or ""
        if not hasattr(self, "anonym_fs_watcher") or not isinstance(self.anonym_fs_watcher, QFileSystemWatcher):
            return
    
        try:
            for p in list(self.anonym_fs_watcher.directories()):
                self.anonym_fs_watcher.removePath(p)
        except Exception:
            pass
    
        if self.anonym_watch_path and os.path.isdir(self.anonym_watch_path):
            try:
                self.anonym_fs_watcher.addPath(self.anonym_watch_path)
            except Exception:
                pass
    
        try:
            self.update_anonym_photos_list()
        except Exception:
            pass
        
    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: update_anonym_photos_list
    # NOVÁ FUNKCE – načte fotky ze sledované složky a zobrazí jen ty, které NEJSOU v JSONu anonymizace.
    def update_anonym_photos_list(self):
        if not hasattr(self, 'anonym_photos_widget'):
            return
        folder = getattr(self, "anonym_watch_path", "") or ""
        crop = getattr(self, "crop_status", {})
        self.anonym_photos_widget.update_photos_list(folder, crop)
            
    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: create_anonymization_tab
    # NOVÁ FUNKCE – vytvoří záložku "Nastavení anonymizace" (za "Nastavení stavů").
    # Obsah: vlevo JSON editor, vpravo seznam fotek (real-time watcher na cílovou složku).
    def create_anonymization_tab(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QPushButton
        from PySide6.QtGui import QFont
        from PySide6.QtCore import QTimer, QFileSystemWatcher
    
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
    
        # === LEVÁ STRANA: Editor „🛡️ JSON anonymizace“ ===
        anonym_group = QGroupBox("🛡️ JSON anonymizace")
        anonym_layout = QVBoxLayout()
    
        editor_container = QWidget()
        editor_container_layout = QVBoxLayout(editor_container)
        editor_container_layout.setContentsMargins(0, 0, 0, 0)
    
        # JSONCodeEditor pro anonymizaci
        self.anonym_config_text = JSONCodeEditor()
        self.anonym_config_text.setFont(QFont("Consolas", 11))
        if not self.anonym_config_text.toPlainText().strip():
            # výchozí struktura dle zadání
            self.anonym_config_text.setPlainText('{\n "ANONYMIZOVANE": []\n}')
    
        # Změna JSONu => obnov pravý seznam
        self.anonym_config_text.textChanged.connect(self.update_anonym_photos_list)
    
        # Help tlačítko
        help_btn = QPushButton("?", parent=editor_container)
        help_btn.setFixedSize(24, 24)
        help_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db; color: white; border: none;
                border-radius: 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        help_btn.setToolTip(
            "Formát JSON anonymizace:\n"
            "{ \"ANONYMIZOVANE\": [\"1-5\", \"43\", ...] }\n\n"
            "• Lze kombinovat intervaly i jednotlivá čísla.\n"
            "• Čísla uvedená v seznamu se NEZOBRAZÍ v pravém seznamu (již anonymizovaná).\n"
            "• Editor zobrazuje čísla řádků; klávesa Tab vloží 2 mezery."
        )
    
        def position_help_button():
            help_btn.move(editor_container.width() - 30, 5)
            help_btn.raise_()
    
        original_resize = editor_container.resizeEvent
        def new_resize_event(event):
            if original_resize:
                original_resize(event)
            position_help_button()
        editor_container.resizeEvent = new_resize_event
        QTimer.singleShot(100, position_help_button)
    
        editor_container_layout.addWidget(self.anonym_config_text)
        anonym_layout.addWidget(editor_container)
    
        # Ovládací lišta (ponecháme jen validaci – pokud máš validátor)
        buttons_layout = QHBoxLayout()
        if hasattr(self, "validate_notes"):  # používáme stejný validátor, pokud existuje
            btn_validate = QPushButton("✅ Validovat JSON")
            btn_validate.clicked.connect(lambda: self._validate_json_editor(self.anonym_config_text))
            buttons_layout.addWidget(btn_validate)
        buttons_layout.addStretch()
        anonym_layout.addLayout(buttons_layout)
        anonym_group.setLayout(anonym_layout)
    
        # === PRAVÁ STRANA: Seznam fotek s jedinou akcí „Anonymizovat“ ===
        photos_group = QGroupBox("📋 Seznam fotek")
        photos_layout = QVBoxLayout(photos_group)
        photos_layout.setContentsMargins(8, 8, 8, 8)
    
        self.anonym_photos_widget = AnonymPhotosWidget()
        photos_layout.addWidget(self.anonym_photos_widget)
    
        # === HORIZONTÁLNÍ ROZVRŽENÍ ===
        horizontal_layout = QHBoxLayout()
        horizontal_layout.setSpacing(15)
        horizontal_layout.addWidget(anonym_group, stretch=7)
        horizontal_layout.addWidget(photos_group, stretch=3)
        layout.addLayout(horizontal_layout)
    
        # === QFileSystemWatcher – real-time sledování cílové složky (bez podsložek) ===
        from PySide6.QtCore import QFileSystemWatcher
        self.anonym_watch_path = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/"
    
        # Pokud existuje starý watcher, odpoj ho
        if hasattr(self, "anonym_fs_watcher") and isinstance(self.anonym_fs_watcher, QFileSystemWatcher):
            try:
                for p in self.anonym_fs_watcher.directories():
                    self.anonym_fs_watcher.removePath(p)
            except Exception:
                pass
    
        self.anonym_fs_watcher = QFileSystemWatcher(self)
        self.set_anonym_watch_path(self.anonym_watch_path)
        self.anonym_fs_watcher.directoryChanged.connect(lambda _: self.update_anonym_photos_list())
    
        # První načtení
        self.update_anonym_photos_list()
    
        # Zařazení tabu – hned za „Nastavení stavů“
        # (pokud pořadí řešíš explicitně, můžeš použít insertTab s indexem)
        self.tabs.addTab(tab, "🛡️ Nastavení anonymizace")

    def validate_status_config(self):
        """Validace JSON konfigurace stavů v novém formátu { "STAV": ["start-end"|"cislo", ...] }."""
        try:
            config_text = self.status_config_text.toPlainText().strip()
            if not config_text:
                QMessageBox.information(self, "Validace", "⚠️ JSON konfigurace stavů je prázdná")
                return
    
            data = json.loads(config_text)
    
            if not isinstance(data, dict):
                QMessageBox.critical(self, "Chyba validace", "❌ JSON musí být objekt tvaru {\"BEZFOTKY\": [\"13600-13602\", \"13603\"]}")
                return
    
            allowed_states = {"BEZFOTKY", "DAROVANY", "ZTRACENY", "BEZGPS"}  # NOVÉ: Přidán stav BEZGPS
    
            analysis = []
            analysis.append("✅ JSON konfigurace stavů (nový formát) je platná\n")
    
            invalid_states = []
            invalid_tokens = []
            total_numbers = 0
    
            for state_key, seq in data.items():
                state = str(state_key).strip().upper()
                if state not in allowed_states:
                    invalid_states.append(state_key)
                    continue
    
                if not isinstance(seq, list):
                    analysis.append(f"❌ Stav {state}: hodnota musí být seznam (list)")
                    continue
    
                numbers_in_state = 0
                for token in seq:
                    s = str(token).strip()
                    if not s:
                        continue
    
                    if '-' in s:
                        try:
                            a, b = s.split('-', 1)
                            start = int(a.strip())
                            end = int(b.strip())
                            if start > end:
                                start, end = end, start
                            numbers_in_state += end - start + 1
                            analysis.append(f"📊 Stav {state}: interval {start}-{end}")
                        except Exception:
                            invalid_tokens.append(f"{state}:{s}")
                    else:
                        try:
                            num = int(s)
                            numbers_in_state += 1
                            analysis.append(f"🎯 Stav {state}: číslo {num}")
                        except Exception:
                            invalid_tokens.append(f"{state}:{s}")
    
                total_numbers += numbers_in_state
                analysis.append(f"📈 Stav {state}: celkem {numbers_in_state} čísel")
    
            if invalid_states:
                analysis.append(f"\n❌ Nepovolené stavy (povoleno: BEZFOTKY, DAROVANY, ZTRACENY, BEZGPS): {', '.join(invalid_states)}")
    
            if invalid_tokens:
                analysis.append(f"\n❌ Neplatné položky: {', '.join(invalid_tokens)}")
    
            if invalid_states or invalid_tokens:
                QMessageBox.critical(self, "Chyba validace", "\n".join(analysis))
            else:
                analysis.append(f"\n📊 Celkem čísel ve všech stavech: {total_numbers}")
                analysis_text = "\n".join(analysis)
                QMessageBox.information(self, "Validace konfigurace stavů", analysis_text)
    
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Chyba validace", f"❌ Neplatný JSON:\n\nŘádek {e.lineno}, pozice {e.colno}:\n{str(e)}")

    def sync_single_tree(self, tree_widget, new_path, name):
        """Synchronizuje jeden strom s novou cestou"""
        try:
            tree_view = tree_widget.findChild(QTreeView)
            if tree_view and hasattr(tree_view, 'file_model'):
                tree_view.root_path = new_path

                # Aktualizace path labelu
                if hasattr(tree_view, 'path_label'):
                    path_label = tree_view.path_label
                    if new_path and os.path.exists(new_path):
                        # Zkrácení dlouhé cesty - více znaků kvůli většímu oknu
                        display_path = new_path
                        if len(new_path) > 80:  # 60*1.33 ≈ 80
                            display_path = "..." + new_path[-77:]
                        path_label.setText(f"📂 {display_path}")
                        path_label.setToolTip(new_path)
                    else:
                        path_label.setText("📂 Cesta není nastavena nebo neexistuje")
                        path_label.setToolTip("")

                # Aktualizace stromu
                if new_path and os.path.exists(new_path):
                    tree_view.file_model.setRootPath(new_path)
                    tree_view.setRootIndex(tree_view.file_model.index(new_path))
                    self.update_log(f"🔗 {name} synchronizován: {os.path.basename(new_path)}")
                else:
                    tree_view.file_model.setRootPath("")
                    if new_path:
                        self.update_log(f"⚠️ {name}: Cesta neexistuje")

        except Exception as e:
            self.update_log(f"❌ Chyba synchronizace {name}: {str(e)}")

    def validate_location_config(self):
        """Validuje JSON konfiguraci lokací v novém formátu { IDLokace: [\"start-end\"|\"cislo\", ...] } a vypíše analýzu."""
        try:
            config_text = self.location_config_text.toPlainText().strip()
            if not config_text:
                QMessageBox.information(self, "Validace", "⚠️ JSON konfigurace je prázdná")
                return
            data = json.loads(config_text)
            if not isinstance(data, dict):
                QMessageBox.critical(self, "Chyba validace", "❌ JSON musí být objekt tvaru { \"36\": [\"13600-13680\", \"13681\"], ... }")
                return
    
            analysis = []
            analysis.append("✅ JSON nastavení lokací (nový formát) je platná\n")
    
            intervals = []        # [(start,end,loc)]
            singles = {}          # {num: loc}
            invalid_tokens = []
            invalid_loc_ids = []
            first_loc = None
    
            for loc_key, seq in data.items():
                try:
                    loc_id = int(str(loc_key).strip())
                except Exception:
                    invalid_loc_ids.append(str(loc_key))
                    continue
    
                if first_loc is None:
                    first_loc = loc_id
    
                if not isinstance(seq, list):
                    analysis.append(f"❌ Lokace {loc_id}: hodnota musí být seznam (list)")
                    continue
    
                for token in seq:
                    s = str(token).strip()
                    if not s:
                        continue
                    if '-' in s:
                        try:
                            a, b = s.split('-', 1)
                            start = int(a.strip()); end = int(b.strip())
                            if start > end: start, end = end, start
                            intervals.append((start, end, loc_id))
                            analysis.append(f"📊 Lokace {loc_id}: interval {start}-{end}")
                        except Exception:
                            invalid_tokens.append(f"{loc_id}:{s}")
                    else:
                        try:
                            num = int(s)
                            if num in singles and singles[num] != loc_id:
                                analysis.append(f"⚠️ Duplicitní číslo {num} pro lokace {singles[num]} a {loc_id}")
                            singles[num] = loc_id
                            analysis.append(f"🎯 Lokace {loc_id}: číslo {num}")
                        except Exception:
                            invalid_tokens.append(f"{loc_id}:{s}")
    
            if invalid_loc_ids:
                analysis.append(f"\n❌ Neplatná ID lokací: {', '.join(invalid_loc_ids)}")
            if invalid_tokens:
                analysis.append(f"\n❌ Neplatné položky: {', '.join(invalid_tokens)}")
    
            # Kontrola překryvů intervalů (mezi různými lokacemi může znamenat konflikt)
            intervals.sort()
            for i in range(len(intervals) - 1):
                s1, e1, l1 = intervals[i]
                s2, e2, l2 = intervals[i + 1]
                if not (e1 < s2):  # překryv nebo dotyk
                    if l1 != l2:
                        analysis.append(f"⚠️ Překrývající se intervaly {s1}-{e1} (loc {l1}) a {s2}-{e2} (loc {l2})")
    
            if first_loc is None:
                analysis.append("\nℹ️ Konfigurace je prázdná; fallback v generátoru použije lokaci 1")
    
            analysis_text = "\n".join(analysis)
            QMessageBox.information(self, "Validace konfigurace", analysis_text)
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Chyba validace", f"❌ Neplatný JSON:\n\nŘádek {e.lineno}, pozice {e.colno}:\n{str(e)}")

    def validate_notes(self):
        """Validuje JSON Nastavení poznámek s detailním výstupem"""
        try:
            notes_text = self.notes_text.toPlainText().strip()
            if not notes_text:
                QMessageBox.information(self, "Validace", "ℹ️ Nastavení poznámek jsou prázdné (volitelné)")
                return

            notes = json.loads(notes_text)

            # Analýza poznámek
            analysis = []
            analysis.append("✅ JSON Nastavení poznámek jsou platné\n")

            valid_notes = 0
            invalid_keys = []

            for key, value in notes.items():
                try:
                    number = int(key)
                    analysis.append(f"📝 Čtyřlístek {number}: '{value}'")
                    valid_notes += 1
                except ValueError:
                    invalid_keys.append(key)

            if invalid_keys:
                analysis.append(f"\n⚠️ Neplatné klíče (musí být čísla): {', '.join(invalid_keys)}")

            analysis.append(f"\n📊 Celkem platných poznámek: {valid_notes}")

            analysis_text = "\n".join(analysis)
            QMessageBox.information(self, "Validace poznámek", analysis_text)

        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Chyba validace", f"❌ Neplatný JSON:\n\nChyba na řádku {e.lineno}, pozici {e.colno}:\n{str(e)}")
            
    def analyze_location_config_real_time(self):
        """Real-time analýza JSON konfigurace lokací pro duplicity a neexistující lokace"""
        try:
            config_text = self.location_config_text.toPlainText().strip()
            
            # Resetuj indikace
            duplicates = set()
            missing_locations = set()
            
            if config_text:
                try:
                    data = json.loads(config_text)
                    if isinstance(data, dict):
                        duplicates = self._find_duplicate_numbers_in_config(data)
                        missing_locations = self._find_missing_location_folders(data)
                except json.JSONDecodeError:
                    # JSON není platný, neukazuj chyby (to řeší validace)
                    pass
            
            # Aktualizuj indikační labely
            self._update_duplicates_indicator(duplicates)
            self._update_missing_locations_indicator(missing_locations)
            
        except Exception as e:
            # Tichá chyba - nenarušuj uživatelské rozhraní
            pass
    
    def _find_duplicate_numbers_in_config(self, config: dict) -> set:
        """Najde duplicitní čísla fotek napříč lokacemi"""
        number_to_locations = {}
        duplicates = set()
        
        for location_id, intervals_list in config.items():
            if not isinstance(intervals_list, list):
                continue
                
            location_numbers = self._expand_intervals_to_numbers(intervals_list)
            
            for number in location_numbers:
                if number in number_to_locations:
                    duplicates.add(number)
                    number_to_locations[number].append(str(location_id))
                else:
                    number_to_locations[number] = [str(location_id)]
        
        return duplicates
    
    def _expand_intervals_to_numbers(self, intervals_list: list) -> set:
        """Rozbalí seznam intervalů na množinu čísel"""
        numbers = set()
        
        for item in intervals_list:
            item_str = str(item).strip()
            if not item_str:
                continue
                
            if '-' in item_str:
                try:
                    start_str, end_str = item_str.split('-', 1)
                    start_num = int(start_str.strip())
                    end_num = int(end_str.strip())
                    if start_num > end_num:
                        start_num, end_num = end_num, start_num
                    numbers.update(range(start_num, end_num + 1))
                except ValueError:
                    continue
            else:
                try:
                    number = int(item_str)
                    numbers.add(number)
                except ValueError:
                    continue
        
        return numbers
    
    def _find_missing_location_folders(self, config: dict) -> set:
        """Najde lokace, které nemají odpovídající složky"""
        location_folder = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/"
        missing = set()
        
        if not os.path.isdir(location_folder):
            return set(config.keys())
        
        try:
            existing_items = set()
            for item in os.listdir(location_folder):
                item_path = os.path.join(location_folder, item)
                existing_items.add(item)
                
                if os.path.isfile(item_path):
                    import re
                    numbers_in_name = re.findall(r'\b(\d+)\b', item)
                    for num_str in numbers_in_name:
                        existing_items.add(num_str)
            
            for location_id in config.keys():
                location_id_str = str(location_id).strip()
                
                found = False
                for existing_item in existing_items:
                    if (location_id_str == existing_item or 
                        location_id_str in existing_item or
                        existing_item.startswith(location_id_str + "+") or
                        existing_item.startswith(location_id_str + "_") or
                        existing_item.startswith(location_id_str + "-")):
                        found = True
                        break
                
                if not found:
                    missing.add(location_id_str)
                    
        except Exception:
            missing = set(config.keys())
        
        return missing
    
    def _update_duplicates_indicator(self, duplicates: set):
        """Aktualizuj indikátor duplicitních přiřazení"""
        if not hasattr(self, 'duplicates_indicator'):
            return
            
        if duplicates:
            duplicates_list = sorted(list(duplicates))
            if len(duplicates_list) <= 10:
                duplicates_str = ", ".join(map(str, duplicates_list))
            else:
                duplicates_str = ", ".join(map(str, duplicates_list[:8])) + f", ... (+{len(duplicates_list)-8})"
            
            self.duplicates_indicator.setText(f"⚠️ Duplicitní čísla: {duplicates_str}")
            self.duplicates_indicator.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    background-color: #fadbd8;
                    border: 1px solid #e74c3c;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.duplicates_indicator.setVisible(True)
        else:
            self.duplicates_indicator.setVisible(False)
    
    def _update_missing_locations_indicator(self, missing: set):
        """Aktualizuj indikátor chybějících lokací"""
        if not hasattr(self, 'missing_locations_indicator'):
            return
            
        if missing:
            missing_list = sorted(list(missing), key=lambda x: int(x) if x.isdigit() else 0)
            if len(missing_list) <= 8:
                missing_str = ", ".join(missing_list)
            else:
                missing_str = ", ".join(missing_list[:6]) + f", ... (+{len(missing_list)-6})"
            
            self.missing_locations_indicator.setText(f"📁 Neexistující lokace: {missing_str}")
            self.missing_locations_indicator.setStyleSheet("""
                QLabel {
                    color: #f39c12;
                    background-color: #fef9e7;
                    border: 1px solid #f39c12;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.missing_locations_indicator.setVisible(True)
        else:
            self.missing_locations_indicator.setVisible(False)

    def generate_pdf(self):
        """Spustí generování PDF s aktualizovanými parametry."""
        if not self.validate_inputs():
            return
    
        self.generation_start_time = time.time()
        n = self.spin_n.value()
        m = self.spin_m.value()
    
        location_path = self.edit_location_path.text()
        clover_path = self.edit_clover_path.text()
        output_folder = self.edit_output_folder.text()
        pages_per_pdf = self.spin_pages_per_pdf.value()
    
        # Bez použití strip: robustní extrakce prvního názvu před čárkou/novým řádkem
        def _extract_first_filename(raw):
            # Pokud by omylem dorazil list, vezmi první prvek
            if isinstance(raw, list):
                raw = raw if raw else ""
            if raw is None:
                raw = ""
            s = str(raw)
            # Najdi první oddělovač (čárka nebo nový řádek)
            end = len(s)
            for sep in (',', '\n', '\r'):
                p = s.find(sep)
                if p != -1 and p < end:
                    end = p
            # Ořezání bílých znaků manuálně (bez strip)
            i = end - 1
            while i >= 0 and s[i].isspace():
                i -= 1
            start = 0
            while start <= i and s[start].isspace():
                start += 1
            return s[start:i+1] if i >= start else ""
    
        raw_name = self.edit_pdf_filename.text()
        pdf_filename = _extract_first_filename(raw_name)
        output_pdf = os.path.join(output_folder, pdf_filename)
    
        # Načtení JSON konfigurace lokací
        try:
            location_config = json.loads(self.location_config_text.toPlainText().strip())
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Chyba", f"Neplatná JSON nastavení lokací:\n{str(e)}")
            return
    
        # Načtení poznámek
        poznamky_dict = {}
        notes_text = self.notes_text.toPlainText().strip()
        if notes_text:
            try:
                notes_data = json.loads(notes_text)
                poznamky_dict = {int(k): v for k, v in notes_data.items()}
            except (json.JSONDecodeError, ValueError) as e:
                QMessageBox.critical(self, "Chyba", f"Neplatný formát poznámek:\n{str(e)}")
                return
    
        # Převod JSON stavů z nového formátu {"STAV": [intervaly/čísla]} na starý {číslo: STAV}
        def _strip_json_comments(text: str) -> str:
            import re
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            text = re.sub(r"//.*", "", text)
            return text
        
        def _parse_status_config_new_format(config_dict):
            """Převede nový formát {"STAV": [intervaly/čísla]} na {číslo: STAV} pro pdf_generator.py"""
            result = {}
            
            for state_name, number_list in config_dict.items():
                if not isinstance(number_list, list):
                    continue
                    
                for item in number_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
                        
                    if '-' in item_str:
                        try:
                            start_str, end_str = item_str.split('-', 1)
                            start_num = int(start_str.strip())
                            end_num = int(end_str.strip())
                            if start_num > end_num:
                                start_num, end_num = end_num, start_num
                            
                            for num in range(start_num, end_num + 1):
                                result[num] = state_name
                        except ValueError:
                            continue
                    else:
                        try:
                            num = int(item_str)
                            result[num] = state_name
                        except ValueError:
                            continue
            
            return result
        
        status_dict = {}
        status_text_raw = self.status_config_text.toPlainText().strip()
        if status_text_raw:
            try:
                status_text = _strip_json_comments(status_text_raw)
                if status_text.strip():
                    data = json.loads(status_text)
                    if not isinstance(data, dict):
                        raise ValueError("JSON konfigurace stavů musí být objekt.")
                    
                    # Převod z nového formátu na starý pro pdf_generator.py
                    status_dict = _parse_status_config_new_format(data)
                    
                    if status_dict:
                        self.update_log(f"✅ Načteno {len(status_dict)} stavových záznamů")
                        
            except Exception as e:
                self.update_log(f"⚠️ Stavový JSON ignorován (chyba): {e}")
                QMessageBox.warning(self, "Varování", f"Konfigurace stavů bude ignorována:\n{e}")

    
        copy_folder = self.edit_copy_folder.text() if self.checkbox_copy_enabled.isChecked() else None
    
        # Vytvoření a spuštění vlákna
        try:
            self.generator_thread = PDFGeneratorThread(
                n=n, m=m, location_config=location_config,
                def_cesta_lokaci=location_path, cesta_ctyrlistky=clover_path,
                output_pdf=output_pdf, poznamky_dict=poznamky_dict, copy_folder=copy_folder,
                pages_per_pdf=pages_per_pdf, status_dict=status_dict
            )
        except Exception as e:
            self.update_log(f"❌ Chyba při přípravě generování: {e}")
            QMessageBox.critical(self, "Chyba", f"Nelze spustit generování:\n{e}")
            return
    
        self.generator_thread.progress_updated.connect(self.update_log_and_progress)
        self.generator_thread.finished_success.connect(self.on_generation_success)
        self.generator_thread.finished_error.connect(self.on_generation_error)
    
        self.btn_generate.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.tabs.setEnabled(False)
    
        for bar in [self.progress_bar_loading, self.progress_bar_combining, self.progress_bar_saving]:
            bar.setValue(0)
            bar.setVisible(True)
    
        self.log_text.clear()
        self.update_log(f"🚀 Spouštím generování PDF pro rozsah: {n} - {m}")
        self.generator_thread.start()

    def validate_inputs(self):
        """Validace vstupních hodnot - s progress indikátorem"""
        self.update_log("🔍 Spouštím validaci vstupních hodnot...")

        # Kontrola rozsahu
        if self.spin_n.value() > self.spin_m.value():
            self.update_log("❌ Chyba: První čtyřlístek (N) nemůže být větší než poslední (M)")
            QMessageBox.warning(self, "Chyba", "První čtyřlístek (N) nemůže být větší než poslední (M)")
            return False

        self.update_log("✅ Rozsah čtyřlístků je v pořádku")

        # Kontrola cest
        paths_to_check = [
            (self.edit_location_path.text(), "mapky lokací", "📁"),
            (self.edit_clover_path.text(), "čtyřlístky", "🍀")
        ]

        for path, name, icon in paths_to_check:
            if not path:
                error_msg = f"❌ Chyba: Zadejte cestu k {name}"
                self.update_log(error_msg)
                QMessageBox.warning(self, "Chyba", f"Zadejte cestu k {name}")
                return False

            if not os.path.exists(path):
                error_msg = f"❌ Chyba: Cesta k {name} neexistuje: {path}"
                self.update_log(error_msg)
                QMessageBox.warning(self, "Chyba", f"Cesta k {name} neexistuje")
                return False

            self.update_log(f"✅ Cesta k {name} je platná")

        # Kontrola výstupní složky
        if not self.edit_output_folder.text():
            self.update_log("❌ Chyba: Zadejte výstupní složku pro PDF")
            QMessageBox.warning(self, "Chyba", "Zadejte výstupní složku pro PDF")
            return False

        # Kontrola názvu PDF souboru
        if not self.edit_pdf_filename.text():
            self.update_log("❌ Chyba: Zadejte název PDF souboru")
            QMessageBox.warning(self, "Chyba", "Zadejte název PDF souboru")
            return False

        # Kontrola přípony .pdf
        if not self.edit_pdf_filename.text().lower().endswith('.pdf'):
            reply = QMessageBox.question(
                self,
                "Přípona souboru",
                "Název souboru neobsahuje příponu .pdf. Chcete ji přidat automaticky?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                current_name = self.edit_pdf_filename.text()
                self.edit_pdf_filename.setText(f"{current_name}.pdf")
                self.update_log(f"✅ Přidána přípona .pdf: {current_name}.pdf")

        # Kontrola existence výstupní složky
        output_folder = self.edit_output_folder.text()
        if not os.path.exists(output_folder):
            reply = QMessageBox.question(
                self,
                "Výstupní složka",
                f"Výstupní složka neexistuje:\n{output_folder}\n\nChcete ji vytvořit?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                try:
                    os.makedirs(output_folder, exist_ok=True)
                    self.update_log(f"✅ Vytvořena výstupní složka: {output_folder}")
                except Exception as e:
                    error_msg = f"❌ Nepodařilo se vytvořit složku: {str(e)}"
                    self.update_log(error_msg)
                    QMessageBox.critical(self, "Chyba", f"Nepodařilo se vytvořit složku:\n{str(e)}")
                    return False
            else:
                self.update_log("❌ Validace zrušena uživatelem")
                return False

        self.update_log("✅ Výstupní složka je v pořádku")

        # Kontrola JSON konfigurace
        try:
            config_text = self.location_config_text.toPlainText().strip()
            json.loads(config_text)
            self.update_log("✅ JSON konfigurace lokací je platná")
        except json.JSONDecodeError as e:
            error_msg = f"❌ Neplatná JSON konfigurace lokací: {str(e)}"
            self.update_log(error_msg)
            QMessageBox.warning(self, "Chyba", "Neplatná JSON konfigurace lokací")
            return False

        # Kontrola JSON poznámek
        notes_text = self.notes_text.toPlainText().strip()
        if notes_text:
            try:
                json.loads(notes_text)
                self.update_log("✅ JSON Nastavení poznámek jsou platné")
            except json.JSONDecodeError as e:
                error_msg = f"❌ Neplatný JSON formát poznámek: {str(e)}"
                self.update_log(error_msg)
                QMessageBox.warning(self, "Chyba", "Neplatný JSON formát poznámek")
                return False
        else:
            self.update_log("ℹ️ Nastavení poznámek nejsou zadány (volitelné)")

        # Kontrola duplicitního souboru
        full_pdf_path = self.get_full_pdf_path()
        if os.path.exists(full_pdf_path):
            reply = QMessageBox.question(
                self,
                "Soubor již existuje",
                f"PDF soubor již existuje:\n{full_pdf_path}\n\nChcete ho přepsat?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.No:
                self.update_log("❌ Generování zrušeno - soubor již existuje")
                return False
            else:
                self.update_log("⚠️ Existující soubor bude přepsán")

        self.update_log("✅ Všechny validace úspěšně dokončeny")
        return True

    def get_full_pdf_path(self):
        """Vrátí celou cestu k PDF souboru"""
        output_folder = self.edit_output_folder.text()
        pdf_filename = self.edit_pdf_filename.text()
        return os.path.join(output_folder, pdf_filename)

    def stop_generation(self):
        """Zastavení generování - opravená verze bez zamrznutí"""
        if hasattr(self, 'generator_thread') and self.generator_thread and self.generator_thread.isRunning():
            self.update_log("⏹️ Zastavuji generování...")
            
            # Použijeme requestInterruption() místo terminate()
            self.generator_thread.requestInterruption()
            
            # Použijeme timeout pro wait() aby se aplikace nezamrzla
            if not self.generator_thread.wait(2000):  # 2 sekundy timeout
                self.update_log("⚠️ Vynucené ukončení vlákna...")
                self.generator_thread.terminate()
                self.generator_thread.wait(1000)
            
            self.update_log("⏹️ Generování zastaveno uživatelem")
            self.reset_ui_after_generation()


    def update_log(self, message: str):
        """
        Bezpečné logování do panelu:
        - pokud log panel ještě není připraven, buffruje řádky do self._early_logs,
        - jakmile je panel vytvořen, vše se flushne a další zprávy jdou rovnou do UI,
        - nikdy nepíše do konzole.
        """
        try:
            # Přidej časovou značku a lehké barevné označení podle ikon (zachováno jako prostý text)
            import datetime
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {message}"

            # Pokud ještě log panel není připraven → buffer
            if not getattr(self, "_log_ready", False) or not hasattr(self, "log_text") or self.log_text is None:
                if not hasattr(self, "_early_logs") or self._early_logs is None:
                    self._early_logs = []
                self._early_logs.append(line)
                return

            # Přímý zápis do panelu
            self._append_log_line(line)

            # UI pump (jemné) – jen pokud existuje QApplication
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    app.processEvents()
            except Exception:
                pass

        except Exception:
            # Záměrně žádný print – logy do konzole nechceme
            pass

    def on_generation_success(self, pdf_paths):
        """Úspěšné dokončení generování - s podporou více souborů a měřením času."""
        # Vypočítáme a zalogujeme celkový čas
        if hasattr(self, 'generation_start_time'):
            end_time = time.time()
            duration = end_time - self.generation_start_time
            self.update_log(f"✅ Celkový čas generování: {duration:.2f} s")
            del self.generation_start_time # Vyčistíme proměnnou

        self.reset_ui_after_generation()

        if isinstance(pdf_paths, list) and len(pdf_paths) > 1:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Generování dokončeno")
            msg.setText(f"✅ Bylo úspěšně vygenerováno {len(pdf_paths)} PDF souborů!")
            
            btn_open_folder = msg.addButton("📁 Otevřít složku", QMessageBox.ActionRole)
            btn_open_all = msg.addButton("📄 Otevřít všechna PDF", QMessageBox.ActionRole)
            btn_ok = msg.addButton("OK", QMessageBox.AcceptRole)
            
            msg.exec()

            clicked_button = msg.clickedButton()
            if clicked_button == btn_open_all:
                for path in pdf_paths:
                    self.open_pdf_file(path)
            elif clicked_button == btn_open_folder:
                self.open_output_folder()
        
        elif isinstance(pdf_paths, list) and len(pdf_paths) == 1:
            self.handle_single_pdf_success(pdf_paths[0])
        else:
            self.handle_single_pdf_success(str(pdf_paths))

    def handle_single_pdf_success(self, pdf_path):
        """Obsluha úspěšného dokončení pro jeden PDF soubor."""
        self.reset_ui_after_generation()
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Generování dokončeno")
        msg.setText("✅ PDF bylo úspěšně vygenerováno!")
        msg.setInformativeText(f"Soubor: {os.path.basename(pdf_path)}")
        msg.setDetailedText(f"Celá cesta:\n{pdf_path}")
        
        btn_open_folder = msg.addButton("📁 Otevřít složku", QMessageBox.ActionRole)
        btn_open_file = msg.addButton("📄 Otevřít PDF", QMessageBox.ActionRole)
        btn_ok = msg.addButton("OK", QMessageBox.AcceptRole)

        msg.exec()

        if msg.clickedButton() == btn_open_folder:
            self.open_output_folder()
        elif msg.clickedButton() == btn_open_file:
            self.open_pdf_file(pdf_path)


    def open_pdf_file(self, pdf_path):
        """Otevře PDF soubor v defaultní aplikaci"""
        try:
            import subprocess
            import platform

            if platform.system() == 'Darwin':  # macOS
                subprocess.Popen(['open', pdf_path])
            elif platform.system() == 'Windows':
                subprocess.Popen(['start', pdf_path], shell=True)
            else:  # Linux
                subprocess.Popen(['xdg-open', pdf_path])

            self.update_log(f"📄 PDF otevřeno: {os.path.basename(pdf_path)}")

        except Exception as e:
            self.update_log(f"❌ Chyba při otevírání PDF: {str(e)}")
            QMessageBox.warning(self, "Chyba", f"Nepodařilo se otevřít PDF:\n{str(e)}")

    def on_generation_error(self, error_message):
        """Chyba při generování"""
        self.reset_ui_after_generation()
        QMessageBox.critical(self, "Chyba generování", f"Došlo k chybě:\n\n{error_message}")
        
    def reset_ui_after_generation(self):
        """Resetuje UI po dokončení generování."""
        self.btn_generate.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.tabs.setEnabled(True)
        
        # Skrytí všech progress barů
        self.progress_bar_loading.setVisible(False)
        self.progress_bar_combining.setVisible(False)
        self.progress_bar_saving.setVisible(False)

        # Cleanup thread
        if hasattr(self, 'generator_thread') and self.generator_thread:
            self.generator_thread.deleteLater()
            self.generator_thread = None

        self.update_full_pdf_path_preview()

    def open_output_folder(self):
        """Otevře výstupní složku v file manageru - aktualizovaná verze"""
        output_folder = self.edit_output_folder.text()
        if output_folder and os.path.exists(output_folder):
            try:
                import subprocess
                import platform

                if platform.system() == 'Darwin':  # macOS
                    subprocess.Popen(['open', output_folder])
                elif platform.system() == 'Windows':
                    subprocess.Popen(['explorer', output_folder])
                else:  # Linux
                    subprocess.Popen(['xdg-open', output_folder])

                self.update_log(f"📁 Složka otevřena: {output_folder}")

            except Exception as e:
                self.update_log(f"❌ Chyba při otevírání složky: {str(e)}")
                QMessageBox.warning(self, "Chyba", f"Nepodařilo se otevřít složku:\n{str(e)}")
        else:
            QMessageBox.warning(self, "Chyba", "Výstupní složka neexistuje nebo není zadána")

    def save_settings(self):
        """Uloží aktuální nastavení a stav ořezání fotek do složky 'settings'."""
        from pathlib import Path
        import json
        from PySide6.QtWidgets import QMessageBox

        settings_dir = Path("settings")
        settings_dir.mkdir(exist_ok=True)  # Zajistí, že složka existuje

        settings_path = settings_dir / "pdf_generator_settings.json"
        crop_status_path = settings_dir / "crop_status.json"  # nezávislý soubor pro ořezy

        # Sestav slovník nastavení
        try:
            settings = {
                'n': self.spin_n.value(),
                'm': self.spin_m.value(),
                'location_path': self.edit_location_path.text(),
                'clover_path': self.edit_clover_path.text(),
                'output_folder': self.edit_output_folder.text(),
                'pdf_filename': self.edit_pdf_filename.text(),
                'auto_filename': self.checkbox_auto_filename.isChecked(),
                'copy_folder': self.edit_copy_folder.text() if hasattr(self, 'edit_copy_folder') else '',
                'copy_enabled': self.checkbox_copy_enabled.isChecked() if hasattr(self, 'checkbox_copy_enabled') else False,
                'location_config': self.location_config_text.toPlainText() if hasattr(self, 'location_config_text') else '',
                'notes': self.notes_text.toPlainText() if hasattr(self, 'notes_text') else '',
                'status_config': self.status_config_text.toPlainText() if hasattr(self, 'status_config_text') else '',
                # ✅ NOVÉ: ulož i JSON anonymizace
                'anonym_config': self.anonym_config_text.toPlainText() if hasattr(self, 'anonym_config_text') else ''
            }
        except Exception as e:
            if hasattr(self, 'update_log'):
                self.update_log(f"⚠️ Chyba při čtení vstupů pro uložení nastavení: {e}")
            settings = {}

        # Uložení nastavení
        try:
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            if hasattr(self, 'update_log'):
                self.update_log(f"💾 Nastavení uloženo do: {settings_path}")
        except Exception as e:
            if hasattr(self, 'update_log'):
                self.update_log(f"⚠️ Chyba při ukládání nastavení: {e}")
            QMessageBox.warning(self, "Varování", f"Nepodařilo se uložit nastavení:\n{str(e)}")

        # Uložení stavu ořezání
        try:
            with open(crop_status_path, "w", encoding="utf-8") as f:
                json.dump(getattr(self, 'crop_status', {}), f, indent=2, ensure_ascii=False)
            if hasattr(self, 'update_log'):
                self.update_log(f"💾 Stav ořezání uložen do: {crop_status_path}")
        except Exception as e:
            if hasattr(self, 'update_log'):
                self.update_log(f"⚠️ Chyba při ukládání stavu ořezání: {e}")

    def load_settings(self):
        """Načte uložená nastavení a stav ořezání fotek ze složky 'settings'."""
        from pathlib import Path
        import json
        from PySide6.QtCore import QTimer

        settings_dir = Path("settings")
        settings_path = settings_dir / "pdf_generator_settings.json"
        crop_status_path = settings_dir / "crop_status.json"

        # Výchozí hodnoty (včetně anonymizace)
        default_settings = {
            'n': 13590, 'm': 13590,
            'location_path': '',
            'clover_path': '',
            'output_folder': '',
            'pdf_filename': '',
            'auto_filename': True,
            'copy_folder': '',
            'copy_enabled': False,
            'location_config': '{\n "36": ["13600-13680", "13681"],\n "8": ["13300-13301"]\n}',
            'notes': '{\n "13302": "DAR - BIP 2025"\n}',
            'status_config': '{}',
            # ✅ NOVÉ: výchozí JSON anonymizace
            'anonym_config': '{\n "ANONYMIZOVANE": []\n}'
        }

        # Načti nastavení
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                settings = {**default_settings, **(saved or {})}
                if hasattr(self, 'update_log'):
                    self.update_log(f"✅ Nastavení načteno z: {settings_path}")
            except Exception as e:
                settings = default_settings
                if hasattr(self, 'update_log'):
                    self.update_log(f"⚠️ Chyba při načítání nastavení: {e}")
        else:
            settings = default_settings
            if hasattr(self, 'update_log'):
                self.update_log("ℹ️ Používám výchozí nastavení")

        # Aplikuj nastavení do UI
        try:
            self.spin_n.setValue(settings['n'])
            self.spin_m.setValue(settings['m'])
            self.edit_location_path.setText(settings['location_path'])
            self.edit_clover_path.setText(settings['clover_path'])
            self.edit_output_folder.setText(settings['output_folder'])
            if hasattr(self, 'edit_copy_folder'):
                self.edit_copy_folder.setText(settings['copy_folder'])
            if hasattr(self, 'checkbox_copy_enabled'):
                self.checkbox_copy_enabled.setChecked(settings['copy_enabled'])
            if hasattr(self, 'location_config_text'):
                self.location_config_text.setPlainText(settings['location_config'])
            if hasattr(self, 'notes_text'):
                self.notes_text.setPlainText(settings['notes'])
            if hasattr(self, 'status_config_text'):
                self.status_config_text.setPlainText(settings['status_config'])
            if hasattr(self, 'anonym_config_text'):
                # ✅ NOVÉ: načti uložený JSON anonymizace
                self.anonym_config_text.setPlainText(settings.get('anonym_config', default_settings['anonym_config']))
            if hasattr(self, 'checkbox_auto_filename'):
                self.checkbox_auto_filename.setChecked(settings['auto_filename'])
            if settings.get('pdf_filename'):
                self.edit_pdf_filename.setText(settings['pdf_filename'])
            else:
                if hasattr(self, 'update_pdf_filename'):
                    self.update_pdf_filename()
        except Exception as e:
            if hasattr(self, 'update_log'):
                self.update_log(f"⚠️ Chyba při aplikaci nastavení do UI: {e}")

        # Načti stav ořezání
        try:
            self.crop_status_file = crop_status_path
            if crop_status_path.exists():
                with open(crop_status_path, "r", encoding="utf-8") as f:
                    self.crop_status = json.load(f)
                if hasattr(self, 'update_log'):
                    self.update_log(f"✅ Stav ořezání načten z: {crop_status_path}")
            else:
                self.crop_status = {}
        except Exception as e:
            self.crop_status = {}
            if hasattr(self, 'update_log'):
                self.update_log(f"⚠️ Chyba při načítání crop_status.json: {e}")

        # Refreshy / watchery (ponecháno dle existující logiky)
        if hasattr(self, '_refresh_clover_watcher'):
            self._refresh_clover_watcher()
        if hasattr(self, '_refresh_output_watcher'):
            self._refresh_output_watcher()
        if hasattr(self, 'update_clover_stats_label'):
            QTimer.singleShot(50, self.update_clover_stats_label)
        if hasattr(self, 'update_full_pdf_path_preview'):
            QTimer.singleShot(50, self.update_full_pdf_path_preview)
        if hasattr(self, 'update_missing_photos_list'):
            QTimer.singleShot(200, self.update_missing_photos_list)
        if hasattr(self, 'check_duplicate_photos_real_time'):
            QTimer.singleShot(300, self.check_duplicate_photos_real_time)
        if hasattr(self, 'check_missing_locations_real_time'):
            QTimer.singleShot(350, self.check_missing_locations_real_time)
        if hasattr(self, 'update_status_photos_list'):
            QTimer.singleShot(400, self.update_status_photos_list)
        if hasattr(self, 'check_duplicate_states_real_time'):
            QTimer.singleShot(400, self.check_duplicate_states_real_time)
        if hasattr(self, 'check_states_without_notes_real_time'):
            QTimer.singleShot(450, self.check_states_without_notes_real_time)
        if hasattr(self, 'update_pdf_pages_stats'):
            QTimer.singleShot(100, self.update_pdf_pages_stats)

    def _load_crop_status(self):
        """Načte stavy ořezu fotek ze souboru crop_status.json."""
        try:
            if self.crop_status_file.exists():
                with open(self.crop_status_file, 'r', encoding='utf-8') as f:
                    self.crop_status = json.load(f)
                self.update_log(f"✅ Načteno {len(self.crop_status)} stavů ořezu.")
            else:
                self.update_log("ℹ️ Soubor se stavy ořezu nenalezen, bude vytvořen při uložení.")
                self.crop_status = {}
                
        except (json.JSONDecodeError, IOError) as e:
            self.update_log(f"❌ Chyba při načítání stavů ořezu: {e}")
            self.crop_status = {}

    def _save_crop_status(self):
        """Uloží aktuální stavy ořezu fotek do souboru crop_status.json."""
        try:
            # Vytvoření složky pokud neexistuje
            self.crop_status_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Zápis JSON dat
            with open(self.crop_status_file, 'w', encoding='utf-8') as f:
                json.dump(self.crop_status, f, ensure_ascii=False, indent=2)
                
            self.update_log(f"💾 Stav ořezání uložen ({len(self.crop_status)} fotek)")
            
        except Exception as e:
            self.update_log(f"❌ Chyba při ukládání stavů ořezu: {e}")
            
    def check_duplicate_photos_real_time(self):
        """Real-time kontrola duplicitních přiřazení čísel fotek"""
        try:
            config_text = self.location_config_text.toPlainText().strip()
            duplicates = set()
            
            if config_text:
                try:
                    data = json.loads(config_text)
                    if isinstance(data, dict):
                        duplicates = self._find_duplicate_numbers_in_config(data)
                except json.JSONDecodeError:
                    # JSON není platný, neukazuj chyby duplicit
                    pass
            
            # Aktualizuj pouze indikátor duplicit
            self._update_duplicates_indicator(duplicates)
            
        except Exception:
            # Tichá chyba - nenarušuj uživatelské rozhraní
            pass
    
    def check_missing_locations_real_time(self):
        """Real-time kontrola neexistujících lokací ve složce"""
        try:
            config_text = self.location_config_text.toPlainText().strip()
            missing_locations = set()
            
            if config_text:
                try:
                    data = json.loads(config_text)
                    if isinstance(data, dict):
                        missing_locations = self._find_missing_location_folders(data)
                except json.JSONDecodeError:
                    # JSON není platný, neukazuj chyby lokací
                    pass
            
            # Aktualizuj pouze indikátor chybějících lokací
            self._update_missing_locations_indicator(missing_locations)
            
        except Exception:
            # Tichá chyba - nenarušuj uživatelské rozhraní
            pass
    
    def trigger_all_location_checks(self):
        """Spustí všechny kontroly lokací nezávisle"""
        # Spustí obě kontroly samostatně
        QTimer.singleShot(50, self.check_duplicate_photos_real_time)
        QTimer.singleShot(100, self.check_missing_locations_real_time)


    def _mark_log_ready(self):
        """
        Označí log panel jako připravený a vyprázdní early‑buffer do self.log_text.
        Bez efektu, pokud již bylo provedeno.
        """
        try:
            if getattr(self, "_log_ready", False):
                return
            if not hasattr(self, "log_text") or self.log_text is None:
                return

            # Flush early zpráv (pokud nějaké jsou)
            for line in getattr(self, "_early_logs", []) or []:
                self._append_log_line(line)
            self._early_logs = []
            self._log_ready = True
        except Exception:
            # Bezpečný no‑op; nechceme padat při startu okna
            pass

    def _append_log_line(self, message: str):
        """
        Interní: zapíše jednu zprávu do log panelu se zachováním auto‑scrollu.
        Používá HTML formátování pro barevné rozlišení podle typu zprávy.
        """
        try:
            # Určení barvy podle ikony ve zprávě
            color = self._get_log_color(message)
            
            # HTML formátování s barvou
            html_message = f'<span style="color: {color};">{message}</span>'
            
            # Přidání do log panelu
            self.log_text.append(html_message)
            
            # Auto‑scroll
            try:
                sb = self.log_text.verticalScrollBar()
                if sb is not None:
                    sb.setValue(sb.maximum())
            except Exception:
                pass
        except Exception:
            pass
    
    def _get_log_color(self, message: str):
        """Určí barvu zprávy podle jejího obsahu/ikony"""
        # Pozitivní zprávy - zelená
        positive_icons = ['✅', '🚀', '📄', '📁', '💾', '🔗', '🎯']
        if any(icon in message for icon in positive_icons):
            return '#4CAF50'  # Zelená
        
        # Chybové zprávy - červená  
        error_icons = ['❌', '⚠️', '🚫']
        if any(icon in message for icon in error_icons):
            return '#f44336'  # Červená
        
        # Ostatní informativní zprávy - bílá (světlá pro dark theme)
        return '#e6e6e6'  # Bílá/světlá

    # FILE: gui/pdf_generator_window.py
    # CLASS: PdfGeneratorWindow
    # FUNCTION: _cleanup_bak_files
    # PŘIDEJ TUTO NOVOU FUNKCI DO TŘÍDY (neměň nic jiného).
    def _cleanup_bak_files(self) -> None:
        """
        Smaže všechny .bak soubory ve složce:
          /Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/
        Tichý běh (bez dialogů). Chyby jsou ignorovány.
        """
        import os
        from pathlib import Path
    
        root = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/")
        if not root.is_dir():
            return
    
        try:
            for name in os.listdir(root):
                p = root / name
                # pouze soubory přímo v této složce (bez podsložek)
                if p.is_file() and p.suffix.lower() == ".bak":
                    try:
                        p.unlink()
                    except Exception:
                        # tiché přeskočení na případné zamčené / nedostupné soubory
                        pass
        except Exception:
            pass
            
    def closeEvent(self, event):
        """Uloží nastavení a zastaví vlákno před zavřením"""
        self.stop_clover_validation_timer()
        self._save_crop_status()
        self._cleanup_bak_files()
        self.save_settings()
        if hasattr(self, 'generator_thread') and self.generator_thread and self.generator_thread.isRunning():
            self.generator_thread.terminate()
            self.generator_thread.wait(3000)
        if hasattr(self, 'generator_thread'):
            del self.generator_thread
        self.update_log("👋 PDF okno se zavírá – nastavení uloženo a vlákna uklizena")
        event.accept()

# FILE: gui/pdf_generator_window.py
# === NOVÁ TŘÍDA (modulová, mimo jakoukoli jinou třídu) ===
# Umožní hromadný Drag&Drop přesun mezi dvěma stromovými widgety složek.
# Použitá POUZE v záložce „📂 Přehled vygenerovaných PDF“ přes create_file_tree_widget().
from PySide6.QtWidgets import QTreeView
from PySide6.QtCore import Qt, QMimeData, QModelIndex
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
import os, shutil, pathlib

class FileTreeView(QTreeView):
    """QTreeView s podporou hromadného přesunu souborů pomocí Drag&Drop.
       Předpokládá QFileSystemModel jako model a platný .root_path (cílový kořen)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QTreeView.ExtendedSelection)
        self.root_path = ""   # nastavuje create_file_tree_widget

    def _dest_dir_for_index(self, index: QModelIndex) -> str:
        """Vrátí cílovou složku pro drop podle indexu."""
        model = self.model()
        if not model:
            return self.root_path or ""
        if index.isValid():
            p = model.filePath(index)
            try:
                if os.path.isdir(p):
                    return p
                return os.path.dirname(p)
            except Exception:
                return self.root_path or ""
        return self.root_path or ""

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e: QDragMoveEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e: QDropEvent):
        md: QMimeData = e.mimeData()
        if not md.hasUrls():
            return super().dropEvent(e)

        dest_dir = self._dest_dir_for_index(self.indexAt(e.position().toPoint()))
        if not dest_dir or not os.path.isdir(dest_dir):
            return super().dropEvent(e)

        # Přesuň všechny soubory
        moved = 0
        skipped = 0
        errors = 0
        for url in md.urls():
            try:
                src = url.toLocalFile()
                if not src or not os.path.isfile(src):
                    skipped += 1
                    continue
                base = os.path.basename(src)
                dst = os.path.join(dest_dir, base)
                if os.path.abspath(src) == os.path.abspath(dst):
                    skipped += 1
                    continue
                if os.path.exists(dst):
                    # kolize názvu -> přeskočit (nepřepisujeme)
                    skipped += 1
                    continue
                shutil.move(src, dst)
                moved += 1
            except Exception:
                errors += 1
                continue

        # Refresh modelu – změny se obvykle propíší samy, ale tímhle to jistíme.
        try:
            m = self.model()
            if hasattr(m, "setRootPath") and self.root_path:
                m.setRootPath(self.root_path)
                self.setRootIndex(m.index(self.root_path))
        except Exception:
            pass

        e.acceptProposedAction()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PDFGeneratorWindow()
    window.show()
    sys.exit(app.exec())
