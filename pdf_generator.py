import os
import sys
from PIL import Image, ImageDraw, ImageFont
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from datetime import datetime
import tempfile
import math
import shutil
import re

import concurrent.futures
from functools import partial
import threading

# Registrace HEIF formátu pro PIL
pillow_heif.register_heif_opener()

# --- Thread-safe načítání TTF fontů (FreeType lock) ---
FONT_LOCK = threading.Lock()

from reportlab.pdfbase.pdfmetrics import stringWidth

def draw_arc_text(canvas, text, center_x, center_y, radius, max_width, font_name='DejaVuSans-Bold'):
    """
    Vykreslí text po oblouku směrem po hodinových ručičkách zleva doprava.
    OPRAVA: Posun o 75 stupňů doleva + dodatečný posun o 1% poloměru dolů.
    """
    if not text or not text.strip():
        return
    
    # Dynamické určení velikosti fontu
    font_size = 20
    while font_size > 4:
        try:
            text_width = stringWidth(text, font_name, font_size)
            if text_width <= max_width:
                break
        except:
            font_name = 'Helvetica-Bold'
            text_width = stringWidth(text, font_name, font_size)
            if text_width <= max_width:
                break
        font_size -= 1
    
    #print(f"DEBUG: Dynamická velikost fontu pro '{text}': {font_size}pt")
    
    # Úhly pro směr po hodinových ručičkách zleva doprava
    start_angle_deg = 160   
    end_angle_deg = 20      
    total_angle_deg = start_angle_deg - end_angle_deg
    
    if len(text) <= 1:
        # Jediný znak uprostřed oblouku
        angle_deg = start_angle_deg - total_angle_deg / 2 + 75  # posun o 75°
        angle_rad = math.radians(angle_deg)
        
        x = center_x + radius * math.cos(angle_rad)
        # OPRAVA: Přidán posun o 1% poloměru dolů
        y = center_y + radius * math.sin(angle_rad) - radius * 0.01
        
        canvas.saveState()
        canvas.translate(x, y)
        canvas.rotate(angle_deg - 90)
        try:
            canvas.setFont(font_name, font_size)
        except:
            canvas.setFont('Helvetica-Bold', font_size)
        canvas.setFillColorRGB(0, 0, 0)
        canvas.drawCentredString(0, 0, text)
        canvas.restoreState()
        return
    
    # Větší mezery mezi znaky
    angle_step_deg = total_angle_deg / (len(text) - 1) if len(text) > 1 else 0
    angle_step_deg *= 1.25  # Zvětšení mezer o 25%
    
    # Přepočet začátečního úhlu pro vycentrování rozšířeného textu
    expanded_total_angle = angle_step_deg * (len(text) - 1)
    start_angle_centered = start_angle_deg + (total_angle_deg - expanded_total_angle) / 2
    
    # Posun celého textu o 75 stupňů doleva (40 + 35 stupňů)
    start_angle_centered += 75
    
    for i, char in enumerate(text):
        # Úhel pro vykreslování zleva doprava s většími mezerami
        angle_deg = start_angle_centered - (i * angle_step_deg)
        angle_rad = math.radians(angle_deg)
        
        # Pozice znaku na oblouku
        x = center_x + radius * math.cos(angle_rad)
        # OPRAVA: Přidán posun o 1% poloměru dolů
        y = center_y + radius * math.sin(angle_rad) - radius * 0.01
        
        # Vykreslení znaku
        canvas.saveState()
        canvas.translate(x, y)
        canvas.rotate(angle_deg - 90)
        
        try:
            canvas.setFont(font_name, font_size)
        except:
            canvas.setFont('Helvetica-Bold', font_size)
        
        canvas.setFillColorRGB(0, 0, 0)
        canvas.drawCentredString(0, 0, char)
        canvas.restoreState()
    
    #print(f"DEBUG: Text '{text}' vykreslen s posunem o 75° doleva + 1% dolů")

def _safe_truetype(font_path: str, size: int):
    with FONT_LOCK:
        return ImageFont.truetype(font_path, size)

def parse_gps_from_filename(filename):
    """
    Parsuje GPS souřadnice z názvu souboru lokační mapy

    Podporované formáty:
    1) Nový formát z MapProcessoru:
       ...+GPS{lat}{S/J}+{lon}{V/Z}+Z{zoom}+....png
       Příklad: ...+GPS49.23173S+17.65707V+Z18+00001.png
       Pozn.: S=Sever (kladná šířka), J=Jih (záporná), V=Východ (kladná délka), Z=Západ (záporná)

    2) Původní formát:
       {lat_deg}N{lat_min}_{lon_deg}E{lon_min}
       Příklad: 49N23098_017E65707 -> GPS_Latitude: 49.23098, GPS_Longitude: 17.65707
    """
    try:
        print(f"Parsování GPS z názvu souboru: {filename}")
        base = os.path.basename(filename)

        # 1) Nový formát z MapProcessoru: ...+GPS49.23173S+17.65707V+Z18+...
        #    - podporuje i desetinné čárky
        m2 = re.search(
            r'GPS\\s*([0-9]+(?:[\\.,][0-9]+)?)\\s*([NnSsJj])\\+([0-9]+(?:[\\.,][0-9]+)?)\\s*([EeWwVvZz])',
            base
        )
        if m2:
            lat_str, lat_ref, lon_str, lon_ref = m2.groups()
            lat_val = float(lat_str.replace(',', '.'))
            lon_val = float(lon_str.replace(',', '.'))

            # Určení znamének – české i anglické značky
            # Šířka: J (Jih) vždy záporná; N vždy kladná.
            # 'S' je ve formátu MapProcessoru "Sever" (kladná), v angličtině "South" (záporná).
            # Rozlišíme podle značky délky: pokud používá V/Z, interpretujeme S jako Sever (kladná).
            if lat_ref.upper() == 'J':
                lat_val = -lat_val
            elif lat_ref.upper() == 'N':
                lat_val = abs(lat_val)
            elif lat_ref.upper() == 'S':
                if lon_ref.upper() in ('V', 'Z'):  # české značení
                    lat_val = abs(lat_val)  # Sever
                else:  # anglické 'South'
                    lat_val = -abs(lat_val)

            # Délka: Z/W záporná, V/E kladná
            if lon_ref.upper() in ('Z', 'W'):
                lon_val = -abs(lon_val)
            else:  # 'V' nebo 'E'
                lon_val = abs(lon_val)

            gps_coords = (lat_val, lon_val)
            print(f"GPS souřadnice z názvu souboru (nový formát): {gps_coords}")
            return gps_coords

        # 2) Původní formát: 49N23098_017E65707
        parts = base.split('+')
        if len(parts) < 3:
            print(f"Nedostatek parametrů v názvu souboru (očekáváno 3+, nalezeno {len(parts)})")
        else:
            gps_part = parts[2]
            print(f"GPS část z názvu: {gps_part}")
            pattern = r'(\\d+)N(\\d+)_(\\d+)E(\\d+)'
            match = re.match(pattern, gps_part)
            if match:
                lat_deg, lat_min, lon_deg, lon_min = match.groups()
                lat_deg = int(lat_deg)
                lat_min = int(lat_min)
                lon_deg = int(lon_deg)
                lon_min = int(lon_min)
                print(f"Parsované hodnoty: lat_deg={lat_deg}, lat_min={lat_min}, lon_deg={lon_deg}, lon_min={lon_min}")
                lat_decimal = lat_deg + (lat_min / 100000.0)
                lon_decimal = lon_deg + (lon_min / 100000.0)
                gps_coords = (lat_decimal, lon_decimal)
                print(f"GPS souřadnice z názvu souboru (původní formát): {gps_coords}")
                return gps_coords

        print(f"GPS část neodpovídá očekávaným formátům: {filename}")
        return None
    except Exception as e:
        print(f"Chyba při parsování GPS z názvu souboru: {e}")
        return None
    
