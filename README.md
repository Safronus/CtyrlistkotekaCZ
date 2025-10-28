# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.1f  
**Datum vydání:** 2025-10-28

> **Ochrana soukromí:** README neobsahuje osobní údaje, GPS souřadnice ani jména. Konfiguraci v `settings/*.json` neuvádíme.

---

## Funkce
- Moderní GUI v **PySide6** (HiDPI/Retina, dark theme preferováno).
- Import/správa položek sbírky, práce s obrázky (Pillow, OpenCV).
- Generování PDF (ReportLab).
- Konfigurace v `settings/` (JSON).

### Nástroj: Počítadlo čtyřlístků (🍀)
- Umístění: horní **toolbar „Monitoring“**.
- Ovládání v podokně:
  - levý klik: **otisk čísla** do obrázku (start default **15140**),
  - **pravý klik = Undo**, tlačítka **Undo/Reset**,
  - **živý náhled** následujícího čísla se pohybuje **přímo pod kurzorem jako „razítko“**, zarovnání **na střed**,
  - náhled je **světle šedý** a **o něco menší** než finální otisk (0.8×, outline silnější) — přesně jako ve skriptu `PočítadloČtyřlístků.py`,
  - zavření podokna: **⌘W (Cmd+W)**, **Undo (⌘Z)**, **Uložit (⌘S)**,
  - výchozí složka dialogů:  
    `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Čtyřlístky na sušičce/`

---

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
- **v3.1f – 2025-10-28**
  - **Náhled čísel funguje jako „razítko“** přesně dle `PočítadloČtyřlístků.py`: menší šedý náhled (0.8×, outline +2) zarovnaný na **střed** kurzoru; klik vytvoří otisk do originálu.
- **v3.1e – 2025-10-28** — Fix: náhled plynule sleduje kurzor.
- **v3.1d – 2025-10-28** — Center text, macOS file dialog focus, bezpečné znovuotevření docku.
- **v3.1c – 2025-10-28** — Parita chování se skriptem (undo, preview, mapování souřadnic).
- **v3.1a–b – 2025-10-28** — Integrace tlačítka do toolbaru „Monitoring“, dock s Cmd+W.
- **v3.0 – 2025-10-28** — První zveřejnění projektu.
