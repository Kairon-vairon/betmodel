"""Password hashing with Argon2id."""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(set(password)) < 4:
        raise ValueError("That password is too simple.")


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("edgewise-timing-equaliser")


def burn_time(password: str) -> None:
    """Spend the same time as a real check, so unknown usernames can't be spotted by timing."""
    verify_password(_dummy_hash(), password)
