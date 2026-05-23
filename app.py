import os
import zipfile
import re
import zlib
import struct
try:
    import zstandard
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    print("[BACKEND] WARNING: zstandard not installed. Title text extraction will be limited.")
    print("[BACKEND] Install with: pip install zstandard")
import shutil
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder=".")

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_drp_decode")

# Predefined database of common fonts to scan for inside binary payloads
FONTS_DB = [
    "Helvetica Neue LT Std", "Helvetica Neue", "HelveticaNeue", "Helvetica", 
    "Arial", "Open Sans", "Inter", "Roboto", "Times New Roman", "Times", 
    "Courier New", "Courier", "Verdana", "Georgia", "Tahoma", "Trebuchet MS", 
    "Impact", "Comic Sans MS", "Lato", "Montserrat", "Outfit", "Segoe UI", 
    "Calibri", "Cambria", "Myriad Pro", "Minion Pro", "Garamond", "Bodoni", 
    "Futura", "Gill Sans", "Rockwell", "Baskerville"
]

def sanitize_xml(xml_bytes):
    """Replaces double colons with underscores to make tags valid XML for ElementTree."""
    xml_str = xml_bytes.decode('utf-8', errors='replace')
    xml_str_sanitized = xml_str.replace("::", "_")
    return xml_str_sanitized.encode('utf-8')

def decompress_zstd_blob(hex_str):
    """Decompresses a ZSTD-compressed EffectFiltersBA hex blob.
    
    Format:
    - 8-byte header: 4-byte count (big-endian) + 4-byte payload size (big-endian)
    - 1-byte type marker (0x81)
    - ZSTD frame (magic: 28 B5 2F FD)
    
    Returns the decompressed bytes, or b"" on failure.
    """
    if not hex_str or not HAS_ZSTD:
        return b""
    try:
        blob_bytes = bytes.fromhex(hex_str)
        if len(blob_bytes) < 13:  # 8 header + 1 type + 4 zstd magic minimum
            return b""
        
        # Skip 8-byte header + 1-byte type marker
        payload = blob_bytes[9:]
        
        # Verify ZSTD magic number
        if payload[:4] == b'\x28\xb5\x2f\xfd':
            dctx = zstandard.ZstdDecompressor()
            return dctx.decompress(payload, max_output_size=1024 * 1024)
    except Exception as e:
        # ZSTD decompression can fail on some blobs (e.g., minor data corruption)
        pass
    return b""

def decompress_blob(hex_str):
    """Attempts to find and decompress zlib/deflate streams inside a hex blob."""
    if not hex_str:
        return b""
    try:
        blob_bytes = bytes.fromhex(hex_str)
        # Try decompressing starting at every offset
        for offset in range(len(blob_bytes)):
            if len(blob_bytes) - offset < 8:
                break
            for wbits in [15, -15]:
                try:
                    return zlib.decompress(blob_bytes[offset:], wbits)
                except Exception:
                    pass
    except Exception:
        pass
    return b""

def extract_utf16le_strings(data, min_length=2):
    """Extract all UTF-16-LE encoded strings from binary data.
    Returns a list of (offset, string) tuples.
    Only returns strings with at least min_length characters.
    """
    strings = []
    i = 0
    while i < len(data) - 1:
        # Look for sequences of printable UTF-16-LE chars (low byte printable, high byte 0x00)
        if data[i] >= 0x20 and data[i] < 0x7F and data[i+1] == 0x00:
            start = i
            while i < len(data) - 1 and data[i] >= 0x20 and data[i] < 0x7F and data[i+1] == 0x00:
                i += 2
            text = data[start:i].decode('utf-16-le')
            if len(text) >= min_length:
                strings.append((start, text))
        else:
            i += 1
    return strings

