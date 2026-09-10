"""
The permission check, and the guards that stop an admin locking everyone out.

These test decisions rather than plumbing: what the wildcard means, what a
missing permission does to a request, and the three ways someone could remove
the last administrator by accident.
"""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth  # noqa: E402
from auth import Caller  # noqa: E402


def caller(*permissions, active=True, role="editor"):
    return Caller(user_id="u1", email="u@example.com", role=role,
                  permissions=list(permissions), is_active=active)


class TestPermissions:
    def test_a_held_permission_is_allowed(self):
        assert caller("supply.read", "supply.write").can("supply.write")

    def test_an_unheld_permission_is_refused(self):
        assert not caller("supply.read").can("supply.delete")

    def test_the_wildcard_covers_everything_including_the_unknown(self):
        """
        Admin holds '*' rather than a list, so a permission added by a future
        feature is granted to admins without a migration to backfill it.
        """
        admin = caller("*", role="admin")
        assert admin.can("supply.delete")
        assert admin.can("a.permission.that.does.not.exist.yet")
        assert admin.is_admin

    def test_managing_users_is_what_makes_an_admin(self):
        assert caller("users.manage").is_admin
        assert not caller("supply.read", "supply.write", "supply.delete").is_admin

    def test_no_permissions_means_no_access(self):
        assert not caller().can("supply.read")


class TestRouteGuard:
    """`require(...)` is the backend half; row-level security is the other."""

    def test_a_missing_permission_is_a_403_naming_the_role(self):
        guard = auth.require("supply.delete")
        with pytest.raises(HTTPException) as raised:
            guard(caller("supply.read", role="viewer"))
        assert raised.value.status_code == 403
        assert "viewer" in raised.value.detail
        assert "supply.delete" in raised.value.detail

    def test_a_held_permission_passes_the_caller_through(self):
        guard = auth.require("supply.read")
        assert guard(caller("supply.read")).email == "u@example.com"

    def test_no_session_is_a_401_not_a_403(self):
        """
        The distinction matters to the UI: 401 means sign in, 403 means you are
        signed in and this is not yours to do.
        """
        with pytest.raises(HTTPException) as raised:
            auth.require_user(None)
        assert raised.value.status_code == 401

    def test_a_deactivated_account_is_refused_even_with_permissions(self):
        with pytest.raises(HTTPException) as raised:
            auth.require_user(caller("*", active=False))
        assert raised.value.status_code == 403
        assert "deactivated" in raised.value.detail.lower()


class TestSetupMode:
    """
    Before migration 0006 the backend cannot identify anyone, so it stays open
    rather than locking the operator out of the tool mid-setup.
    """

    def test_the_setup_caller_holds_the_wildcard(self):
        assert auth.SETUP_CALLER.can("users.manage")

    def test_setup_mode_hands_out_the_open_caller(self, monkeypatch):
        monkeypatch.setattr(auth, "auth_schema_ready", lambda: False)
        assert auth.current_caller(None) is auth.SETUP_CALLER

    def test_once_the_schema_exists_a_missing_token_is_nobody(self, monkeypatch):
        monkeypatch.setattr(auth, "auth_schema_ready", lambda: True)
        assert auth.current_caller(None) is None
        assert auth.current_caller("Basic abc") is None


class TestProfileCache:
    def test_forgetting_a_user_drops_their_cached_permissions(self):
        """A role change has to take effect without restarting the backend."""
        auth._profile_cache["u1"] = (2 ** 40, caller("supply.read"))
        auth.forget("u1")
        assert "u1" not in auth._profile_cache

    def test_forget_all_clears_everyone(self):
        auth._profile_cache["u1"] = (2 ** 40, caller("supply.read"))
        auth._profile_cache["u2"] = (2 ** 40, caller("supply.read"))
        auth.forget_all()
        assert auth._profile_cache == {}
