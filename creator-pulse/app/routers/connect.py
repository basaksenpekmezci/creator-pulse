"""
Instagram OAuth bağlanma akışı (workflow.html'deki sequence diyagramının
kod karşılığı). Meta uygulama incelemesi tamamlanana kadar bu endpoint'ler
çalışır ama gerçek bir izin ekranına yönlendirme yapamaz — INSTAGRAM_APP_ID
.env'de tanımlı olmalı.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.connectors import instagram

router = APIRouter(prefix="/connect", tags=["connect"])

# NOT: Bu basit in-memory store sadece tek-worker geliştirme ortamı içindir.
# Üretimde state'i session/cookie ya da Redis'te tutmak gerekir.
_pending_states: set[str] = set()


@router.get("/instagram")
def connect_instagram():
    state = secrets.token_urlsafe(16)
    _pending_states.add(state)
    try:
        url = instagram.build_authorize_url(state)
    except instagram.InstagramConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url)


@router.get("/instagram/callback")
def instagram_callback(request: Request, code: str | None = None, state: str | None = None):
    if not code or not state or state not in _pending_states:
        raise HTTPException(status_code=400, detail="Geçersiz OAuth callback (code/state eksik veya yanlış).")
    _pending_states.discard(state)

    token_data = instagram.exchange_code_for_token(code)
    short_lived_token = token_data.get("access_token")
    if not short_lived_token:
        raise HTTPException(status_code=400, detail="Token alınamadı.")

    long_lived = instagram.exchange_for_long_lived_token(short_lived_token)
    access_token = long_lived.get("access_token", short_lived_token)

    accounts = instagram.fetch_connected_ig_accounts(access_token)
    # TODO: access_token'ı app/security.py::encrypt ile şifreleyip
    # PlatformAccount tablosuna kaydet (Meta onayı geldiğinde tamamlanacak).
    return {"message": "Bağlantı başarılı", "access_token_preview": access_token[:12] + "...", "accounts": accounts}