def decimal_to_dms_string(decimal_degrees, is_lat):
    """
    Převede desetinné stupně na formátovaný string D° M' S.sss".
    """
    direction = ''
    if is_lat:
        direction = 'N' if decimal_degrees >= 0 else 'S'
    else:
        direction = 'E' if decimal_degrees >= 0 else 'W'
        
    decimal_degrees = abs(decimal_degrees)
    degrees = int(decimal_degrees)
    minutes_float = (decimal_degrees - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    
    return f"{direction} {degrees}° {minutes}' {seconds:.3f}\""

def create_radial_gradient_circle(width, height, center_x, center_y, radius_px):
    """
    Vytvoří overlay s radiálním gradientem - lineární transparence od středu k okraji.
    Střed: 0% transparence (plně viditelný)
    Okraj: 75% transparence (25% viditelnost)
    """
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    
    # Vykreslení pixel po pixelu pro přesný gradient
    for y in range(max(0, int(center_y - radius_px)), min(height, int(center_y + radius_px + 1))):
        for x in range(max(0, int(center_x - radius_px)), min(width, int(center_x + radius_px + 1))):
            # Vzdálenost od středu
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx * dx + dy * dy)
            
            # Pouze pixely uvnitř kruhu
            if distance <= radius_px:
                # Lineární interpolace průhlednosti
                # 0% transparence ve středu = alpha 255 (plně viditelné)
                # 75% transparence na okraju = alpha 64 (25% viditelnost)
                normalized_distance = distance / radius_px  # 0.0 až 1.0
                alpha = int(255 - (normalized_distance * 191))  # 255 až 64
                
                # Nastavení pixelu s gradientní průhledností
                overlay.putpixel((x, y), (128, 128, 128, alpha))
    
    return overlay

def extract_location_gps_center(location_image_path):
    """Extrahuje GPS střed lokace z metadat obrázku lokace nebo z názvu souboru"""
    try:
        image = Image.open(location_image_path)
        exifdata = image.getexif()
        filename = os.path.basename(location_image_path)
        #print(f"Hledám GPS střed v: {filename}")

        # 0) PNG tEXt metadata z MapProcessoru: GPS_Latitude, GPS_Longitude (textové hodnoty)
        try:
            text_meta = getattr(image, 'text', {}) or {}
            info_meta = getattr(image, 'info', {}) or {}
            lat_txt = text_meta.get('GPS_Latitude') or info_meta.get('GPS_Latitude')
            lon_txt = text_meta.get('GPS_Longitude') or info_meta.get('GPS_Longitude')
            if lat_txt is not None and lon_txt is not None:
                lat_val = float(str(lat_txt).replace(',', '.'))
                lon_val = float(str(lon_txt).replace(',', '.'))
                gps_center = (lat_val, lon_val)
                #print(f"GPS střed lokace z PNG meta {gps_center}")
                #print(f"Finální GPS střed lokace: {gps_center}")
                return gps_center
            else:
                print("PNG tEXt metadata GPS_Latitude/GPS_Longitude nenalezena")
        except Exception as meta_err:
            print(f"Chyba při čtení PNG text metadat: {meta_err}")

        # 1) EXIF (HEIC/JPEG) – původní chování
        gps_center = None
        try:
            gps_info = exifdata.get_ifd(34853)  # GPS Info IFD
            if gps_info:
                print(f"Nalezena GPS data lokace v EXIF: {gps_info}")
                if 2 in gps_info and 4 in gps_info:  # GPSLatitude a GPSLongitude
                    lat_dms = gps_info[2]  # GPSLatitude
                    lon_dms = gps_info[4]  # GPSLongitude
                    lat_ref = gps_info.get(1, 'N')  # GPSLatitudeRef
                    lon_ref = gps_info.get(3, 'E')  # GPSLongitudeRef

                    lat_decimal = float(lat_dms[0]) + float(lat_dms[1]) / 60 + float(lat_dms[2]) / 3600
                    lon_decimal = float(lon_dms[0]) + float(lon_dms[1]) / 60 + float(lon_dms[2]) / 3600
                    if lat_ref == 'S':
                        lat_decimal = -lat_decimal
                    if lon_ref == 'W':
                        lon_decimal = -lon_decimal

                    gps_center = (lat_decimal, lon_decimal)
                    print(f"GPS střed lokace z EXIF: {gps_center}")
                else:
                    print("GPS souřadnice nenalezeny v GPS datech lokace")
            else:
                print("GPS data nenalezena v EXIF lokace")
        except Exception as gps_error:
            print(f"Chyba při čtení GPS dat lokace z EXIF: {gps_error}")

        # 2) Fallback: název souboru (nový i původní formát)
        if not gps_center:
            print("GPS střed lokace nenalezen v EXIF/PNG metadatech, zkouším načíst z názvu souboru")
            gps_center = parse_gps_from_filename(filename)
            if gps_center:
                print(f"GPS střed lokace úspěšně načten z názvu souboru: {gps_center}")
            else:
                print("GPS střed lokace se nepodařilo načíst ani z názvu souboru")

        print(f"Finální GPS střed lokace: {gps_center}")
        return gps_center
    except Exception as e:
        print(f"Chyba při extrakci GPS středu z {location_image_path}: {e}")
        return None

def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """Vypočítá vzdálenost mezi dvěma GPS body v metrech pomocí Haversine vzorce"""
    from math import radians, cos, sin, asin, sqrt
    
    # Převod na radiány
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine vzorec
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Poloměr Země v metrech
    earth_radius_m = 6371000
    
    # Vzdálenost v metrech
    distance = earth_radius_m * c
    return distance

def copy_and_rename_clovers(clover_metadata, extended_locations, n, m, cesta_ctyrlistky, output_folder):
    """
    Zkopíruje a přejmenuje obrázky čtyřlístků podle specifikace
    Formát: čísloČtyřlístku+IDlokace+V+M.HEIC
    NOVÉ: Přeskočuje také stav BEZGPS
    """
    if not output_folder:
        print("Žádná výstupní složka pro kopírování čtyřlístků není zadána")
        return

    print(f"\n=== KOPÍROVÁNÍ A PŘEJMENOVÁNÍ ČTYŘLÍSTKŮ ===")
    print(f"Výstupní složka: {output_folder}")
    os.makedirs(output_folder, exist_ok=True)

    if not os.path.exists(cesta_ctyrlistky):
        print(f"CHYBA: Cesta {cesta_ctyrlistky} neexistuje!")
        return

    all_files = os.listdir(cesta_ctyrlistky)
    print(f"Celkem souborů v adresáři: {len(all_files)}")

    total_copied = 0
    total_errors = 0

    for i, metadata in enumerate(clover_metadata):
        # ZMĚNA: Přeskočit záznamy bez fotky, darované, ztracené a bez GPS
        status_val = str(metadata.get('status') or "").upper()
        if status_val in ["BEZFOTKY", "DAROVANY", "ZTRACENY", "BEZGPS"]:  # NOVÉ: Přidán BEZGPS
            print(f"Přeskakuji {metadata['number']} ({status_val})")
            continue

        clover_number = metadata['number']
        location_id = extended_locations[i]

        print(f"Kopíruji čtyřlístek {i+1}/{len(clover_metadata)}: {clover_number}")

        source_path = None
        original_filename = None

        for filename in all_files:
            if filename.startswith(f"{clover_number}+") and filename.lower().endswith((".heic", ".jpg", ".jpeg", ".png")):
                source_path = os.path.join(cesta_ctyrlistky, filename)
                original_filename = filename
                break

        if not source_path:
            print(f" ✗ CHYBA: Soubor pro čtyřlístek {clover_number} nenalezen")
            total_errors += 1
            continue

        location_id_padded = f"{location_id:03d}"
        new_filename = f"{clover_number}+{location_id_padded}+V+M.HEIC"
        destination_path = os.path.join(output_folder, new_filename)

        print(f" Zdroj: {original_filename}")
        print(f" Cíl: {new_filename}")

        try:
            if not os.path.exists(source_path):
                print(f" ✗ CHYBA: Zdrojový soubor neexistuje: {source_path}")
                total_errors += 1
                continue

            shutil.copy2(source_path, destination_path)
            print(f" ✓ Úspěšně zkopírováno")
            total_copied += 1

        except Exception as e:
            print(f" ✗ CHYBA při kopírování: {e}")
            total_errors += 1

    print(f"\n=== SHRNUTÍ KOPÍROVÁNÍ ===")
    print(f"Úspěšně zkopírováno: {total_copied} souborů")
    print(f"Chyby: {total_errors} souborů")
    print(f"Celkem zpracováno: {len(clover_metadata)} souborů")
    if total_copied > 0:
        print(f"Zkopírované soubory jsou uloženy v: {output_folder}")

