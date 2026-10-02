"""
Basit veritabanı yardımcı fonksiyonları: kullanıcı oluşturma, eski ortak
kullanıcının verisini taşıma, platform hesabı ve metrik kaydı.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ContentMetric, PlatformAccount, User

# Kullanıcı sisteminden önce tüm veriler bu tek ortak kullanıcıya yazılıyordu.
# Artık kimse bu kullanıcıyla giriş yapamaz; sadece verisini gerçek bir
# kullanıcıya taşımak (claim_legacy_data) için tanınıyor.
LEGACY_USER_EMAIL = "me@creator-pulse.local"


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(db: Session, email: str, password_hash: str) -> User:
    user = User(email=email, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def claim_legacy_data(db: Session, user: User) -> int:
    """Eski ortak kullanıcının bağlı hesaplarını (ve onlara bağlı tüm
    metrikleri) verilen kullanıcıya taşır, sonra ortak kullanıcıyı siler.

    Kime taşınacağı LEGACY_DATA_OWNER_EMAIL ayarına bağlı: boşsa ilk kayıt
    olan kullanıcı (kendisinden başka şifreli kullanıcı yoksa), doluysa sadece
    o e-postayla kayıt olan kullanıcı alır. Taşınan hesap sayısını döndürür."""
    legacy = get_user_by_email(db, LEGACY_USER_EMAIL)
    if legacy is None or legacy.id == user.id:
        return 0

    owner_email = get_settings().legacy_data_owner_email.strip().lower()
    if owner_email:
        if user.email != owner_email:
            return 0
    else:
        other_real_user = db.scalar(
            select(User.id).where(User.password_hash.is_not(None), User.id != user.id)
        )
        if other_real_user is not None:
            return 0

    accounts = list(legacy.accounts)
    for account in accounts:
        account.user_id = user.id
    db.flush()
    db.expire(legacy, ["accounts"])
    db.delete(legacy)
    db.commit()
    db.refresh(user)
    return len(accounts)


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
