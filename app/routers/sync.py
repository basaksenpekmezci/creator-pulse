"""
Manuel senkronizasyon endpoint'leri. Normal kullanımda hesaplar
dashboard'dan bağlanır ve zamanlayıcı (scheduler.py) günde bir günceller;
bu uçlar geliştirme sırasında "hemen şimdi çek" demek için duruyor. Hepsi
giriş gerektirir ve sadece giriş yapan kullanıcının hesaplarına dokunur.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.auth import get_current_user
from app.connectors import instagram, youtube
from app.database import get_db
from app.models import PlatformAccount, User
from app.security import EncryptionKeyError, decrypt

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/youtube")
def sync_youtube(handle: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Örnek: POST /sync/youtube?handle=MKBHD"""
    try:
        channel_id, items = youtube.sync_channel_with_id(handle)

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
def sync_instagram(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Kullanıcının /connect/instagram ile bağladığı (token'ı veritabanında
    şifreli kayıtlı) Instagram hesaplarını hemen senkronize eder. Token URL'de
    alınmaz; önce dashboard'daki "Instagram bağla" ile hesabı bağla."""
    accounts = db.scalars(
        select(PlatformAccount).where(
            PlatformAccount.user_id == user.id,
            PlatformAccount.platform == "instagram",
            PlatformAccount.access_token_encrypted != "",
        )
    ).all()
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="Kayıtlı Instagram hesabı yok. Önce dashboard'dan Instagram'ı bağla.",
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