def find_files_recursive(directory, target_id):
    """Rekurzivně najde soubor s daným ID pomocí os.scandir - oddělovač +"""
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.endswith(".png"):
                # Zpracuje soubor
                filename_without_ext = os.path.splitext(entry.name)[0]
                parts = filename_without_ext.split('+')  # Změna z '_' na '+'
                
                if len(parts) > 0:
                    try:
                        file_location_id = int(parts[-1])
                        if file_location_id == target_id:
                            return entry.path
                    except ValueError:
                        continue
            
            elif entry.is_dir():
                # Rekurzivně prohledá podsložku
                result = find_files_recursive(entry.path, target_id)
                if result:
                    return result
    except PermissionError:
        print(f"Nemám oprávnění pro přístup do složky: {directory}")
    
    return None

def load_location_images(seznam_lokaci, def_cesta_lokaci):
    """Načte obrázky lokací podle seznamu ID - rychlá verze s + oddělovačem"""
    location_images = []
    location_gps_centers = []  # ZMĚNA: Seznam GPS středů místo hranic
    
    #print(f"Hledám lokace v cestě: {def_cesta_lokaci}")
    
    if not os.path.exists(def_cesta_lokaci):
        print(f"CHYBA: Cesta {def_cesta_lokaci} neexistuje!")
        for i in range(len(seznam_lokaci)):
            blank_img = Image.new('RGB', (827, 602), 'white')
            location_images.append(blank_img)
            location_gps_centers.append(None)  # ZMĚNA
        return location_images, location_gps_centers  # ZMĚNA
    
    for i, id_lokace in enumerate(seznam_lokaci):
        #print(f"Hledám lokaci s ID: {id_lokace}")
        
        filepath = find_files_recursive(def_cesta_lokaci, id_lokace)
        
        if filepath:
            relative_path = os.path.relpath(filepath, def_cesta_lokaci)
            #print(f"Nalezen soubor lokace: {relative_path} (ID: {id_lokace})")
            try:
                img = Image.open(filepath)
                location_images.append(img)
                
                # ZMĚNA: Extrahuje GPS střed z obrázku lokace
                gps_center = extract_location_gps_center(filepath)
                location_gps_centers.append(gps_center)
                
            except Exception as e:
                print(f"Chyba při načítání lokace {os.path.basename(filepath)}: {e}")
                blank_img = Image.new('RGB', (827, 602), 'white')
                location_images.append(blank_img)
                location_gps_centers.append(None)  # ZMĚNA
        else:
            print(f"Lokace s ID {id_lokace} nenalezena ani v podsložkách, vytvářím prázdný obrázek")
            blank_img = Image.new('RGB', (827, 602), 'white')
            location_images.append(blank_img)
            location_gps_centers.append(None)  # ZMĚNA
    
    return location_images, location_gps_centers  # ZMĚNA

def check_gps_within_bounds(clover_gps, location_bounds):
    """Zkontroluje, zda GPS souřadnice čtyřlístku spadají do hranic mapy lokace"""
    if not clover_gps or not location_bounds:
        print("Chybí GPS data pro kontrolu")
        return False
    
    lat, lon = clover_gps
    min_lat, min_lon, max_lat, max_lon = location_bounds
    
    print(f"Kontroluji: lat={lat:.6f} ({min_lat} <= {lat:.6f} <= {max_lat})")
    print(f"Kontroluji: lon={lon:.6f} ({min_lon} <= {lon:.6f} <= {max_lon})")
    
    # Jednoduchá kontrola obdélníkových hranic
    within_bounds = (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon)
    print(f"Výsledek kontroly: {within_bounds}")
    
    return within_bounds

def extract_gps_and_time(image_path):
    """Extrahuje GPS souřadnice a čas vytvoření z HEIC souboru"""
    try:
        image = Image.open(image_path)
        exifdata = image.getexif()
        
        gps_coords = None
        creation_time = None
        
        #print(f"Zpracovávám metadata pro: {os.path.basename(image_path)}")
        
        # Extrakce času vytvoření - zkusí různé tagy
        time_tags = [36867, 36868, 306]  # DateTimeOriginal, DateTimeDigitized, DateTime
        for tag in time_tags:
            if tag in exifdata:
                creation_time = exifdata[tag]
                #print(f"Nalezen čas v tagu {tag}: {creation_time}")
                break
        
        if not creation_time:
            print("Čas vytvoření nenalezen v EXIF datech")
        
        # Extrakce GPS dat
        try:
            gps_info = exifdata.get_ifd(34853)  # GPS Info IFD
            if gps_info:
                #print(f"Nalezena GPS data: {gps_info}")
                
                # Získá GPS souřadnice
                if 2 in gps_info and 4 in gps_info:  # GPSLatitude a GPSLongitude
                    lat_dms = gps_info[2]  # GPSLatitude
                    lon_dms = gps_info[4]  # GPSLongitude
                    lat_ref = gps_info.get(1, 'N')  # GPSLatitudeRef
                    lon_ref = gps_info.get(3, 'E')  # GPSLongitudeRef
                    
                    # Převod DMS na desetinné stupně - OPRAVA pro Fraction objekty
                    if isinstance(lat_dms[0], tuple):
                        lat_decimal = float(lat_dms[0]) + float(lat_dms[1])/60 + float(lat_dms[2])/3600
                        lon_decimal = float(lon_dms[0]) + float(lon_dms[1])/60 + float(lon_dms[2])/3600
                    else:
                        # Pro Fraction objekty
                        lat_decimal = float(lat_dms[0]) + float(lat_dms[1])/60 + float(lat_dms[2])/3600
                        lon_decimal = float(lon_dms[0]) + float(lon_dms[1])/60 + float(lon_dms[2])/3600
                    
                    if lat_ref == 'S':
                        lat_decimal = -lat_decimal
                    if lon_ref == 'W':
                        lon_decimal = -lon_decimal
                    
                    gps_coords = (lat_decimal, lon_decimal)
                    #print(f"GPS souřadnice (desetinné): {gps_coords}")
                else:
                    print("GPS souřadnice nenalezeny v GPS datech")
            else:
                print("GPS data nenalezena v EXIF")
        except Exception as gps_error:
            print(f"Chyba při čtení GPS dat: {gps_error}")
        
        return gps_coords, creation_time
        
    except Exception as e:
        print(f"Chyba při extrakci metadat z {image_path}: {e}")
        return None, None