def extract_title_text_from_decompressed(data):
    """Extract the title text from decompressed EffectFiltersBA data using structural parsing.
    
    The decompressed data has a binary structure where the title text is stored as
    UTF-16-LE after a 0x38 0x04 0x00 marker followed by two 4-byte length fields.
    
    Structure: ... 38 04 00 <byte_len:u32le> <char_count_or_padding:u32le> <utf16le_text> ...
    
    Returns the title text string or empty string.
    """
    # Search for the marker byte sequence: 0x38 0x04 0x00
    marker = b'\x38\x04\x00'
    pos = data.find(marker)
    if pos < 0 or pos + 11 >= len(data):
        return ""
    
    # After marker come two 4-byte LE uint32 fields, then the UTF-16-LE text
    # Field 1 at pos+3: total byte length of text region
    # Field 2 at pos+7: could be char count or another length
    # Text starts at pos+11
    text_start = pos + 3 + 4 + 4  # marker(3) + field1(4) + field2(4)
    
    if text_start >= len(data):
        return ""
    
    # Extract the UTF-16-LE string starting at text_start
    i = text_start
    while i < len(data) - 1:
        if data[i] >= 0x20 and data[i] < 0x7F and data[i+1] == 0x00:
            start = i
            while i < len(data) - 1 and data[i] >= 0x20 and data[i] < 0x7F and data[i+1] == 0x00:
                i += 2
            text = data[start:i].decode('utf-16-le')
            return text.strip()
        else:
            i += 1
    
    return ""

STANDARD_STYLE_WORDS = [
    'semibold', 'condensed', 'ultralight', 'extrabold', 'hairline',
    'regular', 'condensed', 'oblique', 'extended', 'slanted', 'upright',
    'italic', 'medium', 'narrow', 'poster', 'double', 'single',
    'light', 'roman', 'black', 'heavy', 'super', 'ultra', 'extra',
    'demi', 'book', 'thin', 'wide', 'cond', 'alt', 'lgt', 'med',
    'bold', 'cn', 'lt', 'bd', 'rg', 'it'
]

def clean_and_validate_style(style_str):
    """Cleans a font style string and validates that it is a standard font style.
    
    If the string has trailing structural bytes (e.g. 'BoldK', 'Medium9'), they are stripped.
    If the string is not a standard style (e.g. 'years old'), returns None.
    """
    words = style_str.strip().split()
    cleaned_words = []
    
    for w in words:
        w_lower = w.lower()
        matched = False
        for std in STANDARD_STYLE_WORDS:
            if w_lower.startswith(std):
                suffix = w[len(std):]
                if len(suffix) <= 2:
                    cleaned_words.append(w[:len(std)])
                    matched = True
                    break
        if not matched:
            return None
            
    return ' '.join(cleaned_words) if cleaned_words else None

