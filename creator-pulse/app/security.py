"""
OAuth token'larını veritabanında düz metin olarak tutmamak için basit
simetrik şifreleme. ENCRYPTION_KEY .env'de yoksa geliştirme için otomatik
bir anahtar üretir (üretimde mutlaka sabit bir anahtar .env'e yazılmalı,
yoksa uygulama her yeniden başlatıldığında eski token'lar okunamaz hale gelir).
"""
from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()

if settings.encryption_key:
    _fernet = Fernet(settings.encryption_key.encode())
else:
    # Sadece geliştirme kolaylığı içindir — .env'e ENCRYPTION_KEY eklemeyi unutma.
    _fernet = Fernet(Fernet.generate_key())


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet.decrypt(value.encode()).decode()
