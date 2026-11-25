from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Request
from jwt import PyJWKClient

from idp.config import Settings
from idp.errors import AppError

VALID_ROLES = {"operator", "reviewer", "administrator", "auditor"}
PERMISSIONS: dict[str, set[str]] = {
    "view": VALID_ROLES,
    "upload": {"operator", "reviewer", "administrator"},
    "retry": {"operator", "reviewer", "administrator"},
    "review": {"reviewer", "administrator"},
    "audit": {"reviewer", "administrator", "auditor"},
    "admin": {"administrator"},
}


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    roles: frozenset[str]

    def require(self, permission: str) -> None:
        allowed = PERMISSIONS.get(permission, set())
        if not self.roles.intersection(allowed):
            raise AppError(403, "forbidden", "Forbidden", "You are not authorized for this action.")


class Authenticator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwk_client = (
            PyJWKClient(settings.oidc_jwks_url) if settings.auth_mode == "oidc" else None
        )

    def authenticate(self, request: Request) -> Principal:
        if self.settings.auth_mode == "demo":
            return self._authenticate_demo(request)
        return self._authenticate_oidc(request)

    def _authenticate_demo(self, request: Request) -> Principal:
        if self.settings.environment not in {"development", "test"}:
            raise AppError(
                500, "unsafe_auth_mode", "Configuration error", "Authentication is unavailable."
            )
        subject = request.headers.get("X-Demo-User", self.settings.demo_user_id).strip()
        tenant_id = request.headers.get("X-Demo-Tenant", self.settings.demo_tenant_id).strip()
        requested_roles = request.headers.get("X-Demo-Role", self.settings.demo_role)
        roles = frozenset(role.strip() for role in requested_roles.split(",") if role.strip())
        if not subject or not tenant_id or not roles or not roles.issubset(VALID_ROLES):
            raise AppError(
                401, "invalid_demo_identity", "Unauthorized", "The demo identity is invalid."
            )
        return Principal(subject=subject[:200], tenant_id=tenant_id[:100], roles=roles)

    def _authenticate_oidc(self, request: Request) -> Principal:
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AppError(
                401, "authentication_required", "Unauthorized", "A bearer token is required."
            )
        try:
            assert self._jwk_client is not None
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except Exception as exc:
            raise AppError(
                401,
                "invalid_token",
                "Unauthorized",
                "The bearer token is invalid or expired.",
            ) from exc
        tenant = claims.get(self.settings.tenant_claim)
        raw_roles = claims.get(self.settings.roles_claim, [])
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        roles = frozenset(str(role) for role in raw_roles if str(role) in VALID_ROLES)
        if not isinstance(tenant, str) or not tenant or not roles:
            raise AppError(
                403, "missing_access_claims", "Forbidden", "Required access claims are missing."
            )
        return Principal(subject=str(claims["sub"])[:200], tenant_id=tenant[:100], roles=roles)
