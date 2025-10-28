# Dokumentace hlavního okna (`main_window.py`)

**Cílový soubor:** `main_window.py`  
**SHA-256:** `8b085fe0e8187d6f30e20093032298243dac7c9800c3ba4c62f35dbfca83f634`  
**Řádků:** 11140  •  **Velikost:** 497244 B  
**Datum:** 2025-10-29

---

## Přehled
Tento dokument popisuje architekturu a chování hlavního okna aplikace (PySide6). Zaměřuje se na třídu `MainWindow`, navázané akce, zkratky, docky a integraci pomocných oken (např. počítadla čtyřlístků).

## Struktura souboru
- **Definované třídy:** ProcessorThread, ClickableMapLabel, MapGenerationThread, MultiZoomPreviewDialog, FLClickableLabel, FourLeafCounterWidget, FourLeafCounterDock, MainWindow, RegenerateProgressDialog, _MismatchOverlay, _MapClickFilter, _MapResizeFilter, _RefreshPosFilter, MapPreviewThread, _AutoFitFilter, _AutoFitFilter
- **Signály v rámci `MainWindow`:** _žádné pyqtSignal/Signal nezachyceny_

## Třída `MainWindow` – veřejné metody
Seznam metod detekovaných jednoduchou analýzou zdrojáku:
- `__init__()`
- `add_log()`
- `init_ui()`
- `showEvent()`
- `_inject_fourleaf_ui()`
- `open_fourleaf_counter_window()`
- `setup_file_tree_anonym_column()`
- `has_aoi_polygon()`
- `_ensure_anonym_column_and_update()`
- `has_anonymized_location_flag()`
- `_norm()`
- `_update_anonymization_column()`
- `read_meta_map()`
- `has_anon_flag()`
- `has_polygon()`
- `parse_area_m2()`
- `guess_path()`
- `process_item()`
- `add_anonymized_location_flag()`
- `remove_anonymized_location_flag()`
- `add_anonymized_location_flag_bulk()`
- `remove_anonymized_location_flag_bulk()`
- `open_web_photos_window()`
- `_on_viewer_current_file_changed()`
- `add_toolbar_gap()`
- `close_active_child_dialogs()`
- `show_tree_help()`
- `create_file_tree_widget()`
- `style_btn()`
- `_sort_tree_globally_by_name()`
- `_is_dir()`
- `_key_name()`
- `_sort_children()`
- `_on_sort_tree_globally_by_name()`
- `_on_sort_unsorted_alphabetically()`
- `_key_alpha()`
- `_find_unsorted_root_item_top_level()`
- `_norm_path()`
- `_on_sort_unsorted_by_location_numbers()`
- `_norm()`
- `_is_dir()`
- `_last5()`
- `_key()`
- `on_tree_current_changed()`
- `open_unsorted_browser_from_min()`
- `norm()`
- `id_or_big()`
- `_wire_common_shortcuts()`
- `_post_key()`
- `_unsorted_name_variants()`
- `_norm_text()`
- `_tokenize_filter()`
- `_find_unsorted_roots()`
- `_item_matches_tokens()`
- `open_polygon_editor_shortcut()`
- `select_all_in_unsorted_shortcut()`
- `_on_paste_shortcut()`
- `_apply_unsorted_filter()`
- `apply_on_subtree()`
- `unhide_all()`
- `walk()`
- `_extract_last5_id_from_name()`
- `_iter_children_recursive()`
- `analyze_unsorted_location_ids()`
- `_p5()`
- `_compress_ranges_safe()`
- `_format_id_list_compact()`
- `update_unsorted_id_indicator()`
- `set_label()`
- `rename_selected_item()`
- `cut_selected_items()`
- `_get_selected_png_path()`
- `on_edit_polygon()`
- `on_edit_polygon_for_path()`
- `_init_gps_preview_first_show()`
- `on_tree_selection_changed()`
- `collapse_except_unsorted_fixed()`
- `process_item()`
- `on_tree_section_resized()`
- `adjust_tree_columns()`
- `text_w()`
- `adjust_tree_columns_delayed()`
- `resizeEvent()`
- `refresh_file_tree()`
- `_item_path()`
- `save_tree_expansion_state()`
- `restore_tree_expansion_state()`
- `get_item_path()`
- `restore_expanded_items()`
- `count_folders()`
- `count_folders_recursive()`
- `expand_all_items()`
- `expand_recursive()`
- `collapse_all_items()`
- `collapse_recursive()`
- `load_directory_tree()`
- `_n()`
- `format_file_size()`
- `count_tree_items()`
- `recalculate_unsorted_areas()`
- `compute_and_store_aoi_area()`
- `_read_polygon_points()`
- `compute_and_store_aoi_area_bulk()`
- `show_context_menu()`
- `_open_heic_preview_dialog_for_path()`
- `_reselect_after_close()`
- `_reselect_in_file_tree()`
- `_find_rec()`
- `_on_heic_file_renamed()`
- `_find_item_by_path()`
- `_find_rec()`
- `_load_HeicPreviewDialog_class()`

## Akce (QAction) a jejich handlery
_Nenalezeny žádné QAction._

## QShortcut (globální zkratky okna)
| Sekvence | Handler |
|---|---|
| `QKeySequence.Close` | `accept` |
| `QKeySequence.Copy` | `copy_selected_item` |
| `QKeySequence.Paste` | `_on_paste_shortcut` |

