"""
Kayıt olma, giriş ve çıkış testleri: şifrelerin bcrypt ile saklanması,
oturum çerezinin güvenlik bayrakları ve giriş gerektiren sayfalar.
"""
import bcrypt
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import get_settings
from app.main import build_app
from app.database import get_db
from app.models import User
from tests.conftest import TEST_PASSWORD, login, make_user

COOKIE = "creator_pulse_session"


def register(test_client, email="yeni@example.com", password=TEST_PASSWORD, confirm=None):
    return test_client.post(
        "/register",
        data={"email": email, "password": password, "password_confirm": password if confirm is None else confirm},
        follow_redirects=False,
    )


# --- şifre hash'leme -------------------------------------------------------


def test_hash_password_uses_bcrypt_and_verifies():
    hashed = auth.hash_password("cok-gizli-sifre")
    assert hashed != "cok-gizli-sifre"
    assert hashed.startswith("$2b$")
    assert auth.verify_password("cok-gizli-sifre", hashed)
    assert not auth.verify_password("yanlis-sifre", hashed)
    # Her hash'in tuzu farklı.
    assert auth.hash_password("cok-gizli-sifre") != hashed


def test_verify_password_without_hash_is_false():
    assert not auth.verify_password("herhangi", None)
    assert not auth.verify_password("x" * 100, auth.hash_password("kisa-sifre"))


@pytest.mark.parametrize(
    "email, password, message",
    [
        ("gecersiz", "uzun-bir-sifre", "e-posta"),
        ("a@b.co", "kisa", "en az 8"),
        ("a@b.co", "ş" * 40, "çok uzun"),
    ],
)
def test_validate_credentials_rejects(email, password, message):
    with pytest.raises(auth.AuthError, match=message):
        auth.validate_credentials(email, password)


def test_validate_credentials_normalizes_email():
    assert auth.validate_credentials("  Basak@Example.COM ", "uzun-bir-sifre") == "basak@example.com"


# --- kayıt -----------------------------------------------------------------


def test_register_page_renders(anon_client):
    resp = anon_client.get("/register")
    assert resp.status_code == 200
    assert 'action="/register"' in resp.text
    assert 'name="password_confirm"' in resp.text


def test_register_creates_user_with_bcrypt_hash_and_logs_in(anon_client, db):
    resp = register(anon_client, email="Yeni@Example.com")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    user = db.query(User).one()
    assert user.email == "yeni@example.com"
    assert user.password_hash != TEST_PASSWORD
    assert bcrypt.checkpw(TEST_PASSWORD.encode(), user.password_hash.encode())
    # Kayıttan sonra doğrudan oturum açık.
    assert anon_client.get("/api/me").json()["email"] == "yeni@example.com"


def test_register_rejects_duplicate_email(anon_client, db):
    make_user(db, "var@example.com")
    resp = register(anon_client, email="VAR@example.com")
    assert resp.status_code == 400
    assert "zaten bir hesap var" in resp.text
    assert db.query(User).count() == 1


def test_register_rejects_mismatched_passwords(anon_client, db):
    resp = register(anon_client, confirm="baska-bir-sifre")
    assert resp.status_code == 400
    assert "eşleşmiyor" in resp.text
    assert db.query(User).count() == 0


def test_register_rejects_short_password_and_keeps_email(anon_client, db):
    resp = register(anon_client, email="yeni@example.com", password="kisa")
    assert resp.status_code == 400
    assert "en az 8" in resp.text
    assert 'value="yeni@example.com"' in resp.text
    assert db.query(User).count() == 0


def test_register_escapes_user_input(anon_client):
    resp = register(anon_client, email='"><script>alert(1)</script>', password="kisa")
    assert "<script>alert(1)</script>" not in resp.text


def test_legacy_shared_user_email_cannot_be_registered(anon_client):
    resp = register(anon_client, email="me@creator-pulse.local")
    assert resp.status_code == 400


# --- giriş / çıkış ---------------------------------------------------------


def test_login_with_correct_password(anon_client, user):
    resp = anon_client.post(
        "/login", data={"email": "  BASAK@example.com", "password": TEST_PASSWORD}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert anon_client.get("/api/me").json()["email"] == user.email


@pytest.mark.parametrize(
    "email, password",
    [("basak@example.com", "yanlis-sifre"), ("kimse@example.com", TEST_PASSWORD), ("basak@example.com", "")],
)
def test_login_rejects_wrong_credentials_with_same_message(anon_client, user, email, password):
    resp = anon_client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert resp.status_code == 400
    # Hangi bilginin yanlış olduğu söylenmez (kayıtlı e-postalar tahmin edilemesin).
    assert "E-posta ya da şifre hatalı." in resp.text
    assert anon_client.get("/api/me").status_code == 401


def test_login_cookie_is_httponly_and_samesite(anon_client, user):
    resp = anon_client.post("/login", data={"email": user.email, "password": TEST_PASSWORD}, follow_redirects=False)
    cookie = resp.headers["set-cookie"].lower()
    assert cookie.startswith(f"{COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=1209600" in cookie  # 14 gün
    # Çerezde e-posta ya da şifre yok, sadece imzalı oturum.
    assert "basak" not in cookie
    assert TEST_PASSWORD not in cookie


def test_cookie_is_secure_when_configured(monkeypatch, session_factory, db):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    app = build_app()

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    make_user(db)
    resp = TestClient(app, base_url="https://testserver").post(
        "/login", data={"email": "basak@example.com", "password": TEST_PASSWORD}, follow_redirects=False
    )
    assert "secure" in resp.headers["set-cookie"].lower()


def test_tampered_cookie_is_rejected(anon_client, user):
    login(anon_client, user.email)
    value = anon_client.cookies[COOKIE]
    anon_client.cookies.set(COOKIE, value[:-4] + "AAAA")
    assert anon_client.get("/api/me").status_code == 401


def test_logout_clears_session(client):
    assert client.get("/api/me").status_code == 200
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    assert client.get("/api/me").status_code == 401


def test_session_of_deleted_user_is_dropped(client, db, user):
    db.delete(user)
    db.commit()
    assert client.get("/api/me").status_code == 401


# --- giriş gerektiren sayfalar ---------------------------------------------


def test_dashboard_redirects_to_login_when_anonymous(anon_client):
    resp = anon_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_dashboard_served_when_logged_in(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Creator Pulse" in resp.text


def test_login_and_register_pages_redirect_when_logged_in(client):
    for path in ("/login", "/register"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/metrics"),
        ("get", "/api/me"),
        ("post", "/sync/youtube?handle=x"),
        ("post", "/sync/instagram"),
        ("get", "/connect/instagram"),
    ],
)
def test_api_requires_login(anon_client, method, path):
    assert getattr(anon_client, method)(path).status_code == 401


def test_health_is_public(anon_client):
    assert anon_client.get("/health").json() == {"status": "ok"}
