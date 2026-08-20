"""
YouTube connector — YouTube Data API v3.

Bilinçli tasarım kararı: OAuth GEREKTİRMİYOR. Bir kanalın herkese açık
video istatistiklerini (beğeni, yorum, izlenme sayısı) sadece bir API
key ile çekebiliyoruz. Bu yüzden Faz 1'de ilk çalışan entegrasyon burası.

Kota notu: her "list" çağrısı 1 unit, günlük varsayılan kota 10.000 unit.
Bu modüldeki fonksiyonlar mümkün olduğunca az çağrı yapacak şekilde
(playlistItems + videos.list tek seferde 50 video) yazıldı.
"""
from __future__ import annotations

import httpx

from app.config import get_settings

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeConnectorError(Exception):
    pass


def _api_key() -> str:
    settings = get_settings()
    if not settings.youtube_api_key:
        raise YouTubeConnectorError(
            "YOUTUBE_API_KEY tanımlı değil. .env dosyana Google Cloud Console'dan "
            "aldığın API anahtarını ekle (bkz. .env.example)."
        )
    return settings.youtube_api_key


def _get(url: str, params: dict) -> dict:
    """Tüm YouTube API GET çağrılarının ortak noktası. httpx/HTTP hatalarını
    ham haliyle sızdırmak yerine anlamlı bir YouTubeConnectorError'a çevirir
    (aksi halde FastAPI tarafında yakalanamayıp genel 500 hatası dönerdi)."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise YouTubeConnectorError(
            f"YouTube API hata döndürdü (HTTP {exc.response.status_code}): {detail}"
        ) from exc
    except httpx.RequestError as exc:
        raise YouTubeConnectorError(f"YouTube API'ye ulaşılamadı: {exc}") from exc
    return resp.json()


def resolve_channel_id(handle_or_id: str) -> str:
    """'@kullaniciadi' gibi bir handle ya da doğrudan channel id verildiğinde
    gerçek channel id'yi döndürür."""
    if handle_or_id.startswith("UC"):
        return handle_or_id

    handle = handle_or_id if handle_or_id.startswith("@") else f"@{handle_or_id}"
    params = {"key": _api_key(), "part": "id", "forHandle": handle}

    data = _get(f"{YOUTUBE_API_BASE}/channels", params)
    items = data.get("items", [])
    if not items:
        raise YouTubeConnectorError(
            f"Kanal bulunamadı: {handle_or_id}. Kanalının gerçek @handle'ını "
            "YouTube Studio → Özelleştirme → Temel bilgiler'den kontrol et "
            "(Türkçe karakter içermeyen, YouTube'un sana verdiği tam handle'ı kullan)."
        )
    return items[0]["id"]


def _get_uploads_playlist_id(channel_id: str) -> str:
    params = {"key": _api_key(), "part": "contentDetails", "id": channel_id}
    data = _get(f"{YOUTUBE_API_BASE}/channels", params)
    items = data.get("items", [])
    if not items:
        raise YouTubeConnectorError(f"Kanal bulunamadı: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_recent_video_ids(channel_id: str, max_results: int = 25) -> list[str]:
    playlist_id = _get_uploads_playlist_id(channel_id)
    params = {
        "key": _api_key(),
        "part": "contentDetails",
        "playlistId": playlist_id,
        "maxResults": min(max_results, 50),
    }
    data = _get(f"{YOUTUBE_API_BASE}/playlistItems", params)
    items = data.get("items", [])
    return [item["contentDetails"]["videoId"] for item in items]


def fetch_video_stats(video_ids: list[str]) -> list[dict]:
    """Verilen video id'leri için başlık + istatistikleri tek çağrıda döndürür
    (videos.list en fazla 50 id kabul eder, 1 unit harcar)."""
    if not video_ids:
        return []

    params = {
        "key": _api_key(),
        "part": "snippet,statistics",
        "id": ",".join(video_ids[:50]),
    }
    data = _get(f"{YOUTUBE_API_BASE}/videos", params)

    results = []
    for item in data.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        results.append(
            {
                "content_id": item["id"],
                "title": snippet.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "views": int(stats.get("viewCount", 0)),
                "published_at": snippet.get("publishedAt"),
            }
        )
    return results


def sync_channel(handle_or_id: str, max_results: int = 25) -> list[dict]:
    """Bir kanal için son videoların normalize edilmiş istatistiklerini döndürür.
    Bu fonksiyonun çıktısı doğrudan ContentMetric satırlarına dönüştürülebilir."""
    channel_id = resolve_channel_id(handle_or_id)
    video_ids = fetch_recent_video_ids(channel_id, max_results=max_results)
    return fetch_video_stats(video_ids)


def sync_channel_with_id(handle_or_id: str, max_results: int = 25) -> tuple[str, list[dict]]:
    """sync_channel ile aynı işi yapar ama channel_id'yi de birlikte döndürür.
    Router'ın ayrıca ikinci bir resolve_channel_id çağrısı yapmasına gerek
    kalmaz (önceden bu ikinci çağrı try/except dışındaydı ve olası bir
    YouTube API hatasında genel/anlamsız bir 500 hatasına yol açıyordu)."""
    channel_id = resolve_channel_id(handle_or_id)
    video_ids = fetch_recent_video_ids(channel_id, max_results=max_results)
    items = fetch_video_stats(video_ids)
    return channel_id, items
