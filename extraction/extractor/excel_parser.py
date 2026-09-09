import openpyxl
import pandas as pd
import re
import os

def parse_excel_file(item):
    """
    Parses an Excel file (.xlsx, .xls) and returns a list of extracted raw unit records.
    """
    abs_path = item['abs_path']
    rel_path = item['rel_path']
    developer_name = item['developer_name']
    period = item['period']
    
    records = []
    
    try:
        xls = pd.ExcelFile(abs_path)
        sheet_names = xls.sheet_names
    except Exception as e:
        return [{
            'developer_name': developer_name,
            'folder_category': item['folder_category'],
            'property_name': 'Error reading file',
            'raw_remarks': f'Failed to open Excel file: {str(e)}',
            'source_file': rel_path,
            'source_format': 'XLSX',
            'extraction_method': 'Excel Error',
            'report_period': period
        }]

    for sheet in sheet_names:
        try:
            df = pd.read_excel(abs_path, sheet_name=sheet, header=None)
        except Exception:
            continue

        if df.empty or df.shape[0] < 1:
            continue

        # Strategy 1: Search for transposed property columns (e.g. Kalyani Developers / Nitesh Estates)
        # Look for rows containing 'LOCATION', 'TOTAL AVAILABLE AREA', 'BUILDING STATUS', 'RENT', 'FLOOR'
        df_str = df.astype(str).apply(lambda col: col.str.strip())
        
        row_attributes = {}
        for r_idx in range(min(25, len(df))):
            row_vals = df_str.iloc[r_idx].values
            col0_val = str(row_vals[0]).upper() if len(row_vals) > 0 else ""
            
            # Check attribute keywords
            if any(k in col0_val for k in ['LOCATION', 'AREA', 'STATUS', 'RENT', 'FLOOR', 'DESCRIPTION', 'SIZE', 'FITOUT']):
                row_attributes[r_idx] = col0_val
                
        # If we found transposed attributes in rows
        if len(row_attributes) >= 2:
            # Columns (from col 1 onwards) represent individual properties or blocks!
            for col_idx in range(1, df.shape[1]):
                col_data = df_str.iloc[:, col_idx].values
                header_prop = str(df_str.iloc[0, col_idx]).strip()
                if not header_prop or header_prop.lower() in ['nan', 'none', 'unnamed: ' + str(col_idx)]:
                    header_prop = str(df_str.iloc[1, col_idx]).strip()
                    
                if not header_prop or header_prop.lower() in ['nan', 'none', '']:
                    continue
                    
                prop_dict = {
                    'developer_name': developer_name,
                    'folder_category': item['folder_category'],
                    'property_name': header_prop,
                    'source_file': rel_path,
                    'source_format': 'XLSX',
                    'extraction_method': f'Excel Transposed Matrix ({sheet})',
                    'report_period': period
                }
                
                has_val = False
                for r_idx, attr_name in row_attributes.items():
                    val = str(col_data[r_idx]).strip()
                    if val and val.lower() not in ['nan', 'none', '']:
                        has_val = True
                        if 'LOCATION' in attr_name:
                            prop_dict['micromarket_location'] = val
                        elif 'AREA' in attr_name or 'SIZE' in attr_name:
                            prop_dict['available_area_sqft'] = val
                        elif 'STATUS' in attr_name or 'FITOUT' in attr_name:
                            prop_dict['fitout_status'] = val
                        elif 'RENT' in attr_name or 'COMMERCIAL' in attr_name:
                            prop_dict['rent_rate_sqft_pm'] = val
                        elif 'FLOOR' in attr_name:
                            prop_dict['floor_details'] = val
                        else:
                            curr_rem = prop_dict.get('raw_remarks', '')
                            prop_dict['raw_remarks'] = (curr_rem + f" | {attr_name}: {val}").strip(' | ')
                            
                if has_val:
                    records.append(prop_dict)
            continue
            
        # Strategy 2: Standard Tabular Search (Header row with column names)
        header_row_idx = None
        for r_idx in range(min(15, len(df))):
            row_vals = [str(x).upper() for x in df.iloc[r_idx].values if pd.notna(x)]
            row_text = " ".join(row_vals)
            if any(k in row_text for k in ['PROJECT', 'PROPERTY', 'BUILDING', 'LOCATION', 'AREA', 'SQFT', 'RENT', 'FLOOR', 'STATUS', 'TIMELINE']):
                header_row_idx = r_idx
                break
                
        if header_row_idx is not None:
            headers = [str(x).strip() if pd.notna(x) else f"Col_{i}" for i, x in enumerate(df.iloc[header_row_idx].values)]
            
            for r_idx in range(header_row_idx + 1, len(df)):
                row_vals = df.iloc[r_idx].values
                if all(pd.isna(x) or str(x).strip() == "" for x in row_vals):
                    continue
                    
                row_dict = {
                    'developer_name': developer_name,
                    'folder_category': item['folder_category'],
                    'source_file': rel_path,
                    'source_format': 'XLSX',
                    'extraction_method': f'Excel Table ({sheet})',
                    'report_period': period
                }
                
                raw_pairs = []
                for i, h in enumerate(headers):
                    val = row_vals[i] if i < len(row_vals) else None
                    if pd.notna(val) and str(val).strip() not in ['', 'nan', 'None']:
                        val_str = str(val).strip()
                        h_upper = h.upper()
                        raw_pairs.append(f"{h}: {val_str}")
                        
                        if any(k in h_upper for k in ['PROJECT', 'PROPERTY', 'BUILDING', 'NAME', 'PARK']):
                            row_dict['property_name'] = val_str
                        elif any(k in h_upper for k in ['LOCATION', 'ADDRESS', 'MICROMARKET', 'ZONE']):
                            row_dict['micromarket_location'] = val_str
                        elif any(k in h_upper for k in ['BLOCK', 'TOWER', 'WING']):
                            row_dict['building_block_tower'] = val_str
                        elif any(k in h_upper for k in ['FLOOR']):
                            row_dict['floor_details'] = val_str
                        elif any(k in h_upper for k in ['AREA', 'SQFT', 'SIZE', 'SFT']):
                            row_dict['available_area_sqft'] = val_str
                        elif any(k in h_upper for k in ['STATUS', 'CONDITION', 'FITOUT', 'WARM', 'BARE', 'FURNISHED']):
                            row_dict['fitout_status'] = val_str
                        elif any(k in h_upper for k in ['RENT', 'RATE', 'PRICE', 'COMMERCIAL']):
                            row_dict['rent_rate_sqft_pm'] = val_str
                        elif any(k in h_upper for k in ['TIMELINE', 'POSSESSION', 'AVAILABILITY', 'DATE']):
                            row_dict['timeline_possession'] = val_str
                            
                if raw_pairs:
                    row_dict['raw_remarks'] = " | ".join(raw_pairs)
                    if 'property_name' not in row_dict:
                        row_dict['property_name'] = f"{developer_name} Listing"
                    records.append(row_dict)
            continue

        # Strategy 3: Freeform Text Note fallback (e.g. Brookfield Ecospace coming up note)
        full_text_blocks = []
        for r_idx in range(len(df)):
            for c_idx in range(df.shape[1]):
                val = df.iloc[r_idx, c_idx]
                if pd.notna(val) and str(val).strip() not in ['', 'nan', 'None']:
                    full_text_blocks.append(str(val).strip())
                    
        if full_text_blocks:
            combined_text = " ".join(full_text_blocks)
            records.append({
                'developer_name': developer_name,
                'folder_category': item['folder_category'],
                'property_name': f"{developer_name} Property Note",
                'raw_remarks': combined_text,
                'source_file': rel_path,
                'source_format': 'XLSX',
                'extraction_method': f'Excel Text Note ({sheet})',
                'report_period': period
            })

    if not records:
        records.append({
            'developer_name': developer_name,
            'folder_category': item['folder_category'],
            'property_name': f"{developer_name} Record",
            'raw_remarks': 'File processed cleanly but no tabular entries detected',
            'source_file': rel_path,
            'source_format': 'XLSX',
            'extraction_method': 'Excel Inventory Record',
            'report_period': period
        })

    return records

if __name__ == '__main__':
    import glob
    files = glob.glob(r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply\**\*.xlsx', recursive=True)
    for f in files:
        item = {
            'abs_path': f,
            'rel_path': os.path.relpath(f, r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply'),
            'developer_name': os.path.relpath(f, r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply').split(os.sep)[0],
            'folder_category': os.path.relpath(f, r'c:\Users\devil\Desktop\Data-extract\BLR_Builders_Developers_Supply').split(os.sep)[0],
            'period': 'July 2026'
        }
        res = parse_excel_file(item)
        print(f"File {item['rel_path']} extracted {len(res)} records.")
        for r in res[:2]:
            print("  ", r)
