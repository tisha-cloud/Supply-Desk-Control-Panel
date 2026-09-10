"""
Matching a requirement to options.

Each case here is a defect found on a real search: "150 managed seats in
Koramangala" returned 6 of the 25 available centres, ranked a 70-seat centre
above a 167-seat one, and named the tower's owner instead of the operator the
client would actually be dealing with.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import deck_service as ds  # noqa: E402


class TestRequirementSize:
    """
    The parser fills whichever key suits how the brief was phrased. Reading
    only one of them left a 150-seat requirement carrying no size at all, so
    nothing was ranked by fit.
    """

    def test_a_seat_count_is_found_under_either_key(self):
        assert ds.requirement_size({"seats": 150}) == (150.0, "seats")
        assert ds.requirement_size({"min_seats": 120}) == (120.0, "seats")

    def test_the_stated_count_wins_over_a_widened_band(self):
        assert ds.requirement_size({"seats": 150, "min_seats": 120}) == (150.0, "seats")

    def test_area_when_there_is_no_headcount(self):
        assert ds.requirement_size({"area_sqft": 30000}) == (30000.0, "area")

    def test_the_asked_area_wins_over_the_widened_band(self):
        """
        The fallback parser stores 0.8x the asked area in min_area_sqft.
        Reading that first would quietly move the fit line below the brief.
        """
        assert ds.requirement_size(
            {"area_sqft": 30000, "min_area_sqft": 24000}) == (30000.0, "area")

    def test_no_size_at_all(self):
        assert ds.requirement_size({}) == (None, None)
        assert ds.requirement_size({"seats": 0}) == (None, None)


def building(name, seats, operator=None, developer=None,
             supply="managed", market="KRM", photo=True):
    return {
        "id": name, "name": name, "supply_type": supply,
        "micro_markets": {"code": market},
        "developer": {"name": developer} if developer else None,
        "operator": {"name": operator} if operator else None,
        "operator_brand": None,
        "spaces": [{"seats": seats, "area_sqft": 0, "occupancy": "available",
                    "condition": "Pre - Furnished", "timeline": "Immediate",
                    "rent_psf": None, "price_per_seat": 9000}],
        "building_images": [{"storage_path": "x"}] if photo else [],
        "contacts": [],
    }


# The Koramangala stock this was first run against.
KRM = [
    building("Workshaala Avenor", 700, operator="Workshaala"),
    building("Incubex KRM7", 430, operator="Incubex"),
    building("Prestige Bluechip", 275, operator="Awfis", developer="Prestige Group"),
    building("KRM 1 - Kothari Tower II", 220, operator="315Work Avenue",
             developer="Sattva Group"),
    building("Urban Vault 57", 175, operator="Urban Vault"),
    building("Padmavathi Complex", 171, operator="91SpringBoard"),
    building("Prestige Cube", 167, operator="WeWork India", developer="Prestige Group"),
    building("Prestige Atlanta", 143, operator="WeWork India", developer="Prestige Group"),
    building("Clayworks 5B", 134, operator="Clayworks"),
    building("Chanakya", 70, operator="Attic Space"),
    building("Obeya Elan", 12, operator="Obeya Workspace"),
]


@pytest.fixture
def krm(monkeypatch):
    """Point shortlist() at the fixture above instead of Supabase."""
    class _Query:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            import copy
            return type("R", (), {"data": copy.deepcopy(KRM)})()

    class _Client:
        def table(self, name): return _Query()

    monkeypatch.setattr(ds.db, "client", lambda: _Client())
    monkeypatch.setattr(ds.config, "BUCKET_IMAGES", "building-images", raising=False)


CRITERIA = {"micro_markets": ["KRM"], "supply_type": "managed", "seats": 150,
            "limit": None}


class TestEveryMatchIsReturned:
    def test_the_list_is_not_truncated(self, krm):
        """
        The default used to be six, which hid two thirds of the market and
        dropped the best fits. The operator trims the list, not the filter.
        """
        names = [r["name"] for r in ds.shortlist(dict(CRITERIA))]
        assert len(names) == 9
        for expected in ("Prestige Cube", "Urban Vault 57", "Padmavathi Complex",
                         "Incubex KRM7", "Workshaala Avenor"):
            assert expected in names

    def test_an_explicit_count_is_still_honoured(self, krm):
        assert len(ds.shortlist({**CRITERIA, "limit": 3})) == 3

    def test_options_far_below_the_brief_are_dropped(self, krm):
        """A 12-seat centre is not a near miss for 150 seats, it is noise."""
        names = [r["name"] for r in ds.shortlist(dict(CRITERIA))]
        assert "Obeya Elan" not in names
        assert "Chanakya" not in names


class TestFit:
    def test_meeting_and_falling_short_are_distinguished(self, krm):
        by_name = {r["name"]: r for r in ds.shortlist(dict(CRITERIA))}
        assert by_name["Prestige Cube"]["_fit"] == "meets"
        assert by_name["Prestige Atlanta"]["_fit"] == "short"
        assert by_name["Prestige Atlanta"]["_shortfall"] == 7
        assert by_name["Clayworks 5B"]["_shortfall"] == 16

    def test_everything_that_fits_leads_everything_that_does_not(self, krm):
        rows = ds.shortlist(dict(CRITERIA))
        fits = [r["_fit"] for r in rows]
        assert fits == sorted(fits, key=lambda f: {"meets": 0, "short": 1}[f])

    def test_the_tightest_fit_comes_first(self, krm):
        """
        An exact match must not be buried under a centre five times the size,
        and a 70-seat centre must never outrank a 167-seat one.
        """
        rows = ds.shortlist(dict(CRITERIA))
        assert rows[0]["name"] == "Prestige Cube"          # 167, the tightest
        assert rows[0]["_available_seats"] == 167
        meets = [r["_available_seats"] for r in rows if r["_fit"] == "meets"]
        assert meets == sorted(meets)

    def test_near_misses_are_ordered_by_how_close_they_are(self, krm):
        short = [r["_shortfall"] for r in ds.shortlist(dict(CRITERIA))
                 if r["_fit"] == "short"]
        assert short == sorted(short)


class TestWhoTheClientDealsWith:
    def test_managed_space_names_the_operator_not_the_tower_owner(self, krm):
        """
        315Work Avenue runs KRM 1; Sattva Group owns the building and is not a
        party to the deal. Naming the developer billed the wrong company.
        """
        by_name = {r["name"]: r for r in ds.shortlist(dict(CRITERIA))}
        assert by_name["KRM 1 - Kothari Tower II"]["_landlord"] == "315Work Avenue"
        assert by_name["Prestige Cube"]["_landlord"] == "WeWork India"

    def test_conventional_space_names_the_developer(self, krm, monkeypatch):
        rows = [building("Tower A", 0, operator="Someone", developer="Embassy",
                         supply="conventional")]
        rows[0]["spaces"][0]["area_sqft"] = 40000
        rows[0]["spaces"][0]["seats"] = 0

        class _Q:
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def in_(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self): return type("R", (), {"data": rows})()
        monkeypatch.setattr(ds.db, "client", lambda: type(
            "C", (), {"table": lambda self, n: _Q()})())

        out = ds.shortlist({"micro_markets": ["KRM"], "supply_type": "conventional",
                            "area_sqft": 30000, "limit": None})
        assert out[0]["_landlord"] == "Embassy"
