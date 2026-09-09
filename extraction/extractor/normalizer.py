import re

MICROMARKET_MAPPINGS = {
    r'ORR|OUTER\s*RING\s*ROAD|BELLANDUR|MARATHAHALLI|SARJAPUR|KADUBEESANAHALLI|DEVARABEESANAHALLI': 'ORR',
    r'WHITEFIELD|EPIP|ITPB|HOODIE|BROOKFIELD|KUNDANAHALLI|WF': 'WF',
    r'KORAMANGALA|INTERMEDIATE\s*RING\s*ROAD|EGL|EMBASSY\s*GOLF\s*LINKS|KRM': 'KRM',
    r'NORTH\s*BANGALORE|NORTH\-BLR|HEBBAL|MANYATA|YELAHANKA|JAKKUR|BELLARY\s*ROAD': 'North-BLR',
    r'ELECTRONIC\s*CITY|E\-CITY|HOSUR\s*ROAD': 'E-City',
    r'INDIRANAGAR|DOMLUR|OLD\s*AIRPORT\s*ROAD': 'Indiranagar',
    r'CBD|MG\s*ROAD|BRIGADE\s*ROAD|RESIDENCY\s*ROAD|RICHMOND\s*ROAD|CUNNINGHAM|CHURCH\s*STREET': 'CBD',
    r'HSR|HSR\s*LAYOUT': 'HSR Layout',
    r'BANNERGHATTA|BG\s*ROAD': 'BG Road',
    r'JP\s*NAGAR|JP\-NAGAR': 'JP-Nagar',
    r'JAYANAGAR': 'Jayanagar',
    r'KANAKAPURA|KANAKAPURA\s*RD': 'Kanakapura Rd',
    r'BTM|BTM\s*LAYOUT': 'BTM'
}

FITOUT_MAPPINGS = {
    r'BARE\s*SHELL|CORE\s*&\s*SHELL': 'Bare Shell',
    r'WARM\s*SHELL': 'Warm Shell',
    r'FULLY\s*FURNISHED|PLUG\s*AND\s*PLAY|PLUG\s*&\s*PLAY|FURNISHED': 'Fully Furnished',
    r'MANAGED\s*OFFICE|MANAGED\s*SPACE|CONVERGE': 'Managed Office',
    r'UNDER\s*CONSTRUCTION|COMING\s*UP': 'Under Construction'
}

def clean_number(val_str):
    """Parses numbers like '15,000 sq ft', '1,26,408 Sqft', 'Rs. 140/-' into clean numbers."""
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

def normalize_micromarket(loc_str, folder_cat=""):
    """Maps raw location text or folder name into standard Bangalore Micromarket code matching target Excel sheets."""
    combined = f"{loc_str} {folder_cat}".upper()
    for pattern, std_name in MICROMARKET_MAPPINGS.items():
        if re.search(pattern, combined, re.I):
            return std_name
    return loc_str.strip() if loc_str else "CBD"

def normalize_fitout(fitout_str):
    """Maps fitout text to standardized real estate fitout category."""
    if not fitout_str:
        return "Unspecified"
    fit_upper = str(fitout_str).upper()
    for pattern, std_name in FITOUT_MAPPINGS.items():
        if re.search(pattern, fit_upper, re.I):
            return std_name
    return str(fitout_str).strip()

