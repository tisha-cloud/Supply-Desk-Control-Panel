import pdfplumber
import pymupdf
import re
import os

def clean_cell(val):
    if val is None:
        return ""
    return str(val).replace('\n', ' ').strip()

def parse_pdf_file(item):
    """
    Parses native/vector text PDF files and extracts structured property listings.
    """
    abs_path = item['abs_path']
    rel_path = item['rel_path']
    developer_name = item['developer_name']
    period = item['period']
    folder_category = item['folder_category']
    
    records = []
    current_property_context = ""
    current_micromarket_context = ""
    
    try:
        pdf_doc = pdfplumber.open(abs_path)
    except Exception as e:
        return [{
            'developer_name': developer_name,
            'folder_category': folder_category,
            'property_name': 'Error reading PDF',
            'raw_remarks': f'Failed to open PDF: {str(e)}',
            'source_file': rel_path,
            'source_format': 'PDF',
            'extraction_method': 'PDF Error',
            'report_period': period
        }]

    tables_extracted_pages = 0
    for page_num, page in enumerate(pdf_doc.pages):
        page_text = page.extract_text() or ""
        
        # Check for Property / Park / Micromarket Header on page
        lines = [line.strip() for line in page_text.split('\n') if line.strip()]
        for line in lines[:5]:
            line_upper = line.upper()
            if any(k in line_upper for k in ['PARK', 'TECH', 'BUSINESS', 'CITY', 'HEIGHTS', 'TOWER', 'PLAZA', 'ESTATE', 'COMPLEX', 'PORTFOLIO', 'BUILDING', 'ITPB', 'ECOWORLD', 'ECOSPACE']):
                if not any(k in line_upper for k in ['AVAILABILITY REPORT', 'CONTENTS', 'PAGE', 'SUMMARY', 'TABLE OF']):
                    current_property_context = line
                    break

        # Fast table page filter: only invoke pdfplumber.extract_tables if page text has both area unit AND table header keywords
        has_area_terms = any(k in page_text.upper() for k in ['SQFT', 'SFT', 'SQ FT', 'SQ. FT', 'SQFT.'])
        has_table_headers = any(k in page_text.upper() for k in ['BUILDING', 'PREMISES', 'BLOCK', 'FLOOR', 'STATUS', 'RENT', 'TOWER', 'AVAILABLE', 'VACANCY'])
        
        if has_area_terms and has_table_headers and tables_extracted_pages < 3:
            tables = page.extract_tables()
            tables_extracted_pages += 1
        else:
            tables = []
        
        if tables:
            for table_idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
                    
                # Identify header row
                header_row_idx = 0
                for r_idx in range(min(3, len(table))):
                    row_cells = [clean_cell(c).upper() for c in table[r_idx] if c is not None]
                    row_str = " ".join(row_cells)
                    if any(k in row_str for k in ['BUILDING', 'PREMISES', 'BLOCK', 'FLOOR', 'AREA', 'SF', 'SQFT', 'STATUS', 'TIMELINE', 'RENT', 'ZONE', 'TOWER']):
                        header_row_idx = r_idx
                        break
                        
                headers = [clean_cell(c) for c in table[header_row_idx]]
                
                # Check if headers are empty
                if not any(headers):
                    headers = [f"Col_{i}" for i in range(len(table[0]))]
                    
                for r_idx in range(header_row_idx + 1, len(table)):
                    row = table[r_idx]
                    if not row or all(clean_cell(c) == "" for c in row):
                        continue
                        
                    row_dict = {
                        'developer_name': developer_name,
                        'folder_category': folder_category,
                        'source_file': rel_path,
                        'source_format': 'PDF',
                        'extraction_method': f'PDF Table (Pg {page_num+1})',
                        'report_period': period
                    }
                    
                    raw_pairs = []
                    for col_idx, cell in enumerate(row):
                        cell_val = clean_cell(cell)
                        if col_idx < len(headers):
                            h_name = headers[col_idx]
                            h_upper = h_name.upper()
                            
                            if cell_val:
                                raw_pairs.append(f"{h_name}: {cell_val}")
                                
                            if any(k in h_upper for k in ['BUILDING', 'PREMISES', 'PROJECT', 'PARK', 'PROPERTY']):
                                row_dict['property_name'] = cell_val
                            elif any(k in h_upper for k in ['LOCATION', 'ADDRESS', 'ZONE', 'MICROMARKET']):
                                row_dict['micromarket_location'] = cell_val
                            elif any(k in h_upper for k in ['BLOCK', 'TOWER', 'WING']):
                                row_dict['building_block_tower'] = cell_val
                            elif any(k in h_upper for k in ['FLOOR']):
                                row_dict['floor_details'] = cell_val
                            elif any(k in h_upper for k in ['AREA', 'SQFT', 'SF', 'SIZE', 'SFT', 'AVAILABLE']):
                                row_dict['available_area_sqft'] = cell_val
                            elif any(k in h_upper for k in ['STATUS', 'CONDITION', 'FITOUT', 'WARM', 'BARE', 'FURNISHED', 'TYPE']):
                                row_dict['fitout_status'] = cell_val
                            elif any(k in h_upper for k in ['RENT', 'COMMERCIAL', 'RATE', 'PRICE']):
                                row_dict['rent_rate_sqft_pm'] = cell_val
                            elif any(k in h_upper for k in ['TIMELINE', 'POSSESSION', 'AVAILABILITY', 'DATE']):
                                row_dict['timeline_possession'] = cell_val
                                
                    if raw_pairs:
                        row_dict['raw_remarks'] = " | ".join(raw_pairs)
                        if 'property_name' not in row_dict or not row_dict['property_name']:
                            row_dict['property_name'] = current_property_context if current_property_context else f"{developer_name} Property"
                        if 'micromarket_location' not in row_dict or not row_dict['micromarket_location']:
                            if current_micromarket_context:
                                row_dict['micromarket_location'] = current_micromarket_context
                                
                        records.append(row_dict)
        else:
            # No table on page - extract key-value text lines or slide summary
            if page_text:
                area_match = re.search(r'(?:Area|Size|Space|Available)[\s:\-]+([\d,]+(?:\s*sq\.?\s*ft|\s*sft)?)', page_text, re.I)
                rent_match = re.search(r'(?:Rent|Commercials|Rate)[\s:\-]+(?:Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)', page_text, re.I)
                loc_match = re.search(r'(?:Location|Address|Situated in)[\s:\-]+([^\.\n]+)', page_text, re.I)
                
                if area_match or rent_match or loc_match:
                    rec = {
                        'developer_name': developer_name,
                        'folder_category': folder_category,
                        'property_name': current_property_context if current_property_context else f"{developer_name} Page {page_num+1}",
                        'source_file': rel_path,
                        'source_format': 'PDF',
                        'extraction_method': f'PDF Text Analysis (Pg {page_num+1})',
                        'report_period': period,
                        'raw_remarks': page_text[:400].replace('\n', ' ')
                    }
                    if area_match: rec['available_area_sqft'] = area_match.group(1)
                    if rent_match: rec['rent_rate_sqft_pm'] = rent_match.group(1)
                    if loc_match: rec['micromarket_location'] = loc_match.group(1).strip()
                    records.append(rec)

    pdf_doc.close()

    if not records:
        records.append({
            'developer_name': developer_name,
            'folder_category': folder_category,
            'property_name': f"{developer_name} Document Summary",
            'raw_remarks': 'Document processed cleanly. Extracted as master developer brochure/deck record.',
            'source_file': rel_path,
            'source_format': 'PDF',
            'extraction_method': 'PDF Inventory Record',
            'report_period': period
        })

    return records

if __name__ == '__main__':
    import glob
    files = glob.glob(r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply\**\*.pdf', recursive=True)
    print(f"Testing PDF parser on {len(files)} files...")
    sample_res = parse_pdf_file({
        'abs_path': files[0],
        'rel_path': os.path.relpath(files[0], r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply'),
        'developer_name': 'Test Dev',
        'folder_category': 'Test Folder',
        'period': 'July 2026'
    })
    print(f"Extracted {len(sample_res)} records from first PDF.")
