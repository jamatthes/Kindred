"""Password hashing and opaque token generation.

argon2id via ``argon2-cffi`` with library defaults. No other algorithm is accepted (F-3):
there is no legacy hash format to fall back to, so a stored hash that argon2 refuses to parse
is a corrupt row, not an older scheme, and is treated as a failed verification.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: Single shared hasher. Parameters are the library defaults so they can be raised later and
#: picked up by `needs_rehash` on each successful login.
_hasher = PasswordHasher()

#: Bytes of entropy behind a session cookie value / CSRF token.
TOKEN_BYTES = 32

#: A real argon2 hash of a value nobody can log in with. Verifying against it on an unknown
#: username costs the same as verifying a real user, so response time does not reveal whether
#: the account exists. Computed once at import — the point is constant work per request, not
#: per process.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Return an argon2id hash of ``password``."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify ``password`` against ``password_hash``. Never raises."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> bool:
    """Burn one hash verification against :data:`DUMMY_HASH`. Always returns ``False``.

    Call this on the "no such user" branch of login so the branch costs what the real one
    costs. See `plan/features/foundation/design.md` > Security details > Timing.
    """
    verify_password(DUMMY_HASH, password)
    return False


def check_needs_rehash(password_hash: str) -> bool:
    """True when ``password_hash`` was made with weaker parameters than the current ones.

    Called on every successful login so raising the argon2 parameters later upgrades stored
    hashes transparently rather than requiring a password reset.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_token() -> str:
    """A fresh opaque token — used as the session cookie value and as the CSRF token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """sha256 of a token, hex-encoded. Only this is stored; the raw token lives in the cookie.

    A plain sha256 is correct here and argon2 would be wrong: the token is 32 bytes of
    CSPRNG output, so there is no low-entropy secret to slow a guesser down against, and the
    lookup is on the hot path of every authenticated request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
