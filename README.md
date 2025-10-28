# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.1a  
**Datum vydání:** 2025-10-28

> **Ochrana soukromí:** README neobsahuje osobní údaje, GPS souřadnice ani jména. Konfiguraci v `settings/*.json` neuvádíme.

---

## Funkce
- Moderní GUI v **PySide6** (HiDPI/Retina, dark theme preferováno).
- Import/správa položek sbírky, práce s obrázky (Pillow, OpenCV).
- Generování PDF (ReportLab).
- Konfigurace v `settings/` (JSON).

### Nové / upravené ve verzi 3.1a
- **Počítadlo čtyřlístků** — interaktivní číslování bodů v obrázku (OpenCV), startovní číslo, živý náhled, **Undo/Reset**, uložení.
- **Umístění tlačítka:** tlačítko **🍀 Počítadlo** je přidáno **na horní toolbar „Monitoring“** (nikoliv do menu).  
  Pokud je toolbar skrytý, je po startu okna zviditelněn.
- **Zavírání podokna zkratkou:** **⌘W (Cmd+W)**.
- **Výchozí složka dialogů:**  
  `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Čtyřlístky na sušičce/`

**Ovládání:**  
V hlavním okně klikni na **🍀 Počítadlo** v **toolbaru „Monitoring“**. Otevře se samostatné nemodální okno s počítadlem; zavření **Cmd+W**.

---

## Požadavky
- macOS (Apple Silicon i Intel), doporučeno aktuální
- Python 3.10+ (doporučeno 3.12)
- Virtuální prostředí (venv)

### Systémové balíčky (pokud je potřeba)
- **Tesseract OCR** (pro `pytesseract`): `brew install tesseract`
- (volitelně) **libheif** pro `pillow-heif`: `brew install libheif`

## Instalace (macOS)
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

> `requirements.txt` obsahuje stejné položky. Pro reprodukovatelnost zvaž `pip-tools`.

---

## Architektura & moduly
- `main_window.py` — hlavní okno; **toolbar „Monitoring“**; tlačítko **🍀 Počítadlo**; otevření nemodálního okna s počítadlem (Cmd+W).
- `core/` — logika a zpracování dat/obrazů.
- `gui/` — UI komponenty (PySide6 widgety/okna).
- `pdf_generator.py` — export/generování PDF.
- `settings/` — konfigurační JSON (nedávejte do repa citlivá data; preferujte `settings.example.json`).

---

## Changelog
- **v3.1a – 2025-10-28**
  - Oprava integrace tlačítka: přidáno na toolbar **„Monitoring“** + zviditelnění toolbaru po startu.
  - Podokno počítadla zavíratelné **Cmd+W**.
- **v3.1 – 2025-10-28**
  - Přidán nástroj **Počítadlo čtyřlístků** (OpenCV, start, náhled, Undo/Reset, uložení).
- **v3.0 – 2025-10-28**
  - První zveřejnění projektu, přidán `README.md`, `.gitignore`, `requirements.txt`.
