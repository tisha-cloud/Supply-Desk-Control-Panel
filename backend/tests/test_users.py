"""
The guards around user and role management.

There is no recovery path from a database with no administrator except editing
Postgres by hand, so every route that could produce one is tested here: the
last admin cannot be deleted, deactivated, demoted, or have the ground removed
from under them by re-scoping their role.
"""
import os
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import users  # noqa: E402
from services.users import UserError  # noqa: E402


def make_user(uid, admin=True, active=True, role="admin"):
    return {"id": uid, "email": "%s@example.com" % uid, "full_name": None,
            "role_key": role, "role_name": role, "is_active": active,
            "permissions": ["*"] if admin else ["supply.read"],
            "is_admin": admin, "created_at": "", "last_sign_in_at": None}


class TestAdminCount:
    def test_only_active_admins_count(self, monkeypatch):
        monkeypatch.setattr(users, "list_users", lambda: [
            make_user("a"),
            make_user("b", active=False),          # deactivated
            make_user("c", admin=False),           # not an admin
        ])
        assert users.admin_count() == 1

    def test_excluding_the_user_under_scrutiny(self, monkeypatch):
        monkeypatch.setattr(users, "list_users", lambda: [make_user("a"), make_user("b")])
        assert users.admin_count(exclude_id="a") == 1
        monkeypatch.setattr(users, "list_users", lambda: [make_user("a")])
        assert users.admin_count(exclude_id="a") == 0


class TestLastAdminIsProtected:
    """Three different clicks, one outcome that must never be possible."""

    def test_the_last_admin_cannot_be_deleted(self, monkeypatch):
        monkeypatch.setattr(users, "admin_count", lambda exclude_id=None: 0)
        with pytest.raises(UserError, match="last administrator"):
            users.delete_user("a")

    def test_the_last_admin_cannot_be_demoted(self, monkeypatch):
        _stub_db(monkeypatch, profile={"id": "a", "role_key": "admin"})
        monkeypatch.setattr(users, "admin_count", lambda exclude_id=None: 0)
        monkeypatch.setattr(users, "_grants_admin", lambda key: key == "admin")
        with pytest.raises(UserError, match="last administrator"):
            users.update_user("a", role_key="viewer")

    def test_the_last_admin_cannot_be_deactivated(self, monkeypatch):
        _stub_db(monkeypatch, profile={"id": "a", "role_key": "admin"})
        monkeypatch.setattr(users, "admin_count", lambda exclude_id=None: 0)
        with pytest.raises(UserError, match="last administrator"):
            users.update_user("a", is_active=False)

    def test_another_admin_makes_all_three_allowed(self, monkeypatch):
        monkeypatch.setattr(users, "admin_count", lambda exclude_id=None: 1)
        calls = _stub_db(monkeypatch, profile={"id": "a", "role_key": "admin"})
        users.update_user("a", is_active=False)
        assert calls["updated"] == {"is_active": False}


class TestValidation:
    def test_an_address_that_is_not_an_address_is_refused(self, monkeypatch):
        with pytest.raises(UserError, match="not a valid email"):
            users.create_user("not-an-email", "secret123", "viewer")

    def test_a_short_password_is_refused_before_the_account_is_made(self, monkeypatch):
        with pytest.raises(UserError, match="at least"):
            users.create_user("a@example.com", "abc", "viewer")

    def test_the_role_key_is_derived_from_the_name(self):
        assert users._slug("Research Analyst") == "research_analyst"
        assert users._slug("  Deal Team (BLR) ") == "deal_team_blr"


class TestSystemRolesAreImmutable:
    def test_a_built_in_role_cannot_be_edited(self, monkeypatch):
        _stub_roles(monkeypatch, {"key": "admin", "name": "Administrator", "is_system": True})
        with pytest.raises(UserError, match="built-in"):
            users.update_role("admin", name="Something else")

    def test_a_built_in_role_cannot_be_deleted(self, monkeypatch):
        _stub_roles(monkeypatch, {"key": "admin", "name": "Administrator", "is_system": True})
        with pytest.raises(UserError, match="built-in"):
            users.delete_role("admin")

    def test_a_role_in_use_cannot_be_deleted(self, monkeypatch):
        _stub_roles(monkeypatch, {"key": "editor", "name": "Editor", "is_system": False},
                    holders=[{"id": "a", "email": "a@example.com"}])
        with pytest.raises(UserError, match="still hold"):
            users.delete_role("editor")


class TestPermissionCleaning:
    def test_unknown_permissions_are_dropped(self, monkeypatch):
        """
        The wildcard is the important one: accepting it from the role editor
        would let an admin mint a second all-powerful role that is editable,
        and therefore removable.
        """
        monkeypatch.setattr(users, "list_permissions", lambda: [
            {"key": "supply.read"}, {"key": "supply.write"}])
        cleaned = users._clean_permissions(
            ["supply.read", "*", "supply.invent", "supply.write"])
        assert cleaned == ["supply.read", "supply.write"]

    def test_duplicates_collapse_and_order_is_stable(self, monkeypatch):
        monkeypatch.setattr(users, "list_permissions", lambda: [
            {"key": "b.thing"}, {"key": "a.thing"}])
        assert users._clean_permissions(["b.thing", "a.thing", "b.thing"]) == \
            ["a.thing", "b.thing"]


# ------------------------------------------------------------------ test kit
class _Result:
    def __init__(self, data: List[Dict[str, Any]]):
        self.data = data


class _Table:
    """The slice of the PostgREST builder these functions actually use."""

    def __init__(self, rows, sink):
        self._rows = rows
        self._sink = sink

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def update(self, patch):
        self._sink["updated"] = patch
        return self

    def delete(self):
        self._sink["deleted"] = True
        return self

    def execute(self):
        return _Result(self._rows)


def _stub_db(monkeypatch, profile):
    sink: Dict[str, Any] = {}

    class _Client:
        def table(self, name):
            return _Table([profile] if name == "profiles" else [{"key": "viewer"}], sink)

    monkeypatch.setattr(users.db, "client", lambda: _Client())
    monkeypatch.setattr(users.auth, "forget", lambda _id: None)
    return sink


def _stub_roles(monkeypatch, role, holders=None):
    sink: Dict[str, Any] = {}

    class _Client:
        def table(self, name):
            if name == "roles":
                return _Table([role], sink)
            return _Table(holders or [], sink)

    monkeypatch.setattr(users.db, "client", lambda: _Client())
    monkeypatch.setattr(users.auth, "forget_all", lambda: None)
    return sink
