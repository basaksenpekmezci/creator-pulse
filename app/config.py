"""
Uygulama ayarları. Tüm gizli/ortama bağlı değerler .env dosyasından okunur.
Gerçek .env dosyasını asla git'e ekleme — .gitignore zaten dışlıyor.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_secret_key: str = "gelistirme-ortami-anahtari"
    database_url: str = "sqlite:///./creator_pulse.db"
    encryption_key: str = ""

    # YouTube
    youtube_api_key: str = ""

    # Instagram
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = "http://localhost:8000/connect/instagram/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
