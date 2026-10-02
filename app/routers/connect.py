"""
Hesap bağlama uçları. Dashboard'daki "YouTube bağla" ve "Instagram bağla"
butonları buraya gelir. Hesap giriş yapmış kullanıcıya bağlanır ve ilk
senkronizasyon arka planda başlar; terminalden komut çalıştırmak gerekmez.
Sonraki günlük güncellemeleri app/scheduler.py yapar.

Instagram tarafı OAuth akışı (workflow.html'deki sequence diyagramının kod
karşılığı) — INSTAGRAM_APP_ID/SECRET .env'de tanımlı olmalı.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import crud, scheduler
from app.auth import get_current_user
from app.connectors import instagram, youtube
from app.database import get_db
from app.models import User
from app.security import EncryptionKeyError, encrypt, require_encryption_key

router = APIRouter(prefix="/connect", tags=["connect"])

# OAuth state'i kullanıcının kendi oturum çerezinde tutulur: böylece callback
# sadece akışı başlatan oturumda kabul edilir ve birden çok worker'da da çalışır.
OAUTH_STATE_KEY = "instagram_oauth_state"


class YouTubeConnectRequest(BaseModel):
    handle: str


@router.post("/youtube", status_code=202)
def connect_youtube(
    body: YouTubeConnectRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kanal adını (@handle) ya da kanal id'sini alır. Kanalın var olduğunu
    hemen doğrular (yanlış ad anında hata olarak dönsün), videoları ise arka
    planda çeker."""
    handle = body.handle.strip()
    if not handle:
        raise HTTPException(status_code=400, detail="YouTube kanal adını gir.")
    try:
        channel_id = youtube.resolve_channel_id(handle)
    except youtube.YouTubeConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    account = crud.get_or_create_platform_account(
        db, user, platform="youtube", external_account_id=channel_id, display_name=handle
    )
    account.sync_status = "syncing"
    account.last_sync_error = None
    db.commit()
    background_tasks.add_task(scheduler.sync_account, account.id)
    return {"platform": "youtube", "account_id": account.id, "channel": handle, "status": "syncing"}


@router.get("/instagram")
def connect_instagram(request: Request, user: User = Depends(get_current_user)):
    # Token callback'te şifrelenip kaydedilecek; anahtar yoksa kullanıcıyı
    # Instagram'a hiç göndermeden şimdi durduralım.
    try:
        require_encryption_key()
    except EncryptionKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = secrets.token_urlsafe(16)
    try:
        url = instagram.build_authorize_url(state)
    except instagram.InstagramConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.session[OAUTH_STATE_KEY] = state
    return RedirectResponse(url)


@router.get("/instagram/callback")
def instagram_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    code: str | None = None,
    state: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expected_state = request.session.pop(OAUTH_STATE_KEY, None)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Geçersiz OAuth callback (code/state eksik veya yanlış).")

    try:
        token_data = instagram.exchange_code_for_token(code)
        short_lived_token = token_data.get("access_token")
        if not short_lived_token:
            raise HTTPException(status_code=400, detail="Token alınamadı.")

        long_lived = instagram.exchange_for_long_lived_token(short_lived_token)
        access_token = long_lived.get("access_token", short_lived_token)
        expires_in = long_lived.get("expires_in")  # saniye, genelde 5184000 (60 gün)

        accounts = instagram.fetch_connected_ig_accounts(access_token)
        if not accounts:
            raise HTTPException(status_code=400, detail="Bağlı Instagram hesabı bulunamadı.")

        ig_account = accounts[0]
        ig_account_id = ig_account["ig_account_id"]
        username = ig_account.get("page_name") or str(ig_account_id)

        # Token'ı şifreleyip giriş yapan kullanıcının hesabına kaydet;
        # scheduler.py da bu kayıttan otomatik senkronize edecek.
        account = crud.get_or_create_platform_account(
            db, user, platform="instagram", external_account_id=str(ig_account_id), display_name=username
        )
        account.access_token_encrypted = encrypt(access_token)
        if expires_in:
            account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        account.sync_status = "syncing"
        account.last_sync_error = None
        db.commit()
    except instagram.InstagramConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - ham hatayı göstermek anlamsız 500'lerle uğraşmaktan iyi
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    # İlk senkron arka planda; kullanıcı dashboard'a döner ve ilerlemeyi orada görür.
    background_tasks.add_task(scheduler.sync_account, account.id)
    return RedirectResponse("/?baglandi=instagram", status_code=303)
