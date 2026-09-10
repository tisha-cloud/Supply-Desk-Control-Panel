"""
The same shortlist as the deck, written as a spreadsheet instead.

Some clients want the options as a grid they can sort and annotate rather than
as a presentation. Both formats are built from the identical option records,
so a figure can never differ between the .pptx and the .xlsx a client is sent
side by side - if the deck says 30,000 Sq. Ft., so does the sheet.
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
BODY_FONT = Font(size=10)
LABEL_FONT = Font(bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# (heading, record key, column width). Order follows the option slide, so the
# sheet reads as the same document in a different shape.
COLUMNS = [
    ("Option", "_option_no", 8),
    ("Building Name", "building_name", 30),
    ("Micro-market", "micromarket_category", 14),
    ("Developer / Landlord", "developer_landlord", 24),
    ("Address / Location", "address_location", 34),
    ("Product", "_product_label", 16),
    ("Building Structure", "building_structure", 20),
    ("Total Building Size", "total_building_size_sqft", 18),
    ("Avg. Floor Plate", "average_floor_plate_sqft", 16),
    ("Floor Offered", "floor_offered", 18),
    ("Available Area", "available_inventory_sqft", 16),
    ("Seats Offered", "offered_seats", 12),
    ("Condition", "status", 18),
    ("Timeline", "timeline", 14),
    ("Quoted Rental", "quoted_rental_sqft_pm", 22),
    ("CAM / Sq. Ft. / Month", "cam_charges_sqft_pm", 16),
    ("Car Park Ratio", "car_parking_ratio", 14),
    ("Car Park Charges", "car_parking_charges", 16),
    ("Rental Escalation", "rental_escalation", 14),
    ("Security Deposit", "security_deposit_months", 14),
    ("Lease Tenure", "lease_tenure_months", 14),
    ("Lock-in", "lock_in_period_months", 12),
    ("Notice Period", "notice_period_months", 13),
    ("OC Available", "occupancy_certificate", 12),
    ("Contact", "contact_person", 20),
    ("Phone", "contact_number", 16),
    ("Email", "official_email", 26),
]

WRAP = {"Address / Location", "Building Structure", "Floor Offered", "Condition"}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def build(records: List[Dict[str, Any]],
          criteria: Dict[str, Any],
          client_name: str,
          query: str,
          out_path: str) -> str:
    """Write the options workbook and return the path it was written to."""
    wb = Workbook()

    brief = wb.active
    brief.title = "Requirement"
    _write_brief(brief, records, criteria, client_name, query)

    ws = wb.create_sheet("Options")
    ws.append([heading for heading, _, _ in COLUMNS])
    for index, record in enumerate(records, start=1):
        row = dict(record)
        row["_option_no"] = index
        ws.append([_cell(row.get(key)) for _, key, _ in COLUMNS])

    for index, (heading, _, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
        cell = ws.cell(row=1, column=index)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(COLUMNS)):
        for cell in row:
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = Alignment(
                vertical="center",
                wrap_text=COLUMNS[cell.column - 1][0] in WRAP)

    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "C2"
    if ws.max_row > 1:
        ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(COLUMNS)), ws.max_row)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    wb.save(out_path)
    return out_path


def _write_brief(ws, records, criteria, client_name, query) -> None:
    """The cover sheet: who it is for, what was asked, and what was counted."""
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 78

    ws["A1"] = criteria.get("title") or "Office Space Options"
    ws["A1"].font = TITLE_FONT
    ws.append([])

    def line(label: str, value: Any) -> None:
        ws.append([label, _cell(value)])
        ws.cell(row=ws.max_row, column=1).font = LABEL_FONT
        ws.cell(row=ws.max_row, column=2).font = BODY_FONT
        ws.cell(row=ws.max_row, column=2).alignment = Alignment(
            vertical="top", wrap_text=True)

    line("Prepared for", client_name)
    line("Prepared on", datetime.now().strftime("%d %b %Y"))
    line("Requirement", query)
    if criteria.get("product_note"):
        line("Product", criteria["product_note"])
    line("Options included", len(records))

    areas = [_as_number(r.get("available_inventory_sqft")) for r in records]
    seats = [_as_number(r.get("offered_seats")) for r in records]
    if any(areas):
        line("Total available area", "{:,} Sq. Ft.".format(int(sum(areas))))
    if any(seats):
        line("Total seats offered", "{:,}".format(int(sum(seats))))

    markets = sorted({r.get("micromarket_category") for r in records if r.get("micromarket_category")})
    if markets:
        line("Micro-markets", ", ".join(markets))
    landlords = sorted({r.get("developer_landlord") for r in records if r.get("developer_landlord")})
    if landlords:
        line("Landlords / operators", ", ".join(landlords))

    ws.append([])
    ws.append(["Every figure on the Options sheet is taken from the supply database "
               "as at the date above."])
    ws.cell(row=ws.max_row, column=1).font = Font(size=9, italic=True, color="7F7F7F")


def _as_number(value: Any) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(value)) or 0)
    except ValueError:
        return 0.0
