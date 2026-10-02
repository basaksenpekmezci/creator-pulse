"""
Kullanıcı kimlik doğrulaması: şifre hash'leme (bcrypt) ve oturumdaki
kullanıcıyı bulan FastAPI bağımlılıkları.

Oturum, Starlette'in SessionMiddleware'i ile imzalı bir çerezde tutulur
(bkz. app/main.py). Çerezde sadece kullanıcı id'si bulunur; APP_SECRET_KEY
ile imzalandığı için kullanıcı tarafından değiştirilemez.
"""
from __future__ import annotations

import re

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

SESSION_USER_KEY = "user_id"
MIN_PASSWORD_LENGTH = 8
# bcrypt şifrenin sadece ilk 72 baytını kullanır (bcrypt 5 daha uzununu
# reddediyor); sessizce kesmek yerine kullanıcıya açıkça söylüyoruz.
MAX_PASSWORD_BYTES = 72
# bcrypt maliyet faktörü (2^12 tur). Testler hız için düşürür.
BCRYPT_ROUNDS = 12

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Kayıtlı olmayan bir e-postayla giriş denendiğinde de bir bcrypt kontrolü
# yapıyoruz ki yanıt süresinden e-postanın kayıtlı olup olmadığı anlaşılmasın.
_DUMMY_HASH = bcrypt.hashpw(b"creator-pulse-dummy", bcrypt.gensalt()).decode()


class AuthError(ValueError):
    """Kullanıcıya gösterilecek kayıt/giriş hatası."""


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_credentials(email: str, password: str) -> str:
    """Kayıt formunu doğrular, normalize edilmiş e-postayı döndürür."""
    email = normalize_email(email)
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise AuthError("Geçerli bir e-posta adresi gir.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AuthError("Şifre çok uzun (en fazla 72 bayt).")
    return email


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    encoded = (password or "").encode("utf-8")
    if not password_hash or len(encoded) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"x", _DUMMY_HASH.encode())
        return False
    return bcrypt.checkpw(encoded, password_hash.encode())


def login_session(request: Request, user: User) -> None:
    # Giriş öncesi oturumda kalan her şeyi (ör. yarım kalmış OAuth state'i)
    # temizle; oturum sabitleme (session fixation) riskini de kapatır.
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id


def logout_session(request: Request) -> None:
    request.session.clear()


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None:
        # Kullanıcı silinmişse bayat oturumu da temizle.
        request.session.clear()
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    """API uçları için: giriş yapılmamışsa 401 döner."""
    if user is None:
        raise HTTPException(status_code=401, detail="Giriş yapman gerekiyor.")
    return user
