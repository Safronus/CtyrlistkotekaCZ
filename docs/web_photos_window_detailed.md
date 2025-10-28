# Dokumentace (`web_photos_window.py`) – podrobná verze

**Soubor:** `web_photos_window.py`  
**SHA-256:** `3cb436091fc14bdecd65f26e4833a68f7eb759a89d5c6bbd8d2a5caae0abce3a`  •  **Řádků:** 8691  •  **Velikost:** 368970 B  
**Generováno:** 2025-10-29

---

## 1. Role a architektura
- Modul obsahuje okno/dialog postavené na PySide6 a obsluhu GUI prvků (toolbar, zkratky, signály/sloty).

## 2. Importy a závislosti
### 2.1 Projektové moduly (lokální)
- `from __future__ import annotations`
- `from status_widget import StatusWidget`
- `from log_widget import LogWidget`
- `from .status_widget import StatusWidget`
- `import piexif`
- `import html`
- `from shiboken6 import isValid`
- `from shiboken6 import isValid`
- `import weakref`
- `import unicodedata`
- `import pillow_heif`
- `import piexif`
- `import exifread`

### 2.2 Knihovny třetích stran
- `PySide6.QtCore` (import ()
- `PySide6.QtGui` (import ()
- `PySide6.QtWidgets` (import ()
- `PySide6.QtWidgets` (import ()
- `PySide6.QtGui` (import ()
- `PySide6.QtCore` (import ()
- `PIL` (import Image, ImageOps)
- `PIL` (import Image)
- `PySide6.QtWidgets` (import QAbstractItemView)
- `PySide6.QtCore` (import Qt, QModelIndex)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QDialog, QVBoxLayout, QDialogButtonBox, QTextBrowser)
- `PySide6.QtCore` (import QMargins)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QApplication)
- `PySide6.QtConcurrent` (import run as qt_run)
- `PySide6.QtCore` (import QFutureWatcher, QObject)
- `PySide6.QtCore` (import Qt, QModelIndex)
- `PySide6.QtWidgets` (import QAbstractItemView)
- `PySide6.QtWidgets` (import QToolButton)
- `PySide6.QtCore` (import Qt, QEvent, QObject)
- `PySide6.QtGui` (import QStandardItem)
- `PySide6.QtWidgets` (import QStyle)
- `PySide6.QtCore` (import Qt, QTimer)
- `PySide6.QtWidgets` (import QLabel, QWidget)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QFont)
- `PySide6.QtGui` (import QColor)
- `PySide6.QtWidgets` (import QLabel)
- `PIL` (import Image as _Image)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QKeySequence, QShortcut, QColor)
- `PySide6.QtWidgets` (import ()
- `PIL` (import Image as _Image)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QColor, QKeySequence, QAction, QShortcut, QGuiApplication)
- `PySide6.QtWidgets` (import QProgressDialog, QApplication)
- `PIL` (import Image as _Image)
- `PIL` (import Image as _ImageDim)
- `PySide6.QtWidgets` (import QApplication)
- `PIL` (import Image as _Image)
- `PIL` (import Image)
- `PySide6.QtCore` (import Qt, QTimer)
- `PySide6.QtGui` (import QKeySequence)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtCore` (import Qt, QTimer)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtWidgets` (import QLabel as _QLabel)
- `PySide6.QtCore` (import QModelIndex)
- `PySide6.QtWidgets` (import QTableView, QAbstractItemView)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QApplication)

### 2.3 Standardní knihovna (výběr)
dataclasses, datetime, hashlib, json, math, os, pathlib, re, shutil, sys, typing

## 3. Třídy v souboru
### 3.1 `NamingFormatDialog`  
Báze: QDialog
> Modální okno s popisem formátu pojmenování.     - Zavírá se tlačítkem „Zavřít“ nebo zkratkou QKeySequence.Close (Cmd+W / Ctrl+W).

### 3.2 `SelectionIndicator`  
Báze: QFrame
> Jednoduchý panel zobrazující počty vybraných položek ve stromu:       - počet vybraných souborů       - počet vybraných složek      Ovládá se metodou set_counts(files:int, dirs:int).

### 3.3 `ScanWorker`  
Báze: QObject
> Rekurzivní sken složek + vyhodnocení formátu názvů + seznam validních souborů.

### 3.4 `RecursiveDirectoryWatcher`  
Báze: QObject
> Nadstavba nad QFileSystemWatcher:       - rekurzivně hlídá všechny podsložky,       - emituje `changed` při libovolné změně,       - `refresh()` po skenu doplní nově vzniklé podsložky.

### 3.5 `LineNumberArea`  
Báze: QWidget

### 3.6 `JsonCodeEditor`  
Báze: QPlainTextEdit
> QPlainTextEdit s levým žlábkem pro čísla řádků a jemným zvýrazněním aktuálního řádku.

### 3.7 `_LineNumberArea`  
Báze: QWidget

### 3.8 `WebPhotosWindow`  
Báze: QDialog
> Záložka 1: „Kontrola stavu fotek na web“       • Zobrazuje statistiky pro Ořezy a Originály.       • Kontrola běží na pozadí (watcher + debounce).       • Ukázka formátu v modálním okně.      Záložka 2: „Nastavení JSONů“       • Tři editory (lokace / stavy / poznámky), ukládají se do settings/LokaceStavyPoznamky.json.       • Vpravo strom platných souborů (složkový přehled) s realtime updatem.

### 3.9 `_Emitter`  
Báze: QObject

### 3.10 `_CropPreviewDialog`  
Báze: QDialog

### 3.11 `_OverlayEF`  
Báze: QObject

## 4. Signály, sloty, zkratky, akce, docky
### 4.1 Signál → Slot (detekováno)
| Emitter | Slot |
|---|---|
| `self.btn_crop` | `crop_image` |
| `self.shortcut_crop` | `crop_image` |
| `self.btn_show_format` | `_show_format_modal` |
| `self.btn_load` | `_load_settings_into_editors` |
| `self.btn_save` | `_save_editors_to_settings` |
| `self.btn_json_lookup` | `_on_json_lookup_clicked` |
| `self.json_tree_filter` | `_on_json_tree_filter_text_changed` |

### 4.2 QShortcut
| Sekvence | Slot |
|---|---|
| `QKeySequence.Close` | `` |
| `QKeySequence.Close` | `` |
| `QKeySequence.Copy` | `` |
| `QKeySequence.Paste` | `` |

### 4.3 QAction
_—_

### 4.4 Dock widgety
_—_

## 5. Výchozí cesty a dialogy
Detekované explicitní cesty:
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Miniatury/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Originály`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Originály/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Ořezy`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Ořezy/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné`

## 6. Vazby na další soubory
pdf_generator_window, web_photos_window

---

## 7. Integrita zdrojového souboru
- Počet řádků: **8691**  •  Velikost: **368970 B**  •  SHA-256: `3cb436091fc14bdecd65f26e4833a68f7eb759a89d5c6bbd8d2a5caae0abce3a`
- První 3 neprázdné řádky:
  - `# -*- coding: utf-8 -*-`
  - `"""`
  - `web_photos_window.py`
- Poslední 3 neprázdné řádky:
  - `    dlg = WebPhotosWindow()`
  - `    dlg.show()`
  - `    sys.exit(app.exec())`