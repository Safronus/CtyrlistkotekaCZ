# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.2a  **Datum vydání:** 2025-10-28

> **Ochrana soukromí:** Tento dokument záměrně **neobsahuje žádné osobní údaje, GPS souřadnice ani jména**. Obsah souborů `settings/*.json` není zde uváděn; dokumentace vychází pouze ze struktury a symbolů ve zdrojovém kódu.


---

## Funkce
- Moderní GUI v **PySide6** s preferencí dark theme (HiDPI/Retina).
- Import a správa položek sbírky, včetně práce s obrázky (Pillow).
- Zpracování obrazu (OpenCV), volitelná OCR integrace (`pytesseract`).
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

## Instalace (macOS)
Doporučený postup s virtuálním prostředím:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Spuštění
```bash
python main.py
```

---

## Struktura projektu (strom s uplatněným .gitignore)
_Následující strom **neobsahuje** ignorované položky (např. `__pycache__/`, `.DS_Store`, virtuální prostředí atp.)._

```text
core/
  .DS_Store
  map_processor.py
  map_processor.py
gui/
  settings/
    json_tab_tree_state.json
    json_tab_tree_state.json
    json_tab_tree_state.json
    LokaceStavyPoznamky.json
    LokaceStavyPoznamky.json
    LokaceStavyPoznamky.json
    rename_tree_state.json
    rename_tree_state.json
    rename_tree_state.json
    web_photos_status_cache.json
    web_photos_status_cache.json
    web_photos_status_cache.json
  .DS_Store
  image_viewer.py
  image_viewer.py
  log_widget.py
  log_widget.py
  main_window.py
  main_window.py
  pdf_generator_window.py
  pdf_generator_window.py
  status_widget.py
  status_widget.py
  web_photos_window.py
  web_photos_window.py
settings/
  .DS_Store
  crop_status.json
  crop_status.json
  json_tree_state_web_photos.json
  json_tree_state_web_photos.json
  last_heic_dir.txt
  last_heic_dir.txt
  last_loc_assigned.json
  last_loc_assigned.json
  pdf_generator_settings.json
  pdf_generator_settings.json
BEZ_FOTKY.png
DAROVANY.png
DejaVuSans-Bold.ttf
DejaVuSans.ttf
LiberationSerif-Bold.ttf
LiberationSerif-Regular.ttf
main.py
NICKNAME.png
pdf_generator.py
settings.json
VODOZNAK_BezJmena.png
ZTRACENY.png
```

---

## Závislosti (připnuté verze)
```text
ExifRead==3.0.0
numpy==2.1.3
opencv-python==4.10.0.84
piexif==1.1.3
Pillow==10.4.0
pillow-heif==0.16.0
PySide6==6.7.3
pytesseract==0.3.13
reportlab==4.2.2
requests==2.32.3
shapely==2.0.4
shiboken6==6.7.3
```


---

## Architektura & moduly
- `main.py` – vstupní bod aplikace.
- `core/` – logika a zpracování dat/obrazů.
- `gui/` – uživatelské rozhraní (PySide6 widgety/okna).
- `pdf_generator.py` – export/generování PDF.
- `settings/` – konfigurační JSON soubory (necommitujte citlivá data; použijte `settings.example.json`).

---

## Changelog
- **v3.2g – 2025-11-02**
  - PDF generátor → „📁 Přesunout do Ořezy“: po přesunu se automaticky **vymaže JSON anonymizace**
    (tab „🛡️ Nastavení anonymizace“), provede se refresh a uložení nastavení.
- **v3.2f – 2025-11-02**
  - Počítadlo čtyřlístků: oprava aplikace **velikosti textu** – při změně px se nově přepočítá
    `font_scale` a `font_thickness` pro OpenCV, takže velikost se projeví v náhledu i v otisku.
- **v3.2e – 2025-11-02**
  - Počítadlo čtyřlístků: fix zápisu čísel do fotky – pokud je canvas `numpy.ndarray`, text se kreslí
    in-place přes OpenCV (centrování, obrys i barva/velikost z UI). PIL větev zachována pro `PIL.Image`.
- **v3.2d – 2025-11-02**
  - Počítadlo čtyřlístků: hotfix pádu „missing self“ při starém volání `_put_centered_text_with_outline`.
    Wrapper nyní volá implementaci přes `type(self)._put_text_with_outline(self, ...)`, což obchází
    případné přestínění instančním atributem. UI **velikost** a **barva** textu zůstávají závazné.
- **v3.2c – 2025-11-02**
  - Počítadlo čtyřlístků: hotfix pádu při pohybu myší po prvním kliknutí.
    Přidán zpětně kompatibilní wrapper `_put_centered_text_with_outline(...)`
    (akceptuje starý podpis volání) a helper `_ensure_pil_draw(...)`.
    Velikost/barva textu z UI se uplatní v náhledu i v otisku.
- **v3.2b – 2025-11-02**  
  - Počítadlo čtyřlístků: oprava – UI **velikost** a **barva** textu se nyní uplatní vždy (náhled i otisk), i když starší kód předává vlastní defaulty.
- **v3.2a – 2025-11-02**
  - Počítadlo čtyřlístků: přidána volba **velikosti textu** (px) a **barvy textu** (dialog) pro čísla vkládaná do fotek.

- **v3.0c – 2025-10-28**
  - aktualizována sekce *Struktura projektu* na strom s uplatněným `.gitignore`
- **v3.0 – 2025-10-28**
  - první zveřejnění projektu do GitHub repozitáře
  - přidán `README.md`, `.gitignore`, `requirements.txt`

### Nástroj: **Počítadlo čtyřlístků** (🍀)
**Nové ovládání textu (v3.2a):**
- **Velikost textu** čísel (px) přes **spinbox** v docku Počítadla (rozsah 8–256 px, výchozí 64 px).
- **Barva textu** přes **Barva…** (QColorDialog); náhled čísla i otisk používá zvolenou barvu.
- Funkce fungují pro **náhled u kurzoru** i pro **otisk** do výsledného obrázku; obrys zůstává kvůli čitelnosti.
