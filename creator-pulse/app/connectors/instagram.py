"""
Instagram connector — "Instagram API with Instagram Login".

ÖNEMLİ GÜNCELLEME: Meta artık Facebook Sayfası gerektirmeyen bir giriş
yöntemi sunuyor ("Instagram API with Instagram Login" / Business Login for
Instagram). Bu yüzden bu connector ARTIK Facebook OAuth'u değil, doğrudan
Instagram'ın kendi OAuth'unu kullanıyor. Tek şart: hesabın Business veya
Creator (yani "Professional") hesap türünde olması — Facebook Sayfasına
bağlı olması gerekmiyor.

OAuth akışı:
  1. Kullanıcıyı api.instagram.com/oauth/authorize'a yönlendir.
  2. Callback'te gelen 'code'u api.instagram.com/oauth/access_token'a
     POST ederek kısa ömürlü (1 saat) token al.
  3. Kısa ömürlü token'ı graph.instagram.com/access_token üzerinden
     uzun ömürlü (60 gün) token'a çevir.
  4. Sonraki tüm çağrılar graph.instagram.com üzerinden yapılır.

Not: Meta bu uçları zaman zaman günceller — kurulum sırasında
developers.facebook.com/docs/instagram-platform üzerinden teyit etmekte
fayda var. Gerçek veri çekimini test etmek için önce Meta Developer hesabı
+ uygulama incelemesi tamamlanmalı (bkz. README.md "Instagram Kurulumu").
O onaya kadar build_authorize_url / exchange_code_for_token fonksiyonları
kodda hazır duruyor, sadece INSTAGRAM_APP_ID/SECRET boş olduğu için
çalıştırılamıyor.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

import httpx

from app.config import get_settings

GRAPH_API_BASE = "https://graph.instagram.com/v21.0"
OAUTH_AUTHORIZE_URL = "https://api.instagram.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"
REFRESH_TOKEN_URL = "https://graph.instagram.com/refresh_access_token"

# "Instagram API with Instagram Login" için gerekli izinler.
# instagram_business_basic: profil + medya listesi
# instagram_business_manage_insights: beğeni/yorum/izlenme gibi metrikler
SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_insights",
]


class InstagramConnectorError(Exception):
    pass


def _require_credentials() -> tuple[str, str]:
    settings = get_settings()
    if not settings.instagram_app_id or not settings.instagram_app_secret:
        raise InstagramConnectorError(
            "INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET tanımlı değil. Meta for "
            "Developers'ta uygulama oluşturup .env'e ekle (bkz. README.md)."
        )
    return settings.instagram_app_id, settings.instagram_app_secret


def build_authorize_url(state: str) -> str:
    """Kullanıcıyı Instagram'ın izin ekranına yönlendirecek URL'i üretir.
    `state` CSRF koruması için rastgele üretilip session'da saklanmalı,
    callback'te doğrulanmalı."""
    app_id, _ = _require_credentials()
    settings = get_settings()

    params = {
        "client_id": app_id,
        "redirect_uri": settings.instagram_redirect_uri,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    """OAuth callback'ten gelen 'code'u kısa ömürlü (1 saat) access token'a
    çevirir. Bu token sadece test için yeterli; gerçek kullanımda
    exchange_for_long_lived_token ile 60 günlük token'a çevrilmeli."""
    app_id, app_secret = _require_credentials()
    settings = get_settings()

    data = {
        "client_id": app_id,
        "client_secret": app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": settings.instagram_redirect_uri,
        "code": code,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.post(OAUTH_TOKEN_URL, data=data)
    resp.raise_for_status()
    return resp.json()  # {"access_token": "...", "user_id": ..., "permissions": [...]}


def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    """Kısa ömürlü token'ı 60 gün geçerli uzun ömürlü token'a çevirir.
    Bu token'ın süresi dolmadan (örn. her 50 günde bir) yenilenmesi gerekir
    — bkz. refresh_long_lived_token, scheduler.py bunu otomatik çağırıyor."""
    _, app_secret = _require_credentials()
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": app_secret,
        "access_token": short_lived_token,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.get(LONG_LIVED_TOKEN_URL, params=params)
    resp.raise_for_status()
    return resp.json()  # {"access_token": "...", "token_type": "bearer", "expires_in": 5184000}


def refresh_long_lived_token(access_token: str) -> dict:
    """60 günlük uzun ömürlü token'ı süresi dolmadan yeniler ve süresini
    tekrar 60 güne uzatır. Instagram kuralı: token en az 24 saatlik olmalı
    ve süresi henüz dolmamış olmalı — süresi dolmuş bir token yenilenemez,
    o zaman kullanıcının /connect/instagram ile yeniden bağlanması gerekir.
    Not: Bu fonksiyon app_secret istemiyor (kısa ömürlü token değişiminden
    farklı olarak), sadece mevcut access_token'ın kendisi yeterli."""
    params = {
        "grant_type": "ig_refresh_token",
        "access_token": access_token,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.get(REFRESH_TOKEN_URL, params=params)
    resp.raise_for_status()
    return resp.json()  # {"access_token": "...", "token_type": "bearer", "expires_in": 5184000}


def fetch_connected_ig_accounts(access_token: str) -> list[dict]:
    """Instagram Login ile bağlanan hesabın kendi profil bilgisini döndürür.
    Facebook Sayfası gerekmediği için burada tek bir hesap dönüyor
    (eski Facebook Login akışındaki 'birden çok sayfa listeleme' senaryosu
    burada geçerli değil)."""
    params = {
        "access_token": access_token,
        "fields": "user_id,username,account_type",
    }
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{GRAPH_API_BASE}/me", params=params)
    resp.raise_for_status()
    profile = resp.json()
    return [{"page_name": profile.get("username"), "ig_account_id": profile.get("user_id")}]


def _parse_datetime(value: str | None) -> datetime | None:
    """Instagram 'timestamp' alanı '2024-05-01T12:00:00+0000' formatında gelir.
    Veritabanı modeli gerçek bir Python datetime nesnesi bekliyor — YouTube
    connector'ında yaşadığımız aynı hataya (SQLite DateTime hatası, 500 dönmesi)
    burada düşmemek için aynı koruma."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def sync_account(ig_account_id: str, access_token: str, limit: int = 25) -> list[dict]:
    """Bir Instagram Business hesabının son gönderilerinin normalize edilmiş
    istatistiklerini döndürür. Çıktı formatı youtube.sync_channel ile aynı,
    böylece dashboard/scheduler tarafında platform farkı gözetmeden işlenebilir."""
    params = {
        "access_token": access_token,
        "fields": "id,caption,permalink,like_count,comments_count,timestamp",
        "limit": limit,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{GRAPH_API_BASE}/{ig_account_id}/media", params=params)
    resp.raise_for_status()

    results = []
    for item in resp.json().get("data", []):
        results.append(
            {
                "content_id": item["id"],
                "title": (item.get("caption") or "")[:200],
                "url": item.get("permalink", ""),
                "likes": int(item.get("like_count", 0)),
                "comments": int(item.get("comments_count", 0)),
                "views": 0,  # Not: view count sadece video/reels için ayrı bir alanda gelir (TODO)
                "published_at": _parse_datetime(item.get("timestamp")),
            }
        )
    return results
