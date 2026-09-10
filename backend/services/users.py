"""
Creating users, assigning roles, and defining what a role may do.

Creating a user needs the Supabase Admin API, which needs the secret key, which
must never reach the browser - so all of it runs here rather than in the
Next.js app.

Everything in this module refuses two things on principle:

  * removing the last administrator, by deletion, deactivation or demotion.
    There is no recovery path from a database with no admin except editing
    Postgres by hand.
  * editing or deleting a system role. `admin` is the wildcard, and a role that
    could be re-scoped is a role that could be scoped to nothing.
"""
import re
from typing import Any, Dict, List, Optional

import auth
import config
import db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 6


class UserError(Exception):
    """A rejection the caller should see in full - not an internal failure."""


# ------------------------------------------------------------------- reading
def list_permissions() -> List[Dict[str, Any]]:
    sb = db.client()
    return sb.table("permissions").select("*").order("sort_order").execute().data or []


def list_roles() -> List[Dict[str, Any]]:
    """Roles, each with how many people hold it - deleting one needs to know."""
    sb = db.client()
    roles = sb.table("roles").select("*").order("is_system", desc=True).order(
        "key").execute().data or []
    profiles = sb.table("profiles").select("role_key").limit(5000).execute().data or []
    counts: Dict[str, int] = {}
    for row in profiles:
        counts[row["role_key"]] = counts.get(row["role_key"], 0) + 1
    for role in roles:
        role["user_count"] = counts.get(role["key"], 0)
    return roles


def list_users() -> List[Dict[str, Any]]:
    sb = db.client()
    rows = sb.table("profiles").select(
        "id, email, full_name, role_key, is_active, created_at, "
        "roles(key, name, permissions, is_system)"
    ).order("created_at").limit(2000).execute().data or []

    # Last sign-in lives in auth.users, which PostgREST does not expose.
    last_seen: Dict[str, Any] = {}
    try:
        for user in sb.auth.admin.list_users():
            last_seen[str(user.id)] = getattr(user, "last_sign_in_at", None)
    except Exception:
        pass

    for row in rows:
        role = row.pop("roles", None) or {}
        row["role_name"] = role.get("name") or row.get("role_key")
        row["permissions"] = list(role.get("permissions") or [])
        row["is_admin"] = "*" in row["permissions"] or "users.manage" in row["permissions"]
        stamp = last_seen.get(row["id"])
        row["last_sign_in_at"] = str(stamp) if stamp else None
    return rows


def admin_count(exclude_id: Optional[str] = None) -> int:
    """How many active administrators remain, ignoring one user."""
    admins = [u for u in list_users() if u["is_admin"] and u["is_active"]]
    return len([u for u in admins if u["id"] != exclude_id])


# ------------------------------------------------------------------- writing
def create_user(email: str, password: str, role_key: str,
                full_name: Optional[str] = None) -> Dict[str, Any]:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise UserError("%r is not a valid email address." % email)
    if len(password or "") < MIN_PASSWORD:
        raise UserError("The password must be at least %d characters." % MIN_PASSWORD)

    sb = db.client()
    if not sb.table("roles").select("key").eq("key", role_key).execute().data:
        raise UserError("No such role: %s" % role_key)

    try:
        created = sb.auth.admin.create_user({
            "email": email,
            "password": password,
            # No mail server is configured, and an admin creating an account
            # for a colleague has already vouched for the address.
            "email_confirm": True,
            "user_metadata": {"role": role_key, "full_name": full_name or ""},
        })
    except Exception as exc:
        message = str(exc)
        if "already" in message.lower():
            raise UserError("%s already has an account." % email)
        raise UserError("Could not create the account: %s" % message)

    user_id = str(created.user.id)
    # The trigger writes the profile; this settles the role and name in case the
    # trigger ran before the metadata was visible to it.
    sb.table("profiles").upsert({
        "id": user_id,
        "email": email,
        "full_name": full_name or None,
        "role_key": role_key,
        "is_active": True,
    }).execute()
    auth.forget(user_id)
    return {"id": user_id, "email": email, "role_key": role_key}


def update_user(user_id: str, role_key: Optional[str] = None,
                is_active: Optional[bool] = None,
                full_name: Optional[str] = None) -> Dict[str, Any]:
    sb = db.client()
    existing = sb.table("profiles").select("*").eq("id", user_id).limit(1).execute().data
    if not existing:
        raise UserError("No such user.")

    patch: Dict[str, Any] = {}
    if role_key is not None:
        if not sb.table("roles").select("key").eq("key", role_key).execute().data:
            raise UserError("No such role: %s" % role_key)
        patch["role_key"] = role_key
    if is_active is not None:
        patch["is_active"] = bool(is_active)
    if full_name is not None:
        patch["full_name"] = full_name.strip() or None

    # Demoting or deactivating the last admin locks everyone out of user
    # management permanently, so both are refused rather than warned about.
    losing_admin = ("role_key" in patch and not _grants_admin(patch["role_key"])) or \
                   (patch.get("is_active") is False)
    if losing_admin and admin_count(exclude_id=user_id) == 0:
        raise UserError(
            "This is the last administrator. Give another user the "
            "Administrator role first.")

    if not patch:
        return existing[0]

    sb.table("profiles").update(patch).eq("id", user_id).execute()
    if "role_key" in patch:
        try:
            sb.auth.admin.update_user_by_id(
                user_id, {"user_metadata": {"role": patch["role_key"]}})
        except Exception:
            pass  # the profile is authoritative; metadata is a convenience
    auth.forget(user_id)
    return sb.table("profiles").select("*").eq("id", user_id).limit(1).execute().data[0]


