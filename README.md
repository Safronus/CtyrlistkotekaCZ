# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.0  
**Datum vydání:** 2025-10-28

> **Ochrana soukromí:** Tento dokument záměrně **neobsahuje žádné osobní údaje, GPS souřadnice ani jména**. Obsah souborů `settings/*.json` není zde uváděn; dokumentace vychází pouze ze struktury a symbolů ve zdrojovém kódu.

---

## Funkce
- Moderní GUI v **PySide6** s preferencí dark theme (HiDPI/Retina).
- Import a správa položek sbírky, včetně práce s obrázky (Pillow).
- Základní zpracování obrazu (OpenCV) a volitelná OCR integrace (`pytesseract`).
- Generování dokumentů do **PDF** (ReportLab).
- Konfigurace uložená v `settings/` (JSON), snadno přenositelná.

---

## Požadavky
- macOS (Apple Silicon i Intel), doporučeno aktuální
- Python 3.10+ (doporučeno 3.12)
- Virtuální prostředí (venv)

### Systémové balíčky (pokud je potřebujete)
- **Tesseract OCR** (pro `pytesseract`):  
  ```bash
  brew install tesseract
  ```
- (Volitelné) **libheif** – pouze pokud by instalace/použití `pillow-heif` selhávalo na chybějící knihovně:  
  ```bash
  brew install libheif
  ```

---

## Instalace (macOS)
Doporučený postup s virtuálním prostředím:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> Pokud se instalace PySide6 nedaří, ujistěte se, že používáte systémové `python3` (Xcode Command Line Tools) nebo Homebrew Python.

---

## Spuštění
Ve virtuálním prostředí spusťte hlavní skript:
```bash
python {entry_point}
```

---

## Přesná struktura projektu
(Vypsány **všechny** soubory z dodaného archivu, kromě interní složky `__MACOSX/`.)

```text
BEZ_FOTKY.png
DAROVANY.png
DejaVuSans-Bold.ttf
DejaVuSans.ttf
LiberationSerif-Bold.ttf
LiberationSerif-Regular.ttf
NICKNAME.png
VODOZNAK_BezJmena.png
ZTRACENY.png
__pycache__/pdf_generator.cpython-313.pyc
core/.DS_Store
core/__pycache__/map_processor.cpython-313.pyc
core/__pycache__/map_processor.cpython-313.pyc
core/map_processor.py
core/map_processor.py
gui/.DS_Store
gui/__pycache__/image_viewer.cpython-313.pyc
gui/__pycache__/image_viewer.cpython-313.pyc
gui/__pycache__/log_widget.cpython-313.pyc
gui/__pycache__/log_widget.cpython-313.pyc
gui/__pycache__/main_window.cpython-313.pyc
gui/__pycache__/main_window.cpython-313.pyc
gui/__pycache__/pdf_generator_window.cpython-313.pyc
gui/__pycache__/pdf_generator_window.cpython-313.pyc
gui/__pycache__/status_widget.cpython-313.pyc
gui/__pycache__/status_widget.cpython-313.pyc
gui/__pycache__/web_photos_window.cpython-313.pyc
gui/__pycache__/web_photos_window.cpython-313.pyc
gui/image_viewer.py
gui/image_viewer.py
gui/log_widget.py
gui/log_widget.py
gui/main_window.py
gui/main_window.py
gui/pdf_generator_window.py
gui/pdf_generator_window.py
gui/settings/LokaceStavyPoznamky.json
gui/settings/LokaceStavyPoznamky.json
gui/settings/LokaceStavyPoznamky.json
gui/settings/json_tab_tree_state.json
gui/settings/json_tab_tree_state.json
gui/settings/json_tab_tree_state.json
gui/settings/rename_tree_state.json
gui/settings/rename_tree_state.json
gui/settings/rename_tree_state.json
gui/settings/web_photos_status_cache.json
gui/settings/web_photos_status_cache.json
gui/settings/web_photos_status_cache.json
gui/status_widget.py
gui/status_widget.py
gui/web_photos_window.py
gui/web_photos_window.py
main.py
pdf_generator.py
settings.json
settings/.DS_Store
settings/crop_status.json
settings/crop_status.json
settings/json_tree_state_web_photos.json
settings/json_tree_state_web_photos.json
settings/last_heic_dir.txt
settings/last_heic_dir.txt
settings/last_loc_assigned.json
settings/last_loc_assigned.json
settings/pdf_generator_settings.json
settings/pdf_generator_settings.json
```

---

## Konfigurace
- Výchozí nastavení je v `settings/settings.json`.
- Další související nastavení pro export PDF: `settings/pdf_generator_settings.json` a související JSON v `settings/`.
- Při ruční úpravě JSON formátu dodržujte platnou syntaxi (UTF-8).
- **Citlivá data (koordináty, jména)** do verzovaného repozitáře **neukládejte**; držte je mimo VCS (např. `.env`/lokální soubory) nebo použijte šifrované úložiště.

---

## Závislosti (připnuté verze)
```text
{requirements_block}
```

> Soubor `requirements.txt` by měl obsahovat přesně stejné položky. Pro úplnou reprodukovatelnost buildů zvažte `pip-tools`.

---

## Architektura & moduly
- `main.py` – vstupní bod aplikace (spuštění GUI).
- `core/` – logika a zpracování dat/obrazů.
- `gui/` – definice widgetů, oken a dialogů (PySide6).
- `pdf_generator.py` – export a generování PDF dokumentů.
- `settings/` – konfigurační JSON soubory.

{symbols_md}

---

## Vývoj
- Styl kódu: PEP 8, typové anotace, krátké a čitelné funkce.
- GUI: PySide6, preferováno dark theme; HiDPI kompatibilita.
- Commit zprávy v konvenci **Conventional Commits** (např. `feat: ...`, `fix: ...`).

---

## Licence
Doplňte vhodnou licenci do souboru `LICENSE` (např. MIT).

---

## Changelog
- **v{version} – {today.strftime("%Y-%m-%d")}**
  - první zveřejnění projektu do GitHub repozitáře
  - přidán `README.md` (podrobná struktura a symboly), `.gitignore`, `requirements.txt`
