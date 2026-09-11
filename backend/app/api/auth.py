"""Login endpoints (BRD S1): email + password, no self-registration."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core import auth
from app.core.config import get_settings

router = APIRouter(prefix="/auth")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: LoginRequest, response: Response) -> dict:
    result = auth.login(body.email, body.password)
    if result is None:
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    token, csrf = result
    response.set_cookie(
        auth.COOKIE_NAME, token,
        httponly=True, samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=get_settings().session_ttl_hours * 3600,
    )
    # The CSRF token is deliberately NOT a cookie — the frontend keeps it in
    # memory and echoes it in the X-CSRF-Token header, which a cross-site
    # attacker cannot read or set.
    return {"ok": True, "csrf_token": csrf}


@router.post("/logout")
def logout(response: Response,
           qct_session: str | None = Cookie(default=None)) -> dict:
    if qct_session:
        auth.end_session(qct_session)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: Annotated[dict, Depends(auth.require_user)],
       qct_session: str | None = Cookie(default=None)) -> dict:
    # Return the CSRF token too, so a page reload on an existing session can
    # recover it without re-logging in.
    return {
        "email": user["email"],
        "name": user["name"],
        "csrf_token": auth.csrf_token_for(qct_session) or "",
    }