def set_password(user_id: str, password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise UserError("The password must be at least %d characters." % MIN_PASSWORD)
    try:
        db.client().auth.admin.update_user_by_id(user_id, {"password": password})
    except Exception as exc:
        raise UserError("Could not change the password: %s" % exc)


def delete_user(user_id: str) -> None:
    if admin_count(exclude_id=user_id) == 0:
        raise UserError(
            "This is the last administrator. Give another user the "
            "Administrator role first.")
    try:
        db.client().auth.admin.delete_user(user_id)
    except Exception as exc:
        raise UserError("Could not delete the account: %s" % exc)
    # `profiles` cascades from auth.users, but tidy up if the cascade is absent.
    db.client().table("profiles").delete().eq("id", user_id).execute()
    auth.forget(user_id)


def _grants_admin(role_key: str) -> bool:
    rows = db.client().table("roles").select("permissions").eq(
        "key", role_key).limit(1).execute().data or []
    perms = list((rows[0] if rows else {}).get("permissions") or [])
    return "*" in perms or "users.manage" in perms


# --------------------------------------------------------------------- roles
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def create_role(name: str, permissions: List[str],
                description: str = "", key: Optional[str] = None) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise UserError("Give the role a name.")
    key = _slug(key or name)
    if not key:
        raise UserError("That name does not make a usable role key.")

    sb = db.client()
    if sb.table("roles").select("key").eq("key", key).execute().data:
        raise UserError("A role called %s already exists." % name)

    row = {"key": key, "name": name, "description": (description or "").strip() or None,
           "permissions": _clean_permissions(permissions), "is_system": False}
    sb.table("roles").insert(row).execute()
    return row


def update_role(key: str, name: Optional[str] = None,
                description: Optional[str] = None,
                permissions: Optional[List[str]] = None) -> Dict[str, Any]:
    sb = db.client()
    existing = sb.table("roles").select("*").eq("key", key).limit(1).execute().data
    if not existing:
        raise UserError("No such role: %s" % key)
    if existing[0].get("is_system"):
        raise UserError(
            "%s is a built-in role and cannot be changed. Create a new role "
            "instead." % existing[0]["name"])

    patch: Dict[str, Any] = {}
    if name is not None and name.strip():
        patch["name"] = name.strip()
    if description is not None:
        patch["description"] = description.strip() or None
    if permissions is not None:
        patch["permissions"] = _clean_permissions(permissions)
        # Re-scoping a role can strand the tool with no administrator just as
        # surely as demoting a user can.
        if "users.manage" not in patch["permissions"]:
            holders = sb.table("profiles").select("id").eq("role_key", key).eq(
                "is_active", True).execute().data or []
            if holders and _role_is_only_admin_route(key):
                raise UserError(
                    "Removing user management from this role would leave nobody "
                    "able to administer the tool.")

    if not patch:
        return existing[0]
    sb.table("roles").update(patch).eq("key", key).execute()
    auth.forget_all()
    return sb.table("roles").select("*").eq("key", key).limit(1).execute().data[0]


def delete_role(key: str) -> None:
    sb = db.client()
    existing = sb.table("roles").select("*").eq("key", key).limit(1).execute().data
    if not existing:
        raise UserError("No such role: %s" % key)
    if existing[0].get("is_system"):
        raise UserError("%s is a built-in role and cannot be deleted."
                        % existing[0]["name"])

    holders = sb.table("profiles").select("id, email").eq(
        "role_key", key).execute().data or []
    if holders:
        raise UserError(
            "%d user%s still hold%s this role. Move them to another role first."
            % (len(holders), "" if len(holders) == 1 else "s",
               "s" if len(holders) == 1 else ""))

    sb.table("roles").delete().eq("key", key).execute()
    auth.forget_all()


def _role_is_only_admin_route(key: str) -> bool:
    """True when this role is the only active source of user management."""
    for user in list_users():
        if user["is_active"] and user["is_admin"] and user["role_key"] != key:
            return False
    return True


def _clean_permissions(permissions: List[str]) -> List[str]:
    """Keep only permissions the catalogue knows. The wildcard is admin-only."""
    known = {p["key"] for p in list_permissions()}
    return sorted({p for p in (permissions or []) if p in known})


# ------------------------------------------------------------- first-run seed
def ensure_seed_admin() -> Optional[Dict[str, Any]]:
    """
    Create the first administrator when the database has no users at all.

    Without this there is no way in: creating a user needs the user-management
    permission, and nobody holds it yet. It runs only on a completely empty
    profiles table, so it can never overwrite or resurrect a real account.
    """
    if not config.supabase_configured() or not auth.auth_schema_ready():
        return None
    sb = db.client()
    try:
        if sb.table("profiles").select("id").limit(1).execute().data:
            return None
    except Exception:
        return None

    try:
        created = create_user(config.SEED_ADMIN_EMAIL, config.SEED_ADMIN_PASSWORD,
                              "admin", full_name="Administrator")
    except UserError as exc:
        # The auth user can outlive its profile if the profiles table was
        # dropped and recreated. Adopt it rather than failing.
        if "already has an account" not in str(exc):
            return None
        found = [u for u in sb.auth.admin.list_users()
                 if (u.email or "").lower() == config.SEED_ADMIN_EMAIL.lower()]
        if not found:
            return None
        user_id = str(found[0].id)
        sb.table("profiles").upsert({
            "id": user_id, "email": config.SEED_ADMIN_EMAIL,
            "full_name": "Administrator", "role_key": "admin", "is_active": True,
        }).execute()
        created = {"id": user_id, "email": config.SEED_ADMIN_EMAIL, "role_key": "admin"}

    return created
