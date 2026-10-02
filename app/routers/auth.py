"""
Kayıt olma, giriş ve çıkış sayfaları. Formlar klasik HTML POST ile çalışır
(JavaScript gerekmez); başarılı kayıt/girişte oturum çerezi kurulur ve
kullanıcı dashboard'a yönlendirilir.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.auth import (
    MIN_PASSWORD_LENGTH,
    AuthError,
    get_optional_user,
    hash_password,
    login_session,
    logout_session,
    normalize_email,
    validate_credentials,
    verify_password,
)
from app.database import get_db
from app.models import User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")


def _render(request: Request, mode: str, email: str = "", error: str = "", status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {"mode": mode, "email": email, "error": error, "min_password_length": MIN_PASSWORD_LENGTH},
        status_code=status_code,
    )


@router.get("/register")
def register_page(request: Request, user: User | None = Depends(get_optional_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return _render(request, "register")


@router.post("/register")
def register(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        email = validate_credentials(email, password)
        if password != password_confirm:
            raise AuthError("Şifreler eşleşmiyor.")
        if crud.get_user_by_email(db, email) is not None or email == crud.LEGACY_USER_EMAIL:
            raise AuthError("Bu e-postayla zaten bir hesap var. Giriş yapmayı dene.")
        try:
            user = crud.create_user(db, email, hash_password(password))
        except IntegrityError as exc:  # aynı anda iki kayıt isteği
            db.rollback()
            raise AuthError("Bu e-postayla zaten bir hesap var. Giriş yapmayı dene.") from exc
    except AuthError as exc:
        return _render(request, "register", email=normalize_email(email), error=str(exc), status_code=400)

    crud.claim_legacy_data(db, user)
    login_session(request, user)
    return RedirectResponse("/", status_code=303)


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(get_optional_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return _render(request, "login")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    email = normalize_email(email)
    user = crud.get_user_by_email(db, email)
    if not verify_password(password, user.password_hash if user else None):
        return _render(request, "login", email=email, error="E-posta ya da şifre hatalı.", status_code=400)
    login_session(request, user)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=303)
