"""
Manuel senkronizasyon endpoint'leri. Faz 1'de zamanlanmış job (scheduler.py)
otomatik çalışacak, ama geliştirme sırasında "hemen şimdi çek" diyebilmek
için bu endpoint'ler kullanışlı.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.connectors import instagram, youtube
from app.database import get_db
from app.models import PlatformAccount
from app.security import EncryptionKeyError, decrypt

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
def sync_instagram(db: Session = Depends(get_db)):
    """/connect/instagram ile bağlanmış (token'ı veritabanında şifreli
    kayıtlı) tüm Instagram hesaplarını hemen senkronize eder. Token URL'de
    alınmaz; önce /connect/instagram ile hesabı bağla."""
    accounts = db.scalars(
        select(PlatformAccount).where(
            PlatformAccount.platform == "instagram",
            PlatformAccount.access_token_encrypted != "",
        )
    ).all()
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="Kayıtlı Instagram hesabı yok. Önce /connect/instagram ile bağlan.",
        )

    results = []
    for account in accounts:
        try:
            access_token = decrypt(account.access_token_encrypted)
            items = instagram.sync_account(account.external_account_id, access_token)
            saved = crud.upsert_metrics(db, account, items)
        except EncryptionKeyError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - geliştirme aşamasında ham hatayı
            # göstermek, sebepsiz 500'lerle uğraşmaktan çok daha faydalı.
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
        results.append({"account": account.display_name or account.external_account_id, "posts_synced": saved})

    return {"platform": "instagram", "accounts": results}
