# CtyrlistkotekaCZ

Aplikace v Pythonu s GUI (PySide6) pro správu sbírky čtyřlístků.

**Verze:** 3.2  
**Datum vydání:** 2025-10-29

> **Soukromí:** README neobsahuje osobní údaje, GPS souřadnice ani jména. Citlivé konfigurace (`settings.json`) nedávejte do Gitu (ignorováno).

---

## Funkce
- Moderní GUI v **PySide6** (HiDPI/Retina, dark theme preferováno).
- Import/správa položek sbírky, práce s obrázky (OpenCV, Pillow).
- Generování PDF.
- macOS-first UX a klávesové zkratky.
- **Editor polygonu nad reálnými fotkami (.HEIC)** s náhledem (mezerník) a volbou **Upravit polygon**.

### Režimy editoru polygonu
- **Přidat bod**, **Mazat bod**, **Posun polygonu** (beze změn).
- **Vymalovat (štětcem)** — *nově ve verzi 3.2*:
  - Aktivace pomocí **checkboxu** v sekci **Režimy**.
  - **Malování tahem** myši zvětšuje plochu polygonu (bez klikání bodů).
  - **Nezávislé** na bodovém polygonu: po zapnutí se **nesemínuje** ze starého tvaru.
  - **Resetovat/Vymazat** v režimu štětce vynuluje **body i masku** (nic se „nevrací“).
  - **Kurzor** je **kolečko** v **barvě polygonu**; **výchozí poloměr 5 px** (lze měnit ve spinboxu „Štětec“).
  - Klávesy: `[` a `]` (nebo `-`/`=`) mění velikost štětce, `C` smaže tahy.

### Nástroj: **Počítadlo čtyřlístků** (🍀)
- Tlačítko v horním toolbaru „Monitoring“ (**🍀 Počítadlo**).
- **Náhled** čísla u kurzoru (zarovnán na střed), **otisk** levým klikem, **Undo** pravým.
- **Startovní číslo** se po otevření souboru nastaví na **(nejvyšší `Poslední` + 1)** z názvů `První-Poslední.(png|jpg|jpeg)` ve stejné složce.
- **Uložení** navrhuje jméno `První-Poslední.png`.

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
- **v3.2 – 2025-10-29**
  - Editor polygonu: přidán **režim „Vymalovat (štětcem)”** (checkbox v „Režimy“). Kreslení tahem, nezávislé na původním polygonu, **reset/clear** smaže body i masku; **kurzor kolečko v barvě polygonu**, výchozí **5 px**.
- **v3.1j – 2025-10-28** — Auto start čísla po otevření: **max `Poslední` + 1**.
- **v3.1i – 2025-10-28** — Auto start čísla dle max `Poslední` + auto název při uložení.
- **v3.1h – 2025-10-28** — macOS nativní dialogy (klik hned), auto název při uložení.
- **v3.1g – 2025-10-28** — File dialog focus, re-render při resize.
- **v3.1f – 2025-10-28** — Náhled ihned po otevření souboru; `_put_centered_text_with_outline`.
- **v3.1e – 2025-10-28** — Náhled sleduje kurzor (správné pořadí výpočtu).
- **v3.1d – 2025-10-28** — Center text; macOS file dialog focus; safe reopen dock.
- **v3.1c – 2025-10-28** — Parita chování se skriptem (undo, preview, mapping).
- **v3.1a–b – 2025-10-28** — Integrace tlačítka do toolbaru „Monitoring“, dock s Cmd+W.
- **v3.0 – 2025-10-28** — První zveřejnění projektu.
