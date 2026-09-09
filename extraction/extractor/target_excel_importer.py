"""
Target Excel Importer — Reads the authoritative 'BLR - Managed Office Space Supply 2026.xlsx'
and transposes all 13 micro-market sheets into flat normalized records.

This produces the GOLDEN dataset with 100% accuracy — no guessing, no noise.
"""
import pandas as pd
import os
import re

# The 33 Particulars rows in each micro-market sheet (transposed format)
# Maps: Particulars label -> normalized field name
PARTICULARS_TO_FIELD = {
    'Building Name': 'building_name',
    'Address': 'address_location',
    'Building Perspective/ Photograph': 'building_perspective_photo',
    'Building Details': 'building_details',
    'Developer/ Landlord': 'developer_landlord',
    'Building Structure': 'building_structure',
    'Total Building Size (SBA) [In Sq. Ft.]': 'total_building_size_sqft',
    'Average Floor Plate Size [In Sq. Ft.]': 'average_floor_plate_sqft',
    'Floor Plate Efficiency [Approx.]': 'floor_plate_efficiency',
    'Power [In KVA]': 'power_kva',
    'Power Back-up': 'power_backup',
    'Proposed Space': 'proposed_space',
    'Offered Seats / Area Offered [In Sq. Ft.]': 'available_inventory_sqft',
    'Floor Offered': 'floor_offered',
    'Status': 'status',
    'Fit-out Details': 'fitout_details',
    'Timeline': 'timeline',
    'Car Parking Ratio': 'car_parking_ratio',
    'Commercial Terms': 'commercial_terms',
    'Quoted Rental [INR/ Sq. Ft./ Month]': 'quoted_rental_sqft_pm',
    'CAM Charges [INR/ Sq. Ft./ Month]': 'cam_charges_sqft_pm',
    'Car Parking Charges [INR/ Slot/ Month]': 'car_parking_charges',
    'Rental Escalation [% In Months]': 'rental_escalation',
    'Interest Free Refundable Security Deposit [In Months]': 'security_deposit_months',
    'Lease Tenure [In Months]': 'lease_tenure_months',
    'Lock-In Period [In Months]': 'lock_in_period_months',
    'Notice Period for Termination [In Months]': 'notice_period_months',
    'Occupancy Certificate Available (Yes / No)': 'occupancy_certificate',
    'Location Map': 'location_map',
    'Contact Details': 'contact_details',
    'Contact Person': 'contact_person',
    'Contact Number': 'contact_number',
    'Official Email ID': 'official_email',
}

# Standard micromarket sheet names in the target Excel
MICROMARKET_SHEETS = [
    'CBD', 'Indiranagar', 'KRM', 'HSR Layout', 'ORR',
    'WF', 'North-BLR', 'E-City', 'BG Road', 'JP-Nagar',
    'Jayanagar', 'Kanakapura Rd', 'BTM'
]

# Map Master File categorization names to standard sheet names
MASTER_TO_SHEET_MAP = {
    'CBD': 'CBD',
    'SBD - Indiranagar': 'Indiranagar',
    'Indiranagar': 'Indiranagar',
    'Koramanagala': 'KRM',
    'Koramangala': 'KRM',
    'KRM': 'KRM',
    'HSR Layout': 'HSR Layout',
    'HSR': 'HSR Layout',
    'ORR': 'ORR',
    'Outer Ring Road': 'ORR',
    'Whitefield': 'WF',
    'WF': 'WF',
    'North-BLR': 'North-BLR',
    'North Bengaluru': 'North-BLR',
    'E-City': 'E-City',
    'Electronic City': 'E-City',
    'Bannerghatta': 'BG Road',
    'BG Road': 'BG Road',
    'JP Nagar': 'JP-Nagar',
    'JP-Nagar': 'JP-Nagar',
    'Jayanagar': 'Jayanagar',
    'Kanakapura Road': 'Kanakapura Rd',
    'Kanakapura Rd': 'Kanakapura Rd',
    'BTM Layout': 'BTM',
    'BTM': 'BTM',
}


