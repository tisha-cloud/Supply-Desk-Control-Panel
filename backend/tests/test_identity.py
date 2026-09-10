"""
Regression tests for building identity.

A false merge is far more damaging than a false split: the survivor's fields
are overwritten and the other block's availability is attached to the wrong
building, silently. A false split shows up as a duplicate a human can merge.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import like_escape, same_building_name  # noqa: E402


class TestLikeEscape:
    def test_wildcards_are_neutralised(self):
        """`%` and `_` are LIKE wildcards; a name containing them matched far
        more than itself when interpolated straight into an ilike pattern."""
        assert like_escape("50% Block") == r"50\% Block"
        assert like_escape("Tower_A") == r"Tower\_A"

    def test_ordinary_names_are_untouched(self):
        assert like_escape("Prestige Tech Park") == "Prestige Tech Park"


class TestSameBuildingName:
    @pytest.mark.parametrize("left,right", [
        ("Sattva Hallmark", "sattva  hallmark"),
        ("Prestige Tech Park - Venus", "Prestige Tech Park  Venus"),
        ("SLK Green Group Tower B", "SLK Green Group Tower B"),
    ])
    def test_spelling_noise_still_matches(self, left, right):
        assert same_building_name(left, right)

    @pytest.mark.parametrize("left,right", [
        # The old rule compared a 24-character substring, so every block of
        # Bagmane World Technology Centre collapsed into whichever was first.
        ("Bagmane World Technology Centre - Opal",
         "Bagmane World Technology Centre - Aquamarine"),
        ("Bagmane World Technology Centre - Citrine",
         "Bagmane World Technology Centre - Peridot"),
        ("WTC Block 5", "WTC Block 6"),
        ("Helios Business Park - Wing D", "Helios Business Park - Wing E"),
        ("Prestige Tech Park - Venus", "Prestige Tech Park - Jupiter"),
    ])
    def test_sibling_blocks_stay_separate(self, left, right):
        assert not same_building_name(left, right)

    def test_blank_never_matches(self):
        assert not same_building_name("", "Anything")
        assert not same_building_name(None, "Anything")
