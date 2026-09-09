"""
Regression tests for the normalisation layer.

Every case here is a defect that was found in real output and verified by
running the code against live data - not a hypothetical. The docstrings say
what went wrong so a future change that reintroduces it is obvious.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extractor import schema  # noqa: E402


# --------------------------------------------------------------- condition
class TestCondition:
    def test_semi_furnished_is_not_fully_furnished(self):
        """
        The worst normalisation bug found: the bare `furnished` alternative in
        the Fully Furnished rule swallowed "Semi-furnished", so a semi-furnished
        floor was marketed to a client as fully furnished.
        """
        assert schema.normalize_condition("Semi-furnished") == "Semi-Furnished"
        assert schema.normalize_condition("Semi Furnished") == "Semi-Furnished"
        assert schema.normalize_condition("semi-furnished") == "Semi-Furnished"

    def test_fully_furnished_still_maps(self):
        for value in ("Fully Furnished", "plug and play", "Plug & Play", "turn-key"):
            assert schema.normalize_condition(value) == "Fully Furnished"

    def test_shell_types(self):
        assert schema.normalize_condition("Warm Shell") == "Warm Shell"
        assert schema.normalize_condition("Warmshell") == "Warm Shell"
        assert schema.normalize_condition("warm shell") == "Warm Shell"
        assert schema.normalize_condition("Core & Shell") == "Bare Shell"

    def test_fitted_out_is_recognised(self):
        assert schema.normalize_condition("Fitted out") == "Pre - Furnished"

    def test_as_is_where_is_is_case_folded(self):
        """Output held 'As is Where is' and 'As is where is' as separate values."""
        first = schema.normalize_condition("As is Where is")
        second = schema.normalize_condition("As is where is")
        assert first == second

    def test_unknown_text_passes_through(self):
        assert schema.normalize_condition("Something bespoke") == "Something bespoke"


# ---------------------------------------------------------------- timeline
class TestTimeline:
    def test_ready_by_a_date_is_not_immediate(self):
        """
        The `ready` alternative was evaluated before the date patterns, so a
        stated future handover was reported to the client as available now.
        """
        assert schema.normalize_timeline("Ready by Dec 26", "available") == "Dec 2026"
        assert schema.normalize_timeline("Ready by Q3 2027", "available") == "Q3 2027"
        assert schema.normalize_timeline("Ready to occupy Mar-27", "available") == "Mar 2027"

    def test_genuinely_immediate_still_maps(self):
        for value in ("Immediate", "Ready to occupy", "ready", "available now", "Vacant"):
            assert schema.normalize_timeline(value, "available") == "Immediate"

    def test_bare_available_folds_to_immediate(self):
        """7 rows carried a bare 'Available' that never folded into Immediate."""
        assert schema.normalize_timeline("Available", "available") == "Immediate"

    def test_quarter_with_comma(self):
        """'Q3, 2026' passed through raw because the separator class had no comma."""
        assert schema.normalize_timeline("Q3, 2026", "available") == "Q3 2026"
        assert schema.normalize_timeline("Q3 2026", "available") == "Q3 2026"
        assert schema.normalize_timeline("Q3-26", "available") == "Q3 2026"

    def test_half_year(self):
        assert schema.normalize_timeline("H2 2028", "available") == "H2 2028"

    def test_occupancy_wins_over_text(self):
        assert schema.normalize_timeline("Immediate", "occupied") == "Occupied"

    def test_leased_is_occupied(self):
        assert schema.normalize_timeline("Let out", "available") == "Occupied"


# --------------------------------------------------------------- to_number
class TestToNumber:
    def test_leading_number_is_not_the_area(self):
        """
        `re.search` took the first number, so 'Block 2, 45000 sqft' became 2.0
        and was written straight into spaces.area_sqft.
        """
        assert schema.to_number("Block 2, 45000 sqft") == 45000
        assert schema.to_number("2 Towers of 3,00,000 sft") == 300000
        assert schema.to_number("Tower 1 - 25,000 Sft") == 25000

    def test_k_suffix_without_a_space(self):
        r"""`\bk\b` cannot match '50K' - there is no word boundary after a digit."""
        assert schema.to_number("50K sft") == 50000
        assert schema.to_number("50 K sft") == 50000
        assert schema.to_number("1.5k seats") == 1500

    def test_kva_is_not_thousands(self):
        assert schema.to_number("1 KVA per 100 sft") == 1

    def test_ranges_take_the_upper_bound(self):
        assert schema.to_number("60,500-60,700 Sft") == 60700
        assert schema.to_number("7,020 sft to 4,67,470 sft") == 467470

    def test_indian_and_western_units(self):
        assert schema.to_number("1,26,408 Sqft") == 126408
        assert schema.to_number("1.1 Mn Sq ft") == 1100000
        assert schema.to_number("4.5 lakh sft") == 450000

    def test_blank_and_junk(self):
        assert schema.to_number(None) is None
        assert schema.to_number("N/A") is None
        assert schema.to_number("") is None


# ----------------------------------------------------------- micro-markets
class TestMicroMarket:
    @pytest.mark.parametrize("text,expected", [
        ("Kanakpura Road", "South-BLR"),          # misspelling of Kanakapura
        ("Bannerghata Road", "Bannerghatta Road"),
        ("Bannergatta Road", "Bannerghatta Road"),
        ("Indranagar", "Indiranagar"),
        ("Sarjapura Road", "Sarjapur Road"),
        ("Nagawara", "North-BLR"),
        ("JC Road", "CBD"),
    ])
    def test_real_spellings_from_the_documents(self, text, expected):
        """Each of these landed in 'Others' and was verified in the output."""
        assert schema.normalize_micromarket(text) == expected

    def test_orr_wins_over_whitefield(self):
        """
        Whitefield was tested before ORR, so any ORR address mentioning
        Whitefield was confidently misfiled.
        """
        assert schema.normalize_micromarket("Bellandur Whitefield Road") == "ORR"

    def test_hosur_road_does_not_capture_koramangala(self):
        """Hosur Road runs from Koramangala, so the E-City rule over-reached."""
        assert schema.normalize_micromarket("Hosur Road Koramangala") == "Koramangala"

    def test_plain_markets_still_resolve(self):
        assert schema.normalize_micromarket("Outer Ring Road, Bellandur") == "ORR"
        assert schema.normalize_micromarket("Whitefield EPIP") == "Whitefield"
        assert schema.normalize_micromarket("Vittal Mallya Road") == "CBD"
        assert schema.normalize_micromarket("Electronic City Phase 1") == "E-City"

    def test_non_bangalore(self):
        assert schema.normalize_micromarket("Hinjewadi, Pune") == "Outside BLR"


# ------------------------------------------------------------------ floors
class TestFloorLabel:
    @pytest.mark.parametrize("text,expected", [
        ("5th", "5F"),
        ("5th Floor", "5F"),
        ("Fifth Floor", "5F"),
        ("Fifth", "5F"),
        ("FIRST", "1F"),
        ("First floor", "1F"),
        ("Second floor", "2F"),
        ("Level 12", "12F"),
        ("Ground Floor", "GF"),
        ("Basement 2", "B2"),
        ("B2", "B2"),
        ("LG", "LGF"),
        ("Mezzanine", "Mezzanine"),
    ])
    def test_one_floor_has_one_label(self, text, expected):
        """
        The output held 5F, 5th, Fifth and 'Fifth Floor' as four separate
        values for the same floor, which breaks every per-floor rollup.
        """
        assert schema.normalize_floor(text) == expected

    def test_compound_labels_pass_through(self):
        assert schema.normalize_floor("Full Building (3B+G+10)") == "Full Building (3B+G+10)"
