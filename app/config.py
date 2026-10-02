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

    # Oturum çerezi. Çerez APP_SECRET_KEY ile imzalanır, JavaScript'ten
    # okunamaz (HttpOnly) ve başka sitelerden gelen isteklere eklenmez
    # (SameSite=Lax). HTTPS üzerinde yayındayken (ör. Render)
    # SESSION_COOKIE_SECURE=true yap ki çerez sadece şifreli bağlantıda gitsin.
    session_cookie_secure: bool = False
    session_max_age_days: int = 14

    # Kullanıcı sistemi gelmeden önce tüm veriler tek bir ortak kullanıcıda
    # (me@creator-pulse.local) duruyordu. Bu veriler kayıt sırasında bir
    # kullanıcıya taşınır: burası boşsa ilk kayıt olan kullanıcıya, doluysa
    # sadece bu e-postayla kayıt olan kullanıcıya.
    legacy_data_owner_email: str = ""

    # YouTube
    youtube_api_key: str = ""

    # Instagram
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = "http://localhost:8000/connect/instagram/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
