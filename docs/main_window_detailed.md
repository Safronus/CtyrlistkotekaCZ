# Dokumentace hlavního okna (`main_window.py`) – podrobná verze

**Soubor:** `main_window.py`  
**SHA-256:** `74692180b9103bcd041577d2b41b24559a2da364550bbd989ca83bb373277ceb`  •  **Řádků:** 10658  •  **Velikost:** 477164 B  
**Generováno:** 2025-10-29

---

## 1. Role a architektura
- **`MainWindow`** je kořenové okno aplikace (PySide6), spravuje strom položek, náhledy, nástroje a pomocná okna/docky.
- Integruje editor polygonů nad fotkami (.HEIC) přes samostatný dialog (**`PolygonEditorDialog`** v `image_viewer.py`).
- Integruje nástroj **Počítadlo čtyřlístků (🍀)** – třídy `FourLeafCounterDock` a `FourLeafCounterWidget`.

## 2. Importy a závislosti
### 2.1 Projektové moduly (lokální)
- `import requests`
- `import tempfile`
- `from gui.status_widget import StatusWidget`
- `from gui.log_widget import LogWidget`
- `from gui.image_viewer import ImageViewerDialog, open_polygon_editor_for_file`
- `from gui.pdf_generator_window import PDFGeneratorWindow`
- `from core.map_processor import MapProcessor`
- `from gui.web_photos_window import WebPhotosWindow`
- `from core.map_processor import MapProcessor`
- `import unicodedata`
- `import unicodedata`
- `import unicodedata`
- `from gui.image_viewer import ImageViewerDialog`
- `import unicodedata`
- `from image_viewer import HeicPreviewDialog`
- `from .image_viewer import HeicPreviewDialog`
- `from gui.image_viewer import HeicPreviewDialog`
- `import importlib.util`
- `from image_viewer import HeicPreviewDialog`
- `from .image_viewer import HeicPreviewDialog`
- `import importlib.util`
- `import unicodedata`
- `from gui.image_viewer import ImageViewerDialog`
- `import unicodedata`
- `import platform`
- `import platform`
- `import unicodedata`
- `from gui.image_viewer import ImageViewerDialog`
- `import stat`
- `import pillow_heif`
- `import piexif`
- `import io`
- `from gui.image_viewer import ImageViewerDialog`
- `from gui.image_viewer import ImageViewerDialog`
- `import platform`

