"""
Basit veritabanı yardımcı fonksiyonları. MVP'de tek kullanıcı olduğu için
`get_or_create_default_user` var — Faz 4'te gerçek login sistemi eklenince
bu fonksiyonun yerini normal auth alacak, ama tablo yapısı zaten hazır.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentMetric, PlatformAccount, User

DEFAULT_USER_EMAIL = "me@creator-pulse.local"


def get_or_create_default_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == DEFAULT_USER_EMAIL))
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_or_create_platform_account(
    db: Session, user: User, platform: str, external_account_id: str, display_name: str = ""
) -> PlatformAccount:
    account = db.scalar(
        select(PlatformAccount).where(
            PlatformAccount.user_id == user.id,
            PlatformAccount.platform == platform,
            PlatformAccount.external_account_id == external_account_id,
        )
    )
    if account is None:
        account = PlatformAccount(
            user_id=user.id,
            platform=platform,
            external_account_id=external_account_id,
            display_name=display_name,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def upsert_metrics(db: Session, account: PlatformAccount, items: list[dict]) -> int:
    """Her senkronizasyonda yeni bir satır ekler (aynı content_id için de),
    böylece zaman içindeki değişimi (trend) kaybetmeyiz. Sadece son değeri
    tutmak isteseydik burada update yapardık."""
    count = 0
    for item in items:
        metric = ContentMetric(
            account_id=account.id,
            content_id=item["content_id"],
            title=item.get("title", ""),
            url=item.get("url", ""),
            likes=item.get("likes", 0),
            comments=item.get("comments", 0),
            views=item.get("views", 0),
            published_at=item.get("published_at"),
        )
        db.add(metric)
        count += 1
    db.commit()
    return count