def extract_text_and_fonts_from_zstd(hex_str):
    """Extract title text, fonts, and colors from a ZSTD-compressed EffectFiltersBA blob.
    
    After ZSTD decompression, the data contains a protobuf-like structure with
    UTF-16-LE encoded strings for:
    - Title text (first meaningful string, near offset 0x42)
    - Font family name (e.g., "HelveticaNeueLT Std Med Cn")
    - Font style (e.g., "67 Medium Condensed")
    - Template name (e.g., "Basic Title")
    - Colors (e.g., "#ebecea", "#FFFFFF")
    
    Returns (title_text, fonts_list, colors_list, template_name).
    """
    decompressed = decompress_zstd_blob(hex_str)
    if not decompressed:
        return "", [], [], ""
    
    # Extract title text using structural parsing (handles single-char titles like "A")
    title_text = extract_title_text_from_decompressed(decompressed)
    
    # Extract all longer strings for fonts, colors, template
    strings = extract_utf16le_strings(decompressed, min_length=2)
    
    fonts = []
    colors = []
    template_name = ""
    
    # Known non-text structural strings to skip
    skip_strings = {'ba`', '8J', 'JJ', 'JJJ', 'JJJJJJJ', '||'}
    # Known number-prefix patterns for font style IDs (e.g., "67 Medium Condensed")
    font_style_pattern = re.compile(r'^\d+\s+.+')
    
    font_indicators_nocase = ['neue', 'sans', 'serif', 'mono', 'bold', 'regular', 'medium', 'light', 'condensed', 'helvetica', 'arial', 'roboto', 'inter']
    font_indicators_case = ['LT', 'Std', 'Cn', 'Lt', 'Med']
    
    for offset, s in strings:
        s_stripped = s.strip()
        if not s_stripped or s_stripped in skip_strings:
            continue
            
        # Skip the title text itself (already extracted)
        if s_stripped == title_text:
            continue
            
        # Color values start with #
        if s_stripped.startswith('#'):
            colors.append(s_stripped)
            continue
        
        # First, try to see if it starts with a number (style pattern like "67 Medium Condensed")
        if font_style_pattern.match(s_stripped):
            style_parts = s_stripped.split(' ', 1)
            if len(style_parts) == 2:
                cleaned = clean_and_validate_style(style_parts[1])
                if cleaned:
                    fonts.append(cleaned)
            continue
            
        # Second, try to clean it as a style directly (like 'BoldK' or 'Medium9')
        cleaned_style = clean_and_validate_style(s_stripped)
        if cleaned_style:
            fonts.append(cleaned_style)
            continue
        
        # Third, check if it looks like a font family name
        is_font = False
        if len(s_stripped) <= 50 and not any(char in s_stripped for char in [',', '.', ';', '!', '?']):
            if any(ind in s_stripped.lower() for ind in font_indicators_nocase):
                is_font = True
            elif any(re.search(r'\b' + re.escape(ind) + r'\b', s_stripped) for ind in font_indicators_case):
                is_font = True
        
        if is_font:
            fonts.append(s_stripped)
            continue
        
        # Check if it's a template name
        template_indicators = ['Basic Title', 'Lower Third', 'Scroll']
        is_template = any(ind.lower() in s_stripped.lower() for ind in template_indicators)
        if is_template:
            template_name = s_stripped
            continue
    
    # Deduplicate fonts
    unique_fonts = []
    for f in fonts:
        if f not in unique_fonts:
            unique_fonts.append(f)
    
    # Deduplicate colors
    unique_colors = list(set(colors))
    
    return title_text, unique_fonts, unique_colors, template_name

