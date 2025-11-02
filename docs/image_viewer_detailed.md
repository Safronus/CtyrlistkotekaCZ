# Dokumentace (`image_viewer.py`) – podrobná verze

**Soubor:** `image_viewer.py`  
**SHA-256:** `f02d609dfcea4840ed3226564ac1081c0f7bd09785692582dad3cabffa1759c7`  •  **Řádků:** 4124  •  **Velikost:** 177144 B  
**Generováno:** 2025-10-29

---

## 1. Role a architektura
- Modul obsahuje okno/dialog postavené na PySide6 a obsluhu GUI prvků (toolbar, zkratky, signály/sloty).

## 2. Importy a závislosti
### 2.1 Projektové moduly (lokální)
- `import platform`
- `import platform`
- `import unicodedata`
- `import tempfile`
- `import tempfile`
- `from map_processor import MapProcessor`
- `import importlib.util`
- `import pillow_heif`
- `import piexif`
- `import piexif`
- `import pillow_heif`
- `import pillow_heif`
- `import piexif`
- `import pillow_heif`
- `import piexif`
- `import pillow_heif`
- `import piexif`
- `import tempfile`
- `import pillow_heif`
- `from image_viewer import open_polygon_editor_for_file, read_polygon_metadata`
- `import importlib.util`
- `import pillow_heif`
- `import piexif`

### 2.2 Knihovny třetích stran
- `PySide6.QtWidgets` (import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, )
- `PySide6.QtCore` (import Qt, Signal, QTimer, QEvent, QPointF)
- `PySide6.QtGui` (import QPixmap, QFont)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtWidgets` (import QApplication)
- `PIL` (import Image, ImageQt)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtWidgets` (import QSizePolicy)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtGui` (import QKeySequence)
- `PySide6.QtWidgets` (import QLabel)
- `PIL.ExifTags` (import TAGS)
- `PySide6.QtCore` (import QSize)
- `PySide6.QtCore` (import Qt, QEvent, QPointF)
- `PySide6.QtWidgets` (import QWidget, QHBoxLayout, QLabel, QComboBox, QSpinBox, QMenu)
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtGui` (import QPixmap)
- `PySide6.QtCore` (import Qt)
- `numpy`
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QPixmap, QPainter, QPen, QColor, QCursor)
- `PySide6.QtCore` (import Qt)
- `cv2`
- `cv2`
- `cv2`
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QPainter, QPen, QBrush, QColor, QPolygonF)
- `PySide6.QtGui` (import QFont, QFontMetrics)
- `PySide6.QtCore` (import QRect)
- `PySide6.QtCore` (import QPointF, Qt)
- `PySide6.QtCore` (import QPointF, Qt)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtGui` (import QPixmap, QGuiApplication, QShortcut, QKeySequence)
- `PySide6.QtCore` (import QTimer, Qt, QPointF)
- `PIL` (import Image, ImageQt)
- `PySide6.QtWidgets` (import QGroupBox, QHBoxLayout, QLabel, QCheckBox, QSpinBox)
- `PySide6.QtWidgets` (import QCheckBox, QGroupBox)
- `PySide6.QtWidgets` (import QGroupBox, QGridLayout, QLabel, QSpinBox)
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtWidgets` (import QColorDialog)
- `PIL` (import Image as _Image)
- `PySide6.QtCore` (import QPointF)
- `PySide6.QtWidgets` (import QLabel, QCheckBox, QGroupBox, QVBoxLayout, QWidget)
- `PySide6.QtCore` (import Qt)
- `PIL` (import Image as _Image)
- `PIL` (import Image)
- `PIL` (import Image, ImageDraw)
- `PIL.PngImagePlugin` (import PngInfo)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtWidgets` (import QDialog, QWidget)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtGui` (import QPixmap, QImage, QPainter, QPen, QShortcut, QKeySequence)
- `PySide6.QtCore` (import Qt, QSize)
- `PySide6.QtWidgets` (import QWidget)
- `PySide6.QtGui` (import QPen)
- `PySide6.QtWidgets` (import QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsPathItem)
- `PIL` (import Image)
- `PIL` (import Image)
- `PIL` (import Image)
- `PySide6.QtCore` (import QEvent)
- `PIL` (import Image)
- `PIL` (import Image)
- `PIL` (import Image)
- `PIL` (import Image, PngImagePlugin)
- `PySide6.QtWidgets` (import QMessageBox)
- `PIL` (import Image, ImageDraw, ImageFilter)
- `PySide6.QtWidgets` (import QMessageBox)

### 2.3 Standardní knihovna (výběr)
json, math, os, pathlib, re, subprocess

## 3. Třídy v souboru
### 3.1 `ImageViewerDialog`  
Báze: QDialog
> Dialog pro zobrazení obrázku s metadaty

### 3.2 `PolygonCanvas`  
Báze: QWidget
> Kreslící widget nad bitmapou s interaktivním polygonem s podporou zoomu, přidávání/mazání bodů,     posunu jednotlivých bodů a posunu celého polygonu myší v rámci hranic obrázku.     Přidáno: překryvné (cizí) polygony pouze pro vizuální náhled (neukládají se).

### 3.3 `PolygonEditorDialog`  
Báze: QDialog
> Editor oblasti nad PNG: zoom, přidávání/mazání bodů, posun polygonu, volba barvy, uložení do AOI_POLYGON.     Reorganizace: logické skupiny ovladačů, jednotný styl tlačítek, širší pravý panel a 'Odznačit vše'.     Překryvné polygony: checkboxy map ze složky 'Neroztříděné' s uloženým AOI_POLYGON (pouze náhled).

