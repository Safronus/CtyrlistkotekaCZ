# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.1g  
**Datum vydání:** 2025-10-28

> **Ochrana soukromí:** README neobsahuje osobní údaje, GPS souřadnice ani jména. Citlivé konfigurace (`settings.json`) nedávejte do Gitu (ignorováno).

---

## Funkce
- Moderní GUI v **PySide6** (HiDPI/Retina, dark theme preferováno).
- Import/správa položek sbírky, práce s obrázky (OpenCV, Pillow).
- Generování PDF.
- macOS-first UX a klávesové zkratky.

### Nástroj: **Počítadlo čtyřlístků** (🍀)
- Umístění: horní **toolbar „Monitoring“** (tlačítko **🍀 Počítadlo**).
- Chování (parita se skriptem `PočítadloČtyřlístků.py`):
  - **Náhled čísla** (další v pořadí) je **zarovnaný na střed** kurzoru, **viditelný ihned po otevření** (u kurzoru, jinak střed).
  - **Levý klik** vytvoří **otisk čísla** do originálního obrázku; **pravý klik = Undo**.
  - **Startovní číslo:** výchozí **15140** (lze měnit ve spinboxu).
  - **Náhled** se plynule **pohybuje s kurzorem** („razítko“).
  - **Zkratky:** **⌘Z** (Undo), **⌘S** (Uložit), **⌘W** (Zavřít podokno).
  - **Výchozí složka dialogů:**  
    `/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Čtyřlístky na sušičce/`

> Pozn.: File dialog na macOS používá **WindowModal**, aktivaci okna a focus, aby šlo **okamžitě klikat** na položky.

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

## Changelog
- **v3.1g – 2025-10-28**
  - **macOS file dialog:** přepnuto na *WindowModal* + aktivace okna a focus → lze **hned klikat** na soubory bez „odkliku mimo“.  
  - **Resizing preview:** `QLabel` (FLClickableLabel) po změně velikosti **okamžitě znovu renderuje** náhled (bez „divného růstu“).
- **v3.1f – 2025-10-28** — Náhled ihned po otevření souboru; doplněna `_put_centered_text_with_outline`.
- **v3.1e – 2025-10-28** — Náhled plynule sleduje kurzor (správné pořadí výpočtu scale/offset).
- **v3.1d – 2025-10-28** — Center text; macOS file dialog focus; bezpečné znovuotevření docku.
- **v3.1c – 2025-10-28** — Parita chování se skriptem (undo, preview, mapování souřadnic).
- **v3.1a–b – 2025-10-28** — Integrace tlačítka do toolbaru „Monitoring“, dock s Cmd+W.
- **v3.0 – 2025-10-28** — První zveřejnění projektu.
