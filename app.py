import os
import zipfile
import re
import zlib
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

def extract_text_and_fonts_from_rich_blob(hex_str):
    """Searches decompressed hex blobs for font family name occurrences and text content."""
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
        
        # Check both UTF-8 and UTF-16 versions for font family names
        for text_content in [text_utf8, text_utf16]:
            # 1. Try dynamic regex matching first
            # e.g., Font = "Arial"
            dynamic_matches = re.findall(r'[Ff]ont\s*=\s*["\']([^"\']+)["\']', text_content)
            for dm in dynamic_matches:
                dm_clean = dm.strip()
                if len(dm_clean) >= 2 and dm_clean.lower() not in system_keys:
                    fonts.add(dm_clean)
            
            # e.g., face="Arial"
            face_matches = re.findall(r'face=["\']([^"\']+)["\']', text_content)
            for fm in face_matches:
                fm_clean = fm.strip()
                if len(fm_clean) >= 2 and fm_clean.lower() not in system_keys:
                    fonts.add(fm_clean)
                    
            # 2. Try predefined database matching
            for font in FONTS_DB:
                if font.lower() in text_content.lower():
                    fonts.add(font)
                    
        printable_strings = []
        
        # Search UTF-8 for sequences of printable characters of length >= 2
        for match in re.findall(r'[\x20-\x7E\s]{2,}', text_utf8):
            match_clean = match.strip()
            if (len(match_clean) >= 2 and 
                match_clean.lower() not in system_keys and 
                not match_clean.isdigit() and
                not any(font.lower() in match_clean.lower() for font in fonts)):
                printable_strings.append(match_clean)
                
        # Search UTF-16LE
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
