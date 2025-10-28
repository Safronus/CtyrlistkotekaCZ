# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.1i  
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
  - **Náhled čísla** je **zarovnaný na střed** kurzoru a **viditelný ihned po otevření** (u kurzoru, jinak střed).
  - **Levý klik** vytvoří **otisk čísla** do originálu; **pravý klik = Undo** (Undo/Reset i tlačítky).
  - **Startovní číslo:** výchozí **15140** (lze měnit), **a po otevření souboru se automaticky nastaví** na **nejvyšší `PosledníČíslo`** nalezené v názvech souborů v aktuální složce (formát `První-Poslední.png/jpg/jpeg`).  
  - **Auto název při uložení:** `PrvníČíslo-PosledníČíslo.png` (např. `15140-15188.png`).
  - **Zkratky:** **⌘Z** (Undo), **⌘S** (Uložit), **⌘W** (Zavřít podokno).

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
- **v3.1j – 2025-10-28 — Auto start čísla = max PosledníČíslo + 1.**
- **v3.1i – 2025-10-28**
  - Po otevření souboru se **startovní číslo** automaticky nastaví na **největší `PosledníČíslo`** dle názvů `První-Poslední.(png|jpg|jpeg)` v aktuální složce.  
  - Při uložení se **navrhne název** `První-Poslední.png`.
- **v3.1h – 2025-10-28** — macOS nativní dialogy (klik hned), auto název při uložení.  
- **v3.1g – 2025-10-28** — File dialog focus, re-render při resize.  
- **v3.1f – 2025-10-28** — Náhled ihned po otevření souboru; `_put_centered_text_with_outline`.  
- **v3.1e – 2025-10-28** — Náhled sleduje kurzor (správné pořadí výpočtu).  
- **v3.1d – 2025-10-28** — Center text; macOS file dialog focus; safe reopen dock.  
- **v3.1c – 2025-10-28** — Parita chování se skriptem (undo, preview, mapping).  
- **v3.1a–b – 2025-10-28** — Integrace tlačítka do toolbaru „Monitoring“, dock s Cmd+W.  
- **v3.0 – 2025-10-28** — První zveřejnění projektu.
