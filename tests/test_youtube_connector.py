"""
API anahtarı olmadan da connector'ın YouTube API yanıtını doğru şekilde
normalize ettiğini doğrulayan test. Gerçek ağ çağrısı yapmaz — httpx.Client.get
mock'lanır.
"""
from unittest.mock import MagicMock, patch

from app.connectors import youtube

SAMPLE_VIDEOS_RESPONSE = {
    "items": [
        {
            "id": "abc123",
            "snippet": {"title": "Test Video", "publishedAt": "2026-08-01T10:00:00Z"},
            "statistics": {"likeCount": "1500", "commentCount": "42", "viewCount": "98000"},
        }
    ]
}


def test_fetch_video_stats_parses_response(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake-key-for-test")
    youtube.get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_VIDEOS_RESPONSE
    mock_response.raise_for_status.return_value = None

    with patch("httpx.Client.get", return_value=mock_response):
        results = youtube.fetch_video_stats(["abc123"])

    assert len(results) == 1
    item = results[0]
    assert item["content_id"] == "abc123"
    assert item["title"] == "Test Video"
    assert item["likes"] == 1500
    assert item["comments"] == 42
    assert item["views"] == 98000
    assert item["url"] == "https://www.youtube.com/watch?v=abc123"


def test_fetch_video_stats_empty_list_returns_empty():
    assert youtube.fetch_video_stats([]) == []
