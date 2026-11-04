"""Owner account, login and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from edgewise.auth import crypto, totp
from edgewise.auth.passwords import (
    burn_time,
    hash_password,
    needs_rehash,
    validate_new_password,
    verify_password,
)
from edgewise.config import Settings
from edgewise.db.models import AuthSession, Owner
from edgewise.services import audit


def normalise_username(username: str) -> str:
    return username.strip().lower()


class LoginStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    LOCKED = "locked"


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    token: str | None = None  # raw session token: goes in the cookie, never stored
    owner: Owner | None = None
    locked_until: datetime | None = None


def owner_exists(session: Session) -> bool:
    return bool(session.scalar(select(func.count()).select_from(Owner)))


def create_owner(
    session: Session,
    settings: Settings,
    *,
    username: str,
    password: str,
    totp_secret: str,
    now: datetime,
) -> Owner:
    """Create the single owner account. There can only ever be one."""
    if owner_exists(session):
        raise ValueError("An owner account already exists.")
    name = normalise_username(username)
    if not name:
        raise ValueError("Enter an email or username.")
    validate_new_password(password)
    owner = Owner(
        username=name,
        password_hash=hash_password(password),
        totp_secret_encrypted=crypto.encrypt(
            settings.app_secret_key.get_secret_value(), totp_secret
        ),
        created_at=now,
        password_changed_at=now,
    )
    session.add(owner)
    session.flush()
    audit.record(
        session,
        actor="owner",
        action="owner_created",
        at=now,
        entity_type="owner",
        entity_id=owner.id,
    )
    return owner


def login(
    session: Session,
    settings: Settings,
    *,
    username: str,
    password: str,
    code: str,
    now: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> LoginResult:
    """Check password and authenticator code. The caller must commit even on failure,
    so failed attempts are counted."""
    owner = session.scalar(select(Owner).where(Owner.username == normalise_username(username)))
    if owner is None:
        burn_time(password)
        return LoginResult(LoginStatus.FAILED)
    if owner.locked_until is not None and owner.locked_until > now:
        return LoginResult(LoginStatus.LOCKED, locked_until=owner.locked_until)

    step: int | None = None
    if verify_password(owner.password_hash, password):
        secret = crypto.decrypt(
            settings.app_secret_key.get_secret_value(), owner.totp_secret_encrypted
        )
        step = totp.verify(secret, code, now=now, last_step=owner.totp_last_step)

    if step is None:
        owner.failed_login_count += 1
        audit.record(
            session,
            actor="owner",
            action="login_failed",
            at=now,
            entity_type="owner",
            entity_id=owner.id,
            ip=ip_address,
        )
        if owner.failed_login_count >= settings.login_max_failures:
            owner.failed_login_count = 0
            owner.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            audit.record(
                session,
                actor="system",
                action="login_locked",
                at=now,
                entity_type="owner",
                entity_id=owner.id,
                until=owner.locked_until,
            )
            return LoginResult(LoginStatus.LOCKED, locked_until=owner.locked_until)
        return LoginResult(LoginStatus.FAILED)

    owner.failed_login_count = 0
    owner.locked_until = None
    owner.totp_last_step = step
    owner.last_login_at = now
    if needs_rehash(owner.password_hash):
        owner.password_hash = hash_password(password)

    token = crypto.new_session_token()
    session.add(
        AuthSession(
            owner_id=owner.id,
            token_hash=crypto.hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_max_age_hours),
            user_agent=(user_agent or "")[:255] or None,
            ip_address=ip_address,
        )
    )
    audit.record(
        session,
        actor="owner",
        action="login",
        at=now,
        entity_type="owner",
        entity_id=owner.id,
        ip=ip_address,
    )
    return LoginResult(LoginStatus.OK, token=token, owner=owner)


def authenticate(
    session: Session, settings: Settings, token: str | None, *, now: datetime
) -> Owner | None:
    """The owner for a session token, or None if it is unknown, revoked, expired or idle."""
    if not token:
        return None
    record = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == crypto.hash_token(token))
    )
    if record is None or record.revoked_at is not None or record.expires_at <= now:
        return None
    if record.last_seen_at + timedelta(hours=settings.session_idle_hours) <= now:
        return None
    if now - record.last_seen_at > timedelta(minutes=1):
        record.last_seen_at = now
    return record.owner


def logout(session: Session, token: str | None, *, now: datetime) -> None:
    if not token:
        return
    session.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == crypto.hash_token(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_all_sessions(session: Session, owner: Owner, *, now: datetime) -> None:
    session.execute(
        update(AuthSession)
        .where(AuthSession.owner_id == owner.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def get_owner(session: Session, username: str) -> Owner:
    owner = session.scalar(select(Owner).where(Owner.username == normalise_username(username)))
    if owner is None:
        raise ValueError(f"No owner called {username!r}.")
    return owner


def set_password(session: Session, owner: Owner, password: str, *, now: datetime) -> None:
    validate_new_password(password)
    owner.password_hash = hash_password(password)
    owner.password_changed_at = now
    owner.failed_login_count = 0
    owner.locked_until = None
    revoke_all_sessions(session, owner, now=now)
    audit.record(
        session,
        actor="owner",
        action="password_changed",
        at=now,
        entity_type="owner",
        entity_id=owner.id,
    )


def set_totp_secret(
    session: Session, settings: Settings, owner: Owner, secret: str, *, now: datetime
) -> None:
    owner.totp_secret_encrypted = crypto.encrypt(settings.app_secret_key.get_secret_value(), secret)
    owner.totp_last_step = None
    revoke_all_sessions(session, owner, now=now)
    audit.record(
        session,
        actor="owner",
        action="two_factor_reset",
        at=now,
        entity_type="owner",
        entity_id=owner.id,
    )
