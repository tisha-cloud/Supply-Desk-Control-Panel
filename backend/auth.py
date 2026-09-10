"""
Who is calling, and what are they allowed to do.

The browser holds a Supabase session and sends its access token as a bearer
token. This module turns that token into a caller - user id, email, role and
the permissions that role carries - and refuses the request when the caller
lacks the permission a route requires.

Two independent checks guard every write, deliberately:

  * Row-level security in Postgres (migration 0006) governs what the browser
    can do talking to Supabase directly. That is the one that actually cannot
    be bypassed.
  * This module governs the FastAPI backend, which holds the secret key and
    bypasses RLS by design. Without it, any unauthenticated caller could reach
    the import and extraction endpoints and write anything they liked.

Verification order: the JSON Web Key Set first, because it needs no network
call once cached; then the Auth API, which validates the token server-side and
works on projects still signing with a shared secret.
"""
import time
from typing import Any, Dict, List, Optional

import httpx
import jwt
from fastapi import Depends, Header, HTTPException

import config
import db

# Cached JWKS client. Fetching the key set is a network call, so it happens
# once per process rather than once per request.
_jwks_client: Optional[jwt.PyJWKClient] = None
_jwks_failed = False

# Profile lookups are cached briefly: a burst of requests from one page load
# should not become a burst of database queries. Short enough that revoking a
# role takes effect within seconds.
_PROFILE_TTL = 15.0
_profile_cache: Dict[str, Any] = {}

# Whether migration 0006 has been run. Cached after the first successful check.
_auth_schema_ready: Optional[bool] = None


class Caller:
    """The authenticated user behind a request."""

    def __init__(self, user_id: str, email: str, role: str,
                 permissions: List[str], is_active: bool = True,
                 full_name: Optional[str] = None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.permissions = permissions
        self.is_active = is_active
        self.full_name = full_name

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    @property
    def is_admin(self) -> bool:
        return self.can("users.manage")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.user_id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "permissions": self.permissions,
            "is_active": self.is_active,
        }


def auth_schema_ready() -> bool:
    """
    True once migration 0006 has created the profiles table.

    Until then the backend cannot know who anyone is, so it stays open and says
    so loudly in /api/health rather than locking the operator out of the tool
    they are in the middle of setting up. The moment the table exists, every
    route below enforces.
    """
    global _auth_schema_ready
    if _auth_schema_ready:
        return True
    if not config.supabase_configured():
        return False
    try:
        db.client().table("profiles").select("id").limit(1).execute()
        _auth_schema_ready = True
    except Exception:
        _auth_schema_ready = False
    return bool(_auth_schema_ready)


# ------------------------------------------------------------ token decoding
def _jwks_url() -> str:
    configured = getattr(config, "SUPABASE_JWKS_URL", "") or ""
    if configured:
        return configured
    return "%s/auth/v1/.well-known/jwks.json" % (config.SUPABASE_URL or "").rstrip("/")


def _claims_via_jwks(token: str) -> Optional[Dict[str, Any]]:
    """Verify the signature locally against the project key set."""
    global _jwks_client, _jwks_failed
    if _jwks_failed:
        return None
    try:
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(_jwks_url(), cache_keys=True)
        key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token, key.key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience="authenticated",
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        # A well-formed token that this key set cannot verify is not our
        # problem to retry: fall through to the Auth API.
        return None
    except Exception:
        # No key set published - a project still signing with a shared secret.
        # Stop trying; the Auth API path handles it.
        _jwks_failed = True
        return None


def _claims_via_auth_api(token: str) -> Optional[Dict[str, Any]]:
    """Ask the Auth server who this token belongs to. Works on any project."""
    url = "%s/auth/v1/user" % (config.SUPABASE_URL or "").rstrip("/")
    try:
        response = httpx.get(url, timeout=8.0, headers={
            "Authorization": "Bearer %s" % token,
            "apikey": config.SUPABASE_PUBLISHABLE_KEY or "",
        })
    except Exception:
        return None
    if response.status_code != 200:
        return None
    body = response.json()
    return {"sub": body.get("id"), "email": body.get("email")}


def decode(token: str) -> Optional[Dict[str, Any]]:
    return _claims_via_jwks(token) or _claims_via_auth_api(token)


# ------------------------------------------------------------ profile lookup
def load_caller(user_id: str, email: str = "") -> Optional[Caller]:
    """Read the role and permissions for a verified user id."""
    cached = _profile_cache.get(user_id)
    if cached and cached[0] > time.time():
        return cached[1]

    try:
        rows = db.client().table("profiles").select(
            "id, email, full_name, role_key, is_active, roles(key, permissions)"
        ).eq("id", user_id).limit(1).execute().data or []
    except Exception:
        return None
    if not rows:
        return None

    row = rows[0]
    role = row.get("roles") or {}
    caller = Caller(
        user_id=row["id"],
        email=row.get("email") or email,
        role=row.get("role_key") or "viewer",
        permissions=list(role.get("permissions") or []),
        is_active=bool(row.get("is_active", True)),
        full_name=row.get("full_name"),
    )
    _profile_cache[user_id] = (time.time() + _PROFILE_TTL, caller)
    return caller


def forget(user_id: str) -> None:
    """Drop a cached profile, so a role change takes effect immediately."""
    _profile_cache.pop(user_id, None)


def forget_all() -> None:
    _profile_cache.clear()


# --------------------------------------------------------- FastAPI plumbing
# The open caller used only while migration 0006 has not been run. It holds the
# wildcard so the tool keeps working during setup; `auth_schema_ready` is what
# decides whether it is ever handed out.
SETUP_CALLER = Caller(user_id="setup", email="setup@local",
                      role="admin", permissions=["*"])


def current_caller(authorization: Optional[str] = Header(None)) -> Optional[Caller]:
    """The caller behind this request, or None when there is no valid session."""
    if not auth_schema_ready():
        return SETUP_CALLER
    if not authorization or not authorization.lower().startswith("bearer "):
        return None

    claims = decode(authorization.split(None, 1)[1].strip())
    if not claims or not claims.get("sub"):
        return None
    return load_caller(claims["sub"], claims.get("email") or "")


def require_user(caller: Optional[Caller] = Depends(current_caller)) -> Caller:
    if caller is None:
        raise HTTPException(401, "Sign in to use this.")
    if not caller.is_active:
        raise HTTPException(403, "This account has been deactivated.")
    return caller


def require(permission: str):
    """
    Dependency factory: refuse the request unless the caller holds `permission`.

        @app.post("/api/import", dependencies=[Depends(require("supply.import"))])
    """
    def guard(caller: Caller = Depends(require_user)) -> Caller:
        if not caller.can(permission):
            raise HTTPException(
                403,
                "Your role (%s) does not include %s." % (caller.role, permission))
        return caller
    return guard
