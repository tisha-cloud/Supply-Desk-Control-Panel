"""
User access: who exists, what role they hold, and what each role may do.

Split out of main.py because it is the one area where the backend is doing
something the browser cannot: creating accounts needs the Supabase Admin API,
which needs the secret key.

Every route here except /api/me requires the `users.manage` permission, and
services/users.py refuses anything that would leave the tool with no
administrator.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
from auth import Caller, require, require_user
from services.users import UserError

router = APIRouter(prefix="/api", tags=["access"])

ADMIN = Depends(require("users.manage"))


def _guard(action):
    """Run a users.py call, turning its rejections into 400s the UI can show."""
    try:
        return action()
    except UserError as exc:
        raise HTTPException(400, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Unexpected failure: %s" % exc)


# ------------------------------------------------------------------ identity
@router.get("/me")
def me(caller: Caller = Depends(require_user)):
    """
    The signed-in user, with the permissions their role carries.

    The browser uses this to decide what to render. It is a convenience, not a
    control: the same permissions are enforced by row-level security and by the
    guards on every other route.
    """
    return caller.as_dict()


# --------------------------------------------------------------------- roles
class RoleBody(BaseModel):
    name: str
    permissions: List[str] = []
    description: str = ""
    key: Optional[str] = None


class RolePatch(BaseModel):
    name: Optional[str] = None
    permissions: Optional[List[str]] = None
    description: Optional[str] = None


@router.get("/access/permissions")
def permissions(caller: Caller = Depends(require_user)):
    """The catalogue of things a role can be granted. Readable by anyone."""
    from services import users
    return _guard(users.list_permissions)


@router.get("/access/roles")
def roles(caller: Caller = Depends(require_user)):
    from services import users
    return _guard(users.list_roles)


@router.post("/access/roles")
def create_role(body: RoleBody, caller: Caller = ADMIN):
    from services import users
    return _guard(lambda: users.create_role(
        body.name, body.permissions, body.description, body.key))


@router.patch("/access/roles/{key}")
def update_role(key: str, body: RolePatch, caller: Caller = ADMIN):
    from services import users
    return _guard(lambda: users.update_role(
        key, body.name, body.description, body.permissions))


@router.delete("/access/roles/{key}")
def delete_role(key: str, caller: Caller = ADMIN):
    from services import users
    _guard(lambda: users.delete_role(key))
    return {"deleted": key}


# --------------------------------------------------------------------- users
class UserBody(BaseModel):
    email: str
    password: str
    role_key: str
    full_name: Optional[str] = None


class UserPatch(BaseModel):
    role_key: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None


class PasswordBody(BaseModel):
    password: str


@router.get("/access/users")
def list_users(caller: Caller = ADMIN):
    from services import users
    return _guard(users.list_users)


@router.post("/access/users")
def create_user(body: UserBody, caller: Caller = ADMIN):
    from services import users
    return _guard(lambda: users.create_user(
        body.email, body.password, body.role_key, body.full_name))


@router.patch("/access/users/{user_id}")
def update_user(user_id: str, body: UserPatch, caller: Caller = ADMIN):
    from services import users
    # Deactivating or demoting yourself is a mistake, not a feature. The
    # last-admin guard in users.py would not catch it while another admin
    # exists, and the effect is the same to whoever clicked it.
    if user_id == caller.user_id:
        if body.is_active is False:
            raise HTTPException(400, "You cannot deactivate your own account.")
        if body.role_key and body.role_key != caller.role:
            raise HTTPException(
                400, "You cannot change your own role. Ask another administrator.")
    return _guard(lambda: users.update_user(
        user_id, body.role_key, body.is_active, body.full_name))


@router.post("/access/users/{user_id}/password")
def set_password(user_id: str, body: PasswordBody, caller: Caller = ADMIN):
    from services import users
    _guard(lambda: users.set_password(user_id, body.password))
    return {"updated": user_id}


@router.delete("/access/users/{user_id}")
def delete_user(user_id: str, caller: Caller = ADMIN):
    from services import users
    if user_id == caller.user_id:
        raise HTTPException(400, "You cannot delete your own account.")
    _guard(lambda: users.delete_user(user_id))
    return {"deleted": user_id}


# ---------------------------------------------------------------- setup help
@router.get("/access/status")
def status():
    """
    Whether authentication is switched on yet. Deliberately unauthenticated:
    the login screen has to be able to ask before anyone can sign in.
    """
    import auth as auth_module
    ready = auth_module.auth_schema_ready()
    return {
        "auth_ready": ready,
        "supabase_configured": config.supabase_configured(),
        "seed_admin_email": config.SEED_ADMIN_EMAIL if ready else None,
    }
