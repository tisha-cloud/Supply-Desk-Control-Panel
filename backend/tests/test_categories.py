"""
The three listing categories and the seat rule that names the product.

Each case here is a decision the desk made, not an implementation detail:
managed and co-working are one listing, and the fifteen-seat line decides only
what a proposal calls the space.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.categories import (  # noqa: E402
    MANAGED_SEAT_THRESHOLD,
    canonical_supply_type,
    describe_product,
    product_for_seats,
    product_label,
    stored_supply_types,
)


class TestCanonicalSupplyType:
    """Co-working folds into managed; anything unknown fails rather than guesses."""

    @pytest.mark.parametrize("raw,expected", [
        ("conventional", "conventional"),
        ("managed", "managed"),
        ("sale", "sale"),
        ("coworking", "managed"),
        ("Co-Working", "managed"),
        ("  MANAGED  ", "managed"),
        ("flex", "managed"),
    ])
    def test_folds_to_a_listing_category(self, raw, expected):
        assert canonical_supply_type(raw) == expected

    def test_unknown_is_rejected_not_guessed(self):
        """
        An import parameter typo must fail loudly. Silently defaulting to
        managed would file conventional stock in the wrong category, where the
        deck builder would never find it again.
        """
        assert canonical_supply_type("managd") is None
        assert canonical_supply_type("") is None
        assert canonical_supply_type(None) is None

    def test_default_applies_only_when_asked(self):
        assert canonical_supply_type(None, default="managed") == "managed"

    def test_managed_query_still_finds_pre_merge_rows(self):
        """
        Rows written before the merge hold 'coworking'. A managed query has to
        cover both or a co-working centre disappears from every shortlist.
        """
        assert stored_supply_types("managed") == ["managed", "coworking"]
        assert stored_supply_types("conventional") == ["conventional"]
        assert stored_supply_types(None) == []


class TestSeatRule:
    """Under fifteen seats is co-working; fifteen or more is managed."""

    def test_the_boundary_has_no_gap(self):
        assert MANAGED_SEAT_THRESHOLD == 15
        assert product_for_seats(14) == "coworking"
        assert product_for_seats(15) == "managed"
        assert product_for_seats(16) == "managed"

    @pytest.mark.parametrize("seats", [1, 5, 14.9])
    def test_small_requirements_are_coworking(self, seats):
        assert product_for_seats(seats) == "coworking"

    @pytest.mark.parametrize("seats", [15, 150, 2000])
    def test_large_requirements_are_managed(self, seats):
        assert product_for_seats(seats) == "managed"

    def test_no_headcount_means_no_product(self):
        """
        An area brief is not a flex requirement at all. Labelling it would put
        "Co-working" on a 30,000 sq ft warm shell floor.
        """
        assert product_for_seats(None) is None
        assert product_for_seats(0) is None
        assert product_for_seats("") is None
        assert product_for_seats("not a number") is None

    def test_the_label_is_what_the_client_sees(self):
        assert product_label("coworking") == "Co-working"
        assert product_label("managed") == "Managed Office"
        assert product_label(None) == ""

    def test_the_reason_is_explained_in_full(self):
        assert "under 15" in describe_product("coworking", 8)
        assert "8 seats" in describe_product("coworking", 8)
        assert "managed office" in describe_product("managed", 150)
        assert describe_product(None, 8) == ""
