# -*- coding: utf-8 -*-
"""
web_photos_window.py
====================

Okno pro správu a přípravu webových fotek nálezů čtyřlístků.

Aktuální verze zavádí:
- Realtime kontrolu souborů (QFileSystemWatcher + debounce), statistiky v 1. záložce.
- CMD/⌘ + W pro zavření okna.
- Vycentrovaný TabBar + ikony záložek.
- NOVÁ ZÁLOŽKA „Nastavení JSONů“:
  • 3 editory pro JSON („Nastavení lokací“, „Nastavení stavů“, „Nastavení poznámek“).
  • Ukládá/načítá se JEDEN společný soubor settings/LokaceStavyPoznamky.json
    ve struktuře: { "lokace": {...}, "stavy": {...}, "poznamky": {...} }.
  • Editory mají čísla řádků a klávesa Tab vkládá 2 mezery.
  • Vpravo strom složek s čísly fotek (jen validně pojmenované), s realtime updatem.

Pozn.: Tichý režim (QUIET_MODE=True) — bez log panelu.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Iterable, Dict, List, Set, Tuple
from datetime import datetime

from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QObject, QTimer, QSize, QModelIndex, QPersistentModelIndex, QFileSystemWatcher, QRect, QItemSelectionModel
)
from PySide6.QtGui import (
    QFont, QKeySequence, QShortcut, QIcon, QPixmap, QPainter, QColor,
    QTextFormat, QFontMetricsF, QStandardItemModel, QStandardItem,
    QAction, QGuiApplication  # ← přidáno sem
)
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget,
    QLabel, QPushButton, QGroupBox, QFrame, QSizePolicy, QApplication, QToolButton,
    QStyle, QDialogButtonBox, QMessageBox, QPlainTextEdit, QTreeView, QSpacerItem,
    QSplitter, QScrollArea, QMenu, QTextEdit, QAbstractItemView, QMenu, QLineEdit, QListWidget, QListWidgetItem, QInputDialog  # ← bez QAction
)


# --- QUIET MODE: tiché pozadí (bez log panelu a debug výpisů) ---
QUIET_MODE = True

# Reuse existujících widgetů pro sladění stylu aplikace (pokud jsou k dispozici v projektu)
try:
    from status_widget import StatusWidget
except Exception:
    StatusWidget = None  # fallback

try:
    from log_widget import LogWidget
except Exception:
    LogWidget = None  # fallback


# === Konfigurace sledovaných složek ===

OREZY_DIR = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Ořezy/")
MINIATURY_DIR = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Miniatury/")
ORIGINALS_DIR  = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Originály/")

# Lokační mapy jsou pouze zde:
LOCATION_MAPS_DIR = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Mapky lokací/Neroztříděné")

ALLOWED_EXTS: Set[str] = {".heic", ".jpg", ".jpeg"}  # case-insensitive

# Nový formát:
# ČísloNálezu + ČísloLokace(5) + IDLokace + [STAV] + [ANO|NE] + [Poznámka] . (HEIC/JPG/JPEG)
# STAV/ANO|NE/Poznámka jsou volitelné, ale mohou být i prázdné (např. "++NE+").
NAME_PATTERN = re.compile(
    r'^'
    r'(?P<id>\d+)\+'             # ČísloNálezu
    r'(?P<clok>\d{5})\+'         # ČísloLokace (5 číslic)
    r'(?P<idlok>[^+]+)'          # IDLokace (alespoň 1 znak, bez '+')
    r'(?:\+(?P<state>[^+]*)'     # [STAV] – může být i prázdné
    r'(?:\+(?P<anon>ANO|NE)'     # [Anonymizován] – ANO/NE
    r'(?:\+(?P<note>[^.]*))?'    # [Poznámka] – může být prázdné
    r')?)?'
    r'\.(?P<ext>HEIC|heic|JPG|jpg|JPEG|jpeg)$'
)

# === Cesty k nastavení ===
SETTINGS_DIR  = Path(__file__).resolve().parent / "settings"
RENAME_STATE_FILE = SETTINGS_DIR / "rename_tree_state.json"
JSON_TREE_STATE_FILE = SETTINGS_DIR / "json_tab_tree_state.json"
SETTINGS_FILE = SETTINGS_DIR / "LokaceStavyPoznamky.json"

# NEW: cache posledního zobrazeného stavu indikátorů (pro rychlý „warm start“)
STATUS_CACHE_FILE = SETTINGS_DIR / "web_photos_status_cache.json"
ALLOWED_STATES = {
    "BEZFOTKY", "DAROVANY", "ZTRACENY",
    "BEZGPS", "NEUTRZEN", "OBDAROVANY",
    # >>> DOPLNĚNO:
    "BEZLOKACE", "LOKACE-NEEXISTUJE",
}

class NamingFormatDialog(QDialog):
    """
    Modální okno s popisem formátu pojmenování.
    - Zavírá se tlačítkem „Zavřít“ nebo zkratkou QKeySequence.Close (Cmd+W / Ctrl+W).
    """
    def __init__(self, html_description: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Formát názvů souborů")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        self._lbl = QLabel(self)
        self._lbl.setTextFormat(Qt.RichText)
        self._lbl.setWordWrap(True)
        self._lbl.setText(html_description)
        layout.addWidget(self._lbl)

        # Spodní lišta s tlačítkem Zavřít
        btn_row = QHBoxLayout()
        btn_row.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        btn_close = QPushButton("Zavřít", self)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        # Klávesová zkratka pro zavření (Cmd+W na macOS, Ctrl+W jinde)
        QShortcut(QKeySequence.Close, self, activated=self.accept)

# === NEW: Dataclass a worker pro porovnání složek "Originály" a "Ořezy" ===

class SelectionIndicator(QFrame):
    """
    Jednoduchý panel zobrazující počty vybraných položek ve stromu:
      - počet vybraných souborů
      - počet vybraných složek

    Ovládá se metodou set_counts(files:int, dirs:int).
    """
    def __init__(self, title: str = "Výběr", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._title = QLabel(title, self)
        self._title.setStyleSheet("font-weight: 600;")

        self._label = QLabel("Vybráno: 0 souborů, 0 složek", self)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)
        row.addWidget(self._title)
        row.addStretch(1)
        row.addWidget(self._label)

        self.setStyleSheet("""
        SelectionIndicator {
            background: palette(base);
            border: 1px solid palette(midlight);
            border-radius: 6px;
        }
        """)

    def set_counts(self, files: int, dirs: int) -> None:
        # Korektní čeština pro jednotná čísla (minimální logika)
        def plural(val: int, one: str, few: str, many: str) -> str:
            # 1 -> one, 2-4 -> few, ostatní -> many
            if val == 1: return one
            if 2 <= val <= 4: return few
            return many

        files_txt = plural(files, "soubor", "soubory", "souborů")
        dirs_txt  = plural(dirs,  "složka", "složky", "složek")
        self._label.setText(f"Vybráno: {files} {files_txt}, {dirs} {dirs_txt}")
        

# === Datové struktury ===

@dataclass
class FolderStats:
    folder: Path
    total_files: int
    valid_named: int
    invalid_named: int


# === Worker (QThread) pro sken složek ===

class ScanWorker(QObject):
    """Rekurzivní sken složek + vyhodnocení formátu názvů + seznam validních souborů."""
    finished = Signal(dict)  # dict[str, {...stats..., "valid_files": [abs_paths]}]
    progress = Signal(str)   # nepoužito v QUIET režimu

    def __init__(self, folders: Iterable[Path]):
        super().__init__()
        self._folders = list(folders)

    @Slot()
    def run(self):
        result: Dict[str, dict] = {}
        for folder in self._folders:
            stats, valid_files = self._scan_one(folder)
            result[str(folder)] = {
                "folder": folder,
                "total_files": stats.total_files,
                "valid_named": stats.valid_named,
                "invalid_named": stats.invalid_named,
                "valid_files": [str(p) for p in valid_files],
            }
        self.finished.emit(result)

    def _scan_one(self, root: Path) -> Tuple[FolderStats, List[Path]]:
        total = 0
        valid = 0
        invalid = 0
        valid_files: List[Path] = []

        if not root.exists():
            return FolderStats(root, 0, 0, 0), valid_files

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_EXTS:
                continue
            total += 1
            if NAME_PATTERN.match(path.name):
                valid += 1
                valid_files.append(path)
            else:
                invalid += 1

        return FolderStats(root, total, valid, invalid), valid_files


# === Watcher pro reálný čas ===

class RecursiveDirectoryWatcher(QObject):
    """
    Nadstavba nad QFileSystemWatcher:
      - rekurzivně hlídá všechny podsložky,
      - emituje `changed` při libovolné změně,
      - `refresh()` po skenu doplní nově vzniklé podsložky.
    """
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._roots: List[Path] = []
        self._watched_dirs: List[str] = []

        self._watcher.directoryChanged.connect(self._on_fs_event)
        self._watcher.fileChanged.connect(self._on_fs_event)

    def set_roots(self, roots: Iterable[Path]):
        self._roots = [Path(p) for p in roots]
        self._rebuild_watches()

    def refresh(self):
        self._rebuild_watches()

    def _on_fs_event(self, _):
        self.changed.emit()

    def _rebuild_watches(self):
        if self._watched_dirs:
            try:
                self._watcher.removePaths(self._watched_dirs)
            except Exception:
                pass
        self._watched_dirs = []

        paths: List[str] = []
        for root in self._roots:
            if not root.exists():
                continue
            if root.is_dir():
                paths.append(str(root))
                for p in root.rglob("*"):
                    if p.is_dir():
                        paths.append(str(p))

        if paths:
            self._watcher.addPaths(paths)
            self._watched_dirs = paths


# === Editor s čísly řádků pro JSON ===

class LineNumberArea(QWidget):
    def __init__(self, editor: "JsonCodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self._editor.lineNumberAreaPaintEvent(event)

class JsonCodeEditor(QPlainTextEdit):
    """QPlainTextEdit s levým žlábkem pro čísla řádků a jemným zvýrazněním aktuálního řádku."""

    class _LineNumberArea(QWidget):
        def __init__(self, editor: "JsonCodeEditor"):
            super().__init__(editor)
            self._editor = editor

        def sizeHint(self) -> QSize:
            return QSize(self._editor._lineNumberAreaWidth(), 0)

        def paintEvent(self, event):
            self._editor._paintLineNumberArea(event)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        # Levý žlábek s čísly řádků
        self._lineNumberArea = JsonCodeEditor._LineNumberArea(self)

        # Aktualizace šířky žlábku / překreslení při změnách
        self.blockCountChanged.connect(self._updateLineNumberAreaWidth)
        self.updateRequest.connect(self._updateLineNumberArea)
        self.cursorPositionChanged.connect(self._highlightCurrentLine)

        self._updateLineNumberAreaWidth(0)
        self._highlightCurrentLine()

    # ---------- Line numbers: layout & malování ----------

    def _lineNumberAreaWidth(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        char_w = self.fontMetrics().horizontalAdvance('9')
        # malé okraje vlevo/vpravo + šířka čísel
        return 8 + digits * char_w + 8

    def _updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self._lineNumberAreaWidth(), 0, 0, 0)

    def _updateLineNumberArea(self, rect, dy):
        if dy:
            self._lineNumberArea.scroll(0, dy)
        else:
            self._lineNumberArea.update(0, rect.y(), self._lineNumberArea.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._lineNumberArea.setGeometry(QRect(cr.left(), cr.top(), self._lineNumberAreaWidth(), cr.height()))

    def _paintLineNumberArea(self, event):
        painter = QPainter(self._lineNumberArea)
        # jemné pozadí žlábku
        try:
            bg = self.palette().alternateBase()
        except Exception:
            bg = QColor(245, 245, 245)
        painter.fillRect(event.rect(), bg)

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        fm = self.fontMetrics()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(blockNumber + 1)
                painter.setPen(self.palette().color(self.foregroundRole()))
                painter.drawText(
                    0, top, self._lineNumberArea.width() - 4, fm.height(),
                    Qt.AlignRight | Qt.AlignVCenter, number
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            blockNumber += 1

    # ---------- UX drobnosti ----------

    def _highlightCurrentLine(self):
        try:
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(self.palette().alternateBase())
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            self.setExtraSelections([sel])
        except Exception:
            # bezpečný fallback
            self.setExtraSelections([])

    def keyPressEvent(self, e):
        # Tab -> 2 mezery (podle specifikace editoru)
        if e.key() == Qt.Key_Tab:
            self.insertPlainText("  ")
            return
        super().keyPressEvent(e)

# === Hlavní okno ===

class WebPhotosWindow(QDialog):
    """
    Záložka 1: „Kontrola stavu fotek na web“
      • Zobrazuje statistiky pro Ořezy a Originály.
      • Kontrola běží na pozadí (watcher + debounce).
      • Ukázka formátu v modálním okně.

    Záložka 2: „Nastavení JSONů“
      • Tři editory (lokace / stavy / poznámky), ukládají se do settings/LokaceStavyPoznamky.json.
      • Vpravo strom platných souborů (složkový přehled) s realtime updatem.
    """
    
    def __init__(self, parent=None, log_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Web fotky")
        # Velké okno – na výšku obrazovky (s menší rezervou), šířka 1600
        try:
            screen = QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
            h = avail.height() - 60 if avail else 1200
        except Exception:
            h = 1200
        self.setMinimumSize(QSize(1600, h))
        self.resize(QSize(1600, h))
    
        self._log_fn = log_fn  # volitelné externí logování
    
        # --- Hlavní layout + záložky ---
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
    
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        root.addWidget(self.tabs, 1)
    
        # Záložky
        tab_check  = self._build_check_tab()   # "Kontrola stavu fotek na web"
        tab_json   = self._build_json_tab()    # "Nastavení JSONů" (4 editory + pravý strom)
        tab_rename = self._build_rename_tab()  # "Přejmenování" (strom + akce)
    
        # NOVÁ záložka: "Ořezávání"
        tab_crop   = self._build_crop_tab()
    
        # Ikony záložek (standardní)
        self.tabs.addTab(tab_check,  self.style().standardIcon(QStyle.SP_DialogYesButton), "Kontrola stavu fotek na web")
        self.tabs.addTab(tab_json,   self.style().standardIcon(QStyle.SP_FileDialogDetailedView), "Nastavení JSONů")
        self.tabs.addTab(tab_rename, self.style().standardIcon(QStyle.SP_BrowserReload), "Přejmenování")
        self.tabs.addTab(tab_crop,   self.style().standardIcon(QStyle.SP_FileDialogContentsView), "Ořezávání")
    
        try:
            self._apply_indicator_styles()
            self._force_range_badge_style()
            self._restyle_last_check_as_badge()
        except Exception:
            pass
    
        # (Volitelné) stavový pruh – pokud ho používáš jinde v kódu
        try:
            from .status_widget import StatusWidget  # nebo: from status_widget import StatusWidget
            self.status = StatusWidget(parent=self)
            root.addWidget(self.status)
        except Exception:
            self.status = None
    
        # --- Klávesová zkratka na zavření podokna (CMD+W) ---
        QShortcut(QKeySequence.Close, self, self.close)
    
        # --- Watcher na změny ve složkách + debounce skenu ---
        self._dir_watcher = RecursiveDirectoryWatcher(self)
        self._dir_watcher.set_roots([OREZY_DIR, ORIGINALS_DIR])
        self._dir_watcher.changed.connect(self._on_fs_changed)
    
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self.run_scan)
    
        # --- Řízení „rename seance“ a stabilizace stromu Přejmenování ---
        self._suspend_fs_events = False                 # když True, _on_fs_changed ignoruje FS události
        self._rename_in_progress = False                # právě probíhá dávkové přejmenování
        self._sticky_expand_paths: list[str] = []       # rozbalené cesty (Přejmenování)
        self._sticky_focus_path: str | None = None      # složka, na kterou se má vrátit fokus
        self._sticky_scroll: int | None = None          # vertikální scroll stromu
        self._sticky_scans_remaining: int = 0           # kolik následných skenů ještě držet „sticky“
    
        # Throttle skenů: max 1 běžící + 1 pending
        self._scan_running: bool = False
        self._scan_pending: bool = False
    
        self._rename_grace_timer = QTimer(self)
        self._rename_grace_timer.setSingleShot(True)
        self._rename_grace_timer.setInterval(1200)  # ms
        self._rename_grace_timer.timeout.connect(self._end_rename_grace)
    
        # --- Sticky stav a realtime pro pravý strom v „Nastavení JSONů“ ---
        self._json_tree_sticky_expand: list[str] = []        # rozbalené složky (cesty) v pravém stromu
        self._json_tree_sticky_focus_path: str | None = None # složka s fokusem
        self._json_tree_sticky_scroll: int | None = None     # vertikální scroll
    
        self._json_rebuild_timer = QTimer(self)   # debounce pro rebuild pravého stromu po změně JSON editorů
        self._json_rebuild_timer.setSingleShot(True)
        self._json_rebuild_timer.setInterval(350)
        self._json_rebuild_timer.timeout.connect(self._rebuild_json_right_tree)
    
        # Autosave JSON editorů (tiché ukládání při psaní)
        self._json_autosave_timer = QTimer(self)
        self._json_autosave_timer.setSingleShot(True)
        self._json_autosave_timer.setInterval(800)
        self._json_autosave_timer.timeout.connect(self._autosave_json_settings)
             
        # --- Debounce pro rychlou aktualizaci indikátorů v záložce „Přejmenování“ ---
        self._indicators_timer = QTimer(self)
        self._indicators_timer.setSingleShot(True)
        self._indicators_timer.setInterval(150)  # ms – svižné, ale ne přespříliš
        self._indicators_timer.timeout.connect(self._update_rename_indicators)
    
        # ENTER -> přejmenování
        QShortcut(QKeySequence(Qt.Key_Return), self.ren_tree, activated=self._rename_selected_item)
        
        # CMD+Backspace -> smazat
        QShortcut(QKeySequence("Ctrl+Backspace"), self.ren_tree, activated=self._delete_selected_items)
        
        # CMD+C -> kopírovat
        QShortcut(QKeySequence.Copy, self.ren_tree, activated=self._copy_selected_items)
        
        # CMD+V -> vložit
        QShortcut(QKeySequence.Paste, self.ren_tree, activated=self._paste_items)
    
        # --- Měkké počítadlo FS změn během rename (pro „grace“ burst) ---
        self._fs_changes_during_rename = 0
    
        # --- Odložené „obnovení watcherů“ po skončení grace (nebude-li třeba, nic neudělá) ---
        self._watcher_refresh_timer = QTimer(self)
        self._watcher_refresh_timer.setSingleShot(True)
        self._watcher_refresh_timer.setInterval(300)
        self._watcher_refresh_timer.timeout.connect(self._refresh_watcher_roots_main)
    
        # --- Cache aktuálně nastavených kořenů watcheru (pro chytré porovnání) ---
        self._watch_roots_cache = [str(OREZY_DIR), str(ORIGINALS_DIR)]
    
        # --- Prvotní načtení dat / sken ---
        # (Načtení nastavení zároveň spustí první rebuild pravého stromu JSONů.)
        QTimer.singleShot(200, self.run_scan)
        QTimer.singleShot(250, self._load_settings_into_editors)
        self._ensure_selection_indicator_panel()
        
        new_w = int(self.width() * 1.45)
        self.resize(new_w, self.height())
        
    def _refresh_watcher_roots_main(self):
        """
        „Chytrý“ refresh kořenů watcheru:
        - Pokud se kořeny fakticky nezměnily (po normalizaci cest), nedělá NIC.
          -> tím se zabrání hromadnému odebírání/přidávání podsložek a „zamrznutí UI“.
        - Pokud se změnily, provede se set_roots(...) JEN jednou, odloženě po grace.
        """
        try:
            import os
            def _norm(paths):
                out = []
                for p in paths:
                    try:
                        out.append(os.path.realpath(os.fspath(p)))
                    except Exception:
                        out.append(str(p))
                out.sort()
                return out
    
            new_roots = [OREZY_DIR, ORIGINALS_DIR]
            old_norm = _norm(getattr(self, "_watch_roots_cache", []))
            new_norm = _norm(new_roots)
    
            # NIC nedělej, pokud se reálně nic nezměnilo
            if old_norm == new_norm:
                return
    
            # Jinak jednorázově přenastav kořeny a ulož novou cache
            self._dir_watcher.set_roots(new_roots)
            self._watch_roots_cache = [str(OREZY_DIR), str(ORIGINALS_DIR)]
        except Exception:
            # Bezpečný fallback: nic nedělej (raději neblokovat UI)
            pass
        
    # --- UVNITŘ třídy WebPhotosWindow ---
    
    def _build_crop_tab(self):
        """
        Záložka 'Ořezávání' pro Web fotky.
        - Seznam: agregace všech fotek z 'Originály/' (rekurzivně), ořezané = existuje protějšek v 'Ořezy/' se shodným číslem před '+'.
        - Jednořádkové zobrazení: "číslo · relativní_cesta" + stavová ikona (zelená=✅ ořezané, šedá=neořezané).
        - Náhled: čtvercový výběr (create/move/resize), tlačítko ✂️ Ořezat (Ctrl+K), mezerník/ESC zavřít, kolo=další/předchozí.
        - Uložení do 'Ořezy/' (originály se NEMĚNÍ), metadata + časy zachovány; běží na pozadí a během zápisu umlčí watcher.
        - Po ořezu: hned přejde na další NEOŘEZANOU (ve viditelném seznamu); po ZAVŘENÍ náhledu proběhne plný rescan a seznam se aktualizuje.
        - Filtr „Skrýt ořezané“ (default zapnutý) jen přefiltruje zobrazení (bez I/O).
        """
        from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
            QPushButton, QSizePolicy, QMessageBox, QStyle, QDialog, QApplication,
            QRubberBand, QCheckBox
        )
        from PySide6.QtGui import (
            QPixmap, QKeySequence, QShortcut, QCursor, QImageReader, QImage,
            QIcon, QPainter, QColor, QPen
        )
        from PySide6.QtCore import (
            Qt, QSize, QRect, QPoint, QObject, Signal, QTimer
        )
    
        import os, re, sys, threading, subprocess
        from pathlib import Path
        from datetime import datetime
    
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".webp"}
    
        # --- Signálový emitor pro thread-safe callbacky ---
        class _Emitter(QObject):
            saved = Signal(str)                 # num (číslo před '+') po úspěšném uložení
            prefetched = Signal(str, object)    # path, QImage (scaled)
            rescanned = Signal(list, set)       # items: [(num, path, rel)], cropped_nums:set
    
        emitter = _Emitter(self)
    
        # --- UI kořen ---
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
    
        # --- Horní lišta akcí ---
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
    
        lbl_roots = QLabel(
            f"<b>Kořen (Originály):</b> {str(ORIGINALS_DIR)}<br>"
            f"<b>Uložení ořezů:</b> {str(OREZY_DIR)}"
        )
        lbl_roots.setTextFormat(Qt.RichText)
    
        chk_hide = QCheckBox("Skrýt ořezané")
        chk_hide.setChecked(True)
    
        btn_refresh = QPushButton(self.style().standardIcon(QStyle.SP_BrowserReload), " Obnovit")
        btn_refresh.setToolTip("Znovu načte seznam fotek z 'Originály/' (běží na pozadí)")
    
        btn_quick_crop = QPushButton("✂️ Rychlý ořez")
        btn_quick_crop.setToolTip("Otevřít první neořezanou fotku")
    
        top.addWidget(lbl_roots, 1)
        top.addWidget(chk_hide, 0)
        top.addWidget(btn_quick_crop, 0)
        top.addWidget(btn_refresh, 0)
        layout.addLayout(top)
    
        # --- Seznam fotek (jednořádkový layout) ---
        lst = QListWidget()
        lst.setSelectionMode(QListWidget.SingleSelection)
        lst.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lst.setMinimumHeight(300)
        lst.setStyleSheet("""
            QListWidget { background:#1a1a1a; color:#e6e6e6; border:1px solid #333; }
            QListWidget::item { padding:4px 8px; }  /* méně paddingu -> více položek na výšku */
            QListWidget::item:selected { background:#2a2a2a; }
        """)
        layout.addWidget(lst, 1)
    
        info = QLabel("Načítání…")
        info.setStyleSheet("color:#a0a0a0;")
        layout.addWidget(info)
    
        # Uložit widgety na self
        self._crop_list = lst
        self._crop_info = info
        self._crop_btn_quick = btn_quick_crop
        self._crop_hide_chk = chk_hide
    
        # === Ikony (stavové tečky) ===
        def _make_dot_icon(hex_color: str, diameter: int = 12) -> QIcon:
            pm = QPixmap(diameter, diameter)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            color = QColor(hex_color)
            p.setPen(QPen(color.darker(140), 1))
            p.setBrush(color)
            p.drawEllipse(1, 1, diameter - 2, diameter - 2)
            p.end()
            return QIcon(pm)
    
        icon_cropped = _make_dot_icon("#42b983")   # zelená jako v PDF generátoru
        icon_uncropped = _make_dot_icon("#666666") # šedá pro nehotové
    
        # === Pomocné: extrakce čísla před '+' ===
        num_re = re.compile(r"^(\d+)\+")
        def number_from_name(name: str) -> str | None:
            m = num_re.match(name)
            return m.group(1) if m else None
    
        # --- Stav / statistiky ---
        total_count = 0
        cropped_count = 0
        def _update_stats_label():
            info.setText(f"Celkem: {total_count} • Ořezané: {cropped_count} • Neořezané: {total_count - cropped_count}")
            btn_quick_crop.setEnabled(total_count > cropped_count)
    
        # Interní model (všechny položky) pro rychlý filtr
        model_items: list[dict] = []   # {"num": str, "path": str, "rel": str, "is_cropped": bool}
    
        # Přestavění listu podle filtru (bez I/O) – JEDEN ŘÁDEK NA POLOŽKU
        def rebuild_list_from_model():
            lst.clear()
            hide = chk_hide.isChecked()
            for it in model_items:
                if hide and it["is_cropped"]:
                    continue
                text = f"{it['num']} · {it['rel']}"   # jednorádkový popisek
                w = QListWidgetItem(text)
                w.setIcon(icon_cropped if it["is_cropped"] else icon_uncropped)
                w.setToolTip(
                    f"{'Ořezané' if it['is_cropped'] else 'Neořezané'}\n"
                    f"Originál: {it['path']}"
                )
                w.setData(Qt.UserRole, it["path"])
                w.setData(Qt.UserRole + 1, it["num"])
                w.setData(Qt.UserRole + 2, bool(it["is_cropped"]))  # stav
                w.setSizeHint(QSize(-1, 26))  # kompaktní výška
                lst.addItem(w)
    
        # === Asynchronní rescan (Originály rekurzivně + Ořezy ploché) ===
        def _scan_worker():
            items = []
            cropped_nums = set()
            try:
                for f in os.listdir(OREZY_DIR):
                    p = Path(OREZY_DIR, f)
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                        n = number_from_name(p.name)
                        if n: cropped_nums.add(n)
            except Exception:
                pass
            root = Path(ORIGINALS_DIR)
            if root.exists():
                base = root
                for dpath, _, files in os.walk(root):
                    for f in files:
                        p = Path(dpath, f)
                        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
                            continue
                        n = number_from_name(p.name)
                        if not n:
                            continue
                        rel = str(p.relative_to(base))
                        items.append((n, str(p), rel))
            items.sort(key=lambda t: (int(t[0]), t[2].lower()))
            emitter.rescanned.emit(items, cropped_nums)
    
        def rescan_async():
            info.setText("Skenuji…")
            threading.Thread(target=_scan_worker, daemon=True).start()
    
        def _on_rescanned(items, cropped_nums):
            nonlocal total_count, cropped_count, model_items
            # Přepočítej počty
            total_count = len(items)
            cropped_count = 0
            # Postav model
            model_items = []
            for n, path, rel in items:
                is_c = (n in cropped_nums)
                if is_c: cropped_count += 1
                model_items.append({"num": n, "path": path, "rel": rel, "is_cropped": is_c})
            # Přestav zobrazení podle filtru
            rebuild_list_from_model()
            _update_stats_label()
    
        emitter.rescanned.connect(_on_rescanned)
    
        # === Označ VŠECHNY položky se stejným číslem jako ořezané (bez plného rescanu během práce) ===
        def mark_cropped_by_number(num: str | None):
            nonlocal cropped_count
            if not num:
                return
            changed = 0
            # 1) aktualizuj model
            for it in model_items:
                if it["num"] == num and not it["is_cropped"]:
                    it["is_cropped"] = True
                    changed += 1
            if changed:
                cropped_count += changed
                _update_stats_label()
            # 2) aktualizuj *aktuálně viditelné* položky (ikona + role)
            for i in range(lst.count()):
                w = lst.item(i)
                if w.data(Qt.UserRole + 1) == num and not bool(w.data(Qt.UserRole + 2)):
                    w.setIcon(icon_cropped)
                    w.setData(Qt.UserRole + 2, True)
    
        emitter.saved.connect(mark_cropped_by_number)
    
        # === Pomocné pro nalezení první/„další“ neořezané v *aktuálním zobrazení* ===
        def _item_is_cropped(it: QListWidgetItem) -> bool:
            val = it.data(Qt.UserRole + 2)
            if isinstance(val, bool):
                return val
            return False
    
        def first_uncropped_index() -> int | None:
            for i in range(lst.count()):
                if not _item_is_cropped(lst.item(i)):
                    return i
            return None
    
        def next_uncropped_after(idx: int) -> int | None:
            for i in range(idx + 1, lst.count()):
                if not _item_is_cropped(lst.item(i)):
                    return i
            for i in range(0, idx):
                if not _item_is_cropped(lst.item(i)):
                    return i
            return None
    
        # === Prefetch cache ===
        class _PrefetchState:
            def __init__(self):
                self.lock = threading.Lock()
                self.cache: dict[str, QImage] = {}
                self.pending: set[str] = set()
        prefetch = _PrefetchState()
    
        def _scaled_qimage_read(path: str) -> QImage | None:
            """
            Načte obrázek a hned ho škáluje tak, aby se CELÝ vešel na aktuální obrazovku.
            Zachová poměr stran, aplikuje EXIF rotaci (QImageReader.AutoTransform).
            """
            scr = QApplication.primaryScreen()
            geom = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
        
            # Rezervy na rámeček okna, horní lištu s tlačítkem „Ořezat“ a spodní hint
            # (volené s rezervou, aby se náhled vždy vešel i s chrome)
            max_w = max(200, geom.width()  - 120)
            max_h = max(200, geom.height() - 260)
        
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                rw, rh = size.width(), size.height()
                ratio = min(max_w / max(1, rw), max_h / max(1, rh), 1.0)
                target = QSize(int(rw * ratio), int(rh * ratio))
                reader.setScaledSize(target)
        
            img = reader.read()
            return img if not img.isNull() else None
    
        def _prefetch_worker(path: str):
            img = _scaled_qimage_read(path)
            emitter.prefetched.emit(path, img)
    
        def prefetch_paths(paths: list[str], how_many: int = 2):
            with prefetch.lock:
                for p in paths[:how_many]:
                    if p in prefetch.cache or p in prefetch.pending:
                        continue
                    prefetch.pending.add(p)
                    threading.Thread(target=_prefetch_worker, args=(p,), daemon=True).start()
    
        def _on_prefetched(path: str, qimg: QImage | None):
            with prefetch.lock:
                prefetch.pending.discard(path)
                if qimg is not None:
                    prefetch.cache[path] = qimg
    
        emitter.prefetched.connect(_on_prefetched)
    
        # === Náhled/Editor (umlčení watcheru během save) ===
        class _CropPreviewDialog(QDialog):
            def __init__(self, image_paths: list[str], start_index: int, parent=None,
                         on_cropped=None, get_next_uncropped_idx=None):
                super().__init__(parent)
                self.setWindowTitle("Náhled a ořez")
                self.setModal(True)
                self.image_paths = image_paths
                self.current_index = max(0, min(start_index, len(image_paths)-1))
                self._on_cropped = on_cropped
                self._get_next_uncropped_idx = get_next_uncropped_idx
                self._parent_win = parent  # WebPhotosWindow
    
                # výběr stav
                self._rubber: QRubberBand | None = None
                self._origin: QPoint | None = None
                self._mode: str = "idle"
                self._resize_handle: str | None = None
                self._anchor: QPoint | None = None
                self._move_offset: QPoint | None = None
                self._did_action_in_gesture = False
    
                self._HANDLE_R = 8
                self._MIN_SIDE = 24
    
                v = QVBoxLayout(self)
                v.setContentsMargins(10, 10, 10, 10)
                v.setSpacing(6)
    
                # horní lišta: název + tlačítko Ořezat
                topbar = QHBoxLayout()
                self._name_lbl = QLabel("")
                self._name_lbl.setStyleSheet("color:#ddd; font-weight:bold;")
                self.btn_crop = QPushButton("✂️ Ořezat (Ctrl+K)")
                self.btn_crop.setToolTip("Provést ořez vybraného čtverce a uložit do složky „Ořezy“ (metadata zachována).")
                self.btn_crop.clicked.connect(self.crop_image)
                topbar.addWidget(self._name_lbl, 1)
                topbar.addWidget(self.btn_crop, 0)
                v.addLayout(topbar)
    
                self._img_lbl = QLabel("Načítání...")
                self._img_lbl.setAlignment(Qt.AlignCenter)
                self._img_lbl.setMouseTracking(True)
                self._img_lbl.setStyleSheet("background:#111; color:#999;")
                v.addWidget(self._img_lbl, 1)
    
                hint = QLabel("Mezerník/ESC: zavřít • Kolečko/gesto: předchozí/další • Ctrl+K: ořez (čtverec)")
                hint.setStyleSheet("color:#aaa;")
                v.addWidget(hint)
    
                # zkratka Ctrl+K přesně dle požadavku
                self.shortcut_crop = QShortcut(QKeySequence("Ctrl+K"), self)
                self.shortcut_crop.activated.connect(self.crop_image)
    
                # Obrázek / metadata
                self._scaled_pixmap: QPixmap | None = None
                self._pil_img = None
                self._pil_exif = None
                self._pil_icc = None
    
                self.load_current()
    
            # robustní zavření okna
            def keyPressEvent(self, event):
                if event.key() in (Qt.Key_Space, Qt.Key_Escape):
                    self.accept()
                else:
                    super().keyPressEvent(event)
    
            # kolo = před/za
            def wheelEvent(self, event):
                phase = event.phase()
                if phase == Qt.ScrollBegin:
                    self._did_action_in_gesture = False
                elif phase == Qt.ScrollEnd:
                    self._did_action_in_gesture = False
                    event.accept(); return
                if self._did_action_in_gesture:
                    event.accept(); return
                delta = event.pixelDelta().y() if not event.pixelDelta().isNull() else event.angleDelta().y()
                acted = False
                if delta < -5 and self.current_index < len(self.image_paths) - 1:
                    self.current_index += 1; self.load_current(); acted = True
                elif delta > 5 and self.current_index > 0:
                    self.current_index -= 1; self.load_current(); acted = True
                if acted: self._did_action_in_gesture = True
                event.accept()
    
            # PIL + EXIF transpose
            def _load_pil_with_orientation(self, path: str):
                try:
                    from PIL import Image, ImageOps
                except Exception:
                    return None, None, None
                img = Image.open(path)
                exif_bytes = img.info.get("exif")
                icc = img.info.get("icc_profile")
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                return img, exif_bytes, icc
    
            # cache → QImage rychle
            def _scaled_qimage_from_cache_or_read(self, path: str) -> QImage | None:
                with prefetch.lock:
                    qimg = prefetch.cache.pop(path, None)
                if qimg is not None:
                    return qimg
                return _scaled_qimage_read(path)
    
            def load_current(self):
                if not self.image_paths:
                    return
                path = self.image_paths[self.current_index]
                self._name_lbl.setText(Path(path).name)
            
                self._pil_img, self._pil_exif, self._pil_icc = self._load_pil_with_orientation(path)
            
                qimg = self._scaled_qimage_from_cache_or_read(path)
                if qimg is None:
                    self._img_lbl.setText("Nelze načíst obrázek.")
                    return
            
                # Zajisti, že i při cache bude obrázek vždy komplet vidět na AKTUÁLNÍ obrazovce
                try:
                    scr = self.screen() or QApplication.primaryScreen()
                except Exception:
                    scr = QApplication.primaryScreen()
                geom = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
                max_w = max(200, geom.width()  - 120)
                max_h = max(200, geom.height() - 260)
                if qimg.width() > max_w or qimg.height() > max_h:
                    qimg = qimg.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
                self._scaled_pixmap = QPixmap.fromImage(qimg)
                self._img_lbl.setPixmap(self._scaled_pixmap)
            
                # Velikost okna také omez na obrazovku (bez překročení)
                new_w = min(self._scaled_pixmap.width() + 40,  geom.width()  - 20)
                new_h = min(self._scaled_pixmap.height() + 140, geom.height() - 20)
                self.resize(new_w, new_h)
            
                # Reset interakčních stavů
                if self._rubber:
                    self._rubber.hide()
                    self._rubber = None
                self._origin = None
                self._mode = "idle"
                self._resize_handle = None
                self._anchor = None
                self._move_offset = None
                self._img_lbl.setCursor(Qt.ArrowCursor)
            
                # Prefetch následujících
                nxts = []
                if self.current_index + 1 < len(self.image_paths): nxts.append(self.image_paths[self.current_index + 1])
                if self.current_index + 2 < len(self.image_paths): nxts.append(self.image_paths[self.current_index + 2])
                prefetch_paths(nxts, how_many=len(nxts))
    
            # pixmap bounds
            def _pixmap_rect_in_label(self) -> QRect:
                if not self._img_lbl.pixmap() or self._img_lbl.pixmap().isNull():
                    return QRect()
                pm = self._img_lbl.pixmap().size()
                lab = self._img_lbl.size()
                x = (lab.width() - pm.width()) // 2
                y = (lab.height() - pm.height()) // 2
                return QRect(x, y, pm.width(), pm.height())
    
            @staticmethod
            def _square_from_points(p0: QPoint, p1: QPoint) -> QRect:
                dx = p1.x() - p0.x(); dy = p1.y() - p0.y()
                side = min(abs(dx), abs(dy))
                rx = p0.x() + (side if dx >= 0 else -side)
                ry = p0.y() + (side if dy >= 0 else -side)
                return QRect(min(p0.x(), rx), min(p0.y(), ry), side, side)
    
            def _hit_corner(self, p_lbl: QPoint) -> str | None:
                if not self._rubber: return None
                r = self._rubber.geometry(); hr = 8
                tl = QRect(r.topLeft() - QPoint(hr, hr), QSize(2*hr, 2*hr))
                tr = QRect(QPoint(r.right()-hr+1, r.top()-hr), QSize(2*hr, 2*hr))
                bl = QRect(QPoint(r.left()-hr, r.bottom()-hr+1), QSize(2*hr, 2*hr))
                br = QRect(r.bottomRight() - QPoint(hr-1, hr-1), QSize(2*hr, 2*hr))
                if tl.contains(p_lbl): return "tl"
                if tr.contains(p_lbl): return "tr"
                if bl.contains(p_lbl): return "bl"
                if br.contains(p_lbl): return "br"
                return None
    
            def _update_cursor(self, p_lbl: QPoint):
                if not self._rubber or self._rubber.geometry().isNull():
                    self._img_lbl.setCursor(Qt.ArrowCursor); return
                hit = self._hit_corner(p_lbl)
                if hit in ("tl", "br"): self._img_lbl.setCursor(Qt.SizeFDiagCursor)
                elif hit in ("tr", "bl"): self._img_lbl.setCursor(Qt.SizeBDiagCursor)
                elif self._rubber.geometry().contains(p_lbl): self._img_lbl.setCursor(Qt.SizeAllCursor)
                else: self._img_lbl.setCursor(Qt.ArrowCursor)
    
            def _square_from_anchor(self, anchor: QPoint, p: QPoint, handle: str) -> QRect:
                pm_rect = self._pixmap_rect_in_label()
                side = max(abs(p.x() - anchor.x()), abs(p.y() - anchor.y()))
                side = max(self._MIN_SIDE, side)
                if handle == "br":
                    side = min(side, min(pm_rect.right() - anchor.x(), pm_rect.bottom() - anchor.y()))
                    return QRect(anchor, QSize(side, side))
                elif handle == "tl":
                    side = min(side, min(anchor.x() - pm_rect.left(), anchor.y() - pm_rect.top()))
                    return QRect(QPoint(anchor.x()-side, anchor.y()-side), QSize(side, side))
                elif handle == "tr":
                    side = min(side, min(pm_rect.right() - anchor.x(), anchor.y() - pm_rect.top()))
                    return QRect(QPoint(anchor.x(), anchor.y()-side), QSize(side, side))
                elif handle == "bl":
                    side = min(side, min(anchor.x() - pm_rect.left(), pm_rect.bottom() - anchor.y()))
                    return QRect(QPoint(anchor.x()-side, anchor.y()), QSize(side, side))
                return QRect()
    
            def mousePressEvent(self, ev):
                if ev.button() != Qt.LeftButton: return
                if not self._img_lbl.pixmap() or self._img_lbl.pixmap().isNull(): return
                p = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                lbl_p = self._img_lbl.mapFrom(self, p)
                pm_rect = self._pixmap_rect_in_label()
                if not pm_rect.contains(lbl_p): return
    
                if self._rubber and not self._rubber.geometry().isNull():
                    hit = self._hit_corner(lbl_p)
                    if hit is not None:
                        r = self._rubber.geometry()
                        anchors = {"tl": r.bottomRight(),"tr": r.bottomLeft(),"bl": r.topRight(),"br": r.topLeft()}
                        self._resize_handle = hit; self._anchor = anchors[hit]; self._mode = "resizing"; return
                    elif self._rubber.geometry().contains(lbl_p):
                        self._mode = "moving"; self._move_offset = lbl_p - self._rubber.geometry().topLeft(); return
    
                self._origin = lbl_p
                if not self._rubber: self._rubber = QRubberBand(QRubberBand.Rectangle, self._img_lbl)
                self._rubber.setGeometry(QRect(lbl_p, QSize(1,1))); self._rubber.show(); self._mode = "creating"
    
            def mouseMoveEvent(self, ev):
                p = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                lbl_p = self._img_lbl.mapFrom(self, p)
    
                if self._mode == "creating" and self._origin is not None and self._rubber:
                    rect = self._square_from_points(self._origin, lbl_p)
                    rect = rect.intersected(self._pixmap_rect_in_label())
                    if rect.width() < self._MIN_SIDE or rect.height() < self._MIN_SIDE:
                        side = max(self._MIN_SIDE, min(rect.width(), rect.height()))
                        ox, oy = self._origin.x(), self._origin.y()
                        nx = ox + (side if lbl_p.x() >= ox else -side)
                        ny = oy + (side if lbl_p.y() >= oy else -side)
                        rect = QRect(min(ox, nx), min(oy, ny), side, side)
                        rect = rect.intersected(self._pixmap_rect_in_label())
                    self._rubber.setGeometry(rect); self._update_cursor(lbl_p); return
    
                if self._mode == "moving" and self._rubber and self._move_offset is not None:
                    pm_rect = self._pixmap_rect_in_label(); r = self._rubber.geometry()
                    top_left = lbl_p - self._move_offset
                    x = max(pm_rect.left(), min(top_left.x(), pm_rect.right() - r.width() + 1))
                    y = max(pm_rect.top(),  min(top_left.y(), pm_rect.bottom() - r.height() + 1))
                    self._rubber.setGeometry(QRect(QPoint(x, y), r.size())); self._update_cursor(lbl_p); return
    
                if self._mode == "resizing" and self._rubber and self._anchor is not None and self._resize_handle:
                    rect = self._square_from_anchor(self._anchor, lbl_p, self._resize_handle)
                    self._rubber.setGeometry(rect); self._update_cursor(lbl_p); return
    
                self._update_cursor(lbl_p)
    
            def mouseReleaseEvent(self, ev):
                if ev.button() != Qt.LeftButton: return
                self._mode = "idle"; self._resize_handle = None; self._anchor = None; self._move_offset = None
    
            # výběr -> souřadnice originálu
            def _selection_to_original_box(self):
                if not self._rubber or self._rubber.geometry().isNull() or self._pil_img is None: return None
                sel = self._rubber.geometry(); pm_rect = self._pixmap_rect_in_label()
                if pm_rect.width() == 0 or pm_rect.height() == 0: return None
                nx = (sel.x() - pm_rect.x()) / pm_rect.width()
                ny = (sel.y() - pm_rect.y()) / pm_rect.height()
                nw = sel.width() / pm_rect.width()
                nh = sel.height() / pm_rect.height()
                ow, oh = self._pil_img.size
                x0 = max(0, int(round(nx * ow))); y0 = max(0, int(round(ny * oh)))
                x1 = min(ow, int(round((nx + nw) * ow))); y1 = min(oh, int(round((ny + nh) * oh)))
                if x1 - x0 <= 0 or y1 - y0 <= 0: return None
                return (x0, y0, x1, y1)
    
            # umlčení watcheru (ref-count)
            def _begin_fs_quiet(self):
                try:
                    w = self._parent_win
                    if not hasattr(w, "_crop_fs_quiet_count"):
                        w._crop_fs_quiet_count = 0
                    w._crop_fs_quiet_count += 1
                    w._suspend_fs_events = True
                    try:
                        w._dir_watcher.blockSignals(True)
                    except Exception:
                        pass
                except Exception:
                    pass
    
            def _end_fs_quiet(self):
                try:
                    w = self._parent_win
                    if hasattr(w, "_crop_fs_quiet_count") and w._crop_fs_quiet_count > 0:
                        w._crop_fs_quiet_count -= 1
                    if getattr(w, "_crop_fs_quiet_count", 0) <= 0:
                        try:
                            w._dir_watcher.blockSignals(False)
                        except Exception:
                            pass
                        w._suspend_fs_events = False
                except Exception:
                    pass
    
            # zachování časů (mtime/atime) + best-effort creation time na macOS
            def _preserve_file_times(self, src: Path, dst: Path):
                try:
                    st = os.stat(src)
                    os.utime(dst, (st.st_atime, st.st_mtime))
                    if sys.platform == "darwin":
                        try:
                            ctime = getattr(st, "st_birthtime", None)
                            if ctime:
                                ts = datetime.fromtimestamp(ctime).strftime("%m/%d/%Y %H:%M:%S")
                                subprocess.run(["/usr/bin/SetFile", "-d", ts, str(dst)], check=False)
                        except Exception:
                            pass
                except Exception:
                    pass
    
            # uložit ořez na pozadí, umlčet watcher; po dokončení jen označ, přestavba seznamu proběhne až po zavření okna
            def crop_image(self):
                box = self._selection_to_original_box()
                if not box:
                    QMessageBox.information(self, "Ořez", "Vyber čtvercový výběr tažením myši – lze i posouvat/roztahovat za rohy.")
                    return
                src_path = Path(self.image_paths[self.current_index])
                dst_path = Path(OREZY_DIR, src_path.name)
    
                self._begin_fs_quiet()
    
                def _save_worker():
                    try:
                        from PIL import Image
                        pil = self._pil_img if self._pil_img is not None else Image.open(str(src_path))
                        cropped = pil.crop(box)
    
                        save_kwargs = {}
                        exif_bytes = self._pil_exif
                        if exif_bytes:
                            try:
                                import piexif
                                exif_dict = piexif.load(exif_bytes)
                                if piexif.ImageIFD.Orientation in exif_dict.get("0th", {}):
                                    exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
                                save_kwargs["exif"] = piexif.dump(exif_dict)
                            except Exception:
                                save_kwargs["exif"] = exif_bytes
                        if self._pil_icc:
                            save_kwargs["icc_profile"] = self._pil_icc
                        if dst_path.suffix.lower() in {".jpg", ".jpeg"}:
                            save_kwargs.setdefault("quality", 95)
                            save_kwargs.setdefault("subsampling", "keep")
    
                        dst_path.parent.mkdir(parents=True, exist_ok=True)
                        cropped.save(str(dst_path), **save_kwargs)
    
                        self._preserve_file_times(src_path, dst_path)
    
                        num = number_from_name(src_path.name) or ""
                        QTimer.singleShot(0, lambda: emitter.saved.emit(num))
                    except Exception as e:
                        QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Chyba", f"Ořez selhal:\n{e}"))
                    finally:
                        QTimer.singleShot(0, self._end_fs_quiet)
    
                threading.Thread(target=_save_worker, daemon=True).start()
    
                # hned přejít na další NEOŘEZANOU (bez čekání na I/O)
                next_idx = None
                if self._get_next_uncropped_idx:
                    next_idx = self._get_next_uncropped_idx(self.current_index)
                if next_idx is not None:
                    self.current_index = next_idx
                    self.load_current()
    
        # === Otevření náhledu / po zavření *plný rescan* pro korektní seznam ===
        def open_preview_at(idx: int | None):
            if idx is None or idx < 0 or idx >= lst.count():
                return
            paths = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())]
            dlg = _CropPreviewDialog(
                paths, idx, parent=self,
                on_cropped=mark_cropped_by_number,
                get_next_uncropped_idx=lambda cur: next_uncropped_after(cur)
            )
            dlg.exec()
            # >>> PO ZAVŘENÍ: proveď asynchronní rescan a přestav zobrazení dle filtru
            rescan_async()
    
        # === Akce / signály ===
        def open_selected():
            idx = lst.currentRow()
            if idx < 0:
                idx = first_uncropped_index()
            open_preview_at(idx)
    
        lst.itemDoubleClicked.connect(lambda *_: open_selected())
        shortcut_open = QShortcut(QKeySequence(Qt.Key_Space), lst)
        shortcut_open.setContext(Qt.WidgetShortcut)
        shortcut_open.activated.connect(open_selected)
    
        # Změna filtru -> jen přestav z aktuálního modelu (bez I/O)
        chk_hide.stateChanged.connect(rebuild_list_from_model)
    
        btn_refresh.clicked.connect(rescan_async)
        btn_quick_crop.clicked.connect(lambda: open_preview_at(first_uncropped_index()))
    
        # první naplnění (asynchronně)
        rescan_async()
        return page
    
    def _build_naming_format_html(self) -> str:
        """
        Vrátí HTML s popisem aktuálního formátu názvů souborů.
        - Zahrnuje část IDLokace v názvu souboru.
        - Zahrnuje aktuální regex (pokud je dostupný).
        - Pravidla odpovídají logice kontroly (prefix před prvním '+').
        """
        id_lokace = self._get_current_id_lokace()
    
        # Získání regexu z existujících zdrojů v okně (použijte vaše pole/metody, pokud máte jiné)
        regex = None
        if hasattr(self, "naming_regex_string") and isinstance(self.naming_regex_string, str):
            regex = (self.naming_regex_string or "").strip() or None
        elif hasattr(self, "_current_naming_regex") and callable(getattr(self, "_current_naming_regex")):
            try:
                regex = getattr(self, "_current_naming_regex")() or None
            except Exception:
                regex = None
        elif hasattr(self, "_get_current_name_regex") and callable(getattr(self, "_get_current_name_regex")):
            try:
                pat = getattr(self, "_get_current_name_regex")()
                regex = pat.pattern if pat is not None else None
            except Exception:
                regex = None
    
        # Popis pravidel
        rules_html = """
            <ul>
                <li>Název se skládá z <b>prefixu</b> (obvykle číselný identifikátor) následovaného znakem <code>+</code> a popisem.</li>
                <li><b>Shoda souborů</b> mezi <i>Originály</i> a <i>Ořezy</i> se ověřuje podle části <b>před prvním</b> znakem <code>+</code>.</li>
                <li><b>Formát názvu</b> musí odpovídat aktuálnímu regex nastavení (je-li aktivní).</li>
            </ul>
        """
    
        # Příklad s IDLokace v názvu (pokud jej známe)
        sample_id = id_lokace or "IDLokace"
        example_html = f"""
            <p><b>Příklad názvu:</b><br>
            <code>001+{sample_id}+popis-obrazku.jpg</code></p>
        """
    
        regex_html = (f"""
            <p><b>Aktuální regex:</b><br>
            <code style="white-space:pre-wrap">{regex}</code></p>
        """ if regex else "<p><i>Regex není aktuálně nastaven.</i></p>")
    
        idlok_html = (f"<p><b>IDLokace:</b> <code>{id_lokace}</code></p>" if id_lokace else "")
    
        return f"""
            <div>
                <h3 style="margin-top:0;">Formát názvů souborů</h3>
                {idlok_html}
                {rules_html}
                {example_html}
                {regex_html}
                <p style="color:#666;">Okno lze zavřít zkratkou <b>Cmd+W</b> (resp. <b>Ctrl+W</b>) nebo tlačítkem „Zavřít“.</p>
            </div>
        """
    
    
    def _get_current_id_lokace(self) -> str | None:
        """
        Vrátí aktuální 'IDLokace' z dostupných atributů.
        Pokud hodnotu ukládáte jinde (např. QLineEdit), doplňte zde.
        """
        candidates = [
            "id_lokace", "IDLokace", "idLokace", "current_location_id",
            "lokace_id", "location_id", "renaming_location_id",
        ]
        for name in candidates:
            val = getattr(self, name, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (int, float)):
                return str(val)
        # Příklad čtení z QLineEdit (odkomentujte, pokud existuje):
        # if hasattr(self, "le_id_lokace") and self.le_id_lokace.text().strip():
        #     return self.le_id_lokace.text().strip()
        return None
        
    def _ensure_selection_indicator_panel(self) -> None:
        """
        Jednorázově vloží panel s indikátorem výběru do layoutu záložky 'Přejmenování',
        hned pod (nebo nad) ostatní status panely. Panel se aktualizuje přes signály výběru.
        """
        if getattr(self, "_ren_selection_panel_initialized", False):
            return
        if not hasattr(self, "ren_tree") or self.ren_tree is None:
            return
    
        # Najdi parent/layout, kam je vložen ren_tree
        parent_widget = self.ren_tree.parentWidget()
        target_layout = parent_widget.layout() if parent_widget and parent_widget.layout() else self.layout()
        if target_layout is None:
            return  # bezpečný no-op
    
        # Vytvoř a vlož panel
        self._ren_selection_indicator = SelectionIndicator(title="Výběr v přejmenování", parent=parent_widget or self)
        try:
            # preferenčně pod panel parity; pokud jste jej vkládali na index 0,
            # dáme výběrový panel hned za něj (na index 1). Když to nevyjde, prostě add.
            target_layout.insertWidget(1, self._ren_selection_indicator)
        except Exception:
            target_layout.addWidget(self._ren_selection_indicator)
    
        # Zajisti, že strom podporuje multiselect
        try:
            from PySide6.QtWidgets import QAbstractItemView
            self.ren_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        except Exception:
            pass
    
        # Napoj signály výběru a modelu
        sel_model = self.ren_tree.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._update_selection_indicator_from_selection)
    
        if hasattr(self, "ren_model") and self.ren_model is not None:
            try:
                self.ren_model.modelReset.connect(self._update_selection_indicator_from_selection)
                self.ren_model.rowsInserted.connect(lambda *_: self._update_selection_indicator_from_selection())
                self.ren_model.rowsRemoved.connect(lambda *_: self._update_selection_indicator_from_selection())
            except Exception:
                pass
    
        # Inicializace hodnot
        self._update_selection_indicator_from_selection()
        self._ren_selection_panel_initialized = True
    
    
    def _update_selection_indicator_from_selection(self) -> None:
        """
        Přečte aktuální výběr v ren_tree a pošle počty do SelectionIndicator.
        """
        if not hasattr(self, "_ren_selection_indicator"):
            return
        files, dirs = self._extract_selection_counts()
        self._ren_selection_indicator.set_counts(files, dirs)
    
    
    def _extract_selection_counts(self) -> Tuple[int, int]:
        """
        Vrátí dvojici (files_count, dirs_count) pro aktuální výběr v ren_tree.
    
        Očekává, že model ukládá typ položky do role Qt.UserRole:
          - 'dir' pro složku
          - 'file' (nebo cokoliv jiného) pro soubor
        a absolutní cestu do role (Qt.UserRole + 1). Pokud role neexistují,
        fallback logika určí typ přes QFileInfo nebo podle konvence.
        """
        from PySide6.QtCore import Qt, QModelIndex
        files = 0
        dirs = 0
    
        if not hasattr(self, "ren_tree") or self.ren_tree is None:
            return (files, dirs)
    
        sel_model = self.ren_tree.selectionModel()
        if sel_model is None:
            return (files, dirs)
    
        indexes = sel_model.selectedRows()  # předpokládáme jeden sloupec pro hlavní jméno
        if not indexes:
            return (files, dirs)
    
        model = self.ren_tree.model()
        for idx in indexes:
            if not isinstance(idx, QModelIndex) or not idx.isValid():
                continue
            item_type = model.data(idx, Qt.UserRole)
            # Preferovaná role: 'dir' / 'file'
            if isinstance(item_type, str) and item_type.lower() == "dir":
                dirs += 1
                continue
            # Pokud role není nastavena, nebo není 'dir' -> ber jako soubor
            files += 1
    
        return (files, dirs)

    # === NEW: Pomocné metody ve WebPhotosWindow ===
    
    def _get_orig_and_crops_dirs(self) -> Tuple[Optional[Path], Optional[Path]]:
        """
        PEVNÉ NASTAVENÍ KOŘENŮ PRO KONTROLU:
        - Originály: /Users/safronus/.../Fotky pro web/Originály/
        - Ořezy:     /Users/safronus/.../Fotky pro web/Ořezy/
    
        Tyto cesty se používají pro PARITY kontrolu v záložce „Přejmenování“.
        Kontrola probíhá REKURZIVNĚ přes všechny podsložky (včetně dalších úrovní).
    
        Vrací dvojici (orig_dir, crops_dir) jako Path, nebo (None, None), pokud cesty neexistují.
        """
        from pathlib import Path  # lokální import pro jasnost, modulu to nevadí
    
        orig_dir = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Originály")
        crops_dir = Path("/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Fotky pro web/Ořezy")
    
        # Volitelně zapiš do atributů instance (neovlivní stávající chování, jen zpřístupní pro další části UI/logiky).
        self._orig_dir = orig_dir
        self._crops_dir = crops_dir
    
        # Bezpečnost: vrať None, pokud některá z cest neexistuje (worker to ošetří a zobrazí „neutral/neshoda“).
        if not orig_dir.exists():
            try:
                print(f"[WebPhotos] Upozornění: složka 'Originály' neexistuje: {orig_dir}")
            except Exception:
                pass
            return (None, crops_dir if crops_dir.exists() else None)
    
        if not crops_dir.exists():
            try:
                print(f"[WebPhotos] Upozornění: složka 'Ořezy' neexistuje: {crops_dir}")
            except Exception:
                pass
            return (orig_dir, None)
    
        return (orig_dir, crops_dir)
    
    def _get_current_name_regex(self) -> Optional[re.Pattern]:
        """
        Vrátí kompilovaný regex podle aktuálního formátu názvů, jak je nyní nastaveno v okně.
        - Pokud už máte v okně nějaké nastavení / textové pole s regexem, přečtěte jej zde.
        - Jinak vraťte None => formát se nebude vyhodnocovat jako chyba.
        """
        # Příklad: pokud máte někde self.naming_regex_string nebo metodu self._current_naming_regex()
        pattern_str = None
    
        # Preferovaná místa:
        if hasattr(self, "naming_regex_string") and isinstance(self.naming_regex_string, str):
            pattern_str = self.naming_regex_string.strip() or None
        elif hasattr(self, "_current_naming_regex") and callable(getattr(self, "_current_naming_regex")):
            try:
                pattern_str = self._current_naming_regex() or None
            except Exception:
                pattern_str = None
    
        if not pattern_str:
            return None  # Bez regexu nepovažuj za chybu
    
        try:
            return re.compile(pattern_str)
        except re.error:
            # Když je regex chybně zadaný, raději potlačíme chybu a budeme "OK"
            return None
        
    # --- uvnitř třídy WebPhotosWindow ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # udrž výšky editorů dle řádků při každém resize
        try:
            self._apply_json_editor_split_sizes()
        except Exception:
            pass


    # --- UI STAVEBNICE ---

    def _center_tabs_visually(self):
        """Vycentrování TabBaru: do levého i pravého rohu vloží expandující 'spacery'."""
        left_spacer = QWidget()
        left_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_spacer = QWidget()
        right_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.tabs.setCornerWidget(left_spacer, Qt.TopLeftCorner)
        self.tabs.setCornerWidget(right_spacer, Qt.TopRightCorner)

    # ---------- TAB 1: Overview ----------
    def _build_check_tab(self) -> QWidget:
        """Kompatibilní alias: starší kód volal _build_check_tab, 
        v aktuální verzi je metoda pojmenována _build_overview_tab."""
        return self._build_overview_tab()

    def _build_overview_tab(self) -> QWidget:
        """
        Záložka 1: základní statistiky Ořezy/Originály + souhrnné indikátory
        (zrcadlí stav ze záložky Přejmenování) včetně času poslední kontroly.
        """
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
    
        # Akční řádek: pouze modal s formátem
        actions_row = QHBoxLayout()
        actions_row.addStretch(1)
        self.btn_show_format = QPushButton("Ukázat formát názvu")
        self.btn_show_format.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.btn_show_format.clicked.connect(self._show_format_modal)
        actions_row.addWidget(self.btn_show_format, 0, Qt.AlignRight)
        layout.addLayout(actions_row)
    
        # Sekce s jednoduchými počty (zůstává)
        section = QGroupBox("🧪 Kontrola stavu souborů")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(10, 10, 10, 10)
        section_layout.setSpacing(10)
    
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
    
        row = 0
        # Ořezy
        mini_left = self._folder_header_widget("Ořezy", str(OREZY_DIR))
        mini_total, mini_valid, mini_invalid = self._make_value_labels()
        grid.addWidget(mini_left,  row, 0)
        grid.addWidget(self._stat_tile(self.style().standardIcon(QStyle.SP_FileIcon),          "Počet",   mini_total),   row, 1)
        grid.addWidget(self._stat_tile(self.style().standardIcon(QStyle.SP_DialogApplyButton), "Správně", mini_valid),   row, 2)
        grid.addWidget(self._stat_tile(self.style().standardIcon(QStyle.SP_MessageBoxWarning), "Špatně",  mini_invalid), row, 3)
        self.lbl_total_a, self.lbl_valid_a, self.lbl_invalid_a = mini_total, mini_valid, mini_invalid
    
        row += 1
        # Originály
        orig_left = self._folder_header_widget("Originály", str(ORIGINALS_DIR))
        orig_total, orig_valid, orig_invalid = self._make_value_labels()
        grid.addWidget(orig_left,  row, 0)
        grid.addWidget(self._stat_tile(self.style().standardIcon(QStyle.SP_FileIcon),          "Počet",   orig_total),   row, 1)
        grid.addWidget(self._stat_tile(self.style().standardIcon(QStyle.SP_DialogApplyButton), "Správně", orig_valid),   row, 2)
        grid.addWidget(self._stat_tile(self.style().standardIcon(QStyle.SP_MessageBoxWarning), "Špatně",  orig_invalid), row, 3)
        self.lbl_total_b, self.lbl_valid_b, self.lbl_invalid_b = orig_total, orig_valid, orig_invalid
    
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
    
        section_layout.addLayout(grid)
        layout.addWidget(section)
    
        # --- NOVÁ SOUHRNNÁ SEKCE: zrcadlo indikátorů z Přejmenování ---
        summary = QGroupBox("Souhrnné indikátory")
        sum_lay = QVBoxLayout(summary)
        sum_lay.setContentsMargins(10, 10, 10, 10)
        sum_lay.setSpacing(8)
    
        # Zrcadlené labely (HTML + stejný styl jako v Přejmenování)
        self.chk_counts = QLabel("—");           self.chk_counts.setWordWrap(True)
        self.chk_name_mismatch = QLabel("—");    self.chk_name_mismatch.setWordWrap(True)
        self.chk_format_errors = QLabel("—");    self.chk_format_errors.setWordWrap(True)
        self.chk_format_ok = QLabel("—");        self.chk_format_ok.setWordWrap(True)
        self.chk_range_missing = QLabel("—");    self.chk_range_missing.setTextFormat(Qt.RichText); self.chk_range_missing.setWordWrap(True)
        self.chk_last_check = QLabel("—");       self.chk_last_check.setTextFormat(Qt.RichText); self.chk_last_check.setWordWrap(True); self.chk_last_check.setStyleSheet("color:#666;")
    
        sum_lay.addWidget(self.chk_counts)
        sum_lay.addWidget(self.chk_name_mismatch)
        sum_lay.addWidget(self.chk_format_errors)
        sum_lay.addWidget(self.chk_format_ok)
        sum_lay.addWidget(self.chk_range_missing)
        sum_lay.addWidget(self.chk_last_check)
    
        layout.addWidget(summary)
        layout.addStretch(1)
        return w

    def _hdr_label(self, text: str) -> QLabel:
        l = QLabel(text)
        f = QFont()
        f.setBold(True)
        l.setFont(f)
        l.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        l.setStyleSheet("color: rgba(0,0,0,170);")
        return l

    def _make_value_labels(self) -> Tuple[QLabel, QLabel, QLabel]:
        val_font = QFont()
        val_font.setBold(True)
        val_font.setPointSize(val_font.pointSize() + 2)

        def _v():
            lab = QLabel("-")
            lab.setFont(val_font)
            lab.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            return lab

        return _v(), _v(), _v()

    def _folder_header_widget(self, title: str, tooltip_path: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(self.style().standardIcon(QStyle.SP_DirIcon).pixmap(20, 20))
        icon_lbl.setFixedSize(20, 20)

        title_lbl = QLabel(title)
        tf = QFont()
        tf.setBold(True)
        title_lbl.setFont(tf)
        title_lbl.setToolTip(tooltip_path)

        h.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        h.addWidget(title_lbl, 0, Qt.AlignVCenter)
        return w

    def _stat_tile(self, qicon: QIcon, title: str, value_label: QLabel) -> QWidget:
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        w.setMinimumWidth(140)
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qicon.pixmap(18, 18))
        icon_lbl.setFixedSize(18, 18)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        colon = QLabel(":")
        colon.setAlignment(Qt.AlignVCenter)

        value_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        h.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        h.addWidget(title_lbl, 0, Qt.AlignVCenter)
        h.addWidget(colon, 0, Qt.AlignVCenter)
        h.addWidget(value_label, 0, Qt.AlignVCenter)

        w.setStyleSheet("""
            QWidget {
                border: 1px solid rgba(0,0,0,40);
                border-radius: 6px;
            }
        """)
        return w

    # --- Modal s ukázkou formátu názvu ---

    @Slot()
    def _show_format_modal(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Formát názvu souboru")
        dlg.setModal(True)
        dlg.setMinimumWidth(560)
    
        v = QVBoxLayout(dlg)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
    
        info = QLabel(
            "<b>Formát (nově):</b><br>"
            "ČísloNálezu+ČísloLokace+IDLokace+[STAV]+[Anonymizován]+[Poznámka].HEIC<br><br>"
            "<b>Povinné:</b> ČísloNálezu, ČísloLokace (5 číslic), IDLokace.<br>"
            "<b>Volitelné (v uvedeném pořadí):</b> STAV → Anonymizován (ANO/NE) → Poznámka.<br>"
            "Oddělovač je znak '+'. Přípustné přípony: .HEIC (preferovaná), .jpg/.jpeg."
        )
        info.setWordWrap(True)
        v.addWidget(info)
    
        sample = QGroupBox("Příklady")
        sv = QVBoxLayout(sample)
        ex = QLabel(
            # pouze 3 povinné části
            "17+00001+PARK_A.HEIC<br>"
            # + STAV
            "128+01234+BRNO_STRED+NOVY.HEIC<br>"
            # + STAV + ANO/NE
            "42+00007+ID123+ANONYM+ANO.HEIC<br>"
            # všech 6 částí
            "99+00003+LES_U_RYBNIKU+ZKONTROL+NE+nocni_foto.jpg"
        )
        ex.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sv.addWidget(ex)
        v.addWidget(sample)
    
        btns = QDialogButtonBox(QDialogButtonBox.Ok, parent=dlg)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
    
        dlg.exec()

    # ---------- TAB 2: JSON Settings ----------
    
    def _on_json_lookup_clicked(self):
        """Vyvolá dialog s detaily JSON přiřazení pro zadané ID fotky."""
        try:
            text = (self.ed_json_lookup.text() if hasattr(self, "ed_json_lookup") else "").strip()
            if not text:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Detail fotky", "Zadej číslo fotky (ID).")
                return
            # povolíme jen čísla
            if not text.isdigit():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Detail fotky", "Číslo fotky musí být celé číslo.")
                return
            fid = int(text)
            self._show_json_assignment_detail_dialog(fid)
        except Exception as e:
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Detail fotky", f"Nepodařilo se otevřít detail: {e}")
            except Exception:
                pass
            
    def _show_json_assignment_detail_dialog(self, fid: int):
        """
        Dialog s přehledem zařazení fotky do JSONů (konzistentní, dark-theme friendly).
        Všechny sekce mají stejný styl: nadpis → tabulka Klíč → Hodnota.
    
        Lokace (pro každou přiřazenou lokaci samostatná karta):
          - Číslo lokace (z JSONu),
          - Název lokace = část názvu souboru mapy před prvním '+',
          - Popis lokace = část mezi prvním a druhým '+',
          - Soubor (plný název),
          - Cesta (absolutní).
        Dále karta „Detail“: Stavy, Anonymizace, Poznámka – také ve formátu K/V.
        Dialog je 2× širší a ~ o 50 % vyšší (1280×810).
        """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox, QTextBrowser
        import html, os, re
    
        # --- Data z editorů
        lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
    
        # --- Lokace přiřazené k danému fid (tak, jak jsou uvedeny v JSONu)
        assigned_locs: list[str] = []
        for idlok, spec in (lokace or {}).items():
            try:
                if self._parse_ranges_spec(spec, fid):
                    assigned_locs.append(str(idlok))
            except Exception:
                pass
    
        # --- Mapy a lookup (pro název/cestu k mapě)
        try:
            maps = self._get_available_location_maps_from_dir() or []
        except Exception:
            maps = []
    
        def _esc(s: str) -> str:
            return html.escape("" if s is None else str(s))
    
        def _norm_key(k: str) -> str:
            try:
                return self._normalize_cislolok(str(k))
            except Exception:
                return str(k).strip()
    
        def _parse_map_filename(fname: str) -> dict:
            """Název = před 1. '+', Popis = mezi 1. a 2. '+'. Vrací i původní jméno a ext."""
            base, ext = os.path.splitext(fname or "")
            parts = base.split("+") if "+" in base else [base]
            name_first = (parts[0] or "").strip() if parts else ""
            desc = (parts[1].strip() if len(parts) >= 2 else "")
            return {"name_first": name_first, "desc": desc, "full": fname or "", "ext": ext}
    
        norm_to_file: dict[str, dict] = {}
        for md in maps:
            c5 = md.get("cislolok5", None)
            key_norm = None
            if c5 is not None:
                try:
                    key_norm = self._normalize_cislolok(str(c5))
                except Exception:
                    key_norm = None
            if key_norm:
                norm_to_file[key_norm] = {
                    "soubor": md.get("filename") or "",
                    "cesta": md.get("absolute") or "",
                }
    
        # --- Stavy (všechny odpovídající)
        assigned_states: list[str] = []
        for s, spec in (stavy or {}).items():
            try:
                if self._parse_ranges_spec(spec, fid):
                    assigned_states.append(str(s))
            except Exception:
                pass
    
        # --- Anonymizace
        anonym_spec = (anonym or {}).get("ANONYMIZOVANE", [])
        try:
            is_anon = self._parse_ranges_spec(anonym_spec, fid)
        except Exception:
            is_anon = False
    
        # --- Poznámka
        note_text = (poznamky or {}).get(str(fid), "")
    
        # ============ HTML ============
    
        # Lokace – pro každou lokaci konzistentní karta s K/V tabulkou
        loc_cards: list[str] = []
        if assigned_locs:
            for k_display in assigned_locs:
                k_norm = _norm_key(k_display)  # jen pro lookup souboru
                file_meta = norm_to_file.get(k_norm, {"soubor": "", "cesta": ""})
                parsed = _parse_map_filename(file_meta["soubor"])
    
                loc_cards.append(f"""
                <section class="card">
                  <div class="section-title">Lokace</div>
                  <table class="kv">
                    <tr><td class="k">Číslo lokace</td><td class="v">#{_esc(k_display)}</td></tr>
                    <tr><td class="k">Název lokace</td><td class="v">{_esc(parsed['name_first'] or '—')}</td></tr>
                    <tr><td class="k">Popis lokace</td><td class="v">{_esc(parsed['desc'] or '—')}</td></tr>
                    <tr><td class="k">Soubor</td><td class="v">{_esc(file_meta['soubor'] or '—')}</td></tr>
                    <tr><td class="k">Cesta</td><td class="v"><code>{_esc(file_meta['cesta'] or '—')}</code></td></tr>
                  </table>
                </section>
                """)
        else:
            loc_cards.append("""
            <section class="card">
              <div class="section-title">Lokace</div>
              <div class="muted">Nepřiřazena</div>
            </section>
            """)
        loc_html = "\n".join(loc_cards)
    
        # Detail (Stavy / Anonymizace / Poznámka) – stejný K/V layout
        if assigned_states:
            states_texts = []
            for s in sorted(set(assigned_states)):
                try:
                    em = self._state_emoji(s)
                except Exception:
                    em = ""
                states_texts.append(f"{_esc(em)} {_esc(s)}")
            states_value = " • ".join(states_texts)
        else:
            states_value = "Žádné"
    
        anon_value = "🕶️ Ano" if is_anon else "— Ne"
        if note_text:
            note_value = f"<pre class='pre-note'>{_esc(note_text)}</pre>"
        else:
            note_value = "Žádná"
    
        detail_card = f"""
        <section class="card">
          <div class="section-title">Detail</div>
          <table class="kv">
            <tr><td class="k">Stavy</td><td class="v">{states_value}</td></tr>
            <tr><td class="k">Anonymizace</td><td class="v">{anon_value}</td></tr>
            <tr><td class="k">Poznámka</td><td class="v">{note_value}</td></tr>
          </table>
        </section>
        """
    
        # CSS – jednotné barvy, žádná „náhodná“ pozadí, vysoký kontrast v dark theme
        css = """
        <style>
          .wrap { font-family: system-ui, Segoe UI, Arial; font-size: 14px; color: #e5e7eb; }
          .title { margin: 0 0 12px 0; font-weight: 700; font-size: 16px; color: #f3f4f6; }
    
          .card {
            border: 1px solid #3f3f46;   /* konzistentní rámeček */
            border-radius: 10px;
            padding: 12px;
            margin: 12px 0;
            background: transparent;     /* žádné náhodné pozadí */
          }
    
          .section-title {
            margin: 0 0 8px 0;
            font-weight: 600;
            color: #f3f4f6;              /* stejná barva nadpisů všude */
          }
    
          .kv { width: 100%; border-collapse: collapse; table-layout: fixed; }
          .kv .k { width: 200px; color: #a1a1aa; padding: 6px 8px; vertical-align: top; }
          .kv .v { padding: 6px 8px; color: #e5e7eb; word-break: break-word; }
    
          code {
            color: #e5e7eb;
            background: transparent;
            border: 1px solid #3f3f46;
            border-radius: 6px;
            padding: 1px 6px;
          }
    
          .muted { color: #9ca3af; }
          .pre-note { white-space: pre-wrap; margin: 0; font-size: 13px; color: #e5e7eb; }
        </style>
        """
    
        html_doc = f"""
        {css}
        <div class="wrap">
          <div class="title">Foto ID {fid}</div>
    
          {loc_html}
          {detail_card}
        </div>
        """
    
        # --- Dialog (2× širší a +50 % vyšší)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Detail JSON – foto {fid}")
        lay = QVBoxLayout(dlg)
    
        view = QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setHtml(html_doc)
        lay.addWidget(view)
    
        btns = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
    
        dlg.resize(1280, 440)
        dlg.exec()

    def _build_json_tab(self) -> QWidget:
        """
        Vlevo: 4 editorové sekce (lokace, stavy, poznámky, anonymizace) v poměru 60/20/15/5
               – poměr je dynamicky udržován při změně velikosti okna.
        Vpravo: strom všech souborů v 'Originály' (rekurzivně), realtime indikace dle JSONů
                a souhrnná kontrola 'STAV bez poznámky'.
        """
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(10)
    
        # Horní akce
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_load = QPushButton("Načíst")
        self.btn_load.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.btn_load.clicked.connect(self._load_settings_into_editors)
        actions.addWidget(self.btn_load, 0, Qt.AlignRight)
    
        self.btn_save = QPushButton("Uložit")
        self.btn_save.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_save.clicked.connect(self._save_editors_to_settings)
        actions.addWidget(self.btn_save, 0, Qt.AlignRight)
    
        # --- Lookup fotky (ID -> detail JSONů) ---
        actions.addSpacing(12)
        lbl_lookup = QLabel("Detail fotky:")
        actions.addWidget(lbl_lookup, 0, Qt.AlignRight)
    
        self.ed_json_lookup = QLineEdit()
        self.ed_json_lookup.setPlaceholderText("Číslo fotky…")
        self.ed_json_lookup.setMaximumWidth(160)
        actions.addWidget(self.ed_json_lookup, 0, Qt.AlignRight)
    
        self.btn_json_lookup = QPushButton("Zobrazit")
        self.btn_json_lookup.clicked.connect(self._on_json_lookup_clicked)
        self.ed_json_lookup.returnPressed.connect(self._on_json_lookup_clicked)
        actions.addWidget(self.btn_json_lookup, 0, Qt.AlignRight)
    
        page_layout.addLayout(actions)
    
        # Hlavní splitter (levý editory / pravý strom)
        splitter = QSplitter(Qt.Horizontal, page)
        page_layout.addWidget(splitter, 1)
    
        # ---- Levý panel: 4 editory v poměru 60/20/15/5 ----
        hint_lokace = (
            "Formát JSON pro přiřazení lokací (bez 'default'):\n"
            "{ \"IDLokace\": [\"start-end\", \"cislo\", ...], ... }\n\n"
            "Příklad:\n"
            "{ \"36\": [\"13600-13680\", \"13681\"], \"8\": [\"13300-13301\"] }\n\n"
            "• Lze kombinovat intervaly i jednotlivá čísla.\n"
            "• Editor zobrazuje čísla řádků; klávesa Tab vloží 2 mezery."
        )
        hint_stavy = (
            "JSON pro Nastavení stavů:\n"
            "{ \"STAV\": [\"start-end\", \"cislo\", ...] }\n"
            "Povoleno: BEZFOTKY, BEZGPS, BEZLOKACE, DAROVANY, LOKACE-NEEXISTUJE, ZTRACENY, NEUTRZEN, OBDAROVANY.\n\n"
            "Popis jednotlivých stavů:\n"
            "1. BEZFOTKY -> znamená, že nález nemá fotku, ale je fyzicky vylisován a katalogizován, má lokaci ale né GPS souřadnice, čas není přesny a musí mít svou poznámku\n"
            "2. BEZGPS -> vše má, datum i čas, lokaci i fotku, ale nemá GPS souřadnice\n"
            "3. BEZLOKACE -> nemá lokaci, nemá GPS souřadnice, má datum a čas a fotku\n"
            "4. DAROVANY -> vše má, jen je fyzicky darován jiné osobě -> popsané v rámci poznámky.\n"
            "5. LOKACE-NEEXISTUJE -> všechno má, ale lokační mapa ukazuje na místo, které už neexistuje\n"
            "6. ZTRACENY -> má fotku, datum a čas, souřadnice, ale fyzicky jsem ho ztratil, viz popis poznámky\n"
            "7. NEUTRZEN -> nemá fotku nálezu, nemá GPS souřadnice, našel jsem starší vylisovaný čtyřlístek. Poznámka ohledně místa nálezu - kniha\n"
            "8. OBDAROVANY -> od někoho jsem dostal, obvykle nemá souřadnice, ani datum a čas, ani lokaci, jen poznámku"
        )
        hint_poznamky = (
            "Poznámky ve formátu JSON: { \"ČísloNálezu\": \"text poznámky\" }."
        )
        hint_anonym = (
            "Nastavení anonymizace ve formátu JSON:\n"
            "{ \"ANONYMIZOVANE\": [\"start-end\", \"cislo\", ...] }"
        )
    
        self.gb_lokace, self.ed_lokace   = self._make_editor_section("🗺️ JSON konfigurace lokací",     hint_lokace,  min_height=200)
        self.gb_stavy,  self.ed_stavy    = self._make_editor_section("⚙️ JSON Nastavení stavů",         hint_stavy,   min_height=120)
        self.gb_pozn,   self.ed_poznamky = self._make_editor_section("📝 JSON poznámky",                 hint_poznamky,min_height=120)
        self.gb_an,     self.ed_anonym   = self._make_editor_section("🕶️ JSON Nastavení anonymizace",   hint_anonym,  min_height=80)
    
        # Vertikální splitter s udržovanými poměry (60/20/15/5)
        self._json_editor_ratios = [60, 20, 15, 5]  # v procentech
        self.json_editors_splitter = QSplitter(Qt.Vertical)
        self.json_editors_splitter.addWidget(self.gb_lokace)
        self.json_editors_splitter.addWidget(self.gb_stavy)
        self.json_editors_splitter.addWidget(self.gb_pozn)
        self.json_editors_splitter.addWidget(self.gb_an)
        self.json_editors_splitter.setChildrenCollapsible(False)
        self.json_editors_splitter.setMinimumWidth(950)
    
        # Realtime rebuild + AUTOSAVE při editaci JSONů
        for ed in (self.ed_lokace, self.ed_stavy, self.ed_poznamky, self.ed_anonym):
            ed.textChanged.connect(self._schedule_json_tree_rebuild)
            ed.textChanged.connect(self._schedule_json_autosave)
    
        splitter.addWidget(self.json_editors_splitter)
    
        # ---- Pravý panel: strom + souhrnná kontrola ----
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(2, 2, 2, 2)
        right_layout.setSpacing(6)
    
        # Souhrnná kontrola (STAV bez poznámky)
        self.lbl_consistency = QLabel("Kontrola: …")
        self.lbl_consistency.setStyleSheet("QLabel { font-weight: 500; }")
        right_layout.addWidget(self.lbl_consistency)
    
        gb_tree = QGroupBox("Originály – všechny soubory (indikace dle JSON)")
        vlt = QVBoxLayout(gb_tree)
    
        # --- Filtr nad stromem souborů (aktivní pouze při psaní do pole) ---
        self.json_tree_filter = QLineEdit()
        self.json_tree_filter.setPlaceholderText("Filtr souborů…")
        self.json_tree_filter.setClearButtonEnabled(True)
        self.json_tree_filter.setToolTip("Pište pro filtrování seznamu souborů. Mimo toto pole se nic nefiltruje.")
        self.json_tree_filter.textChanged.connect(self._on_json_tree_filter_text_changed)
        vlt.addWidget(self.json_tree_filter)
    
        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_json_tree_context_menu)
    
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(["Soubory"])
        self.tree.setModel(self.tree_model)
    
        vlt.addWidget(self.tree)
        right_layout.addWidget(gb_tree)
        splitter.addWidget(right_container)
    
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([1100, 600])
    
        # Inicialní aplikace poměrů po vykreslení
        QTimer.singleShot(0, self._apply_json_editor_split_sizes)
    
        return page
    
    def _apply_json_editor_split_sizes(self):
        """
        Nastaví výšky 4 panelů v self.json_editors_splitter tak, aby:
          - anonymizace ≈ 4 řádky editoru,
          - stavy ≈ 15 řádků editoru,
          - poznámky ≈ 15 řádků editoru,
          - lokace = zbytek dostupné výšky.
    
        FIX (PySide6): Guard proti volání po zániku splitteru (RuntimeError) pomocí shiboken6.isValid().
        """
        from shiboken6 import isValid
        from PySide6.QtCore import QMargins
    
        spl = getattr(self, "json_editors_splitter", None)
        if spl is None or not isValid(spl):
            return
        if spl.count() != 4:
            return
    
        def gb_height_for_lines(gb, editor, lines: int) -> int:
            try:
                fm = editor.fontMetrics()
                line_h = fm.lineSpacing() if hasattr(fm, "lineSpacing") else fm.height()
                text_h = int(max(1, lines) * line_h) + 8
                lay = gb.layout()
                m = lay.contentsMargins() if lay is not None else QMargins(8, 8, 8, 8)
                margins_h = m.top() + m.bottom()
                chrome = 28
                try:
                    frame = editor.frameWidth()
                except Exception:
                    frame = 1
                return text_h + margins_h + chrome + frame * 2
            except Exception:
                return 120
    
        h_an  = gb_height_for_lines(self.gb_an,   self.ed_anonym,   4)
        h_stv = gb_height_for_lines(self.gb_stavy, self.ed_stavy,   15)
        h_poz = gb_height_for_lines(self.gb_pozn,  self.ed_poznamky,15)
    
        try:
            total_h = max(200, spl.size().height())
            handle = max(6, spl.handleWidth())
            reserve = (spl.count() - 1) * handle
            fixed_sum = h_an + h_stv + h_poz + reserve
    
            h_lok = max(100, total_h - fixed_sum)
            sizes = [h_lok, h_stv, h_poz, h_an]
            if isValid(spl):
                spl.setSizes(sizes)
        except RuntimeError:
            # Splitter mohl zaniknout během běhu
            return

    def _json_help_button(self, tooltip_text: str) -> QPushButton:
        """
        Malé kulaté 'i' tlačítko do pravého horního rohu hlavičky editoru.
        Tooltip nese nápovědu k formátu.
        """
        btn = QPushButton("i")
        btn.setToolTip(tooltip_text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(22, 22)
        btn.setStyleSheet("""
            QPushButton {
                border: 1px solid rgba(0,0,0,40);
                border-radius: 11px;
                background: #f3f6fb;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #e8eef9;
            }
            QPushButton:pressed {
                background: #dde6f7;
            }
        """)
        return btn
    
    def _make_editor_section(self, title: str, tooltip_text: str, min_height: int = 180):
        """
        Sekce editoru ve stylu PDF generátoru (GroupBox title + tmavý JsonCodeEditor + '?' v rohu).
        Vrací: (groupbox_widget, editor_instance)
    
        FIX (PySide6): Bezpečné polohování '?' tlačítka — používáme shiboken6.isValid()
        a ověření, že widgety ještě žijí (zabrání RuntimeError: Internal C++ object deleted).
        """
        from shiboken6 import isValid  # PySide6 way
    
        gb = QGroupBox(title)
        gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
        lay = QVBoxLayout(gb)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
    
        editor_container = QWidget()
        editor_container_layout = QVBoxLayout(editor_container)
        editor_container_layout.setContentsMargins(0, 0, 0, 0)
    
        editor = JsonCodeEditor()
        editor.setMinimumHeight(min_height)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        editor.setStyleSheet("""
            QPlainTextEdit {
                background: #1e1e1e;
                color: #e6e6e6;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                selection-background-color: #264F78;
            }
        """)
        editor_container_layout.addWidget(editor)
    
        help_btn = QPushButton("?", parent=editor_container)
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip(tooltip_text)
        help_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
    
        # Bezpečné polohování: vždy ověřit, že objekty ještě žijí
        def position_help_button():
            try:
                if not isValid(editor_container) or not isValid(help_btn):
                    return
                help_btn.move(editor_container.width() - help_btn.width() - 6, 6)
                help_btn.raise_()
            except RuntimeError:
                return
    
        # Bezpečně „překryj“ resizeEvent
        _orig_resize = getattr(editor_container, "resizeEvent", None)
        def _safe_resize_event(event):
            try:
                if _orig_resize:
                    _orig_resize(event)
            except RuntimeError:
                pass
            position_help_button()
        editor_container.resizeEvent = _safe_resize_event  # přiřazení handleru
    
        # Jednorázové umístění po vykreslení (guard přes isValid)
        QTimer.singleShot(0, position_help_button)
    
        # Když se container ničí, není třeba nic odpojovat — guard to ošetří
        editor_container.destroyed.connect(lambda *_: None)
    
        lay.addWidget(editor_container)
        return gb, editor

    def _make_help_section(self, title: str, tooltip_text: str):
        """
        Vytvoří sekci ve stylu PDF generátoru:
          - QGroupBox s titulkem,
          - uvnitř 'content' kontejner (QWidget) se svým QVBoxLayoutem,
          - v pravém horním rohu contentu je ukotvené modré '?' tlačítko (tooltip = nápověda).
        Vrací: (groupbox_widget, content_widget)
        """
        gb = QGroupBox(title)
        outer = QVBoxLayout(gb)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)
    
        # Vnitřní kontejner s layoutem – do něj budeš přidávat vlastní obsah (layouty, widgety)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        outer.addWidget(content)
    
        # '?' help tlačítko (stejné jako u editorů)
        help_btn = QPushButton("?", parent=content)
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip(tooltip_text)
        help_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
    
        def position_help_button():
            help_btn.move(content.width() - help_btn.width() - 6, 6)
            help_btn.raise_()
    
        original_resize = content.resizeEvent
        def new_resize_event(event):
            if original_resize:
                original_resize(event)
            position_help_button()
        content.resizeEvent = new_resize_event
        QTimer.singleShot(0, position_help_button)
    
        # DŮLEŽITÉ: vracíme tuple (gb, content), nikoli None
        return gb, content
    
    def _update_rename_indicators(self):
        """
        Reálně (rekurzivně) projde Ořezy/Originály, spočítá indikátory a
        aktualizuje panel v Přejmenování + promítne to do záložky „Kontrola stavu…“.
        Odolné vůči chybám – vždy něco zobrazí.
        """
        def _safe_set(lbl: QLabel | None, html: str, style: str = ""):
            if lbl is None:
                return
            lbl.setText(html)
            if style:
                lbl.setStyleSheet(style)
    
        try:
            # Načti soubory rekurzivně
            def get_all_files(root_dir: Path) -> list[Path]:
                files = []
                if not root_dir.is_dir():
                    return files
                for p in root_dir.rglob("*"):
                    try:
                        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
                            files.append(p)
                    except Exception:
                        continue
                return files
    
            orezy_files = get_all_files(OREZY_DIR)
            originaly_files = get_all_files(ORIGINALS_DIR)
    
            # === Počty ===
            counts_html = (
                f"<b>Počty souborů:</b><br>"
                f"&nbsp;• Ořezy: <b>{len(orezy_files)}</b><br>"
                f"&nbsp;• Originály: <b>{len(originaly_files)}</b>"
            )
            _safe_set(getattr(self, "lbl_counts", None), counts_html)
            _safe_set(getattr(self, "chk_counts", None), counts_html)
    
            # === Formát OK / Chyby formátu (per-složka) ===
            def count_format(files: list[Path]) -> tuple[int, int]:
                ok = err = 0
                for p in files:
                    if NAME_PATTERN.match(p.name):
                        ok += 1
                    else:
                        err += 1
                return ok, err
    
            ok_o, err_o = count_format(orezy_files)
            ok_r, err_r = count_format(originaly_files)
            total_ok  = ok_o + ok_r
            total_err = err_o + err_r
    
            errors_html = (
                f"<b>Chyby formátu (celkem):</b> {total_err}<br>"
                f"&nbsp;• Ořezy: {err_o}<br>"
                f"&nbsp;• Originály: {err_r}"
            )
            ok_html = (
                f"<b>Správný formát (celkem):</b> {total_ok}<br>"
                f"&nbsp;• Ořezy: {ok_o}<br>"
                f"&nbsp;• Originály: {ok_r}"
            )
            err_style = "color: #D32F2F; font-weight: bold;" if total_err > 0 else ""
            ok_style  = "color: #2E7D32; font-weight: 600;"
    
            _safe_set(getattr(self, "lbl_format_errors", None), errors_html, err_style)
            _safe_set(getattr(self, "lbl_format_ok", None), ok_html, ok_style)
            _safe_set(getattr(self, "chk_format_errors", None), errors_html, err_style)
            _safe_set(getattr(self, "chk_format_ok", None), ok_html, ok_style)
    
            # === Rozdílné názvy (1:1 včetně přípony) ===
            def id_from_name(name: str) -> str | None:
                m = re.match(r'^(\d+)[_+]', name)
                return m.group(1) if m else None
    
            orezy_map = {id_from_name(p.name): p for p in orezy_files if id_from_name(p.name)}
            originaly_map = {id_from_name(p.name): p for p in originaly_files if id_from_name(p.name)}
    
            mismatches = 0
            for fid in set(orezy_map.keys()).intersection(originaly_map.keys()):
                if fid is None:
                    continue
                if orezy_map[fid].name != originaly_map[fid].name:
                    mismatches += 1
    
            mismatch_html = f"<b>Rozdílné názvy:</b> {mismatches}"
            mismatch_style = "color: #FFA000; font-weight: bold;" if mismatches > 0 else ""
            _safe_set(getattr(self, "lbl_name_mismatch", None), mismatch_html, mismatch_style)
            _safe_set(getattr(self, "chk_name_mismatch", None), mismatch_html, mismatch_style)
    
            # === Min/Max + chybějící ID (pro obě složky zvlášť) ===
            def collect_ids(files: list[Path]) -> list[int]:
                out = []
                for p in files:
                    s = id_from_name(p.name)
                    if not s:
                        continue
                    try:
                        out.append(int(s))
                    except Exception:
                        continue
                return sorted(set(out))
    
            ids_o = collect_ids(orezy_files)
            ids_r = collect_ids(originaly_files)
    
            def min_max_missing(ids: list[int]) -> tuple[str, str, str]:
                if not ids:
                    return ("–", "–", "–")
                mn, mx = ids[0], ids[-1]
                miss = sorted(set(range(mn, mx + 1)) - set(ids))
                # intervaly
                if not miss:
                    return (str(mn), str(mx), "žádné")
                s = miss[0]; e = miss[0]; out = []
                for n in miss[1:]:
                    if n == e + 1: e = n
                    else:
                        out.append(f"{s}-{e}" if s != e else str(s))
                        s = e = n
                out.append(f"{s}-{e}" if s != e else str(s))
                return (str(mn), str(mx), ", ".join(out))
    
            mn_o, mx_o, miss_o = min_max_missing(ids_o)
            mn_r, mx_r, miss_r = min_max_missing(ids_r)
            range_html = (
                "<b>Rozsah a chybějící ID:</b><br>"
                f"&nbsp;• Ořezy: min <b>{mn_o}</b>, max <b>{mx_o}</b>, chybí: {miss_o}<br>"
                f"&nbsp;• Originály: min <b>{mn_r}</b>, max <b>{mx_r}</b>, chybí: {miss_r}"
            )
            _safe_set(getattr(self, "lbl_range_missing", None), range_html)
            _safe_set(getattr(self, "chk_range_missing", None), range_html)
    
            # === Čas poslední kontroly (NOVÉ) ===
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            last_check_html = f"<span style='color:#666;'>Poslední kontrola:<br>{ts}</span>"
            _safe_set(getattr(self, "lbl_last_check", None), last_check_html)
            _safe_set(getattr(self, "chk_last_check", None), last_check_html)
    
        except Exception as e:
            # fallback – nikdy nenecháme „Načítání…“
            msg = f"<b>Chyba při aktualizaci indikátorů:</b> {e!s}"
            for name in ("lbl_counts","lbl_name_mismatch","lbl_format_errors","lbl_format_ok","lbl_range_missing","lbl_last_check",
                         "chk_counts","chk_name_mismatch","chk_format_errors","chk_format_ok","chk_range_missing","chk_last_check"):
                _safe_set(getattr(self, name, None), "—")
            _safe_set(getattr(self, "lbl_counts", None), msg)
            _safe_set(getattr(self, "chk_counts", None), msg)

    def _build_rename_tab(self):
        """
        Vytvoří a vrátí widget se záložkou "Přejmenování".
        Layout: strom souborů (vlevo) a panel indikátorů (vpravo).
        """
        page = QWidget()
        main_layout = QHBoxLayout(page)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
    
        # --- Levá část: Strom + akce ---
        left_widget = QWidget()
        v = QVBoxLayout(left_widget)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
    
        # Horní lišta s akcemi
        actions = QHBoxLayout()
        btn_reload = QPushButton(self.style().standardIcon(QStyle.SP_BrowserReload), " Obnovit")
        btn_reload.setToolTip("Znovu načte obsah složek a aktualizuje indikátory")
        btn_reload.clicked.connect(lambda: self._rebuild_rename_tree(preserve_state=self._capture_rename_ui_state()))
        actions.addWidget(btn_reload)
    
        # Defaultní přejmenování
        btn_rename = QPushButton(self.style().standardIcon(QStyle.SP_DialogYesButton), " Defaultní přejmenování")
        btn_rename.setToolTip("Přejmenuje vybrané položky na tvar ČísloNálezu++++NE+.HEIC")
        btn_rename.clicked.connect(self._on_click_default_rename_button)
        actions.addWidget(btn_rename)
    
        # Ukázat formát
        btn_show_format = QPushButton(self.style().standardIcon(QStyle.SP_MessageBoxInformation), "Ukázat formát názvu", self)
        btn_show_format.setToolTip("Zobrazí modální okno s formátem názvů")
        btn_show_format.clicked.connect(self._show_format_modal)
        actions.addWidget(btn_show_format)
    
        actions.addStretch(1)
        v.addLayout(actions)
    
        # Strom
        group = QGroupBox("Přejmenování – strom složek")
        gl = QVBoxLayout(group)
        gl.setContentsMargins(10, 10, 10, 10)
        gl.setSpacing(6)
    
        tree_container = QWidget(group)
        tc_lay = QVBoxLayout(tree_container)
        tc_lay.setContentsMargins(0, 0, 0, 0)
        tc_lay.setSpacing(0)
    
        self.ren_tree = QTreeView(tree_container)
        self.ren_tree.setHeaderHidden(True)
        self.ren_tree.setUniformRowHeights(True)
        self.ren_tree.setAnimated(True)
        self.ren_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.ren_tree.setSelectionBehavior(QAbstractItemView.SelectItems)
        tc_lay.addWidget(self.ren_tree)
    
        self.ren_model = QStandardItemModel()
        self.ren_model.setHorizontalHeaderLabels(["Soubory"])
        self.ren_tree.setModel(self.ren_model)
    
        self.ren_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ren_tree.customContextMenuRequested.connect(self._on_rename_tree_context_menu)
    
        self._ren_dir_items = {}
    
        gl.addWidget(tree_container)
        v.addWidget(group, 1)
    
        # --- Pravá část: Indikátory ---
        indicators_group = QGroupBox("Kontrola")
        indicators_layout = QVBoxLayout(indicators_group)
        indicators_layout.setSpacing(12)
    
        # Počty
        self.lbl_counts = QLabel("Načítání...")
        self.lbl_counts.setTextFormat(Qt.RichText)
        self.lbl_counts.setWordWrap(True)
        indicators_layout.addWidget(self.lbl_counts)
    
        # Rozdílné názvy
        self.lbl_name_mismatch = QLabel("Načítání...")
        self.lbl_name_mismatch.setTextFormat(Qt.RichText)
        self.lbl_name_mismatch.setWordWrap(True)
        indicators_layout.addWidget(self.lbl_name_mismatch)
    
        # Chyby formátu (s rozpadem)
        self.lbl_format_errors = QLabel("Načítání...")
        self.lbl_format_errors.setTextFormat(Qt.RichText)
        self.lbl_format_errors.setWordWrap(True)
        indicators_layout.addWidget(self.lbl_format_errors)
    
        # Správný formát (zeleně) – celkem + rozpad
        self.lbl_format_ok = QLabel("Načítání...")
        self.lbl_format_ok.setTextFormat(Qt.RichText)
        self.lbl_format_ok.setWordWrap(True)
        indicators_layout.addWidget(self.lbl_format_ok)
    
        # Min/Max a chybějící
        self.lbl_range_missing = QLabel("Načítání...")
        self.lbl_range_missing.setTextFormat(Qt.RichText)
        self.lbl_range_missing.setWordWrap(True)
        indicators_layout.addWidget(self.lbl_range_missing)
    
        # Čas poslední kontroly (NOVÉ)
        self.lbl_last_check = QLabel("—")
        self.lbl_last_check.setTextFormat(Qt.RichText)
        self.lbl_last_check.setStyleSheet("color: #666;")
        indicators_layout.addWidget(self.lbl_last_check)
    
        indicators_layout.addStretch(1)
        indicators_group.setFixedWidth(280)
    
        main_layout.addWidget(left_widget, 1)
        main_layout.addWidget(indicators_group)
    
        # Real-time monitoring
        self._setup_rename_file_watcher()
    
        # Sestav strom a hned zkus spočítat indikátory
        initial_state = self._load_rename_ui_state()
        self._rebuild_rename_tree(preserve_state=initial_state)
        QTimer.singleShot(0, self._update_rename_indicators)
    
        # Warm-start z cache (pokud používáš)
        try:
            self._apply_cached_status(self._load_cached_status())
        except Exception:
            pass
    
        return page
    
    def _on_watched_directory_changed(self, path: str):
        """
        Reaguje na změny ve sledované složce (přidání/odebrání souborů nebo podsložek).
        - Rychle obnoví indikátory (debounce).
        - Při změně v kořenech OŘEZY/ORIGINÁLY navíc po krátké prodlevě obnoví strom (je-li třeba).
        - Udržuje seznam sledovaných podsložek.
        """
        # === NOVĚ: během přejmenování / pozastavení watcher umlčet a odložit změny ===
        if getattr(self, "_suspend_fs_events", False) or getattr(self, "_rename_in_progress", False):
            # poznač, že po skončení rename se mají pending změny zpracovat
            setattr(self, "_fs_events_pending", True)
            # jemně připrav debounce aktualizace watched paths, až se odblokujeme
            try:
                if not hasattr(self, "_watcher_paths_timer") or self._watcher_paths_timer is None:
                    self._watcher_paths_timer = QTimer(self)
                    self._watcher_paths_timer.setSingleShot(True)
                    self._watcher_paths_timer.timeout.connect(self._update_watcher_paths)
                # start jen nastaví pending akci; když jsme „suspend“, na timeoutu se _update_… hned vrátí
                self._watcher_paths_timer.start(150)
            except Exception:
                pass
            return
    
        # 1) Rychlá indikace (Počty / Rozsah ID / Chybějící / Názvy / Formát)
        if hasattr(self, "_indicators_timer"):
            self._indicators_timer.start()  # debounce 150 ms
    
        # 2) Strom přestav až po malém zpoždění (aby OS „dopsal“ změny)
        if path in (str(OREZY_DIR), str(ORIGINALS_DIR)):
            # zachovej stav (preserve_state=True je default v _rebuild_rename_tree)
            QTimer.singleShot(200, self._rebuild_rename_tree)
    
        # 3) Sledování nových/přebytečných podsložek — DEBOUNCE místo okamžitého přeregistrování
        if not hasattr(self, "_watcher_paths_timer") or self._watcher_paths_timer is None:
            self._watcher_paths_timer = QTimer(self)
            self._watcher_paths_timer.setSingleShot(True)
            self._watcher_paths_timer.timeout.connect(self._update_watcher_paths)
        # slouč rychlé série změn do 1 aplikace
        try:
            self._watcher_paths_timer.stop()
        except Exception:
            pass
        self._watcher_paths_timer.start(150)
    
    def _on_watched_file_changed(self, path: str):
        """
        Reaguje na úpravy/přejmenování jednotlivých souborů.
        - Aktualizuje pouze indikátory (debounce), strom necháváme být kvůli plynulosti.
        """
        if hasattr(self, "_indicators_timer"):
            self._indicators_timer.start()  # debounce 150 ms
    
    def _update_watcher_paths(self):
        """
        Aktualizuje seznam sledovaných cest ve watcheru pro 'Přejmenování'
        tak, aby se přidaly/odebraly pouze ROZDÍLY.
        Pokud se sada sledovaných složek nezměnila, nedělá nic a nic neloguje.
        """
        watcher = getattr(self, "_rename_file_watcher", None)
        if watcher is None:
            return
    
        # Během přejmenování/suspend jen odlož – případnou změnu dožene _on_fs_changed
        if getattr(self, "_suspend_fs_events", False) or getattr(self, "_rename_in_progress", False):
            return
    
        import os, sys
        from pathlib import Path
    
        def _norm(p: str) -> str:
            """Kanonická normalizace cest pro stabilní porovnání (bez ohledu na symlinky/case)."""
            try:
                p2 = os.path.normpath(os.path.realpath(p))
            except Exception:
                p2 = os.path.normpath(p)
            try:
                if sys.platform.startswith("win") or sys.platform == "darwin":
                    p2 = p2.lower()
            except Exception:
                pass
            return p2
    
        # Nová sada (norm_path -> original_path)
        new_map: dict[str, str] = {}
        roots = []
        try:
            if 'OREZY_DIR' in globals():
                roots.append(OREZY_DIR)
            if 'ORIGINALS_DIR' in globals():
                roots.append(ORIGINALS_DIR)
        except Exception:
            pass
    
        for root in roots:
            try:
                if root and root.exists():
                    s = str(root)
                    new_map[_norm(s)] = s
                    for sub in root.rglob("*"):
                        if sub.is_dir():
                            sp = str(sub)
                            new_map[_norm(sp)] = sp
            except Exception:
                continue
    
        # Aktuální sada (norm_path -> watcher_path)
        try:
            current_list = watcher.directories()
        except Exception:
            current_list = []
        cur_map = {_norm(p): p for p in current_list}
    
        new_norm = set(new_map.keys())
        cur_norm = set(cur_map.keys())
    
        to_add_norm = sorted(new_norm - cur_norm)
        to_remove_norm = sorted(cur_norm - new_norm)
    
        # ŽÁDNÁ reálná změna → NIC nedělej (ani log)
        if not to_add_norm and not to_remove_norm:
            return
    
        # Odebrání a přidání po normalizované deltě (s originálními řetězci)
        if to_remove_norm:
            try:
                watcher.removePaths([cur_map[n] for n in to_remove_norm])
            except Exception:
                pass
    
        if to_add_norm:
            try:
                watcher.addPaths([new_map[n] for n in to_add_norm])
            except Exception:
                pass
    
        # Log jen pokud k reálné změně došlo
        try:
            if to_remove_norm:
                print(f"Odebráno {len(to_remove_norm)} složek ze sledování")
            if to_add_norm:
                print(f"Přidáno {len(to_add_norm)} nových složek do sledování")
        except Exception:
            pass
    
    def _setup_rename_file_watcher(self):
        """
        Nastaví QFileSystemWatcher pro real-time sledování změn 
        ve složkách Ořezy a Originály. Při jakékoliv změně automaticky
        aktualizuje indikátory.
        """
        # Pokud už watcher existuje, nejprve ho zrušíme
        if hasattr(self, '_rename_file_watcher'):
            self._rename_file_watcher.deleteLater()
        
        self._rename_file_watcher = QFileSystemWatcher(self)
        
        # Cesty ke sledovaným složkám
        watched_dirs = []
        
        # Přidáme hlavní složky
        if OREZY_DIR.exists():
            watched_dirs.append(str(OREZY_DIR))
            
            # Přidáme také všechny podsložky pro komplexní monitoring
            for subdir in OREZY_DIR.rglob("*"):
                if subdir.is_dir():
                    watched_dirs.append(str(subdir))
        
        if ORIGINALS_DIR.exists():
            watched_dirs.append(str(ORIGINALS_DIR))
            
            # Přidáme také všechny podsložky pro komplexní monitoring
            for subdir in ORIGINALS_DIR.rglob("*"):
                if subdir.is_dir():
                    watched_dirs.append(str(subdir))
        
        if watched_dirs:
            self._rename_file_watcher.addPaths(watched_dirs)
            
            # Připojení signálů pro automatickou aktualizaci
            self._rename_file_watcher.directoryChanged.connect(self._on_watched_directory_changed)
            self._rename_file_watcher.fileChanged.connect(self._on_watched_file_changed)
            
            print(f"File watcher nastaven pro {len(watched_dirs)} složek")
        else:
            print("Varování: Žádné složky k sledování nebyly nalezeny")

    def _rebuild_rename_tree(self, preserve_state: bool = True, path_map: dict[str, str] | None = None):
        """
        Sestaví strom (Ořezy/Originály) + podsložky/soubory.

        Parametry:
        - preserve_state: zachovat rozbalení, fokus a scroll (default True).
        - path_map: volitelná mapa {old_path: new_path}, použije se k obnově výběru
                    po přejmenování (nově pojmenovaný soubor bude vybrán).
        """
        if not hasattr(self, "ren_tree"):
            return

        self.ren_tree.setUpdatesEnabled(False)
        try:
            prev_scroll = None
            if preserve_state:
                try:
                    prev_scroll = self.ren_tree.verticalScrollBar().value()
                except Exception:
                    prev_scroll = None

            if preserve_state and not getattr(self, "_sticky_expand_paths", None):
                self._restore_rename_tree_state()

            self.ren_model.clear()
            self.ren_model.setHorizontalHeaderLabels(["Soubory"])
            self._ren_dir_items = {}

            def make_dir_item(name: str, path: Path):
                # Indikace: pokud tato složka obsahuje nějaké soubory .HEIC a všechny mají platné názvy podle pravidel,
                # přidej k názvu složky badge "✅ HEIC".
                badge = ""
                try:
                    heic_files = [p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".heic"]
                    if heic_files and all(self._is_full_valid_name(p.name) for p in heic_files):
                        badge = "  ✅ HEIC"
                except Exception:
                    pass
                label = f"{name}{badge}"
                it = QStandardItem(self.style().standardIcon(QStyle.SP_DirIcon), label)
                it.setEditable(False)
                it.setData("dir", Qt.UserRole)
                it.setData(str(path), Qt.UserRole + 1)
                # ToolTip rozšíříme, pokud je vše OK
                if badge:
                    it.setToolTip(f"{path}\nVšechny .HEIC jsou správně pojmenované.")
                else:
                    it.setToolTip(str(path))
                self._ren_dir_items[str(path)] = it
                return it

            def make_file_item(path: Path):
                icon = self.style().standardIcon(QStyle.SP_FileIcon)
                badge = " ✅" if self._is_full_valid_name(path.name) else ""
                label = f"{path.name}{badge}"
                it = QStandardItem(icon, label)
                it.setEditable(False)
                it.setData("file", Qt.UserRole)
                it.setData(str(path), Qt.UserRole + 1)
                it.setToolTip(str(path))
                return it

            def populate_dir(parent_item: QStandardItem, root_path: Path):
                try:
                    entries = list(root_path.iterdir())
                except Exception:
                    return
                dirs = sorted((p for p in entries if p.is_dir()), key=lambda p: p.name.lower())
                files = sorted(
                    (p for p in entries if p.is_file() and p.suffix.lower() in ALLOWED_EXTS),
                    key=self._file_numeric_sort_key
                )

                for d in dirs:
                    child = make_dir_item(d.name, d)
                    parent_item.appendRow(child)
                    populate_dir(child, d)

                for f in files:
                    parent_item.appendRow(make_file_item(f))

            # Kořeny
            mini_root = make_dir_item("Ořezy", OREZY_DIR)
            orig_root = make_dir_item("Originály", ORIGINALS_DIR)
            self.ren_model.appendRow(mini_root)
            self.ren_model.appendRow(orig_root)

            populate_dir(mini_root, OREZY_DIR)
            populate_dir(orig_root, ORIGINALS_DIR)

            # Reaplikace rozbalení
            if preserve_state:
                if getattr(self, "_sticky_expand_paths", None):
                    self._apply_expand_paths(self._sticky_expand_paths, collapse_others=False)
                elif not self._restore_rename_tree_state():
                    self.ren_tree.expand(self.ren_model.indexFromItem(mini_root))
                    self.ren_tree.expand(self.ren_model.indexFromItem(orig_root))
            else:
                self.ren_tree.expand(self.ren_model.indexFromItem(mini_root))
                self.ren_tree.expand(self.ren_model.indexFromItem(orig_root))

            # Obnova výběru: nejdřív podle path_map, pak sticky_focus_path
            target_path = None
            if path_map:
                # vezmeme první novou cestu z mapy
                target_path = next(iter(path_map.values()))
            elif preserve_state and getattr(self, "_sticky_focus_path", None):
                target_path = self._sticky_focus_path

            if target_path:
                item = self._ren_dir_items.get(target_path)
                if item is not None:
                    idx = self.ren_model.indexFromItem(item)
                    if idx.isValid():
                        self.ren_tree.setCurrentIndex(idx)
                        sel = self.ren_tree.selectionModel()
                        if sel is not None:
                            sel.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
                        # POZOR: nescrollujeme při prostém preserve_state, abychom nezpůsobili „hop“ nahoru
                        if path_map:
                            self.ren_tree.scrollTo(idx)

            # Scroll
            if preserve_state:
                try:
                    scroll_val = self._sticky_scroll if self._sticky_scroll is not None else prev_scroll
                    if scroll_val is not None:
                        self.ren_tree.verticalScrollBar().setValue(scroll_val)
                except Exception:
                    pass

            self._update_rename_indicators()

        finally:
            self.ren_tree.setUpdatesEnabled(True)
            
    def _save_rename_tree_state(self):
        """
        Uloží seznam rozbalených adresářů (absolutní cesty) do JSON souboru v /settings.
        """
        if not hasattr(self, "ren_model"):
            return
        expanded_paths = []
    
        def walk(parent_item: QStandardItem):
            rows = parent_item.rowCount()
            for r in range(rows):
                it = parent_item.child(r)
                if it is None:
                    continue
                if it.data(Qt.UserRole) == "dir":
                    idx = self.ren_model.indexFromItem(it)
                    if self.ren_tree.isExpanded(idx):
                        expanded_paths.append(it.data(Qt.UserRole + 1))
                    # rekurze
                    walk(it)
    
        # Top-level procházení
        root_rows = self.ren_model.rowCount()
        for rr in range(root_rows):
            root_item = self.ren_model.item(rr)
            if root_item and root_item.data(Qt.UserRole) == "dir":
                idx = self.ren_model.indexFromItem(root_item)
                if self.ren_tree.isExpanded(idx):
                    expanded_paths.append(root_item.data(Qt.UserRole + 1))
                walk(root_item)
    
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            RENAME_STATE_FILE.write_text(json.dumps({"expanded": expanded_paths}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # tiché – není kritické
    
    
    def _restore_rename_tree_state(self) -> bool:
        """
        Zkusí obnovit rozbalené adresáře ze souboru. Vrací True, pokud byl stav načten a aplikován.
        """
        if not RENAME_STATE_FILE.exists():
            return False
    
        try:
            data = json.loads(RENAME_STATE_FILE.read_text(encoding="utf-8"))
            expanded = set(data.get("expanded", []))
        except Exception:
            return False
    
        if not expanded:
            return False
    
        # pro každý uložený path najdi item a expanduj
        applied = False
        for path_str in expanded:
            it = self._ren_dir_items.get(path_str)
            if it is None:
                continue
            idx = self.ren_model.indexFromItem(it)
            if idx.isValid():
                self.ren_tree.setExpanded(idx, True)
                applied = True
        return applied
        
    def _do_default_rename_batch(self, items: list[tuple[Path, bool]]):
        """
        Defaultní přejmenování (viz dřívější logika) + robustní obnova stavu stromu.
        """
        items = [(p, is_dir) for (p, is_dir) in items if isinstance(p, Path) and p.exists()]
        if not items:
            QMessageBox.information(self, "Přejmenování", "Nebyly vybrány žádné platné položky.")
            return
    
        # stav před akcí
        state_before = self._capture_rename_ui_state()
    
        # Nasbírej cílové soubory (bez rekurze u složek)
        file_set: set[Path] = set()
        for p, is_dir in items:
            if is_dir:
                try:
                    for fp in p.iterdir():
                        if fp.is_file() and fp.suffix.lower() in ALLOWED_EXTS:
                            file_set.add(fp)
                except Exception:
                    continue
            else:
                if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
                    file_set.add(p)
    
        # === NOVĚ: umlčení watcheru + sticky stav pro přesné obnovení UI ===
        self._suspend_fs_events = True
        self._rename_in_progress = True
        try:
            self._sticky_expand_paths = state_before.get("expanded", [])
            self._sticky_scroll = state_before.get("scroll")
            self._sticky_focus_path = state_before.get("current")
        except Exception:
            # fail-safe
            self._sticky_expand_paths = getattr(self, "_sticky_expand_paths", None)
            self._sticky_scroll = getattr(self, "_sticky_scroll", None)
    
        renamed = skipped = errors = 0
        path_map: dict[str, str] = {}
    
        for fp in sorted(file_set):
            # zdrojová extrakce čísla (zachovávám původní logiku)
            if hasattr(self, "_extract_id_from_name_default"):
                id_str = self._extract_id_from_name_default(fp.name)
            else:
                id_str = self._extract_id_from_name(fp.name)
            if not id_str:
                skipped += 1
                continue
            try:
                id_clean = str(int(id_str))  # bez počátečních nul
            except Exception:
                skipped += 1
                continue
    
            base = f"{id_clean}++++NE+"
            target = fp.with_name(base + ".HEIC")
            if target.exists() and target != fp:
                i = 1
                found = None
                while i <= 999:
                    cand = fp.with_name(f"{base}_{i}.HEIC")
                    if not cand.exists():
                        found = cand
                        break
                    i += 1
                if found is None:
                    errors += 1
                    continue
                target = found
    
            try:
                if target != fp:
                    old = str(fp)
                    fp.rename(target)
                    path_map[old] = str(target)
                    renamed += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
    
        # Pokud byl vybraný soubor přejmenován, nasměruj current na novou cestu
        cur = state_before.get("current")
        if cur and cur in path_map:
            state_before["current"] = path_map[cur]
        # U výběru nahraď staré cesty novými
        if "selected" in state_before and state_before["selected"]:
            state_before["selected"] = [path_map.get(p, p) for p in state_before["selected"]]
    
        # Rebuild s obnovou
        self._rebuild_rename_tree(preserve_state=state_before, path_map=path_map)
    
        QMessageBox.information(
            self, "Přejmenování dokončeno",
            f"Přejmenováno: {renamed}\nPřeskočeno: {skipped}\nChyb: {errors}"
        )
    
        # >>> JSON: refresh pravého stromu (zachovat rozbalení/scroll/fokus)
        try:
            self._schedule_json_tree_rebuild()
        except Exception:
            pass
    
        QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
        self._save_rename_ui_state()
        
    def _on_collapse_all_rename_clicked(self):
        """Sbalí všechny složky ve stromu 'Přejmenování' a uloží stav."""
        if not hasattr(self, "ren_model") or not hasattr(self, "ren_tree") or not hasattr(self, "_ren_dir_items"):
            return
        # vypnout repainty pro plynulost
        self.ren_tree.setUpdatesEnabled(False)
        try:
            for item in self._ren_dir_items.values():
                if item is None:
                    continue
                idx = self.ren_model.indexFromItem(item)
                if idx.isValid():
                    self.ren_tree.setExpanded(idx, False)
            # vyčistit sticky expanzi, aby se po dalších skenech zase všechno „nevyboulilo“
            self._sticky_expand_paths = []
            self._sticky_focus_path = None
            self._sticky_scroll = None
            # uložit stav do settings
            self._save_rename_tree_state()
        finally:
            self.ren_tree.setUpdatesEnabled(True)

    def _on_click_default_rename_button(self):
        """
        Spustí defaultní přejmenování nad vybranými položkami.
        Úprava: během akce umlčí watcher, zachová expand/selection; SCROLL VRACÍ AŽ NA KONCI.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    
        items = self._gather_selected_items()
        if not items:
            items = [(OREZY_DIR, True), (ORIGINALS_DIR, True)]
    
        # Snapshot (bez okamžitého vracení scrollu)
        state = self._capture_rename_ui_state() if hasattr(self, "_capture_rename_ui_state") else None
        try:
            vbar = self.ren_tree.verticalScrollBar()
            saved_scroll = int(vbar.value())
        except Exception:
            saved_scroll = 0
    
        # Sticky – POUZE expand/selection; scroll necháme na finální restorer
        if state:
            self._sticky_expand_paths = state.get("expanded", [])
            self._sticky_focus_path = state.get("current")
            self._sticky_scroll = None  # <— důležité: ať žádná mezikroková obnova nenasetuje scroll
    
        # Umlčet watcher po dobu akce
        self._suspend_fs_events = True
        self._rename_in_progress = True
    
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._do_default_rename_batch(items)  # původní implementace
        finally:
            QApplication.restoreOverrideCursor()
            self._rename_in_progress = False
            self._suspend_fs_events = False
    
            # Naplánuj finální vrácení scrollu AŽ PO všech rebuildech
            self._schedule_final_scroll_restore(saved_scroll)
    
            # Vyčistit sticky
            self._sticky_expand_paths = None
            self._sticky_focus_path = None
            self._sticky_scroll = None
        
    def _extract_id_from_name(self, fname: str):
        m = re.match(r'^(\d+)\+', fname)
        return m.group(1) if m else None

    def _extract_id_from_name_default(self, fname: str) -> str | None:
        """
        Pro účely DEFAULTNÍHO PŘEJMENOVÁNÍ:
        Vrátí ČísloNálezu jako string podle části před PRVNÍM '+' NEBO '_'.
        Příklady:
          '2487_2024-05-24_133452' → '2487'
          '2487+BRNO.HEIC'         → '2487'
        """
        m = re.match(r'^(\d+)[_+]', fname)
        return m.group(1) if m else None

    def _do_default_rename_on_path(self, path: Path, is_dir: bool):
        """
        Defaultní pojmenování pro jeden path:
          - soubor  -> <id_bez_nul>+++++.HEIC
          - složka  -> přejmenuje všechny soubory přímo v dané složce (bez rekurze)
        """
        if not path.exists():
            QMessageBox.warning(self, "Přejmenování", f"Cesta neexistuje:\n{path}")
            return
    
        # Start rename-seance
        self._rename_in_progress = True
        self._suspend_fs_events = True
    
        # Stav před akcí
        self._sticky_expand_paths = self._capture_rename_tree_state()
        self._sticky_focus_path = str(path if is_dir else path.parent)
        try:
            self._sticky_scroll = self.ren_tree.verticalScrollBar().value()
        except Exception:
            self._sticky_scroll = None
    
        # Nasbírej soubory
        files = []
        if is_dir:
            try:
                for fp in path.iterdir():
                    if fp.is_file() and fp.suffix.lower() in ALLOWED_EXTS:
                        files.append(fp)
            except Exception:
                QMessageBox.warning(self, "Přejmenování", "Nepodařilo se načíst obsah složky.")
                self._rename_in_progress = False
                self._suspend_fs_events = False
                return
        else:
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTS:
                files.append(path)
            else:
                QMessageBox.information(self, "Přejmenování", "Vybraný prvek není podporovaný soubor.")
                self._rename_in_progress = False
                self._suspend_fs_events = False
                return
    
        renamed = skipped = errors = 0
    
        for fp in files:
            # zachovávám původní extrakci id (prefer _extract_id_from_name_default)
            id_str = self._extract_id_from_name_default(fp.name) if hasattr(self, "_extract_id_from_name_default") else self._extract_id_from_name(fp.name)
            if not id_str:
                skipped += 1
                continue
            try:
                id_clean = str(int(id_str))
            except Exception:
                skipped += 1
                continue
    
            base = f"{id_clean}++++NE+"
            target = fp.with_name(base + ".HEIC")
            if target.exists() and target != fp:
                i = 1
                found = None
                while i <= 999:
                    cand = fp.with_name(f"{base}_{i}.HEIC")
                    if not cand.exists():
                        found = cand
                        break
                    i += 1
                if found is None:
                    errors += 1
                    continue
                target = found
            try:
                if target != fp:
                    fp.rename(target)
                    renamed += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
    
        # Spusť jeden kontrolní sken
        self.run_scan()
    
        QMessageBox.information(
            self, "Přejmenování dokončeno",
            f"Přejmenováno: {renamed}\nPřeskočeno: {skipped}\nChyb: {errors}"
        )
    
        # >>> JSON: refresh pravého stromu (zachovat rozbalení/scroll/fokus)
        try:
            self._schedule_json_tree_rebuild()
        except Exception:
            pass

    @Slot()
    def _load_settings_into_editors(self):
        """Načte JSON nastavení a vloží do editorů jednořádkový formát (zarovnání dvojteček)."""
        lokace = {}; stavy = {}; poznamky = {}; anonym = {}
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                lokace   = data.get("lokace", {}) or {}
                stavy    = data.get("stavy", {}) or {}
                poznamky = data.get("poznamky", {}) or {}
                anonym   = data.get("anonymizace", {}) or {}
            except Exception as e:
                QMessageBox.warning(self, "Načítání nastavení", f"Soubor se nepodařilo načíst:\n{e}")
    
        self.ed_lokace.setPlainText(self._format_singleline_dict(lokace,   sort_numeric_keys=True,  align_values=True))
        self.ed_stavy.setPlainText( self._format_singleline_dict(stavy,    sort_numeric_keys=False, align_values=True))
        self.ed_poznamky.setPlainText(self._format_singleline_dict(poznamky,sort_numeric_keys=True, align_values=True))
        self.ed_anonym.setPlainText(self._format_singleline_dict(anonym,   sort_numeric_keys=False, align_values=True))
    
        # realtime refresh pravého stromu
        self._schedule_json_tree_rebuild()

    def _format_singleline_dict(self, d: dict, sort_numeric_keys: bool = True, align_values: bool = True) -> str:
        """
        Vrátí JSON slovník ve stylu:
        {
          "1":    ["14305"],
          "8":    ["13609"],
          "10":   ["13608","14310-14313"]
        }
    
        - 1 položka = 1 řádek (kromě { a }).
        - Dvojtečky jsou sloupcově zarovnány (align_values=True).
        - Klíče se pokusíme řadit numericky (sort_numeric_keys=True), jinak abecedně.
        - Hodnoty-list jsou kompaktní: ["a","b","c"] (bez mezer po čárkách).
        """
        if not d:
            return "{}"
    
        # seřaď klíče
        items = list(d.items())
        if sort_numeric_keys:
            def _k(key):
                try:
                    return (0, int(key))
                except Exception:
                    return (1, str(key))
            items.sort(key=lambda kv: _k(kv[0]))
        else:
            items.sort(key=lambda kv: str(kv[0]))
    
        key_strs = [json.dumps(k, ensure_ascii=False) for k, _ in items]
        max_key_len = max(len(s) for s in key_strs) if align_values else 0
    
        lines = ["{"]
        for idx, ((k, v), k_str) in enumerate(zip(items, key_strs)):
            # hodnota jako kompaktní JSON
            if isinstance(v, list):
                val = "[" + ",".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
            else:
                val = json.dumps(v, ensure_ascii=False)
    
            pad = " " * (max_key_len - len(k_str) + 1) if align_values else " "
            comma = "," if idx < len(items) - 1 else ""
            lines.append(f"  {k_str}:{pad}{val}{comma}")
        lines.append("}")
        return "\n".join(lines)

    @Slot()
    def _save_editors_to_settings(self):
        """
        Uloží obsah editorů do settings/LokaceStavyPoznamky.json.
        Na disk zapisuje standardně (indent=2), poté editorům opět nastaví jednořádkový formát
        a přebuduje pravý strom (realtime indikace).
        """
        try:
            lokace = json.loads(self.ed_lokace.toPlainText() or "{}")
            stavy  = json.loads(self.ed_stavy.toPlainText() or "{}")
            poznamky = json.loads(self.ed_poznamky.toPlainText() or "{}")
            anonym = json.loads(self.ed_anonym.toPlainText() or "{}")
        except Exception as e:
            QMessageBox.critical(self, "Chyba JSON", f"JSON není validní:\n{e}")
            return
    
        # Validace klíčů stavů
        unknown = set(stavy.keys()) - ALLOWED_STATES
        if unknown:
            QMessageBox.warning(
                self, "Neplatné stavy",
                "Nalezeny neplatné klíče ve 'stavy':\n"
                + ", ".join(sorted(unknown)) +
                "\n\nPovoleno je pouze: " + ", ".join(sorted(ALLOWED_STATES))
            )
            return
    
        data = {"lokace": lokace, "stavy": stavy, "poznamky": poznamky, "anonymizace": anonym}
    
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Ukládání selhalo", f"Nepodařilo se uložit soubor:\n{e}")
            return
    
        # Po uložení znovu nastavíme jednořádkové zobrazení
        self.ed_lokace.setPlainText(self._format_singleline_dict(lokace, sort_numeric_keys=True,  align_values=True))
        self.ed_stavy.setPlainText( self._format_singleline_dict(stavy,  sort_numeric_keys=False, align_values=True))
        self.ed_poznamky.setPlainText(self._format_singleline_dict(poznamky, sort_numeric_keys=True, align_values=True))
        self.ed_anonym.setPlainText(self._format_singleline_dict(anonym, sort_numeric_keys=False, align_values=True))
    
        # realtime refresh pravého stromu
        self._schedule_json_tree_rebuild()

    # --- Real-time FS reakce ---

    @Slot()
    def _on_fs_changed(self):
        """
        Reakce na FS změny z RecursiveDirectoryWatcher.
        Cíl: během intenzivního přejmenovávání nezatěžovat UI – jen prodlužujeme „grace“,
        a skutečné skeny/obnovu watcherů pustíme až po uklidnění.
        """
        if self._suspend_fs_events:
            return  # dočasně umlčeno (např. ořez/ukládání nebo ruční suspend)
    
        # Pokud probíhá rename seance (nebo už běží grace), jen prodluž jej a nespouštěj nic těžkého.
        if self._rename_in_progress or self._rename_grace_timer.isActive():
            self._fs_changes_during_rename += 1
            # prodluž okno: každá další změna posune konec grace, aby se vše slilo do jedné práce
            self._rename_grace_timer.start()
            return
    
        # Pokud to vypadá na burst (první změna) – rozjeď grace a sbírej další změny.
        self._rename_in_progress = True
        self._fs_changes_during_rename = 1
    
        # Umlčení watcher signálů – aby UI neprocházelo opakovanými rebuildy.
        try:
            self._suspend_fs_events = True
            self._dir_watcher.blockSignals(True)
        except Exception:
            pass
    
        # Spusť „grace“ – po jejím uplynutí proběhne jeden konsolidovaný scan + refresh watcherů.
        self._rename_grace_timer.start()

    # --- Akce ---

    @Slot()
    def run_scan(self):
        """
        Spustí asynchronní sken souborového systému. Pokud už běží, jen si poznačí pending.
        Reálná práce běží v backgroundu (QtConcurrent), UI se neblokuje.
        """
        # Hlídané stavové příznaky už v třídě máš:
        #   self._scan_running: bool
        #   self._scan_pending: bool
    
        if getattr(self, "_scan_running", False):
            # Běží – jen si poznačíme, že chceme ještě jeden cyklus po dokončení
            self._scan_pending = True
            return
    
        self._scan_running = True
        self._scan_pending = False
    
        # Background běh: QtConcurrent
        try:
            from PySide6.QtConcurrent import run as qt_run
            from PySide6.QtCore import QFutureWatcher, QObject
    
            # Založ watcher (uložíme si ho na instanci, ať nám neumře dřív)
            if hasattr(self, "_scan_watcher") and self._scan_watcher is not None:
                try:
                    self._scan_watcher.cancel()
                except Exception:
                    pass
                try:
                    self._scan_watcher.deleteLater()
                except Exception:
                    pass
    
            self._scan_watcher = QFutureWatcher(self)
    
            # Spustíme background výpočet snapshotu
            future = qt_run(self._scan_collect_snapshot)
    
            # Po dokončení převezmeme výsledek a dokončíme v GUI vlákně
            def _finished():
                try:
                    snapshot = self._scan_watcher.future().result()
                except Exception:
                    snapshot = None
                # Předáme do on_finish (necháme kompatibilní signaturu – parametr je volitelný)
                self._on_scan_finished(snapshot)
    
            self._scan_watcher.finished.connect(_finished)
            self._scan_watcher.setFuture(future)
        except Exception:
            # Když QtConcurrent není k dispozici, uděláme synchronní fallback (aby to aspoň fungovalo).
            snapshot = self._scan_collect_snapshot()
            self._on_scan_finished(snapshot)
            
    def _scan_collect_snapshot(self):
        """
        Rychlý „otisk“ (hash) obsahu sledovaných složek (ORIGINALS_DIR, OREZY_DIR).
        Nesahá na GUI. Vrací dict se 'hash' a pár metadaty.
        """
        from pathlib import Path
        import hashlib, os
    
        roots = []
        try:
            roots.append(ORIGINALS_DIR)
        except Exception:
            pass
        try:
            roots.append(OREZY_DIR)
        except Exception:
            pass
    
        entries = []
        for root in roots:
            try:
                root = Path(root)
                if not root.exists():
                    continue
                for dirpath, dirnames, filenames in os.walk(root):
                    # případné skryté položky můžeš filtrovat už tady dle potřeby
                    for fname in filenames:
                        p = Path(dirpath) / fname
                        try:
                            st = p.stat()
                            # bereme jen invarianty pro rychlý diff
                            entries.append((
                                str(root),
                                str(p.relative_to(root)),
                                int(st.st_mtime),
                                int(st.st_size)
                            ))
                        except Exception:
                            continue
            except Exception:
                continue
    
        entries.sort()
        h = hashlib.sha1()
        for item in entries:
            h.update(("|".join(map(str, item)) + "\n").encode("utf-8", "ignore"))
    
        return {
            "hash": h.hexdigest(),
            "counts": {
                r if isinstance(r, str) else str(r): sum(1 for e in entries if e[0] == (r if isinstance(r, str) else str(r)))
                for r in roots
            }
        }

    @Slot(dict)
    def _on_scan_finished(self, snapshot=None):
        """
        Dokončení skenu: porovná snapshot hash a případně provede UI rebuild.
        Drží UI responsive (rebuild jen při změně a jen když je příslušný widget vidět).
        """
        # odblokuj „běží“
        self._scan_running = False
    
        # Pokud máme pending požadavek (během skenu přišly další změny), naplánujeme další běh
        if getattr(self, "_scan_pending", False):
            self._scan_pending = False
            # malé zpoždění, ať si event loop vydechne
            QTimer.singleShot(120, self.run_scan)
    
        # Bez snapshotu nemáme srovnání (např. fallback cesta)
        if not snapshot or not isinstance(snapshot, dict) or "hash" not in snapshot:
            # Zachováme původní chování, ale odloženě, ať UI stihne reagovat
            QTimer.singleShot(0, self._rebuild_json_right_tree)
            return
    
        new_hash = snapshot.get("hash")
        last_hash = getattr(self, "_last_applied_snapshot_hash", None)
    
        # Pokud se nic nezměnilo, nedělej nic → žádné trhání UI
        if new_hash == last_hash:
            return
    
        # Uložíme posledně aplikovaný snapshot hash
        self._last_applied_snapshot_hash = new_hash
        self._last_snapshot_meta = snapshot  # může se hodit do status baru apod.
    
        # Rebuild náročného stromu dělej jen, když je vidět (uživatel je na záložce)
        try:
            if hasattr(self, "tree") and self.tree.isVisible():
                # Drobný yield do event loopu, aby GUI nezamrzlo
                QTimer.singleShot(0, self._rebuild_json_right_tree)
            else:
                # Není vidět → označíme k pozdější obnově (při další změně nebo po přepnutí záložky)
                self._json_pending_rebuild = True
        except Exception:
            # Bezpečný fallback
            QTimer.singleShot(0, self._rebuild_json_right_tree)

    # --- Strom platných souborů (jen validní názvy) ---
    
    def _capture_rename_tree_state(self) -> list[str]:
        """
        Vezme aktuální strom v záložce 'Přejmenování' a vrátí seznam
        ABSOLUTNÍCH cest adresářů, které jsou ROZBALENÉ.
        (Používáme pro okamžité zachování stavu během přejmenování.)
        """
        paths = []
        if not hasattr(self, "ren_model") or not hasattr(self, "ren_tree"):
            return paths
    
        def walk_dir(item):
            rows = item.rowCount()
            for r in range(rows):
                it = item.child(r)
                if it is None:
                    continue
                if it.data(Qt.UserRole) == "dir":
                    idx = self.ren_model.indexFromItem(it)
                    if self.ren_tree.isExpanded(idx):
                        paths.append(it.data(Qt.UserRole + 1))
                    walk_dir(it)
    
        # top-level
        for rr in range(self.ren_model.rowCount()):
            root_item = self.ren_model.item(rr)
            if root_item and root_item.data(Qt.UserRole) == "dir":
                idx = self.ren_model.indexFromItem(root_item)
                if self.ren_tree.isExpanded(idx):
                    paths.append(root_item.data(Qt.UserRole + 1))
                walk_dir(root_item)
        return paths
    
    def _apply_expand_paths(self, expanded_paths: list[str], collapse_others: bool = False) -> None:
        """
        Aplikuje rozbalení složek podle `expanded_paths`.
        Pokud collapse_others=True, nejprve sbalí všechny složky – standardně NE, aby se minimalizovalo „cukání“.
        """
        if not hasattr(self, "ren_model") or not hasattr(self, "ren_tree") or not hasattr(self, "_ren_dir_items"):
            return
    
        if collapse_others:
            for item in self._ren_dir_items.values():
                if item is None:
                    continue
                idx = self.ren_model.indexFromItem(item)
                if idx.isValid():
                    self.ren_tree.setExpanded(idx, False)
    
        for path_str in expanded_paths or []:
            item = self._ren_dir_items.get(path_str)
            if item is None:
                continue
            idx = self.ren_model.indexFromItem(item)
            if idx.isValid():
                self.ren_tree.setExpanded(idx, True)

    def _rebuild_valid_tree(self, valid_map: Dict[str, List[str]]):
        """
        Postaví model stromu se dvěma top-level uzly (Ořezy/Originály),
        pod nimi reálná složková struktura, listy = ČísloNálezu (z názvu souboru).
        Tooltip listu = celý název souboru; tooltip složek = celá cesta.
        """
        self.tree_model.clear()
        self.tree_model.setHorizontalHeaderLabels(["Soubory"])

        # Root uzly
        mini_root = QStandardItem(self.style().standardIcon(QStyle.SP_DirIcon), "Ořezy")
        mini_root.setEditable(False)
        mini_root.setToolTip(str(OREZY_DIR))

        orig_root = QStandardItem(self.style().standardIcon(QStyle.SP_DirIcon), "Originály")
        orig_root.setEditable(False)
        orig_root.setToolTip(str(ORIGINALS_DIR))

        self.tree_model.appendRow(mini_root)
        self.tree_model.appendRow(orig_root)

        def add_paths(root_item: QStandardItem, root_path: Path, files: List[str]):
            # Map: dir_rel_path -> item
            dir_nodes: Dict[Path, QStandardItem] = {Path("."): root_item}

            for f in files:
                fp = Path(f)
                try:
                    rel = fp.relative_to(root_path)
                except Exception:
                    # Soubor mimo tento root – přeskoč
                    continue

                # vytvoř cestu složek
                parent = root_item
                dir_rel = Path(".")
                for part in rel.parts[:-1]:  # všechny složky
                    dir_rel = dir_rel / part
                    if dir_rel not in dir_nodes:
                        item = QStandardItem(self.style().standardIcon(QStyle.SP_DirIcon), part)
                        item.setEditable(False)
                        item.setToolTip(str(root_path / dir_rel))
                        parent.appendRow(item)
                        dir_nodes[dir_rel] = item
                        parent = item
                    else:
                        parent = dir_nodes[dir_rel]

                # list: číslo nálezu z názvu
                name = rel.name
                m = NAME_PATTERN.match(name)
                if not m:
                    continue
                num = m.group("id")
                leaf = QStandardItem(self.style().standardIcon(QStyle.SP_FileIcon), num)
                leaf.setEditable(False)
                leaf.setToolTip(name)
                parent.appendRow(leaf)

        add_paths(mini_root, OREZY_DIR, valid_map.get(str(OREZY_DIR), []))
        add_paths(orig_root, ORIGINALS_DIR, valid_map.get(str(ORIGINALS_DIR), []))

        # volitelně rozbalit top-level
        self.tree.expand(self.tree_model.indexFromItem(mini_root))
        self.tree.expand(self.tree_model.indexFromItem(orig_root))
        
    def _gather_selected_items(self):
        """
        Vrátí seznam (Path, is_dir) z aktuálního výběru ve stromu.
        Bez duplicit; ignoruje neplatné indexy.
        """
        result = []
        seen = set()
        if not hasattr(self, "ren_tree") or not hasattr(self, "ren_model"):
            return result
    
        indexes = self.ren_tree.selectionModel().selectedIndexes()
        for idx in indexes:
            if not idx.isValid():
                continue
            item = self.ren_model.itemFromIndex(idx)
            if item is None:
                continue
            t = item.data(Qt.UserRole)
            p = item.data(Qt.UserRole + 1)
            if not p:
                continue
            key = (p, t)
            if key in seen:
                continue
            seen.add(key)
            result.append((Path(p), t == "dir"))
        return result

    def _file_numeric_sort_key(self, p: Path):
        """
        Klíč pro řazení souborů: pokud název začíná číslem, řaď podle tohoto čísla,
        jinak fallback na abecední pořadí. Stabilizováno názvem (lower).
        """
        name = p.name
        m = re.match(r"^(\d+)", name)
        if m:
            try:
                return (0, int(m.group(1)), name.lower())
            except Exception:
                pass
        return (1, name.lower())
        
    def _end_rename_grace(self):
        """
        Zavolá se po uplynutí „grace“ (1200 ms od poslední FS změny během rename).
        Tady znovu povolíme watcher signály, spustíme jeden konsolidovaný SCAN a
        odloženě refreshneme watchery (aby neblokovaly kreslení).
        """
        # Ukonči stav „probíhá rename“
        self._rename_in_progress = False
    
        # Znovu povol signály watcheru (až po naplánování práce).
        try:
            self._dir_watcher.blockSignals(False)
        except Exception:
            pass
        self._suspend_fs_events = False
    
        # Jeden konsolidovaný SCAN (přes tvůj debounce – hned)
        try:
            self._debounce_timer.start(0)
        except Exception:
            # fallback, kdyby debounce nebyl k dispozici
            QTimer.singleShot(0, self.run_scan)
    
        # Odložený refresh watcher kořenů – proběhne mimo „kritickou“ část
        try:
            self._watcher_refresh_timer.start()
        except Exception:
            pass
    
        # Indikátory v záložce „Přejmenování“ – spustíme přes stávající timer,
        # ale až teď (po grace), nikoli během rename.
        try:
            self._indicators_timer.start()
        except Exception:
            pass
    
        # vyčisti počitadlo
        self._fs_changes_during_rename = 0
        
    def _parse_ranges_spec(self, spec_list, target_id: int) -> bool:
        """
        Vrátí True, pokud target_id je obsažen v 'spec_list', kde položky jsou:
          - "start-end"  nebo  "cislo".
        """
        if not isinstance(spec_list, list):
            return False
        for token in spec_list:
            try:
                s = str(token).strip()
                if "-" in s:
                    a, b = s.split("-", 1)
                    a, b = int(a), int(b)
                    if a <= target_id <= b:
                        return True
                else:
                    if int(s) == target_id:
                        return True
            except Exception:
                continue
        return False
    
    def _get_current_settings_dicts(self):
        """
        Vrací (lokace, stavy, poznamky, anonym) načtené z editorů.
        anonym má tvar: { "ANONYMIZOVANE": [intervaly/čísla] }
        """
        try:
            lokace = json.loads(self.ed_lokace.toPlainText() or "{}")
        except Exception:
            lokace = {}
        try:
            stavy = json.loads(self.ed_stavy.toPlainText() or "{}")
        except Exception:
            stavy = {}
        try:
            poznamky = json.loads(self.ed_poznamky.toPlainText() or "{}")
        except Exception:
            poznamky = {}
        try:
            anonym = json.loads(self.ed_anonym.toPlainText() or "{}")
        except Exception:
            anonym = {}
        return lokace, stavy, poznamky, anonym

    def _is_id_in_any_json_section(self, find_id: int, lokace: dict, stavy: dict, poznamky: dict, anonym: dict) -> tuple[bool, str]:
        """
        Zjistí, zda 'find_id' figuruje v některé JSON sekci.
        Vrací (True/False, tooltip_text se seznamem zásahů).
        """
        tags = []
    
        # Lokace
        for idlok, spec in (lokace or {}).items():
            if self._parse_ranges_spec(spec, find_id):
                tags.append(f"lokace:{idlok}")
                break
    
        # Stavy
        for stav, spec in (stavy or {}).items():
            if self._parse_ranges_spec(spec, find_id):
                tags.append(f"stav:{stav}")
                break
    
        # Poznámky
        if str(find_id) in (poznamky or {}):
            tags.append("poznámka")
    
        # Anonymizace
        anon_spec = (anonym or {}).get("ANONYMIZOVANE", [])
        if self._parse_ranges_spec(anon_spec, find_id):
            tags.append("anonym")
    
        if tags:
            return True, " • ".join(tags)
        return False, ""
    
    def _schedule_json_autosave(self):
        """Debounce: po úpravě JSON editorů spustí odložené uložení na disk."""
        self._json_autosave_timer.start()
    
    def _autosave_json_settings(self):
        """
        Tiché uložení obsahu editorů do settings/LokaceStavyPoznamky.json.
        - bez reformatování editorů (nepřeskakuje kurzor),
        - s validací stavů,
        - po uložení přebuduje pravý strom (indikace v reálném čase).
        """
        try:
            lokace   = json.loads(self.ed_lokace.toPlainText() or "{}")
            stavy    = json.loads(self.ed_stavy.toPlainText() or "{}")
            poznamky = json.loads(self.ed_poznamky.toPlainText() or "{}")
            anonym   = json.loads(self.ed_anonym.toPlainText() or "{}")
        except Exception:
            return  # tichý fail — editor obsahuje rozpracovaný JSON
    
        # Validace stavů
        unknown = set(stavy.keys()) - ALLOWED_STATES
        if unknown:
            return  # neukládejme nevalidní stavy; uživatel dostane varování při ručním Uložit
    
        data = {"lokace": lokace, "stavy": stavy, "poznamky": poznamky, "anonymizace": anonym}
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            return
    
        # Po tichém uložení jen refresh indikace vpravo (bez „cukání“)
        self._schedule_json_tree_rebuild()
    
    
    def _save_json_tree_state(self):
        """Zapíše stav pravého stromu (rozbalené složky, fokus, scroll) do JSON souboru."""
        if not hasattr(self, "tree_model") or not hasattr(self, "tree"):
            return
    
        # nasnímej aktuální (využij existující helper)
        self._capture_json_tree_state()
        payload = {
            "expanded": self._json_tree_sticky_expand,
            "focus_dir": self._json_tree_sticky_focus_path,
            "scroll": self._json_tree_sticky_scroll,
        }
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            JSON_TREE_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    
    def _restore_json_tree_state(self) -> bool:
        """Načte stav pravého stromu ze souboru a před-nastaví sticky proměnné. Vrací True/False, zda se povedlo načíst."""
        if not JSON_TREE_STATE_FILE.exists():
            return False
        try:
            data = json.loads(JSON_TREE_STATE_FILE.read_text(encoding="utf-8"))
            self._json_tree_sticky_expand = data.get("expanded", []) or []
            self._json_tree_sticky_focus_path = data.get("focus_dir")
            self._json_tree_sticky_scroll = data.get("scroll")
            return True
        except Exception:
            return False

    def _normalize_cislolok(self, text: str) -> str:
        """
        Normalizuje vstup ČísloLokace:
          - přijme číslo o 1–5 číslicích (např. '1' nebo '00001'),
          - vrací NEpadded podobu (např. '1').
        Vyvolá ValueError, pokud vstup není 1–5 číslic.
        """
        s = (text or "").strip()
        if not re.fullmatch(r"\d{1,5}", s):
            raise ValueError("ČísloLokace musí být číslo o 1–5 číslicích (např. 1 nebo 00001).")
        return str(int(s))  # bez počátečních nul
    
    
    def remember_last_loc_assigned(self, file_paths: list[str] | None = None, fids: list[int] | None = None, persist: bool = True):
        """
        Zapamatuje 'posledně přiřazené' fotky. Volej PO úspěšném přiřazení lokace.
        - file_paths: absolutní cesty k souborům (může být None)
        - fids: čísla nálezu (může být None)
        Pokud je předáno obojí, uloží se páry; jinak se uloží, co je k dispozici.
        Historie se ztenčí na max. 50 položek. Volitelně persist do settings/last_loc_assigned.json.
        """
        import json
        from pathlib import Path
    
        # Lazy init historie
        if not hasattr(self, "_last_loc_assigned_history") or not isinstance(self._last_loc_assigned_history, list):
            self._last_loc_assigned_history = []
            try:
                p = Path("settings/last_loc_assigned.json")
                if p.exists():
                    self._last_loc_assigned_history = json.load(open(p, "r", encoding="utf-8")) or []
            except Exception:
                self._last_loc_assigned_history = []
    
        file_paths = file_paths or []
        fids = fids or []
    
        # Normalizace délek: pokud je jedna kolekce prázdná, doplníme None
        n = max(len(file_paths), len(fids), 1)
        if len(file_paths) < n:
            file_paths = file_paths + [None] * (n - len(file_paths))
        if len(fids) < n:
            fids = fids + [None] * (n - len(fids))
    
        # Přidej záznamy (nejnovější na konec), deduplikuj jednoduchým způsobem
        for pth, fid in zip(file_paths, fids):
            entry = {"path": pth, "fid": int(fid) if (fid is not None) else None}
            # Vyhoď úplně prázdný záznam
            if not entry["path"] and entry["fid"] is None:
                continue
            # Pokud už je na konci stejný, nepřidávej duplicitu
            if self._last_loc_assigned_history and self._last_loc_assigned_history[-1] == entry:
                continue
            self._last_loc_assigned_history.append(entry)
    
        # Ořez historie
        if len(self._last_loc_assigned_history) > 50:
            self._last_loc_assigned_history = self._last_loc_assigned_history[-50:]
    
        # Persist
        if persist:
            try:
                Path("settings").mkdir(parents=True, exist_ok=True)
                with open("settings/last_loc_assigned.json", "w", encoding="utf-8") as f:
                    json.dump(self._last_loc_assigned_history, f, ensure_ascii=False, indent=2)
            except Exception:
                pass    
    
    def _focus_last_assigned_location(self):
        """
        Rozbalí složky a zafokusuje 'poslední fotku, které byla přiřazena lokace'.
        Cíl bere z paměťové historie (settings/last_loc_assigned.json), z poslední položky.
        """
        from pathlib import Path
        import json
        from PySide6.QtCore import Qt, QModelIndex
        from PySide6.QtWidgets import QAbstractItemView
    
        if not hasattr(self, "tree_model") or not hasattr(self, "tree"):
            return
    
        # Načti historii (lazy)
        history = getattr(self, "_last_loc_assigned_history", None)
        if history is None:
            try:
                p = Path("settings/last_loc_assigned.json")
                history = json.load(open(p, "r", encoding="utf-8")) if p.exists() else []
            except Exception:
                history = []
            self._last_loc_assigned_history = history
    
        if not history:
            return
    
        # Vezmeme poslední (= nejnovější) záznam
        target = history[-1] or {}
        target_path = target.get("path") or None
        target_fid = target.get("fid") if isinstance(target.get("fid"), int) else None
    
        # Pomocné: najdi index podle uložené cesty (UserRole+1 nese absolutní cestu)
        def _match_index_by_path(path_str: str) -> QModelIndex | None:
            if self.tree_model.rowCount() == 0:
                return None
            root_index = self.tree_model.index(0, 0)
            hits = self.tree_model.match(root_index, Qt.UserRole + 1, path_str, 1, Qt.MatchRecursive | Qt.MatchExactly)
            return hits[0] if hits else None
    
        # Pomocné: najdi index podle čísla nálezu (FID)
        def _match_index_by_fid(fid: int) -> QModelIndex | None:
            import re
            rx = re.compile(rf"^{fid}[_+]")
            def _walk(parent: QModelIndex):
                rows = self.tree_model.rowCount(parent)
                for r in range(rows):
                    idx = self.tree_model.index(r, 0, parent)
                    kind = self.tree_model.data(idx, Qt.UserRole)
                    if kind == "file":
                        p = self.tree_model.data(idx, Qt.UserRole + 1) or ""
                        base = Path(p).name if p else (self.tree_model.data(idx, Qt.DisplayRole) or "")
                        if rx.match(base):
                            return idx
                    found = _walk(idx)
                    if found:
                        return found
                return None
            return _walk(QModelIndex())
    
        # Zjisti index
        index = None
        if isinstance(target_path, str):
            index = _match_index_by_path(target_path)
        if (index is None or not index.isValid()) and (target_fid is not None):
            index = _match_index_by_fid(int(target_fid))
    
        if not index or not index.isValid():
            return
    
        # Rozbal nadřazené větve
        p = index.parent()
        while p.isValid():
            self.tree.expand(p)
            p = p.parent()
    
        # Vyber a vycentruj položku
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index, QAbstractItemView.PositionAtCenter)  
        
    def _teardown_json_tree_jump_button(self):
        """
        Bezpečně odstraní plovoucí tlačítko a jeho eventFilter z pravého stromu.
        (Použitelné např. v closeEvent/tab-change, není však nutné – máme i auto-úklid na destroyed.)
        """
        try:
            ef = getattr(self, "_json_jump_btn_filter", None)
            if ef and hasattr(self, "tree") and self.tree:
                try:
                    vp = self.tree.viewport()
                    if vp:
                        vp.removeEventFilter(ef)
                except Exception:
                    pass
            btn = getattr(self, "_json_jump_btn", None)
            if btn:
                try:
                    btn.hide()
                    btn.setParent(None)
                    btn.deleteLater()
                except Exception:
                    pass
        finally:
            try:
                self._json_jump_btn = None
                self._json_jump_btn_filter = None
            except Exception:
                pass
    
    def _ensure_json_tree_jump_button(self):
        """
        Plovoucí tlačítko v pravém stromu („Nastavení JSONů“), které rozbalí strom
        k naposledy přiřazené fotce. Umístění bez zásahu do layoutu – nahoře vpravo.
        OŠETŘENO proti pádu při zavírání okna (strom může být již zničen).
        """
        from PySide6.QtWidgets import QToolButton
        from PySide6.QtCore import Qt, QEvent, QObject
        import weakref
    
        if not hasattr(self, "tree") or self.tree is None:
            return
    
        # Pokud už je tlačítko vytvořené, jen ho znovu umísti a ukaž
        if getattr(self, "_json_jump_btn", None) is not None:
            try:
                vp = self.tree.viewport()
                self._json_jump_btn.setParent(vp)
                self._json_jump_btn.adjustSize()
                rect = vp.rect()
                self._json_jump_btn.move(rect.right() - self._json_jump_btn.width() - 10, rect.top() + 8)
                self._json_jump_btn.show()
            except Exception:
                pass
            return
    
        # Nové tlačítko
        try:
            vp = self.tree.viewport()
        except Exception:
            return
    
        btn = QToolButton(vp)
        btn.setText("⮕ Poslední přiřazená lokace")
        btn.setToolTip("Rozbalí strom k fotce, které byla naposledy přiřazena lokace.")
        btn.setAutoRaise(True)
        btn.clicked.connect(self._focus_last_assigned_location)
        btn.setStyleSheet("""
            QToolButton {
                background: rgba(30,30,30,180);
                padding: 4px 8px;
                border-radius: 6px;
                border: 1px solid rgba(255,255,255,40);
                font-size: 11px;
            }
            QToolButton:hover { background: rgba(45,45,45,220); }
        """)
        self._json_jump_btn = btn
    
        # Bezpečný event filter – odolný proti zničení stromu/viewportu
        class _OverlayEF(QObject):
            def __init__(self, tree_ref, btn):
                super().__init__()
                self._tree_ref = tree_ref   # weakref na QTreeView
                self._btn = btn
                self._dead = False
    
            def mark_dead(self):
                self._dead = True
    
            def eventFilter(self, obj, ev):
                if self._dead:
                    return False
                tree = self._tree_ref()
                if tree is None:
                    return False
                try:
                    vp = tree.viewport()
                except RuntimeError:
                    # C++ objekt už neexistuje
                    return False
    
                # Jen když event přichází z viewportu
                try:
                    if obj is vp and ev.type() in (QEvent.Resize, QEvent.Paint, QEvent.Wheel, QEvent.Show):
                        rect = vp.rect()
                        try:
                            self._btn.adjustSize()
                            self._btn.move(rect.right() - self._btn.width() - 10, rect.top() + 8)
                        except RuntimeError:
                            return False
                except RuntimeError:
                    return False
                return False
    
        tree_ref = weakref.ref(self.tree)
        ef = _OverlayEF(tree_ref, btn)
        self._json_jump_btn_filter = ef
    
        # instalace filtru
        vp.installEventFilter(ef)
    
        # úklid při zničení stromu (nebo viewportu)
        def _on_tree_destroyed(*_):
            try:
                ef.mark_dead()
            except Exception:
                pass
            try:
                if vp:
                    vp.removeEventFilter(ef)
            except Exception:
                pass
            try:
                if btn:
                    btn.hide()
                    btn.setParent(None)
                    btn.deleteLater()
            except Exception:
                pass
            try:
                self._json_jump_btn = None
                self._json_jump_btn_filter = None
            except Exception:
                pass
    
        try:
            self.tree.destroyed.connect(_on_tree_destroyed)
            vp.destroyed.connect(_on_tree_destroyed)
        except Exception:
            pass
    
        # první umístění
        try:
            rect = vp.rect()
            btn.adjustSize()
            btn.move(rect.right() - btn.width() - 10, rect.top() + 8)
            btn.show()
        except Exception:
            pass

    def _rebuild_json_right_tree(self):
        """
        Naplní pravý strom v záložce 'Nastavení JSON' obsahem složky Originály (rekurzivně),
        ignoruje skryté položky. Soubory řadí NUMERICKY dle prvních číslic v názvu.
        Indikace přes badges za názvem (✅ ⚙️ 📝 🔒). Varování 'stav bez poznámky' je v tooltipu.
        Zachová rozbalení, fokus a scroll (sticky) a stav perzistuje do souboru.
        """
        if not hasattr(self, "tree_model") or not hasattr(self, "tree"):
            return
    
        # Pokud sticky zatím není, zkus z disku
        if not getattr(self, "_json_filter_active", False):
            if not getattr(self, "_json_tree_sticky_expand", None) and not getattr(self, "_json_tree_sticky_focus_path", None):
                self._restore_json_tree_state()
    
        lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
    
        from pathlib import Path
        import re
        from PySide6.QtGui import QStandardItem
        from PySide6.QtWidgets import QStyle
        from PySide6.QtCore import Qt, QTimer
    
        def is_hidden(p: Path) -> bool:
            name = p.name
            return name.startswith(".") or name.lower() in {"thumbs.db", "desktop.ini"}
    
        def parse_leading_int(name: str):
            m = re.match(r"^(\d+)", name)
            return int(m.group(1)) if m else None
    
        def sort_key(p: Path):
            n = parse_leading_int(p.name)
            return (0 if p.is_dir() else 1, n if n is not None else 10**9, p.name.lower())
    
        # Zachování rozbalení/fokusu/scrollu
        self._capture_json_tree_state()
        self.tree.setUpdatesEnabled(False)
    
        missing_note_ids_accum = set()
    
        try:
            self.tree_model.clear()
            self.tree.setModel(self.tree_model)
    
            self.tree_model.setHorizontalHeaderLabels(["Soubor / složka (včetně indikátorů)"])
            self._json_dir_items = {}
    
            def make_dir_item(path: Path):
                it = QStandardItem(self.style().standardIcon(QStyle.SP_DirIcon), path.name)
                it.setEditable(False)
                it.setToolTip(str(path))
                it.setData("dir", Qt.UserRole)
                it.setData(str(path), Qt.UserRole + 1)
                self._json_dir_items[str(path)] = it
                return it
    
            def make_file_item(path: Path):
                m = re.match(r"^(\d+)[_+]", path.name)
                fid = None
                if m:
                    try:
                        fid = int(m.group(1))
                    except Exception:
                        fid = None
    
                badges_txt = ""
                if fid is not None:
                    badges_txt = self._json_badges_for_id(fid, lokace, stavy, poznamky, anonym)
    
                icon = self.style().standardIcon(QStyle.SP_FileIcon)
                label_text = path.name if not badges_txt else f"{path.name}    {badges_txt}"
    
                it = QStandardItem(icon, label_text)
                it.setEditable(False)
    
                tip_lines = [str(path)]
                if fid is not None:
                    tip_lines.append(f"ČísloNálezu: {fid}")
    
                    tags = []
                    for idlok, spec in (lokace or {}).items():
                        if self._parse_ranges_spec(spec, fid):
                            tags.append(f"lokace:{idlok}")
                            break
                    has_state = False
                    for s, spec in (stavy or {}).items():
                        if self._parse_ranges_spec(spec, fid):
                            has_state = True
                            tags.append(f"stav:{s}")
                            break
                    has_note = str(fid) in (poznamky or {})
                    if has_note:
                        tags.append("poznámka")
                    anon_spec = (anonym or {}).get("ANONYMIZOVANE", [])
                    if self._parse_ranges_spec(anon_spec, fid):
                        tags.append("anonym")
                    if tags:
                        tip_lines.append("JSON: " + " • ".join(tags))
                    if has_state and not has_note:
                        tip_lines.append("⚠ Stav bez poznámky (vyžadováno pro: BEZFOTKY, DAROVANY)")
    
                # datum/čas vytvoření
                try:
                    st = path.stat()
                    ts = getattr(st, "st_birthtime", None) or st.st_mtime
                    from datetime import datetime
                    dt = datetime.fromtimestamp(ts)
                    tip_lines.append(f"Vytvořeno: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                except Exception:
                    pass
    
                it.setToolTip("\n".join(tip_lines))
                it.setData("file", Qt.UserRole)
                it.setData(str(path), Qt.UserRole + 1)
                return it
    
            def populate(parent_item: QStandardItem, folder: Path) -> tuple[int, int]:
                """
                Naplní uzel složky a rekurzivně spočítá:
                  - total_files: celkový počet souborů v této složce (rekurzivně),
                  - with_loc: kolik z nich má přiřazenou lokaci.
                Vrací (total_files, with_loc). Po naplnění upraví popisek složky:
                pokud with_loc == total_files > 0, doplní za název složky indikaci ✅.
                """
                try:
                    entries = [p for p in folder.iterdir() if not is_hidden(p)]
                except Exception:
                    return 0, 0
                dirs = sorted((p for p in entries if p.is_dir()), key=sort_key)
                files = sorted((p for p in entries if p.is_file()), key=sort_key)
            
                total_files = 0
                with_loc = 0
            
                # Nejprve složky
                for d in dirs:
                    dit = make_dir_item(d)
                    parent_item.appendRow(dit)
                    t, w = populate(dit, d)
                    total_files += t
                    with_loc += w
            
                # Pak soubory
                for f in files:
                    fit = make_file_item(f)
                    parent_item.appendRow(fit)
                    # spočti, zda má soubor lokaci (pokud umíme vyčíst fid)
                    m = re.match(r"^(\d+)[_+]", f.name)
                    fid = None
                    if m:
                        try:
                            fid = int(m.group(1))
                        except Exception:
                            fid = None
                    total_files += 1
                    if fid is not None:
                        try:
                            has_loc = False
                            for idlok, spec in (lokace or {}).items():
                                if self._parse_ranges_spec(spec, fid):
                                    has_loc = True
                                    break
                            if has_loc:
                                with_loc += 1
                        except Exception:
                            pass
            
                # Aktualizuj label složky podle výsledku
                try:
                    if total_files > 0 and with_loc == total_files:
                        base_text = parent_item.text().split('    ')[0]  # odstraň případné staré badge
                        parent_item.setText(f"{base_text}    ✅")
                except Exception:
                    pass
            
                return total_files, with_loc
    
            try:
                root_path = ORIGINALS_DIR
            except Exception:
                root_path = Path.cwd()
    
            root_item = make_dir_item(root_path)
            self.tree_model.appendRow(root_item)
            populate(root_item, root_path)
            self.tree.expand(root_item.index())
    
            try:
                if missing_note_ids_accum:
                    self.lbl_consistency.setText("⚠ Kontrola: existují čísla se stavem bez poznámky")
                    short_list = ", ".join(map(str, sorted(list(missing_note_ids_accum))[:50]))
                    self.lbl_consistency.setToolTip(short_list + (" …" if len(missing_note_ids_accum) > 50 else ""))
                    self.lbl_consistency.setStyleSheet("QLabel { color: #b58900; font-weight: 600; }")
                else:
                    self.lbl_consistency.setText("✓ Kontrola: vše v pořádku (všechna čísla se stavem mají poznámku)")
                    self.lbl_consistency.setToolTip("")
                    self.lbl_consistency.setStyleSheet("QLabel { color: #2aa198; font-weight: 600; }")
            except Exception:
                pass
    
            if getattr(self, "_json_filter_active", False):
                # Během filtru NEsaháme na sticky stav, pouze znovu aplikujeme filtr
                try:
                    pat = (self.json_tree_filter.text() or "").strip().lower()
                    self._json_tree_apply_filter(pat)
                except Exception:
                    pass
            else:
                self._apply_json_tree_state()
                self._save_json_tree_state()
            
            # Zajisti (bezpečné) plovoucí tlačítko
    
            # Zajisti (bezpečné) plovoucí tlačítko
            QTimer.singleShot(0, self._ensure_json_tree_jump_button)
    
            # Jednorázové auto-zobrazení „poslední přiřazené“ po otevření záložky
            if not hasattr(self, "_json_auto_jump_pending"):
                self._json_auto_jump_pending = True
            if getattr(self, "_json_auto_jump_pending", False):
                def _auto_jump():
                    try:
                        self._focus_last_assigned_location()
                    finally:
                        # už neautomaticky při dalších rebuildech
                        self._json_auto_jump_pending = False
                QTimer.singleShot(0, _auto_jump)
    
        finally:
            self.tree.setUpdatesEnabled(True)

    def _capture_json_tree_state(self):
        """Uloží aktuální rozbalené složky, fokus (složka) a scroll pravého stromu (JSON záložka)."""
        self._json_tree_sticky_expand = []
        if not hasattr(self, "tree_model") or not hasattr(self, "tree"):
            return
    
        # expanded dirs
        def walk_dir(item: QStandardItem):
            for r in range(item.rowCount()):
                it = item.child(r)
                if it is None:
                    continue
                if it.data(Qt.UserRole) == "dir":
                    idx = self.tree_model.indexFromItem(it)
                    if self.tree.isExpanded(idx):
                        self._json_tree_sticky_expand.append(it.data(Qt.UserRole + 1))
                    walk_dir(it)
    
        for rr in range(self.tree_model.rowCount()):
            root_item = self.tree_model.item(rr)
            if root_item and root_item.data(Qt.UserRole) == "dir":
                idx = self.tree_model.indexFromItem(root_item)
                if self.tree.isExpanded(idx):
                    self._json_tree_sticky_expand.append(root_item.data(Qt.UserRole + 1))
                walk_dir(root_item)
    
        # fokus (aktuální výběr → složka)
        self._json_tree_sticky_focus_path = None
        try:
            idx = self.tree.currentIndex()
            if idx.isValid():
                it = self.tree_model.itemFromIndex(idx)
                if it:
                    if it.data(Qt.UserRole) == "file":
                        # soubor → fokus složka = parent
                        parent = it.parent()
                        if parent:
                            self._json_tree_sticky_focus_path = parent.data(Qt.UserRole + 1)
                    elif it.data(Qt.UserRole) == "dir":
                        self._json_tree_sticky_focus_path = it.data(Qt.UserRole + 1)
        except Exception:
            pass
    
        # scroll
        try:
            self._json_tree_sticky_scroll = self.tree.verticalScrollBar().value()
        except Exception:
            self._json_tree_sticky_scroll = None
    
    
    def _apply_json_tree_state(self):
        """Aplikuje uložený sticky stav pravého stromu – expanze, fokus, scroll – bez kolapsu ostatních."""
        if not hasattr(self, "tree_model") or not hasattr(self, "tree"):
            return
        # expand
        for path_str in self._json_tree_sticky_expand or []:
            item = getattr(self, "_json_dir_items", {}).get(path_str)
            if not item:
                continue
            idx = self.tree_model.indexFromItem(item)
            if idx.isValid():
                self.tree.setExpanded(idx, True)
    
        # fokus
        if self._json_tree_sticky_focus_path:
            item = getattr(self, "_json_dir_items", {}).get(self._json_tree_sticky_focus_path)
            if item:
                idx = self.tree_model.indexFromItem(item)
                if idx.isValid():
                    self.tree.setCurrentIndex(idx)
                    sel = self.tree.selectionModel()
                    if sel:
                        sel.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current)
                    self.tree.scrollTo(idx)
    
        # scroll
        try:
            if self._json_tree_sticky_scroll is not None:
                self.tree.verticalScrollBar().setValue(self._json_tree_sticky_scroll)
        except Exception:
            pass
    
    def _schedule_json_tree_rebuild(self):
        """
        Debounce: zachyť aktuální stav a odlož přestavění pravého stromu.
        (Zajišťuje realtime aktualizaci „indikace v JSONu“ bez uskakování UI.)
    
        NOVĚ:
          • Líná (lazy) inicializace spodního indikátoru pod stromem.
          • Okamžité přepočítání integrity (duplicit v lokacích/stavech/poznámkách a chybějící
            anonymizace pro lokace, které vyžadují anonymizaci).
        """
        # 1) Zachyť aktuální stav jako dosud
        self._capture_json_tree_state()
    
        # 2) Lazy vytvoření spodního indikátoru a vložení PŘÍMO POD strom v pravém panelu
        try:
            from PySide6.QtWidgets import QLabel, QWidget
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QFont
            if hasattr(self, "tree") and isinstance(self.tree, QWidget):
                if not hasattr(self, "lbl_json_issues") or self.lbl_json_issues is None:
                    self.lbl_json_issues = QLabel("Integrita JSONů: …", parent=self.tree.parent())
                    self.lbl_json_issues.setWordWrap(True)
                    # jemné odlišení + monospace pro čitelnost ID
                    f = QFont(self.font())
                    f.setStyleHint(QFont.Monospace)
                    f.setFamily("monospace")
                    self.lbl_json_issues.setFont(f)
                    self.lbl_json_issues.setTextInteractionFlags(
                        Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
                    )
                    # vložit POD strom (strom je ve vlt layoutu uvnitř groupboxu)
                    parent = self.tree.parent()
                    lay = parent.layout() if parent is not None else None
                    if lay is not None:
                        lay.addWidget(self.lbl_json_issues)
        except Exception:
            # Pokud by se nepovedlo vytvořit indikátor, plynule pokračujeme (nenaruší stávající chování)
            pass
    
        # 3) Okamžitě přepočti a zobraz indikaci integrity (bez nutnosti čekat na rebuild)
        try:
            lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
            self._update_json_integrity_indicator(lokace, stavy, poznamky, anonym)
        except Exception:
            # Nikdy neblokovat UI
            pass
    
        # 4) Původní chování: spustit odložený rebuild pravého stromu
        self._json_rebuild_timer.start()
        
    def _on_json_tree_filter_text_changed(self, text: str):
        """
        Filtrování stromu souborů vpravo podle textu ve filtru.
        - Aktivuje se pouze při psaní do pole (textChanged signál).
        - Při PRVNÍM zapnutí filtru se uloží stav stromu (expanze/fokus/scroll),
          aby bylo možné rozhodnout, co dělat po vymazání filtru.
        - BĚHEM filtru se sticky stav NEaplikuje (při rebuildech),
          místo toho se jen znovu aplikuje filtr.
        - PŘI VYMAZÁNÍ FILTRU:
            * Zruší se skrývání (vše viditelné),
            * Strom se celý SBALÍ,
            * Rozbalí se POUZE složka s naposledy přiřazenou lokací
              (aplikace si tento příznak pamatuje; použije se _focus_last_assigned_location()),
            * Zachytí se tento nový stav jako výchozí (sticky).
        """
        try:
            if not hasattr(self, "_json_filter_active"):
                self._json_filter_active = False
                self._json_tree_state_before_filter = None
    
            pattern = (text or "").strip().lower()
    
            # Vstup do filtru: ulož původní stav stromu (jen jednou při přechodu z neaktivního do aktivního)
            if pattern and not self._json_filter_active:
                self._capture_json_tree_state()
                self._json_tree_state_before_filter = {
                    "expanded": list(self._json_tree_sticky_expand or []),
                    "focus_dir": self._json_tree_sticky_focus_path,
                    "scroll": self._json_tree_sticky_scroll,
                }
                self._json_filter_active = True
    
            # Opouštím filtr: zruš skrývání a nastav požadovaný nový výchozí stav
            if pattern == "":
                view = getattr(self, "tree", None)
                model = getattr(self, "tree_model", None)
                if view is None or model is None:
                    # bezpečný návrat
                    self._json_filter_active = False
                    self._json_tree_state_before_filter = None
                    return
    
                view.setUpdatesEnabled(False)
                try:
                    # 1) zruš skrytí (vše viditelné)
                    self._json_tree_show_all()
    
                    # 2) sbal celý strom
                    try:
                        view.collapseAll()
                    except Exception:
                        # fallback: ruční rekurzivní sbalení by šlo doplnit, ale QTreeView.collapseAll by měl být dostupný
                        pass
    
                    # 3) rozbal pouze větev k naposledy přiřazené lokaci (a nastav fokus)
                    try:
                        self._focus_last_assigned_location()
                    except Exception:
                        # pokud není co rozbalit/fokusovat, necháme strom prostě sbalený
                        pass
    
                    # 4) zachyť tento stav jako nový sticky (aby se držel i po případném rebuildu)
                    self._capture_json_tree_state()
    
                finally:
                    view.setUpdatesEnabled(True)
    
                # filter mód ukončen
                self._json_filter_active = False
                self._json_tree_state_before_filter = None
                return
    
            # Aplikace filtru (pattern != "")
            self._json_tree_apply_filter(pattern)
    
        except Exception:
            # nechceme padat kvůli filtru
            pass

    def _json_tree_show_all(self):
        """Zruší skrytí všech řádků ve stromu (bez zásahu do expanzí)."""
        model = self.tree_model
        view = self.tree
        if model is None or view is None:
            return
    
        view.setUpdatesEnabled(False)
        try:
            def recurse(parent_index):
                rows = model.rowCount(parent_index)
                for r in range(rows):
                    view.setRowHidden(r, parent_index, False)
                    idx = model.index(r, 0, parent_index)
                    recurse(idx)
            recurse(QModelIndex())
        finally:
            view.setUpdatesEnabled(True)

    def _json_tree_apply_filter(self, pattern: str):
        """
        Skryje všechny uzly, které (ani žádný jejich potomek) neobsahují pattern v textu.
        Rozbalí pouze nadřazené větve k viditelným položkám (aby byly skutečně vidět),
        ale globálně neexpanduje celý strom.
        """
        model = self.tree_model
        view = self.tree
        if model is None or view is None:
            return
    
        def node_matches(idx):
            try:
                text = model.data(idx) or ""
                return pattern in str(text).lower()
            except Exception:
                return False
    
        view.setUpdatesEnabled(False)
        try:
            def recurse(parent_index):
                rows = model.rowCount(parent_index)
                any_visible = False
                for r in range(rows):
                    idx = model.index(r, 0, parent_index)
    
                    # Rekurze do potomků
                    child_visible = recurse(idx)
    
                    # Shoda na aktuálním uzlu (case-insensitive)
                    self_visible = node_matches(idx)
    
                    # Viditelnost: uzel sám nebo některý potomek odpovídá filtru
                    visible = self_visible or child_visible
    
                    # Schovej/ukaž aktuální řádek
                    view.setRowHidden(r, parent_index, not visible)
    
                    # Pokud je cokoliv v této větvi viditelné, rozbal cestu k tomuto uzlu (jen předky)
                    if visible:
                        p = parent_index
                        while p.isValid():
                            view.setExpanded(p, True)
                            p = p.parent()
    
                    any_visible = any_visible or visible
                return any_visible
    
            # Spusť od kořene
            recurse(QModelIndex())
        finally:
            view.setUpdatesEnabled(True)
        
    def _update_json_integrity_indicator(self, lokace: dict, stavy: dict, poznamky: dict, anonym: dict):
        """
        Přepočítá a vykreslí indikaci integrity JSONů ve spodní části pravého panelu (pod stromem).
    
        Kontroluje:
          1) Duplicitní přiřazení jednoho ČíslaNálezu do více LOKACÍ (různé klíče v 'lokace').
          2) Duplicitní přiřazení jednoho ČíslaNálezu do více STAVŮ (různé klíče ve 'stavy').
          3) (Volitelně) Duplicitní přiřazení u POZNÁMEK – jen pokud jsou ve formátu „label -> intervaly/čísla“.
             (Pokud jsou poznámky jako {"12345": "text"}, duplicity se nehodnotí.)
          4) Chybějící ANONYMIZACI pro fotky, které jsou v lokaci vyžadující anonymizaci
             (detekováno z metadat map: „Anonymizovaná lokace: Ano“).
    
        NOVĚ – podrobnější výpis názvy lokací:
          • U konfliktů i u chybějící anonymizace vypisujeme místo L<číslo> název lokace
            (první část názvu souboru lokační mapy před '+'). Pokud název nelze určit,
            použije se „Lokace <číslo>“ jako fallback.
        """
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QLabel
        import re as _re
    
        lbl: QLabel | None = getattr(self, "lbl_json_issues", None)
        if lbl is None:
            return  # indikátor zatím neexistuje (vytváří se líně v _schedule_json_tree_rebuild)
    
        # ---------- Pomocné funkce ----------
        def _safe_int(x):
            try:
                return int(x)
            except Exception:
                return None
    
        def _numbers_from_spec_map(d: dict) -> dict[int, set[str]]:
            """
            Z 'mapy' {key: [spec,...]} složí mapu {id: {key1,key2,..}}.
            Využívá existující self._numbers_from_intervals.
            """
            id_to_keys: dict[int, set[str]] = {}
            if not isinstance(d, dict):
                return id_to_keys
            for key, spec in d.items():
                try:
                    ids = self._numbers_from_intervals(spec)
                except Exception:
                    ids = set()
                for i in ids:
                    id_to_keys.setdefault(int(i), set()).add(str(key))
            return id_to_keys
    
        def _keys_to_ids_map(d: dict) -> dict[str, set[int]]:
            """
            Inverzní pohled: {key: {ids...}}. Použije self._numbers_from_intervals.
            """
            out: dict[str, set[int]] = {}
            if not isinstance(d, dict):
                return out
            for key, spec in d.items():
                try:
                    ids = self._numbers_from_intervals(spec)
                except Exception:
                    ids = set()
                out[str(key)] = set(int(i) for i in ids)
            return out
    
        def _dup_ids(id_to_keys: dict[int, set[str]]) -> set[int]:
            return {i for i, ks in id_to_keys.items() if len(ks) > 1}
    
        def _conflict_ids_per_key(keys_to_ids: dict[str, set[int]], id_to_keys: dict[int, set[str]]) -> dict[str, list[int]]:
            """
            Pro každý key vrátí seznam ID, která jsou zároveň i v jiném key (tj. skutečný konflikt).
            """
            out: dict[str, list[int]] = {}
            for k, ids in keys_to_ids.items():
                conflicted = [i for i in ids if len(id_to_keys.get(i, set())) > 1]
                if conflicted:
                    out[k] = sorted(conflicted)
            return out
    
        def _fmt_ids(ids: list[int] | set[int], limit: int = 18) -> str:
            ids_list = sorted(int(x) for x in ids)
            if len(ids_list) <= limit:
                return ", ".join(map(str, ids_list))
            return ", ".join(map(str, ids_list[:limit])) + f" (+{len(ids_list) - limit})"
    
        # Pomocné: extrakce čísla lokace z názvu souboru
        def _extract_numeric_location_id_from_filename(filename: str) -> int | None:
            parts = (filename or "").split('+')
            last = parts[-1] if parts else (filename or "")
            base = last.split('.')[0] if '.' in last else last
            m = _re.search(r'(\d{1,5})$', base)
            return int(m.group(1)) if m else None
    
        # ---------- 0) Mapa „ČísloLokace (normalizované)“ → „Název lokace (první část názvu souboru)“ ----------
        loc_key_to_name: dict[str, str] = {}
        try:
            for md in self._get_available_location_maps_from_dir() or []:
                fname = md.get("filename", "") or ""
                first_name = (fname.split('+')[0].strip() if '+' in fname else fname).strip() or None
                # zjisti normalizovaný klíč lokace
                key = None
                c5 = md.get("cislolok5")
                if c5:
                    try:
                        key = self._normalize_cislolok(str(c5))
                    except Exception:
                        key = None
                if key is None:
                    num = _extract_numeric_location_id_from_filename(fname)
                    if num is not None:
                        try:
                            key = self._normalize_cislolok(str(num))
                        except Exception:
                            key = None
                if key:
                    loc_key_to_name.setdefault(key, first_name or f"Lokace {key}")
        except Exception:
            # fallback: prázdná mapa -> budeme zobrazovat „Lokace <key>“
            loc_key_to_name = {}
    
        def _display_loc_name(key: str) -> str:
            return loc_key_to_name.get(key, f"Lokace {key}")
    
        def _sort_keys_by_loc_name(keys: list[str]) -> list[str]:
            return sorted(keys, key=lambda k: (loc_key_to_name.get(k, f"Lokace {k}").lower(), k))
    
        # ---------- 1) Duplicitní lokace / stavy / poznámky ----------
        id2loc = _numbers_from_spec_map(lokace or {})
        id2sta = _numbers_from_spec_map(stavy or {})
        dup_loc_ids_set = _dup_ids(id2loc)
        dup_sta_ids_set = _dup_ids(id2sta)
    
        k2ids_loc = _keys_to_ids_map(lokace or {})
        k2ids_sta = _keys_to_ids_map(stavy or {})
    
        # rozpis per-key: pouze ID, která jsou v konfliktu
        k2conf_loc = _conflict_ids_per_key(k2ids_loc, id2loc)
        k2conf_sta = _conflict_ids_per_key(k2ids_sta, id2sta)
    
        # Poznámky – jen pokud mají formu {label: [intervaly/čísla]}
        k2conf_poz: dict[str, list[int]] = {}
        dup_poz_ids_set: set[int] = set()
        if isinstance(poznamky, dict) and any(isinstance(v, (list, tuple)) for v in poznamky.values()):
            id2poz = _numbers_from_spec_map(poznamky)
            dup_poz_ids_set = _dup_ids(id2poz)
            k2ids_poz = _keys_to_ids_map(poznamky)
            k2conf_poz = _conflict_ids_per_key(k2ids_poz, id2poz)
    
        # ---------- 2) Lokace vyžadující anonymizaci a chybějící anonymizace ----------
        # Cache metadat map (aby se zbytečně neotvíraly stále dokola)
        if not hasattr(self, "_anon_flag_cache"):
            self._anon_flag_cache = {}  # {absolute_path: bool}
    
        def _read_anonym_flag_from_metadata(image_path: str) -> bool:
            if not image_path:
                return False
            if image_path in self._anon_flag_cache:
                return self._anon_flag_cache[image_path]
            flag = False
            try:
                from PIL import Image as _Image
                with _Image.open(image_path) as img:
                    # a) text pole
                    if hasattr(img, "text") and isinstance(img.text, dict):
                        for k, v in img.text.items():
                            ks = str(k).strip().lower()
                            vs = str(v).strip().lower()
                            if "anonym" in ks or "anonym" in vs:
                                if "ano" in vs or "yes" in vs or "true" in vs or vs == "1":
                                    flag = True
                                    break
                    # b) info pole
                    if not flag and isinstance(img.info, dict):
                        for k, v in img.info.items():
                            ks = str(k).strip().lower()
                            vs = str(v).strip().lower()
                            if "anonym" in ks or "anonym" in vs:
                                if "ano" in vs or "yes" in vs or "true" in vs or vs == "1":
                                    flag = True
                                    break
            except Exception:
                flag = False
            self._anon_flag_cache[image_path] = flag
            return flag
    
        # z map ve složce vyrob množinu normalizovaných klíčů lokací, které vyžadují anonymizaci
        requires_anon_keys: set[str] = set()
        try:
            for md in self._get_available_location_maps_from_dir() or []:
                abs_path = md.get("absolute", "") or ""
                if not _read_anonym_flag_from_metadata(abs_path):
                    continue
                # normalizovaný klíč lokace
                key = None
                c5 = md.get("cislolok5")
                if c5:
                    try:
                        key = self._normalize_cislolok(str(c5))
                    except Exception:
                        key = None
                if key is None:
                    fname = md.get("filename", "") or ""
                    num = _extract_numeric_location_id_from_filename(fname)
                    if num is not None:
                        try:
                            key = self._normalize_cislolok(str(num))
                        except Exception:
                            key = None
                if key:
                    requires_anon_keys.add(key)
        except Exception:
            requires_anon_keys = set()
    
        # vytažení specifikace anonymizovaných ID z JSONu „anonym“
        anon_spec = None
        if isinstance(anonym, dict):
            for k in ("ANONYMIZOVANE", "ANONYM", "ANON", "ANONYMIZACE"):
                if k in anonym:
                    anon_spec = anonym.get(k)
                    break
    
        def _is_anon(idnum: int) -> bool:
            if anon_spec is None:
                return False
            # primárně zkusit parser rozsahů, jinak fallback rozbalení
            try:
                return bool(self._parse_ranges_spec(anon_spec, int(idnum)))
            except Exception:
                try:
                    return int(idnum) in self._numbers_from_intervals(anon_spec)
                except Exception:
                    return False
    
        missing_anon_ids: set[int] = set()
        missing_by_loc_key: dict[str, list[int]] = {}
    
        if isinstance(lokace, dict) and requires_anon_keys:
            for raw_key, spec in lokace.items():
                try:
                    key = self._normalize_cislolok(str(raw_key))
                except Exception:
                    continue
                if key not in requires_anon_keys:
                    continue
                try:
                    ids_here = self._numbers_from_intervals(spec)
                except Exception:
                    ids_here = set()
                miss_here = [int(pid) for pid in ids_here if not _is_anon(int(pid))]
                if miss_here:
                    miss_here_sorted = sorted(miss_here)
                    missing_by_loc_key[key] = miss_here_sorted
                    missing_anon_ids.update(miss_here_sorted)
    
        # ---------- Výstup do labelu ----------
        has_any_issue = (
            bool(dup_loc_ids_set) or bool(dup_sta_ids_set) or bool(dup_poz_ids_set) or bool(missing_anon_ids)
        )
    
        if not has_any_issue:
            lbl.setText("✓ Integrita JSONů: vše v pořádku")
            lbl.setStyleSheet("QLabel { color: #2aa198; font-weight: 600; }")
            lbl.setToolTip("")
            return
    
        # Podrobnější LABEL (word-wrap) + plný TOOLTIP
        sec_lines_label: list[str] = []
        sec_lines_tip: list[str] = []
    
        # --- Lokace – konflikty (vážeme na názvy lokací) ---
        if k2conf_loc:
            sec_lines_label.append("• Lokace – konflikty:")
            for key in _sort_keys_by_loc_name(list(k2conf_loc.keys())):
                ids = k2conf_loc[key]
                name = _display_loc_name(key)
                sec_lines_label.append(f"   {name}: { _fmt_ids(ids, limit=18) }")
            # tooltip – plné výpisy
            sec_lines_tip.append("Lokace – konflikty (ID přiřazená ve více lokacích):")
            for key in _sort_keys_by_loc_name(list(k2conf_loc.keys())):
                ids = k2conf_loc[key]
                name = _display_loc_name(key)
                sec_lines_tip.append(f"  {name}: { ', '.join(map(str, sorted(ids))) }")
    
        # --- Stavy – konflikty (ponecháno jako dříve; klíče stavů necháváme jak jsou) ---
        if k2conf_sta:
            sec_lines_label.append("• Stavy – konflikty:")
            # pokus o číselné řazení, jinak lexikograficky
            def _sort_keys_numeric_str(keys: list[str]) -> list[str]:
                nums, texts = [], []
                for k in keys:
                    n = _safe_int(k)
                    (nums if n is not None else texts).append((n if n is not None else 0, k))
                nums.sort(key=lambda t: t[0])
                texts.sort(key=lambda t: t[1])
                return [k for _, k in nums] + [k for _, k in texts]
            for key in _sort_keys_numeric_str(list(k2conf_sta.keys())):
                ids = k2conf_sta[key]
                sec_lines_label.append(f"   {key}: { _fmt_ids(ids, limit=18) }")
            sec_lines_tip.append("Stavy – konflikty (ID přiřazená ve více stavech):")
            for key in _sort_keys_numeric_str(list(k2conf_sta.keys())):
                ids = k2conf_sta[key]
                sec_lines_tip.append(f"  {key}: { ', '.join(map(str, sorted(ids))) }")
    
        # --- Poznámky – konflikty (jen „label -> intervaly“) ---
        if k2conf_poz:
            sec_lines_label.append("• Poznámky – konflikty:")
            # pro poznámky necháváme řazení podle názvu labelu
            for key in sorted(k2conf_poz.keys(), key=lambda s: s.lower()):
                ids = k2conf_poz[key]
                sec_lines_label.append(f"   {key}: { _fmt_ids(ids, limit=18) }")
            sec_lines_tip.append("Poznámky – konflikty (ID přiřazená ve více poznámkových skupinách):")
            for key in sorted(k2conf_poz.keys(), key=lambda s: s.lower()):
                ids = k2conf_poz[key]
                sec_lines_tip.append(f"  {key}: { ', '.join(map(str, sorted(ids))) }")
    
        # --- Chybějící anonymizace – rozpis podle NÁZVŮ lokací ---
        if missing_by_loc_key:
            sec_lines_label.append("• Chybí anonymizace (lokace vyžadují anonymizaci):")
            for key in _sort_keys_by_loc_name(list(missing_by_loc_key.keys())):
                ids = missing_by_loc_key[key]
                name = _display_loc_name(key)
                sec_lines_label.append(f"   {name}: { _fmt_ids(ids, limit=18) }")
            sec_lines_tip.append("Chybějící anonymizace – rozpis podle lokací, kde je anonymizace vyžadována:")
            for key in _sort_keys_by_loc_name(list(missing_by_loc_key.keys())):
                ids = missing_by_loc_key[key]
                name = _display_loc_name(key)
                sec_lines_tip.append(f"  {name}: { ', '.join(map(str, ids)) }")
    
        # finální texty
        lbl.setText("⚠ Integrita JSONů:\n" + "\n".join(sec_lines_label))
        lbl.setStyleSheet("QLabel { color: #b58900; font-weight: 600; }")
        lbl.setToolTip("\n".join(sec_lines_tip))

    def _gather_selected_json_files(self) -> list[Path]:
        """Vrátí seznam Path vybraných SOUBORŮ v pravém stromu JSON tabu (ignoruje složky)."""
        result = []
        if not hasattr(self, "tree") or not hasattr(self, "tree_model"):
            return result
        seen = set()
        for idx in self.tree.selectionModel().selectedIndexes():
            if not idx.isValid():
                continue
            item = self.tree_model.itemFromIndex(idx)
            if item is None or item.data(Qt.UserRole) != "file":
                continue
            p = item.data(Qt.UserRole + 1)
            if not p:
                continue
            if p in seen:
                continue
            seen.add(p)
            result.append(Path(p))
        return result
    
    # FILE: gui/web_photos_window.py
    # CLASS: WebPhotosWindow
    # REPLACE the whole function exactly.
    
    def _state_emoji(self, state: str) -> str:
            """
            Vrátí emoji pro daný STAV (pro text v menu).
            Pokud stav neznáme, vrátíme '•'.
            """
            m = {
                "BEZFOTKY":  "🖼️❌",
                "DAROVANY":  "🎁",
                "ZTRACENY":  "❌",
                "BEZGPS":    "📡❌",
                "NEUTRZEN":  "🌱",
                "OBDAROVANY":"🤝",
                # >>> DOPLNĚNO:
                "BEZLOKACE": "📍❌",
                "LOKACE-NEEXISTUJE": "🗺️🚫",
            }
            return m.get(state, "•")

    def _on_json_tree_context_menu(self, pos):
        """
        Kontextové menu pro pravý strom v 'Nastavení JSONů'.
        - Levé ikonky jsou schválně skryté (zůstanou jen emoji v textu).
        - V podmenu 'Přiřadit stav' jsou místo odrážek konkrétní emoji pro stavy.
        """
        files = self._gather_selected_json_files()
        if not files:
            idx = self.tree.indexAt(pos)
            if idx.isValid():
                it = self.tree_model.itemFromIndex(idx)
                if it and it.data(Qt.UserRole) == "file":
                    files = [Path(it.data(Qt.UserRole + 1))]
        if not files:
            return
    
        menu = QMenu(self.tree)
        # Skryj ikonový sloupec jen v TOMTO menu (nezasáhne menu v 'Přejmenování'):
        menu.setStyleSheet("QMenu::icon { width: 0px; } QMenu { padding: 4px 6px; }")
    
        # Akce – jen emoji v textu (pravá ikonka v názvu)
        act_assign_loc = QAction("📍 Přiřadit lokaci", self)
        act_assign_loc.setIconVisibleInMenu(False)
        act_assign_loc.triggered.connect(lambda: self._json_action_assign_location(files))
        menu.addAction(act_assign_loc)
    
        act_reco_loc = QAction("🎯 Doporučit lokace", self)
        act_reco_loc.setIconVisibleInMenu(False)
        act_reco_loc.triggered.connect(lambda: self._json_action_recommend_locations(files))
        menu.addAction(act_reco_loc)
    
        # >>> DOPLNĚNO: nová akce pro zápis poznámky (modalní vstup), nic dalšího se nemění
        act_write_note = QAction("✍️ Zapsat poznámku", self)
        act_write_note.setIconVisibleInMenu(False)
        act_write_note.triggered.connect(lambda: self._json_action_write_note(files))
        menu.addAction(act_write_note)
        # <<< KONEC DOPLNĚNÍ
    
        # >>> DOPLNĚNO: nová akce – odstranění ze všech JSONů
        act_remove_all = QAction("🧹 Odstranit ze všech JSONů", self)
        act_remove_all.setIconVisibleInMenu(False)
        act_remove_all.triggered.connect(lambda: self._json_action_remove_from_all(files))
        menu.addAction(act_remove_all)
        # <<< KONEC DOPLNĚNÍ
    
        # Podmenu STAVŮ – také bez levého ikonového sloupce, ale s emoji v textu
        sub_states = QMenu("⚙️ Přiřadit stav", menu)
        sub_states.setStyleSheet("QMenu::icon { width: 0px; }")
    
        # ⬇️ ZMĚNA: místo pevného seznamu použijeme ALLOWED_STATES (s preferovaným pořadím)
        state_order = [
            "BEZFOTKY", "BEZGPS", "BEZLOKACE", "LOKACE-NEEXISTUJE",
            "DAROVANY", "OBDAROVANY", "NEUTRZEN", "ZTRACENY"
        ]
        states = [s for s in state_order if s in ALLOWED_STATES] + [
            s for s in sorted(ALLOWED_STATES) if s not in state_order
        ]
        for s in states:
            em = self._state_emoji(s)
            a = QAction(f"{em}  {s}", self)
            a.setIconVisibleInMenu(False)
            a.triggered.connect(lambda _, st=s: self._json_action_assign_state(files, st))
            sub_states.addAction(a)
        menu.addMenu(sub_states)
    
        act_anon = QAction("🕶️ Nastavit jako anonymizovaný", self)
        act_anon.setIconVisibleInMenu(False)
        act_anon.triggered.connect(lambda: self._json_action_set_anonymized(files))
        menu.addAction(act_anon)
    
        menu.exec(self.tree.viewport().mapToGlobal(pos))
    
    def _json_action_remove_from_all(self, files):
        import json
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
    
        # 1) Vyparsovat jedinečná čísla nálezů z názvů souborů (prefix před '+')
        ids_str = set()
        for p in files:
            try:
                stem = Path(p).stem
                cid = stem.split("+", 1)[0].strip()
                if cid.isdigit():
                    ids_str.add(cid)
            except Exception:
                continue
    
        if not ids_str:
            QMessageBox.information(self, "Odstranit ze všech JSONů", "Nenalezena žádná čísla nálezů k odstranění.")
            return
    
        ids_int = set(int(x) for x in ids_str)  # pro práci s intervaly
        removed_counts = {"lokace": 0, "stavy": 0, "poznamky": 0, "anonym": 0}
    
        # --- lokální pomocné funkce ---
    
        def _load_editor_dict(ed):
            raw = ed.toPlainText().strip()
            if not raw:
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Kořen JSONu musí být objekt ({}).")
            return data
    
        def _dump_editor_dict(ed, data):
            ed.setPlainText(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    
        def _parse_range(token: str):
            t = (str(token) if token is not None else "").strip()
            if not t or "-" not in t:
                return None
            a, b = t.split("-", 1)
            a = a.strip(); b = b.strip()
            if not (a.isdigit() and b.isdigit()):
                return None
            ai, bi = int(a), int(b)
            if ai > bi:
                ai, bi = bi, ai
            return (ai, bi)
    
        def _format_range(a: int, b: int) -> str:
            return str(a) if a == b else f"{a}-{b}"
    
        def _subtract_ids_from_array(arr, ids_to_remove_int: set[int]):
            """
            Z pole tokenů (čísla nebo 'a-b') odstraní čísla z ids_to_remove_int.
            Vrátí (new_arr, removed_count).
            """
            new_arr = []
            removed = 0
            for tok in arr:
                tok_s = str(tok).strip()
                if not tok_s:
                    continue
    
                if tok_s.isdigit():
                    vi = int(tok_s)
                    if vi in ids_to_remove_int:
                        removed += 1
                    else:
                        new_arr.append(tok_s)
                    continue
    
                rng = _parse_range(tok_s)
                if rng is None:
                    new_arr.append(tok_s)  # neznámý formát ponechám
                    continue
    
                a, b = rng
                hits = sorted([v for v in ids_to_remove_int if a <= v <= b])
                if not hits:
                    new_arr.append(_format_range(a, b))
                    continue
    
                removed += len(hits)
    
                segs = []
                cur_start = a
                for h in hits:
                    if cur_start <= h - 1:
                        segs.append((cur_start, h - 1))
                    cur_start = h + 1
                if cur_start <= b:
                    segs.append((cur_start, b))
    
                for s, e in segs:
                    new_arr.append(_format_range(s, e))
    
            return new_arr, removed
    
        # 2) LOKACE: dict[str -> list[str]] – odstranění čísel (i uvnitř intervalů) + SMAZÁNÍ PRÁZDNÝCH KLÍČŮ
        try:
            data = _load_editor_dict(self.ed_lokace)
            changed = False
            local_removed = 0
            keys_to_delete = []
            for key, arr in list(data.items()):
                if isinstance(arr, list):
                    new_arr, rem = _subtract_ids_from_array(arr, ids_int)
                    if rem > 0:
                        local_removed += rem
                        changed = True
                    # pokud po odečtu nic nezbylo, celé umístění smažeme
                    if len(new_arr) == 0:
                        keys_to_delete.append(key)
                    else:
                        data[key] = new_arr
            for k in keys_to_delete:
                data.pop(k, None)
                # smazání prázdné lokace nepočítám do removed_counts (počítáme odmazané položky),
                # ale pokud chceš, lze přičíst +1 za každý smazaný klíč.
            if changed or keys_to_delete:
                _dump_editor_dict(self.ed_lokace, data)
            removed_counts["lokace"] += local_removed
        except Exception:
            pass  # ponech beze změny při nevalidním JSONu
    
        # 3) STAVY: dict[state -> list[str]] – odstranění čísel (i uvnitř intervalů)
        try:
            data = _load_editor_dict(self.ed_stavy)
            changed = False
            local_removed = 0
            for key, arr in list(data.items()):
                if isinstance(arr, list):
                    new_arr, rem = _subtract_ids_from_array(arr, ids_int)
                    if rem > 0:
                        data[key] = new_arr
                        changed = True
                        local_removed += rem
            if changed:
                _dump_editor_dict(self.ed_stavy, data)
            removed_counts["stavy"] += local_removed
        except Exception:
            pass
    
        # 4) POZNÁMKY: dict[id -> str] – smaž klíče rovné ID
        try:
            data = _load_editor_dict(self.ed_poznamky)
            changed = False
            local_removed = 0
            for cid in list(ids_str):
                if cid in data:
                    data.pop(cid, None)
                    local_removed += 1
                    changed = True
            if changed:
                _dump_editor_dict(self.ed_poznamky, data)
            removed_counts["poznamky"] += local_removed
        except Exception:
            pass
    
        # 5) ANONYMIZACE: dict[str -> list[str]] – odstranění čísel (i uvnitř intervalů)
        try:
            data = _load_editor_dict(self.ed_anonym)
            changed = False
            local_removed = 0
            for key, arr in list(data.items()):
                if isinstance(arr, list):
                    new_arr, rem = _subtract_ids_from_array(arr, ids_int)
                    if rem > 0:
                        data[key] = new_arr
                        changed = True
                        local_removed += rem
            if changed:
                _dump_editor_dict(self.ed_anonym, data)
            removed_counts["anonym"] += local_removed
        except Exception:
            pass
    
        # 6) Uložení a refresh UI (stejně jako u ostatních JSON akcí)
        try:
            self._save_editors_to_settings()
        except Exception:
            pass
        try:
            self._rebuild_json_right_tree()
        except Exception:
            pass
    
        total_removed = sum(removed_counts.values())
        QMessageBox.information(
            self,
            "Odstranit ze všech JSONů",
            f"Hotovo. Odstraněno celkem {total_removed} záznamů (včetně zásahů do intervalů)."
            f"\n• Lokace: {removed_counts['lokace']}"
            f"\n• Stavy: {removed_counts['stavy']}"
            f"\n• Poznámky: {removed_counts['poznamky']}"
            f"\n• Anonymizace: {removed_counts['anonym']}"
        )
        
    # FILE: gui/web_photos_window.py
    # CLASS: WebPhotosWindow
    # ADD: celá nová funkce obsluhy kontextové akce (umísti ji vedle ostatních _json_action_* metod)
    
    def _json_action_write_note(self, files: list[Path]):
        """
        Pro vybrané soubory otevře modální vstup a zapíše zadanou poznámku
        do editoru „📝 JSON poznámky“ (self.ed_poznamky) ve tvaru:
          "ČísloNálezu": "Poznámka"
        Každé číslo nálezu dostane tu samou poznámku. Poté uloží nastavení
        a obnoví pravý strom.
        """
        # Stabilita pravého stromu (zachová rozbalení a výběr)
        self._capture_json_tree_state()
    
        # Sesbírej ČíslaNálezů z vybraných souborů
        ids: list[str] = []
        for p in files:
            s = self._extract_id_from_name(p.name)
            if s:
                ids.append(s)
    
        if not ids:
            QMessageBox.information(self, "Zapsat poznámku", "Ve vybraných souborech se nepodařilo najít ČísloNálezu.")
            return
    
        # Modalní multi-line vstup
        note_text, ok = QInputDialog.getMultiLineText(
            self,
            "Zapsat poznámku",
            "Poznámka pro vybrané položky:",
            ""
        )
        if not ok:
            return
        note_text = (note_text or "").strip()
        if not note_text:
            QMessageBox.information(self, "Zapsat poznámku", "Poznámka je prázdná – nic se nezapsalo.")
            return
    
        # Načti existující JSON z editoru „JSON poznámky“
        try:
            raw = self.ed_poznamky.toPlainText() or "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Kořen JSONu musí být objekt ({}).")
        except Exception as e:
            QMessageBox.warning(self, "Zapsat poznámku", f"Editor 'JSON poznámky' obsahuje neplatný JSON.\n{e}")
            return
    
        # Zapiš / aktualizuj poznámku pro všechna ČíslaNálezů
        for cid in ids:
            data[str(cid)] = note_text
    
        # Přepiš editor v jednořádkovém formátu jako zbytek aplikace
        self.ed_poznamky.setPlainText(
            self._format_singleline_dict(data, sort_numeric_keys=True, align_values=True)
        )
    
        # Standardní uložení a refresh jako u ostatních akcí
        self._save_editors_to_settings()
        QMessageBox.information(self, "Zapsat poznámku", f"Zapsána poznámka pro {len(ids)} položek.")
        self._rebuild_json_right_tree()
        
    def _json_action_assign_location(self, files: list[Path]):
        """
        Přiřadí vybraným fotkám ČísloLokace.
    
        NOVĚ:
          • Dialog má 2 vstupy:
              (A) ruční zadání ČísloLokace (1–5 číslic),
              (B) fulltext vyhledávání mezi názvy map (výběr mapy doplní ČísloLokace).
          • Dvojklik na položku ve výsledcích nebo Enter doplní číslo a PROVEDE přiřazení (volá _on_accept()).
          • Zachováno: aktualizace JSONů, formátování, obnova pravého stromu.
        """
        from pathlib import Path
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence, QShortcut, QColor
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
            QListWidgetItem, QDialogButtonBox, QMessageBox
        )
        import re as _re
        import json as _json
    
        # --- Pomůcky ---
        def _extract_numeric_location_id_from_filename(filename: str):
            parts = filename.split('+')
            if len(parts) < 2:
                return None
            last_part = parts[-1]
            base = last_part.split('.')[0] if '.' in last_part else last_part
            m = _re.search(r'(\d{1,5})$', base)
            return int(m.group(1)) if m else None
    
        def _parse_location_info(filename: str):
            parts = filename.split('+')
            info = {'id': parts[0] if parts else filename, 'description': '', 'number_display': ''}
            if len(parts) >= 2:
                info['description'] = parts[1]
            for part in reversed(parts):
                base = part.split('.')[0] if '.' in part else part
                m = _re.search(r'(\d{5})$', base)
                if m:
                    try:
                        info['number_display'] = str(int(m.group(1)))
                    except Exception:
                        info['number_display'] = m.group(1)
                    break
            return info
    
        # --- 1) Vytažení ID fotek ze jmen souborů ---
        photo_ids: list[int] = []
        for p in files:
            s = self._extract_id_from_name(p.name)
            if not s:
                continue
            try:
                pid = int(s)
            except Exception:
                continue
            photo_ids.append(pid)
    
        if not photo_ids:
            QMessageBox.information(self, "Přiřadit lokaci", "U vybraných souborů se nepodařilo zjistit ID fotek.")
            return
    
        # Hlavička s intervaly (jen pro informaci)
        try:
            intervals = self._merge_numbers_to_intervals(sorted(set(photo_ids)))
            header_text = ", ".join(intervals)
        except Exception:
            header_text = ", ".join(map(str, sorted(set(photo_ids))))
    
        # --- 2) Načti dostupné mapy (pro fulltext) ---
        maps = self._get_available_location_maps_from_dir() or []
        # Připrav index položek pro fulltext
        indexed_items = []
        for md in maps:
            fname = md.get("filename", "")
            info = _parse_location_info(fname)
            # Kandidát na ČL z metadat
            c5 = md.get("cislolok5")
            cislolok_key = None
            if c5:
                try:
                    cislolok_key = self._normalize_cislolok(c5)
                except Exception:
                    cislolok_key = None
            if cislolok_key is None:
                num = _extract_numeric_location_id_from_filename(fname)
                if num is not None:
                    try:
                        cislolok_key = self._normalize_cislolok(str(num))
                    except Exception:
                        cislolok_key = None
    
            indexed_items.append({
                "md": md,
                "fname": fname,
                "text": (fname or "") + " " + (info.get("description") or "") + " " + (info.get("id") or ""),
                "info": info,
                "key": cislolok_key  # může být None -> doplní se až v dialogu dotazem
            })
    
        # --- 3) Dialog ---
        dlg = QDialog(self)
        dlg.setWindowTitle("Přiřadit lokaci")
        dlg.setMinimumWidth(720)
        v = QVBoxLayout(dlg); v.setSpacing(10)
    
        v.addWidget(QLabel(f"Vybrané fotky ({len(photo_ids)}): {header_text}"))
    
        # Řádek A: ruční zadání ČísloLokace
        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("ČísloLokace (1–5 číslic):"))
        le_key = QLineEdit(dlg)
        le_key.setPlaceholderText("např. 1 nebo 00001")
        row_a.addWidget(le_key, 1)
        v.addLayout(row_a)
    
        # Řádek B: fulltext nad mapami
        v.addWidget(QLabel("Vyhledat podle názvu mapy (fulltext):"))
        le_search = QLineEdit(dlg)
        le_search.setPlaceholderText("piš část názvu/ID/Popisu… (Enter = potvrdit a přiřadit)")
        v.addWidget(le_search)
    
        lw = QListWidget(dlg)
        lw.setAlternatingRowColors(True)
        v.addWidget(lw, 1)
    
        hint = QLabel("Tip: dvojklik na mapu vyplní ČísloLokace a hned přiřadí všem vybraným fotkám.")
        hint.setStyleSheet("color:#666;")
        v.addWidget(hint)
    
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        btns.button(QDialogButtonBox.Ok).setText("Přiřadit")
        v.addWidget(btns)
    
        # Zkratka zavření
        QShortcut(QKeySequence.Close, dlg, dlg.reject)
    
        # --- 4) Formátování a plnění seznamu ---
        def _format_item_text(info: dict, fname: str, key: str | None) -> str:
            id_text = info.get("id") or "?"
            desc = info.get("description") or ""
            number_display = info.get("number_display")
            add = f" • Mapa číslo: {number_display}" if number_display else ""
            line1 = f"{id_text}{add}"
            if desc:
                line1 += f"\n 📄 {desc}"
            if key:
                line1 += f"\n 🔢 ČísloLokace: {key}"
            return line1
    
        def _refill_list(filter_text: str):
            """
            Bezdiakritické fulltext filtrování přes:
              - název souboru (fname)
              - ČísloLokace (key / number_display)
              - zkratku/název lokace (info['id'])
              - popis (info['description'])
            Víceslovný dotaz: AND logika (všechna slova musí být přítomna),
            pokud by AND nic nenašel, fallbackne se slabším skóre na OR kandidáty.
            Seřazení dle relevance, potom dle názvu souboru.
            """
            lw.clear()
        
            import re
            import unicodedata
        
            def _fold(s: str) -> str:
                if not s:
                    return ""
                # bez diakritiky + lower
                return "".join(
                    c for c in unicodedata.normalize("NFKD", str(s))
                    if not unicodedata.combining(c)
                ).lower()
        
            # připrav dotaz: tokeny bez diakritiky
            raw = (filter_text or "").strip()
            tokens_raw = [t for t in re.split(r"[\s/_\-.]+", raw) if t]
            tokens = [_fold(t) for t in tokens_raw]
        
            def _mk_blob(it: dict) -> tuple[str, str]:
                info = it.get("info") or {}
                parts = [
                    it.get("fname", ""),
                    it.get("key", "") or "",
                    info.get("id", "") or "",
                    info.get("description", "") or "",
                    info.get("number_display", "") or "",
                ]
                blob = " ".join(p for p in parts if p)
                return blob, _fold(blob)
        
            candidates: list[tuple[int, dict]] = []
        
            for it in indexed_items:
                blob, blob_f = _mk_blob(it)
        
                if not tokens:
                    # bez filtru -> vše, nízké skóre
                    candidates.append((0, it))
                    continue
        
                # AND: všechna slova musí být v bloku
                all_in = all(tok in blob_f for tok in tokens)
                some_in = any(tok in blob_f for tok in tokens)
        
                score = 0
                if all_in:
                    # základní boost za plnou shodu všech tokenů
                    score += 100
        
                # boosty za shody tokenů, prefixy a přesnou shodu čísla lokace
                for tok in tokens:
                    if tok in blob_f:
                        score += 1
                    # prefix (na začátku blobu)
                    if blob_f.startswith(tok):
                        score += 1
                    # přesná shoda s klíčem lokace
                    key = (it.get("key") or "").lower()
                    if key and tok == key:
                        score += 3
        
                if all_in:
                    candidates.append((score, it))
                elif some_in:
                    # slabší kandidát, použijeme pokud by AND nic nenašel
                    candidates.append((score - 50, it))
        
            if not candidates:
                none_item = QListWidgetItem("(Nenalezeny žádné mapy)")
                none_item.setFlags(none_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
                lw.addItem(none_item)
                return
        
            # seřadit: skóre desc, potom fname asc
            candidates.sort(key=lambda t: (-t[0], (t[1].get("fname") or "").lower()))
        
            for _, it in candidates:
                item = QListWidgetItem(_format_item_text(it["info"], it["fname"], it["key"]))
                item.setData(Qt.UserRole, it)
                # zvýraznění, když známe ČísloLokace
                if it["key"]:
                    item.setForeground(QColor("#0B5ED7"))
                lw.addItem(item)
    
        _refill_list("")
        le_search.textChanged.connect(_refill_list)
    
        # --- 5) Vlastní přiřazení (společná logika) ---
        def _on_accept():
            raw = (le_key.text() or "").strip()
            if not raw:
                QMessageBox.information(self, "Přiřadit lokaci", "Zadej ČísloLokace nebo vyber mapu ze seznamu.")
                return
            try:
                cislolok_key = self._normalize_cislolok(raw)
            except ValueError as e:
                QMessageBox.warning(self, "Přiřadit lokaci", str(e))
                return
    
            # Zápis do JSON a uložení
            try:
                lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
                exist = self._numbers_from_intervals(lokace.get(cislolok_key, []))
                exist |= set(photo_ids)
                lokace[cislolok_key] = self._merge_numbers_to_intervals(sorted(exist))
                self.ed_lokace.setPlainText(self._format_singleline_dict(
                    lokace, sort_numeric_keys=True, align_values=True
                ))
                self._save_editors_to_settings()
                # --- AUTO anonymizace dle metadat lokace ---
                try:
                    # zjisti, zda tato lokace vyžaduje anonymizaci (z metadat lokační mapy)
                    def _map_requires_anon_for_key(_key: str) -> bool:
                        try:
                            from PIL import Image as _Image
                        except Exception:
                            _Image = None
                        try:
                            for _md in self._get_available_location_maps_from_dir() or []:
                                _fname = _md.get('filename', '') or ''
                                _abs = _md.get('absolute', '') or ''
                                _key_here = None
                                _c5 = _md.get('cislolok5')
                                if _c5:
                                    try:
                                        _key_here = self._normalize_cislolok(str(_c5))
                                    except Exception:
                                        _key_here = None
                                if _key_here is None:
                                    # pokus vyčíst číslo lokace z konce názvu souboru
                                    _parts = (_fname or '').split('+')
                                    _last = _parts[-1] if _parts else (_fname or '')
                                    _base = _last.split('.')[0] if '.' in _last else _last
                                    import re as _re
                                    _m = _re.search(r'(\d{1,5})$', _base)
                                    if _m:
                                        try:
                                            _key_here = self._normalize_cislolok(str(int(_m.group(1))))
                                        except Exception:
                                            _key_here = None
                                if _key_here != _key:
                                    continue
                                # čtení metadat (pokud PIL k dispozici)
                                flag = False
                                if _Image and _abs:
                                    try:
                                        with _Image.open(_abs) as _img:
                                            if hasattr(_img, 'text') and isinstance(_img.text, dict):
                                                for _k, _v in _img.text.items():
                                                    _ks = str(_k).strip().lower()
                                                    _vs = str(_v).strip().lower()
                                                    if 'anonym' in _ks or 'anonym' in _vs:
                                                        if ('ano' in _vs) or ('yes' in _vs) or ('true' in _vs) or (_vs == '1'):
                                                            flag = True
                                                            break
                                    except Exception:
                                        pass
                                return flag
                        except Exception:
                            return False
                        return False
                
                    if _map_requires_anon_for_key(cislolok_key):
                        # načti aktuální anonym spec, přidej nová ID a ulož
                        _lok, _st, _poz, _an = self._get_current_settings_dicts()
                        _spec = None
                        for _k in ('ANONYMIZOVANE', 'ANONYM', 'ANON', 'ANONYMIZACE'):
                            if isinstance(_an, dict) and _k in _an:
                                _spec = _an.get(_k)
                                break
                        try:
                            _existing = self._numbers_from_intervals(_spec) if _spec is not None else set()
                        except Exception:
                            _existing = set()
                        _merged = sorted(set(_existing) | set(photo_ids))
                        _an['ANONYMIZOVANE'] = self._merge_numbers_to_intervals(_merged)
                        self.ed_anonym.setPlainText(self._format_singleline_dict(_an, sort_numeric_keys=False, align_values=True))
                        self._save_editors_to_settings()
                except Exception:
                    pass
                # zapamatuj poslední přiřazení (pokud máš tu funkci)
                try:
                    self.remember_last_loc_assigned(
                        file_paths=[str(p) for p in files],
                        fids=photo_ids,
                        persist=True
                    )
                except Exception:
                    pass
            except Exception as e:
                QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{e}")
                return
    
            # Refresh pravého stromu se zachováním stavu
            try:
                self._schedule_json_tree_rebuild()
            except Exception:
                pass
    
            QMessageBox.information(
                self, "Přiřadit lokaci",
                f"✅ Přiřazeno {len(photo_ids)} fotek do lokace {cislolok_key}\n"
                f"Fotky: {', '.join(map(str, sorted(set(photo_ids))))}"
            )
            dlg.accept()
    
        btns.accepted.connect(_on_accept)
        btns.rejected.connect(dlg.reject)
    
        # --- 6) Interakce: výběr položky → doplnit klíč a rovnou potvrdit ---
        def _use_item_selected(confirm_after: bool):
            it = lw.currentItem()
            if not it:
                return
            data = it.data(Qt.UserRole) or {}
            # zkus získat nebo dovodit ČL
            key = data.get("key")
            if not key:
                md = data.get("md") or {}
                c5 = md.get("cislolok5")
                if c5:
                    try:
                        key = self._normalize_cislolok(c5)
                    except Exception:
                        key = None
                if key is None:
                    fname = data.get("fname") or ""
                    num = _extract_numeric_location_id_from_filename(fname)
                    if num is not None:
                        try:
                            key = self._normalize_cislolok(str(num))
                        except Exception:
                            key = None
            if key:
                le_key.setText(key)
                if confirm_after:
                    _on_accept()  # ← místo dlg.accept() voláme přímo vlastní logiku přiřazení
            else:
                QMessageBox.information(self, "Přiřadit lokaci",
                                        "Tuto mapu nelze automaticky převést na ČísloLokace.\n"
                                        "Zadej číslo ručně do horního pole.")
    
        lw.itemDoubleClicked.connect(lambda _i: _use_item_selected(True))
    
        # Enter v hledání -> pokud je vybraná položka, použít; jinak se pokusí o přímé přiřazení z pole
        def _enter_in_search():
            if lw.currentItem() and (lw.currentItem().flags() & Qt.ItemIsSelectable):
                _use_item_selected(True)
            else:
                _on_accept()
        le_search.returnPressed.connect(_enter_in_search)
    
        dlg.exec()

    def _json_action_recommend_locations(self, files: list[Path]):
        """
        Doporučí lokace dle GPS fotek vs. map (Neroztříděné).
    
        Nově:
          • METRY (↔ xx m) místo km.
          • U každé lokace zobrazen počet i KONKRÉTNÍ ID fotek uvnitř AOI (polygonu).
          • Mapy BEZ polygonu se nikdy netváří jako „uvnitř“ – berou se jen jako „nejbližší“ (dle bodu mapy).
          • Dialog má dvě záložky:
              1) „Hromadně“ – vybereš jednu lokaci a přiřadíš ji všem vybraným fotkám.
              2) „Po fotkách“ – u každé fotky TOP doporučení; dvojklik přiřadí jen této fotce.
                 (NOVĚ) U kořenové položky každé fotky je vidět, zda je již přiřazená (✅ lokace) nebo ne.
          • Dialog je výrazně vyšší (3–4×) s ohledem na výšku obrazovky.
        """
        # Stabilita pravého stromu
        self._capture_json_tree_state()
    
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QTabWidget,
            QDialogButtonBox, QLineEdit, QMessageBox, QTreeWidget, QTreeWidgetItem,
            QPushButton, QHBoxLayout
        )
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QKeySequence, QAction, QShortcut, QGuiApplication
        import re as _re, json as _json, math as _math
    
        # === 1) Sesbírat IDs a GPS fotek (jen ty, co mají GPS) ===
        photo_ids: list[int] = []
        photo_coords: list[tuple[int, tuple[float, float]]] = []
        latlon_map: dict[int, tuple[float, float]] = {}
    
        for p in files:
            s = self._extract_id_from_name(p.name)
            if not s:
                continue
            try:
                pid = int(s)
            except Exception:
                continue
            gps = self._extract_gps_from_file(str(p))
            if gps:
                photo_ids.append(pid)
                photo_coords.append((pid, gps))
                latlon_map[pid] = gps
    
        if not photo_coords:
            QMessageBox.information(self, "Doporučit lokace", "U vybraných souborů se nepodařilo načíst GPS souřadnice.")
            return
    
        total_photos = len(photo_coords)
    
        # === 1b) Zjisti, které z vybraných fotek už MAJÍ přiřazenou lokaci (pro vizuální indikaci v „Po fotkách“) ===
        assigned_by_id: dict[int, str] = {}
        try:
            lokace, _stavy, _poznamky, _anonym = self._get_current_settings_dicts()
            if isinstance(lokace, dict):
                for key, intervals in lokace.items():
                    try:
                        nums = self._numbers_from_intervals(intervals)
                    except Exception:
                        nums = set()
                    # zajímají nás jen právě vybrané fotky
                    for pid in photo_ids:
                        if pid in nums:
                            assigned_by_id[pid] = str(key)
        except Exception:
            pass
    
        # === 2) Mapy s GPS bodem (ze složky) ===
        maps = [m for m in self._get_available_location_maps_from_dir() if m.get("gps_point")]
        if not maps:
            QMessageBox.information(self, "Doporučit lokace", "Ve složce s mapami nebyly nalezeny mapy s GPS v názvu.")
            return
    
        # === PROGRESS: inicializace dialogu ===
        try:
            from PySide6.QtWidgets import QProgressDialog, QApplication
            _prog = QProgressDialog("Doporučuji lokace…", "Zrušit", 0, len(maps), self)
            _prog.setWindowTitle("Pracuje se…")
            _prog.setWindowModality(Qt.WindowModal)
            _prog.setMinimumDuration(0)
            _prog.setAutoClose(True)
            _prog.setAutoReset(True)
            _prog.setValue(0)
        except Exception:
            _prog = None
        _cancelled = False
    
        # --- Pomocné funkce ---
        def _read_polygon_from_metadata(image_path: str):
            """Vrátí list s jedním dict {'points': [(x,y),...]} nebo None."""
            try:
                from PIL import Image as _Image
                with _Image.open(image_path) as img:
                    if hasattr(img, 'text') and isinstance(img.text, dict):
                        val = img.text.get('AOI_POLYGON')
                        if isinstance(val, str) and val:
                            try:
                                poly = _json.loads(val)
                                if isinstance(poly, dict) and 'points' in poly and isinstance(poly['points'], list) and len(poly['points']) >= 3:
                                    return [{'points': poly['points']}]
                            except Exception:
                                pass
                    if 'AOI_POLYGON' in img.info:
                        val = img.info.get('AOI_POLYGON')
                        if isinstance(val, str) and val:
                            try:
                                poly = _json.loads(val)
                                if isinstance(poly, dict) and 'points' in poly and isinstance(poly['points'], list) and len(poly['points']) >= 3:
                                    return [{'points': poly['points']}]
                            except Exception:
                                pass
            except Exception:
                pass
        def _gps_to_pixel(target_lat, target_lon, center_lat, center_lon, zoom, map_w, map_h):
            def deg2num(lat_deg, lon_deg, zoom):
                lat_rad = _math.radians(lat_deg)
                n = 2.0 ** zoom
                xtile = (lon_deg + 180.0) / 360.0 * n
                ytile = (1.0 - _math.asinh(_math.tan(lat_rad)) / _math.pi) / 2.0 * n
                return (xtile, ytile)
            cx, cy = deg2num(center_lat, center_lon, zoom)
            tx, ty = deg2num(target_lat, target_lon, zoom)
            pixel_dx = (tx - cx) * 256
            pixel_dy = (ty - cy) * 256
            return (map_w / 2) + pixel_dx, (map_h / 2) + pixel_dy
    
        def _is_point_in_polygon(x, y, poly_points):
            n = len(poly_points)
            if n < 3:
                return False
            inside = False
            p1x, p1y = poly_points[0]
            for i in range(n + 1):
                p2x, p2y = poly_points[i % n]
                if y > min(p1y, p2y):
                    if y <= max(p1y, p2y):
                        if x <= max(p1x, p2x):
                            if p1y != p2y:
                                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                            if p1x == p2x or x <= xinters:
                                inside = not inside
                p1x, p1y = p2x, p2y
            return inside
    
        def _point_to_segment_dist(p, a, b):
            px, py = p; ax, ay = a; bx, by = b
            abx, aby = bx - ax, by - ay
            ab2 = abx**2 + aby**2
            if ab2 == 0:
                return _math.hypot(px - ax, py - ay)
            t = ((px - ax) * abx + (py - ay) * aby) / ab2
            t = max(0, min(1, t))
            cx = ax + t * abx; cy = ay + t * aby
            return _math.hypot(px - cx, py - cy)
    
        def _point_to_polygon_dist(point, poly_points):
            if len(poly_points) < 2:
                return float('inf')
            md = float('inf')
            for i in range(len(poly_points)):
                p1 = poly_points[i]
                p2 = poly_points[(i + 1) % len(poly_points)]
                d = _point_to_segment_dist(point, p1, p2)
                if d < md: md = d
            return md
    
        def _meters_per_pixel(latitude, zoom):
            try:
                return 156543.03 * _math.cos(_math.radians(latitude)) / (2 ** zoom)
            except Exception:
                return 1.0
    
        def _extract_numeric_location_id_from_filename(filename: str):
            parts = filename.split('+')
            if len(parts) < 2:
                return None
            last_part = parts[-1]
            base = last_part.split('.')[0] if '.' in last_part else last_part
            m = _re.search(r'(\d{1,5})$', base)
            return int(m.group(1)) if m else None
    
        def _parse_location_info(filename: str):
            parts = filename.split('+')
            info = {'id': parts[0] if parts else filename, 'description': '', 'number_display': ''}
            if len(parts) >= 2:
                info['description'] = parts[1]
            for part in reversed(parts):
                base = part.split('.')[0] if '.' in part else part
                m = _re.search(r'(\d{5})$', base)
                if m:
                    try:
                        info['number_display'] = str(int(m.group(1)))
                    except Exception:
                        info['number_display'] = m.group(1)
                    break
            return info
    
        def _fmt_meters(val) -> str:
            try:
                n = int(round(float(val)))
                s = f"{n:,}".replace(",", " ")
                return f"{s} m"
            except Exception:
                return f"{val} m"
    
        def _fmt_id_list(ids: list[int], limit: int = 12) -> str:
            try:
                ids_sorted = list(map(int, ids))
            except Exception:
                ids_sorted = ids
            ids_sorted = sorted(ids_sorted)
            if len(ids_sorted) <= limit:
                return ", ".join(str(x) for x in ids_sorted)
            shown = ", ".join(str(x) for x in ids_sorted[:limit])
            return f"{shown} (+{len(ids_sorted) - limit})"
    
        # Průměrný bod fotek (jen pro agregované řazení)
        if len(photo_coords) == 1:
            avg_lat, avg_lon = photo_coords[0][1]
        else:
            avg_lat = sum(c[1][0] for c in photo_coords) / len(photo_coords)
            avg_lon = sum(c[1][1] for c in photo_coords) / len(photo_coords)
    
        # === 3) Připrav mapové metainformace (zoom, rozměry, polygon) ===
        zoom_re = _re.compile(r'\+Z(\d+)\+')
        try:
            from PIL import Image as _ImageDim
        except Exception:
            _ImageDim = None
    
        pre = []  # předzpracované mapy
        for m in maps:
            plat, plon = m["gps_point"]
            fname = m.get("filename", "")
            absolute = m.get("absolute", "")
    
            zm = 17
            mz = zoom_re.search(fname)
            if mz:
                try:
                    zm = int(mz.group(1))
                except Exception:
                    zm = 17
    
            width = height = None
            if _ImageDim:
                try:
                    with _ImageDim.open(absolute) as _img:
                        width, height = _img.size
                except Exception:
                    width = height = None
    
            polys = _read_polygon_from_metadata(absolute)  # None nebo [{'points':[...]}]
    
            pre.append({
                "m": m, "plat": plat, "plon": plon, "fname": fname, "abs": absolute,
                "zoom": zm, "w": width, "h": height, "poly": polys
            })
    
        # === 4) Agregované skóre pro „Hromadně“ (počty uvnitř + vzdálenost na avg bod) ===
        scored = []
        if _prog:
            from PySide6.QtWidgets import QApplication
        for idx, it in enumerate(pre, start=1):
            if _prog is not None:
                try:
                    _prog.setLabelText(f"Doporučuji lokace…\n{it['fname']}")
                    _prog.setValue(idx)
                    QApplication.processEvents()
                    if _prog.wasCanceled():
                        _cancelled = True
                        break
                except Exception:
                    pass
    
            plat, plon, zm, w, h, polys = it["plat"], it["plon"], it["zoom"], it["w"], it["h"], it["poly"]
            has_poly = bool(polys and w and h)
    
            # per-fotka inside pouze pokud existuje POLYGON
            inside_ids: list[int] = []
            if has_poly:
                poly_pts = polys[0]['points']
                for pid, (lat, lon) in photo_coords:
                    px, py = _gps_to_pixel(lat, lon, plat, plon, zm, w, h)
                    if _is_point_in_polygon(px, py, poly_pts):
                        inside_ids.append(pid)
            # bez polygonu – nikdy se netváříme jako „uvnitř“
            inside_count = len(inside_ids)
            inside_all = (inside_count == total_photos) and (total_photos > 0)
            inside_any = (inside_count > 0)
    
            # vzdálenost agregovaně (na průměrný bod) → m
            if has_poly:
                px_avg, py_avg = _gps_to_pixel(avg_lat, avg_lon, plat, plon, zm, w, h)
                poly_pts = polys[0]['points']
                if _is_point_in_polygon(px_avg, py_avg, poly_pts):
                    distance_m = 0.0
                else:
                    pix_dist = _point_to_polygon_dist((px_avg, py_avg), poly_pts)
                    mpp = _meters_per_pixel(plat, zm)
                    distance_m = float(pix_dist * mpp)
            else:
                # fallback k map-pointu
                distance_m = float(self._haversine(avg_lat, avg_lon, plat, plon) * 1000.0)
    
            info = _parse_location_info(it["fname"])
            scored.append({
                "distance_m": distance_m,
                "inside_all": inside_all,
                "inside_any": inside_any,
                "inside_ids": inside_ids,
                "inside_count": inside_count,
                "outside_count": total_photos - inside_count,
                "total_count": total_photos,
                "map": it["m"],
                "info": info,
                "has_poly": has_poly,
            })
    
        # úklid progress
        if _prog is not None:
            try:
                _prog.setValue(len(pre))
                _prog.close()
            except Exception:
                pass
        if _cancelled:
            return
    
        # setřídění pro „Hromadně“
        inside_list = sorted([r for r in scored if r["inside_any"]],
                             key=lambda r: (not r["inside_all"], r["distance_m"]))
        outside_sorted = sorted([r for r in scored if not r["inside_any"]],
                                key=lambda r: r["distance_m"])
        nearest_10 = outside_sorted[:10]
    
        # === 5) Per-fotka doporučení (TOP pro každou fotku) ===
        per_photo_best: dict[int, dict] = {}
        per_photo_candidates: dict[int, list] = {}
        for pid, (plat0, plon0) in photo_coords:
            candidates = []
            for it in pre:
                plat, plon, zm, w, h, polys = it["plat"], it["plon"], it["zoom"], it["w"], it["h"], it["poly"]
                has_poly = bool(polys and w and h)
                inside = False
                if has_poly:
                    poly_pts = polys[0]['points']
                    px, py = _gps_to_pixel(plat0, plon0, plat, plon, zm, w, h)
                    inside = _is_point_in_polygon(px, py, poly_pts)
                    if inside:
                        dist_m = 0.0
                    else:
                        pix_dist = _point_to_polygon_dist((px, py), poly_pts)
                        mpp = _meters_per_pixel(plat, zm)
                        dist_m = float(pix_dist * mpp)
                else:
                    # bez polygonu – čistě vzdálenost k bodu mapy
                    dist_m = float(self._haversine(plat0, plon0, plat, plon) * 1000.0)
    
                info = _parse_location_info(it["fname"])
                candidates.append({
                    "pid": pid,
                    "inside": inside and has_poly,   # „uvnitř“ jen pokud polygon existuje
                    "dist_m": dist_m,
                    "map": it["m"],
                    "has_poly": has_poly,
                    "info": info
                })
            candidates.sort(key=lambda c: (not c["inside"], c["dist_m"]))
            per_photo_candidates[pid] = candidates[:5]
            per_photo_best[pid] = candidates[0] if candidates else None
    
        # === 6) Dialog (2 záložky: Hromadně / Po fotkách) ===
        dlg = QDialog(self)
        dlg.setWindowTitle("Doporučené lokace")
        dlg.setMinimumWidth(900)
        root = QVBoxLayout(dlg); root.setSpacing(10)
    
        try:
            intervals = self._merge_numbers_to_intervals(sorted(set(photo_ids)))
            header_text = ", ".join(intervals)
        except Exception:
            header_text = ", ".join(map(str, sorted(set(photo_ids))))
        root.addWidget(QLabel(f"Vyber doporučení pro {len(photo_ids)} fotek: {header_text}"))
    
        tabs = QTabWidget(dlg)
        root.addWidget(tabs, 1)
    
        # --- TAB 1: Hromadně ---
        tab_bulk = QDialog(dlg)
        lay_bulk = QVBoxLayout(tab_bulk); lay_bulk.setSpacing(8)
    
        lw = QListWidget(tab_bulk)
    
        def _add_header(text: str):
            header = QListWidgetItem(text)
            header.setFlags(header.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            header.setForeground(QColor("#666666"))
            lw.addItem(header)
    
        _add_header("— Lokace uvnitř AOI (polygon) —")
        if not inside_list:
            none_item = QListWidgetItem("(Žádná mapa s polygonem, do kterého by spadaly GPS souřadnice)")
            none_item.setFlags(none_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            lw.addItem(none_item)
        else:
            for i, rec in enumerate(inside_list, start=1):
                md = rec['map']
                dist_m = rec['distance_m']
                inside_all = rec.get('inside_all', False)
                info = rec.get('info') or {}
                number_display = info.get('number_display')
                desc = info.get('description') or ""
                if len(desc) > 90: desc = desc[:87] + "…"
                id_text = info.get('id', md.get('location_id', '?'))
                add = f" • Mapa číslo: {number_display}" if number_display else ""
                count_text = f"📷 {rec['inside_count']} / {rec['total_count']}"
                meters_text = _fmt_meters(dist_m)
                ids_text = _fmt_id_list(rec.get('inside_ids', []))
                dist_text = "UVNITŘ AOI (všechny)" if inside_all else "UVNITŘ AOI"
                txt = f"{i}. {id_text}" \
                      + (f"\n 📄 {desc}" if desc else "") \
                      + f"\n {count_text} • {dist_text}{add}" \
                      + f"\n ↔ {meters_text}" \
                      + (f"\n 🔢 ID: {ids_text}" if rec.get('inside_ids') else "")
                item = QListWidgetItem(txt)
                item.setData(Qt.UserRole, md)
                if inside_all and i == 1:
                    item.setBackground(QColor("#d4edda")); item.setForeground(QColor("#155724"))
                elif i <= 3:
                    item.setBackground(QColor("#fff3cd")); item.setForeground(QColor("#856404"))
                lw.addItem(item)
    
        _add_header("— Další nejbližší (bez AOI nebo mimo AOI) —")
        if not nearest_10:
            none_item = QListWidgetItem("(Žádné další lokace v okolí)")
            none_item.setFlags(none_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            lw.addItem(none_item)
        else:
            for i, rec in enumerate(nearest_10, start=1):
                md = rec['map']
                dist_m = rec['distance_m']
                info = rec.get('info') or {}
                number_display = info.get('number_display')
                desc = info.get('description') or ""
                if len(desc) > 90: desc = desc[:87] + "…"
                id_text = info.get('id', md.get('location_id', '?'))
                add = f" • Mapa číslo: {number_display}" if number_display else ""
                count_text = f"📷 {rec['inside_count']} / {rec['total_count']}"
                meters_text = _fmt_meters(dist_m)
                txt = f"{i}. {id_text}" \
                      + (f"\n 📄 {desc}" if desc else "") \
                      + f"\n {count_text}{add}" \
                      + f"\n ↔ {meters_text}"
                item = QListWidgetItem(txt)
                item.setData(Qt.UserRole, md)
                if i <= 3:
                    item.setBackground(QColor("#eef5ff")); item.setForeground(QColor("#003a8c"))
                lw.addItem(item)
    
        lay_bulk.addWidget(lw)
    
        bulk_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=tab_bulk)
        bulk_btns.button(QDialogButtonBox.Ok).setText("Přiřadit vybranou všem")
        lay_bulk.addWidget(bulk_btns)
    
        tabs.addTab(tab_bulk, "Hromadně")
    
        # --- TAB 2: Po fotkách ---
        tab_per = QDialog(dlg)
        lay_per = QVBoxLayout(tab_per); lay_per.setSpacing(8)
    
        tree = QTreeWidget(tab_per)
        tree.setHeaderHidden(True)
        tree.setUniformRowHeights(True)
    
        pid_to_root: dict[int, QTreeWidgetItem] = {}
    
        def _format_root_label(pid: int) -> str:
            lat, lon = latlon_map.get(pid, (None, None))
            pos = f"(lat={lat:.6f}, lon={lon:.6f})" if (lat is not None and lon is not None) else ""
            key = assigned_by_id.get(pid)
            if key:
                return f"📷 {pid}  {pos}  —  ✅ {key}"
            else:
                return f"📷 {pid}  {pos}  —  • nepřiřazeno"
    
        def _refresh_root_item(pid: int):
            root_item = pid_to_root.get(pid)
            if not root_item:
                return
            root_item.setText(0, _format_root_label(pid))
            if assigned_by_id.get(pid):
                root_item.setForeground(0, QColor("#155724"))  # zeleně, přiřazeno
            else:
                root_item.setForeground(0, QColor("#FFFFFF"))  # bíle, NEpřiřazeno (změna z černé)
    
        # Naplnění stromu
        for pid, (plat0, plon0) in photo_coords:
            root_item = QTreeWidgetItem([_format_root_label(pid)])
            root_item.setFirstColumnSpanned(True)
            pid_to_root[pid] = root_item
            tree.addTopLevelItem(root_item)
    
            cands = per_photo_candidates.get(pid, [])
            if not cands:
                child = QTreeWidgetItem(["(Žádné doporučení)"])
                child.setDisabled(True)
                root_item.addChild(child)
            else:
                for rank, cand in enumerate(cands, start=1):
                    md = cand["map"]; info = cand["info"] or {}
                    id_text = info.get('id', md.get('location_id', '?'))
                    number_display = info.get('number_display')
                    desc = info.get('description') or ""
                    if len(desc) > 80: desc = desc[:77] + "…"
                    badge = "UVNITŘ AOI" if (cand["inside"] and cand["has_poly"]) else "mimo AOI"
                    meters_text = _fmt_meters(cand["dist_m"])
                    add = f" • mapa #{number_display}" if number_display else ""
                    line1 = f"{rank}. {id_text}{add}  —  {badge}  —  ↔ {meters_text}"
                    child = QTreeWidgetItem([line1 + (f"\n    📄 {desc}" if desc else "")])
                    child.setData(0, Qt.UserRole, {"pid": pid, "md": md})
                    if rank == 1:
                        child.setForeground(0, QColor("#0B5ED7"))  # zvýraznění první doporučené
                    root_item.addChild(child)
    
            _refresh_root_item(pid)
    
        lay_per.addWidget(tree, 1)
    
        row = QHBoxLayout()
        btn_assign_best = QPushButton("Přiřadit nejlepší každému")
        btn_close_per = QPushButton("Zavřít")
        row.addWidget(btn_assign_best)
        row.addStretch(1)
        row.addWidget(btn_close_per)
        lay_per.addLayout(row)
    
        tabs.addTab(tab_per, "Po fotkách")
    
        # --- Společné akce / přiřazování ---
        def _extract_numeric_location_id_from_filename(filename: str):
            parts = filename.split('+')
            if len(parts) < 2:
                return None
            last_part = parts[-1]
            base = last_part.split('.')[0] if '.' in last_part else last_part
            m = _re.search(r'(\d{1,5})$', base)
            return int(m.group(1)) if m else None
    
        def _resolve_cislolok_key_from_map_md(md: dict) -> str | None:
            c5 = md.get("cislolok5")
            fname = md.get("filename", "")
            if c5:
                try:
                    return self._normalize_cislolok(c5)
                except ValueError:
                    return None
            numeric_id = _extract_numeric_location_id_from_filename(fname)
            if numeric_id is None:
                return None
            try:
                return self._normalize_cislolok(str(numeric_id))
            except ValueError:
                return None
        def _assign_many(photo_ids_to_assign: list[int], md: dict) -> tuple[bool, str]:
            """Přiřadí jednu lokaci všem zadaným ID (hromadně). Vrací (ok, cislolok_key|err)."""
            cislolok_key = _resolve_cislolok_key_from_map_md(md)
            if cislolok_key is None:
                # dotaz na číslo lokace
                d2 = QDialog(self)
                d2.setWindowTitle("Zadej ČísloLokace (1–5 číslic)")
                d2.setMinimumWidth(420)
                l2 = QVBoxLayout(d2)
                fname = md.get("filename", "")
                l2.addWidget(QLabel(
                    f"Vybraná mapa: <b>{fname}</b><br>"
                    f"Zadej <b>ČísloLokace</b> (1–5 číslic). "
                    f"Např. <code>1</code> se uloží do JSON jako <code>1</code>."
                ))
                le = QLineEdit(d2); le.setPlaceholderText("např. 1 nebo 00001")
                b2 = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=d2)
                b2.button(QDialogButtonBox.Ok).setText("Použít")
                b2.button(QDialogButtonBox.Cancel).setText("Zrušit")
                l2.addWidget(le); l2.addWidget(b2)
                b2.accepted.connect(d2.accept); b2.rejected.connect(d2.reject)
                QShortcut(QKeySequence.Close, d2, d2.reject)
                if d2.exec() != QDialog.Accepted:
                    return False, "Zrušeno uživatelem."
                try:
                    cislolok_key = self._normalize_cislolok(le.text())
                except ValueError as e:
                    return False, str(e)
        
            try:
                # 1) Zápis lokace
                lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
                exist = self._numbers_from_intervals(lokace.get(cislolok_key, []))
                exist |= set(photo_ids_to_assign)
                lokace[cislolok_key] = self._merge_numbers_to_intervals(sorted(exist))
                self.ed_lokace.setPlainText(self._format_singleline_dict(lokace, sort_numeric_keys=True, align_values=True))
                self._save_editors_to_settings()
        
                # 2) NOVĚ: Auto-anonymizace pokud daná lokace má v metadatech „Anonymizovaná lokace: Ano“
                try:
                    def _map_requires_anon_for_key(_key: str) -> bool:
                        try:
                            from PIL import Image as _Image
                        except Exception:
                            _Image = None
                        try:
                            for _md in self._get_available_location_maps_from_dir() or []:
                                _fname = _md.get('filename', '') or ''
                                _abs = _md.get('absolute', '') or ''
                                _key_here = None
                                _c5 = _md.get('cislolok5')
                                if _c5:
                                    try:
                                        _key_here = self._normalize_cislolok(str(_c5))
                                    except Exception:
                                        _key_here = None
                                if _key_here is None:
                                    # vyčti číslo lokace z konce názvu souboru
                                    parts = (_fname or '').split('+')
                                    last = parts[-1] if parts else (_fname or '')
                                    base = last.split('.')[0] if '.' in last else last
                                    import re as _re
                                    m = _re.search(r'(\d{1,5})$', base)
                                    if m:
                                        try:
                                            _key_here = self._normalize_cislolok(str(int(m.group(1))))
                                        except Exception:
                                            _key_here = None
                                if _key_here != _key:
                                    continue
                                # metadata mapy
                                if _Image and _abs:
                                    try:
                                        with _Image.open(_abs) as _img:
                                            if hasattr(_img, 'text') and isinstance(_img.text, dict):
                                                for _k, _v in _img.text.items():
                                                    ks = str(_k).strip().lower()
                                                    vs = str(_v).strip().lower()
                                                    if ('anonym' in ks) or ('anonym' in vs):
                                                        if ('ano' in vs) or ('yes' in vs) or ('true' in vs) or (vs == '1'):
                                                            return True
                                    except Exception:
                                        pass
                                return False
                        except Exception:
                            return False
                        return False
        
                    if _map_requires_anon_for_key(cislolok_key):
                        _lok, _st, _poz, _an = self._get_current_settings_dicts()
                        _spec = None
                        if isinstance(_an, dict):
                            for _k in ("ANONYMIZOVANE", "ANONYM", "ANON", "ANONYMIZACE"):
                                if _k in _an:
                                    _spec = _an.get(_k)
                                    break
                        try:
                            _existing = self._numbers_from_intervals(_spec) if _spec is not None else set()
                        except Exception:
                            _existing = set()
                        _merged = sorted(set(_existing) | set(photo_ids_to_assign))
                        _an["ANONYMIZOVANE"] = self._merge_numbers_to_intervals(_merged)
                        self.ed_anonym.setPlainText(self._format_singleline_dict(_an, sort_numeric_keys=False, align_values=True))
                        self._save_editors_to_settings()
                except Exception:
                    # anonymizace je „best-effort“ – nesmí rozbít přiřazení lokace
                    pass
        
                # 3) housekeeping
                try:
                    self.remember_last_loc_assigned(
                        file_paths=[str(p) for p in files],
                        fids=photo_ids_to_assign,
                        persist=True
                    )
                except Exception:
                    pass
                self._schedule_json_tree_rebuild()
                return True, cislolok_key
        
            except Exception as e:
                return False, f"Chyba při ukládání JSON: {e}"
    
        def _assign_one(photo_id: int, md: dict) -> tuple[bool, str]:
            """Přiřadí lokaci jen jedné fotce."""
            return _assign_many([photo_id], md)
    
        # --- Akce TAB 1: hromadně ---
        def bulk_assign_from_item(item: QListWidgetItem):
            if not item:
                return
            md = item.data(Qt.UserRole)
            if not md:
                return
            ok, msg = _assign_many(photo_ids, md)
            if ok:
                QMessageBox.information(self, "Doporučit lokace", f"✅ Vše přiřazeno do lokace {msg}")
                dlg.accept()
            else:
                QMessageBox.warning(self, "Doporučit lokace", msg)
    
        lw.itemDoubleClicked.connect(bulk_assign_from_item)
    
        def on_bulk_ok():
            it = lw.currentItem()
            bulk_assign_from_item(it)
        bulk_btns.accepted.connect(on_bulk_ok)
        bulk_btns.rejected.connect(dlg.reject)
    
        # --- Akce TAB 2: po fotkách ---
        def on_tree_double_clicked(item: QTreeWidgetItem, column: int):
            data = item.data(0, Qt.UserRole)
            if not isinstance(data, dict):
                return
            pid = data.get("pid")
            md = data.get("md")
            if pid is None or md is None:
                return
            ok, msg = _assign_one(pid, md)
            if ok:
                # Aktualizuj lokální stav + vizuální indikaci
                assigned_by_id[pid] = msg
                _refresh_root_item(pid)
                QMessageBox.information(self, "Doporučit lokace", f"✅ Fotka {pid} přiřazena do lokace {msg}")
            else:
                QMessageBox.warning(self, "Doporučit lokace", msg)
        tree.itemDoubleClicked.connect(on_tree_double_clicked)
    
        def on_assign_best_for_all():
            assigned = 0
            skipped = 0
            errors = 0
            missing_cislolok: list[int] = []
            for pid, best in per_photo_best.items():
                if not best:
                    skipped += 1
                    continue
                md = best["map"]
                key = _resolve_cislolok_key_from_map_md(md)
                if key is None:
                    missing_cislolok.append(pid)
                    continue
                ok, msg = _assign_one(pid, md)
                if ok:
                    assigned += 1
                    # Aktualizuj lokální stav + vizuální indikaci pro tuto fotku
                    assigned_by_id[pid] = msg
                    _refresh_root_item(pid)
                else:
                    errors += 1
            if missing_cislolok:
                QMessageBox.warning(
                    self, "Doporučit lokace",
                    "U některých doporučených map nelze bez dotazu určit ČísloLokace.\n"
                    f"Fotky bez přiřazení: {', '.join(map(str, missing_cislolok))}\n"
                    "Tyto přiřaď ručně dvojklikem ve stromu."
                )
            QMessageBox.information(self, "Doporučit lokace",
                                    f"Hotovo.\nPřiřazeno: {assigned}\nBez doporučení: {skipped}\nChyby: {errors}")
        btn_assign_best.clicked.connect(on_assign_best_for_all)
        btn_close_per.clicked.connect(dlg.reject)
    
        # Zkratka zavření celého dialogu (Cmd/Ctrl+W)
        close_action = QAction("Zavřít", dlg)
        close_action.setShortcut(QKeySequence.Close)
        close_action.triggered.connect(dlg.reject)
        dlg.addAction(close_action)
    
        # >>> Velikost dialogu (výrazně vyšší)
        try:
            screen = QGuiApplication.primaryScreen()
            avail_h = screen.availableGeometry().height() if screen else 1400
            hint = dlg.sizeHint()
            target_h = min(int(hint.height() * 3.5), int(avail_h * 0.92))
            target_w = max(hint.width(), 1000)
            dlg.resize(target_w, target_h)
        except Exception:
            dlg.resize(1000, 1000)
    
        dlg.exec()

    def _json_action_assign_state(self, files: list[Path], state_key: str):
        """Přidá vybrané fotky (ČísloNálezu) do JSON 'stavy' pod daný klíč."""
        self._capture_json_tree_state()
        
        if state_key not in ALLOWED_STATES:
            QMessageBox.warning(self, "Přiřadit stav", f"Neplatný stav: {state_key}")
            return
    
        ids = []
        for p in files:
            s = self._extract_id_from_name(p.name)
            if not s:
                continue
            try:
                ids.append(int(s))
            except Exception:
                continue
        if not ids:
            QMessageBox.information(self, "Přiřadit stav", "Ve vybraných souborech se nepodařilo najít ČísloNálezu.")
            return
    
        try:
            lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
            exist = self._numbers_from_intervals(stavy.get(state_key, []))
            stavy[state_key] = self._merge_numbers_to_intervals(sorted(exist.union(set(ids))))
            # přepiš editor (abecedně řazené klíče)
            self.ed_stavy.setPlainText(self._format_singleline_dict(stavy, sort_numeric_keys=False, align_values=True))
            self._save_editors_to_settings()
            QMessageBox.information(self, "Přiřadit stav", f"Přidáno {len(ids)} fotek do stavu „{state_key}“.")
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{e}")
            return
    
        self._rebuild_json_right_tree()

    def _json_action_set_anonymized(self, files: list[Path]):
        """
        U vybraných souborů nastaví anonymizaci v JSONu:
          settings -> anonymizace: { "ANONYMIZOVANE": ["intervaly/čísla", ...] }
        - Neprovádí se žádné přejmenování souborů.
        - Zápis je v redukovaném (intervalovém) tvaru a editor zůstane jednořádkový.
        """
        # Stabilita pravého stromu
        self._capture_json_tree_state()
    
        ids = []
        for p in files:
            s = self._extract_id_from_name(p.name)
            if not s:
                continue
            try:
                ids.append(int(s))
            except Exception:
                continue
    
        if not ids:
            QMessageBox.information(self, "Anonymizace", "Ve vybraných souborech se nepodařilo najít ČísloNálezu.")
            return
    
        try:
            lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
    
            # existující specifikace anonymizace
            spec = (anonym or {}).get("ANONYMIZOVANE", [])
            existing = self._numbers_from_intervals(spec)
            merged = sorted(existing.union(set(ids)))
    
            if anonym is None or not isinstance(anonym, dict):
                anonym = {}
            anonym["ANONYMIZOVANE"] = self._merge_numbers_to_intervals(merged)
    
            # editor -> singleline + zarovnání
            self.ed_anonym.setPlainText(self._format_singleline_dict(anonym, sort_numeric_keys=False, align_values=True))
            # uložit + realtime refresh
            self._save_editors_to_settings()
    
            QMessageBox.information(
                self, "Anonymizace", f"Nastaveno jako anonymizované: {len(ids)} položek."
            )
        except Exception as e:
            QMessageBox.critical(self, "Chyba", f"Nepodařilo se aktualizovat konfiguraci:\n{e}")
            return
    
        self._schedule_json_tree_rebuild()
    
    def _numbers_from_intervals(self, intervals_list) -> set[int]:
        """Rozbalí seznam intervalů/čísel na množinu čísel."""
        nums = set()
        for item in intervals_list or []:
            s = str(item).strip()
            if not s:
                continue
            if '-' in s:
                try:
                    a, b = s.split('-', 1)
                    a, b = int(a), int(b)
                    if a > b:
                        a, b = b, a
                    nums.update(range(a, b + 1))
                except Exception:
                    continue
            else:
                try:
                    nums.add(int(s))
                except Exception:
                    continue
        return nums
    
    def _merge_numbers_to_intervals(self, numbers: list[int]) -> list[str]:
        """Spojí čísla do intervalů: [1,2,3,5] -> ['1-3','5']"""
        if not numbers:
            return []
        nums = sorted(set(numbers))
        out = []
        s = e = nums[0]
        for n in nums[1:]:
            if n == e + 1:
                e = n
            else:
                out.append(f"{s}-{e}" if s != e else str(s))
                s = e = n
        out.append(f"{s}-{e}" if s != e else str(s))
        return out
    
    def _extract_gps_from_file(self, file_path: str):
        """
        Extrahuje GPS souřadnice z EXIF (přebráno z pdf_generator_window.py, zkrácená verze):
        - Primárně Pillow + pillow-heif + piexif
        - Fallback: exifread
        Vrací (lat, lon) nebo None.
        """
        # Metoda 1: Pillow + piexif (+ HEIC registrace)
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
    
            try:
                import piexif
                with Image.open(file_path) as img:
                    if "exif" in img.info:
                        exif_dict = piexif.load(img.info["exif"])
                        gps = exif_dict.get("GPS")
                        if gps:
                            def _rat_to_float(x): return float(x[0]) / float(x[1]) if isinstance(x, tuple) and x[1] else float(x)
                            def _dms_to_deg(dms):
                                d, m, s = dms
                                return _rat_to_float(d) + _rat_to_float(m) / 60 + _rat_to_float(s) / 3600
    
                            lat = _dms_to_deg(gps.get(piexif.GPSIFD.GPSLatitude))
                            lon = _dms_to_deg(gps.get(piexif.GPSIFD.GPSLongitude))
                            lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef, b'N')
                            lon_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef, b'E')
                            if lat_ref in (b'S', 'S'): lat = -lat
                            if lon_ref in (b'W', 'W'): lon = -lon
                            return (lat, lon)
            except Exception:
                pass
        except Exception:
            pass
    
        # Metoda 2: exifread
        try:
            import exifread
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                    def _dms_to_decimal(vals):
                        try:
                            d = float(vals[0].num) / float(vals[0].den)
                            m = float(vals[1].num) / float(vals[1].den)
                            s = float(vals[2].num) / float(vals[2].den)
                            return d + m / 60 + s / 3600
                        except Exception:
                            return 0.0
                    lat = _dms_to_decimal(tags['GPS GPSLatitude'].values)
                    lon = _dms_to_decimal(tags['GPS GPSLongitude'].values)
                    lat_ref = tags.get('GPS GPSLatitudeRef')
                    lon_ref = tags.get('GPS GPSLongitudeRef')
                    if lat_ref and str(lat_ref.values) == 'S': lat = -lat
                    if lon_ref and str(lon_ref.values) == 'W': lon = -lon
                    return (lat, lon)
        except Exception:
            pass
    
        return None
    
    
    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        """Vzdálenost v kilometrech (z pdf_generator_window.py)."""
        import math
        R = 6371.0
        phi1 = math.radians(lat1); phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = (math.sin(dphi/2)**2
             + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2)
        return 2 * R * math.asin(math.sqrt(a))
    
    def _get_available_location_maps_from_dir(self) -> list[dict]:
        """
        Načte mapy ze složky LOCATION_MAPS_DIR.
        Vrací list dictů: {
            "location_id": <první token před '+'> (jen pro info),
            "cislolok5": <5 číslic z konce názvu za posledním '+', pokud existují>,
            "filename": <název souboru>,
            "absolute": <absolutní cesta>,
            "gps_point": (lat, lon)  nebo None,
            "has_polygons": False
        }
        """
        maps = []
        if not LOCATION_MAPS_DIR.exists() or not LOCATION_MAPS_DIR.is_dir():
            return maps
    
        from pathlib import Path
        import re
    
        map_exts = {'.jpg', '.jpeg', '.png', '.pdf'}
    
        # ✅ OPRAVA: povolíme S/J (Sever/Jih) a V/Z (Východ/Západ) + aplikujeme správné znaménko
        # Formát v názvu: ...GPS<lat><S|J>+<lon><V|Z>...
        gps_pattern = re.compile(r'GPS\s*([0-9]+(?:\.[0-9]+)?)\s*([SJ])\+([0-9]+(?:\.[0-9]+)?)\s*([VZ])', re.IGNORECASE)
    
        # 5 číslic za posledním '+', těsně před příponou
        last_plus_5digits = re.compile(r'\+(\d{5})(?:\.[^.]+)?$')
    
        for entry in sorted(LOCATION_MAPS_DIR.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir():
                continue
            if entry.suffix.lower() not in map_exts:
                continue
    
            name = entry.name
            # info: první token (před prvním '+')
            location_id = name.split('+')[0] if '+' in name else entry.stem
    
            # ČísloLokace z konce názvu (5 číslic po posledním '+')
            m_num = last_plus_5digits.search(name)
            cislolok5 = m_num.group(1) if m_num else None
    
            # GPS z názvu
            gps = None
            m_gps = gps_pattern.search(name)
            if m_gps:
                try:
                    lat = float(m_gps.group(1))
                    ns  = m_gps.group(2).upper()  # 'S' (Sever) nebo 'J' (Jih)
                    lon = float(m_gps.group(3))
                    ew  = m_gps.group(4).upper()  # 'V' (Východ) nebo 'Z' (Západ)
                    if ns == 'J':
                        lat = -lat
                    if ew == 'Z':
                        lon = -lon
                    gps = (lat, lon)
                except Exception:
                    gps = None
    
            maps.append({
                "location_id": location_id,
                "cislolok5": cislolok5,
                "filename": name,
                "absolute": str(entry),
                "gps_point": gps,
                "has_polygons": False,
            })
        return maps

    def _ids_with_state_but_no_note(self, stavy: dict, poznamky: dict) -> set[int]:
        """
        Vrátí množinu ČíselNálezů, které jsou ve STAVU vyžadujícím poznámku,
        ale nemají přiřazenou poznámku.
    
        POZOR – Poznámka je POVINNÁ jen pro stavy:
          • BEZFOTKY
          • DAROVANY
    
        Pro ostatní stavy (např. BEZGPS, ZTRACENY, NEUTRZEN, OBDAROVANY) je poznámka VOLITELNÁ.
        """
        # Stavy, pro které je poznámka vyžadována
        REQUIRED_NOTE_STATES = {"BEZFOTKY", "DAROVANY"}
    
        # IDs, které spadají do alespoň jednoho z povinných stavů
        ids_in_required_states: set[int] = set()
        for state, spec in (stavy or {}).items():
            try:
                if state in REQUIRED_NOTE_STATES:
                    ids_in_required_states |= self._numbers_from_intervals(spec)
            except Exception:
                continue
    
        # IDs, které mají poznámku (klíče mohou být stringy)
        ids_with_note: set[int] = set()
        for k in (poznamky or {}).keys():
            try:
                ids_with_note.add(int(str(k).strip()))
            except Exception:
                continue
    
        # Chybějící poznámka = v povinném stavu ∧ nemá poznámku
        return ids_in_required_states - ids_with_note

    def _on_rename_tree_context_menu(self, pos):
        """
        Kontextové menu stromu v záložce 'Přejmenování' – s ikonami.
        (sjednoceno s verzí "ze včerejška" + přidaná akce 'Přejmenovat podle JSON')
    
        Úprava (mírná, bez zásahu do logiky přejmenování):
        - U akcí „Defaultní pojmenování“ a „Přejmenovat podle JSON“ se před akcí
          sejme UI stav (expand/výběr + aktuální scroll) a watcher se dočasně umlčí.
          SCROLL se vrací až ÚPLNĚ NAKONEC (po všech rebuildech) přes QTimer,
          takže nedochází k „hopování“ nahoru/dolů.
        """
        from pathlib import Path
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QKeySequence
    
        index = self.ren_tree.indexAt(pos)
        items = self._gather_selected_items()
    
        # Když není výběr, vezmeme položku pod kurzorem
        if not items and index.isValid():
            it = self.ren_model.itemFromIndex(index)
            if it is not None:
                t = it.data(Qt.UserRole)
                p = it.data(Qt.UserRole + 1)
                if p:
                    items = [(Path(p), t == "dir")]
        if not items:
            return
    
        menu = QMenu(self.ren_tree)
        si = self.style().standardIcon  # zkratka pro standardní ikony
    
        # Pomocný wrapper pro hromadné akce (Default/JSON):
        # - sejmout snapshot UI (expand/výběr + scroll)
        # - umlčet watcher po dobu akce
        # - SCROLL vrátit AŽ NA KONCI (po všech rebuildech), bez průběžného scrollování
        def _run_batched(action_callable):
            # Snapshot
            state = self._capture_rename_ui_state() if hasattr(self, "_capture_rename_ui_state") else None
            try:
                vbar = self.ren_tree.verticalScrollBar()
                saved_scroll = int(vbar.value())
            except Exception:
                saved_scroll = 0
    
            # Sticky – ponecháme pouze expand/výběr; scroll necháme až na úplný konec
            if state:
                self._sticky_expand_paths = state.get("expanded", [])
                self._sticky_focus_path = state.get("current")
                self._sticky_scroll = None  # žádné průběžné vracení scrollu
    
            # Umlčet watcher po dobu akce
            self._suspend_fs_events = True
            self._rename_in_progress = True
    
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                # PŮVODNÍ AKCE (default rename / JSON rename) – nic v ní neměním
                action_callable()
            finally:
                QApplication.restoreOverrideCursor()
                self._rename_in_progress = False
                self._suspend_fs_events = False
    
                # FINÁLNÍ vrácení scrollu – až po všech rebuildech (žádné skoky)
                def _set_scroll(val=saved_scroll):
                    try:
                        sb = self.ren_tree.verticalScrollBar()
                        sb.setValue(val)
                    except Exception:
                        pass
    
                # jen plánujeme, aby to proběhlo po debounce/rebuildech watcheru
                QTimer.singleShot(0, _set_scroll)
                QTimer.singleShot(180, _set_scroll)
                QTimer.singleShot(320, _set_scroll)
    
                # Sticky proměnné vyčistíme až po poslední pojistce
                def _clear_sticky():
                    self._sticky_expand_paths = None
                    self._sticky_focus_path = None
                    self._sticky_scroll = None
                QTimer.singleShot(360, _clear_sticky)
    
        # --- Defaultní přejmenování ---
        act_default = QAction(si(QStyle.SP_DialogApplyButton), "Defaultní pojmenování", self)
        act_default.setIconVisibleInMenu(True)
        act_default.triggered.connect(lambda: _run_batched(self._on_click_default_rename_button))
        menu.addAction(act_default)
    
        # --- Přejmenovat podle JSON ---
        act_json = QAction(si(QStyle.SP_BrowserReload), "Přejmenovat podle JSON", self)
        act_json.setToolTip("Přejmenuje vybrané soubory/složky dle JSON nastavení.")
        act_json.setIconVisibleInMenu(True)
        if hasattr(self, "_action_intelligent_rename"):
            act_json.triggered.connect(lambda: _run_batched(self._action_intelligent_rename))
        else:
            act_json.setEnabled(False)
        menu.addAction(act_json)
    
        # --- Inline přejmenování (ENTER) ---
        act_rename = QAction(si(QStyle.SP_FileDialogDetailedView), "Přejmenovat…", self)
        act_rename.setIconVisibleInMenu(True)
        act_rename.setShortcut(QKeySequence(Qt.Key_Return))
        act_rename.triggered.connect(self._rename_selected_item)
        menu.addAction(act_rename)
    
        # --- Odstranit ---
        trash_sp = QStyle.SP_TrashIcon if hasattr(QStyle, "SP_TrashIcon") else QStyle.SP_DialogDiscardButton
        act_delete = QAction(si(trash_sp), "Odstranit", self)
        act_delete.setIconVisibleInMenu(True)
        act_delete.setShortcut(QKeySequence("Meta+Backspace"))
        act_delete.triggered.connect(self._delete_selected_items)
        menu.addAction(act_delete)
    
        menu.addSeparator()
    
        # --- Kopírovat cesty ---
        act_copy = QAction(si(QStyle.SP_DialogSaveButton), "Kopírovat cesty", self)
        act_copy.setIconVisibleInMenu(True)
        act_copy.setShortcut(QKeySequence.Copy)
        act_copy.triggered.connect(self._copy_selected_items)
        menu.addAction(act_copy)
    
        # --- Vložit cesty (jen pokud metoda existuje) ---
        if hasattr(self, "_paste_items_into_tree") and callable(getattr(self, "_paste_items_into_tree")):
            act_paste = QAction(si(QStyle.SP_DialogOpenButton), "Vložit cesty", self)
            act_paste.setIconVisibleInMenu(True)
            act_paste.setShortcut(QKeySequence.Paste)
            act_paste.triggered.connect(self._paste_items_into_tree)
            menu.addAction(act_paste)
    
        menu.addSeparator()
    
        # --- Zobrazit v umístění (Finder/Explorer/xdg-open) ---
        act_reveal = QAction(si(QStyle.SP_DirIcon), "Zobrazit v umístění", self)
        act_reveal.setIconVisibleInMenu(True)
    
        def _reveal():
            import os, sys, subprocess
            idx = self.ren_tree.currentIndex()
            if not idx.isValid():
                return
            it = self.ren_model.itemFromIndex(idx)
            p = Path(it.data(Qt.UserRole + 1) or "")
            if not p.exists():
                return
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", "--reveal", str(p)])
                elif os.name == "nt":
                    subprocess.run(["explorer", str(p)])
                else:
                    subprocess.run(["xdg-open", str(p.parent if p.is_file() else p)])
            except Exception:
                pass
    
        act_reveal.triggered.connect(_reveal)
        menu.addAction(act_reveal)
    
        # --- Sbalit vše ---
        act_collapse = QAction(si(QStyle.SP_ArrowDown), "Sbalit vše", self)
        act_collapse.setIconVisibleInMenu(True)
        act_collapse.triggered.connect(self._on_collapse_all_rename_clicked)
        menu.addAction(act_collapse)
    
        menu.exec(self.ren_tree.viewport().mapToGlobal(pos))
        
    def _schedule_final_scroll_restore(self, value: int):
        """
        Naplánuje jediné finální vrácení scrollu po všech rebuildech/layoutech.
        Opakovaná volání se slévají; pokusí se max 3x s rozestupem 80 ms.
        """
        from PySide6.QtCore import QTimer
    
        try:
            self._final_scroll_value = int(value)
        except Exception:
            self._final_scroll_value = 0
    
        # Init timeru jen jednou
        t = getattr(self, "_final_scroll_timer", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._apply_final_scroll_restore)
            setattr(self, "_final_scroll_timer", t)
            setattr(self, "_final_scroll_tries", 0)
    
        # restartuj okno, ať se to provede AŽ po všech předchozích debouncích
        try:
            t.stop()
        except Exception:
            pass
        t.start(80)
    
    
    def _apply_final_scroll_restore(self):
        """
        Provede jeden pokus o vrácení scrollu. Pokud ještě layout není stabilní,
        zopakuje po 80 ms (max 3 pokusy).
        """
        from PySide6.QtCore import QTimer
    
        tree = getattr(self, "ren_tree", None) or getattr(self, "tree_rename", None)
        if tree is None or not hasattr(tree, "verticalScrollBar"):
            return
    
        try:
            vbar = tree.verticalScrollBar()
            vbar.setValue(int(getattr(self, "_final_scroll_value", 0)))
        except Exception:
            pass
    
        # Další pokus, pokud ještě „žbluňká“ layout
        tries = int(getattr(self, "_final_scroll_tries", 0)) + 1
        setattr(self, "_final_scroll_tries", tries)
        if tries < 3:
            t = getattr(self, "_final_scroll_timer", None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
                t.start(80)
        else:
            # hotovo – vynuluj počitadlo, timer necháme re-use
            setattr(self, "_final_scroll_tries", 0)

    def _rename_selected_item(self):
        """
        Přejmenuje první vybranou položku (soubor i složku).
        U souboru uživatel edituje jen 'název bez přípony'; přípona zůstane zachována.
        Po akci vrátí fokus do stromu a uloží stav pro příští spuštění.
        """
        from pathlib import Path
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QLineEdit, QPushButton, QMessageBox
        )
    
        if not hasattr(self, "ren_tree") or not hasattr(self, "ren_model"):
            return
    
        indexes = self.ren_tree.selectedIndexes()
        if not indexes:
            return
    
        # Najdi první položku
        item = None
        for idx in indexes:
            if idx.isValid():
                it = self.ren_model.itemFromIndex(idx)
                if it is not None:
                    item = it
                    break
        if item is None:
            return
    
        old_path_str = item.data(Qt.UserRole + 1)
        if not old_path_str:
            return
        old_path = Path(old_path_str)
        if not old_path.exists():
            QMessageBox.warning(self, "Přejmenování", "Položka už neexistuje.")
            return
    
        # Zachyť stav před akcí (expand/scroll/selection/focus)
        state_before = self._capture_rename_ui_state()
    
        # === NOVĚ: umlčení watcheru + sticky stav pro přesné obnovení UI ===
        self._suspend_fs_events = True
        self._rename_in_progress = True
        try:
            self._sticky_expand_paths = state_before.get("expanded", [])
            self._sticky_scroll = state_before.get("scroll")
            self._sticky_focus_path = state_before.get("current")
        except Exception:
            # fail-safe
            self._sticky_expand_paths = getattr(self, "_sticky_expand_paths", None)
            self._sticky_scroll = getattr(self, "_sticky_scroll", None)
            self._sticky_focus_path = getattr(self, "_sticky_focus_path", None)
    
        # Dialog
        is_file = item.data(Qt.UserRole) == "file"
    
        dlg = QDialog(self)
        dlg.setWindowTitle("Přejmenovat")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"Aktuální: <b>{old_path.name}</b>"))
    
        le = QLineEdit(dlg)
        if is_file:
            # Soubor: editujeme jen STŘED (stem), přípona zůstane zachována
            old_stem, old_suffix = old_path.stem, old_path.suffix
            le.setText(old_stem)
            le.setPlaceholderText("název souboru (bez přípony)")
            ext_lbl = QLabel(f"Přípona zůstane zachována: <b>{old_suffix or ''}</b>")
            v.addWidget(le)
            v.addWidget(ext_lbl)
        else:
            # Složka: editujeme celý název složky
            le.setText(old_path.name)
            le.setPlaceholderText("název složky")
            v.addWidget(le)
    
        btns = QHBoxLayout()
        ok = QPushButton("Přejmenovat")
        cancel = QPushButton("Zrušit")
        btns.addWidget(ok); btns.addWidget(cancel)
        v.addLayout(btns)
    
        ok.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)
    
        if dlg.exec() != QDialog.Accepted:
            # uživatel zrušil – pouze obnov fokus, nic jiného nedělat
            QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
            # === NOVĚ: ukončení rename seance ===
            self._rename_in_progress = False
            self._suspend_fs_events = False
            self._sticky_expand_paths = None
            self._sticky_scroll = None
            self._sticky_focus_path = None
            return
    
        new_name_raw = (le.text() or "").strip()
        if not new_name_raw:
            QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
            # === NOVĚ: ukončení rename seance ===
            self._rename_in_progress = False
            self._suspend_fs_events = False
            self._sticky_expand_paths = None
            self._sticky_scroll = None
            self._sticky_focus_path = None
            return
    
        # Sestavení cílové cesty
        if is_file:
            new_path = old_path.with_name(new_name_raw + old_path.suffix)
        else:
            new_path = old_path.with_name(new_name_raw)
    
        if new_path == old_path:
            QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
            # === NOVĚ: ukončení rename seance ===
            self._rename_in_progress = False
            self._suspend_fs_events = False
            self._sticky_expand_paths = None
            self._sticky_scroll = None
            self._sticky_focus_path = None
            return
    
        # Kolizní chování: necháme vyhodit chybu jako doposud (zachování původního UX)
        try:
            old_path.rename(new_path)
        except Exception as e:
            QMessageBox.critical(self, "Přejmenování selhalo", f"{e}")
            # === NOVĚ: ukončení rename seance i v případě chyby ===
            self._rename_in_progress = False
            self._suspend_fs_events = False
            self._sticky_expand_paths = None
            self._sticky_scroll = None
            self._sticky_focus_path = None
            return
    
        # Rebuild s plným zachováním stavu + výběr nového souboru
        path_map = {str(old_path): str(new_path)}
        self._rebuild_rename_tree(preserve_state=True, path_map=path_map)
    
        # >>> JSON: refresh pravého stromu (zachovat rozbalení/scroll/fokus)
        try:
            self._schedule_json_tree_rebuild()
        except Exception:
            pass
    
        # rychle umožnit další akci (Enter/F2) a uložit stav na disk
        QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
        self._save_rename_ui_state()
    
        # === NOVĚ: ukončení rename seance ===
        self._rename_in_progress = False
        self._suspend_fs_events = False
        self._sticky_expand_paths = None
        self._sticky_scroll = None
        self._sticky_focus_path = None
    
    def _delete_selected_items(self):
        """
        Smaže vybrané soubory/složky. Po akci obnoví UI stav a uloží ho.
        """
        if not hasattr(self, "ren_tree") or not hasattr(self, "ren_model"):
            return
        indexes = self.ren_tree.selectedIndexes()
        if not indexes:
            return
    
        # Jedinečné cesty k položkám
        paths = set()
        for idx in indexes:
            if idx.column() != 0 or not idx.isValid():
                continue
            it = self.ren_model.itemFromIndex(idx)
            p = it.data(Qt.UserRole + 1) if it else None
            if p:
                paths.add(Path(p))
    
        if not paths:
            return
    
        reply = QMessageBox.question(
            self, "Potvrzení smazání",
            f"Opravdu chcete smazat {len(paths)} položku(ek)?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
    
        state_before = self._capture_rename_ui_state()
        fallback_parent = None
        try:
            any_p = next(iter(paths))
            fallback_parent = str(any_p.parent)
        except Exception:
            pass
    
        import shutil
        for p in sorted(paths, key=lambda x: len(str(x)), reverse=True):
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                elif p.is_file():
                    p.unlink()
            except Exception as e:
                QMessageBox.warning(self, "Chyba při mazání", f"Nelze smazat {p}:\n{e}")
    
        if state_before.get("current") and not Path(state_before["current"]).exists():
            state_before["current"] = fallback_parent
    
        self._rebuild_rename_tree(preserve_state=state_before)
        QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
        self._save_rename_ui_state()
    
    def _copy_selected_items(self):
        """
        Zkopíruje vybrané cesty (soubory/složky) do clipboardu jako text (každá cesta na nový řádek).
        """
        if not hasattr(self, "ren_tree") or not hasattr(self, "ren_model"):
            return
        indexes = self.ren_tree.selectedIndexes()
        if not indexes:
            return
    
        paths: list[str] = []
        seen = set()
        for idx in indexes:
            if not idx.isValid() or idx.column() != 0:
                continue
            it = self.ren_model.itemFromIndex(idx)
            p = it.data(Qt.UserRole + 1) if it is not None else None
            if not p or p in seen:
                continue
            seen.add(p)
            paths.append(p)
    
        if not paths:
            return
    
        cb = QApplication.clipboard()
        cb.setText("\n".join(paths))
        
    def _destination_dir_for_paste(self) -> Path:
        """
        Určí cílovou složku pro vkládání:
          - je-li vybrána složka → do ní,
          - je-li vybrán soubor → do parent složky,
          - jinak fallback: OREZY_DIR (existuje-li), jinak ORIGINALS_DIR.
        """
        dest_dir = None
        if hasattr(self, "ren_tree") and hasattr(self, "ren_model"):
            idx = self.ren_tree.currentIndex()
            if idx.isValid():
                it = self.ren_model.itemFromIndex(idx)
                if it is not None:
                    path_str = it.data(Qt.UserRole + 1)
                    if path_str:
                        p = Path(path_str)
                        if p.exists():
                            dest_dir = p if p.is_dir() else p.parent
        if dest_dir is None or not dest_dir.exists():
            dest_dir = OREZY_DIR if OREZY_DIR.exists() else ORIGINALS_DIR
        return dest_dir
    
    def _unique_dest_path(self, base_path: Path) -> Path:
        """
        Vrátí nekolidující cestu. Pokud `base_path` existuje,
        zkouší 'name copy', 'name copy 2', ... (před příponou u souborů).
        """
        if not base_path.exists():
            return base_path
    
        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent
    
        # u souborů zachovej příponu; u složek suffix = ""
        candidate = parent / f"{stem} copy{suffix}"
        i = 2
        while candidate.exists() and i <= 9999:
            candidate = parent / f"{stem} copy {i}{suffix}"
            i += 1
        return candidate
    
    def _paste_items(self):
        """
        Vloží soubory/složky z clipboardu do cílové složky.
        Po akci obnoví stav, fokusne nově vloženou položku (pokud je jediná) a uloží stav.
        """
        cb = QApplication.clipboard()
        md = cb.mimeData()
        src_paths: list[Path] = []
    
        # URLs
        try:
            if md and md.hasUrls():
                for url in md.urls():
                    if url.isLocalFile():
                        p = Path(url.toLocalFile())
                        if p.exists():
                            src_paths.append(p)
        except Exception:
            pass
    
        # Textové cesty
        if not src_paths:
            text = cb.text() or ""
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                p = Path(s)
                if p.exists():
                    src_paths.append(p)
    
        if not src_paths:
            QMessageBox.information(self, "Vložit", "Schránka neobsahuje platné cesty.")
            return
    
        dest_dir = self._destination_dir_for_paste() if hasattr(self, "_destination_dir_for_paste") else (OREZY_DIR if OREZY_DIR.exists() else ORIGINALS_DIR)
        if not dest_dir.exists():
            QMessageBox.warning(self, "Vložit", f"Cílová složka neexistuje:\n{dest_dir}")
            return
    
        state_before = self._capture_rename_ui_state()
    
        import shutil
        copied = 0
        errors = 0
        last_new = None
        for src in src_paths:
            try:
                if src.is_file():
                    dest = self._unique_dest_path(dest_dir / src.name) if hasattr(self, "_unique_dest_path") else dest_dir / src.name
                    if dest.exists():
                        # jednoduché unikátní jméno
                        i = 1
                        base = dest.stem
                        suf  = dest.suffix
                        while dest.exists() and i < 1000:
                            dest = dest_dir / f"{base} copy {i}{suf}"
                            i += 1
                    shutil.copy2(src, dest)
                    copied += 1
                    last_new = dest
                elif src.is_dir():
                    dest = dest_dir / src.name
                    i = 1
                    while dest.exists() and i < 1000:
                        dest = dest_dir / f"{src.name} copy {i}"
                        i += 1
                    shutil.copytree(src, dest)
                    copied += 1
                    last_new = dest
            except Exception:
                errors += 1
    
        if copied == 1 and last_new is not None:
            state_before["current"] = str(last_new)
            state_before["selected"] = [str(last_new)]
    
        self._rebuild_rename_tree(preserve_state=state_before)
        QTimer.singleShot(0, lambda: self.ren_tree.setFocus(Qt.OtherFocusReason))
        self._save_rename_ui_state()
    
        QMessageBox.information(self, "Vložit", f"Zkopírováno: {copied}\nChyb: {errors}")
  
        
  
    
  
    def _missing_intervals_from_sorted(self, sorted_ids: list[int]) -> list[str]:
        """
        Vrátí intervaly chybějících čísel v rozsahu <min..max> na základě seřazených existujících ID.
        Efektivní O(n) bez generování celé množiny chybějících čísel.
        Příklad: sorted_ids=[1,2,5,6,9] -> chybí ['3-4','7-8']
        """
        if not sorted_ids or len(sorted_ids) < 2:
            return []
        gaps: list[str] = []
        for a, b in zip(sorted_ids, sorted_ids[1:]):
            if b == a or b == a + 1:
                continue
            start = a + 1
            end = b - 1
            gaps.append(f"{start}" if start == end else f"{start}-{end}")
        return gaps  
    
    def _capture_rename_ui_state(self) -> dict:
        """
        Zachytí kompletní UI stav stromu 'Přejmenování':
          - expanded: list[str] absolutních cest rozbalených SLOŽEK,
          - selected: list[str] absolutních cest vybraných položek (soubory i složky),
          - current:  str | None  absolutní cesta aktuální položky,
          - scroll:   int | None  vertikální scroll.
        """
        state = {"expanded": [], "selected": [], "current": None, "scroll": None}
        if not hasattr(self, "ren_tree") or not hasattr(self, "ren_model"):
            return state
    
        # expanded složky (recyklujeme vnitřní logiku)
        expanded = []
        def walk_dirs(item):
            for r in range(item.rowCount()):
                it = item.child(r)
                if it is None:
                    continue
                if it.data(Qt.UserRole) == "dir":
                    idx = self.ren_model.indexFromItem(it)
                    if self.ren_tree.isExpanded(idx):
                        p = it.data(Qt.UserRole + 1)
                        if p: expanded.append(p)
                    walk_dirs(it)
        for rr in range(self.ren_model.rowCount()):
            root_item = self.ren_model.item(rr)
            if root_item and root_item.data(Qt.UserRole) == "dir":
                idx = self.ren_model.indexFromItem(root_item)
                if self.ren_tree.isExpanded(idx):
                    p = root_item.data(Qt.UserRole + 1)
                    if p: expanded.append(p)
                walk_dirs(root_item)
    
        # výběr (soubory i složky)
        selected = []
        try:
            sel = self.ren_tree.selectionModel()
            if sel:
                for idx in sel.selectedIndexes():
                    if not idx.isValid() or idx.column() != 0:
                        continue
                    it = self.ren_model.itemFromIndex(idx)
                    p = it.data(Qt.UserRole + 1) if it else None
                    if p and p not in selected:
                        selected.append(p)
        except Exception:
            pass
    
        # current
        try:
            cur_idx = self.ren_tree.currentIndex()
            if cur_idx.isValid():
                it = self.ren_model.itemFromIndex(cur_idx)
                if it:
                    state["current"] = it.data(Qt.UserRole + 1)
        except Exception:
            pass
    
        # scroll
        try:
            state["scroll"] = self.ren_tree.verticalScrollBar().value()
        except Exception:
            state["scroll"] = None
    
        state["expanded"] = expanded
        state["selected"] = selected
        return state    
        
    def _index_for_path(self, path_str: str):
        """
        Vrátí QModelIndex pro danou absolutní cestu (soubor nebo složka).
        Vyžaduje, aby _rebuild_rename_tree plnil mapu self._ren_all_items[path] -> QStandardItem.
        """
        try:
            it = getattr(self, "_ren_all_items", {}).get(path_str)
            if it is None:
                return QModelIndex()
            return self.ren_model.indexFromItem(it)
        except Exception:
            return QModelIndex()    
        
    def _restore_rename_ui_state(self, state: dict | None, path_map: dict[str, str] | None = None) -> None:
        """
        Obnoví stav stromu:
          - rozbalení složek (expanded),
          - výběr (selected),
          - current fokus (current),
          - scroll (scroll).
        path_map (volitelné): mapování starých cest -> nových (např. při přejmenování).
        Pokud nějaká položka už neexistuje, zkusí její parent.
        """
        if not state or not hasattr(self, "ren_tree") or not hasattr(self, "ren_model"):
            return
    
        def map_path(p: str | None) -> str | None:
            if p is None:
                return None
            if path_map and p in path_map:
                return path_map[p]
            return p
    
        # Rozbalení složek
        for p in state.get("expanded", []):
            mp = map_path(p)
            if not mp:
                continue
            idx = self._index_for_path(mp)
            if idx.isValid():
                self.ren_tree.setExpanded(idx, True)
    
        # Výběr
        sel = self.ren_tree.selectionModel()
        if sel:
            sel.clearSelection()
            flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
            any_selected = False
            for p in state.get("selected", []):
                mp = map_path(p)
                if not mp:
                    continue
                idx = self._index_for_path(mp)
                if idx.isValid():
                    sel.select(idx, flags)
                    any_selected = True
                else:
                    # fallback: zkus parent složku
                    parent = str(Path(mp).parent)
                    pidx = self._index_for_path(parent)
                    if pidx.isValid():
                        sel.select(pidx, flags)
                        any_selected = True
    
            # Current index
            cur_path = map_path(state.get("current"))
            if cur_path:
                cidx = self._index_for_path(cur_path)
                if cidx.isValid():
                    self.ren_tree.setCurrentIndex(cidx)
                    self.ren_tree.scrollTo(cidx, QTreeView.PositionAtCenter)
                elif any_selected:
                    # aspoň první vybraný
                    idxs = sel.selectedIndexes()
                    if idxs:
                        self.ren_tree.setCurrentIndex(idxs[0])
                        self.ren_tree.scrollTo(idxs[0], QTreeView.PositionAtCenter)
    
        # Scroll
        try:
            scr = state.get("scroll")
            if scr is not None:
                self.ren_tree.verticalScrollBar().setValue(int(scr))
        except Exception:
            pass    
    
    def _save_rename_ui_state(self) -> None:
        """
        Uloží stav stromu 'Přejmenování' do RENAME_STATE_FILE:
          { expanded: [abs_dir_paths], selected: [abs_paths], current: str|None, scroll: int|None }.
        Bezpečně ignoruje chyby.
        """
        try:
            state = self._capture_rename_ui_state()
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            # kompatibilita se starší strukturou (kdy byl jen 'expanded')
            payload = {
                "expanded": state.get("expanded", []),
                "selected": state.get("selected", []),
                "current":  state.get("current"),
                "scroll":   state.get("scroll"),
            }
            RENAME_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_cached_status(self) -> dict | None:
        """
        Načte poslední známé hodnoty indikátorů z disku.
        Struktura:
        {
          "ts": "2025-09-16T12:34:56",
          "overview": {
             "orezy":     {"total": int, "valid": int, "invalid": int},
             "originaly": {"total": int, "valid": int, "invalid": int}
          },
          "rename": {
             "counts_html": str,         # HTML pro self.lbl_counts
             "name_mismatch": int,       # počet rozdílných názvů
             "format_errors": int,       # počet chyb formátu
             "range_html": str           # HTML pro self.lbl_range_missing
          }
        }
        """
        try:
            if STATUS_CACHE_FILE.exists():
                data = json.loads(STATUS_CACHE_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
        except Exception:
            pass
        return None
    
    
    def _apply_cached_status(self, cache: dict | None) -> None:
        """
        Neinvazivně aplikuje cache do UI, pokud existuje:
        - Přepíše jen existující labely (bez chyb při neexistenci).
        - Žádné vlákno ani sken – jen rychlé zobrazení posledního známého stavu.
        """
        if not cache or not isinstance(cache, dict):
            return
    
        # TAB 1 – „Kontrola stavu fotek na web“
        ov = cache.get("overview", {})
        if ov:
            ore = ov.get("orezy", {})
            org = ov.get("originaly", {})
            if hasattr(self, "lbl_total_a"):   self.lbl_total_a.setText(str(ore.get("total", "-")))
            if hasattr(self, "lbl_valid_a"):   self.lbl_valid_a.setText(str(ore.get("valid", "-")))
            if hasattr(self, "lbl_invalid_a"): self.lbl_invalid_a.setText(str(ore.get("invalid", "-")))
            if hasattr(self, "lbl_total_b"):   self.lbl_total_b.setText(str(org.get("total", "-")))
            if hasattr(self, "lbl_valid_b"):   self.lbl_valid_b.setText(str(org.get("valid", "-")))
            if hasattr(self, "lbl_invalid_b"): self.lbl_invalid_b.setText(str(org.get("invalid", "-")))
    
        # TAB 3 – „Přejmenování“ → panel Kontrola
        rn = cache.get("rename", {})
        if rn:
            if hasattr(self, "lbl_counts") and rn.get("counts_html") is not None:
                self.lbl_counts.setText(rn["counts_html"])
            if hasattr(self, "lbl_name_mismatch") and rn.get("name_mismatch") is not None:
                self.lbl_name_mismatch.setText(f"<b>Rozdílné názvy:</b> {int(rn['name_mismatch'])}")
                self.lbl_name_mismatch.setStyleSheet("color: #FFA000; font-weight: bold;" if int(rn["name_mismatch"])>0 else "")
            if hasattr(self, "lbl_format_errors") and rn.get("format_errors") is not None:
                self.lbl_format_errors.setText(f"<b>Chyby formátu:</b> {int(rn['format_errors'])}")
                self.lbl_format_errors.setStyleSheet("color: #D32F2F; font-weight: bold;" if int(rn["format_errors"])>0 else "")
            if hasattr(self, "lbl_range_missing") and rn.get("range_html") is not None:
                self.lbl_range_missing.setText(rn["range_html"])
    
    
    def _snapshot_status_for_cache(self) -> dict:
        """
        Vytvoří snapshot „toho, co teď vidí uživatel“ (z labelů) – je to rychlé a spolehlivé.
        Používá se v closeEvent před uložením na disk.
        """
        def _to_int(txt: str, default: int = 0) -> int:
            try:
                return int(str(txt).strip())
            except Exception:
                return default
    
        overview = {}
        # Z TAB 1 (pokud labely existují)
        if hasattr(self, "lbl_total_a"):
            overview["orezy"] = {
                "total":   _to_int(self.lbl_total_a.text()),
                "valid":   _to_int(self.lbl_valid_a.text()),
                "invalid": _to_int(self.lbl_invalid_a.text()),
            }
        if hasattr(self, "lbl_total_b"):
            overview["originaly"] = {
                "total":   _to_int(self.lbl_total_b.text()),
                "valid":   _to_int(self.lbl_valid_b.text()),
                "invalid": _to_int(self.lbl_invalid_b.text()),
            }
    
        # Z TAB 3 – Přejmenování / Kontrola
        rename = {}
        if hasattr(self, "lbl_counts"):
            # ukládáme již vyrenderovaný HTML text (rychlá obnova 1:1)
            rename["counts_html"] = self.lbl_counts.text()
        if hasattr(self, "lbl_name_mismatch"):
            # vytáhneme pouze číslo z textu, pokud to jde
            nm_txt = self.lbl_name_mismatch.text()
            rename["name_mismatch"] = _to_int(re.findall(r"(\d+)", nm_txt)[-1] if re.findall(r"(\d+)", nm_txt) else 0)
        if hasattr(self, "lbl_format_errors"):
            fe_txt = self.lbl_format_errors.text()
            rename["format_errors"] = _to_int(re.findall(r"(\d+)", fe_txt)[-1] if re.findall(r"(\d+)", fe_txt) else 0)
        if hasattr(self, "lbl_range_missing"):
            rename["range_html"] = self.lbl_range_missing.text()
    
        payload = {
            "ts":  __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "overview": overview,
            "rename":   rename,
        }
        return payload
    
    
    def _save_cached_status(self, data: dict) -> None:
        """Uloží cache na disk (tiché, bezpečné)."""
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            STATUS_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass    
    
    def _load_rename_ui_state(self) -> dict | None:
        """
        Načte uložený stav stromu 'Přejmenování' z RENAME_STATE_FILE.
        Vrací dict kompatibilní s _capture_rename_ui_state() nebo None, když není co načíst.
        Umí číst i starý formát { "expanded": [...] }.
        """
        if not RENAME_STATE_FILE.exists():
            return None
        try:
            data = json.loads(RENAME_STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            # starší formát – pouze expanded
            if "expanded" in data and not any(k in data for k in ("selected", "current", "scroll")):
                return {
                    "expanded": data.get("expanded", []) or [],
                    "selected": [],
                    "current":  None,
                    "scroll":   None,
                }
            # nový formát
            return {
                "expanded": data.get("expanded", []) or [],
                "selected": data.get("selected", []) or [],
                "current":  data.get("current"),
                "scroll":   data.get("scroll"),
            }
        except Exception:
            return None 
        
        
        
    def _icon(self, theme_names: list[str], fallback_sp: QStyle.StandardPixmap) -> QIcon:
        """
        Vrátí QIcon: 1) z XDG/Theme dle seznamu 'theme_names', 2) fallback na QStyle standard pixmap.
        Použití: self._icon(["edit-copy", "edit-copy-symbolic"], QStyle.SP_FileIcon)
        """
        for name in theme_names:
            ico = QIcon.fromTheme(name)
            if not ico.isNull():
                return ico
        return self.style().standardIcon(fallback_sp)
    
    def _apply_indicator_styles(self) -> None:
        """
        Jednotný 'dark badge' vzhled pro indikátory ve všech záložkách.
        - Tmavé pozadí, bílý text; barevný lem podle varianty.
        - Pokrývá jak 'lbl_*' (Přejmenování), tak 'chk_*' (Kontrola stavu fotek na web).
        Chybějící labely bezpečně přeskočí.
        """
        dark_badge_css = """
            QLabel[role="badge-text"] {
                padding: 6px 10px;
                border: 1px solid rgba(255,255,255,0.20);
                border-radius: 8px;
                background: #1f2937;  /* dark slate */
                color: #ffffff;
            }
            QLabel[role="badge-title"] {
                font-weight: 600;
                color: #ffffff;
            }
            /* varianty – barevný lem */
            QLabel[variant="ok"]    { border-color: #2e7d32; }  /* zelená */
            QLabel[variant="warn"]  { border-color: #fb8c00; }  /* oranžová */
            QLabel[variant="error"] { border-color: #c62828; }  /* červená */
            QLabel[variant="info"]  { border-color: #1976d2; }  /* modrá */
            QLabel[variant="muted"] { border-color: rgba(255,255,255,0.18); }
        """
        self.setStyleSheet(self.styleSheet() + "\n" + dark_badge_css)
    
        from PySide6.QtWidgets import QLabel as _QLabel
    
        def mark(lbl, variant: str = "info"):
            if isinstance(lbl, _QLabel):
                lbl.setProperty("role", "badge-text")
                lbl.setProperty("variant", variant)
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
    
        # --- Přejmenování (lbl_*) ---
        mark(getattr(self, "lbl_counts", None), "info")
        mark(getattr(self, "lbl_name_mismatch", None), "warn")
        mark(getattr(self, "lbl_format_errors", None), "error")
        mark(getattr(self, "lbl_format_ok", None), "ok")
    
        # „Rozsah a chybějící ID“ – různé možné názvy
        for attr in (
            "lbl_range_missing", "lbl_range", "lbl_range_summary", "lbl_missing_ids",
            "lbl_range_and_missing", "chk_badge_range", "chk_badge_range_text"
        ):
            mark(getattr(self, attr, None), "info")
    
        # „Poslední kontrola“ – různé možné názvy
        for attr in (
            "lbl_last_check", "lbl_lastcheck", "chk_badge_lastcheck", "chk_badge_lastcheck_text"
        ):
            mark(getattr(self, attr, None), "muted")
    
        # --- Kontrola stavu fotek na web (chk_*) — sjednocení variant s Přejmenováním ---
        mark(getattr(self, "chk_counts", None), "info")
        mark(getattr(self, "chk_name_mismatch", None), "warn")
        mark(getattr(self, "chk_format_errors", None), "error")
        mark(getattr(self, "chk_format_ok", None), "ok")
        mark(getattr(self, "chk_range_missing", None), "info")  # stejné jako v Přejmenování
        mark(getattr(self, "chk_last_check", None), "muted")
    
        # Dlaždice s čísly v souhrnném gridu ponecháme tlumené
        for attr in ("lbl_total_a", "lbl_valid_a", "lbl_invalid_a",
                     "lbl_total_b", "lbl_valid_b", "lbl_invalid_b"):
            mark(getattr(self, attr, None), "muted")
            
    def _restyle_last_check_as_badge(self) -> None:
        """
        Převést 'Poslední kontrola' na dvouřádkový dark badge:
        Nadpis (tučně) + odřádkovaný čas. Platí pro lbl_* i chk_*.
        """
        lbl = None
        for name in (
            # Přejmenování
            "lbl_last_check", "lbl_lastcheck", "chk_badge_lastcheck_text", "chk_badge_lastcheck",
            # Kontrola stavu fotek na web
            "chk_last_check",
        ):
            cand = getattr(self, name, None)
            if isinstance(cand, QLabel):
                lbl = cand
                break
        if not lbl:
            return
    
        raw = (lbl.text() or "").strip()
        if "<div" not in raw and "<br" not in raw:
            html = (
                "<div>"
                "<div style='font-weight:600; color:#fff;'>Poslední kontrola</div>"
                f"<div style='margin-left:8px; color:#fff;'>{raw}</div>"
                "</div>"
            )
            lbl.setTextFormat(Qt.RichText)
            lbl.setText(html)
    
        lbl.setProperty("role", "badge-text")
        lbl.setProperty("variant", "muted")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
    
    def _force_range_badge_style(self) -> None:
        """
        Ujistí se, že 'Rozsah a chybějící ID' má 'dark badge' vzhled
        (pokrývá jak lbl_* v Přejmenování, tak chk_* v Kontrole).
        """
        target = None
        for name in (
            # Přejmenování
            "lbl_range_missing", "lbl_range", "lbl_range_summary",
            "lbl_missing_ids", "lbl_range_and_missing",
            "chk_badge_range", "chk_badge_range_text",
            # Kontrola stavu fotek na web
            "chk_range_missing",
        ):
            cand = getattr(self, name, None)
            if isinstance(cand, QLabel):
                target = cand
                break
    
        if not target:
            return
    
        target.setProperty("role", "badge-text")
        target.setProperty("variant", "info")
        target.setTextFormat(Qt.RichText)
        target.style().unpolish(target)
        target.style().polish(target)
        
    def _json_badges_for_id(self, fid: int, lokace: dict, stavy: dict, poznamky: dict, anonym: dict) -> str:
        """
        Vrátí text s 'badges' za názvem souboru pro dané ČísloNálezu (fid).
        Původně: ✅ (lokace), ⚙️ (stav), 📝 (poznámka), 🕶️ (anonym)
        ZMĚNA: anonym -> 🔒 (lépe viditelné v dark stylu)
        """
        badges: list[str] = []
    
        # ✅ – má přiřazenou lokaci
        try:
            if any(self._parse_ranges_spec(spec, fid) for spec in (lokace or {}).values()):
                badges.append("✅")
        except Exception:
            pass
    
        # ⚙️ – má nastavený stav
        try:
            if any(self._parse_ranges_spec(spec, fid) for spec in (stavy or {}).values()):
                badges.append("⚙️")
        except Exception:
            pass
    
        # 📝 – má poznámku
        try:
            if str(fid) in (poznamky or {}):
                badges.append("📝")
        except Exception:
            pass
    
        # 🔒 – ANONYMIZOVANÉ (původně 🕶️)
        try:
            anon_spec = (anonym or {}).get("ANONYMIZOVANE", [])
            if self._parse_ranges_spec(anon_spec, fid):
                badges.append("🔒")  # << změněná ikonka
        except Exception:
            pass
    
        return " ".join(badges)
        
        
    # Soubor: web_photos_window.py
    # Třída: WebPhotosWindow
    # ZMĚNA 2: přidej kontrolu „plně vyplněného validního názvu“.
    # Umísti někam do třídy (např. k ostatním helperům s regexy):
    
    def _is_full_valid_name(self, fname: str) -> bool:
        """
        True, pokud je název souboru:
          - ve shodě s NAME_PATTERN (ČísloNálezu + 5číslic + IDLokace + STAV + ANO|NE + Poznámka + přípona),
          - obsahuje přesně 5 znaků '+' (všechny části vyplněny),
          - všechny volitelné části (STAV, ANO/NE, Poznámka) jsou opravdu přítomné a NE prázdné.
        """
        m = NAME_PATTERN.match(fname)
        if not m:
            return False
    
        # Musí být přesně 5 plusů v názvu (6 částí oddělených '+'):
        if fname.count('+') != 5:
            return False
    
        # Povinné části
        if not m.group('id') or not m.group('clok') or not m.group('idlok'):
            return False
    
        # Volitelné části – zde požadujeme, aby byly VYPLNĚNÉ:
        state = m.group('state')
        anon  = m.group('anon')
        note  = m.group('note')
    
        if state is None or len(state.strip()) == 0:
            return False
        if anon is None or anon.strip() not in ('ANO', 'NE'):
            return False
        if note is None or len(note.strip()) == 0:
            return False
    
        return True     
        
    def _build_cislolok_to_idlokace_map(self) -> dict[str, str]:
        """
        Mapuje ČísloLokace (nepadded, např. '1') -> IDLokace (první token názvu mapy před '+'),
        podle souborů ve složce LOCATION_MAPS_DIR.
    
        Vychází z _get_available_location_maps_from_dir(), kde:
          - "cislolok5" je 5místné číslo lokace (např. '00001')
          - "location_id" je IDLokace (první část názvu mapy před prvním '+')
        """
        maps = self._get_available_location_maps_from_dir()
        out: dict[str, str] = {}
        for md in maps:
            c5 = md.get("cislolok5")
            loc_id = md.get("location_id")
            if not c5 or not loc_id:
                continue
            try:
                # nepadded klíč do JSON = "1", "12", ...
                key = str(int(c5))
                out[key] = str(loc_id)
            except Exception:
                continue
        return out
    
    
    def _json_lookup_for_id(self, photo_id: int) -> dict:
        """
        Vrátí metadata pro dané ČísloNálezu z JSON editorů a map:
          {
            "cislolok_key":  '1' nebo None,          # klíč v JSON 'lokace' (nepadded)
            "cislolok5":     '00001' nebo None,      # 5místná varianta
            "idlokace":      'BRNO_STRED' nebo None, # IDLokace z map podle ČísloLokace
            "state":         'BEZFOTKY' / ... / None,
            "note":          'text' nebo None,
            "anon":          True/False/None         # True = anonymizovat, False = jistě ne, None = nevíme
          }
        """
        lokace, stavy, poznamky, anonym = self._get_current_settings_dicts()
    
        # Lokace: najdi klíč cislolok, kde ranges obsahují photo_id
        cislolok_key = None
        for k, spec in (lokace or {}).items():
            if self._parse_ranges_spec(spec, photo_id):
                cislolok_key = str(int(str(k).strip()))
                break
        cislolok5 = None
        if cislolok_key is not None:
            try:
                cislolok5 = f"{int(cislolok_key):05d}"
            except Exception:
                cislolok5 = None
    
        # IDLokace z mapy podle ČísloLokace
        idlok_map = self._build_cislolok_to_idlokace_map()
        idlokace = idlok_map.get(cislolok_key) if cislolok_key is not None else None
    
        # STAV: první stav, do jehož rozsahu číslo spadá
        state = None
        for sname, spec in (stavy or {}).items():
            if self._parse_ranges_spec(spec, photo_id):
                state = sname
                break
    
        # Poznámka: přímo klíč = "photo_id" jako string
        note = None
        try:
            note = (poznamky or {}).get(str(photo_id))
            if isinstance(note, str):
                note = note.strip() or None
            else:
                note = None
        except Exception:
            note = None
    
        # Anonym: v JSON je jen seznam ANONYMIZOVANE
        anon = None
        try:
            spec = (anonym or {}).get("ANONYMIZOVANE", [])
            anon = True if self._parse_ranges_spec(spec, photo_id) else False
        except Exception:
            anon = None
    
        return {
            "cislolok_key": cislolok_key,
            "cislolok5": cislolok5,
            "idlokace": idlokace,
            "state": state,
            "note": note,
            "anon": anon,
        }
    
    
    def _compose_target_name(self, photo_id: int, ext: str, meta: dict) -> str | None:
        """
        Sestaví cílový název podle pravidel:
          id + '+' + ČísloLokace(5) + '+' + IDLokace + [ +STAV [ +ANO/NE [ +Poznámka ] ] ]  + přípona
    
        Pozn.: Pokud chybí kritická data (ČísloLokace 5 a IDLokace), vrací None (soubor přeskočíme).
        Tokeny navíc:
          - ANO/NE: přidáme jen pokud víme; pokud víme 'True' a chybí STAV, vložíme prázdný STAV (regex to snese) => '++ANO'
          - Poznámku přidáme jen pokud existuje; bez ANO/NE ji dle regexu nepůjde vložit → pokud je STAV a není info o ANO/NE,
            vložíme 'NE', aby šlo přidat i poznámku v pořadí (STAV → ANO/NE → Poznámka).
        """
        # povinné části
        if meta.get("cislolok5") is None or meta.get("idlokace") is None:
            return None
    
        id_str = str(int(photo_id))  # bez počátečních nul
        parts = [id_str, meta["cislolok5"], meta["idlokace"]]
    
        state = meta.get("state")
        anon = meta.get("anon")
        note = meta.get("note")
    
        # volitelné sekce v přesném pořadí
        if state is not None or anon is True or (note is not None):
            # STAV – může být i prázdný (když chceme přidat ANO/NE či poznámku a stav neznáme)
            parts.append("" if state is None else state)
    
            # ANO/NE
            if anon is True:
                parts.append("ANO")
            elif anon is False:
                parts.append("NE")
            elif note is not None:
                # chceme přidat poznámku, ale info o anonymizaci není → vložíme 'NE', aby pořadí sedělo
                parts.append("NE")
    
            # Poznámka – jen pokud opravdu existuje
            if note is not None:
                parts.append(note)
    
        base = "+".join(parts)
        return f"{base}{ext}"
    
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import QTableView, QAbstractItemView
    
    def _get_details_table_widget(self) -> QTableView | None:
        """
        Najde QTableView v záložce 'Přejmenování/Úpravy', kde se objevuje varování
        'Cell requested for row X is out of bounds…'. Hledá běžné názvy.
        Nezasahuje do ostatního kódu, jen vrátí widget pokud existuje.
        """
        candidates = [
            "details_table", "table_details", "tableViewDetails", "tvDetails",
            "tableView", "rename_table", "tvRenameDetails"
        ]
        for name in candidates:
            w = getattr(self, name, None)
            if isinstance(w, QTableView):
                return w
        ui = getattr(self, "ui", None)
        if ui:
            for name in candidates:
                w = getattr(ui, name, None)
                if isinstance(w, QTableView):
                    return w
        return None
    
    def _normalize_details_table_selection(self):
        """
        OPRAVA QT ACCESSIBILITY WARNING:
        Bezpečně upraví výběr po přebudování modelu, aby se
        Qt Accessibility nepokoušelo číst neexistující řádky (row 2 u 0 řádků).
        Neprovádí žádné jiné změny chování.
        """
        tv = self._get_details_table_widget()
        if tv is None:
            return
        model = tv.model()
        if model is None:
            return
    
        rows = model.rowCount()
        if rows <= 0:
            # žádné řádky → zrušit výběr i current index
            try:
                tv.clearSelection()
            except Exception:
                pass
            try:
                tv.setCurrentIndex(QModelIndex())
            except Exception:
                pass
            return
    
        # pokud je vybraný/current mimo rozsah, zůstaň konzervativní (první řádek)
        current = tv.currentIndex()
        if not current.isValid() or current.row() >= rows:
            safe_idx = model.index(0, 0)
            try:
                tv.setCurrentIndex(safe_idx)
                tv.scrollTo(safe_idx, QAbstractItemView.PositionAtCenter)
            except Exception:
                pass
    
    def _action_intelligent_rename(self):
        """
        Kontextová akce v záložce 'Přejmenování'.
    
        Pravidla:
          - Přejmenování je povoleno pro soubory se jménem s přesně 5 plusy (6 slotů) a příponou .HEIC,
            přičemž 1. slot musí být číslo nálezu (číslice).
          - Slot 0 (ČísloNálezu) se vždy zachová ze zdroje.
          - Slot 4 (Anonymizace): ANO pokud JSON/meta['anon'] == True, jinak NE (default).
          - Sloty 1,2,5: primárně z _compose_target_name(...); když nic nedodá, zůstanou prázdné (parametr se tím odstraní).
          - Slot 3 (STAV): compose -> meta (bere i 'state') -> heuristické dohledání ve „Stavy“ JSON.
          - Vždy přesně 5 plusů (6 slotů), přípona .HEIC.
        """
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        import re
    
        def _norm_slots(parts: list[str]) -> list[str]:
            """Zajistí přesně 6 slotů (5 plusů)."""
            if len(parts) < 6:
                parts = parts + [""] * (6 - len(parts))
            elif len(parts) > 6:
                parts = parts[:6]
            return parts
    
        def _int_in_range_spec(x: int, spec: str) -> bool:
            """True, pokud číslo x patří do specifikace ID: '7', '13602-13603', '14310-14313' apod."""
            s = (spec or "").strip()
            if not s:
                return False
            if "-" in s:
                a, b = s.split("-", 1)
                try:
                    return int(a) <= x <= int(b)
                except Exception:
                    return False
            try:
                return int(s) == x
            except Exception:
                return False
    
        def _guess_status_from_any_json(photo_id: int) -> str:
            """
            Heuristicky najde název STAVu podle JSONů přítomných v instanci:
            - Hledá dict, kde hodnoty jsou list[str] se specifikacemi ID nebo rozsahů.
            - Vrací název klíče (např. 'BEZGPS'), u kterého photo_id spadá do některé položky.
            """
            candidate_attrs = [
                "_json_status", "_json_statuses", "_statuses_json", "_json_stavy", "_stavy_json",
                "json_status", "json_statuses", "stavy", "Stavy"
            ]
            for attr in candidate_attrs:
                v = getattr(self, attr, None)
                if isinstance(v, dict):
                    for label, arr in v.items():
                        if not isinstance(arr, (list, tuple)):
                            continue
                        match_found = False
                        for spec in arr:
                            try:
                                if isinstance(spec, (list, tuple)):
                                    continue
                                if _int_in_range_spec(photo_id, str(spec)):
                                    match_found = True
                                    break
                            except Exception:
                                continue
                        if match_found:
                            return str(label).strip()
            # fallback – projdi všechny dict atributy
            for v in self.__dict__.values():
                if isinstance(v, dict):
                    ok = True
                    for vv in v.values():
                        if not isinstance(vv, (list, tuple)):
                            ok = False
                            break
                    if not ok:
                        continue
                    for label, arr in v.items():
                        if not isinstance(arr, (list, tuple)):
                            continue
                        for spec in arr:
                            try:
                                if isinstance(spec, (list, tuple)):
                                    continue
                                if _int_in_range_spec(photo_id, str(spec)):
                                    return str(label).strip()
                            except Exception:
                                continue
            return ""
    
        # vybrané položky
        items = self._gather_selected_items()
        if not items:
            QMessageBox.information(self, "Inteligentní přejmenování", "Není vybrán žádný soubor/složka.")
            return
    
        renamed = 0
        skipped = 0
        errors  = 0
        path_map: dict[str, str] = {}
    
        # pro kontrolu formátu zdrojového názvu (přesně 5 plusů)
        pat = re.compile(r"^\d+\+.*\+.*\+.*\+.*\+.*$", re.IGNORECASE)
    
        # příprava – rozbalíme složky a vyfiltrujeme povolené soubory
        self._sticky_scans_remaining = 3
    
        # nasbírej soubory
        file_list: list[Path] = []
        for p, is_dir in items:
            if not p.exists():
                continue
            if is_dir:
                for fp in p.rglob("*"):
                    if fp.is_file() and fp.suffix.lower() in ALLOWED_EXTS:
                        file_list.append(fp)
            else:
                if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
                    file_list.append(p)
    
        if not file_list:
            QMessageBox.information(self, "Inteligentní přejmenování", "Nenalezeny žádné soubory k přejmenování.")
            return
    
        for fp in file_list:
            if fp.suffix.upper() != ".HEIC":
                skipped += 1
                continue
    
            name = fp.stem
            if not pat.fullmatch(name):
                skipped += 1
                continue
    
            stem = fp.stem
            src_parts = _norm_slots(stem.split("+"))
            id_str = src_parts[0].strip()
            if not id_str.isdigit():
                skipped += 1
                continue
    
            try:
                photo_id = int(id_str)
            except Exception:
                skipped += 1
                continue
    
            meta = self._json_lookup_for_id(photo_id) or {}
    
            # Návrh jako doposud (může dodat 1,2,3,5; nemusí)
            ext = ".HEIC"
            composed = ""
            try:
                composed = self._compose_target_name(photo_id, ext, meta)
            except TypeError:
                try:
                    composed = self._compose_target_name(fp)
                except Exception:
                    composed = ""
    
            if composed:
                comp_stem = Path(composed).stem
                comp_parts = _norm_slots(comp_stem.split("+"))
            else:
                comp_parts = [""] * 6
    
            # výstupní sloty
            out_parts = _norm_slots([""] * 6)
    
            # 0) ČísloNálezu – vždy ze zdroje
            out_parts[0] = id_str
    
            # 1) čísloLokace – primárně z compose, jinak prázdné (zachováno původní chování)
            out_parts[1] = (comp_parts[1] or "").strip()
    
            # 2) IDLokace – primárně z compose, jinak prázdné (zachováno původní chování)
            out_parts[2] = (comp_parts[2] or "").strip()
    
            # 3) STAV – compose -> meta (bere i 'state') -> heuristika
            stav = (comp_parts[3] or "").strip()
            if not stav:
                for k in ("state", "stav", "status", "STAV", "STATUS", "stav_label", "status_label"):
                    v = meta.get(k)
                    if isinstance(v, str) and v.strip():
                        stav = v.strip()
                        break
            if not stav:
                stav = _guess_status_from_any_json(photo_id)
            out_parts[3] = stav
            # DEFAULT doplnění STAV, pokud nezjištěn
            if not out_parts[3]:
                out_parts[3] = "NORMÁLNÍ"
    
            # 4) Anonymizace – ANO pokud JSON říká anonymizovat, jinak NE
            anon_val = meta.get("anon")
            out_parts[4] = "ANO" if (anon_val is True) else "NE"
    
            # 5) Poznámka – primárně z compose, jinak prázdné
            out_parts[5] = (comp_parts[5] or "").strip()
            # DEFAULT doplnění Poznámky, pokud nezadána v JSONech
            if not out_parts[5]:
                out_parts[5] = "BezPoznámky"
    
            target_name = "+".join(_norm_slots(out_parts)) + ".HEIC"
            target_path = fp.with_name(target_name)
    
            # kolize – vytvoř suffix _001.._999
            if target_path.exists():
                base = target_path.stem
                suf_ext = target_path.suffix
                i = 1
                found = None
                while i <= 999:
                    cand = fp.with_name(f"{base}_{i}{suf_ext}")
                    if not cand.exists():
                        found = cand
                        break
                    i += 1
                if found is None:
                    errors += 1
                    continue
                target_path = found
    
            try:
                fp.rename(target_path)
                renamed += 1
                path_map[str(fp)] = str(target_path)
            except Exception:
                errors += 1
    
        # refresh a zachování výběru
        self.run_scan()
        try:
            self._rebuild_rename_tree(preserve_state=True, path_map=path_map)
        except TypeError:
            self._rebuild_rename_tree(preserve_state=True)
    
        # >>> JSON: refresh pravého stromu (zachovat rozbalení/scroll/fokus)
        try:
            self._schedule_json_tree_rebuild()
        except Exception:
            pass
    
        # (volitelně) bezpečná normalizace výběru v tabulce detailů
        try:
            self._normalize_details_table_selection()
        except Exception:
            pass
    
        QMessageBox.information(
            self, "Inteligentní přejmenování",
            f"Přejmenováno: {renamed}\nPřeskočeno: {skipped}\nChyb: {errors}"
        )
    
    def closeEvent(self, event):
        try:
            # Ulož „warm start“ cache indikátorů (rychlé otevření příště)
            try:
                cache = self._snapshot_status_for_cache()
                self._save_cached_status(cache)
            except Exception:
                pass
    
            # Vyčištění file watcheru
            if hasattr(self, '_rename_file_watcher'):
                self._rename_file_watcher.deleteLater()
    
            # Autosave JSON editorů (tichý)
            self._autosave_json_settings()
    
            # Ulož stav pravého stromu (JSON tab)
            self._save_json_tree_state()
    
            # Ulož kompletní stav stromu „Přejmenování“
            if hasattr(self, "ren_model") and hasattr(self, "ren_tree"):
                self._save_rename_ui_state()
        finally:
            super().closeEvent(event)

# --- Samostatný test ---
if __name__ == "__main__":
    # DŮLEŽITÉ: na macOS Qt defaultně NEzobrazuje ikony v menu.
    # Toto MUSÍ být před vytvořením QApplication.
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        QApplication.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    except Exception:
        pass

    import sys
    app = QApplication(sys.argv)
    dlg = WebPhotosWindow()
    dlg.show()
    sys.exit(app.exec())