def load_clover_images_range(n, m, cesta_ctyrlistky, status_dict=None):
    """Načte obrázky čtyřlístků v rozsahu N až M, s podporou stavu BEZFOTKY, DAROVANY, ZTRACENY a BEZGPS."""
    clover_images = []
    clover_metadata = []
    total_images = m - n + 1

    print(f"Rozsah: {n} až {m} (celkem {total_images} obrázků)")

    # Cesta k placeholderu pouze pro BEZFOTKY
    placeholder_bezfotky = os.path.join(os.path.dirname(__file__), "BEZ_FOTKY.png")

    # Pokud zdrojová složka neexistuje, vyrob prázdné obrázky
    if not os.path.exists(cesta_ctyrlistky):
        print(f"CHYBA: Cesta {cesta_ctyrlistky} neexistuje!")
        for i in range(total_images):
            image_number = n + i
            status_val = str(status_dict.get(image_number, '')).upper() if status_dict else ''

            if status_val == "BEZFOTKY":
                try:
                    img = Image.open(placeholder_bezfotky)
                except Exception:
                    img = Image.new('RGB', (236, 236), 'gray')
                clover_images.append(img)
                clover_metadata.append({'number': image_number, 'gps': None, 'time': None, 'status': 'BEZFOTKY'})
            else:
                blank_img = Image.new('RGB', (236, 236), 'green')
                clover_images.append(blank_img)
                metadata = {'number': image_number, 'gps': None, 'time': None}
                # OPRAVA: Přidat status i pro ostatní stavy včetně BEZGPS
                if status_val:
                    metadata['status'] = status_val
                clover_metadata.append(metadata)
        return clover_images, clover_metadata

    all_files = os.listdir(cesta_ctyrlistky)
    print(f"Celkem souborů v adresáři: {len(all_files)}")

    for i in range(total_images):
        image_number = n + i
        status_val = str(status_dict.get(image_number, '')).upper() if status_dict else ''

        # OPRAVA: Pouze BEZFOTKY používá placeholder, BEZGPS používá normální fotku
        if status_val == "BEZFOTKY":
            try:
                img = Image.open(placeholder_bezfotky)
            except Exception:
                img = Image.new('RGB', (236, 236), 'gray')
            clover_images.append(img)
            clover_metadata.append({'number': image_number, 'gps': None, 'time': None, 'status': 'BEZFOTKY'})
            continue

        # Hledání normálního souboru (včetně DAROVANY, ZTRACENY, BEZGPS)
        found = False
        for filename in all_files:
            if filename.startswith(f"{image_number}+") and filename.lower().endswith((".heic", ".jpg", ".jpeg", ".png")):
                filepath = os.path.join(cesta_ctyrlistky, filename)
                try:
                    img = Image.open(filepath)
                    clover_images.append(img)
                    gps_coords, creation_time = extract_gps_and_time(filepath)
                    
                    metadata = {'number': image_number, 'gps': gps_coords, 'time': creation_time}
                    
                    # NOVÉ: Pro BEZGPS nastavit GPS na None (bude se zobrazovat s otazníky)
                    if status_val == "BEZGPS":
                        metadata['gps'] = None
                    
                    # Přidat status pro všechny stavy včetně BEZGPS
                    if status_val:
                        metadata['status'] = status_val
                    clover_metadata.append(metadata)
                    found = True
                    break
                except Exception as e:
                    print(f"Chyba při načítání čtyřlístku {filename}: {e}")

        if not found:
            print(f"Čtyřlístek s číslem {image_number} nenalezen, vytvářím prázdný obrázek")
            blank_img = Image.new('RGB', (236, 236), 'green')
            clover_images.append(blank_img)
            metadata = {'number': image_number, 'gps': None, 'time': None}
            if status_val:
                metadata['status'] = status_val
            clover_metadata.append(metadata)

    print(f"Načteno celkem {len(clover_images)} čtyřlístků")
    return clover_images, clover_metadata

def get_pixel_to_meter_ratio(latitude, zoom):
    """
    Vypočítá poměr metrů na pixel pro danou zeměpisnou šířku a úroveň přiblížení.
    Používá standardní vzorec pro Web Mercator projekci.
    """
    try:
        lat_rad = math.radians(latitude)
        # Konstanta 156543.03 je odvozena od obvodu Země na rovníku / 256 pixelů
        meters_per_pixel = 156543.03 * math.cos(lat_rad) / (2 ** zoom)
        return meters_per_pixel
    except Exception:
        return 1.0 # Fallback

def point_to_segment_dist(p, a, b):
    """
    Vypočítá nejkratší vzdálenost bodu 'p' od úsečky 'ab' v pixelech.
    """
    px, py = p
    ax, ay = a
    bx, by = b

    abx, aby = bx - ax, by - ay
    ab2 = abx**2 + aby**2
    if ab2 == 0:
        return math.hypot(px - ax, py - ay)
        
    t = ((px - ax) * abx + (py - ay) * aby) / ab2
    t = max(0, min(1, t))
    
    closest_x = ax + t * abx
    closest_y = ay + t * aby
    
    return math.hypot(px - closest_x, py - closest_y)

def point_to_polygon_dist(point, polygon_points):
    """
    Najde nejkratší vzdálenost od bodu k hraně polygonu v pixelech.
    """
    min_dist = float('inf')
    if len(polygon_points) < 2:
        return min_dist

    for i in range(len(polygon_points)):
        p1 = polygon_points[i]
        p2 = polygon_points[(i + 1) % len(polygon_points)]
        
        dist = point_to_segment_dist(point, p1, p2)
        if dist < min_dist:
            min_dist = dist
            
    return min_dist

# Soubor: pdf_generator.py

def format_deviation_value(distance):
    """
    Formátuje POUZE HODNOTU odchylky s dynamickou přesností na desetinná místa.
    """
    if distance < 10.0:
        return f"{distance:.3f} m"
    elif distance < 100.0:
        return f"{distance:.2f} m"
    else:
        return f"{distance:.1f} m"
    
