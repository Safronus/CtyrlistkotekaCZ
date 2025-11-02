# Dokumentace (`pdf_generator_window.py`) – podrobná verze

**Soubor:** `pdf_generator_window.py`  
**SHA-256:** `1e474b2af2b451d593bbc1a9c63a029ce4012ac191efdb39cea0fe0df5a0f5bc`  •  **Řádků:** 9456  •  **Velikost:** 408225 B  
**Generováno:** 2025-10-29

---

## 1. Role a architektura
- Modul obsahuje okno/dialog postavené na PySide6 a obsluhu GUI prvků (toolbar, zkratky, signály/sloty).

## 2. Importy a závislosti
### 2.1 Projektové moduly (lokální)
- `from pdf_generator import main as generate_pdf_main`
- `from shapely.geometry import Point, Polygon`
- `import platform`
- `import resource`
- `import io`
- `import piexif`
- `import piexif`
- `import pillow_heif`
- `import pillow_heif`
- `import pytesseract`
- `import piexif`
- `import pillow_heif`
- `import exifread`
- `import colorsys`
- `import platform`
- `import platform`
- `import platform`

### 2.2 Knihovny třetích stran
- `PySide6.QtWidgets` (import ()
- `PySide6.QtCore` (import ()
- `PySide6.QtGui` (import ()
- `PySide6.QtWidgets` (import QRubberBand)
- `PySide6.QtGui` (import QImage, QPainter)
- `PySide6.QtGui` (import QPixmap, QShortcut, QKeySequence, QImage)
- `PySide6.QtWidgets` (import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QApplication, QMessageBox, QRubberBand)
- `PySide6.QtCore` (import Qt, QSize, QRect, QPoint)
- `PIL` (import Image, ImageQt)
- `PIL` (import Image)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QInputDialog, QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox, QInputDialog)
- `PySide6.QtCore` (import QObject, QThread, Signal)
- `PIL` (import Image, ExifTags)
- `PIL` (import Image, ExifTags)
- `PySide6.QtCore` (import Qt)
- `PIL` (import Image)
- `PySide6.QtCore` (import Qt, QDir)
- `PySide6.QtWidgets` (import QFileDialog, QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QPlainTextEdit, QTextEdit)
- `PySide6.QtWidgets` (import QPlainTextEdit, QTextEdit)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtWidgets` (import QProgressDialog, QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton, QHBoxLayout, QListWidgetItem)
- `PySide6.QtCore` (import Qt, QSize)
- `PySide6.QtGui` (import QFont, QAction, QKeySequence)
- `cv2`
- `numpy`
- `PIL` (import Image, ExifTags)
- `PIL` (import Image)
- `PIL` (import Image)
- `PIL` (import Image)
- `cv2`
- `numpy`
- `PIL` (import Image)
- `cv2`
- `numpy`
- `PySide6.QtWidgets` (import QTreeView)
- `PySide6.QtWidgets` (import QLabel)
- `PySide6.QtWidgets` (import QPushButton)
- `PySide6.QtCore` (import Qt, QObject, QEvent)
- `PySide6.QtGui` (import QFontMetrics)
- `PySide6.QtWidgets` (import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy)
- `PySide6.QtWidgets` (import QTreeView)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtCore` (import Qt, QSize)
- `PySide6.QtWidgets` (import QInputDialog)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtCore` (import QFileSystemWatcher)
- `PySide6.QtWidgets` (import QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QPushButton)
- `PySide6.QtGui` (import QFont)
- `PySide6.QtCore` (import QTimer, QFileSystemWatcher)
- `PySide6.QtCore` (import QFileSystemWatcher)
- `PySide6.QtWidgets` (import QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QPushButton)
- `PySide6.QtGui` (import QFont)
- `PySide6.QtCore` (import QTimer, QFileSystemWatcher)
- `PySide6.QtCore` (import QFileSystemWatcher)
- `PySide6.QtWidgets` (import QApplication)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtWidgets` (import QTreeView)
- `PySide6.QtCore` (import Qt, QMimeData, QModelIndex)
- `PySide6.QtGui` (import QDragEnterEvent, QDragMoveEvent, QDropEvent)

### 2.3 Standardní knihovna (výběr)
datetime, json, math, os, pathlib, re, shutil, subprocess, sys, time

## 3. Třídy v souboru
### 3.1 `PDFGeneratorThread`  
Báze: QThread
> Thread pro generování PDF na pozadí - opravená verze

### 3.2 `ImagePreviewDialog`  
Báze: QDialog

### 3.3 `LineNumberArea`  
Báze: QWidget

### 3.4 `JSONCodeEditor`  
Báze: QPlainTextEdit
> QPlainTextEdit s levým sloupcem čísel řádků a vložením 2 mezer na Tab.

### 3.5 `AnonymPhotosWidget`  
Báze: QWidget
> Widget pro zobrazení fotek bez anonymizace s jedinou akcí 'Anonymizovat'.
**Metody (výběr):**
- `__init__(self, parent=None)`
- `setup_ui(self)`
- `update_photos_list(self, folder_path, crop_status=None)` — Aktualizuje seznam fotek, které NEJSOU v JSONu anonymizace.
- `show_context_menu(self, position)` — Kontextové menu s JEDINOU akcí 'Anonymizovat'.
- `_action_anonymize(self, photo_items)` — Přidá vybraná čísla do JSONu anonymizace (sloučí do intervalů).

### 3.6 `NotesPhotosWidget`  
Báze: QWidget
> Widget pro zobrazení fotek bez zapsané Nastavení poznámek s jedinou akcí 'Zapsat poznámku'.
**Metody (výběr):**
- `__init__(self, parent=None)`
- `setup_ui(self)`
- `update_photos_list(self, folder_path, crop_status=None)` — Aktualizuje seznam fotek BEZ poznámky (stejná logika čtení složky jako ve 'Stavech').
- `show_context_menu(self, position)` — Kontextové menu s JEDINOU akcí 'Zapsat poznámku' (funguje 1:1 jako ve Web fotky).
- `_action_write_note(self, photo_items)` — Otevře modální vstup a zapíše poznámku do <PdfGeneratorWindow>.notes_text pro vybraná čísla.
- `format_json_compact_fixed(self, data)` — Formátuje JSON v kompaktním stylu – každý klíč na jeden řádek se zarovnáním.

### 3.7 `PhotosStatusWidget`  
Báze: QWidget
> Widget pro zobrazení fotek ze složky čtyřlístků s možností přiřazování stavů

### 3.8 `_AnnotateWorker`  
Báze: QObject

### 3.9 `MissingPhotosWidget`  
Báze: QWidget
> Widget pro zobrazení nepřiřazených fotek čtyřlístků s multi-select a kontextovým menu

### 3.10 `PDFGeneratorWindow`  
Báze: QDialog
> Okno pro generování PDF z čtyřlístků

### 3.11 `_ClearPosFilter`  
Báze: QObject

### 3.12 `FileTreeView`  
Báze: QTreeView
> QTreeView s podporou hromadného přesunu souborů pomocí Drag&Drop.        Předpokládá QFileSystemModel jako model a platný .root_path (cílový kořen).

## 4. Signály, sloty, zkratky, akce, docky
### 4.1 Signál → Slot (detekováno)
| Emitter | Slot |
|---|---|
| `self.shortcut_crop` | `crop_image` |
| `self.shortcut_undo` | `undo_crop` |
| `self.crop_button` | `crop_image` |
| `self.undo_button` | `undo_crop` |
| `self.btn_log_clear` | `_on_log_clear_click` |
| `self.spin_n` | `update_pdf_filename` |
| `self.spin_m` | `update_pdf_filename` |
| `self.edit_output_folder` | `update_full_pdf_path_preview` |
| `self.notes_text` | `check_states_without_notes_real_time` |
| `self.btn_generate` | `generate_pdf` |
| `self.btn_stop` | `stop_generation` |
| `self.btn_export_json` | `export_json_settings` |
| `self.checkbox_auto_filename` | `on_auto_filename_toggled` |
| `self.spin_n` | `_trigger_clover_validation` |
| `self.spin_m` | `_trigger_clover_validation` |
| `self.edit_clover_path` | `update_clover_stats_label` |
| `self.edit_clover_path` | `update_missing_photos_list` |
| `self.edit_clover_path` | `_refresh_clover_watcher` |
| `self.edit_output_folder` | `_refresh_output_watcher` |
| `self.spin_n` | `update_pdf_filename` |
| `self.spin_m` | `update_pdf_filename` |
| `self.spin_pages_per_pdf` | `update_pdf_filename` |
| `self.spin_n` | `update_pdf_pages_stats` |
| `self.spin_m` | `update_pdf_pages_stats` |
| `self.spin_pages_per_pdf` | `update_pdf_pages_stats` |
| `self.edit_output_folder` | `update_full_pdf_path_preview` |
| `self.edit_pdf_filename` | `update_full_pdf_path_preview` |
| `self.btn_validate_config` | `validate_location_config` |
| `self.location_config_text` | `update_missing_photos_list` |
| `self.location_config_text` | `trigger_all_location_checks` |
| `self.show_all_photos_checkbox` | `on_toggle_show_all_photos` |
| `self.btn_quick_crop` | `open_first_uncropped_photo` |
| `self.btn_quick_crop` | `find_first_uncropped_photo` |
| `self.notes_text` | `check_states_without_notes_real_time` |
| `self.notes_text` | `update_notes_photos_list` |
| `self.btn_validate_notes` | `validate_notes` |
| `self.btn_validate_status` | `validate_status_config` |
| `self.btn_sort_status` | `sort_status_json` |
| `self.status_config_text` | `update_status_photos_list` |
| `self.status_config_text` | `check_duplicate_states_real_time` |
| `self.status_config_text` | `check_states_without_notes_real_time` |
| `self.anonym_config_text` | `update_anonym_photos_list` |

### 4.2 Zkratky (QShortcut / QAction.setShortcut)
| Sekvence | Zdroj |
|---|---|
| `QKeySequence.Close` | QAction.setShortcut |

### 4.3 QAction
_—_

### 4.4 Dock widgety
_—_

## 5. Výchozí cesty a dialogy
Detekované explicitní cesty:
- `/Users/safronus/Library/Mobile Docum...e~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Originály/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Ořezy/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Obrázky ke zpracování/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/PDF k vytištění/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Skripty/gui/settings/LokaceStavyPoznamky.json`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Vytištěné PDF/`

## 6. Vazby na další soubory
image_viewer, main_window, pdf_generator_window, web_photos_window


### 7. QA scénáře (smoke test)
1. Otevři okno → načti 3+ položky.
2. Změň layout (položky/strana, okraje) → náhled se mění.
3. Zapni/vypni popisky/číslování/vodoznak → ověř v náhledu.
4. Export PDF → soubor existuje, otevře se, počet stran a rozvržení sedí.
5. Chybové stavy (prázdný vstup) → korektní hláška, UI stabilní.


### 8. Zkratky – přehled a možné kolize
| Sekvence (zdroj) | Poznámka |
|---|---|
| `QKeySequence.Close` (QAction.setShortcut) | ⚠️ rezervováno macOS |

_Žádné interní kolize nenalezeny._

**Doporučení:** vyhnout se přemapování `Cmd+W`, `Cmd+Q`, `Cmd+H`; sjednotit zkratky v README; ponechat `Space` pro náhled/preview.

---

## 9. Integrita zdrojového souboru
- Počet řádků: **9456**  •  Velikost: **408225 B**  •  SHA-256: `1e474b2af2b451d593bbc1a9c63a029ce4012ac191efdb39cea0fe0df5a0f5bc`
- První 3 neprázdné řádky:
  - `# -*- coding: utf-8 -*-`
  - `from PySide6.QtWidgets import (`
  - `    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,`
- Poslední 3 neprázdné řádky:
  - `    window = PDFGeneratorWindow()`
  - `    window.show()`
  - `    sys.exit(app.exec())`