def extract_text_and_fonts_from_rich_blob(hex_str):
    """Extract text and font info from a Rich generator's EffectFiltersBA blob.
    
    First tries ZSTD decompression (the primary encoding used by DaVinci Resolve).
    Falls back to zlib-based heuristic extraction for older formats.
    
    Returns (title_text, fonts_list).
    """
    # Try ZSTD first (preferred method)
    if HAS_ZSTD and hex_str and len(hex_str) > 26:
        try:
            blob_bytes = bytes.fromhex(hex_str)
            # Check for ZSTD signature: 8-byte header + type byte 0x81 + ZSTD magic
            if (len(blob_bytes) > 13 and 
                blob_bytes[8] == 0x81 and 
                blob_bytes[9:13] == b'\x28\xb5\x2f\xfd'):
                title_text, fonts, colors, template = extract_text_and_fonts_from_zstd(hex_str)
                if title_text or fonts:
                    print(f"[BACKEND] ZSTD decoded: text='{title_text}', fonts={fonts}")
                    return title_text, fonts
        except Exception as e:
            print(f"[BACKEND] ZSTD extraction failed, falling back: {e}")
    
    # Fallback: legacy zlib-based heuristic extraction
    fonts = set()
    longest_text = ""
    decomp = decompress_blob(hex_str)
    if decomp:
        text_utf8 = decomp.decode('utf-8', errors='ignore')
        text_utf16 = decomp.decode('utf-16le', errors='ignore')
        
        system_keys = {
            "numlayers", "effectfiltersba", "rendertextenabled", "rendertextganged",
            "rendertextprefixed", "fieldsblob", "memento", "rgbaoutputenabled",
            "useversionclipprocparams", "virtualaudiotrackba", "wasdisbanded",
            "input", "value", "key", "true", "false", "clip", "track", "sequence",
            "timeline", "mediatimemapba", "rendercacheba", "fusioncompholderitems",
            "importexportmetadataba", "markersba", "uimemento", "none", "rich",
            "style", "param"
        }
        
        for text_content in [text_utf8, text_utf16]:
            dynamic_matches = re.findall(r'[Ff]ont\s*=\s*["\']([^"\']+)["\']', text_content)
            for dm in dynamic_matches:
                dm_clean = dm.strip()
                if len(dm_clean) >= 2 and dm_clean.lower() not in system_keys:
                    fonts.add(dm_clean)
            
            face_matches = re.findall(r'face=["\']([^"\']+)["\']', text_content)
            for fm in face_matches:
                fm_clean = fm.strip()
                if len(fm_clean) >= 2 and fm_clean.lower() not in system_keys:
                    fonts.add(fm_clean)
                    
            for font in FONTS_DB:
                if font.lower() in text_content.lower():
                    fonts.add(font)
                    
        printable_strings = []
        for match in re.findall(r'[\x20-\x7E\s]{2,}', text_utf8):
            match_clean = match.strip()
            if (len(match_clean) >= 2 and 
                match_clean.lower() not in system_keys and 
                not match_clean.isdigit() and
                not any(font.lower() in match_clean.lower() for font in fonts)):
                printable_strings.append(match_clean)
                
        for match in re.findall(r'[\x20-\x7E\s]{2,}', text_utf16):
            match_clean = match.strip()
            if (len(match_clean) >= 2 and 
                match_clean.lower() not in system_keys and 
                not match_clean.isdigit() and
                not any(font.lower() in match_clean.lower() for font in fonts)):
                printable_strings.append(match_clean)
                
        if printable_strings:
            printable_strings.sort(key=len, reverse=True)
            unique_strings = []
            for s in printable_strings:
                if s not in unique_strings:
                    unique_strings.append(s)
            if unique_strings:
                longest_text = unique_strings[0]
                
    return longest_text, list(fonts)

def extract_fonts_from_blob(hex_str):
    """Wrapper for backwards compatibility."""
    _, fonts = extract_text_and_fonts_from_rich_blob(hex_str)
    return fonts

