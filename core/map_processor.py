# -*- coding: utf-8 -*-

from PySide6.QtCore import QObject, Signal
import math
import requests
from PIL import Image, ImageDraw
from PIL.ExifTags import TAGS, GPSTAGS
from io import BytesIO
import os
from pathlib import Path
import time
import hashlib
from sys import exit
import numpy as np
from PIL.PngImagePlugin import PngInfo
import re

class MapProcessor(QObject):
    """Hlavní třída pro zpracování map - obsahuje váš původní kód"""
    
    # Signály pro komunikaci s GUI
    finished = Signal(str)  # Cesta k výslednému souboru
    error = Signal(str)     # Chybová zpráva
    progress = Signal(int)  # Progress 0-100
    log = Signal(str, str)  # Zpráva, typ
    status = Signal(str, str)  # Status typ, zpráva
    
    def __init__(self, parameters):
        super().__init__()
        self.params = parameters
        self.should_stop = False
        
        # Nastavení konstant z vašeho kódu
        self.CACHE_DIR = Path.home() / ".cache" / "osm_tiles"
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.REQUEST_DELAY = parameters.get('request_delay', 1.0)
        self.TILE_SIZE = 256
        
    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """
        Vypočítá vzdálenost mezi dvěma GPS souřadnicemi v metrech pomocí Haversinova vzorce.
        """
        R = 6371000  # Poloměr Země v metrech
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        distance = R * c
        return distance

    def gps_to_pixel(self, target_lat, target_lon, center_lat, center_lon, zoom, map_width_px, map_height_px):
        """
        Převede GPS souřadnice na pixelové souřadnice na finální vycentrované mapě.
        """
        # Pomocná funkce pro převod stupňů na čísla dlaždic (včetně desetinné části)
        def deg2num(lat_deg, lon_deg, zoom):
            lat_rad = math.radians(lat_deg)
            n = 2.0 ** zoom
            xtile = (lon_deg + 180.0) / 360.0 * n
            ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
            return (xtile, ytile)

        center_tile_x, center_tile_y = deg2num(center_lat, center_lon, zoom)
        target_tile_x, target_tile_y = deg2num(target_lat, target_lon, zoom)

        # Rozdíl v pixelech od středové dlaždice
        pixel_dx = (target_tile_x - center_tile_x) * self.TILE_SIZE
        pixel_dy = (target_tile_y - center_tile_y) * self.TILE_SIZE

        # Finální pixelové souřadnice relativně k centru mapy
        pixel_x = (map_width_px / 2) + pixel_dx
        pixel_y = (map_height_px / 2) + pixel_dy

        return pixel_x, pixel_y

    def is_point_in_polygon(self, x, y, polygon_points):
        """
        Zjistí, zda je bod uvnitř daného polygonu pomocí Ray Casting algoritmu.
        `polygon_points` je seznam (x, y) n-tic.
        """
        n = len(polygon_points)
        if n < 3:
            return False
        inside = False
        p1x, p1y = polygon_points[0]
        for i in range(n + 1):
            p2x, p2y = polygon_points[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside

        
    def read_polygon_metadata_from_png(self, image_path):
        """
        Vrátí dict {'points': [[x,y],...], 'alpha': 0.15, 'color': '#FF0000'} načtený z PNG tEXt klíče 'AOI_POLYGON',
        nebo None, pokud klíč neexistuje nebo je neplatný. 
        """
        try:
            import json
            from PIL import Image
            p = Path(image_path)
            if not p.exists() or p.suffix.lower() != ".png":
                return None
            with Image.open(p) as im:
                text_meta = getattr(im, 'text', {}) or {}
                raw = text_meta.get('AOI_POLYGON')
                if not raw:
                    info = getattr(im, 'info', {}) or {}
                    raw = info.get('AOI_POLYGON')
                if not raw:
                    return None
                data = json.loads(raw)
                pts = data.get('points') or []
                if not isinstance(pts, list) or len(pts) < 3:
                    return None
                alpha = float(data.get('alpha', 0.15))
                color = str(data.get('color', '#FF0000'))
                return {'points': pts, 'alpha': alpha, 'color': color}
        except Exception:
            return None

    def draw_polygon_overlay(self, base_image, poly):
        """
        Vykreslí polygon na base_image (RGBA) podle metadat poly a vrátí image s přidaným overlayem.
        Očekává tvar poly: {'points': [[x,y],...], 'alpha': 0.15, 'color': '#FF0000'}.
        """
        from PIL import Image, ImageDraw
    
        # Zajistit RGBA
        img = base_image.convert('RGBA') if base_image.mode != 'RGBA' else base_image
        W, H = img.size
        overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
    
        # 1) Body → seznam dvojic floatů (x, y), min. 3 body
        raw_pts = poly.get('points') or []
        pts = []
        for p in raw_pts:
            try:
                x, y = p  # očekává se 2-prvková sekvence
                x = float(x)
                y = float(y)
                # volitelné ořezání do plochy (zabraňuje chybám mimo obraz)
                x = max(0.0, min(x, float(W - 1)))
                y = max(0.0, min(y, float(H - 1)))
                pts.append((x, y))
            except Exception:
                continue
    
        if len(pts) < 3:
            return img  # nic nekreslit, pokud polygon není platný
    
        # 2) Alfa 0..1
        try:
            alpha = float(poly.get('alpha', 0.15))
        except Exception:
            alpha = 0.15
        alpha = max(0.0, min(1.0, alpha))
    
        # 3) Barva z hex kódu (#RRGGBB nebo RRGGBB)
        color_hex = str(poly.get('color', '#FF0000')).strip().lstrip('#')
        try:
            if len(color_hex) == 6:
                r = int(color_hex[0:2], 16)
                g = int(color_hex[2:4], 16)
                b = int(color_hex[4:6], 16)
            elif len(color_hex) == 3:
                r = int(color_hex * 2, 16)
                g = int(color_hex[2] * 2, 16)
                b = int(color_hex[1] * 2, 16)
            else:
                r, g, b = 255, 0, 0
        except Exception:
            r, g, b = 255, 0, 0
    
        fill_rgba = (r, g, b, int(round(255 * alpha)))
        stroke_rgba = (r, g, b, 255)
    
        # 4) Výplň polygonu
        draw.polygon(pts, fill=fill_rgba)
    
        # 5) Obrys – UZAVŘÍT polyline přidáním PRVNÍHO bodu (NE celý seznam!)
        #    ŠPATNĚ: pts + [pts]  → vytváří vnořený seznam a končí chybou typu
        #    SPRÁVNĚ: pts + [pts]
        draw.line(pts + [pts[0]], fill=stroke_rgba, width=2)
    
        # 6) Sloučení
        merged = Image.alpha_composite(img, overlay)
        return merged

    def get_selected_watermark_font(self, px: int, layout=None):
        """
        Vybraný font pro finální vodoznak podle volby #1 z náhledu.
        Preferuje tučné systémové/bundlované varianty s plnou diakritikou (bez NotoSans).
        px = velikost v pixelech (ne body); layout = ImageFont.Layout.BASIC/RAQM.
        """
        from PIL import ImageFont
        from pathlib import Path
    
        base = Path(__file__).resolve().parent
        # 1) Bundlované TTF (pokud je přibalené)
        bundled = [
            base / "assets" / "fonts" / "Arial.ttf",                     # 1) ekvivalent náhledu #1
            base / "assets" / "fonts" / "SegoeUI-Bold.ttf",              # 2)
            base / "assets" / "fonts" / "Ubuntu-Bold.ttf",               # 3)
            base / "assets" / "fonts" / "PTSans-Bold.ttf",               # 4)
            base / "assets" / "fonts" / "LiberationSans-Bold.ttf",       # 5)
            base / "assets" / "fonts" / "Roboto-Bold.ttf",               # 6)
            base / "assets" / "fonts" / "Inter-SemiBold.ttf",            # 7)
            base / "assets" / "fonts" / "SourceSans3-SemiBold.ttf",      # 8)
            base / "assets" / "fonts" / "DejaVuSansCondensed-Bold.ttf",  # 9)
            base / "assets" / "fonts" / "DejaVuSans-Bold.ttf",           # 10)
        ]
        for p in bundled:
            try:
                if p.exists():
                    return ImageFont.truetype(str(p), px, layout_engine=layout or ImageFont.Layout.BASIC)  # px, ne pt [4][2]
            except Exception:
                continue
    
        # 2) Známé systémové cesty
        sys_paths = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
            "/usr/share/fonts/truetype/ptfonts/PTSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf",
            "/usr/share/fonts/truetype/inter/Inter-SemiBold.ttf",
            "/usr/share/fonts/truetype/source-sans-3/SourceSans3-SemiBold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Segoe UI Bold.ttf",
            "/Library/Fonts/Ubuntu-B.ttf",
            "/Library/Fonts/Roboto Bold.ttf",
        ]
        for f in sys_paths:
            try:
                p = Path(f)
                if p.exists():
                    return ImageFont.truetype(str(p), px, layout_engine=layout or ImageFont.Layout.BASIC)  # px [4][2]
            except Exception:
                continue
    
        # 3) Podle rodinného názvu
        for fam in ("Arial", "Segoe UI", "Ubuntu", "PT Sans", "Liberation Sans", "Roboto", "Inter", "Source Sans 3", "DejaVu Sans Condensed", "DejaVu Sans"):
            try:
                return ImageFont.truetype(fam, px, layout_engine=layout or ImageFont.Layout.BASIC)  # px [4][2]
            except Exception:
                pass
    
        from PIL import ImageFont as _IF
        return _IF.load_default()

    def add_watermark_text_NOVY(self, image, text, size_mm=3.0, dpi=300):
        """
        Vodoznak (upraveno):
        - Černý okraj textu zmenšen na polovinu.
        - Text posunut o 40 % blíže dolnímu okraji.
        - Font zmenšen o 2 px (po přepočtu z mm na px).
        - Stále používá RAQM (pokud je k dispozici), supersampling a LANCZOS.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont, features
            import unicodedata
    
            safe_text = unicodedata.normalize('NFC', text or "")
            if not safe_text.strip():
                self.log.emit("⚠️ Text vodoznaku je prázdný", "warning")
                return image
    
            # Supersampling 1..4 (výchozí 2)
            ss = int(self.params.get('watermark_supersample', 2)) if hasattr(self, 'params') else 2
            ss = max(1, min(4, ss))
    
            # mm -> px a zmenšení fontu o 2 px
            target_px_base = max(1, int(round(float(size_mm or 0.0) * dpi / 25.4)))
            target_px = max(1, target_px_base - 2)
            scaled_px = max(1, target_px * ss)
    
            # Okraj a zvednutí
            margin_mm = 1.0
            raise_mm = 0.3
            margin_px = int(round(margin_mm * dpi / 25.4))
            raise_px = int(round(raise_mm * dpi / 25.4))
    
            W, H = image.size
            W2, H2 = W * ss, H * ss
    
            # RAQM pokud je k dispozici
            layout = ImageFont.Layout.BASIC
            try:
                if features.check("raqm"):
                    layout = ImageFont.Layout.RAQM
            except Exception:
                pass
    
            # Volba fontu
            try:
                font = ImageFont.truetype("LiberationSerif-Bold.ttf", scaled_px, layout_engine=layout)
            except Exception:
                try:
                    font = self.get_selected_watermark_font(scaled_px, layout=layout)
                except Exception:
                    font = ImageFont.load_default()
    
            # Vrstva pro text (supersamplovaná)
            overlay = Image.new('RGBA', (W2, H2), (0, 0, 0, 0))
            d = ImageDraw.Draw(overlay)
    
            # Korekce metrik
            try:
                bb = d.textbbox((0, 0), safe_text, font=font, anchor='la')
                measured = max(1, bb - bb[1])
                expected = scaled_px
                if abs(measured - expected) > 1:
                    adj_px = max(1, int(round(scaled_px * (expected / measured))))
                    try:
                        font = ImageFont.truetype("LiberationSerif-Bold.ttf", adj_px, layout_engine=layout)
                    except Exception:
                        try:
                            font = self.get_selected_watermark_font(adj_px, layout=layout)
                        except Exception:
                            pass
            except Exception:
                pass
    
            # 40 % blíže ke spodní hraně (offset * 0.6)
            total_offset_px = margin_px + raise_px
            new_offset_px = max(0, int(round(total_offset_px * 0.6)))
            new_offset_scaled = new_offset_px * ss
    
            x = W2 - (margin_px * ss)
            y = H2 - new_offset_scaled
    
            # Poloviční stroke (původně ~0.14, nyní ~0.07)
            stroke_w = max(1, int(round(scaled_px * 0.07)))
    
            d.text(
                (x, y),
                safe_text,
                fill=(255, 255, 255, 255),
                font=font,
                stroke_width=stroke_w,
                stroke_fill=(0, 0, 0, 255),
                anchor='rb',
            )
    
            # Downsampling a kompozice
            overlay_small = overlay.resize((W, H), Image.Resampling.LANCZOS) if ss > 1 else overlay
            base_rgba = image.convert('RGBA') if image.mode != 'RGBA' else image
            out = Image.alpha_composite(base_rgba, overlay_small)
            if image.mode != 'RGBA':
                try:
                    out = out.convert(image.mode)
                except Exception:
                    out = out.convert('RGB')
            return out
    
        except Exception as e:
            try:
                self.log.emit(f"❌ Chyba ve vodoznaku (UPR): {e}", "error")
            except Exception:
                pass
            return image

    def stop(self):
        """Zastavení zpracování"""
        self.should_stop = True
        
    def run(self):
        """Hlavní funkce pro spuštění zpracování – s logikou pro anonymizaci a přepočet AOI plochy."""
        try:
            from pathlib import Path
            from PIL import Image
            from PIL.PngImagePlugin import PngInfo
            import json

            self.log.emit("🚀 Spouštím generování mapy...", "info")
            self.status.emit("processing", "Inicializace...")

            # Číselné ID
            cislo_id = self.generate_cislo_id()
            self.log.emit(f"🔢 Použité ID: {cislo_id}", "info")

            # GPS souřadnice (střed mapy)
            self.progress.emit(10)
            self.status.emit("processing", "Získávám GPS souřadnice...")
            if self.params.get('coordinate_mode') == 'F':
                coords = self.get_gps_from_photo(self.params.get('photo_filename'))
                if not coords:
                    raise Exception("Nepodařilo se získat GPS souřadnice ze souboru")
                lat, lon = coords
                self.log.emit(f"📍 GPS ze souboru (střed mapy): {lat:.6f}°, {lon:.6f}°", "success")
            else:
                coords = self.parse_manual_coordinates(self.params.get('manual_coordinates', ''))
                if not coords:
                    raise Exception("Nepodařilo se parsovat ruční GPS souřadnice")
                lat, lon = coords

            # Rozměry
            self.progress.emit(20)
            self.status.emit("processing", "Počítám rozměry...")
            width_cm = float(self.params.get('output_width_cm'))
            height_cm = float(self.params.get('output_height_cm'))
            dpi = int(self.params.get('output_dpi'))
            width_px = max(1, int(round(width_cm / 2.54 * dpi)))
            height_px = max(1, int(round(height_cm / 2.54 * dpi)))
            self.log.emit(f"📏 Rozměry výstupu: {width_px}×{height_px} px ({width_cm}×{height_cm} cm @ {dpi} DPI)", "info")

            # Stahování map
            self.progress.emit(30)
            self.status.emit("processing", "Stahuji mapové dlaždice...")
            zoom = int(self.params.get('zoom'))
            map_image = self.download_map_tiles(lat, lon, zoom, width_px, height_px)
            if map_image is None:
                raise Exception("Nepodařilo se stáhnout mapové dlaždice")

            # Přesná velikost (pojištění)
            if map_image.size != (width_px, height_px):
                map_image = map_image.resize((width_px, height_px), Image.Resampling.LANCZOS)
                self.log.emit(f"✓ Mapa změněna na velikost: {map_image.size}", "info")

            # Podklad
            self.progress.emit(60)
            photo_path = (self.params.get('photo_filename') or "").strip()
            if photo_path and Path(photo_path).exists():
                input_image = Image.open(photo_path)
            else:
                input_image = Image.new('RGB', (width_px, height_px), color='white')

            # Transparentnost a kombinování
            self.progress.emit(70)
            map_opacity = max(0.0, min(1.0, float(self.params.get('map_opacity', 1.0))))
            if map_opacity < 1.0:
                if map_image.mode != 'RGBA': map_image = map_image.convert('RGBA')
                alpha_layer = Image.new('L', map_image.size, int(round(255 * map_opacity)))
                map_image.putalpha(alpha_layer)
            combined_image = self.combine_images(input_image, map_image)

            # --- KRESLENÍ / OVERLAYE ---
            self.progress.emit(80)

            # 1) Polygon z metadat (pokud existuje)
            poly_meta = self.read_polygon_metadata_from_png(photo_path) if photo_path else None
            if poly_meta:
                self.log.emit(f"🔺 Kreslím polygon z metadat (AOI_POLYGON), {len(poly_meta.get('points', []))} bodů", "info")
                combined_image = self.draw_polygon_overlay(combined_image, poly_meta)

            # 2) GPS marker/text
            self.status.emit("processing", "Přidávám GPS značku a text...")
            combined_image = self.draw_central_marker(combined_image)

            # 3) Vodoznak
            self.progress.emit(85)
            self.status.emit("processing", "Přidávám vodoznak...")
            watermark_size = float(self.params.get('watermark_size_mm', 3.0))
            watermark_text = (self.params.get('id_lokace') or '').strip() or str(cislo_id)
            combined_image = self.add_watermark_text_NOVY(combined_image, watermark_text, watermark_size, dpi)

            # --- METADATA PNG ---
            self.progress.emit(90)
            self.status.emit("processing", "Přidávám metadata...")
            metadata = PngInfo()
            metadata.add_text("GPS_Latitude", f"{lat}")
            metadata.add_text("GPS_Longitude", f"{lon}")
            metadata.add_text("GPS_Source", self.params.get('coordinate_mode', 'G'))
            metadata.add_text("Zoom_Level", f"{zoom}")
            metadata.add_text("ID_Lokace", self.params.get('id_lokace', ''))
            metadata.add_text("Popis", self.params.get('popis', ''))
            metadata.add_text("Cislo_ID", f"{cislo_id}")
            metadata.add_text("Generator", f"{self.params.get('app_name','')} - {self.params.get('contact_email','')}")
            try:
                ms_val = max(2, int(self.params.get('marker_size', 10)))
                ms_style = str(self.params.get('marker_style', 'dot')).lower()
                metadata.add_text("Marker_Size_Px", f"{ms_val}")
                metadata.add_text("Marker_Style", ms_style)
            except Exception:
                pass

            # Anonymizace (z GUI/params)
            try:
                if bool(self.params.get('anonymizovana_lokace')):
                    metadata.add_text("Anonymizovaná lokace", "Ano")
                    metadata.add_text("Anonymizovana lokace", "Ano")  # ASCII fallback
            except Exception:
                pass

            # Polygon metadata
            if poly_meta:
                try:
                    metadata.add_text("AOI_POLYGON", json.dumps(poly_meta))
                except Exception:
                    pass

            # AOI_AREA_M2 – přepočet přes m/px (Web Mercator) pokud polygon existuje
            try:
                if poly_meta and isinstance(poly_meta.get('points'), (list, tuple)):
                    W, H = combined_image.size
                    pts = []
                    for p in (poly_meta.get('points') or []):
                        try:
                            x, y = float(p[0]), float(p[1])
                            x = max(0.0, min(x, float(W - 1)))
                            y = max(0.0, min(y, float(H - 1)))
                            pts.append((x, y))
                        except Exception:
                            continue
                    if len(pts) >= 3:
                        area_px2 = 0.0
                        for i in range(len(pts)):
                            x1, y1 = pts[i]
                            x2, y2 = pts[(i + 1) % len(pts)]
                            area_px2 += (x1 * y2 - x2 * y1)
                        area_px2 = abs(area_px2) * 0.5
                        mpp = self._meters_per_pixel(lat, zoom)
                        area_m2 = area_px2 * (mpp * mpp)
                        try:
                            metadata.add_text("AOI_AREA_M2", f"{area_m2:.2f}")
                        except Exception:
                            pass
            except Exception:
                pass

            self._maybe_draw_scale(combined_image)

            # Výstupní název a uložení
            output_filename = self.generate_output_filename_with_gps_and_zoom(
                self.params.get('id_lokace', ''),
                self.params.get('popis', ''),
                lat, lon, zoom, cislo_id
            )
            output_dir = Path(self.params.get('output_directory'))
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / output_filename
            self.log.emit(f"💾 Ukládám do: {output_path}", "info")
            combined_image.save(output_path, "PNG", pnginfo=metadata, dpi=(dpi, dpi))

            self.progress.emit(100)
            self.status.emit("success", "Dokončeno!")
            self.log.emit(f"✅ Mapa úspěšně uložena: {output_path}", "success")
            self.finished.emit(str(output_path))

        except Exception as e:
            import traceback
            self.log.emit(f"❌ Kritická chyba: {e}", "error")
            self.log.emit(f"❌ Traceback: {traceback.format_exc()}", "error")
            self.error.emit(str(e))
    
    import math
    from PIL import Image, ImageDraw, ImageFont
    
    def _meters_per_pixel(self, lat_deg: float, zoom: int, tile_size: int = 256, R: float = 6378137.0) -> float:
        """Web Mercator ground resolution in meters per pixel."""
        return (2.0 * math.pi * R * math.cos(math.radians(float(lat_deg)))) / (tile_size * (2 ** int(zoom)))
    
    def _nice_scale_length_m(self, max_meters: float) -> float:
        """Choose a 'nice' length (1,2,5 * 10^n) <= max_meters."""
        if max_meters <= 0:
            return 0.0
        exp = math.floor(math.log10(max_meters))
        for m in (5.0, 2.0, 1.0):
            cand = m * (10 ** exp)
            if cand <= max_meters + 1e-9:
                return cand
        # fallback
        return (10 ** exp)
    
    def _format_length_label(self, meters: float) -> str:
        return f"{meters:.0f} m" if meters < 1000 else f"{meters/1000.0:.1f} km"
    
    def _extract_lat_lon_from_params(self) -> tuple[float | None, float | None]:
        """
        Try to get center (lat, lon) from self.params.
        Supports:
          - params['center_lat']/['center_lon'] if present
          - params['manual_coordinates'] like '49.23091° S, 17.65691° V' or EN 'N/E/W'
        """
        p = self.params or {}
        lat = p.get('center_lat', None)
        lon = p.get('center_lon', None)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
        txt = str(p.get('manual_coordinates', '')).strip()
        if not txt:
            return None, None
        import re
        m = re.search(r'([0-9]+(?:[.,][0-9]+)?)\s*°?\s*([SJNVEWZ])\s*[, ]+\s*([0-9]+(?:[.,][0-9]+)?)\s*°?\s*([SJNVEWZ])', txt, re.IGNORECASE)
        if not m:
            return None, None
        lat_val = float(m.group(1).replace(',', '.'))
        lat_dir = m.group(2).upper()
        lon_val = float(m.group(3).replace(',', '.'))
        lon_dir = m.group(4).upper()
        english = any(d in {'N', 'E', 'W'} for d in {lat_dir, lon_dir})
        if english:
            lat = -lat_val if lat_dir == 'S' else lat_val
            lon = -lon_val if lon_dir == 'W' else lon_val
        else:
            lat = -lat_val if lat_dir == 'J' else lat_val  # CZ: J = South
            lon = -lon_val if lon_dir == 'Z' else lon_val  # CZ: Z = West
        return lat, lon
    
    def _draw_scale_bar(self, img: Image.Image, lat_deg: float, zoom: int, output_dpi: int, margin_px: int = 16) -> None:
        """
        Draw small black/white scale bar with label in the bottom-left corner.
        Modifies 'img' in place.
        """
        if img is None or lat_deg is None or zoom is None:
            return

        W, H = img.size
        if W <= 0 or H <= 0:
            return

        # meters per pixel at given latitude/zoom
        mpp = self._meters_per_pixel(lat_deg, zoom)

        # scale bar size
        max_bar_px = max(40, min(int(W * 0.25), 240)) # up to 25% width, cap ~240 px
        max_meters = mpp * max_bar_px
        nice_m = self._nice_scale_length_m(max_meters)
        if nice_m <= 0:
            return
        
        bar_px = max(1, int(round(nice_m / mpp)))

        # ÚPRAVA: Zdvojnásobení výšky měřítka
        bar_h = max(4, min(8, int(round(output_dpi / 60))))

        margin_bottom = int(margin_px * 0.125)
        margin_left = int(margin_px * 0.5) 

        x0 = margin_left
        y0 = H - margin_bottom - bar_h - 12 
        x1 = x0 + bar_px
        y1 = y0 + bar_h

        draw = ImageDraw.Draw(img)

        # 4 alternating segments (improves contrast on noisy backgrounds)
        segs = 4
        seg_w = max(1, bar_px // segs)
        for i in range(segs):
            sx0 = x0 + i * seg_w
            sx1 = x0 + (i + 1) * seg_w if i < segs - 1 else x1
            fill = (0, 0, 0) if (i % 2 == 0) else (255, 255, 255)
            draw.rectangle([sx0, y0, sx1, y1], fill=fill)

        # thin black outline
        draw.rectangle([x0, y0, x1, y1], outline=(0, 0, 0), width=1)

        # label (black text with white "halo" for legibility, still B/W)
        label = self._format_length_label(nice_m)
        try:
            # default PIL font
            font = ImageFont.load_default()
        except Exception:
            font = None
        
        tw, th = draw.textbbox((0, 0), label, font=font)[2:]
        tx = x0
        ty = max(0, y0 - th - 3)
        
        # white halo
        for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
            draw.text((tx+dx, ty+dy), label, fill=(255,255,255), font=font)
        draw.text((tx, ty), label, fill=(0,0,0), font=font)


    def _maybe_draw_scale(self, img: Image.Image) -> None:
        """Entry point: read params and draw the scale unless explicitly disabled."""
        if not isinstance(self.params, dict):
            return
        if self.params.get('scale_bar') is False:
            return
        zoom = int(self.params.get('zoom', 18))
        dpi = int(self.params.get('output_dpi', 300))
        lat, _ = self._extract_lat_lon_from_params()
        if lat is None:
            return
        self._draw_scale_bar(img, lat_deg=float(lat), zoom=zoom, output_dpi=dpi)

    def download_map_tiles(self, lat, lon, zoom, width_px, height_px):
        """Hlavní funkce pro stažení mapových dlaždic - s debug informacemi"""
        try:
            self.log.emit(f"🗺️ Parametry mapy: GPS({lat:.6f}, {lon:.6f}), zoom {zoom}, {width_px}×{height_px}px", "info")
            
            # Výpočet rozměrů gridu
            grid_width, grid_height = self.calculate_tile_grid(width_px, height_px)
            self.log.emit(f"📐 Grid dlaždic: {grid_width}×{grid_height}", "info")
            
            # Získání středové dlaždice
            center_x, center_y = self.lat_lon_to_tile_int(lat, lon, zoom)
            self.log.emit(f"🎯 Středová dlaždice: ({center_x}, {center_y})", "info")
            
            # Stažení gridu dlaždic
            tiles, start_x, start_y = self.download_tile_grid(center_x, center_y, grid_width, grid_height)
            
            if not tiles:
                self.log.emit("❌ Nepodařilo se stáhnout žádné dlaždice", "error")
                return None
            
            self.log.emit(f"📥 Staženo {len(tiles)} dlaždic, start pozice: ({start_x}, {start_y})", "info")
            
            # Složení dlaždic
            large_image = self.stitch_tiles(tiles, grid_width, grid_height)
            
            if not large_image:
                self.log.emit("❌ Nepodařilo se složit dlaždice", "error")
                return None
            
            self.log.emit(f"🧩 Složený obrázek: {large_image.size[0]}×{large_image.size[1]}px", "info")
            
            # Výpočet GPS pozice v gridu
            gps_x, gps_y = self.calculate_gps_position_in_grid(lat, lon, zoom, start_x, start_y)
            self.log.emit(f"📍 GPS pozice v gridu: ({gps_x}, {gps_y})", "info")
            
            # Oříznutí na požadovanou velikost
            final_image, new_gps_x, new_gps_y = self.crop_centered_image(
                large_image, gps_x, gps_y, width_px, height_px
            )
            
            if not final_image:
                self.log.emit("❌ Nepodařilo se oříznout obrázek", "error")
                return None
            
            self.log.emit(f"✅ Finální mapa: {final_image.size[0]}×{final_image.size[1]}px, GPS: ({new_gps_x}, {new_gps_y})", "success")
            
            return final_image
            
        except Exception as e:
            self.log.emit(f"❌ Chyba v download_map_tiles: {e}", "error")
            import traceback
            self.log.emit(f"❌ Traceback: {traceback.format_exc()}", "error")
            return None
    
    def calculate_marker_position(self, lat, lon, zoom, width_px, height_px):
        """Výpočet pozice GPS markeru - GPS je ve středu"""
        return width_px // 2, height_px // 2
    
    def combine_images(self, input_image, map_image):
        """Kombinování vstupního obrázku s mapou"""
        try:
            # Převod na RGBA
            if input_image.mode != 'RGBA':
                input_image = input_image.convert('RGBA')
            if map_image.mode != 'RGBA':
                map_image = map_image.convert('RGBA')
            
            # Změna velikosti vstupního obrázku na velikost mapy
            map_width, map_height = map_image.size
            input_resized = input_image.resize((map_width, map_height), Image.Resampling.LANCZOS)
            
            # Kombinování - mapa přes vstupní obrázek
            combined = Image.alpha_composite(input_resized, map_image)
            
            return combined
            
        except Exception as e:
            self.log.emit(f"❌ Chyba při kombinování: {e}", "error")
            return map_image
    
    def get_gps_from_photo(self, photo_path):
        """Wrapper pro get_gps_from_image - pro konzistenci názvů"""
        return self.get_gps_from_image(photo_path)
    
    def validate_coordinate_mode_settings(self):
        """Validace nastavení režimu souřadnic"""
        coordinate_mode = self.params['coordinate_mode']
        
        if coordinate_mode == 'F':
            if not self.params['photo_filename'] or not Path(self.params['photo_filename']).exists():
                self.error.emit("Soubor fotky neexistuje nebo není zadán")
                return False
            self.log.emit("✓ Režim F: Souřadnice budou načteny ze souboru fotky", "info")
        elif coordinate_mode == 'G':
            if not self.params['manual_coordinates']:
                self.error.emit("Pro režim G musíte zadat ruční souřadnice")
                return False
            self.log.emit("✓ Režim G: Použijí se ručně zadané souřadnice", "info")
        else:
            self.error.emit(f"Neplatný režim souřadnic: {coordinate_mode}")
            return False
            
        return True

    def get_coordinates_based_on_mode(self):
        """Získání souřadnic podle zvoleného režimu"""
        coordinate_mode = self.params['coordinate_mode']
        
        if coordinate_mode == 'F':
            self.log.emit("📁 Načítám GPS souřadnice ze souboru fotky...", "info")
            return self.get_gps_from_image(self.params['photo_filename'])
        elif coordinate_mode == 'G':
            self.log.emit("📍 Používám ručně zadané souřadnice...", "info")
            return self.parse_manual_coordinates(self.params['manual_coordinates'])
        
        return None

    def get_gps_from_image(self, image_path):
        """Extrakce GPS souřadnic z EXIF dat obrázku - OPRAVENÁ VERZE pro HEIC"""
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS, GPSTAGS
            import pillow_heif
            
            # Registrace HEIF podpory
            pillow_heif.register_heif_opener()
            
            self.log.emit(f"📷 Načítám GPS data z: {os.path.basename(image_path)}", "info")
            
            with Image.open(image_path) as image:
                self.log.emit(f"📷 Formát obrázku: {image.format}", "info")
                
                # Získání EXIF dat
                if image.format in ['HEIF', 'HEIC']:
                    self.log.emit("📷 HEIC/HEIF: Používám getexif() metodu", "info")
                    exif_data = image.getexif()
                else:
                    self.log.emit("📷 JPEG/ostatní: Používám _getexif() metodu", "info")
                    exif_data = image._getexif()
                
                if exif_data is None:
                    self.log.emit("❌ Obrázek neobsahuje EXIF data", "error")
                    return None
                
                self.log.emit(f"📷 Nalezeno {len(exif_data)} EXIF tagů", "info")
                
                # Hledání GPS informací - NOVÁ METODA pro HEIC
                gps_info = None
                
                # Metoda 1: Použití get_ifd() pro GPS IFD (nejlepší pro HEIC)
                try:
                    if hasattr(exif_data, 'get_ifd'):
                        gps_ifd = exif_data.get_ifd(0x8825)  # GPS IFD tag
                        if gps_ifd:
                            gps_info = dict(gps_ifd)
                            self.log.emit(f"📍 GPS IFD nalezeno s {len(gps_info)} položkami", "success")
                        else:
                            self.log.emit("📍 GPS IFD je prázdné", "warning")
                except Exception as e:
                    self.log.emit(f"📍 GPS IFD nedostupné: {e}", "info")
                
                # Metoda 2: Přímý přístup k GPS tagu (fallback)
                if not gps_info and 34853 in exif_data:
                    gps_raw = exif_data[34853]
                    self.log.emit(f"📍 Nalezen GPS tag 34853, typ: {type(gps_raw)}, hodnota: {gps_raw}", "info")
                    
                    if isinstance(gps_raw, dict):
                        gps_info = gps_raw
                        self.log.emit(f"📍 GPS data jsou slovník s {len(gps_info)} položkami", "info")
                
                # Metoda 3: Klasická metoda pro JPEG
                if not gps_info and hasattr(exif_data, 'items'):
                    for tag, value in exif_data.items():
                        decoded = TAGS.get(tag, tag)
                        if decoded == "GPSInfo":
                            gps_info = {}
                            if isinstance(value, dict):
                                for gps_tag, gps_value in value.items():
                                    sub_decoded = GPSTAGS.get(gps_tag, gps_tag)
                                    gps_info[sub_decoded] = gps_value
                            break
                
                if not gps_info:
                    self.log.emit("❌ Obrázek neobsahuje GPS data", "error")
                    # Debug: vypsat všechny dostupné tagy
                    self.log.emit("🔍 Dostupné EXIF tagy:", "info")
                    for tag_id, value in list(exif_data.items())[:15]:
                        tag_name = TAGS.get(tag_id, f"Tag_{tag_id}")
                        value_str = str(value)[:100] if len(str(value)) > 100 else str(value)
                        self.log.emit(f"  {tag_id}: {tag_name} = {type(value).__name__} {value_str}", "info")
                    
                    # Pokus o alternativní metody
                    return self.try_alternative_gps_extraction(image, image_path)
                
                self.log.emit(f"📍 GPS info nalezeno: {len(gps_info)} položek", "info")
                
                # Debug: vypsat GPS tagy
                self.log.emit("🔍 GPS tagy:", "info")
                for key, value in list(gps_info.items())[:10]:
                    self.log.emit(f"  {key}: {value} (typ: {type(value).__name__})", "info")
                
                # Parsování GPS dat
                lat = self.parse_gps_coordinate_heic(gps_info, 'GPSLatitude', 'GPSLatitudeRef')
                lon = self.parse_gps_coordinate_heic(gps_info, 'GPSLongitude', 'GPSLongitudeRef')
                
                if lat is None or lon is None:
                    self.log.emit("❌ Neplatná GPS data v obrázku", "error")
                    return None
                
                self.log.emit(f"✓ GPS souřadnice načteny ze souboru: {lat:.6f}°, {lon:.6f}°", "success")
                return lat, lon
                
        except Exception as e:
            self.log.emit(f"❌ Chyba při čtení GPS dat: {e}", "error")
            import traceback
            self.log.emit(f"❌ Traceback: {traceback.format_exc()}", "error")
            return None
        
    def try_alternative_gps_extraction(self, image, image_path):
        """Alternativní metody pro extrakci GPS dat"""
        try:
            self.log.emit("🔄 Zkouším alternativní metody extrakce GPS...", "info")
            
            # Metoda 1: Použití exiftool (pokud je dostupný)
            try:
                import subprocess
                import json
                
                self.log.emit("🔧 Zkouším exiftool...", "info")
                result = subprocess.run([
                    'exiftool', '-json', '-GPS*', str(image_path)
                ], capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)[0]
                    
                    # Hledání GPS dat v různých formátech
                    lat = None
                    lon = None
                    
                    # Formát 1: GPSLatitude/GPSLongitude jako čísla
                    if 'GPSLatitude' in data and 'GPSLongitude' in data:
                        lat = float(data['GPSLatitude'])
                        lon = float(data['GPSLongitude'])
                    
                    # Formát 2: Composite GPS pozice
                    elif 'GPSPosition' in data:
                        pos = data['GPSPosition']
                        # Parsování "49.23173 N, 17.42791 E" formátu
                        import re
                        match = re.search(r'([0-9.]+)\s*([NS]),\s*([0-9.]+)\s*([EW])', pos)
                        if match:
                            lat = float(match.group(1))
                            if match.group(2) == 'S':
                                lat = -lat
                            lon = float(match.group(3))
                            if match.group(4) == 'W':
                                lon = -lon
                    
                    if lat is not None and lon is not None:
                        self.log.emit(f"✅ ExifTool GPS: {lat:.6f}°, {lon:.6f}°", "success")
                        return lat, lon
                    else:
                        self.log.emit("❌ ExifTool nenašel GPS data", "warning")
                
            except FileNotFoundError:
                self.log.emit("⚠️ ExifTool není nainstalován", "info")
            except Exception as e:
                self.log.emit(f"❌ ExifTool chyba: {e}", "warning")
            
            # Metoda 2: Pokus o raw EXIF data
            try:
                self.log.emit("🔧 Zkouším raw EXIF data...", "info")
                if hasattr(image, 'info') and 'exif' in image.info:
                    exif_bytes = image.info['exif']
                    self.log.emit(f"📷 Nalezena raw EXIF data: {len(exif_bytes)} bytů", "info")
                    # Zde by bylo potřeba parsovat raw EXIF data, což je složité
            except Exception as e:
                self.log.emit(f"❌ Raw EXIF chyba: {e}", "warning")
            
            self.log.emit("❌ Všechny alternativní metody selhaly", "error")
            return None
            
        except Exception as e:
            self.log.emit(f"❌ Chyba v alternativních metodách: {e}", "error")
            return None
        
    def parse_gps_coordinate_heic(self, gps_info, coord_key, ref_key):
        """Parsování GPS souřadnice pro HEIC - upravená metoda"""
        try:
            from PIL.ExifTags import GPSTAGS
            
            self.log.emit(f"🔍 Hledám {coord_key} a {ref_key} v GPS datech", "info")
            
            # Najít správné klíče v GPS datech
            coord_value = None
            ref_value = None
            
            # Metoda 1: Přímé klíče (string)
            if coord_key in gps_info:
                coord_value = gps_info[coord_key]
            if ref_key in gps_info:
                ref_value = gps_info[ref_key]
            
            # Metoda 2: Hledání podle GPSTAGS (číselné klíče)
            if coord_value is None or ref_value is None:
                for tag_id, tag_name in GPSTAGS.items():
                    if tag_name == coord_key and tag_id in gps_info:
                        coord_value = gps_info[tag_id]
                        self.log.emit(f"📍 Nalezen {coord_key} pod klíčem {tag_id}", "info")
                    elif tag_name == ref_key and tag_id in gps_info:
                        ref_value = gps_info[tag_id]
                        self.log.emit(f"📍 Nalezen {ref_key} pod klíčem {tag_id}", "info")
            
            # Metoda 3: Známé číselné klíče pro GPS
            if coord_value is None or ref_value is None:
                gps_key_map = {
                    'GPSLatitude': 2,
                    'GPSLatitudeRef': 1,
                    'GPSLongitude': 4,
                    'GPSLongitudeRef': 3
                }
                
                if coord_key in gps_key_map and gps_key_map[coord_key] in gps_info:
                    coord_value = gps_info[gps_key_map[coord_key]]
                    self.log.emit(f"📍 Nalezen {coord_key} pod známým klíčem {gps_key_map[coord_key]}", "info")
                
                if ref_key in gps_key_map and gps_key_map[ref_key] in gps_info:
                    ref_value = gps_info[gps_key_map[ref_key]]
                    self.log.emit(f"📍 Nalezen {ref_key} pod známým klíčem {gps_key_map[ref_key]}", "info")
            
            if coord_value is None or ref_value is None:
                self.log.emit(f"❌ Nenalezeny GPS data pro {coord_key}/{ref_key}", "error")
                self.log.emit(f"❌ coord_value: {coord_value}, ref_value: {ref_value}", "error")
                return None
            
            self.log.emit(f"📍 {coord_key}: {coord_value} (typ: {type(coord_value)})", "info")
            self.log.emit(f"📍 {ref_key}: {ref_value} (typ: {type(ref_value)})", "info")
            
            # Konverze na desetinné stupně
            if isinstance(coord_value, (list, tuple)) and len(coord_value) >= 3:
                try:
                    degrees = float(coord_value[0])
                    minutes = float(coord_value[1])
                    seconds = float(coord_value[2])
                    
                    decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
                    
                    self.log.emit(f"📍 Konverze: {degrees}° {minutes}' {seconds}\" = {decimal:.6f}°", "info")
                    
                    # Aplikace směru
                    if isinstance(ref_value, str) and ref_value in ['S', 'W']:
                        decimal = -decimal
                        self.log.emit(f"📍 Aplikován směr {ref_value}: {decimal:.6f}°", "info")
                    
                    return decimal
                    
                except (ValueError, TypeError) as e:
                    self.log.emit(f"❌ Chyba při konverzi GPS hodnot: {e}", "error")
                    return None
            
            self.log.emit(f"❌ Neplatný formát GPS souřadnice: {coord_value} (typ: {type(coord_value)})", "error")
            return None
            
        except Exception as e:
            self.log.emit(f"❌ Chyba při parsování GPS souřadnice: {e}", "error")
            import traceback
            self.log.emit(f"❌ Traceback: {traceback.format_exc()}", "error")
            return None
        
    def parse_gps_coordinate(self, gps_info, coord_key, ref_key):
        """Parsování GPS souřadnice - nová pomocná metoda"""
        try:
            from PIL.ExifTags import GPSTAGS
            
            # Najít správné klíče v GPS datech
            coord_value = None
            ref_value = None
            
            # Pokud je gps_info slovník s číselnými klíči (HEIC)
            if isinstance(gps_info, dict):
                # Hledání podle GPSTAGS
                for tag_id, tag_name in GPSTAGS.items():
                    if tag_name == coord_key and tag_id in gps_info:
                        coord_value = gps_info[tag_id]
                    elif tag_name == ref_key and tag_id in gps_info:
                        ref_value = gps_info[tag_id]
                
                # Pokud nenalezeno, zkusit přímé klíče
                if coord_value is None:
                    coord_value = gps_info.get(coord_key)
                if ref_value is None:
                    ref_value = gps_info.get(ref_key)
            
            if coord_value is None or ref_value is None:
                self.log.emit(f"❌ Nenalezeny GPS data pro {coord_key}/{ref_key}", "error")
                return None
            
            self.log.emit(f"📍 {coord_key}: {coord_value}, {ref_key}: {ref_value}", "info")
            
            # Konverze na desetinné stupně
            if isinstance(coord_value, (list, tuple)) and len(coord_value) >= 3:
                degrees = float(coord_value[0])
                minutes = float(coord_value[1])
                seconds = float(coord_value[2])
                
                decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
                
                # Aplikace směru
                if ref_value in ['S', 'W']:
                    decimal = -decimal
                    
                return decimal
            
            self.log.emit(f"❌ Neplatný formát GPS souřadnice: {coord_value}", "error")
            return None
            
        except Exception as e:
            self.log.emit(f"❌ Chyba při parsování GPS souřadnice: {e}", "error")
            return None

    def convert_to_degrees(self, value):
        """Konverze GPS souřadnic na desetinné stupně"""
        if not value:
            return None
        
        try:
            d, m, s = value
            return float(d) + float(m)/60.0 + float(s)/3600.0
        except:
            return None

    def parse_manual_coordinates(self, coord_string):
        """
        Parsuje ručně zadané souřadnice ve formátu "49,23092° S, 17,65692° V"
        Podporuje české označení: S=Sever, V=Východ, J=Jih, Z=Západ
        Vrací tuple (latitude, longitude) v desetinných stupních nebo None
        """
        try:
            # Odstranění mezer a rozdělení podle čárky mezi souřadnicemi
            coord_string = coord_string.strip()
            
            # Rozdělení na dvě části - hledáme čárku, která odděluje lat a lon
            # Použijeme regex pro přesnější rozdělení
            coord_parts = re.split(r',\s*(?=\d)', coord_string)
            
            if len(coord_parts) != 2:
                # Pokus o jiné rozdělení - hledáme pattern pro lat a lon
                pattern = r'([0-9,\.]+°?\s*[NSJZ])\s*,?\s*([0-9,\.]+°?\s*[EWVZ])'
                match = re.match(pattern, coord_string, re.IGNORECASE)
                
                if not match:
                    self.log.emit(f"❌ Nesprávný formát souřadnic. Očekáván formát: '49,23092° S, 17,65692° V'", "error")
                    self.log.emit(f"Zadáno: '{coord_string}'", "error")
                    return None
                
                coord_parts = [match.group(1), match.group(2)]
            
            # Parsování zeměpisné šířky (latitude)
            lat_part = coord_parts[0].strip()
            # Regex pro podporu českých i anglických označení
            lat_match = re.search(r'([0-9]+[,\.]?[0-9]*)°?\s*([NSJS])', lat_part, re.IGNORECASE)
            
            if not lat_match:
                self.log.emit(f"❌ Nelze parsovat zeměpisnou šířku z: '{lat_part}'", "error")
                self.log.emit(f"Očekávaný formát: '49,23092° S' (S=Sever, J=Jih)", "error")
                return None
            
            lat_value_str = lat_match.group(1).replace(',', '.')  # Převod čárky na tečku
            lat_value = float(lat_value_str)
            lat_direction = lat_match.group(2).upper()
            
            # České označení: S=Sever (kladná), J=Jih (záporná)
            # Anglické označení: N=North (kladná), S=South (záporná)
            if lat_direction in ['J']:  # J = Jih (záporná)
                lat_value = -lat_value
            elif lat_direction in ['S']:  # S = Sever (kladná) v českém systému
                lat_value = abs(lat_value)  # Zajistíme kladnou hodnotu
            elif lat_direction in ['N']:  # N = North (kladná) v anglickém systému
                lat_value = abs(lat_value)
            # Pro anglické S (South) by byla záporná, ale v českém kontextu S=Sever
            
            # Parsování zeměpisné délky (longitude)
            lon_part = coord_parts[1].strip()
            # Regex pro podporu českých i anglických označení
            lon_match = re.search(r'([0-9]+[,\.]?[0-9]*)°?\s*([EWVZ])', lon_part, re.IGNORECASE)
            
            if not lon_match:
                self.log.emit(f"❌ Nelze parsovat zeměpisnou délku z: '{lon_part}'", "error")
                self.log.emit(f"Očekávaný formát: '17,65692° V' (V=Východ, Z=Západ)", "error")
                return None
            
            lon_value_str = lon_match.group(1).replace(',', '.')  # Převod čárky na tečku
            lon_value = float(lon_value_str)
            lon_direction = lon_match.group(2).upper()
            
            # České označení: V=Východ (kladná), Z=Západ (záporná)
            # Anglické označení: E=East (kladná), W=West (záporná)
            if lon_direction in ['Z', 'W']:  # Z=Západ, W=West (záporná)
                lon_value = -lon_value
            elif lon_direction in ['V', 'E']:  # V=Východ, E=East (kladná)
                lon_value = abs(lon_value)  # Zajistíme kladnou hodnotu
            
            self.log.emit(f"✓ Souřadnice úspěšně parsovány (ruční zadání)", "success")
            self.log.emit(f"  Zeměpisná šířka: {lat_value:.6f}° ({'J' if lat_value < 0 else 'S'})", "info")
            self.log.emit(f"  Zeměpisná délka: {lon_value:.6f}° ({'Z' if lon_value < 0 else 'V'})", "info")
            
            return lat_value, lon_value
            
        except Exception as e:
            self.log.emit(f"❌ Chyba při parsování souřadnic: {e}", "error")
            self.log.emit(f"Očekávaný formát: '49,23092° S, 17,65692° V'", "error")
            self.log.emit(f"České označení: S=Sever, V=Východ, J=Jih, Z=Západ", "info")
            self.log.emit(f"Zadáno: '{coord_string}'", "error")
            return None
        
    def calculate_pixel_dimensions(self):
        """Výpočet rozměrů v pixelech"""
        width_cm = self.params['output_width_cm']
        height_cm = self.params['output_height_cm']
        dpi = self.params['output_dpi']
        
        # Konverze cm na palce (1 palec = 2.54 cm)
        width_inches = width_cm / 2.54
        height_inches = height_cm / 2.54
        
        # Výpočet pixelů
        width_pixels = int(width_inches * dpi)
        height_pixels = int(height_inches * dpi)
        
        return width_pixels, height_pixels

    def generate_id(self):
        """Generování ID"""
        if self.params['auto_generate_id']:
            # Automatické generování na základě času
            from datetime import datetime
            return datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            return self.params['manual_cislo_id']

    def generate_output_filename_with_gps_and_zoom(self, id_lokace, popis, lat, lon, zoom, cislo_id):
        """Generování názvu výstupního souboru s + jako oddělovači"""
        # Formátování GPS souřadnic
        lat_formatted = f"{abs(lat):.5f}{'S' if lat >= 0 else 'J'}"
        lon_formatted = f"{abs(lon):.5f}{'V' if lon >= 0 else 'Z'}"
        
        # OPRAVENO: použití + jako oddělovače místo _
        filename = f"{id_lokace}+{popis}+GPS{lat_formatted}+{lon_formatted}+Z{zoom}+{cislo_id}.png"
        
        # Sanitizace názvu souboru (zachování + jako validního znaku)
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        return filename

    def calculate_tile_grid(self, target_width, target_height):
        """Výpočet gridu dlaždic"""
        # Přidání bufferu pro zajištění pokrytí
        buffer_factor = 1.2
        
        grid_width = max(2, int((target_width * buffer_factor) / self.TILE_SIZE) + 1)
        grid_height = max(2, int((target_height * buffer_factor) / self.TILE_SIZE) + 1)
        
        # Zajištění lichého počtu pro centrování
        if grid_width % 2 == 0:
            grid_width += 1
        if grid_height % 2 == 0:
            grid_height += 1
            
        return grid_width, grid_height

    def lat_lon_to_tile_int(self, lat, lon, zoom):
        """Převod GPS souřadnic na čísla dlaždic"""
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        
        x = int((lon + 180.0) / 360.0 * n)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        
        return x, y

    def download_tile_grid(self, center_x, center_y, grid_width, grid_height):
        """Stažení gridu dlaždic"""
        tiles = {}
        total_tiles = grid_width * grid_height
        downloaded = 0
        
        # Výpočet rozsahu
        half_width = grid_width // 2
        half_height = grid_height // 2
        
        start_x = center_x - half_width
        start_y = center_y - half_height
        
        self.log.emit(f"📥 Stahování {total_tiles} dlaždic...", "info")
        
        for dy in range(grid_height):
            if self.should_stop:
                return None, None, None
                
            for dx in range(grid_width):
                if self.should_stop:
                    return None, None, None
                    
                tile_x = start_x + dx
                tile_y = start_y + dy
                
                tile_image = self.download_tile(tile_x, tile_y, self.params['zoom'])
                if tile_image:
                    tiles[(dx, dy)] = tile_image
                    
                downloaded += 1
                progress = 30 + int((downloaded / total_tiles) * 40)  # 30-70%
                self.progress.emit(progress)
                
                # Zpoždění mezi požadavky
                if self.REQUEST_DELAY > 0:
                    time.sleep(self.REQUEST_DELAY)
        
        self.log.emit(f"✓ Staženo {len(tiles)}/{total_tiles} dlaždic", "success")
        return tiles, start_x, start_y

    def download_tile(self, x, y, z, retries=3):
        """Stažení mapové dlaždice s opravou kódování - OPRAVENÁ VERZE"""
        url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        
        # OPRAVENO: User-Agent bez českých znaků
        headers = {
            'User-Agent': 'MapGenerator/1.0 (Python)',  # Bez českých znaků
            'Accept': 'image/png,image/*,*/*',
            'Accept-Language': 'cs,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache'
        }
        
        for attempt in range(retries):
            try:
                response = requests.get(
                    url, 
                    headers=headers,
                    timeout=10,
                    stream=True
                )
                
                if response.status_code == 200:
                    content = response.content
                    if len(content) > 0:
                        # OPRAVENO: Správný signál
                        return content
                    else:
                        self.log.emit(f"⚠️ Prázdná dlaždice {x},{y}", "warning")
                else:
                    self.log.emit(f"⚠️ HTTP {response.status_code} pro dlaždici {x},{y}", "warning")
                    
            except requests.exceptions.Timeout:
                self.log.emit(f"⏱️ Timeout pro dlaždici {x},{y} (pokus {attempt + 1})", "warning")
                
            except requests.exceptions.ConnectionError:
                self.log.emit(f"🌐 Chyba připojení pro dlaždici {x},{y} (pokus {attempt + 1})", "warning")
                
            except Exception as e:
                self.log.emit(f"❌ Chyba pro dlaždici {x},{y}: {str(e)}", "error")
            
            # Pauza mezi pokusy
            if attempt < retries - 1:
                time.sleep(1)
        
        self.log.emit(f"❌ Nepodařilo se stáhnout dlaždici {x},{y} po {retries} pokusech", "error")
        return None

    def stitch_tiles(self, tiles, grid_width, grid_height):
        """Složení dlaždic do jednoho obrázku - OPRAVENÁ VERZE"""
        if not tiles:
            self.log.emit("❌ Žádné dlaždice k složení", "error")
            return None
        
        try:
            # Vytvoření velkého obrázku
            total_width = grid_width * self.TILE_SIZE
            total_height = grid_height * self.TILE_SIZE
            
            self.log.emit(f"🧩 Skládám dlaždice: {grid_width}×{grid_height} = {total_width}×{total_height} px", "info")
            
            large_image = Image.new('RGB', (total_width, total_height), color='white')
            
            successful_tiles = 0
            
            for (dx, dy), tile_data in tiles.items():
                try:
                    # Kontrola pozice
                    if dx >= grid_width or dy >= grid_height:
                        self.log.emit(f"⚠️ Dlaždice mimo grid: ({dx},{dy})", "warning")
                        continue
                    
                    # Konverze tile_data na PIL Image
                    if isinstance(tile_data, bytes):
                        tile_image = Image.open(BytesIO(tile_data))
                    elif isinstance(tile_data, Image.Image):
                        tile_image = tile_data
                    else:
                        self.log.emit(f"⚠️ Neplatný typ dlaždice: {type(tile_data)}", "warning")
                        continue
                    
                    # Kontrola velikosti dlaždice
                    if tile_image.size != (self.TILE_SIZE, self.TILE_SIZE):
                        self.log.emit(f"⚠️ Nesprávná velikost dlaždice: {tile_image.size}, očekáváno: ({self.TILE_SIZE}, {self.TILE_SIZE})", "warning")
                        tile_image = tile_image.resize((self.TILE_SIZE, self.TILE_SIZE), Image.Resampling.LANCZOS)
                    
                    # Výpočet pozice
                    x_pos = dx * self.TILE_SIZE
                    y_pos = dy * self.TILE_SIZE
                    
                    # Kontrola, že pozice je v rámci obrázku
                    if x_pos + self.TILE_SIZE <= total_width and y_pos + self.TILE_SIZE <= total_height:
                        # OPRAVENO: Použití 4-item box tuple
                        paste_box = (x_pos, y_pos, x_pos + self.TILE_SIZE, y_pos + self.TILE_SIZE)
                        large_image.paste(tile_image, paste_box[:2])  # Pouze x,y pozice pro paste
                        successful_tiles += 1
                    else:
                        self.log.emit(f"⚠️ Dlaždice mimo hranice: pozice ({x_pos},{y_pos})", "warning")
                        
                except Exception as e:
                    self.log.emit(f"❌ Chyba při vkládání dlaždice ({dx},{dy}): {e}", "error")
                    continue
            
            self.log.emit(f"✅ Úspěšně složeno {successful_tiles}/{len(tiles)} dlaždic", "success")
            
            if successful_tiles == 0:
                self.log.emit("❌ Žádné dlaždice nebyly úspěšně složeny", "error")
                return None
            
            return large_image
            
        except Exception as e:
            self.log.emit(f"❌ Kritická chyba při skládání dlaždic: {e}", "error")
            import traceback
            self.log.emit(f"❌ Traceback: {traceback.format_exc()}", "error")
            return None

    def calculate_gps_position_in_grid(self, lat, lon, zoom, grid_start_x, grid_start_y):
        """Výpočet pozice GPS v gridu"""
        # Převod na přesné souřadnice dlaždice
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        
        tile_x_float = (lon + 180.0) / 360.0 * n
        tile_y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        
        # Pozice v gridu
        relative_x = tile_x_float - grid_start_x
        relative_y = tile_y_float - grid_start_y
        
        # Převod na pixely
        pixel_x = int(relative_x * self.TILE_SIZE)
        pixel_y = int(relative_y * self.TILE_SIZE)
        
        return pixel_x, pixel_y

    # def draw_location_marker(self, image, x, y):
    #     """
    #     Kreslí GPS značku do finálního obrázku podle parametrů:
    #     - params['marker_style']: 'dot' (puntík) nebo 'cross' (křížek)
    #     - params['marker_size']: velikost značky v pixelech (poloměr pro puntík, půlrameno pro křížek)
    #     """
    #     try:
    #         draw = ImageDraw.Draw(image)
    #         ms = max(2, int(self.params.get('marker_size', 10)))
    #         style = str(self.params.get('marker_style', 'dot')).lower()
    
    #         if style == 'cross':
    #             th = max(2, ms // 3)  # tloušťka čar úměrná velikosti
    #             draw.line([(x - ms, y), (x + ms, y)], fill='black', width=th)
    #             draw.line([(x, y - ms), (x, y + ms)], fill='black', width=th)
    #         else:
    #             # Puntík s bílým okrajem kvůli čitelnosti
    #             draw.ellipse([x - ms, y - ms, x + ms, y + ms],
    #                          fill='black', outline='white', width=max(2, ms // 5))
    #         return image
    #     except Exception as e:
    #         # Při chybě fallback na původní puntík
    #         try:
    #             r = max(2, int(self.params.get('marker_size', 10)))
    #             draw = ImageDraw.Draw(image)
    #             draw.ellipse([x - r, y - r, x + r, y + r], fill='black', outline='white', width=max(2, r // 5))
    #         except Exception:
    #             pass
    #         self.log.emit(f"⚠️ Chyba při kreslení značky: {e}", "warning")
    #         return image
    
    def draw_central_marker(self, image):
        """
        Vykreslí pouze centrální GPS značku do obrázku lokační mapy.
        Žádné texty se zde již nekreslí.
        """
        from PIL import ImageDraw
    
        W, H = image.size
        center_x, center_y = W // 2, H // 2
    
        draw = ImageDraw.Draw(image)
    
        # Parametry značky z nastavení
        marker_size = int(self.params.get('marker_size', 10))
        marker_style = self.params.get('marker_style', 'dot')
    
        if marker_style == 'cross':
            # Křížek s tloušťkou úměrnou velikosti
            thickness = max(2, marker_size // 4)
            draw.line([(center_x - marker_size, center_y), (center_x + marker_size, center_y)], fill="black", width=thickness)  # ✅ ČERNÁ
            draw.line([(center_x, center_y - marker_size), (center_x, center_y + marker_size)], fill="black", width=thickness)  # ✅ ČERNÁ
        else: # 'dot'
            # Puntík s bílým okrajem pro lepší viditelnost
            radius = marker_size // 2
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                fill='black',  # ✅ ČERNÁ
                outline='white',
                width=max(1, radius // 4)
            )
    
        return image


    def crop_centered_image(self, image, center_x, center_y, target_width, target_height):
        """Oříznutí obrázku na cílovou velikost - OPRAVENÁ VERZE"""
        try:
            img_width, img_height = image.size
            
            self.log.emit(f"✂️ Ořezávám obrázek: {img_width}×{img_height} → {target_width}×{target_height}", "info")
            self.log.emit(f"✂️ Střed GPS: ({center_x}, {center_y})", "info")
            
            # Výpočet ořezových souřadnic se středem na GPS pozici
            half_target_width = target_width // 2
            half_target_height = target_height // 2
            
            left = max(0, center_x - half_target_width)
            top = max(0, center_y - half_target_height)
            right = min(img_width, center_x + half_target_width)
            bottom = min(img_height, center_y + half_target_height)
            
            # Úprava pokud je požadovaná oblast větší než dostupný obrázek
            if right - left < target_width:
                if left == 0:
                    right = min(img_width, left + target_width)
                elif right == img_width:
                    left = max(0, right - target_width)
            
            if bottom - top < target_height:
                if top == 0:
                    bottom = min(img_height, top + target_height)
                elif bottom == img_height:
                    top = max(0, bottom - target_height)
            
            # Zajištění platných souřadnic
            left = max(0, min(left, img_width - 1))
            top = max(0, min(top, img_height - 1))
            right = max(left + 1, min(right, img_width))
            bottom = max(top + 1, min(bottom, img_height))
            
            self.log.emit(f"✂️ Ořezové souřadnice: ({left}, {top}, {right}, {bottom})", "info")
            
            # OPRAVENO: Použití 4-item box tuple
            crop_box = (int(left), int(top), int(right), int(bottom))
            
            # Kontrola validity crop_box
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                self.log.emit(f"❌ Neplatný crop box: {crop_box}", "error")
                return None, center_x, center_y
            
            cropped = image.crop(crop_box)
            
            # Výpočet nové pozice GPS v oříznutém obrázku
            new_gps_x = center_x - left
            new_gps_y = center_y - top
            
            cropped_width, cropped_height = cropped.size
            self.log.emit(f"✂️ Oříznutý obrázek: {cropped_width}×{cropped_height}", "info")
            
            # Pokud je oříznutý obrázek menší než cíl, doplnění bílou barvou
            if cropped_width != target_width or cropped_height != target_height:
                self.log.emit(f"📐 Doplňuji na cílovou velikost: {target_width}×{target_height}", "info")
                
                final_image = Image.new('RGB', (target_width, target_height), 'white')
                
                # Centrování oříznutého obrázku
                paste_x = (target_width - cropped_width) // 2
                paste_y = (target_height - cropped_height) // 2
                
                final_image.paste(cropped, (paste_x, paste_y))
                
                # Úprava GPS pozice
                new_gps_x += paste_x
                new_gps_y += paste_y
                
                self.log.emit(f"✅ Finální obrázek: {target_width}×{target_height}, GPS: ({new_gps_x}, {new_gps_y})", "success")
                
                return final_image, new_gps_x, new_gps_y
            
            self.log.emit(f"✅ Oříznutí dokončeno, GPS: ({new_gps_x}, {new_gps_y})", "success")
            return cropped, new_gps_x, new_gps_y
            
        except Exception as e:
            self.log.emit(f"❌ Chyba při ořezávání: {e}", "error")
            import traceback
            self.log.emit(f"❌ Traceback: {traceback.format_exc()}", "error")
            return None, center_x, center_y

    def apply_transparency_to_image_precise(self, image, opacity):
        """Aplikace transparentnosti na obrázek"""
        if opacity >= 1.0:
            return image
            
        # Konverze na RGBA
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Aplikace transparentnosti
        alpha = image.split()[-1]
        alpha = alpha.point(lambda p: int(p * opacity))
        
        image.putalpha(alpha)
        return image

    def add_watermark_text(self, image, text, size_mm, dpi):
        """Přidání textového vodoznaku"""
        try:
            from PIL import ImageFont
            
            # Výpočet velikosti fontu v pixelech
            size_inches = size_mm / 25.4  # mm na palce
            font_size = int(size_inches * dpi)
            
            # Pokus o načtení systémového fontu
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
                except:
                    font = ImageFont.load_default()
            
            # Vytvoření kopie obrázku
            watermarked = image.copy()
            draw = ImageDraw.Draw(watermarked)
            
            # Pozice vodoznaku (pravý dolní roh)
            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            margin = 10
            x = watermarked.width - text_width - margin
            y = watermarked.height - text_height - margin
            
            # Nakreslení textu s obrysem
            for adj_x in [-1, 0, 1]:
                for adj_y in [-1, 0, 1]:
                    if adj_x != 0 or adj_y != 0:
                        draw.text((x + adj_x, y + adj_y), text, font=font, fill='white')
            
            draw.text((x, y), text, font=font, fill='black')
            
            return watermarked
            
        except Exception as e:
            self.log.emit(f"⚠️ Chyba při přidávání vodoznaku: {e}", "warning")
            return image

    def create_output_path(self, filename):
        """Vytvoření cesty k výstupnímu souboru"""
        output_dir = Path(self.params['output_directory'])
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / filename
        
        # Pokud soubor existuje, přidání čísla
        counter = 1
        original_path = output_path
        while output_path.exists():
            stem = original_path.stem
            suffix = original_path.suffix
            output_path = output_dir / f"{stem}_{counter:03d}{suffix}"
            counter += 1
            
        return output_path
    
    def find_next_auto_id(self, output_directory, id_lokace):
        """
        Najde nejvyšší číslo ID v existujících souborech a vrátí další v pořadí
        Hledá pattern: *+Z*+XXXXX.png kde XXXXX je 5-místné číslo
        """
        try:
            output_path = Path(output_directory)
            if not output_path.exists():
                self.log.emit("📁 Výstupní složka neexistuje, začínám s ID 00001", "info")
                return "00001"
            
            # Hledání všech PNG souborů
            png_files = list(output_path.glob("*.png"))
            
            if not png_files:
                self.log.emit("📁 Ve výstupní složce nejsou žádné PNG soubory, začínám s ID 00001", "info")
                return "00001"
            
            max_id = 0
            found_files = []
            
            # Regex pattern pro hledání ID na konci názvu souboru
            # Pattern: cokoliv+Z[číslo]+[5-místné_číslo].png
            import re
            pattern = r'.*\+Z\d+\+(\d{5})\.png'
            
            for file_path in png_files:
                filename = file_path.name
                match = re.search(pattern, filename)
                
                if match:
                    file_id = int(match.group(1))
                    found_files.append((filename, file_id))
                    if file_id > max_id:
                        max_id = file_id
            
            # Logování nalezených souborů
            if found_files:
                self.log.emit(f"🔍 Nalezeno {len(found_files)} souborů s ID:", "info")
                # Seřazení podle ID pro lepší přehled
                found_files.sort(key=lambda x: x[1])
                for filename, file_id in found_files[-5:]:  # Zobrazit posledních 5
                    self.log.emit(f"  • {filename} (ID: {file_id:05d})", "info")
                if len(found_files) > 5:
                    self.log.emit(f"  ... a {len(found_files) - 5} dalších", "info")
            
            next_id = max_id + 1
            next_id_str = f"{next_id:05d}"
            
            self.log.emit(f"✅ Nejvyšší nalezené ID: {max_id:05d}", "success")
            self.log.emit(f"🆕 Nové automatické ID: {next_id_str}", "success")
            
            return next_id_str
            
        except Exception as e:
            self.log.emit(f"❌ Chyba při hledání automatického ID: {e}", "error")
            self.log.emit("🔄 Používám výchozí ID: 00001", "warning")
            return "00001"
    
    def generate_cislo_id(self):
        """Generování čísla ID podle nastavení"""
        if self.params.get('auto_generate_id', True):
            # Automatické generování
            output_dir = self.params.get('output_directory', './output')
            id_lokace = self.params.get('id_lokace', '')
            return self.find_next_auto_id(output_dir, id_lokace)
        else:
            # Ruční zadání
            manual_id = self.params.get('manual_cislo_id', '00001')
            # Zajištění 5-místného formátu
            try:
                id_num = int(manual_id)
                return f"{id_num:05d}"
            except ValueError:
                self.log.emit(f"⚠️ Neplatné ruční ID '{manual_id}', používám 00001", "warning")
                return "00001"

    def save_image_with_gps_metadata(self, image, output_path, lat, lon, coordinate_mode, dpi, additional_metadata=None):
        """Uložení obrázku s GPS metadaty"""
        # Příprava PNG info
        pnginfo = PngInfo()
        
        # Základní metadata
        pnginfo.add_text("GPS_Latitude", f"{lat:.8f}")
        pnginfo.add_text("GPS_Longitude", f"{lon:.8f}")
        pnginfo.add_text("GPS_Source", coordinate_mode)
        pnginfo.add_text("Creation_Date", time.strftime("%Y-%m-%d %H:%M:%S"))
        pnginfo.add_text("Generator", f"{self.params['app_name']} v2.0")
        pnginfo.add_text("Contact", self.params['contact_email'])
        
        # Dodatečná metadata
        if additional_metadata:
            for key, value in additional_metadata.items():
                pnginfo.add_text(key, str(value))
        
        # Uložení
        image.save(output_path, "PNG", dpi=(dpi, dpi), pnginfo=pnginfo)
        
        self.log.emit(f"💾 Soubor uložen: {output_path}", "success")

    def print_osm_attribution(self):
        """Výpis informací o OpenStreetMap"""
        self.log.emit("", "info")
        self.log.emit("=" * 60, "info")
        self.log.emit("🗺️  OPENSTREETMAP ATTRIBUTION", "info")
        self.log.emit("=" * 60, "info")
        self.log.emit("© OpenStreetMap contributors", "info")
        self.log.emit("Data jsou dostupná pod Open Database License", "info")
        self.log.emit("Více informací: https://www.openstreetmap.org/copyright", "info")
        self.log.emit("", "info")
        self.log.emit("Dlaždice poskytuje OpenStreetMap Foundation", "info")
        self.log.emit("Tile usage policy: https://operations.osmfoundation.org/policies/tiles/", "info")
        self.log.emit("=" * 60, "info")