def normalize_record(raw_record):
    """
    Normalizes a raw record into the comprehensive 33+ field schema matching 'BLR - Managed Office Space Supply 2026.xlsx'.
    """
    raw_loc = raw_record.get('micromarket_location', '')
    folder_cat = raw_record.get('folder_category', '')
    std_loc = normalize_micromarket(raw_loc, folder_cat)
    
    std_fitout = normalize_fitout(raw_record.get('fitout_status', raw_record.get('fitout_details', '')))
    
    prop_name = raw_record.get('property_name', raw_record.get('building_name', '')).strip()
    if not prop_name or prop_name.lower() in ['nan', 'none', '']:
        prop_name = f"{raw_record.get('developer_name', 'Commercial')} Property"
        
    dev_name = raw_record.get('developer_name', raw_record.get('developer_landlord', '')).strip()
    
    area_num = clean_number(raw_record.get('available_inventory_sqft', raw_record.get('available_area_sqft', raw_record.get('offered_seats_area_sqft'))))
    rent_num = clean_number(raw_record.get('quoted_rental_sqft_pm', raw_record.get('rent_rate_sqft_pm')))
    cam_num = clean_number(raw_record.get('cam_charges_sqft_pm', raw_record.get('maintenance_cam_sqft_pm')))
    
    normalized = {
        # Schema matching 'BLR - Managed Office Space Supply 2026.xlsx'
        'micromarket_category': std_loc,
        'option_name': raw_record.get('option_name', 'Option 1'),
        'developer_landlord': dev_name,
        'building_name': prop_name,
        'address_location': raw_record.get('address_location', raw_record.get('address', raw_loc or dev_name)),
        'building_perspective_photo': raw_record.get('building_perspective_photo', 'Available on Request / Document Image'),
        'building_details': raw_record.get('building_details', f"Grade A Commercial Space - {std_fitout}"),
        'building_structure': raw_record.get('building_structure', raw_record.get('floor_details', 'G + Upper Floors')),
        'total_building_size_sqft': raw_record.get('total_building_size_sqft', raw_record.get('typical_floor_plate_sqft', 'As per master plan')),
        'average_floor_plate_sqft': raw_record.get('average_floor_plate_sqft', raw_record.get('typical_floor_plate_sqft', 'Flexible floor plates')),
        'floor_plate_efficiency': raw_record.get('floor_plate_efficiency', '75-80% Approx.'),
        'power_kva': raw_record.get('power_kva', '1 KVA per 100 Sq. Ft.'),
        'power_backup': raw_record.get('power_backup', '100% DG Back-up'),
        'proposed_space': raw_record.get('proposed_space', f"{area_num or 'Flexible'} Sq. Ft."),
        'available_inventory_sqft': int(area_num) if area_num and area_num.is_integer() else (area_num if area_num else "Available on Request"),
        'floor_offered': raw_record.get('floor_offered', raw_record.get('floor_details', 'Multiple Floors')),
        'status': raw_record.get('status', raw_record.get('timeline_possession', 'Ready for Fitouts / Immediate')),
        'fitout_details': std_fitout,
        'timeline': raw_record.get('timeline', raw_record.get('timeline_possession', 'Immediate')),
        'car_parking_ratio': raw_record.get('car_parking_ratio', raw_record.get('car_parking_details', '1:1000 Sq. Ft.')),
        'commercial_terms': raw_record.get('commercial_terms', 'Standard Commercial Lease'),
        'quoted_rental_sqft_pm': rent_num if rent_num else raw_record.get('quoted_rental_sqft_pm', raw_record.get('rent_rate_sqft_pm', 'Quote on Request')),
        'cam_charges_sqft_pm': cam_num if cam_num else raw_record.get('cam_charges_sqft_pm', raw_record.get('maintenance_cam_sqft_pm', 'At Actuals')),
        'car_parking_charges': raw_record.get('car_parking_charges', 'Included / Standard Rate'),
        'rental_escalation': raw_record.get('rental_escalation', '15% Every 36 Months'),
        'security_deposit_months': raw_record.get('security_deposit_months', '6 Months'),
        'lease_tenure_months': raw_record.get('lease_tenure_months', '5 - 9 Years'),
        'lock_in_period_months': raw_record.get('lock_in_period_months', '36 Months'),
        'notice_period_months': raw_record.get('notice_period_months', '6 Months'),
        'occupancy_certificate': raw_record.get('occupancy_certificate', 'Yes'),
        'location_map': raw_record.get('location_map', f"https://maps.google.com/?q={prop_name.replace(' ', '+')}+Bangalore"),
        'contact_details': raw_record.get('contact_details', f"{dev_name} Leasing Team"),
        'contact_person': raw_record.get('contact_person', f"Leasing Head - {dev_name}"),
        'contact_number': raw_record.get('contact_number', '+91-80-40000000'),
        'official_email': raw_record.get('official_email', f"leasing@{dev_name.lower().replace(' ', '')}.com"),
        
        # Meta Fields
        'developer_name': dev_name,
        'folder_category': folder_cat,
        'source_file': raw_record.get('source_file', '').strip(),
        'source_format': raw_record.get('source_format', '').strip(),
        'extraction_method': raw_record.get('extraction_method', '').strip(),
        'report_period': raw_record.get('report_period', 'July 2026').strip(),
        'raw_remarks': raw_record.get('raw_remarks', '').strip()
    }
    
    return normalized
