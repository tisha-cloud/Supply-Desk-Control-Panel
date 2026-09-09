import pytesseract
from PIL import Image
import pymupdf
import re
import io
import os

def parse_image_or_scanned_pdf(item):
    """
    Parses image files (.jpeg, .jpg) or scanned PDF pages using Tesseract OCR.
    """
    abs_path = item['abs_path']
    rel_path = item['rel_path']
    developer_name = item['developer_name']
    period = item['period']
    folder_category = item['folder_category']
    file_type = item['file_type']
    
    records = []
    
    if file_type == 'IMAGE':
        try:
            img = Image.open(abs_path)
            ocr_text = pytesseract.image_to_string(img)
            
            lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
            
            # Look for line items (e.g. "1. ITPB, Whitefield 10th Floor Explorer 19,064 Warm Shell | Non SEZ Immediate")
            for line in lines:
                if len(line) < 5:
                    continue
                    
                area_m = re.search(r'([\d,]{3,})\s*(?:Sq\.?\s*ft|sqft|sft|Warm|Bare|Shell|Furnished|Non\s*SEZ|SEZ|Immediate)?', line, re.I)
                floor_m = re.search(r'(\d+(?:st|nd|rd|th)?\s*Floor|GF|Ground\s*Floor)', line, re.I)
                status_m = re.search(r'(Warm\s*Shell|Bare\s*Shell|Fully\s*Furnished|Plug\s*&\s*Play|Non\s*SEZ|SEZ)', line, re.I)
                rent_m = re.search(r'(?:Rs\.?|INR)?\s*([\d,]{2,}(?:\.\d+)?)', line, re.I)
                
                rec = {
                    'developer_name': developer_name,
                    'folder_category': folder_category,
                    'property_name': os.path.splitext(item['filename'])[0],
                    'source_file': rel_path,
                    'source_format': 'IMAGE',
                    'extraction_method': 'Tesseract OCR Image',
                    'report_period': period,
                    'raw_remarks': line
                }
                
                if area_m: rec['available_area_sqft'] = area_m.group(1)
                if floor_m: rec['floor_details'] = floor_m.group(1)
                if status_m: rec['fitout_status'] = status_m.group(1)
                if rent_m: rec['rent_rate_sqft_pm'] = rent_m.group(1)
                
                records.append(rec)
                
            if not records and ocr_text.strip():
                records.append({
                    'developer_name': developer_name,
                    'folder_category': folder_category,
                    'property_name': os.path.splitext(item['filename'])[0],
                    'source_file': rel_path,
                    'source_format': 'IMAGE',
                    'extraction_method': 'Tesseract OCR Image Summary',
                    'report_period': period,
                    'raw_remarks': ocr_text[:400].replace('\n', ' ')
                })
        except Exception as e:
            records.append({
                'developer_name': developer_name,
                'folder_category': folder_category,
                'property_name': 'Error reading Image OCR',
                'raw_remarks': f'OCR Failed: {str(e)}',
                'source_file': rel_path,
                'source_format': 'IMAGE',
                'extraction_method': 'OCR Error',
                'report_period': period
            })
            
    elif file_type == 'PDF_SCANNED':
        try:
            doc = pymupdf.open(abs_path)
            max_pages = min(5, len(doc))
            for page_num in range(max_pages):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=100)
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))
                
                ocr_text = pytesseract.image_to_string(img)
                lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
                
                if not lines:
                    continue
                    
                full_pg_text = " ".join(lines)
                
                area_m = re.search(r'([\d,]{4,})\s*(?:Sq\.?\s*ft|sqft|sft)', full_pg_text, re.I)
                rent_m = re.search(r'(?:Rent|Rate|Price)[\s:\-]+(?:Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)', full_pg_text, re.I)
                loc_m = re.search(r'(?:Location|Address|Situated in)[\s:\-]+([^\.\n]+)', full_pg_text, re.I)
                
                rec = {
                    'developer_name': developer_name,
                    'folder_category': folder_category,
                    'property_name': f"{developer_name} Page {page_num+1}",
                    'source_file': rel_path,
                    'source_format': 'PDF_SCANNED',
                    'extraction_method': f'Tesseract OCR Scanned PDF (Pg {page_num+1})',
                    'report_period': period,
                    'raw_remarks': full_pg_text[:400]
                }
                
                if area_m: rec['available_area_sqft'] = area_m.group(1)
                if rent_m: rec['rent_rate_sqft_pm'] = rent_m.group(1)
                if loc_m: rec['micromarket_location'] = loc_m.group(1).strip()
                
                records.append(rec)
            doc.close()
        except Exception as e:
            records.append({
                'developer_name': developer_name,
                'folder_category': folder_category,
                'property_name': 'Error reading Scanned PDF OCR',
                'raw_remarks': f'Scanned PDF OCR Failed: {str(e)}',
                'source_file': rel_path,
                'source_format': 'PDF_SCANNED',
                'extraction_method': 'OCR Error',
                'report_period': period
            })

    if not records:
        records.append({
            'developer_name': developer_name,
            'folder_category': folder_category,
            'property_name': f"{developer_name} Visual Listing",
            'raw_remarks': 'Visual file processed via OCR engine.',
            'source_file': rel_path,
            'source_format': file_type,
            'extraction_method': 'OCR Default Inventory Record',
            'report_period': period
        })

    return records

if __name__ == '__main__':
    import glob
    imgs = glob.glob(r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply\**\*.jpeg', recursive=True)
    if imgs:
        item = {
            'abs_path': imgs[0],
            'rel_path': os.path.relpath(imgs[0], r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply'),
            'filename': os.path.basename(imgs[0]),
            'developer_name': 'CapitaLand',
            'folder_category': 'Capita Land Investment',
            'file_type': 'IMAGE',
            'period': 'August 2026'
        }
        res = parse_image_or_scanned_pdf(item)
        print(f"OCR extracted {len(res)} records from image.")
        for r in res[:2]: print(r)
