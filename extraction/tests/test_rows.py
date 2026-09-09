"""
Regression tests for row building and the derived "Balance Floors" rows.

The balance row is the highest-risk thing this pipeline produces: it asserts to
a client that a specific amount of a building is already let, from arithmetic
rather than from any document. Every case here is drawn from real output.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extractor import rows as rowbuilder  # noqa: E402


SOURCE = {"rel_path": "x.pdf", "kind": "PDF", "period": "July 2026", "folder": "Some Landlord"}


def building(**overrides):
    base = {
        "building_name": "Test Tower",
        "address_locality": "ORR / Mahadevapura",
        "city": "Bengaluru",
        "asset_type": "office",
        "transaction_type": "lease",
        "building_structure": "3B + G + 10",
        "total_building_size_sqft": 600000,
        "disclosure_mode": "available_only",
        "spaces": [],
    }
    base.update(overrides)
    return base


# ----------------------------------------------------- structure parsing
class TestFloorsFromStructure:
    @pytest.mark.parametrize("structure,expected", [
        ("2B + G + 9", 10),
        ("3B+G+14", 15),
        ("G + 4", 5),
        ("B+G+5", 6),
    ])
    def test_plain_forms(self, structure, expected):
        assert rowbuilder.floors_from_structure(structure) == expected

    def test_parenthetical_annotations_are_stripped(self):
        """
        The basement branch only matched a bare token, so an annotated
        basement fell through to the generic digit grab and was counted as a
        leasable floor. That inflated the level count and de-calibrated the
        plausibility guard.
        """
        assert rowbuilder.floors_from_structure("3B(Parking) + G(Parking) + 13 Floors") == 14
        assert rowbuilder.floors_from_structure("3 Basements + Ground (Lobby) + 14 Office Floors") == 15

    def test_multiple_towers_multiply(self):
        """'2B + G + 9 Floors (2 Towers)' is 20 levels of stock, not 10."""
        assert rowbuilder.floors_from_structure("2B + G + 9 Floors (2 Towers)") == 20
        assert rowbuilder.floors_from_structure("Tower A & B - 2B + G + 7") == 16

    def test_unparseable_returns_none(self):
        assert rowbuilder.floors_from_structure("") is None
        assert rowbuilder.floors_from_structure(None) is None
        assert rowbuilder.floors_from_structure("Grade A Building") is None


# ------------------------------------------------------ plausibility guard
class TestImplausibleTotal:
    def test_absurd_plate_is_rejected(self):
        reason = rowbuilder.implausible_total(1218000, "2B+G+9")
        assert reason and "floor plate" in reason

    def test_believable_plate_passes(self):
        assert rowbuilder.implausible_total(1210000, "3B+G+14") == ""
        assert rowbuilder.implausible_total(199916, "2B + G + 19") == ""

    def test_unparseable_structure_is_not_a_free_pass(self):
        """
        The guard returned "" when the structure could not be parsed, so no
        check ran at all. That is how RMZ Ecoworld Campus 20 acquired a
        derived Occupied row covering 98.5% of the building.
        """
        reason = rowbuilder.implausible_total(1950000, "Campus")
        assert reason, "an unparseable structure must not skip the guard"


# ----------------------------------------------------------- balance rows
class TestBalanceRow:
    def _balance(self, built):
        return [r for r in built if r.get("_derived")]

    def test_normal_balance_is_emitted(self):
        built, diag = rowbuilder.build_building_rows(
            building(spaces=[{"floor_label": "5F", "area_sqft": 53600,
                              "occupancy": "available", "condition": "Warm Shell"}]),
            "Bagmane", SOURCE)
        balance = self._balance(built)
        assert len(balance) == 1
        assert balance[0]["_area_sqft"] == pytest.approx(546400)
        assert balance[0]["Timeline"] == "Occupied"
        assert diag["balance_emitted"] is True

    def test_near_total_balance_is_suppressed(self):
        """
        RMZ Ecoworld Campus 20: a campus-level total minus one 29k floor
        produced a 19,20,988 sft 'Occupied' row - 98.5% of the building -
        presented with a derivation note that reads like evidence.
        """
        built, diag = rowbuilder.build_building_rows(
            building(building_structure="Campus", total_building_size_sqft=1950000,
                     spaces=[{"floor_label": "7F", "area_sqft": 29012,
                              "occupancy": "available"}]),
            "RMZ Corp", SOURCE)
        assert self._balance(built) == []
        assert diag["balance_emitted"] is False
        assert diag["issue"]

    def test_no_measured_area_means_no_derivation(self):
        built, diag = rowbuilder.build_building_rows(
            building(spaces=[{"floor_label": "5F", "area_sqft": None,
                              "occupancy": "available"}]),
            "Bagmane", SOURCE)
        assert self._balance(built) == []

    def test_listed_area_over_total_is_refused(self):
        built, diag = rowbuilder.build_building_rows(
            building(total_building_size_sqft=37355,
                     spaces=[{"floor_label": "1F", "area_sqft": 42160,
                              "occupancy": "available"}]),
            "Prestige Group", SOURCE)
        assert self._balance(built) == []
        assert "exceeds" in diag["issue"]


# ------------------------------------------------------ folder contamination
class TestMicroMarketSource:
    def test_folder_does_not_override_a_real_address(self):
        """
        source_meta["folder"] was blended into the same text as the address, so
        every building in the `Park Square whitefield/` folder was forced to
        Whitefield regardless of where it actually is.
        """
        built, _ = rowbuilder.build_building_rows(
            building(building_name="Park Square", address_locality="Koramangala 3rd Block",
                     total_building_size_sqft=None, spaces=[]),
            "Park Square",
            {**SOURCE, "folder": "Park Square whitefield"})
        assert built[0]["BLR - Categorization"] == "Koramangala"

    def test_folder_is_used_when_the_address_says_nothing(self):
        built, _ = rowbuilder.build_building_rows(
            building(building_name="Some Asset", address_locality=None,
                     total_building_size_sqft=None, spaces=[]),
            "Park Square",
            {**SOURCE, "folder": "Park Square whitefield"})
        assert built[0]["BLR - Categorization"] == "Whitefield"
