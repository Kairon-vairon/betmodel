"""Shared request dependencies: settings, database session, clock, signed-in owner."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from edgewise.config import Settings
from edgewise.db.models import Owner
from edgewise.services import auth as auth_service

Clock = Callable[[], datetime]


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def session_cookie_name(settings: Settings) -> str:
    # The __Host- prefix makes browsers refuse the cookie unless it is Secure, host-only
    # and path=/, so a subdomain or plain-http page can never set or read it.
    return "__Host-edgewise_session" if settings.cookie_secure else "edgewise_session"


SettingsDep = Annotated[Settings, Depends(get_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]
# scope="function": commit BEFORE the response is sent, so a client never sees success
# for a change that is not yet saved (e.g. a new login session).
DbDep = Annotated[Session, Depends(get_db, scope="function")]


def current_owner(request: Request, settings: SettingsDep, clock: ClockDep, db: DbDep) -> Owner:
    token = request.cookies.get(session_cookie_name(settings))
    owner = auth_service.authenticate(db, settings, token, now=clock())
    if owner is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    return owner


OwnerDep = Annotated[Owner, Depends(current_owner)]