def combine_images(location_img, clover_img, metadata, id_lokace, poznamky_dict=None, location_gps_center=None):
    """
    Finální verze: Připraví podkladový obrázek a vrátí jej spolu se seznamem textů
    k vykreslení, s upravenou pozicí, sjednocenými fonty a finální barvou pozadí.
    NOVÉ: Podpora pro stav BEZGPS s automatickou poznámkou.
    """
    from PIL import Image, ImageDraw
    from datetime import datetime
    import os

    base_w, base_h = 1063, 602
    combined = Image.new('RGB', (base_w, base_h), 'white')

    # Podklad a rozložení (zůstává z aktuální verze)
    text_area_bg_color = (207, 236, 184)
    clover_y_start = base_h - 236

    draw_combined = ImageDraw.Draw(combined)
    draw_combined.rectangle([0, 0, 236, clover_y_start - 1], fill=text_area_bg_color)

    orig_w, orig_h = location_img.size
    location_resized = location_img.resize((827, base_h), Image.Resampling.LANCZOS).convert("RGBA")
    clover_resized = clover_img.resize((236, 236), Image.Resampling.LANCZOS)

    location_x = base_w - 827
    combined.paste(clover_resized, (0, clover_y_start))
    overlay = Image.new('RGBA', location_resized.size, (0, 0, 0, 0))

    # Metadata a výpočty
    zoom_level = None
    try:
        text_meta = getattr(location_img, 'text', {}) or {}
        ztxt = text_meta.get('Zoom_Level')
        if ztxt: zoom_level = int(str(ztxt).strip())
    except Exception: pass

    clover_gps = metadata.get('gps')
    poly_meta = read_polygon_metadata(location_img)

    texts_to_draw = []
    COLOR_OK, COLOR_WARN, COLOR_ERR = (0, 128/255, 0), (1, 165/255, 0), (1, 0, 0)
    gps_text_color = (0, 0, 0)
    deviation_value_text = ""

    status_val = str(metadata.get('status') or "").upper()

    # NOVÉ: Zpracování automatických poznámek pro speciální stavy
    if status_val == "BEZGPS":
        # GPS souřadnice s otazníky (stejně jako BEZFOTKY)
        lat_text = "N ??° ??' ??.??\""
        lon_text = "E ??° ??' ??.??\""

        # Automatická poznámka pro BEZGPS
        default_note = "Fotka byla vyfocena bez GPS souřadnic"
        if poznamky_dict is None:
            poznamky_dict = {}
        if metadata['number'] not in poznamky_dict:
            poznamky_dict[metadata['number']] = default_note

    elif status_val == "ZTRACENY":
        # NOVÉ: Automatická poznámka pro ZTRACENY (vždy přepíše uživatelskou)
        default_note = "Ztracený ☹️"
        if poznamky_dict is None:
            poznamky_dict = {}
        # Vždy nastavit automatickou poznámku pro ZTRACENY
        poznamky_dict[metadata['number']] = default_note

    elif status_val == "BEZFOTKY":
        lat_text = "N ??° ??' ??.??\""
        lon_text = "E ??° ??' ??.??\""
    else:
        lat_text = "Chybí GPS data"
        lon_text = ""

    clover_px, clover_py = None, None # Inicializace

    # NOVÉ: Pro BEZGPS zpracovat lokaci a mapu normálně, ale GPS zobrazit s otazníky
    if clover_gps and location_gps_center and zoom_level and status_val != "BEZGPS":
        clover_lat, clover_lon = clover_gps
        map_lat, map_lon = location_gps_center

        lat_text = decimal_to_dms_string(clover_lat, is_lat=True)
        lon_text = decimal_to_dms_string(clover_lon, is_lat=False)

        clover_px, clover_py = gps_to_pixel(clover_lat, clover_lon, map_lat, map_lon, zoom_level, orig_w, orig_h)

        is_on_map = (0 <= clover_px < orig_w) and (0 <= clover_py < orig_h)
        has_poly = bool(poly_meta and isinstance(poly_meta.get('points'), list) and len(poly_meta['points']) >= 3)

        if has_poly:
            dist_m = point_to_polygon_dist((clover_px, clover_py), poly_meta['points']) * get_pixel_to_meter_ratio(map_lat, zoom_level)
            is_in_poly = is_point_in_polygon(clover_px, clover_py, poly_meta['points']) or dist_m == 0.0

            if not is_in_poly: deviation_value_text = format_deviation_value(dist_m)
            gps_text_color = COLOR_OK if is_in_poly else (COLOR_WARN if is_on_map else COLOR_ERR)
        else:
            distance = calculate_distance_meters(map_lat, map_lon, clover_lat, clover_lon)
            deviation_value_text = format_deviation_value(distance)
            gps_text_color = COLOR_ERR if not is_on_map else (COLOR_WARN if distance > 5.0 else COLOR_OK)

            # Přidání gradientu pro mapy bez polygonu
            try:
                meters_per_pixel = get_pixel_to_meter_ratio(map_lat, zoom_level)
                radius_px = 5.0 / max(meters_per_pixel, 1e-9)
                center_x, center_y = overlay.width / 2.0, overlay.height / 2.0
                gradient_overlay = create_radial_gradient_circle(overlay.width, overlay.height, center_x, center_y, radius_px)
                overlay = gradient_overlay
            except Exception as e:
                print(f"CHYBA: Nepodařilo se vytvořit gradientní kruh: {e}")

    # NOVÉ: Pro BEZGPS stále zobrazit mapu a značku, ale GPS text s otazníky
    elif status_val == "BEZGPS" and location_gps_center and zoom_level:
        # Zobrazit mapu normálně, ale GPS souřadnice už jsou nastaveny s otazníky výše
        pass

    # Sloučení vrstev mapy s overlay
    location_resized.alpha_composite(overlay)
    combined.paste(location_resized, (location_x, 0), mask=location_resized)

    # Vykreslení značky čtyřlístku (pokud je GPS dostupné a není BEZGPS)
    if clover_gps and location_gps_center and zoom_level and clover_px is not None and status_val not in ["BEZFOTKY", "BEZGPS"]:
        try:
            px_final_x = location_x + (clover_px * (827.0 / orig_w))
            px_final_y = (clover_py * (602.0 / orig_h))

            if (location_x <= px_final_x < base_w) and (0 <= px_final_y < base_h):
                size = 6
                dark_green = (0, 100, 0)
                for off_x, off_y in [(-size,0),(size,0),(0,-size),(0,size)]:
                    draw_combined.ellipse([px_final_x+off_x-size, px_final_y+off_y-size,
                                         px_final_x+off_x+size, px_final_y+off_y+size], fill=dark_green)
                draw_combined.ellipse([px_final_x-(7//2), px_final_y-(7//2),
                                     px_final_x+(7//2)+1, px_final_y+(7//2)+1],
                                    fill=(0,255,0), outline='black', width=1)
        except Exception as e:
            print(f"CHYBA: Nepodařilo se vykreslit značku čtyřlístku: {e}")

    # Příprava textů pro pozdější vykreslení
    font_size_gps = 22

    lines = []
    if status_val not in ["BEZFOTKY", "BEZGPS"] and deviation_value_text:
        lines.append(("Odchylka:", 0))
        lines.append((deviation_value_text, 20))

    lines.append((lat_text, 0))
    if lon_text:
        lines.append((lon_text, 0))

    total_text_height = len(lines) * font_size_gps * 1.15
    y_start_text = clover_y_start - total_text_height - 4

    for text, indent in lines:
        texts_to_draw.append({'text': text, 'pos': (8 + indent, y_start_text), 'font': 'DejaVuSans', 'size': font_size_gps, 'color': gps_text_color, 'align': 'left'})
        y_start_text += font_size_gps * 1.15

    number_text = f"{metadata['number']}."
    texts_to_draw.append({'text': number_text, 'pos': (118, 20), 'font': 'DejaVuSans-Bold', 'size': 58, 'color': (0,0,0), 'align': 'center'})

    font_size_time = 26
    font_size_note = 22
    font_time_note = 'DejaVuSans-Bold'

    # Zpracování data a poznámek
    if metadata.get('time'):
        try:
            dt = datetime.strptime(metadata['time'], "%Y:%m:%d %H:%M:%S")
            dny = ['pondělí','úterý','středa','čtvrtek','pátek','sobota','neděle']
            mesice = ['ledna','února','března','dubna','května','června','července','srpna','září','října','listopadu','prosince']
            time_text = f"{dny[dt.weekday()]} {dt.day}. {mesice[dt.month - 1]} {dt.year} v {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
            texts_to_draw.append({'text': time_text, 'pos': (base_w - 15, 10), 'font': font_time_note, 'size': font_size_time, 'color': (0,0,0), 'align': 'right'})

            # Poznámky s automatickým zpracováním
            if poznamky_dict and metadata['number'] in poznamky_dict:
                note_text = poznamky_dict[metadata['number']]
                if status_val in ["BEZGPS", "BEZFOTKY"]:
                    # Pro BEZGPS a BEZFOTKY poznámka pod datum a čas vpravo nahoře
                    texts_to_draw.append({'text': note_text, 'pos': (base_w - 15, 10 + font_size_time + 5), 'font': font_time_note, 'size': font_size_note, 'color': (0,0,0), 'align': 'right'})
                elif status_val not in ["DAROVANY", "ZTRACENY"]:
                    # Pro ostatní stavy poznámka dole vlevo
                    texts_to_draw.append({'text': note_text, 'pos': (base_w - 15, 10 + font_size_time + 5), 'font': font_time_note, 'size': font_size_note, 'color': (0,0,0), 'align': 'right'})

        except Exception:
            pass

    elif poznamky_dict and metadata['number'] in poznamky_dict:
        note_text = poznamky_dict[metadata['number']]
        if status_val in ["BEZFOTKY", "BEZGPS"]:
            # Pro BEZFOTKY a BEZGPS nahoře vpravo
            texts_to_draw.append({'text': note_text, 'pos': (base_w - 15, 10), 'font': font_time_note, 'size': font_size_note, 'color': (0,0,0), 'align': 'right'})
        elif status_val not in ["DAROVANY", "ZTRACENY"]:
            # Pro všechny ostatní stavy (včetně prázdného stavu) dole vlevo
            texts_to_draw.append({'text': note_text, 'pos': (236 + 15, base_h - 15 - font_size_note), 'font': font_time_note, 'size': font_size_note, 'color': (0,0,0), 'align': 'left'})


    # === Přidání NICKNAME overlay (minimální změna, po kombinování) ===
    try:
        _nick_path = "/Users/safronus/Library/Mobile Documents/com~apple~CloudDocs/Čtyřlístky/Generování PDF/Skripty/NICKNAME.png"
        if os.path.exists(_nick_path):
            nick = Image.open(_nick_path).convert("RGBA")
            # Omezíme velikost pro levý sloupec (šířka 236 px) a horní textovou oblast (výška clover_y_start)
            max_w = int(236 * 0.9)
            max_h = int(clover_y_start * 0.5)
            scale = min(max_w / nick.width, max_h / nick.height, 1.0)
            new_size = (max(1, int(nick.width * scale)), max(1, int(nick.height * scale)))
            if new_size[0] != nick.width or new_size[1] != nick.height:
                nick = nick.resize(new_size, Image.LANCZOS)

            # Vycentrování v levém sloupci nad fotkou (horní textová zóna)
            x_left = (236 - nick.width) // 2
            y_top  = max(0, (clover_y_start - nick.height) // 2)
            combined.paste(nick, (x_left, y_top), nick)
    except Exception:
        # Tichý fallback – nechceme zablokovat generování kvůli volitelnému overlayi
        pass

    return combined, texts_to_draw

import pillow_heif
import json

# Registrace HEIF formátu pro PIL
pillow_heif.register_heif_opener()

# --- NOVÉ POMOCNÉ FUNKCE (převzaté a upravené z map_processor.py) ---

def read_polygon_metadata(image_obj):
    """
    Načte metadata polygonu z PIL objektu obrázku.
    Vrací dict nebo None.
    """
    try:
        text_meta = getattr(image_obj, 'text', {}) or {}
        raw = text_meta.get('AOI_POLYGON')
        if not raw:
            info_meta = getattr(image_obj, 'info', {}) or {}
            raw = info_meta.get('AOI_POLYGON')
        
        if not raw:
            return None
            
        data = json.loads(raw)
        if isinstance(data.get('points'), list) and len(data['points']) >= 3:
            return data
    except Exception:
        return None
    return None

def is_point_in_polygon(x, y, polygon_points):
    """
    Zjistí, zda je bod uvnitř daného polygonu pomocí Ray Casting algoritmu.
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

def gps_to_pixel(target_lat, target_lon, center_lat, center_lon, zoom, map_width_px, map_height_px):
    """
    Převede GPS souřadnice na pixelové souřadnice na finální vycentrované mapě.
    """
    def deg2num(lat_deg, lon_deg, zoom):
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = (lon_deg + 180.0) / 360.0 * n
        ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        return (xtile, ytile)

    center_tile_x, center_tile_y = deg2num(center_lat, center_lon, zoom)
    target_tile_x, target_tile_y = deg2num(target_lat, target_lon, zoom)

    pixel_dx = (target_tile_x - center_tile_x) * 256 # TILE_SIZE
    pixel_dy = (target_tile_y - center_tile_y) * 256 # TILE_SIZE

    pixel_x = (map_width_px / 2) + pixel_dx
    pixel_y = (map_height_px / 2) + pixel_dy
    return pixel_x, pixel_y

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import tempfile
import os
import math

def create_multipage_pdf(all_images_data, output_path, progress_callback=None):
    """
    Finální verze: Vytvoří PDF pomocí ReportLab s podporou diakritiky,
    správnou tloušťkou rámečku a pozicí textu.
    OPRAVA: Menší darovaný obrázek a text.
    """
    if not all_images_data:
        return

    try:
        pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('LiberationSerif', 'LiberationSerif-Regular.ttf'))
    except Exception as e:
        print(f"Chyba při registraci fontu: {e}. Ujistěte se, že máte soubory .ttf ve složce projektu.")

    page_w_pt, page_h_pt = A4
    margin_pt = (5 / 25.4) * 72
    content_w_pt = page_w_pt - (2 * margin_pt)
    content_h_pt = page_h_pt - (2 * margin_pt)

    images_per_page = 5
    rows, cols = 5, 2

    cell_w_pt = content_w_pt / cols
    cell_h_pt = content_h_pt / rows

    c = canvas.Canvas(output_path, pagesize=A4)

    total_pages = math.ceil(len(all_images_data) / images_per_page)

    # Cesty k obrázkům podle stavů
    darovany_image_path = os.path.join(os.path.dirname(__file__), "DAROVANY.png")
    ztraceny_image_path = os.path.join(os.path.dirname(__file__), "ZTRACENY.png")
    
    #print(f"DEBUG: Cesta k obrázku DAROVANY: {darovany_image_path}")
    #print(f"DEBUG: Cesta k obrázku ZTRACENY: {ztraceny_image_path}")
    #print(f"DEBUG: DAROVANY obrázek existuje: {os.path.exists(darovany_image_path)}")
    #print(f"DEBUG: ZTRACENY obrázek existuje: {os.path.exists(ztraceny_image_path)}")

    for page_idx in range(total_pages):
        page_images_data = all_images_data[page_idx * images_per_page : (page_idx + 1) * images_per_page]
        #print(f"DEBUG: Stránka {page_idx + 1}, počet obrázků: {len(page_images_data)}")
        
        # Debug výpis všech obrázků na stránce
        for i, (img_obj, texts, metadata) in enumerate(page_images_data):
            status = metadata.get('status', 'NORMAL')
            number = metadata.get('number', '?')
            note = metadata.get('note', '')
            #print(f"DEBUG: Pozice {i}: číslo {number}, stav '{status}', poznámka '{note}'")

        # 1. Vykreslení všech hlavních obrázků a textů
        for i, (img_obj, texts, metadata) in enumerate(page_images_data):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
                img_obj.save(temp_img, format='PNG')
                temp_img_path = temp_img.name

            row = i
            col = 0 if (page_idx % 2 == 0 and row % 2 == 0) or \
                     (page_idx % 2 != 0 and row % 2 != 0) else 1

            x_pt = margin_pt + (col * cell_w_pt)
            y_pt = page_h_pt - margin_pt - ((row + 1) * cell_h_pt)

            # Vykreslení hlavního obrázku
            c.drawImage(temp_img_path, x_pt, y_pt, width=cell_w_pt, height=cell_h_pt, mask='auto')
            os.remove(temp_img_path)

            # Vykreslení textů pro hlavní obrázek
            for text_info in texts:
                tx, ty_pil = text_info['pos']
                text_x_rel = tx / 1063
                text_y_rel = ty_pil / 602

                text_x = x_pt + text_x_rel * cell_w_pt
                text_y = y_pt + cell_h_pt - (text_y_rel * cell_h_pt) - (text_info['size'] * 0.2)

                font_name = text_info.get('font', 'DejaVuSans')
                font_size = text_info['size'] * (cell_h_pt / 602)

                try:
                    c.setFont(font_name, font_size)
                except:
                    c.setFont('Helvetica', font_size)

                c.setFillColorRGB(*text_info['color'])

                align = text_info.get('align', 'left')
                if align == 'center':
                    c.drawCentredString(text_x, text_y, text_info['text'])
                elif align == 'right':
                    c.drawRightString(text_x, text_y, text_info['text'])
                else:
                    c.drawString(text_x, text_y, text_info['text'])

        # 2. Vykreslení darovaných/ztracených obrázků do vedlejších sloupců
        for i, (img_obj, texts, metadata) in enumerate(page_images_data):
            status_val = str(metadata.get('status', '')).upper()
            if status_val in ["DAROVANY", "ZTRACENY"]:

                row = i
                col = 0 if (page_idx % 2 == 0 and row % 2 == 0) or \
                         (page_idx % 2 != 0 and row % 2 != 0) else 1
        
                # Pozice pro darovaný obrázek (vedlejší sloupec)
                donation_col = 1 - col
                donation_x_pt = margin_pt + (donation_col * cell_w_pt)
                donation_y_pt = page_h_pt - margin_pt - ((row + 1) * cell_h_pt)
        
                #print(f"DEBUG: Vykresluju obrázek pro číslo {metadata.get('number')} (stav: {status_val})")
                
                # Výběr správného obrázku podle stavu
                if status_val == "DAROVANY":
                    current_image_path = darovany_image_path
                    image_exists = os.path.exists(darovany_image_path)
                    image_name = "DAROVANY.png"
                elif status_val == "ZTRACENY":
                    current_image_path = ztraceny_image_path
                    image_exists = os.path.exists(ztraceny_image_path)
                    image_name = "ZTRACENY.png"
                else:
                    current_image_path = None
                    image_exists = False
                    image_name = "neznámý"
                
                if image_exists and current_image_path:
                    try:

                        # Čtvercový obrázek s 10% okrajem nahoře a dole
                        margin_vertical = cell_h_pt * 0.1  # 10% výšky buňky
                        donation_size = cell_h_pt - (2 * margin_vertical)  # 80% výšky, čtvercový
                        
                        # Vycentrovat horizontálně i vertikálně
                        donation_x_centered = donation_x_pt + (cell_w_pt - donation_size) / 2
                        # OPRAVA: Posun celého obrázku o 5% dolů
                        donation_y_centered = donation_y_pt + margin_vertical - (donation_size * 0.05)
                        
                        # Vložení obrázku podle stavu
                        c.drawImage(current_image_path, donation_x_centered, donation_y_centered,
                                  width=donation_size, height=donation_size, mask='auto')
                        
                        #print(f"DEBUG: Čtvercový {image_name} obrázek vložen s posunem 5% dolů ({donation_size:.1f}x{donation_size:.1f} pt)")

    
                        
                         # NOVÁ LOGIKA: Obloukový text poznámky NAD obrázkem
                        note_text = None
                        if metadata.get('note'):
                            note_text = str(metadata['note'])
                        elif status_val == "ZTRACENY":
                            # NOVÉ: Defaultní text pro ztracené čtyřlístky
                            note_text = "Ztracený ☹️☹️☹️"
                        elif status_val == "DAROVANY":
                            # NOVÉ: Můžete přidat i defaultní text pro darované, pokud chcete
                            # note_text = "Darovaný"
                            pass
                        
                        if note_text:
                            # Střed oblouku posunut o 3% doprava
                            horizontal_shift = cell_w_pt * 0.0 # 3% doprava
                            center_x = donation_x_centered + (donation_size / 2) + horizontal_shift
                            center_y = donation_y_centered + donation_size * 0.50 # Pozice textu relativní k obrázku
                            
                            # Zvětšený poloměr pro lepší rozložení písmen
                            radius = donation_size * 0.5
                            
                            # Maximální šířka textu (80% šířky buňky)
                            max_width = cell_w_pt * 0.8
                            
                            #print(f"DEBUG: Vykresluju obloukový text: '{note_text}'")
                            
                            # Vykreslení textu po oblouku
                            draw_arc_text(c, note_text, center_x, center_y, radius, max_width)

                    except Exception as e:
                        print(f"CHYBA: Při vkládání {image_name} obrázku: {e}")
                else:
                    print(f"CHYBA: Soubor {current_image_path or image_name} neexistuje")

        # 3. Vykreslení rámečku (jako vrchní vrstva)
        border_color_rl = (0, 100/255, 0)
        c.setStrokeColorRGB(*border_color_rl)
        c.setLineWidth(2)
        c.rect(margin_pt, margin_pt, content_w_pt, content_h_pt)

        # 4. Dokončení stránky
        c.showPage()

        if progress_callback:
            progress_callback(page_idx + 1, total_pages)

    c.save()
    #print(f"DEBUG: PDF uloženo do: {output_path}")

def generate_location_list(total_images, seznam_lokaci):
    """Vygeneruje seznam lokací pro všechny obrázky"""
    if not seznam_lokaci:
        return [1] * total_images  # Výchozí lokace 1
    
    # Opakuje seznam lokací dokud nepokryje všechny obrázky
    extended_list = []
    while len(extended_list) < total_images:
        remaining = total_images - len(extended_list)
        if remaining >= len(seznam_lokaci):
            extended_list.extend(seznam_lokaci)
        else:
            extended_list.extend(seznam_lokaci[:remaining])
    
    return extended_list

def parse_location_config(location_config):
    """
    Nový formát konfigurace lokací:
      {
        "IDLokace": ["start-end", "cislo", ...],
        "36": ["13600-13680", "13681"],
        "8":  ["13300-13301"]
      }
    - Bez 'default' klíče.
    - Lze kombinovat intervaly a jednotlivá čísla.
    - Pokud číslo neodpovídá žádnému pravidlu, použije se první nalezené ID lokace (fallback) a zapíše se varování.
    """
    intervals = []          # [(start, end, location_id), ...]
    specific_numbers = {}   # {clover_number: location_id}
    first_location = None

    print("Parsování konfigurace lokací (nový formát {IDLokace: [interval|číslo,...]}):")
    for key, tokens in (location_config or {}).items():
        try:
            loc_id = int(str(key).strip())
        except Exception:
            print(f" CHYBA: Neplatné ID lokace '{key}', přeskočeno")
            continue

        if first_location is None:
            first_location = loc_id

        if not isinstance(tokens, list):
            print(f" CHYBA: Hodnota pro lokaci {loc_id} musí být seznam, nalezeno: {type(tokens).__name__}")
            continue

        for token in tokens:
            s = str(token).strip()
            if not s:
                continue
            if '-' in s:
                try:
                    a, b = s.split('-', 1)
                    start = int(a.strip())
                    end = int(b.strip())
                    if start > end:
                        start, end = end, start
                    intervals.append((start, end, loc_id))
                    print(f" Interval {start}-{end} -> lokace {loc_id}")
                except Exception:
                    print(f" CHYBA: Neplatný interval '{s}' pro lokaci {loc_id}, přeskočeno")
            else:
                try:
                    num = int(s)
                    specific_numbers[num] = loc_id
                    print(f" Číslo {num} -> lokace {loc_id}")
                except Exception:
                    print(f" CHYBA: Neplatné číslo '{s}' pro lokaci {loc_id}, přeskočeno")

    intervals.sort()

    def get_location_for_number(clover_number):
        # 1) konkrétní čísla
        if clover_number in specific_numbers:
            return specific_numbers[clover_number]
        # 2) intervaly (v pořadí)
        for start, end, loc_id in intervals:
            if start <= clover_number <= end:
                return loc_id
        # 3) fallback: první definovaná lokace nebo 1
        if first_location is not None:
            print(f"VAROVÁNÍ: Číslo {clover_number} není v konfiguraci; používám lokaci {first_location}")
            return first_location
        print(f"VAROVÁNÍ: Konfigurace lokací je prázdná; používám lokaci 1")
        return 1

    return get_location_for_number

def generate_location_list_advanced(n, m, location_config):
    """Vygeneruje seznam lokací pro rozsah N–M podle nového formátu {IDLokace: [interval|číslo,...]}."""
    get_location = parse_location_config(location_config)
    location_list = []
    for clover_number in range(n, m + 1):
        location_id = get_location(clover_number)
        location_list.append(location_id)
    print(f"\nVygenerovaný seznam lokací pro rozsah {n}-{m}: Celkem {len(location_list)} položek")
    if len(location_list) <= 10:
        print(f"Seznam: {location_list}")
    else:
        print(f"První 5: {location_list[:5]}")
        print(f"Poslední 5: {location_list[-5:]}")
    return location_list

def combine_image_worker(i, location_images, clover_images, clover_metadata,
                        extended_locations, poznamky_dict, location_gps_centers,
                        progress_callback, total_images):
    """
    Pracovní funkce pro jedno vlákno, která zkombinuje jeden obrázek.
    ZMĚNA: Vrací také metadata pro další zpracování.
    """
    combined = combine_images(
        location_images[i],
        clover_images[i],
        clover_metadata[i],
        extended_locations[i],
        poznamky_dict,
        location_gps_centers[i]
    )

    if progress_callback:
        # Progress pro jednotlivé položky je řízen v main po dokončení future.
        pass

    return i, combined

def main(n, m, location_config, def_cesta_lokaci, cesta_ctyrlistky="./ctyrlistky",
         output_pdf="output.pdf", poznamky_dict=None, copy_folder=None,
         pages_per_pdf=20, status_dict=None, progress_callback=None):
    """
    Finální, plně optimalizovaná verze s nastavitelným počtem stran a podporou stavů.
    ZMĚNA: Přidána podpora pro předávání metadata do PDF generátoru.
    """
    total_images = m - n + 1

    if progress_callback:
        progress_callback("phase_loading:0")

    extended_locations = generate_location_list_advanced(n, m, location_config)
    location_images, location_gps_centers = load_location_images(extended_locations, def_cesta_lokaci)
    clover_images, clover_metadata = load_clover_images_range(n, m, cesta_ctyrlistky, status_dict=status_dict)

    if progress_callback:
        progress_callback("phase_loading:100")

    if progress_callback:
        progress_callback("phase_combining:0")

    # ZMĚNA: Přidání poznámek do metadat pro darované čtyřlístky
    for i, metadata in enumerate(clover_metadata):
        clover_number = metadata['number']
        if poznamky_dict and clover_number in poznamky_dict:
            metadata['note'] = poznamky_dict[clover_number]

    combined_images = [None] * total_images

    with concurrent.futures.ThreadPoolExecutor() as executor:
        worker_func = partial(combine_image_worker,
                              location_images=location_images, clover_images=clover_images,
                              clover_metadata=clover_metadata, extended_locations=extended_locations,
                              poznamky_dict=poznamky_dict, location_gps_centers=location_gps_centers,
                              progress_callback=None, total_images=total_images)

        futures = {executor.submit(worker_func, i): i for i in range(total_images)}
        processed_count = 0

        for future in concurrent.futures.as_completed(futures):
            index, result_image = future.result()
            combined_images[index] = result_image
            processed_count += 1

            if progress_callback:
                percent = int((processed_count / total_images) * 100)
                progress_callback(f"phase_combining:{percent}")

    if progress_callback:
        progress_callback("phase_saving:0")

    # ZMĚNA: Příprava dat pro PDF - kombinování obrázků s metadaty
    all_images_data = []
    for i in range(total_images):
        img_obj, texts = combined_images[i]
        metadata = clover_metadata[i]
        all_images_data.append((img_obj, texts, metadata))

    IMAGES_PER_PAGE = 5
    PAGES_PER_PDF = pages_per_pdf
    IMAGES_PER_PDF = IMAGES_PER_PAGE * PAGES_PER_PDF

    image_chunks = [all_images_data[i:i + IMAGES_PER_PDF] for i in range(0, len(all_images_data), IMAGES_PER_PDF)]

    generated_files = []
    output_dir = os.path.dirname(output_pdf)

    # Robustní extrakce prefixu z output_pdf
    import re
    base_name = os.path.basename(output_pdf)
    m_pref = re.match(r'^([A-Za-z]+)-\d+-\d+\.pdf$', base_name)
    prefix = m_pref.group(1) if m_pref else ""

    total_pages_overall = math.ceil(len(all_images_data) / IMAGES_PER_PAGE)
    processed_pages_lock = threading.Lock()
    processed_pages_total = 0

    def create_pdf_task(chunk_with_index):
        index, chunk = chunk_with_index
        nonlocal processed_pages_total

        start_num = n + index * IMAGES_PER_PDF
        end_num = min(m, start_num + IMAGES_PER_PDF - 1)

        name_core = f"{start_num}-{end_num}.pdf"
        chunk_filename = f"{prefix}-{name_core}" if prefix else name_core
        chunk_output_path = os.path.join(output_dir, chunk_filename)

        def single_pdf_progress_callback(page_in_chunk, total_in_chunk):
            nonlocal processed_pages_total
            with processed_pages_lock:
                processed_pages_total += 1
                percent = int((processed_pages_total / total_pages_overall) * 100) if total_pages_overall > 0 else 0
                if progress_callback:
                    progress_callback(f"phase_saving:{percent}")

        create_multipage_pdf(chunk, chunk_output_path, single_pdf_progress_callback)
        return chunk_output_path

    if len(image_chunks) <= 1:
        # Jediný soubor
        final_output_path = output_pdf
        def single_file_progress(p, t):
            if progress_callback:
                progress_callback(f"phase_saving:{int((p/t)*100)}")

        create_multipage_pdf(all_images_data, final_output_path, single_file_progress)
        generated_files.append(final_output_path)
    else:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_chunk = {executor.submit(create_pdf_task, (i, chunk)): chunk for i, chunk in enumerate(image_chunks)}

            for future in concurrent.futures.as_completed(future_to_chunk):
                try:
                    path = future.result()
                    generated_files.append(path)
                except Exception as exc:
                    print(f'Generování PDF souboru selhalo: {exc}')

    if progress_callback:
        progress_callback("phase_saving:100")

    if copy_folder:
        copy_and_rename_clovers(clover_metadata, extended_locations, n, m, cesta_ctyrlistky, copy_folder)

    return generated_files

if __name__ == "__main__":
    N = 13590
    M = 13590
    LOCATION_CONFIG = { 'default': 8 }
    DEF_CESTA_LOKACI = "/cesta/k/lokacim/"
    CESTA_CTYRLISTKY = "/cesta/ke/ctyrlistkum/"
    COPY_FOLDER = "/cesta/pro/kopie/"
    POZNAMKY = { 13590: "Testovací poznámka" }
    output_filename = f"F-{N}-{M}.pdf"
    main(N, M, LOCATION_CONFIG, DEF_CESTA_LOKACI, CESTA_CTYRLISTKY,
         output_filename, POZNAMKY, COPY_FOLDER)