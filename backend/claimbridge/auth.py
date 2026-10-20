"""Explicit synthetic sandbox or server-authenticated, tenant-scoped access.

Credentials are operator-provisioned opaque tokens, never tenant IDs supplied by
the browser. Protected mode fails closed without credentials. This is a small
deployment boundary, not an identity-provider or clinical compliance claim.
"""
import hmac
import json
import os
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import HTTPException, Request


# A browser session (cookie) and the lifetime of an open event stream are both bounded by this.
SESSION_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    tenant_id: str | None = None


current: ContextVar[Principal | None] = ContextVar("principal", default=None)


def mode() -> str:
    value = os.getenv("AUTH_MODE", "demo")
    if value not in ("demo", "protected"):
        raise HTTPException(503, "Invalid access configuration.")
    return value


def authenticate(token: str) -> Principal:
    try:
        credentials = json.loads(os.getenv("AUTH_CREDENTIALS_JSON", "{}"))
        if not isinstance(credentials, dict) or not credentials:
            raise ValueError()
        for secret, info in credentials.items():
            if len(secret) < 32 or info.get("role") not in ("admin", "tenant") or not info.get("subject"):
                raise ValueError()
            if info["role"] == "tenant" and not info.get("tenant_id"):
                raise ValueError()
        for secret, info in credentials.items():
            if hmac.compare_digest(secret.encode(), token.encode()):
                return Principal(info["subject"], info["role"], info.get("tenant_id"))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(503, "Protected access is not configured.") from None
    raise HTTPException(401, "Sign in with an access token.")


def from_request(request: Request) -> Principal:
    if mode() == "demo":
        return Principal("synthetic-demo", "demo")
    authorization = request.headers.get("authorization", "")
    bearer = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    cookie = request.cookies.get("claimbridge_session", "")
    if not bearer and cookie and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-claimbridge-request") != "1":
            raise HTTPException(403, "Same-origin request header required.")
    return authenticate(bearer or cookie)


def tenant() -> str | None:
    p = current.get()
    return p.tenant_id if p and p.role == "tenant" else None


def require_admin():
    p = current.get()
    if p and p.role not in ("admin", "demo"):
        raise HTTPException(403, "Operator access required.")


def require_tenant(tenant_id: str):
    if tenant() is not None and tenant() != tenant_id:
        raise HTTPException(404, "Claim not found.")


def reviewer(fallback: str) -> str:
    p = current.get()
    return p.subject if p and p.role != "demo" else fallback
