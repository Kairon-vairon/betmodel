"""Sign in, sign out, who am I."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from edgewise.api.deps import ClockDep, DbDep, OwnerDep, SettingsDep, session_cookie_name
from edgewise.services import auth as auth_service
from edgewise.services.auth import LoginStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=6, max_length=12)


class OwnerOut(BaseModel):
    username: str


@router.post("/login", response_model=OwnerOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    clock: ClockDep,
    db: DbDep,
) -> OwnerOut:
    now = clock()
    result = auth_service.login(
        db,
        settings,
        username=body.username,
        password=body.password,
        code=body.code,
        now=now,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    if result.status is LoginStatus.LOCKED:
        db.commit()  # keep the lockout even though we answer with an error
        assert result.locked_until is not None
        minutes = max(1, math.ceil((result.locked_until - now).total_seconds() / 60))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
        )
    if result.status is LoginStatus.FAILED:
        db.commit()  # count the failed attempt
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "That email, password or code isn't right."
        )
    assert result.token is not None and result.owner is not None
    response.set_cookie(
        session_cookie_name(settings),
        result.token,
        max_age=settings.session_max_age_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return OwnerOut(username=result.owner.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, settings: SettingsDep, clock: ClockDep, db: DbDep) -> Response:
    name = session_cookie_name(settings)
    auth_service.logout(db, request.cookies.get(name), now=clock())
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        name, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict"
    )
    return response


@router.get("/me", response_model=OwnerOut)
def me(owner: OwnerDep) -> OwnerOut:
    return OwnerOut(username=owner.username)