### 2.2 Knihovny třetích stran
- `PIL` (import Image, ImageDraw)
- `PySide6.QtWidgets` (import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, )
- `PySide6.QtCore` (import Qt, QThread, Signal, Slot, QDir, QTimer, QObject, QEvent)
- `PySide6.QtGui` (import QFont, QIcon, QAction, QPixmap)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtGui` (import QPixmap, QFont, QGuiApplication, QShortcut, QKeySequence)
- `PySide6.QtCore` (import Qt, QThread, Signal, Slot, QTimer)
- `PIL` (import Image, ImageDraw)
- `PIL.ImageQt` (import ImageQt)
- `PIL` (import Image as PILImage)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtCore` (import QSettings)
- `PySide6.QtWidgets` (import QLabel, QComboBox)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtCore` (import QByteArray)
- `PySide6.QtCore` (import QTimer)
- `PIL` (import Image)
- `PySide6.QtGui` (import QIcon)
- `PIL` (import Image)
- `PySide6.QtWidgets` (import QApplication, QStyle, QTreeWidgetItem)
- `PySide6.QtGui` (import QIcon)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QMessageBox)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QMessageBox)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QApplication, QDialog)
- `PySide6.QtWidgets` (import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout)
- `PySide6.QtGui` (import QFont, QShortcut, QKeySequence)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtWidgets` (import QTreeWidgetItem)
- `PySide6.QtWidgets` (import QMessageBox, QTreeWidgetItem)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QMessageBox, QTreeWidgetItem)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import Qt, QEvent, QCoreApplication)
- `PySide6.QtGui` (import QKeySequence, QShortcut, QKeyEvent)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QApplication)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtWidgets` (import QTreeWidgetItem)
- `PySide6.QtCore` (import QTimer, Qt)
- `PIL` (import Image)
- `PySide6.QtWidgets` (import QStyle, QApplication)
- `PySide6.QtWidgets` (import QMessageBox, QProgressDialog)
- `PySide6.QtCore` (import Qt)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtGui` (import QKeySequence, QShortcut)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QShortcut, QKeySequence)
- `PySide6.QtGui` (import QTextCursor)
- `PySide6.QtWidgets` (import QApplication)
- `PySide6.QtCore` (import QEventLoop)
- `PySide6.QtWidgets` (import QApplication)
- `PySide6.QtCore` (import QEventLoop)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PIL` (import Image)
- `PySide6.QtCore` (import Qt, QEvent, QCoreApplication)
- `PySide6.QtGui` (import QKeySequence, QShortcut, QKeyEvent)
- `PySide6.QtWidgets` (import QInputDialog, QMessageBox)
- `PySide6.QtWidgets` (import QInputDialog, QLineEdit)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtCore` (import Qt, QEvent, QCoreApplication)
- `PySide6.QtGui` (import QKeySequence, QShortcut, QKeyEvent)
- `PIL` (import Image)
- `PIL` (import Image)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtWidgets` (import QWidget)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtGui` (import QPainter, QColor, QPen)
- `PySide6.QtWidgets` (import QLabel, QHBoxLayout, QGridLayout, QSizePolicy)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QFileDialog, QMessageBox)
- `PySide6.QtCore` (import QDir)
- `PySide6.QtWidgets` (import QMessageBox)
- `PIL` (import Image)
- `PySide6.QtWidgets` (import ()
- `PySide6.QtCore` (import Qt, QTimer, QObject, QEvent)
- `PySide6.QtCore` (import QTimer)
- `PySide6.QtWidgets` (import QPushButton)
- `PySide6.QtCore` (import Qt, QObject, QEvent)
- `PySide6.QtCore` (import QThread, Signal)
- `PIL` (import Image)
- `PIL` (import Image as PILImage)
- `PIL.ImageQt` (import ImageQt)
- `PySide6.QtCore` (import QBuffer)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PySide6.QtWidgets` (import ()
- `PIL` (import Image)
- `PySide6.QtGui` (import QBrush, QColor)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtCore` (import Qt)
- `PySide6.QtWidgets` (import QMessageBox)
- `PySide6.QtWidgets` (import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QToolBar, QPushButton)
- `PySide6.QtCore` (import QTimer, Qt)
- `PySide6.QtGui` (import QGuiApplication)
- `PySide6.QtGui` (import QGuiApplication)
- `PySide6.QtWidgets` (import QWidget)
- `PySide6.QtGui` (import QPixmap)

### 2.3 Standardní knihovna (výběr)
datetime, json, math, os, pathlib, re, shutil, subprocess, sys, time

## 3. Třídy v souboru
### 3.1 `ProcessorThread`  
Báze: QThread
> Thread pro zpracování na pozadí
**Atributy inicializované v `__init__`:**
- `self.parameters` = `parameters`
- `self.processor` = `None`
**Metody (výběr):**
- `__init__(self, parameters)`
- `run(self)` — Spuštění zpracování
- `stop(self)` — Zastavení zpracování

### 3.2 `ClickableMapLabel`  
Báze: QFrame
> Vlastní widget pro zobrazení klikatelného náhledu mapy s pevnou velikostí.

### 3.3 `MapGenerationThread`  
Báze: QThread
> Vlákno generuje mapu s progress reportingem.

### 3.4 `MultiZoomPreviewDialog`  
Báze: QDialog
> Rozšířená verze dialogu s dvěma řadami náhledů - původní DPI a 420 DPI.

### 3.5 `MainWindow`  
Báze: QMainWindow
> Hlavní okno aplikace
**Atributy inicializované v `__init__`:**
- `self.settings` = `QSettings("Ctyrlístky", "OSMMapGenerator")`
- `self.map_update_timer` = `None`
- `self.map_thread` = `None`
- `self.processor_thread` = `None`
- `self.last_output_path` = `None`
- `self.saved_tree_expansion_state` = `set()`
- `self.clipboard_data` = `None`
- `self.default_maps_path` = `Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/")`
- `self.config_file` = `Path.home() / ".config" / "osm_map_generator" / "config.json"`
**Metody (výběr):**
- `__init__(self)`
- `add_log(self, *args, **kwargs)`
- `init_ui(self)` — Inicializace UI + obnova uložené geometrie okna a šířek sloupců stromu.
- `process_item(item: QTreeWidgetItem)`
- `open_web_photos_window(self)` — Otevře 'Web fotky' jako NEmodální okno (hlavní okno zůstává použitelné).
- `_on_viewer_current_file_changed(self, path_str: str)` — Převezme cestu z náhledu a označí odpovídající položku ve stromu.
- `close_active_child_dialogs(self)` — NOVÁ FUNKCE: Zavře všechna otevřená QDialog podokna (Cmd+W / Close).
- `show_tree_help(self)` — Zobrazí modální nápovědu s klávesovými zkratkami pro strom souborů/složek.
- `create_file_tree_widget(self)` — UPRAVENÁ FUNKCE: Stromová struktura + sjednocený styl tlačítek bez nepodporovaných QSS vlastností + tlačítko 'Upravit oblast'
- `style_btn(btn: QPushButton, base: str, hover: str, pressed: str, max_w: int | None = None)`
- `_sort_children(parent: QTreeWidgetItem)`
- `_key_alpha(item: QTreeWidgetItem)`
- `_find_unsorted_root_item_top_level(self)` — Vrátí QTreeWidgetItem top-level uzlu 'Neroztříděné'.
- `_key(item: QTreeWidgetItem)`
- `on_tree_current_changed(self, current, previous)` — Reakce na změnu aktuální položky při navigaci klávesnicí.
- `open_unsorted_browser_from_min(self)` — Otevře prohlížeč obrázků ve složce 'Neroztříděné' seřazených podle ID lokace
- `id_or_big(p: Path)`
- `_wire_common_shortcuts(dlg)`
- `_post_key(key)`
- `_unsorted_name_variants(self)`
- `_tokenize_filter(self, text: str)`
- `_find_unsorted_roots(self)` — Najde root položky stromu, které odpovídají 'Neroztříděné' (včetně variant).
- `_item_matches_tokens(self, item, tokens)`
- `open_polygon_editor_shortcut(self)` — Slot pro klávesovou zkratku CMD+P.
- `select_all_in_unsorted_shortcut(self)` — Slot pro klávesovou zkratku CMD+A.
- `_on_paste_shortcut(self)`
- `_apply_unsorted_filter(self)` — Aplikuje/odstraní filtr pouze v podstromu 'Neroztříděné'.
- `apply_on_subtree(root_item)`
- `unhide_all(it)`
- `walk(it)`
- `_iter_children_recursive(self, item)` — Generátor: projde rekurzivně všechny potomky dané položky stromu.
- `update_unsorted_id_indicator(self)` — Získá stav čísel v 'Neroztříděné' a aktualizuje label nad stromem i status widget.
- `set_label(text: str, color: str)`
- `rename_selected_item(self)` — Přejmenuje vybraný soubor (1 položka) – vyvolá jednotný dialog se sjednocenou velikostí.
- `cut_selected_items(self)` — Vyjme (Cut) vybrané soubory/složky do interní schránky; následné Vložit je přesune.
- `_get_selected_png_path(self)` — Pomocná funkce: vrátí cestu k vybranému PNG souboru ze stromu (preferuje currentItem).
- `on_edit_polygon(self)` — Spustí editor polygonu nad aktuálně vybraným PNG ve stromu.
- `on_edit_polygon_for_path(self, file_path: str)` — Spustí editor polygonu přímo pro danou cestu (používá kontextové menu).
- `_init_gps_preview_first_show(self)` — První otevření GPS záložky: zkus načíst cache náhledu, nestahuj automaticky.
- `on_tree_selection_changed(self, selected, deselected)` — UPRAVENÁ FUNKCE: Automatické logování + zvýraznění polygonů
- `collapse_except_unsorted_fixed(self)` — FLEXIBILNÍ HLEDÁNÍ: Různé varianty názvu složky
- `process_item(item=None)`
- `on_tree_section_resized(self, logical_index, old_size, new_size)` — NOVÁ FUNKCE: Reakce na změnu velikosti sloupců
- `adjust_tree_columns(self)` — Fixní šířky pro Typ/Velikost/Změněno dle textu, Název jediný Stretch (vyplní zbytek).
- `adjust_tree_columns_delayed(self)` — Zpožděný přepočet – zmenší sloupce proti skutečnému obsahu a nechá Název vyplnit zbytek.
- `resizeEvent(self, event)` — Reakce na změnu velikosti okna – přepočet sloupců stromu a update mapového náhledu (debounce).
- `refresh_file_tree(self)` — UPRAVENÁ FUNKCE: stabilní pořadí během session + obnova rozbalení i po restartu (uložený stav), bez hromadného expand/collapse.
- `_item_path(it)`
- `save_tree_expansion_state(self)` — Uloží absolutní cesty rozbalených položek (bez položkových debug logů).
- `restore_tree_expansion_state(self, expanded_items)` — Obnovení stavu rozbalení stromové struktury podle absolutních cest (bez položkových logů).
- `get_item_path(item)`
- `restore_expanded_items(item)`
- `count_folders(self)` — NOVÁ FUNKCE: Počítání složek ve stromu
- `count_folders_recursive(item)`
- `expand_all_items(self)` — UPRAVENÁ FUNKCE: Rozbalení všech položek s počítadlem
- `expand_recursive(item)`
- `collapse_all_items(self)` — UPRAVENÁ FUNKCE: Sbalení všech položek s počítadlem
- `collapse_recursive(item)`
- `load_directory_tree(self, directory_path, parent_item, current_depth=0, max_depth=10)` — OPTIMALIZOVANÁ FUNKCE: Rychlé načítání adresářové struktury se skrytím systémových/ skrytých souborů
- `format_file_size(self, size_bytes)` — OPTIMALIZOVANÁ FUNKCE: Rychlejší formátování velikosti souboru
- `count_tree_items(self)` — OPTIMALIZOVANÁ FUNKCE: Rychlejší počítání položek ve stromu
- `_read_polygon_points(path: Path)`
- `show_context_menu(self, position)` — Zobrazení kontextového menu včetně hromadných akcí a editoru polygonu pro PNG + HEIC náhled.
- `_open_heic_preview_dialog_for_path(self, path: str)` — Toggle náhledu pro .HEIC/.HEIF:
- `_reselect_after_close(_res, d=dlg, orig=str(p))`
- `_reselect_in_file_tree(self, target_path: str)` — Najde a vybere položku ve stromu souborů dle absolutní cesty (Qt.UserRole).
- `_find_rec(itm)`
- `_on_heic_file_renamed(self, old_path: str, new_path: str)` — Po přejmenování .HEIC aktualizuje odpovídající položku ve stromu:
- `_find_item_by_path(root_widget)`
- `_find_rec(itm)`
- `_load_HeicPreviewDialog_class(self)` — Robustní načtení HeicPreviewDialog z image_viewer.py.

### 3.6 `RegenerateProgressDialog`  
Báze: QDialog
> Lehký modální dialog s popisem, velkým progress barem a živým logem.

### 3.7 `_MismatchOverlay`  
Báze: QWidget

### 3.8 `_MapClickFilter`  
Báze: QObject

### 3.9 `_MapResizeFilter`  
Báze: QObject

### 3.10 `_RefreshPosFilter`  
Báze: QObject

### 3.11 `MapPreviewThread`  
Báze: QThread

### 3.12 `_AutoFitFilter`  
Báze: QObject

### 3.13 `_AutoFitFilter`  
Báze: QObject


## 4. `MainWindow` – signály, sloty, zkratky, docky
### 4.1 Signál → Slot napojení (detekce)
| Emitter | Slot |
|---|---|
| `self.spin_marker_size` | `update_all_markers` |
| `self.combo_marker_style` | `update_all_markers` |
| `self.btn_save` | `on_save_clicked` |
| `self.btn_close` | `accept` |
| `self._sc_close_all` | `close_active_child_dialogs` |
| `self._act_fourleaf` | `_open_fourleaf_dock` |
| `self.btn_refresh_tree` | `refresh_file_tree` |
| `self.btn_open_folder` | `open_maps_folder` |
| `self.btn_expand_all` | `expand_all_items` |
| `self.btn_collapse_except_unsorted` | `collapse_except_unsorted_fixed` |
| `self.btn_collapse_all` | `collapse_all_items` |
| `self.btn_tree_help` | `show_tree_help` |
| `self.btn_edit_polygon` | `on_edit_polygon` |
| `self.btn_browse_from_00001` | `open_unsorted_browser_from_min` |
| `self.btn_browse_unsorted` | `open_unsorted_browser` |
| `self.btn_regenerate_selected` | `regenerate_selected_items` |
| `self.btn_sort_unsorted_by_loc` | `_on_sort_unsorted_by_location_numbers` |
| `self.btn_sort_unsorted_alpha` | `_on_sort_unsorted_alphabetically` |
| `self.btn_sort_tree_alpha` | `_on_sort_tree_globally_by_name` |
| `self.btn_recalculate_areas` | `recalculate_unsorted_areas` |
| `self._shortcut_delete` | `delete_selected_items` |
| `self._shortcut_space` | `preview_selected_file` |
| `self._shortcut_enter` | `rename_selected_item` |
| `self._shortcut_enter2` | `rename_selected_item` |
| `self._shortcut_cut` | `cut_selected_items` |
| `self._shortcut_new_root_folder` | `create_root_folder` |
| `self._shortcut_open_polygon` | `on_edit_polygon` |
| `self._shortcut_edit_polygon_cmd_p` | `open_polygon_editor_shortcut` |
| `self._shortcut_select_all_unsorted` | `select_all_in_unsorted_shortcut` |
| `self.btn_cancel` | `reject` |
| `self._sc_close` | `reject` |
| `self.input_manual_coords` | `test_coordinate_parsing` |
| `self.btn_coords_from_heic` | `on_pick_heic_and_fill_manual_coords` |
| `self.spin_preview_zoom` | `_on_gps_param_changed` |
| `self.btn_gps_refresh` | `_on_gps_refresh_click` |
| `self.btn_browse_photo` | `browse_photo` |
| `self.spin_marker_size` | `on_marker_size_changed` |
| `self.combo_marker_style` | `on_marker_style_changed` |
| `self.check_preview_row1` | `on_preview_row_toggled` |
| `self.check_preview_row2` | `on_preview_row_toggled` |
| `self._shortcut_undo_filter` | `clear_filter_input` |
| `self._shortcut_undo_filter_win` | `clear_filter_input` |
| `self._shortcut_search` | `focus_filter_input` |
| `self._shortcut_search_mac` | `focus_filter_input` |
| `self.btn_browse_output` | `browse_output_dir` |
| `self.check_auto_id` | `on_auto_id_toggled` |
| `self.btn_set_defaults_secondary` | `set_default_values` |
| `self.btn_start_secondary` | `start_processing` |
| `self.btn_stop_secondary` | `stop_processing` |
| `self.btn_pdf_generator_monitor` | `open_pdf_generator` |
| `self.btn_web_photos` | `open_web_photos_window` |
| `self.btn_toggle_display` | `toggle_display_mode` |

### 4.2 QShortcut (globální zkratky)
| Sekvence | Slot |
|---|---|
| `QKeySequence.Close` | `accept` |
| `QKeySequence.Copy` | `copy_selected_item` |
| `QKeySequence.Paste` | `_on_paste_shortcut` |

### 4.3 QActions
| Jméno | Text | Zkratka | Slot |
|---|---|---|---|
| `_act_fourleaf` |  | `` | `_open_fourleaf_dock` |

### 4.4 Dock widgety
_Nenalezeny explicitní `QDockWidget`._

## 5. Integrované nástroje a vazby na další soubory
- **`image_viewer.py`** – `PolygonEditorDialog`, `PolygonCanvas`; náhled HEIC (mezerník), editace polygonu, režim štětce.
- **`PočítadloČtyřlístků.py`** – logika počítadla; GUI obal `FourLeafCounterWidget` + dock pro integraci do hlavního okna.
- **`main.py`** – bootstrap, verze, changelog; vytváří a zobrazuje `MainWindow`.
- **`README.md`** – uživatelský popis, změny verzí.
- **Konfigurace** – `settings.json`/`settings_backup.json` (ignor/backup) – udržují poslední cesty, apod.

## 6. Výchozí cesty a dialogy
Detekované explicitní cesty (pravděpodobně pro `QFileDialog`):
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/ZLíN_JSVAHY-UTB-U5-001+VlevoPredHlavnimVchodem+GPS49.23091S+17.65691V+Z18+00001.png`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Obrázky/`

## 7. Scénáře a sekvence (z pohledu uživatele)
1. Uživatel ve stromu vybere HEIC → stiskne **mezerník** → otevře se náhled.
2. Volba **Upravit polygon** → otevře se `PolygonEditorDialog` z `image_viewer.py`.
3. Režimy v dialogu: Přidat/Mazat/Posouvat/Štětec; u štětce spin pro velikost; kurzor v barvě polygonu.
4. Tlačítko 🍀 v toolbaru otevře **Počítadlo čtyřlístků** v docku; zavření `Cmd+W`.

## 8. Rozšiřitelnost a hooky
- **Akce**: přidávej přes factory, která vrací `QAction` a rovnou napojí `.triggered.connect(self.slot)`; udržuj přehled ve skupinách toolbaru.
- **Dlouhé operace**: `QThread`/`QRunnable` + signály; nikdy neblokovat UI.
- **Docky**: drž jedinou instanci na typ; při zavření `deleteLater()` a `self._dock_ref = None` → znovuotevření bez chyb.
- **File dialogy (macOS)**: používat nativní; pokud dialog po otevření nereaguje, zavolat `raise_()` a `activateWindow()` před zobrazením.

---

## 9. Integrita souboru
- Počet řádků: **10658**  •  Velikost: **477164 B**  •  SHA-256: `74692180b9103bcd041577d2b41b24559a2da364550bbd989ca83bb373277ceb`
- První 3 neprázdné řádky:
  - `#!/usr/bin/env python3`
  - `# -*- coding: utf-8 -*-`
  - `"""`
- Poslední 3 neprázdné řádky:
  - `            print(f"Chyba při zavírání aplikace: {e}")`
  - `        # Nechat QMainWindow dokončit zavření`
  - `        super().closeEvent(event)  # místo event.accept() je korektnější volat parent implementaci [4]`