### 3.4 `HeicPreviewDialog`  
Báze: QDialog
> Náhled .HEIC s volbou čísla lokace, přejmenováním na     <název_mapy_s_ID>_reálné foto.HEIC, doporučením nejbližších map (jen z metadat)     a úpravou polygonu (editor přes dočasné PNG). Polygon se ukládá do EXIF (AOI_POLYGON=...).

## 4. Signály, sloty, zkratky, akce, docky
### 4.1 Signál → Slot (detekováno)
| Emitter | Slot |
|---|---|
| `self.btn_prev` | `navigate_prev` |
| `self.btn_next` | `navigate_next` |
| `self.btn_zoom_in` | `zoom_in` |
| `self.btn_zoom_out` | `zoom_out` |
| `self.btn_zoom_fit` | `zoom_fit` |
| `self.btn_zoom_100` | `zoom_100` |
| `self.btn_open_folder` | `open_folder` |
| `self.btn_delete` | `delete_file` |
| `self.btn_close` | `accept` |
| `self._sc_left` | `navigate_prev` |
| `self._sc_right` | `navigate_next` |
| `self._sc_up` | `navigate_prev` |
| `self._sc_down` | `navigate_next` |
| `self._sc_del` | `delete_file` |
| `self._sc_close` | `reject` |
| `self._sc_escape` | `reject` |
| `self._sc_space_close` | `accept` |
| `self.btn_deselect_all` | `_on_deselect_all_overlays` |
| `self.chk_add_mode` | `_on_add_mode_toggled` |
| `self.chk_del_mode` | `_on_delete_mode_toggled` |
| `self.chk_move_mode` | `_on_move_mode_toggled` |
| `self.btn_zoom_fit` | `_on_zoom_fit` |
| `self.spin_alpha` | `_on_alpha_changed` |
| `self.btn_color` | `_on_pick_color` |
| `self.btn_reset_poly` | `_on_reset_polygon` |
| `self.btn_clear_poly` | `_on_clear_polygon` |
| `self.btn_cancel` | `reject` |
| `self.btn_ok` | `_on_save` |
| `self.chk_brush_mode` | `_on_brush_mode_toggled` |
| `self.spin_brush_radius` | `_on_brush_value_changed` |
| `self.btn_edit_polygon` | `_on_edit_polygon` |
| `self.btn_save` | `_on_save` |
| `self._sc_close` | `close` |

### 4.2 Zkratky (QShortcut / QAction.setShortcut)
| Sekvence | Zdroj |
|---|---|
| `QKeySequence.Close` | QShortcut |
| `QKeySequence.Close` | QShortcut |
| `QKeySequence.Close` | QShortcut |
| `QKeySequence.Copy` | QShortcut |
| `QKeySequence.Paste` | QShortcut |

### 4.3 QAction
_—_

### 4.4 Dock widgety
_—_

## 5. Výchozí cesty a dialogy
_—_

## 6. Vazby na další soubory
image_viewer, map_processor


### 7. QA scénáře (smoke test)
1. Otevři náhled HEIC (mezerník) → **Upravit polygon**.
2. Přepni **Vymalovat (štětcem)** (checkbox) → kurzor je kolečko v barvě polygonu, výchozí 5 px.
3. Tahem myši vybarvuj plochu; zvy̌š/sniž štětec (spinbox) → plynulé vykreslení a správný poloměr.
4. **Resetovat polygon** a **Vymazat polygon** – ověř, že zmizí body i vybarvená maska.
5. Změň barvu a průhlednost → náhled se okamžitě aktualizuje.
6. Zoom **+/-**, **Fit**, **1:1** → HiDPI ok, bez posunu kurzoru/proporcí.
7. Ulož polygon → znovu otevři → shoda s uloženým stavem.


### 8. Zkratky – přehled a možné kolize
| Sekvence (zdroj) | Poznámka |
|---|---|
| `QKeySequence.Close` (QShortcut) | ⚠️ rezervováno macOS |
| `QKeySequence.Close` (QShortcut) | ⚠️ rezervováno macOS |
| `QKeySequence.Close` (QShortcut) | ⚠️ rezervováno macOS |
| `QKeySequence.Copy` (QShortcut) | ⚠️ rezervováno macOS |
| `QKeySequence.Paste` (QShortcut) | ⚠️ rezervováno macOS |

**Možné kolize v rámci souboru:** QKeySequence.Close

**Doporučení:** vyhnout se přemapování `Cmd+W`, `Cmd+Q`, `Cmd+H`; sjednotit zkratky v README; ponechat `Space` pro náhled/preview.

---

## 9. Integrita zdrojového souboru
- Počet řádků: **4124**  •  Velikost: **177144 B**  •  SHA-256: `f02d609dfcea4840ed3226564ac1081c0f7bd09785692582dad3cabffa1759c7`
- První 3 neprázdné řádky:
  - `# -*- coding: utf-8 -*-`
  - `from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, `
  - `                              QPushButton, QScrollArea, QTextEdit, QSplitter,`
- Poslední 3 neprázdné řádky:
  - `    def _dbg(self, *args):`
  - `        """Jednoduchý konzolový debug s prefixem dialogu."""`
  - `        print("[HEIC_PREVIEW]", *args)`