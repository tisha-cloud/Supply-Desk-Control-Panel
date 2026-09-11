"""
Choosing a location from where the workforce lives.

The recommendation decides where a client puts an office, so the things that
matter are: nothing is silently dropped, a market with no stock is never
recommended, and the mapping behind the answer can be checked.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import demography as dg  # noqa: E402


@pytest.fixture
def stock(monkeypatch):
    """Buildings per micro-market, standing in for the database."""
    monkeypatch.setattr(dg, "available_markets", lambda: {
        "HSR Layout": 60, "KRM": 54, "ORR": 66, "WF": 52, "CBD": 79,
        "Indiranagar": 35, "BG Road": 11, "BTM": 1,
    })


class TestReadingPincodes:
    def test_any_shape_of_input_reads_the_same(self):
        assert dg.extract_pincodes("560102\n560034") == ["560102", "560034"]
        assert dg.extract_pincodes("560102, 560034") == ["560102", "560034"]
        assert dg.extract_pincodes("Bangalore 560102 India") == ["560102"]

    def test_repeats_count_because_one_row_is_one_person(self):
        assert dg.extract_pincodes("560102 560102 560102") == ["560102"] * 3

    def test_numbers_of_the_wrong_length_are_ignored(self):
        assert dg.extract_pincodes("employee 12 of 4500") == []
        assert dg.extract_pincodes("560102456") == []

    def test_pincodes_outside_bengaluru_are_kept_for_reporting(self):
        """
        Matching only 5xxxxx made an employee in Mumbai vanish from the
        workforce rather than be counted as living outside the city, which
        moves the majority without anyone seeing it happen.
        """
        assert dg.extract_pincodes("560102 400001 110001") == [
            "560102", "400001", "110001"]

    def test_a_csv_is_read_column_by_column(self):
        data = b"name,pincode\nA,560102\nB,560034\nC,560102\n"
        assert dg.read_upload(data, "staff.csv") == ["560102", "560034", "560102"]

    def test_a_file_with_nothing_in_it_reads_as_nothing(self):
        assert dg.read_upload(b"name,city\nA,Bangalore\n", "staff.csv") == []


class TestTheMapping:
    def test_every_code_is_a_real_micro_market(self):
        """
        A recommendation naming a market the database does not have is a
        recommendation pointing nowhere.
        """
        known = {"CBD", "KRM", "WF", "ORR", "HSR Layout", "Indiranagar", "E-City",
                 "North-BLR", "BG Road", "JP-Nagar", "Jayanagar", "BTM",
                 "Kanakapura Rd"}
        assert {code for _, code in dg.PINCODE_AREAS.values()} <= known

    def test_the_well_known_ones_land_where_they_should(self):
        for pincode, code in [("560034", "KRM"), ("560102", "HSR Layout"),
                              ("560066", "WF"), ("560103", "ORR"),
                              ("560038", "Indiranagar"), ("560100", "E-City"),
                              ("560001", "CBD"), ("560068", "BTM"),
                              ("560078", "JP-Nagar")]:
            assert dg.PINCODE_AREAS[pincode][1] == code, pincode

    def test_each_entry_carries_a_locality_name(self):
        """The name is what makes a wrong classification visible."""
        for pincode, (locality, _) in dg.PINCODE_AREAS.items():
            assert locality.strip(), pincode


class TestTheRanking:
    def test_the_majority_decides(self, stock):
        result = dg.profile(["560102"] * 10 + ["560034"] * 4)
        assert result["recommended"] == "HSR Layout"
        assert result["markets"][0]["employees"] == 10

    def test_shares_are_of_the_whole_workforce(self, stock):
        result = dg.profile(["560102"] * 3 + ["560034"])
        assert result["total_employees"] == 4
        assert result["markets"][0]["share"] == 75.0

    def test_pincodes_in_one_market_are_pooled(self, stock):
        """Koramangala is two pincodes; the people in them are one group."""
        result = dg.profile(["560034"] * 5 + ["560095"] * 3)
        assert len(result["markets"]) == 1
        assert result["markets"][0]["employees"] == 8
        assert len(result["markets"][0]["areas"]) == 2

    def test_a_market_with_no_stock_is_listed_but_never_recommended(self, monkeypatch):
        """
        Where they live matters only if they can be housed there. A market the
        desk holds nothing in is still shown - it is a real fact about the
        workforce - but it cannot be the answer.
        """
        monkeypatch.setattr(dg, "available_markets", lambda: {"KRM": 54})
        result = dg.profile(["560102"] * 20 + ["560034"] * 3)
        assert result["markets"][0]["micro_market"] == "HSR Layout"
        assert result["markets"][0]["buildings"] == 0
        assert result["recommended"] == "KRM"

    def test_a_tie_goes_to_the_market_with_more_stock(self, stock):
        result = dg.profile(["560102"] * 5 + ["560068"] * 5)
        assert result["recommended"] == "HSR Layout"     # 60 buildings vs 1


class TestNothingIsDroppedQuietly:
    def test_employees_living_elsewhere_are_reported_not_dropped(self, stock):
        result = dg.profile(["560102"] * 5 + ["400001", "110001"])
        assert result["total_employees"] == 7
        assert result["matched_employees"] == 5
        assert result["unrecognised_employees"] == 2
        assert {u["pincode"] for u in result["unrecognised"]} == {"400001", "110001"}

    def test_unrecognised_pincodes_are_reported(self, stock):
        result = dg.profile(["560102"] * 5 + ["999999"] * 2)
        assert result["total_employees"] == 7
        assert result["matched_employees"] == 5
        assert result["unrecognised_employees"] == 2
        assert result["unrecognised"][0]["pincode"] == "999999"

    def test_an_entirely_unrecognised_list_recommends_nothing(self, stock):
        result = dg.profile(["999999", "888888"])
        assert result["recommended"] is None
        assert result["markets"] == []

    def test_the_counts_always_add_up(self, stock):
        result = dg.profile(["560102"] * 4 + ["560034"] * 2 + ["999999"])
        assert (result["matched_employees"] + result["unrecognised_employees"]
                == result["total_employees"])
