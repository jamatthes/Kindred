"""Auth request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.user import UserOut

#: F-5: there is no minimum password length. A password must merely be non-empty.
#:
#: The 1024-character ceiling below is not a policy limit, it is a denial-of-service guard:
#: argon2 hashes whatever it is handed, so an unbounded field lets one request burn arbitrary
#: CPU. Nobody types 1024 characters, so it constrains an attacker and not a user.
MIN_PASSWORD_LENGTH = 1


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # No min_length: a short password must fail as *wrong credentials*, not as a validation
    # error, or the 422 tells an attacker their guess was too short to be this user's.
    password: str = Field(min_length=1, max_length=1024)


class LoginOut(BaseModel):
    """The session and CSRF tokens also arrive as cookies; ``csrf_token`` is repeated in the
    body so a client can hold it in memory rather than reading it back from `document.cookie`.
    """

    user: UserOut
    csrf_token: str


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class SettingsOut(BaseModel):
    """The public subset, readable before login so the login screen can show the instance
    name. Everything else in `settings` requires the main admin and belongs to `admin-console`.
    """

    instance_name: str
    registration_open: bool
    invite_only: bool


class HealthOut(BaseModel):
    status: str
    version: str
    db: str = Field(description='"ok" or "down" — the result of a real query, not a guess.')
