"""
OAuth token'larını veritabanında düz metin olarak tutmamak için basit
simetrik şifreleme. ENCRYPTION_KEY .env'de tanımlı olmalı: her açılışta
rastgele anahtar üretmek, uygulama yeniden başladığında kayıtlı token'ları
okunamaz hale getirirdi. Anahtar yoksa veya geçersizse şifreleme/çözme
çağrıları açık bir hata verir (sunucu yine açılır, YouTube gibi token
gerektirmeyen kısımlar çalışmaya devam eder).

Anahtar üretmek için:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet

from app.config import get_settings

KEY_HELP = (
    'Üretmek için: python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())" ve çıktıyı .env dosyasına '
    "ENCRYPTION_KEY=... olarak ekle. Bu anahtarı sonradan değiştirme; "
    "değişirse kayıtlı token'lar çözülemez."
)


class EncryptionKeyError(RuntimeError):
    pass


def _get_fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise EncryptionKeyError(f"ENCRYPTION_KEY tanımlı değil. {KEY_HELP}")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise EncryptionKeyError(f"ENCRYPTION_KEY geçersiz. {KEY_HELP}") from exc


def require_encryption_key() -> None:
    """Token kaydedecek akışları (örn. Instagram OAuth) başlamadan önce
    anahtarın hazır olduğunu doğrular."""
    _get_fernet()


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    return _get_fernet().decrypt(value.encode()).decode()
