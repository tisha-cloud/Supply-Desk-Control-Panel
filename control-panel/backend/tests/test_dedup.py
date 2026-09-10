"""
Regression tests for organisation de-duplication.

The live database held 163 organisations with 21 near-duplicate pairs. The
danger in fixing that is over-merging: "Mantri Developers" and "Maithri
Developers" are 0.90 similar and are different companies.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.dedup import find_duplicates, merge_risk, org_key  # noqa: E402


class TestOrgKey:
    @pytest.mark.parametrize("left,right", [
        ("Prestige Group", "Prestige Groups"),
        ("Sattva Group", "Sattva Groups"),
        ("Godrej Properties Ltd", "Godrej Properties"),
        ("Prestige Estates Projects Ltd", "Prestige Estates Projects Limited"),
        ("Kalyani Developers Pvt. Ltd.", "Kalyani Developers"),
        ("GoodWorks", "GoodWorks"),
        ("Embassy Property Developments", "Embassy Property Developments Pvt."),
    ])
    def test_meaningless_differences_collapse(self, left, right):
        """Casing, punctuation and legal suffixes cannot change who a company is."""
        assert org_key(left) == org_key(right)

    @pytest.mark.parametrize("left,right", [
        ("Mantri Developers", "Maithri Developers"),
        ("Prestige Groups", "Perstige Groups"),
        ("RMZ Corp", "RMZ Corp Holdings"),
    ])
    def test_judgement_calls_keep_their_own_key(self, left, right):
        """
        A transposed letter or a missing word needs a human. Auto-merging
        Mantri into Maithri would silently destroy a landlord's portfolio.
        """
        assert org_key(left) != org_key(right)


class TestFindDuplicates:
    def _orgs(self, *names):
        return [{"id": str(i), "name": n, "role": "developer"} for i, n in enumerate(names)]

    def test_groups_are_proposed_with_the_most_used_name_kept(self):
        orgs = self._orgs("Prestige Group", "Prestige Groups", "Prestige / UB Group")
        usage = {"0": 26, "1": 2, "2": 1}
        groups = find_duplicates(orgs, usage)
        assert len(groups) == 1
        assert groups[0]["keep"]["name"] == "Prestige Group"
        assert groups[0]["moves"] == 3

    def test_different_companies_are_shown_but_never_as_routine(self):
        """
        Mantri and Maithri are 0.94 similar. They are still surfaced - the same
        shape catches the "Perstige Groups" typo - but the reviewer is told the
        company word itself differs, and the pair is never marked confident.
        """
        groups = find_duplicates(self._orgs("Mantri Developers", "Maithri Developers"), {})
        assert len(groups) == 1
        assert groups[0]["confident"] is False
        assert "different firms" in groups[0]["merge"][0]["risk"]

    def test_unrelated_names_are_not_grouped(self):
        assert find_duplicates(self._orgs("Bagmane", "Embassy Group", "Sobha"), {}) == []

    def test_risk_is_absent_for_a_pure_spelling_difference(self):
        assert merge_risk("Sattva Group", "Sattva Groups") is None
        assert merge_risk("Mantri Developers", "Maithri Developers")

    def test_confident_flag_marks_the_safe_ones(self):
        confident = find_duplicates(self._orgs("Sattva Group", "Sattva Groups"), {})
        assert confident and confident[0]["confident"] is True

        unsure = find_duplicates(self._orgs("RMZ Corp", "RMZ Corp Holdings"), {})
        assert unsure and unsure[0]["confident"] is False

    def test_singletons_are_ignored(self):
        assert find_duplicates(self._orgs("Bagmane", "Embassy Group", "Sobha"), {}) == []
