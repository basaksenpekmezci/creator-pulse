"""
Manuel senkronizasyon endpoint'leri. Faz 1'de zamanlanmış job (scheduler.py)
otomatik çalışacak, ama geliştirme sırasında "hemen şimdi çek" diyebilmek
için bu endpoint'ler kullanışlı.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud
from app.connectors import instagram, youtube
from app.database import get_db

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/youtube")
def sync_youtube(handle: str, db: Session = Depends(get_db)):
    """Örnek: POST /sync/youtube?handle=MKBHD"""
    try:
        channel_id, items = youtube.sync_channel_with_id(handle)

        user = crud.get_or_create_default_user(db)
        account = crud.get_or_create_platform_account(
            db, user, platform="youtube", external_account_id=channel_id, display_name=handle
        )
        saved = crud.upsert_metrics(db, account, items)
    except youtube.YouTubeConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - geliştirme aşamasında ham hatayı
        # göstermek, sebepsiz 500'lerle uğraşmaktan çok daha faydalı.
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    return {"platform": "youtube", "channel": handle, "videos_synced": saved}


@router.post("/instagram")
def sync_instagram(ig_account_id: str, access_token: str, db: Session = Depends(get_db)):
    """Instagram Business hesabı OAuth ile bağlandıktan sonra kullanılır.
    ig_account_id ve access_token normalde /connect/instagram/callback
    sırasında veritabanına kaydedilip buradan otomatik okunur — bu endpoint
    şimdilik manuel test için parametre olarak alıyor."""
    try:
        items = instagram.sync_account(ig_account_id, access_token)

        user = crud.get_or_create_default_user(db)
        account = crud.get_or_create_platform_account(
            db, user, platform="instagram", external_account_id=ig_account_id
        )
        saved = crud.upsert_metrics(db, account, items)
    except Exception as exc:  # noqa: BLE001 - geliştirme aşamasında ham hatayı
        # göstermek, sebepsiz 500'lerle uğraşmaktan çok daha faydalı.
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

    return {"platform": "instagram", "account": ig_account_id, "posts_synced": saved}