def clean_value(val):
    """Clean a cell value — convert nan/None to empty string, strip whitespace."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    if s.lower() in ('nan', 'none', 'n/a'):
        return ''
    return s


def extract_numeric(val_str):
    """Extract numeric value from strings like '15,000', '1,26,408 Sqft', 'Rs. 140/-'."""
    if not val_str:
        return None
    cleaned = str(val_str).replace(',', '').strip()
    match = re.search(r'(\d+(?:\.\d+)?)', cleaned)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def import_from_micromarket_sheets(excel_path):
    """
    Reads all 13 micro-market transposed sheets from the target Excel.
    Each sheet has:
      - Column A: 'Particulars' (33 row labels)
      - Columns B onwards: 'Option 1', 'Option 2', ... (one per property)
    
    Transposes each Option column into a flat record dict.
    Returns list of normalized record dicts.
    """
    xl = pd.ExcelFile(excel_path)
    all_records = []
    
    for sheet_name in MICROMARKET_SHEETS:
        if sheet_name not in xl.sheet_names:
            print(f"  [SKIP] Sheet '{sheet_name}' not found in workbook")
            continue
        
        df = pd.read_excel(xl, sheet_name=sheet_name)
        
        if 'Particulars' not in df.columns:
            print(f"  [SKIP] Sheet '{sheet_name}' has no 'Particulars' column")
            continue
        
        # Build particulars index: row_index -> field_name
        particulars_index = {}
        for idx, row in df.iterrows():
            part_label = clean_value(row.get('Particulars', ''))
            if part_label and part_label in PARTICULARS_TO_FIELD:
                particulars_index[idx] = PARTICULARS_TO_FIELD[part_label]
        
        # Get option columns (everything except 'Particulars')
        option_cols = [c for c in df.columns if c != 'Particulars' and str(c).startswith('Option')]
        
        print(f"  [IMPORT] Sheet '{sheet_name}': {len(option_cols)} options, {len(particulars_index)} mapped fields")
        
        for opt_col in option_cols:
            record = {
                'micromarket_category': sheet_name,
                'option_name': str(opt_col),
                'source_file': os.path.basename(excel_path),
                'source_format': 'TARGET_EXCEL',
                'extraction_method': f'Target Excel Import ({sheet_name})',
                'report_period': 'July 2026',
            }
            
            has_any_value = False
            for row_idx, field_name in particulars_index.items():
                val = clean_value(df.at[row_idx, opt_col])
                if val:
                    record[field_name] = val
                    has_any_value = True
            
            # Only add records that have at least a building name or developer
            building_name = record.get('building_name', '')
            developer = record.get('developer_landlord', '')
            
            if has_any_value and (building_name or developer):
                # Enrich with computed fields
                record.setdefault('developer_name', developer)
                record.setdefault('folder_category', sheet_name)
                
                # Clean up available inventory to numeric
                area_raw = record.get('available_inventory_sqft', '')
                area_num = extract_numeric(area_raw)
                if area_num is not None:
                    record['available_inventory_sqft'] = area_num
                
                all_records.append(record)
    
    return all_records


def import_from_master_file(excel_path):
    """
    Reads the 'Master File' sheet which has a flat table with:
    BLR - Categorization | Options | Operators | Building Name | Address/Location | 
    Available Inventory | Price Per Seats | Floor Occupied
    
    Returns list of record dicts (basic info only — detailed data comes from micro-market sheets).
    """
    xl = pd.ExcelFile(excel_path)
    
    if 'Master File' not in xl.sheet_names:
        return []
    
    df = pd.read_excel(xl, 'Master File', dtype=str).fillna('')
    records = []
    
    for _, row in df.iterrows():
        cat = clean_value(row.get('BLR - Categorization', ''))
        building = clean_value(row.get('Building Name', ''))
        
        if not building:
            continue
        
        # Map categorization to standard micromarket
        std_mm = MASTER_TO_SHEET_MAP.get(cat, cat)
        
        record = {
            'micromarket_category': std_mm,
            'option_name': clean_value(row.get('Options', '')),
            'developer_landlord': clean_value(row.get('Operators', '')),
            'building_name': building,
            'address_location': clean_value(row.get('Address/Loaction', row.get('Address/Location', ''))),
            'available_inventory_sqft': clean_value(row.get('Available Inventory', '')),
            'quoted_rental_sqft_pm': clean_value(row.get('Price  Per Seats', row.get('Price Per Seats', ''))),
            'floor_offered': clean_value(row.get('Floor Occupied', '')),
            'source_file': os.path.basename(excel_path),
            'source_format': 'TARGET_EXCEL_MASTER',
            'extraction_method': 'Target Excel Master File Import',
            'report_period': 'July 2026',
        }
        records.append(record)
    
    return records


def import_target_excel(excel_path):
    """
    Full import: reads micro-market sheets (detailed 33-field data).
    The Master File uses a different naming convention (e.g. "The Pavillion" vs 
    "Wework - The Pavillion") and only has 8 columns, so we use micro-market 
    sheets as the sole authoritative source.
    
    Returns: list of fully populated record dicts
    """
    print(f"[TARGET EXCEL IMPORT] Reading: {excel_path}")
    
    # Primary: detailed data from micro-market transposed sheets (all 33 fields)
    mm_records = import_from_micromarket_sheets(excel_path)
    print(f"  -> Imported {len(mm_records)} detailed records from micro-market sheets")
    
    # Enrich records with operator info from Master File where possible
    master_records = import_from_master_file(excel_path)
    print(f"  -> Read {len(master_records)} records from Master File for cross-reference")
    
    # Build operator lookup from Master File: (micromarket, option_num) -> operator
    operator_lookup = {}
    for rec in master_records:
        mm = rec.get('micromarket_category', '')
        opt = rec.get('option_name', '')
        operator = rec.get('developer_landlord', '')
        if mm and opt and operator:
            operator_lookup[(mm, opt)] = operator
    
    # Enrich mm_records with operator names where the developer field might be
    # more specific (Master File has the operator/brand name like "Wework", "Urban Vault")
    for rec in mm_records:
        mm = rec.get('micromarket_category', '')
        opt = rec.get('option_name', '')
        operator = operator_lookup.get((mm, opt), '')
        if operator:
            rec['operator_brand'] = operator
    
    final_records = mm_records
    
    print(f"  -> TOTAL: {len(final_records)} clean records with full 33-field data")
    
    # Summary by micromarket
    from collections import Counter
    mm_dist = Counter(r.get('micromarket_category', 'Unknown') for r in final_records)
    print(f"  -> Distribution: {dict(sorted(mm_dist.items(), key=lambda x: -x[1]))}")
    
    return final_records


if __name__ == '__main__':
    import sys
    excel_path = sys.argv[1] if len(sys.argv) > 1 else r'c:\Users\devil\Desktop\full automation\BLR - Managed Office Space Supply 2026.xlsx'
    records = import_target_excel(excel_path)
    
    # Quick quality check
    print(f"\n=== QUALITY CHECK ===")
    has_name = sum(1 for r in records if r.get('building_name'))
    has_dev = sum(1 for r in records if r.get('developer_landlord'))
    has_area = sum(1 for r in records if extract_numeric(str(r.get('available_inventory_sqft', ''))) is not None)
    has_rent = sum(1 for r in records if extract_numeric(str(r.get('quoted_rental_sqft_pm', ''))) is not None)
    print(f"Records with building_name: {has_name}/{len(records)}")
    print(f"Records with developer: {has_dev}/{len(records)}")
    print(f"Records with numeric area: {has_area}/{len(records)}")
    print(f"Records with numeric rent: {has_rent}/{len(records)}")
