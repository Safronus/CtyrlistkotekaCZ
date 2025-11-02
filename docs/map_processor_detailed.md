# Dokumentace (`map_processor.py`) – podrobná verze

**Soubor:** `map_processor.py`  
**SHA-256:** `9b8b2bad95716fd5cfccb5b9f4b204a5ef4f9916604d663936cbebe7eecf7c81`  •  **Řádků:** 1792  •  **Velikost:** 79904 B  
**Generováno:** 2025-10-29

---

## 1. Role a architektura
- Modul implementuje zpracování mapových dat/obrázků (výřezy, konverze, výpočty) a utilitní funkce pro GUI.

## 2. Importy a závislosti
### 2.1 Projektové moduly (lokální)
- `from io import BytesIO`
- `import unicodedata`
- `import traceback`
- `import traceback`
- `import pillow_heif`
- `import traceback`
- `import traceback`
- `import traceback`
- `import traceback`

### 2.2 Knihovny třetích stran
- `PySide6.QtCore` (import QObject, Signal)
- `requests`
- `PIL` (import Image, ImageDraw)
- `PIL.ExifTags` (import TAGS, GPSTAGS)
- `numpy`
- `PIL.PngImagePlugin` (import PngInfo)
- `PIL` (import Image)
- `PIL` (import Image, ImageDraw)
- `PIL` (import ImageFont)
- `PIL` (import ImageFont as _IF)
- `PIL` (import Image, ImageDraw, ImageFont, features)
- `PIL` (import Image)
- `PIL.PngImagePlugin` (import PngInfo)
- `PIL` (import Image, ImageDraw, ImageFont)
- `PIL` (import Image)
- `PIL.ExifTags` (import TAGS, GPSTAGS)
- `PIL.ExifTags` (import GPSTAGS)
- `PIL.ExifTags` (import GPSTAGS)
- `PIL` (import ImageDraw)
- `PIL` (import ImageFont)

### 2.3 Standardní knihovna (výběr)
datetime, hashlib, json, math, os, pathlib, re, subprocess, sys, time

## 3. Třídy v souboru
### 3.1 `MapProcessor`  
Báze: QObject
> Hlavní třída pro zpracování map - obsahuje váš původní kód

## 4. Signály, sloty, zkratky, akce, docky
### 4.1 Signál → Slot (detekováno)
_—_

### 4.2 Zkratky (QShortcut / QAction.setShortcut)
_—_

### 4.3 QAction
_—_

### 4.4 Dock widgety
_—_

## 5. Výchozí cesty a dialogy
_—_

## 6. Vazby na další soubory
_—_


### 7. QA scénáře (smoke test)
1. Lat/lon ↔ tile (různé zoomy) → numerická shoda v toleranci.
2. Skládání 3×3 dlaždic → správný rozměr mozaiky a návaznost.
3. Cache hit/miss → druhé volání rychlejší, bez síťových požadavků.
4. Chyby (404/429) → retry/backoff, log bez výjimek do UI.
5. Okraje (antimeridian, max zoom) → bez artefaktů.


### 8. Zkratky – přehled a možné kolize
_V souboru nebyly detekovány žádné zkratky přes `QShortcut`/`setShortcut()`._

---

## 9. Integrita zdrojového souboru
- Počet řádků: **1792**  •  Velikost: **79904 B**  •  SHA-256: `9b8b2bad95716fd5cfccb5b9f4b204a5ef4f9916604d663936cbebe7eecf7c81`
- První 3 neprázdné řádky:
  - `# -*- coding: utf-8 -*-`
  - `from PySide6.QtCore import QObject, Signal`
  - `import math`
- Poslední 3 neprázdné řádky:
  - `        self.log.emit("Dlaždice poskytuje OpenStreetMap Foundation", "info")`
  - `        self.log.emit("Tile usage policy: https://operations.osmfoundation.org/policies/tiles/", "info")`
  - `        self.log.emit("=" * 60, "info")`