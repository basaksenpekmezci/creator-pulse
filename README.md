# Creator Pulse

İçerik üreticiler için platformlar arası (YouTube, Instagram, ileride TikTok/X)
beğeni/yorum/izlenme istatistiklerini tek bir yerde toplayan uygulama —
Faz 1 (MVP) iskeleti.

Ürün stratejisi ve fazlı yol haritası için: `icerik-analitik-app-yol-haritasi.md`.
Teknik akış diyagramları için: `workflow.html` (tarayıcıda aç).

## Kurulum

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Ardından `.env` içindeki `ENCRYPTION_KEY` alanına kalıcı bir anahtar yaz
(Instagram token'larını şifrelemek için gerekli, bir kez üret ve değiştirme):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env` dosyasını doldurmadan da sunucu çalışır (YouTube/Instagram
çağrıları anlamlı bir hata mesajıyla reddedilir), ama gerçek veri çekmek
için aşağıdaki adımları tamamlaman gerekiyor.

## Çalıştırma

```bash
uvicorn app.main:app --reload
```

- Dashboard: http://localhost:8000/ (giriş yapmadıysan /login'e yönlendirir)
- API dokümantasyonu (otomatik): http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Kullanıcı Hesapları

İlk açılışta http://localhost:8000/register adresinden e-posta ve şifreyle
kayıt ol. Şifreler bcrypt ile hash'lenerek saklanır; oturum imzalı,
HttpOnly ve SameSite=Lax bir çerezde 14 gün tutulur. Her kullanıcı sadece
kendi bağladığı hesapları ve onların verisini görür.

- **Eski veriler:** Kullanıcı sisteminden önce tüm veriler tek bir ortak
  kullanıcıda (`me@creator-pulse.local`) duruyordu. Bu veriler, varsayılan
  olarak **ilk kayıt olan kullanıcıya** taşınır. Belirli bir e-postaya
  gitmesini istersen `.env`'e `LEGACY_DATA_OWNER_EMAIL=senin@epostan.com`
  yaz; o zaman sadece o e-postayla kayıt olan kullanıcı alır.
- **Veritabanı:** Sunucu açılırken var olan `creator_pulse.db`'ye eksik
  kolonları (`users.password_hash`, `platform_accounts.sync_status`,
  `last_synced_at`, `last_sync_error`) kendisi ekler; elle bir şey yapman
  ya da veritabanını silmen gerekmez.
- **Yayında (HTTPS):** `.env`'de `APP_SECRET_KEY`'i rastgele, uzun bir
  değerle değiştir ve `SESSION_COOKIE_SECURE=true` yap.

## Hesap Bağlama ve Otomatik Güncelleme

Dashboard'daki **YouTube bağla** butonuna kanal adını (`@kanalin`) yazıp
"Bağla" de; **Instagram bağla** seni Instagram'ın izin ekranına götürür.
Her iki durumda da ilk senkronizasyon arka planda başlar, dashboard
ilerlemeyi gösterir ve bitince veriler kendiliğinden görünür.

Bağlı her hesap sonra **günde bir** otomatik güncellenir: zamanlayıcı
saatte bir bakar ve son güncellemesi 24 saatten eski hesapları çeker.
Sunucu açıldığında da hemen bir kontrol yapılır; böylece sunucu yeniden
başlasa bile hiçbir hesap bir günden eski kalmaz.

## Testler

```bash
pytest
```

## YouTube Kurulumu (OAuth gerektirmez, hemen çalışır)

1. https://console.cloud.google.com adresinde bir proje oluştur (veya var olanı kullan).
2. "APIs & Services → Library" içinden **YouTube Data API v3**'ü etkinleştir.
3. "APIs & Services → Credentials → Create Credentials → API key" ile bir anahtar üret.
4. Anahtarı `.env` dosyasında `YOUTUBE_API_KEY` alanına yapıştır.
5. Sunucuyu başlat, giriş yap ve dashboard'daki **YouTube bağla** ile
   kanal adını gir.

Not: Günlük kota varsayılan olarak 10.000 unit — bu uygulamanın kullandığı
her senkronizasyon ~3 unit civarında harcıyor (playlistItems + videos.list),
bu yüzden kişisel kullanım için fazlasıyla yeterli.

## Instagram Kurulumu (OAuth gerekli, onay süreci var)

