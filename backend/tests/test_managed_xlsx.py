"""
Regression tests for the managed-office workbook importer.

The workbook writes seats and areas into one row labelled
"Offered Seats / Area Offered [In Sq. Ft.]", so the unit has to be inferred.
Getting it wrong does not just mis-file a quantity: it flips a per-seat price
into rent per square foot, which is what puts an absurd number in front of a
client.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.managed_xlsx import (  # noqa: E402
    classify_offering,
    classify_rate,
    offering_mismatch,
    resolve_operator,
)


class TestClassifyOffering:
    """
    Quantity and rate are classified independently. Inferring one from the
    other looked attractive but produced new errors in both directions on the
    real workbook - a 30,000 sq ft suite with a per-seat rate became
    "30,000 seats", and a 63-seat Regus centre became "63 sq ft".
    """

    def test_quantity_by_magnitude(self):
        assert classify_offering(516) == "seats"
        assert classify_offering(1183) == "seats"
        assert classify_offering(60500) == "area"
        assert classify_offering(0) is None
        assert classify_offering(None) is None

    def test_rate_by_magnitude(self):
        assert classify_rate(9500) == "seat"
        assert classify_rate(38000) == "seat"
        assert classify_rate(85) == "sqft"
        assert classify_rate(120) == "sqft"
        assert classify_rate(None) is None

    def test_ambiguous_rate_is_not_guessed(self):
        assert classify_rate(750) is None

    def test_a_seat_rate_is_a_seat_rate_without_a_seat_count(self):
        """
        The defect that put a median of Rs 9,500 per sq ft into the database:
        rate classification used to require a seat count to be present.
        """
        assert classify_rate(9500) == "seat"

    def test_disagreement_is_recorded_not_resolved(self):
        assert offering_mismatch("area", "seat")
        assert offering_mismatch("seats", "sqft")
        assert offering_mismatch("seats", "seat") is None
        assert offering_mismatch("area", "sqft") is None
        assert offering_mismatch(None, "seat") is None


class TestOperatorResolution:
    """The canonicaliser that collapsed 56 raw labels to 31 real operators."""

    CANON = ["WeWork India", "Table Space", "IndiQube", "Urban Vault",
             "BHIVE Workspace", "315Work Avenue", "Clayworks", "CorporateEdge"]

    @pytest.mark.parametrize("raw,expected", [
        ("Wework", "WeWork India"),
        ("UV", "Urban Vault"),
        ("TS", "Table Space"),
        ("Indiqube", "IndiQube"),
        ("BHIVE Platinum", "BHIVE Workspace"),
        ("Clayworks Opus", "Clayworks"),
        ("315Work Avenue DLR1", "315Work Avenue"),
        ("CorporatEdge", "CorporateEdge"),
    ])
    def test_variants_resolve_to_one_operator(self, raw, expected):
        assert resolve_operator(raw, self.CANON) == expected

    def test_unknown_operator_is_left_alone(self):
        assert resolve_operator("Some New Operator", self.CANON) == "Some New Operator"


@pytest.mark.integration
class TestWorkbookImport:
    """
    Guards against silent inventory loss. A normalisation change that drops
    options would otherwise be invisible - the import still reports success.
    """

    WORKBOOK = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))),
        "BLR - Managed Office Space Supply 2026.xlsx")

    def test_dry_run_reads_every_option(self):
        if not os.path.isfile(self.WORKBOOK):
            pytest.skip("source workbook not present")
        from services import managed_xlsx
        stats = managed_xlsx.import_workbook(
            self.WORKBOOK, None, upload_images=False,
            supply_type="managed", dry_run=True)
        assert stats["sheets"] == 13
        assert stats["spaces"] == 440, "an option column was dropped"
        assert stats["buildings"] == 425
        assert stats["errors"] == []
