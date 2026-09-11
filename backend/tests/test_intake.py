"""
Document intake: what gets created, what gets updated, and what it is filed as.

Re-reading a document the desk already holds has to enrich the record, never
hollow it out, and the category has to be the one the operator chose rather
than the one a model inferred from prose.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from services import extraction_service as es  # noqa: E402


class TestAReimportEnrichesRatherThanErases:
    """
    `_clean` decides what a second pass is allowed to write. The extractor
    fills every column it knows about, using an empty string for anything the
    document did not mention - so without this, re-reading a brochure that
    happened to omit the power rating wrote "" over a figure somebody had
    recorded by hand.
    """

    def test_absent_values_are_not_written(self):
        cleaned = db._clean({"name": "Tower", "structure": None})
        assert "structure" not in cleaned

    def test_empty_strings_are_not_written(self):
        cleaned = db._clean({"name": "Tower", "power_kva": "", "structure": "   "})
        assert "power_kva" not in cleaned
        assert "structure" not in cleaned

    def test_real_values_still_are(self):
        cleaned = db._clean({"name": "Tower", "power_kva": "1 KVA / 100 Sft",
                             "total_size_sqft": 25000, "oc_available": False})
        assert cleaned["power_kva"] == "1 KVA / 100 Sft"
        assert cleaned["total_size_sqft"] == 25000

    def test_false_and_zero_survive(self):
        """
        Both are facts, not absences: a building genuinely without an
        occupancy certificate must not read as one nobody has asked about.
        """
        cleaned = db._clean({"oc_available": False, "total_size_sqft": 0,
                             "is_verified": False})
        assert cleaned["oc_available"] is False
        assert cleaned["total_size_sqft"] == 0
        assert cleaned["is_verified"] is False


class TestTheDeclaredCategoryTravelsWithTheUpload:
    @pytest.fixture
    def supply_dir(self, monkeypatch):
        root = tempfile.mkdtemp()
        monkeypatch.setattr(es.config, "SUPPLY_DIR", root)
        return root

    def _file(self):
        path = os.path.join(tempfile.mkdtemp(), "brochure.pdf")
        with open(path, "wb") as fh:
            fh.write(b"%PDF-1.4 test")
        return path

    def test_the_choice_is_recorded_beside_the_files(self, supply_dir):
        folder = es.stage_uploads([self._file()], "Bagmane", "managed")
        assert os.path.isfile(os.path.join(folder, es.CATEGORY_MARKER))
        assert es.declared_category("Bagmane") == "managed"

    def test_co_working_is_filed_as_managed(self, supply_dir):
        """One listing category, so the marker holds the canonical value."""
        es.stage_uploads([self._file()], "Bagmane", "coworking")
        assert es.declared_category("Bagmane") == "managed"

    def test_no_choice_leaves_no_marker(self, supply_dir):
        """
        With nothing declared the pipeline falls back to what it can infer
        from the document, which is the behaviour intake had before.
        """
        folder = es.stage_uploads([self._file()], "Bagmane")
        assert not os.path.exists(os.path.join(folder, es.CATEGORY_MARKER))
        assert es.declared_category("Bagmane") is None

    def test_an_unknown_category_is_not_recorded(self, supply_dir):
        es.stage_uploads([self._file()], "Bagmane", "nonsense")
        assert es.declared_category("Bagmane") is None

    def test_an_unknown_folder_is_not_an_error(self, supply_dir):
        assert es.declared_category("never-uploaded") is None
        assert es.declared_category("") is None

    def test_the_marker_is_hidden_from_the_pipeline(self):
        """
        The pipeline picks documents up by extension. A dotfile with no
        document extension cannot be mistaken for one to read.
        """
        assert es.CATEGORY_MARKER.startswith(".")
        assert not es.CATEGORY_MARKER.lower().endswith(
            (".pdf", ".pptx", ".xlsx", ".xls", ".jpg", ".png"))
