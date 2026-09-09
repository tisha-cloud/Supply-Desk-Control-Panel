import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import pandas as pd
import os

PARTICULARS_LIST = [
    ('Building Name', 'building_name'),
    ('Address', 'address_location'),
    ('Building Perspective/ Photograph', 'building_perspective_photo'),
    ('Building Details', 'building_details'),
    ('Developer/ Landlord', 'developer_landlord'),
    ('Building Structure', 'building_structure'),
    ('Total Building Size (SBA) [In Sq. Ft.]', 'total_building_size_sqft'),
    ('Average Floor Plate Size [In Sq. Ft.]', 'average_floor_plate_sqft'),
    ('Floor Plate Efficiency [Approx.]', 'floor_plate_efficiency'),
    ('Power [In KVA]', 'power_kva'),
    ('Power Back-up', 'power_backup'),
    ('Proposed Space', 'proposed_space'),
    ('Offered Seats / Area Offered [In Sq. Ft.]', 'available_inventory_sqft'),
    ('Floor Offered', 'floor_offered'),
    ('Status', 'status'),
    ('Fit-out Details', 'fitout_details'),
    ('Timeline', 'timeline'),
    ('Car Parking Ratio', 'car_parking_ratio'),
    ('Commercial Terms', 'commercial_terms'),
    ('Quoted Rental [INR/ Sq. Ft./ Month]', 'quoted_rental_sqft_pm'),
    ('CAM Charges [INR/ Sq. Ft./ Month]', 'cam_charges_sqft_pm'),
    ('Car Parking Charges [INR/ Slot/ Month]', 'car_parking_charges'),
    ('Rental Escalation [% In Months]', 'rental_escalation'),
    ('Interest Free Refundable Security Deposit [In Months]', 'security_deposit_months'),
    ('Lease Tenure [In Months]', 'lease_tenure_months'),
    ('Lock-In Period [In Months]', 'lock_in_period_months'),
    ('Notice Period for Termination [In Months]', 'notice_period_months'),
    ('Occupancy Certificate Available (Yes / No)', 'occupancy_certificate'),
    ('Location Map', 'location_map'),
    ('Contact Details', 'contact_details'),
    ('Contact Person', 'contact_person'),
    ('Contact Number', 'contact_number'),
    ('Official Email ID', 'official_email')
]

MICROMARKET_SHEETS = [
    'CBD', 'Indiranagar', 'KRM', 'HSR Layout', 'ORR', 
    'WF', 'North-BLR', 'E-City', 'BG Road', 'JP-Nagar', 
    'Jayanagar', 'Kanakapura Rd', 'BTM'
]