## Dock widgety
_Nenalezeny žádné QDockWidget vytvoření s titulem._

## Integrovaný nástroj: Počítadlo čtyřlístků (🍀)
- **Dock třída:** `FourLeafCounterDock`  
- **Widget třída:** `FourLeafCounterWidget`  

### Výchozí složky/Dialogy
V souboru byly nalezeny následující explicitní cesty (např. pro file dialogy):
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Čtyřlístky na sušičce/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné/ZLíN_JSVAHY-UTB-U5-001+VlevoPredHlavnimVchodem+GPS49.23091S+17.65691V+Z18+00001.png`
- `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Obrázky/`

## Signál → Slot (detekováno)
| Objekt.signál | Slot (`MainWindow.*`) |
|---|---|
| `btn_save.triggered` | `on_save_clicked` |
| `btn_close.triggered` | `accept` |
| `btn_open.triggered` | `open_image` |
| `btn_save.triggered` | `save_image` |
| `btn_undo.triggered` | `undo_last` |
| `btn_reset.triggered` | `reset_numbers` |
| `_sc_close_all.triggered` | `close_active_child_dialogs` |
| `btn_fourleaf.triggered` | `open_fourleaf_counter_window` |
| `btn_refresh_tree.triggered` | `refresh_file_tree` |
| `btn_open_folder.triggered` | `open_maps_folder` |
| `btn_expand_all.triggered` | `expand_all_items` |
| `btn_collapse_except_unsorted.triggered` | `collapse_except_unsorted_fixed` |
| `btn_collapse_all.triggered` | `collapse_all_items` |
| `btn_tree_help.triggered` | `show_tree_help` |
| `btn_edit_polygon.triggered` | `on_edit_polygon` |
| `btn_browse_from_00001.triggered` | `open_unsorted_browser_from_min` |
| `btn_browse_unsorted.triggered` | `open_unsorted_browser` |
| `btn_regenerate_selected.triggered` | `regenerate_selected_items` |
| `btn_sort_unsorted_by_loc.triggered` | `_on_sort_unsorted_by_location_numbers` |
| `btn_sort_unsorted_alpha.triggered` | `_on_sort_unsorted_alphabetically` |
| `btn_sort_tree_alpha.triggered` | `_on_sort_tree_globally_by_name` |
| `btn_recalculate_areas.triggered` | `recalculate_unsorted_areas` |
| `_shortcut_delete.triggered` | `delete_selected_items` |
| `_shortcut_space.triggered` | `preview_selected_file` |
| `_shortcut_enter.triggered` | `rename_selected_item` |
| `_shortcut_enter2.triggered` | `rename_selected_item` |
| `_shortcut_cut.triggered` | `cut_selected_items` |
| `_shortcut_new_root_folder.triggered` | `create_root_folder` |
| `_shortcut_open_polygon.triggered` | `on_edit_polygon` |
| `_shortcut_edit_polygon_cmd_p.triggered` | `open_polygon_editor_shortcut` |
| `_shortcut_select_all_unsorted.triggered` | `select_all_in_unsorted_shortcut` |
| `btn_cancel.triggered` | `reject` |
| `_sc_close.triggered` | `reject` |
| `input_manual_coords.triggered` | `test_coordinate_parsing` |
| `btn_coords_from_heic.triggered` | `on_pick_heic_and_fill_manual_coords` |
| `btn_gps_refresh.triggered` | `_on_gps_refresh_click` |
| `btn_browse_photo.triggered` | `browse_photo` |
| `_shortcut_undo_filter.triggered` | `clear_filter_input` |
| `_shortcut_undo_filter_win.triggered` | `clear_filter_input` |
| `_shortcut_search.triggered` | `focus_filter_input` |
| `_shortcut_search_mac.triggered` | `focus_filter_input` |
| `btn_browse_output.triggered` | `browse_output_dir` |
| `btn_set_defaults_secondary.triggered` | `set_default_values` |
| `btn_start_secondary.triggered` | `start_processing` |
| `btn_stop_secondary.triggered` | `stop_processing` |
| `btn_pdf_generator_monitor.triggered` | `open_pdf_generator` |
| `btn_web_photos.triggered` | `open_web_photos_window` |
| `btn_toggle_display.triggered` | `toggle_display_mode` |

## Rozšíření / doporučení
- **Oddělit logiku a UI:** držet nenáročné sloty v `MainWindow`, delší běhy (I/O) přes `QThread/QRunnable`.
- **Testovatelnost:** funkce, které nepracují s UI, přesunout do samostatných modulů pro snadné unit testy.
- **Klávesové zkratky:** u akcí vždy uvádět i `setStatusTip` pro přístupnost.
- **Docky:** při zavírání používat `deleteLater()` a nulovat reference, aby šlo bezpečně znovu otevřít.

---

### Integrita zdrojového souboru
- Počet řádků: **11140**
- Velikost: **497244 B**
- SHA-256: `8b085fe0e8187d6f30e20093032298243dac7c9800c3ba4c62f35dbfca83f634`
- Náhled:
  - První 3 neprázdné řádky:
    - `#!/usr/bin/env python3`
    - `# -*- coding: utf-8 -*-`
    - `"""`
  - Poslední 3 neprázdné řádky:
    - `            print(f"Chyba při zavírání aplikace: {e}")`
    - `        # Nechat QMainWindow dokončit zavření`
    - `        super().closeEvent(event)  # místo event.accept() je korektnější volat parent implementaci [4]`