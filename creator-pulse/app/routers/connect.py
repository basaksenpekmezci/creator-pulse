"""
Instagram OAuth bağlanma akışı (workflow.html'deki sequence diyagramının
kod karşılığı). Meta uygulama incelemesi tamamlanana kadar bu endpoint'ler
çalışır ama gerçek bir izin ekranına yönlendirme yapamaz — INSTAGRAM_APP_ID
.env'de tanımlı olmalı.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import crud
from app.connectors import instagram
from app.database import get_db
from app.security import encrypt

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
def instagram_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    if not code or not state or state not in _pending_states:
        raise HTTPException(status_code=400, detail="Geçersiz OAuth callback (code/state eksik veya yanlış).")
    _pending_states.discard(state)

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

        # Token'ı şifreleyip veritabanına kalıcı olarak kaydet — artık her
        # bağlantı kurulduğunda yeniden manuel token kopyalamaya gerek yok,
        # scheduler.py da bu kayıttan otomatik senkronize edebilecek.
        user = crud.get_or_create_default_user(db)
        account = crud.get_or_create_platform_account(
            db, user, platform="instagram", external_account_id=str(ig_account_id), display_name=username
        )
        account.access_token_encrypted = encrypt(access_token)
        if expires_in:
            account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        db.commit()

        # Kullanıcı ayrıca /sync/instagram çağırmak zorunda kalmasın diye
        # bağlantı kurulur kurulmaz ilk senkronizasyonu da burada yapalım.
        items = instagram.sync_account(ig_account_id, access_token)
        saved = crud.upsert_metrics(db, account, items)
    except instagram.InstagramConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - ham hatayı göstermek anlamsız 500'lerle uğraşmaktan iyi
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    return {
        "message": "Instagram bağlantısı başarılı ve kaydedildi",
        "account": username,
        "posts_synced": saved,
    }
