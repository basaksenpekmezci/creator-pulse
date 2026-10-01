"""ENCRYPTION_KEY yoksa veya geçersizse açık hata verildiğini doğrular."""
import pytest
from cryptography.fernet import Fernet

from app import security


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    security.get_settings.cache_clear()
    yield
    security.get_settings.cache_clear()


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "")
    with pytest.raises(security.EncryptionKeyError, match="ENCRYPTION_KEY tanımlı değil"):
        security.encrypt("token")


def test_invalid_key_raises_clear_error(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "gecersiz")
    with pytest.raises(security.EncryptionKeyError, match="ENCRYPTION_KEY geçersiz"):
        security.encrypt("token")


def test_roundtrip_with_fixed_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encrypted = security.encrypt("gizli-token")
    assert encrypted != "gizli-token"
    # Anahtar sabit olduğu için ayarlar yeniden okunsa bile çözülebilmeli.
    security.get_settings.cache_clear()
    assert security.decrypt(encrypted) == "gizli-token"
