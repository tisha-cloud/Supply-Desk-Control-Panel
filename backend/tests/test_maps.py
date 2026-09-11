"""
Location slides: reading coordinates, measuring distance, and costing nothing
when nobody asked for a map.

Both Google services here are billed per call, so the tests that matter most
are the ones proving no call is made unless a map was actually requested and a
key is actually set.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from services import maps  # noqa: E402


class TestCoordinates:
    def test_a_pair_is_read_either_spaced_or_not(self):
        assert maps.coordinates("12.9366, 77.6110") == (12.9366, 77.611)
        assert maps.coordinates("12.9366,77.6110") == (12.9366, 77.611)
        assert maps.coordinates([12.9366, 77.611]) == (12.9366, 77.611)

    def test_nothing_usable_is_rejected_rather_than_guessed(self):
        for value in (None, "", "abc", "12.9366", "1,2,3", "999,999"):
            assert maps.coordinates(value) is None, value

    def test_null_island_is_not_a_location(self):
        """
        A record with zeroed coordinates is a record with none. Plotting it
        would put a Bengaluru option in the Gulf of Guinea.
        """
        assert maps.coordinates("0, 0") is None
        assert maps.coordinates("0,0") is None


class TestDistance:
    def test_a_known_separation(self):
        koramangala, indiranagar = (12.9366, 77.6110), (12.9784, 77.6408)
        assert 5000 < maps.distance_m(koramangala, indiranagar) < 6500

    def test_a_point_is_no_distance_from_itself(self):
        assert maps.distance_m((12.9, 77.6), (12.9, 77.6)) == 0


class TestMarkerLabels:
    """
    Static Maps allows one alphanumeric character per pin, so a shortlist
    longer than nine has to continue into letters - and the slide prints a key,
    because a pin reading "C" means nothing on its own.
    """

    def test_the_first_nine_are_their_own_number(self):
        assert [maps.marker_label(n) for n in range(1, 10)] == list("123456789")

    def test_ten_onwards_become_letters(self):
        assert maps.marker_label(10) == "A"
        assert maps.marker_label(11) == "B"
        assert maps.marker_label(35) == "Z"

    def test_beyond_the_alphabet_falls_back_rather_than_breaking(self):
        assert maps.marker_label(200) == "*"


class TestNothingIsBilledUnasked:
    @pytest.fixture
    def no_key(self, monkeypatch):
        monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "")
        monkeypatch.setattr(config, "maps_configured", lambda: False)

    def test_no_key_means_no_map_and_no_call(self, no_key, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("a billed request was made without a key")
        monkeypatch.setattr(maps, "_get", explode)
        assert maps.static_map([{"lat": 12.9, "lng": 77.6}]) is None
        assert maps.nearby(12.9, 77.6) == []

    def test_no_points_means_no_call(self, monkeypatch):
        monkeypatch.setattr(config, "maps_configured", lambda: True)
        def explode(*a, **k):
            raise AssertionError("a billed request was made with nothing to draw")
        monkeypatch.setattr(maps, "_get", explode)
        assert maps.static_map([]) is None


class TestPlottingAShortlist:
    def test_options_keep_the_number_the_deck_gives_them(self):
        records = [
            {"building_name": "A", "location_map": "12.93, 77.61"},
            {"building_name": "B", "location_map": ""},          # no coordinates
            {"building_name": "C", "location_map": "12.97, 77.64"},
        ]
        points = maps.option_points(records)
        assert [p["option"] for p in points] == [1, 3]
        assert [p["label"] for p in points] == ["1", "3"]

    def test_an_option_without_coordinates_is_skipped_not_invented(self):
        records = [{"building_name": "A", "location_map": None}]
        assert maps.option_points(records) == []


class TestDescribingWhatIsNearby:
    def test_metres_below_a_kilometre_and_kilometres_above(self):
        lines = maps.describe_nearby([
            {"kind": "Metro", "name": "Indiranagar", "metres": 850},
            {"kind": "Hospital", "name": "Manipal", "metres": 2400},
        ])
        assert "Indiranagar (850 m)" in lines[0]
        assert "Manipal (2.4 km)" in lines[1]

    def test_kinds_keep_the_order_they_are_asked_for(self):
        """Metro first: it is the one a tenant asks about before any other."""
        lines = maps.describe_nearby([
            {"kind": "Dining", "name": "Cafe", "metres": 100},
            {"kind": "Metro", "name": "Station", "metres": 900},
        ])
        assert lines[0].startswith("Metro")

    def test_nothing_nearby_is_no_lines_rather_than_an_empty_heading(self):
        assert maps.describe_nearby([]) == []
