"""Phase 3 verify (`plan/features/foundation/tasks.md`).

Deliberately free of database and settings imports: these are pure functions and the suite
should say so by not needing a fixture to run them.
"""

from __future__ import annotations

import pytest

from app.core import security


def test_hash_is_argon2id_and_salted() -> None:
    first = security.hash_password("correct horse battery staple")
    second = security.hash_password("correct horse battery staple")

    assert first.startswith("$argon2id$")
    # Distinct salts, so the same password never produces the same stored hash.
    assert first != second


def test_round_trip() -> None:
    password = "correct horse battery staple"
    assert security.verify_password(security.hash_password(password), password) is True


def test_wrong_password_fails() -> None:
    stored = security.hash_password("correct horse battery staple")
    assert security.verify_password(stored, "Correct horse battery staple") is False
    assert security.verify_password(stored, "") is False


def test_corrupt_hash_fails_rather_than_raising() -> None:
    # No legacy hash format exists, so an unparseable hash is a corrupt row, not an older
    # scheme. It must fail closed instead of blowing up the login handler.
    assert security.verify_password("not-a-hash", "anything") is False
    assert security.check_needs_rehash("not-a-hash") is True


def test_unknown_user_still_consumes_a_hash_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 'no such user' branch must cost what the real branch costs (timing attack)."""
    calls: list[tuple[str, str]] = []
    real_hasher = security._hasher

    class CountingHasher:
        """`PasswordHasher` uses __slots__, so wrap it rather than patching its method."""

        def verify(self, password_hash: str, password: str) -> bool:
            calls.append((password_hash, password))
            return real_hasher.verify(password_hash, password)

    monkeypatch.setattr(security, "_hasher", CountingHasher())

    assert security.verify_dummy("whatever they typed") is False

    assert len(calls) == 1, "unknown-username login did not perform a hash verification"
    assert calls[0][0] == security.DUMMY_HASH


def test_dummy_hash_is_a_real_argon2_hash_nobody_can_match() -> None:
    assert security.DUMMY_HASH.startswith("$argon2id$")
    assert security.verify_password(security.DUMMY_HASH, "") is False
    assert security.verify_password(security.DUMMY_HASH, "admin") is False


def test_needs_rehash_false_for_current_parameters() -> None:
    assert security.check_needs_rehash(security.hash_password("x" * 12)) is False


def test_token_generation_is_unique_and_urlsafe() -> None:
    tokens = {security.generate_token() for _ in range(50)}
    assert len(tokens) == 50
    for token in tokens:
        assert token.replace("-", "").replace("_", "").isalnum()


def test_token_hash_is_stable_sha256_hex() -> None:
    import hashlib

    token = "a-known-token"
    expected = hashlib.sha256(token.encode()).hexdigest()

    assert security.hash_token(token) == expected
    assert len(security.hash_token(token)) == 64
    # The stored value must not be the token itself.
    assert security.hash_token(token) != token