Meta'nın Facebook Sayfası **gerektirmeyen** yeni yöntemini kullanıyoruz:
"Instagram API with Instagram Login". Tek şart hesabının Business/Creator
(Professional) türünde olması — senin hesabın zaten Creator olduğu için bu
adım tamam.

1. https://developers.facebook.com/apps/ adresinde bir uygulama oluştur.
2. Uygulamaya **Instagram** ürününü ekle (eski "Instagram Graph API" değil,
   "Instagram API with Instagram Login" / "Business Login for Instagram"
   seçeneği).
3. Uygulama ayarlarından Instagram App ID ve App Secret'i `.env` dosyasına
   (`INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`) ekle. Not: bu App ID, eski
   Facebook uygulama ID'sinden farklı olabilir — Instagram ürününün kendi
   ayarlarındaki değeri kullan.
4. Valid OAuth Redirect URI olarak `http://localhost:8000/connect/instagram/callback`
   gir.
5. Geliştirme modundayken sadece uygulamaya "Instagram Tester" olarak
   eklediğin hesapla test edebilirsin (kendi hesabını ekleyip davetini
   Instagram uygulaması → Ayarlar → Uygulamalar ve Websiteler'den kabul et).
6. Canlıya/başkalarına açmak için Meta'nın **App Review** sürecinden
   `instagram_business_basic` ve `instagram_business_manage_insights`
   izinlerini onaylatman gerekiyor (genelde 2-4 hafta) — ama kendi hesabınla
   test etmek için bunu beklemene gerek yok, Tester olarak eklemen yeterli.
7. Kurulum bitince giriş yap ve dashboard'daki **Instagram bağla**
   butonuna bas — Instagram'ın izin ekranına yönlendirileceksin. İzin
   verdikten sonra token şifrelenip senin hesabına kaydedilir, dashboard'a
   dönersin ve ilk senkronizasyon arka planda yapılır. Sonrasında
   zamanlayıcı günde bir otomatik çeker, token'ı da süresi dolmadan yeniler.

Not: Meta bu API'yi zaman zaman günceller, kurulum sırasında ekran
metinleri/menü isimleri bu talimattan biraz farklı görünebilir — genel akış
(Instagram ürünü ekle → Tester olarak kendini ekle → redirect URI gir) aynı
kalıyor.

## Klasör Yapısı

```
app/
├── main.py            # FastAPI giriş noktası, oturum çerezi, scheduler başlatma
├── auth.py             # Şifre hash'leme (bcrypt) + giriş yapan kullanıcı
├── config.py           # .env ayarları
├── database.py         # SQLAlchemy engine/session
├── models.py           # User, PlatformAccount, ContentMetric
├── crud.py             # DB yardımcı fonksiyonları
├── security.py         # Token şifreleme
├── scheduler.py         # Günlük senkronizasyon (APScheduler)
├── connectors/
│   ├── youtube.py       # Çalışıyor — sadece API key gerekiyor
│   └── instagram.py     # OAuth + token yenileme hazır
└── routers/
    ├── auth.py          # Kayıt / giriş / çıkış sayfaları
    ├── sync.py          # Manuel senkronizasyon endpoint'leri
    ├── connect.py        # YouTube bağla + Instagram OAuth authorize/callback
    └── dashboard.py       # Toplu istatistik API'si
templates/dashboard.html  # Basit web arayüzü
templates/auth.html       # Kayıt ve giriş ekranları
tests/                    # pytest testleri
```

## Sırada Ne Var (Faz 1 devamı / Faz 2)

- Instagram App Review başvurusunu şimdiden başlat (başkalarına açmak
  istediğinde gerekecek; kendi hesabınla test etmek için Tester eklemek yeterli).
- Postgres'e geçiş: sadece `.env`'deki `DATABASE_URL`'i değiştirmek yeterli
  olacak şekilde tasarlandı.

## Neden Bu Yapı

`icerik-analitik-app-yol-haritasi.md` dokümanındaki platform API analizine
göre YouTube ve Instagram, ücretsiz oldukları ve her creator'ın kendi
hesabını bağladığı (yani doğal olarak çok-kullanıcılı bir modele oturan)
API'ler sundukları için Faz 1'de öncelikli seçildi. TikTok ve X, onay
süreci belirsizliği / maliyet nedeniyle Faz 2-4'e bırakıldı.