def parse_drp(drp_path):
    """Unzips and parses the DRP file to extract timelines, clips, and fonts."""
    # Clean temp directory
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    print(f"[BACKEND] Extracting DRP: {drp_path}")
    with zipfile.ZipFile(drp_path, 'r') as z:
        z.extractall(TEMP_DIR)
        
    print("[BACKEND] DRP Extracted. Mapping timelines...")
    
    # 1. Gather all timeline information from MediaPool folder structures
    timelines = []
    # Search all MpFolder.xml files
    for root, dirs, files in os.walk(os.path.join(TEMP_DIR, "MediaPool")):
        for file in files:
            if file == "MpFolder.xml":
                mp_file_path = os.path.join(root, file)
                try:
                    with open(mp_file_path, 'rb') as f:
                        xml_root = ET.fromstring(sanitize_xml(f.read()))
                        for clip in xml_root.findall(".//Sm2MpTimelineClip"):
                            name_node = clip.find("Name")
                            name = name_node.text.strip() if name_node is not None and name_node.text else "Unnamed Timeline"
                            
                            seq_node = clip.find(".//Sm2Sequence")
                            seq_db_id = seq_node.attrib.get('DbId', '').lower() if seq_node is not None else ''
                            
                            if seq_db_id:
                                timelines.append({
                                    "name": name,
                                    "seq_db_id": seq_db_id,
                                    "sequence_file": None,
                                    "fonts": {}
                                })
                except Exception as e:
                    print(f"[BACKEND] Error parsing {mp_file_path}: {e}")
                    
    print(f"[BACKEND] Discovered {len(timelines)} timelines in MediaPool.")
    
    # 2. Map timelines to their sequence XML files in SeqContainer
    seq_container_dir = os.path.join(TEMP_DIR, "SeqContainer")
    if not os.path.exists(seq_container_dir):
        print("[BACKEND] SeqContainer directory not found.")
        return timelines
        
    seq_files = [f for f in os.listdir(seq_container_dir) if f.endswith('.xml')]
    print(f"[BACKEND] Found {len(seq_files)} sequence XML files. Matching...")
    
    mapped_sequences = {}
    for sf in seq_files:
        sf_path = os.path.join(seq_container_dir, sf)
        try:
            with open(sf_path, 'rb') as f:
                xml_root = ET.fromstring(sanitize_xml(f.read()))
                # Find Sequence tag
                seq_node = xml_root.find(".//Sequence")
                if seq_node is not None and seq_node.text:
                    seq_db_id = seq_node.text.strip().lower()
                    mapped_sequences[seq_db_id] = sf
        except Exception as e:
            print(f"[BACKEND] Error matching sequence file {sf}: {e}")
            
    for t in timelines:
        seq_db_id = t["seq_db_id"]
        if seq_db_id in mapped_sequences:
            t["sequence_file"] = mapped_sequences[seq_db_id]
            print(f"[BACKEND] Timeline '{t['name']}' mapped to sequence file '{t['sequence_file']}'")
            
    # 3. Analyze each mapped sequence file to extract fonts
    for t in timelines:
        if not t["sequence_file"]:
            continue
            
        sf_path = os.path.join(seq_container_dir, t["sequence_file"])
        try:
            with open(sf_path, 'rb') as f:
                xml_root = ET.fromstring(sanitize_xml(f.read()))
                
                # Helper to process a generator
                def process_generator(g, track_name, default_type):
                    g_type_node = g.find("PrettyType")
                    g_type = g_type_node.text.strip() if g_type_node is not None and g_type_node.text else default_type
                    
                    g_name_node = g.find("Name")
                    g_name = g_name_node.text.strip() if g_name_node is not None and g_name_node.text else ""
                    
                    # Skip non-text generators unless they are subtitles or rich text
                    if g_type not in ["Rich", "Subtitle"] and not g_name:
                        return
                        
                    fonts = set()
                    custom_texts = []
                    
                    # Search XML nodes for font attributes
                    for elem in g.iter():
                        if 'font' in elem.tag.lower() and elem.text:
                            fonts.add(elem.text.strip())
                        for k, v in elem.attrib.items():
                            if 'font' in k.lower():
                                fonts.add(v.strip())
                                
                    # Search inside Name markup
                    if g_name:
                        face_matches = re.findall(r'face=["\']([^"\']+)["\']', g_name)
                        for face in face_matches:
                            fonts.add(face)
                            
                    # Search FieldsBlob and EffectFiltersBA decompressed contents
                    for tag in ["FieldsBlob", "EffectFiltersBA"]:
                        node = g.find(tag)
                        if node is not None and node.text:
                            custom_text, found_fonts = extract_text_and_fonts_from_rich_blob(node.text)
                            if custom_text:
                                custom_texts.append(custom_text)
                            for ff in found_fonts:
                                fonts.add(ff)
                                
                    # Choose the best custom text (longest one)
                    custom_text = ""
                    if custom_texts:
                        custom_texts.sort(key=len, reverse=True)
                        custom_text = custom_texts[0]
                        
                    # Filter out substrings to get the most specific font names
                    resolved_fonts = []
                    sorted_fonts = sorted(list(fonts), key=len, reverse=True)
                    for f in sorted_fonts:
                        if not any(f.lower() in other.lower() for other in resolved_fonts):
                            resolved_fonts.append(f)
                            
                    # Fallback default: if no font explicitly specified but it is a text/subtitle generator,
                    # resolve defaults to "HelveticaNeue" on macOS (which is implicitly applied and not written to XML)
                    if not resolved_fonts:
                        if g_type == "Subtitle" or g_type == "Rich":
                            resolved_fonts = ["HelveticaNeue"]
                            
                    for font in resolved_fonts:
                        # Clean up formatting strings from Name
                        if g_type == "Subtitle" and g_name:
                            clean_name = re.sub(r'<[^>]+>', '', g_name)
                        elif g_type == "Rich":
                            if custom_text:
                                clean_name = f"{custom_text} [{track_name}]"
                            else:
                                clean_name = f"Title (Default) [{track_name}]"
                        else:
                            clean_name = f"Text Clip ({track_name})"
                            
                        if len(clean_name) > 80:
                            clean_name = clean_name[:77] + "..."
                            
                        if font not in t["fonts"]:
                            t["fonts"][font] = []
                        t["fonts"][font].append({
                            "type": g_type,
                            "clip_name": clean_name,
                            "start": int(g.find("Start").text) if g.find("Start") is not None else 0,
                            "duration": int(g.find("Duration").text) if g.find("Duration") is not None else 0
                        })

                # A. Scan Video Tracks for generators
                video_tracks = xml_root.findall(".//VideoTrackVec/Element/Sm2TiTrack")
                for track_idx, track in enumerate(video_tracks):
                    track_name_node = track.find("UserDefinedName")
                    track_name = track_name_node.text.strip() if track_name_node is not None and track_name_node.text else f"Video Track {track_idx+1}"
                    for g in track.findall(".//Sm2TiGenerator"):
                        process_generator(g, track_name, "Rich")
                        
                # B. Scan Subtitle Tracks for generators
                subtitle_tracks = xml_root.findall(".//SubtitleTrackVec/Element/Sm2TiTrack")
                for track_idx, track in enumerate(subtitle_tracks):
                    track_name_node = track.find("UserDefinedName")
                    track_name = track_name_node.text.strip() if track_name_node is not None and track_name_node.text else f"Subtitle Track {track_idx+1}"
                    for g in track.findall(".//Sm2TiGenerator"):
                        process_generator(g, track_name, "Subtitle")
                        
                # C. Scan Subtitle Track styling (which applies to all subtitles on a track)
                for track_idx, track in enumerate(subtitle_tracks):
                    track_name_node = track.find("UserDefinedName")
                    track_name = track_name_node.text.strip() if track_name_node is not None and track_name_node.text else f"Subtitle Track {track_idx+1}"
                    
                    # Search track FieldsBlob / EffectFiltersBA for track-wide fonts
                    track_fonts = set()
                    for tag in ["FieldsBlob", "EffectFiltersBA"]:
                        node = track.find(tag)
                        if node is not None and node.text:
                            found_fonts = extract_fonts_from_blob(node.text)
                            for ff in found_fonts:
                                track_fonts.add(ff)
                                
                    if track_fonts:
                        print(f"[BACKEND] Subtitle track '{track_name}' specifies fonts: {track_fonts}")
                        for font in track_fonts:
                            if font not in t["fonts"]:
                                t["fonts"][font] = []
                            t["fonts"][font].append({
                                "type": "Subtitle Track Style",
                                "clip_name": track_name,
                                "start": 0,
                                "duration": 0
                            })
                            
        except Exception as e:
            print(f"[BACKEND] Error parsing sequence file {t['sequence_file']}: {e}")
            
    # Cleanup temp directory after reading
    try:
        shutil.rmtree(TEMP_DIR)
    except Exception:
        pass
        
    return timelines

@app.route("/analyze", methods=["POST"])
def analyze_drp():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
        
    if not file.filename.endswith(".drp"):
        return jsonify({"error": "File must be a .drp package"}), 400
        
    # Save the file temporarily
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    file.save(file_path)
    
    try:
        results = parse_drp(file_path)
        # Clean up uploaded DRP
        os.remove(file_path)
        return jsonify({"timelines": results})
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
