import os
import glob
import re
import hashlib
import pymupdf

def get_file_period(text):
    """Extract report period like 'July 2026', 'June 2026', 'August 2026' from filename or folder."""
    months = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    years = r'(202[0-9])'
    match = re.search(f"{months}[\\s_\\-\\\\/]+{years}", text, re.IGNORECASE)
    if match:
        return f"{match.group(1).capitalize()} {match.group(2)}"
    match_year = re.search(r'202[0-9]', text)
    if match_year:
        return match_year.group(0)
    return "N/A"

def get_developer_name(folder_name):
    """Clean folder name to get official Developer / Group name."""
    clean = re.sub(r'\(.*?\)', '', folder_name).strip()
    return clean if clean else folder_name

def scan_directory(target_dir):
    """
    Recursively scans target directory and returns file inventory list.
    """
    all_items = glob.glob(os.path.join(target_dir, '**', '*.*'), recursive=True)
    inventory = []
    
    for abs_path in sorted(all_items):
        if os.path.isdir(abs_path):
            continue
            
        rel_path = os.path.relpath(abs_path, target_dir)
        parts = rel_path.split(os.sep)
        folder_category = parts[0] if len(parts) > 1 else "Root"
        developer_name = get_developer_name(folder_category)
        
        filename = os.path.basename(abs_path)
        ext = os.path.splitext(filename)[1].lower()
        size_bytes = os.path.getsize(abs_path)
        
        period = get_file_period(rel_path)
        
        # Categorize format engine
        if ext in ['.xlsx', '.xls']:
            file_type = 'XLSX'
        elif ext == '.pptx':
            file_type = 'PPTX'
        elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff']:
            file_type = 'IMAGE'
        elif ext == '.pdf':
            try:
                doc = pymupdf.open(abs_path)
                total_text_len = sum(len(page.get_text()) for page in doc)
                doc.close()
                if total_text_len < 50:
                    file_type = 'PDF_SCANNED'
                else:
                    file_type = 'PDF_NATIVE'
            except Exception:
                file_type = 'PDF_SCANNED'
        else:
            file_type = 'UNKNOWN'
            
        inventory.append({
            'abs_path': abs_path,
            'rel_path': rel_path,
            'filename': filename,
            'folder_category': folder_category,
            'developer_name': developer_name,
            'ext': ext,
            'file_type': file_type,
            'size_bytes': size_bytes,
            'period': period
        })
        
    return inventory

if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply'
    inv = scan_directory(path)
    print(f"Scanned {len(inv)} files.")
    for item in inv[:5]:
        print(item)
