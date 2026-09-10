"""
The spreadsheet export, and the formatting it shares with the deck.

The point of the shared formatter is that a client who receives both files
cannot find them disagreeing, so these assert on the values that reach the
page rather than on the writer.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import load_workbook  # noqa: E402

from services import deck_excel  # noqa: E402
from services.deck_service import _fmt_int, _fmt_sqft  # noqa: E402


class TestFormatters:
    def test_zero_area_is_blank_not_a_figure(self):
        """
        A seat-based option has no area. Printing the zero put
        "Area Offered: 0 Sq. Ft." on a suite that had 40 desks available.
        """
        assert _fmt_sqft(0) == ""
        assert _fmt_sqft(None) == ""
        assert _fmt_int(0) == ""

    def test_indian_digit_grouping(self):
        assert _fmt_sqft(100000) == "1,00,000 Sq. Ft."
        assert _fmt_sqft(30000) == "30,000 Sq. Ft."
        assert _fmt_int(7000) == "7,000"


class TestWorkbook:
    RECORDS = [
        {"building_name": "Incubex HSR39", "micromarket_category": "HSR Layout",
         "developer_landlord": "Incubex", "_product_label": "Co-working",
         "available_inventory_sqft": "30,000 Sq. Ft.", "offered_seats": "",
         "quoted_rental_sqft_pm": "INR 7,000 / seat / month", "status": "Fully Furnished",
         "timeline": "Immediate"},
        {"building_name": "Workshaala Vista", "micromarket_category": "HSR Layout",
         "developer_landlord": "Workshaala", "_product_label": "Co-working",
         "available_inventory_sqft": "", "offered_seats": 40,
         "quoted_rental_sqft_pm": "INR 6,499 / seat / month", "status": "Fully Furnished",
         "timeline": "Immediate"},
    ]
    CRITERIA = {"title": "8 desks in HSR",
                "product_note": "8 seats is under 15, so this is quoted as co-working."}

    def build(self):
        path = os.path.join(tempfile.mkdtemp(), "options.xlsx")
        deck_excel.build(self.RECORDS, self.CRITERIA, "Acme Labs",
                         "8 desks in HSR for a small team", path)
        return load_workbook(path)

    def test_both_sheets_are_written(self):
        wb = self.build()
        assert wb.sheetnames == ["Requirement", "Options"]

    def test_one_row_per_option_numbered_in_order(self):
        ws = self.build()["Options"]
        assert ws.max_row == len(self.RECORDS) + 1          # + the header
        assert ws.cell(row=2, column=1).value == "1"
        assert ws.cell(row=2, column=2).value == "Incubex HSR39"
        assert ws.cell(row=3, column=1).value == "2"

    def test_the_product_the_requirement_earned_is_on_every_row(self):
        ws = self.build()["Options"]
        product = [c[0].value for c in ws.iter_rows(min_row=2, min_col=6, max_col=6)]
        assert product == ["Co-working", "Co-working"]

    def test_a_seat_option_carries_seats_and_no_zero_area(self):
        ws = self.build()["Options"]
        headers = [c.value for c in ws[1]]
        area = ws.cell(row=3, column=headers.index("Available Area") + 1).value
        seats = ws.cell(row=3, column=headers.index("Seats Offered") + 1).value
        assert area in (None, "")
        assert seats == "40"

    def test_the_brief_records_who_and_why(self):
        ws = self.build()["Requirement"]
        text = "\n".join(
            str(cell.value) for row in ws.iter_rows(values_only=False)
            for cell in row if cell.value)
        assert "Acme Labs" in text
        assert "8 desks in HSR for a small team" in text
        assert "under 15" in text
        assert "Options included" in text

    def test_the_header_row_is_frozen_and_filterable(self):
        ws = self.build()["Options"]
        assert ws.freeze_panes == "C2"
        assert ws.auto_filter.ref.startswith("A1:")
