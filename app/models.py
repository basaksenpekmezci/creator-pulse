"""
Veri modeli — workflow.html'deki ER diyagramının kod karşılığı.

User: uygulamayı kullanan kişi (MVP'de sadece sen olacaksın ama şema
      baştan çok-kullanıcılı düşünülmüş durumda).
PlatformAccount: bir kullanıcının bağladığı her platform hesabı
      (instagram / youtube / tiktok / x). Token'lar şifreli saklanır.
ContentMetric: her içerik (video/post) için çekilen anlık istatistik.
      Aynı içerik için zamanla birden çok satır birikir, böylece trend
      grafiği çizilebilir.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list["PlatformAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "external_account_id", name="uq_user_platform_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    platform: Mapped[str] = mapped_column(String(32))  # "youtube" | "instagram" | "tiktok" | "x"
    external_account_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="")

    # Token'lar app/security.py içindeki fonksiyonlarla şifrelenip saklanır.
    access_token_encrypted: Mapped[str] = mapped_column(String(2048), default="")
    refresh_token_encrypted: Mapped[str] = mapped_column(String(2048), default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="accounts")
    metrics: Mapped[list["ContentMetric"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class ContentMetric(Base):
    __tablename__ = "content_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"))

    content_id: Mapped[str] = mapped_column(String(255), index=True)  # platformdaki video/post id'si
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")

    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    account: Mapped["PlatformAccount"] = relationship(back_populates="metrics")
