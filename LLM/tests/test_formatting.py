"""
Regression tests for how deck values are rendered.

Every case here was seen in a generated proposal. These are the last thing
between the database and a client, so a wrong value is a wrong value in front
of a customer, not just a wrong row in a table.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ppt_generator import (  # noqa: E402
    format_area,
    format_currency,
    format_months,
    format_percent,
    format_quantity,
    safe_str,
)


class TestMonths:
    def test_floats_become_months(self):
        """
        The caller looped over a list of locals reassigning the loop variable,
        which does nothing, so a client saw "Lease Term: 36.0".
        """
        assert format_months("36.0") == "36 Months"
        assert format_months("24.0") == "24 Months"
        assert format_months(6.0) == "6 Months"

    def test_singular(self):
        assert format_months(1) == "1 Month"

    def test_already_formatted_text_survives(self):
        assert format_months("36 Months") == "36 Months"

    def test_missing_falls_back(self):
        assert format_months(None, "6 Months") == "6 Months"
        assert format_months(0, "6 Months") == "6 Months"


class TestPercent:
    def test_excel_fraction_becomes_a_percentage(self):
        """Excel stores 8% as 0.08; rendered raw it read "Escalation: 0.08"."""
        assert format_percent(0.08) == "8%"
        assert format_percent(0.15) == "15%"
        assert format_percent("0.05") == "5%"

    def test_whole_numbers_are_left_alone(self):
        assert format_percent(15) == "15%"

    def test_already_formatted_survives(self):
        assert format_percent("15% every 3 years") == "15% every 3 years"

    def test_missing_falls_back(self):
        assert format_percent(None, "15%") == "15%"


class TestQuantity:
    def test_seats_when_there_is_no_area(self):
        """
        Managed office is sold by the seat. An option with 105 seats rendered
        "Area Offered: 0 Sq. Ft." because only the area field was consulted.
        """
        assert format_quantity("0", 105) == "105 Seats"
        assert format_quantity("", 1028) == "1,028 Seats"

    def test_area_wins_when_present(self):
        assert format_quantity("30,000 Sq. Ft.", None) == "30,000 Sq. Ft."
        assert format_quantity("45000", 0) == "45,000 Sq. Ft."

    def test_neither(self):
        assert format_quantity("", None) == "Available on Request"
        assert format_quantity("0", 0) == "Available on Request"


class TestExistingHelpers:
    """These already worked; pinned so the changes above do not disturb them."""

    def test_safe_str_swallows_placeholders(self):
        assert safe_str("nan") == ""
        assert safe_str(None, "fallback") == "fallback"
        assert safe_str("  Prestige  ") == "Prestige"

    def test_currency(self):
        assert format_currency(95) == "INR 95 / Sq. Ft. / Month"
        assert format_currency(None) == "Quote on Request"
        assert format_currency("Included in rent") == "Included in rent"

    def test_area(self):
        assert format_area("45000") == "45,000 Sq. Ft."
        assert format_area(None) == "Available on Request"
