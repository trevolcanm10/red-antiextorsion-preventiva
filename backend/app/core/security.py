"""Argon2id passwords and strictly validated JWT access tokens."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, StrictInt, model_validator
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import AuthSettings

ALGORITHM = "HS256"
password_hasher = PasswordHash.recommended()  # Argon2id: m=65536, t=3, p=4.


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Warm at startup; absent users still incur real password verification."""
    return hash_password("synthetic-dummy-password-not-an-account")


def verify_password(password: str, stored_hash: str) -> tuple[bool, str | None]:
    try:
        return password_hasher.verify_and_update(password, stored_hash)
    except UnknownHashError:
        password_hasher.verify(password, dummy_password_hash())
        return False, None


class AccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sub: UUID
    organization_id: UUID
    iat: StrictInt
    exp: StrictInt
    iss: str
    aud: str

    @model_validator(mode="after")
    def chronological(self) -> "AccessClaims":
        if self.exp <= self.iat:
            raise ValueError("Invalid token lifetime")
        return self


def create_access_token(user_id: UUID, organization_id: UUID, settings: AuthSettings) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "organization_id": str(organization_id),
         "iat": int(now.timestamp()),
         "exp": int((now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES)).timestamp()),
         "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
        settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM,
    )


def decode_access_token(token: str, settings: AuthSettings) -> AccessClaims:
    payload = jwt.decode(
        token, settings.JWT_SECRET.get_secret_value(), algorithms=[ALGORITHM],
        issuer=settings.JWT_ISSUER, audience=settings.JWT_AUDIENCE,
        options={"require": ["sub", "organization_id", "iat", "exp", "iss", "aud"],
                 "strict_aud": True},
    )
    return AccessClaims.model_validate(payload)
