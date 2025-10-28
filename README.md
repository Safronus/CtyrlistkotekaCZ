# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.1c  
**Datum vydání:** 2025-10-28

> **Ochrana soukromí:** README neobsahuje osobní údaje, GPS souřadnice ani jména. Konfiguraci v `settings/*.json` neuvádíme.

---

## Funkce
- Moderní GUI v **PySide6** (HiDPI/Retina, dark theme preferováno).
- Import/správa položek sbírky, práce s obrázky (Pillow, OpenCV).
- Generování PDF (ReportLab).
- Konfigurace v `settings/` (JSON).

### Nové / opravené ve verzi 3.1c
- **Počítadlo čtyřlístků** (podokno): chování **přesně podle `PočítadloČtyřlístků.py`**:
  - levý klik přidá číslo, **pravý klik = Undo**,
  - **náhled dalšího čísla pod kurzorem** (zap/vyp), startovní číslo **15140**,
  - měřítko zobrazení s přepočtem kliků → **správné souřadnice na originálním obrázku**,
  - **klávesy:** **Undo** (⌘Z), **Uložit** (⌘S), **Zavřít podokno** (⌘W),
  - výchozí složka dialogů:  
    `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Čtyřlístky na sušičce/`

**Ovládání:**  
V hlavním okně klikni na **🍀 Počítadlo** v toolbaru „Monitoring“. Otevře se **podokno** (dock) s funkcionalitou. Zavření podokna: **Cmd+W**.

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

---

## Changelog
- **v3.1c – 2025-10-28**
  - Reimplementováno chování „Počítadlo čtyřlístků“ 1:1 podle skriptu (`levý/pravý klik`, náhled, start 15140, ⌘Z/⌘S/⌘W, scale-to-fit mapping).
- **v3.1b – 2025-10-28**  
  - (repo housekeeping, bump verze)  
- **v3.1a – 2025-10-28**
  - Tlačítko **🍀** na toolbaru „Monitoring“, podokno zavíratelné **Cmd+W**.
- **v3.1 – 2025-10-28**
  - Přidán nástroj **Počítadlo čtyřlístků**.
- **v3.0 – 2025-10-28**
  - První zveřejnění projektu, přidán `README.md`, `.gitignore`, `requirements.txt`.