def export_target_excel(normalized_records, output_excel_path):
    """
    Generates a multi-sheet Excel workbook structured EXACTLY like 'BLR - Managed Office Space Supply 2026.xlsx'.
    Includes:
    1. Master File sheet
    2. BLR - Categorization sheet
    3. Micro-Market Transposed Sheets (CBD, Indiranagar, ORR, WF, etc.)
    4. Operators sheet
    5. All Extracted Data (Flat master dataset)
    """
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    particulars_font = Font(name="Segoe UI", size=10, bold=True, color="1F4E79")
    cell_font = Font(name="Segoe UI", size=9)
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    # -------------------------------------------------------------
    # Sheet 1: Master File
    # -------------------------------------------------------------
    ws_master = wb.create_sheet(title="Master File")
    master_headers = [
        'BLR - Categorization', 'Options', 'Operators', 'Building Name', 
        'Address/Loaction', 'Available Inventory', 'Price  Per Seats', 'Floor Occupied'
    ]
    ws_master.append(master_headers)
    for col_num, h in enumerate(master_headers, 1):
        cell = ws_master.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Populate Master File rows
    for idx, rec in enumerate(normalized_records, 1):
        option_label = f"Option {idx}"
        rec['option_name'] = option_label
        ws_master.append([
            rec.get('micromarket_category', 'CBD'),
            option_label,
            rec.get('developer_landlord', ''),
            rec.get('building_name', ''),
            rec.get('address_location', ''),
            rec.get('available_inventory_sqft', ''),
            rec.get('quoted_rental_sqft_pm', ''),
            rec.get('floor_offered', '')
        ])

    for row in ws_master.iter_rows(min_row=2, max_row=ws_master.max_row, min_col=1, max_col=len(master_headers)):
        for cell in row:
            cell.font = cell_font
            cell.border = thin_border

    # -------------------------------------------------------------
    # Sheet 2: Micro-Market Transposed Sheets
    # -------------------------------------------------------------
    records_by_mm = {}
    for r in normalized_records:
        mm = r.get('micromarket_category', 'CBD')
        if mm not in records_by_mm:
            records_by_mm[mm] = []
        records_by_mm[mm].append(r)

    for mm_sheet_name in MICROMARKET_SHEETS:
        ws_mm = wb.create_sheet(title=mm_sheet_name)
        mm_recs = records_by_mm.get(mm_sheet_name, [])
        
        # Header row: Particulars | Option 1 | Option 2 | ...
        headers = ['Particulars'] + [f"Option {i}" for i in range(1, len(mm_recs) + 1)]
        ws_mm.append(headers)
        
        for col_num, h in enumerate(headers, 1):
            cell = ws_mm.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Fill 33 Particulars rows
        for p_idx, (p_label, p_key) in enumerate(PARTICULARS_LIST, start=2):
            row_data = [p_label]
            for rec in mm_recs:
                row_data.append(str(rec.get(p_key, '')))
            ws_mm.append(row_data)

        # Style sheet cells
        for row_idx in range(2, ws_mm.max_row + 1):
            cell_p = ws_mm.cell(row=row_idx, column=1)
            cell_p.font = particulars_font
            cell_p.fill = PatternFill(start_color="F2F2F2", fill_type="solid")
            cell_p.border = thin_border
            
            for col_idx in range(2, ws_mm.max_column + 1):
                c = ws_mm.cell(row=row_idx, column=col_idx)
                c.font = cell_font
                c.border = thin_border
                c.alignment = Alignment(wrap_text=True)

    # -------------------------------------------------------------
    # Sheet 3: Operators
    # -------------------------------------------------------------
    ws_op = wb.create_sheet(title="Operators")
    op_headers = ['Sl. No', 'Managed - Coworking Operators', 'Contact Person', 'Contact Number', 'Email ID', 'Availability Status']
    ws_op.append(op_headers)
    for col_num, h in enumerate(op_headers, 1):
        cell = ws_op.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    unique_devs = {}
    for r in normalized_records:
        dev = r.get('developer_landlord', 'Unknown Developer')
        if dev not in unique_devs:
            unique_devs[dev] = {
                'contact_person': r.get('contact_person', ''),
                'contact_number': r.get('contact_number', ''),
                'email': r.get('official_email', ''),
                'status': 'Active Supply'
            }

    for idx, (dev, info) in enumerate(unique_devs.items(), 1):
        ws_op.append([
            idx, dev, info['contact_person'], info['contact_number'], info['email'], info['status']
        ])

    for row in ws_op.iter_rows(min_row=2, max_row=ws_op.max_row, min_col=1, max_col=len(op_headers)):
        for cell in row:
            cell.font = cell_font
            cell.border = thin_border

    # -------------------------------------------------------------
    # Sheet 4: BLR - Categorization
    # -------------------------------------------------------------
    ws_cat = wb.create_sheet(title="BLR - Categorization")
    cat_cols = ['CBD (Central Business District)', 'North Bengaluru', 'East Bengaluru', 'South Bengaluru', 'ORR (Outer Ring Road)', 'West Bengaluru']
    ws_cat.append(cat_cols)
    for col_num, h in enumerate(cat_cols, 1):
        cell = ws_cat.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    cat_data = [
        ['MG Road', 'Manyata Tech Park (Nagawara)', 'Whitefield', 'Koramangala', 'Bellandur', 'Rajajinagar'],
        ['Brigade Road', 'Hebbal', 'ITPL', 'HSR Layout', 'Kadubeesanahalli', 'Yeshwanthpur'],
        ['Residency Road', 'Kirloskar Business Park', 'EPIP Zone', 'Electronic City (Phase 1 & 2)', 'Devarabeesanahalli', 'Malleshwaram'],
        ['Lavelle Road', 'Yelahanka', 'Hoodi', 'JP Nagar', 'Marathahalli', 'Tumkur Road'],
        ['Cunningham Road', 'Jakkur', 'Kundanahalli', 'Jayanagar', 'Sarjapur Road', 'Peenya']
    ]
    for row in cat_data:
        ws_cat.append(row)

    for row in ws_cat.iter_rows(min_row=2, max_row=ws_cat.max_row, min_col=1, max_col=len(cat_cols)):
        for cell in row:
            cell.font = cell_font
            cell.border = thin_border

    # -------------------------------------------------------------
    # Sheet 5: All Extracted Data (Flat dataframe table)
    # -------------------------------------------------------------
    ws_all = wb.create_sheet(title="All Extracted Data")
    df_all = pd.DataFrame(normalized_records)
    all_headers = df_all.columns.tolist()
    ws_all.append(all_headers)
    
    for col_num, h in enumerate(all_headers, 1):
        cell = ws_all.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in df_all.itertuples(index=False):
        ws_all.append(list(r))

    for row in ws_all.iter_rows(min_row=2, max_row=ws_all.max_row, min_col=1, max_col=len(all_headers)):
        for cell in row:
            cell.font = cell_font
            cell.border = thin_border

    # Adjust Column Widths for readability across all sheets
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col[:50]:
                if cell.value:
                    val_str = str(cell.value)
                    max_len = max(max_len, min(len(val_str), 50))
            sheet.column_dimensions[col_letter].width = max(max_len + 3, 15)

    wb.save(output_excel_path)
    print(f"   -> Created Multi-Sheet Target Excel Workbook at: {output_excel_path}")
