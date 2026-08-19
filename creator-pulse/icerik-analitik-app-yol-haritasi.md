# İçerik Üreticileri İçin Analitik Uygulaması — Ürün Yol Haritası

*Hazırlanma tarihi: 19 Ağustos 2026*

## 1. Vizyon

Fikrin özünde iki katman var. Birinci katman, farklı platformlardan (Instagram, TikTok, YouTube, X gibi) gelen beğeni, yorum, izlenme gibi metrikleri tek bir yerde, platforma göre toplu halde görebilmek. İkinci katman ise ileride eklenecek yapay zekâ destekli anlama katmanı: videonun ne anlattığını çözümlemek, metnini çıkarmak, içerik önerileri sunmak. Nihai hedef, önce kendin kullanacağın ama zamanla diğer içerik üreticilere aylık abonelikle açabileceğin, gerçekten güçlü bir ürün.

Bu doküman şu soruya cevap veriyor: buna nereden başlamalı, ürün stratejisiyle mi yoksa doğrudan bir MVP ile mi? Kısa cevap: MVP ile başla, ama MVP'yi "sonra SaaS'a çevrilebilecek" şekilde tasarla — mimariyi baştan çok kullanıcılı düşün, sadece ilk sürümde kullanıcı sayısını sen olarak sınırla. Bu, hem hızlı çıkış yapmanı hem de sonradan her şeyi yeniden yazmak zorunda kalmamanı sağlar.

## 2. Neden MVP ile başlamalı

Bu tür bir ürünün en büyük riski özellik eksikliği değil, platform API'lerinin gerçekte ne kadar veri verdiği ve ne kadar zorluk çıkardığı. Yani önce "ürünü tasarlayıp" sonra API'lerin buna izin vermediğini görmek yerine, önce küçük ve çalışan bir sürümle bu riskleri gerçek dünyada test etmek gerekiyor. Aşağıdaki platform analizi bunun neden önemli olduğunu gösteriyor.

## 3. Platform API Analizi (Araştırma Sonucu)

| Platform | Resmi API | Maliyet | Erişim Modeli | Zorluk |
|---|---|---|---|---|
| **Instagram** | Graph API | Ücretsiz | Her creator kendi hesabını OAuth ile bağlamalı; hesap Business/Creator türünde olmalı ve bir Facebook Sayfasına bağlı olmalı. Meta uygulama incelemesi 2-4 hafta sürüyor. Limit: 200 çağrı/kullanıcı/saat. | Orta — kurulum var ama sonrasında sorunsuz |
| **YouTube** | Data API v3 + Analytics API | Ücretsiz | Google Cloud projesi, OAuth. Günlük 10.000 unit kota (okuma işlemleri 1 unit, gayet yeterli). Gerekirse kota artışı istenebilir. | Düşük — en kolay başlangıç noktası |
| **TikTok** | Display API | Ücretsiz | Public profil/video verisi. Onay süreci TikTok tarafında net bir takvime bağlı değil; sandbox modunda onay öncesi paylaşımlar gizli kalıyor. Limit: 6 istek/dakika/token. Research API sadece akademik kurumlara açık, bize kapalı. | Orta-Yüksek — onay süreci öngörülemez |
| **X (Twitter)** | API v2 | **Ücretsiz katman yok** (Şubat 2026'da kaldırıldı). Kullanım başına ödeme: 1.000 tweet okuma ≈ $5. Düşük hacimli bir analitik uygulaması için bile ayda ~$100-150. | Pay-per-use | Düşük teknik zorluk ama **gerçek bir maliyet kalemi** |

**Buradan çıkan pratik sonuç:** Instagram ve YouTube'la başlamak en mantıklısı — ikisi de ücretsiz ve her creator kendi hesabını bağladığı için mimari zaten çok-kullanıcılı bir yapıya doğal olarak oturuyor. TikTok'u ikinci fazda ekle (onay süreci uzayabileceği için başvuruyu erken yap, beklerken diğer taraflarla ilerle). X'i ya en sona bırak ya da premium/isteğe bağlı bir özellik olarak konumlandır, çünkü kullanıcı sayın arttıkça maliyeti katlanarak büyüyecek bir kalem.

## 4. Rakip Manzarası (Kısa)

Metricool gibi ürünler zaten platformlar arası analitik sunuyor (9 platform, $22-54/ay arası fiyatlandırma), rakip karşılaştırması ve hashtag takibi gibi özellikleri var. Ama araştırmaya göre yapay zekâ tarafları zayıf: görsel/video üretimi, doğal dilde planlama ya da "bu video ne anlatıyor" tarzı içerik anlama özellikleri yok. Senin uzun vadeli planındaki video içeriğini anlayan, metnini çıkaran ve öneri üreten yapay zekâ katmanı — eğer iyi yapılırsa — gerçek bir farklılaşma noktası. Yani MVP aşamasında "bir analitik paneli daha" olmaktan çekinmemeli, çünkü asıl fark ikinci fazda ortaya çıkacak.

## 5. MVP Kapsamı (Faz 1)

MVP'nin tek işi şunu kanıtlamak: platformlardan veri çekip anlamlı, toplu bir görünüme dönüştürebiliyor musun. Öneri kapsam:

Kullanıcı Instagram ve YouTube hesabını OAuth ile bağlar. Uygulama her platformdan son gönderi/video listesini, beğeni-yorum-izlenme sayılarını çeker ve bunu tek bir dashboard'da, platforma göre filtrelenebilir şekilde gösterir (örneğin "bu ay Instagram'da toplam X beğeni, YouTube'da Y izlenme" gibi özet kartları, ve zaman içindeki trend grafiği). Veri günlük olarak senkronize edilir (gerçek zamanlı olmasına gerek yok, YouTube kotası da zaten buna izin vermiyor). Yapay zekâ tarafı bu fazda yok — sadece sayısal toplama ve görselleştirme.

Bunu 4-6 haftada, tek başına ya da küçük bir ekiple, tek kullanıcı (sen) için çalışır hale getirmek gerçekçi bir hedef.

## 6. Teknik Mimari Önerisi

Mimarinin başından itibaren çok-kullanıcılı düşünülmesi öneriliyor, çünkü sonradan tek-kullanıcılı bir sistemi çok-kullanıcılıya çevirmek (özellikle OAuth token yönetimi ve veri izolasyonu konusunda) ciddi bir yeniden yazım gerektirir. Ama bunun bedeli büyük değil — sadece veritabanı şemasını `user_id` bazlı kurmak ve OAuth token'ları kullanıcı başına saklamak yeterli, abonelik/ödeme sistemi gibi karmaşık kısımları ileri faza bırakabilirsin.

Önerilen yapı: bir backend servisi (Node.js/Python), her platform için ayrı bir "connector" modülü (Instagram connector, YouTube connector — ileride TikTok, X), zamanlanmış görevlerle (cron) periyodik veri çekme, ham veriyi saklayan bir veritabanı (Postgres uygun) ve bunun üzerine kurulan bir web dashboard'u. Token'lar şifreli saklanmalı; her connector kendi rate-limit mantığını izole şekilde yönetmeli ki bir platformdaki sorun diğerini etkilemesin.

## 7. Fazlı Yol Haritası

**Faz 1 — MVP (4-6 hafta):** Instagram + YouTube bağlantısı, temel dashboard, sadece sen kullanıyorsun. Amaç: veri çekme borusu çalışıyor mu, gerçekten işine yarıyor mu görmek.

**Faz 2 — Genişleme (6-10 hafta):** TikTok entegrasyonu (başvuruyu Faz 1'in başında yap, onay süreci paralel işlesin), daha zengin analitik (karşılaştırmalı trendler, en iyi performans gösteren içerik tespiti), çoklu kullanıcı desteğinin altyapısal olarak devreye alınması (ama henüz herkese açık değil — belki 5-10 güvendiğin içerik üreticiyle kapalı beta).

**Faz 3 — Yapay Zekâ Katmanı (8-12 hafta):** Video transkript çıkarma (Whisper gibi bir konuşma-metin modeli), içerik özetleme ve konu tespiti, geçmiş performans verisiyle "bu tarz içerik senin için işe yarıyor" tarzı öneriler. Bu faz en çok mühendislik ve muhtemelen en çok maliyet (AI API çağrıları) gerektirecek faz, bu yüzden Faz 1-2'de gelir modeli olmadan yapılmamalı — ya kendi kullanımın için sınırlı tut ya da bu noktada ilk ödeme alan kullanıcıların olması hedeflenmeli.

**Faz 4 — SaaS + Abonelik (Faz 3 ile paralel ya da hemen sonrasında):** Ödeme altyapısı (Stripe gibi), aylık abonelik planları (örneğin temel plan = sadece analitik, üst plan = AI özellikleri dahil), kullanıcı yönetimi, destek süreçleri. X/Twitter entegrasyonu da muhtemelen bu fazda, üst pakete özel bir özellik olarak eklenebilir çünkü maliyeti var.

## 8. Abonelik / Gelir Modeli Önerisi

İki katmanlı bir yapı mantıklı görünüyor: bir "Analitik" planı (platformlar arası istatistik toplama, düşük fiyat, örneğin $8-15/ay aralığı — Metricool'un altında konumlanarak) ve bir "Pro/AI" planı (video anlama, transkript, öneriler dahil, $20-30/ay aralığı). Kesin fiyatlandırma, AI katmanının gerçek maliyetini (transkript + LLM çağrı başına maliyet) Faz 3'te ölçtükten sonra netleşmeli — şu an tahmini bir çerçeve olarak düşün.

## 9. İlk Adımlar (Önümüzdeki 2 Hafta)

Instagram Business/Creator hesabı hazırlığı ve Meta Developer hesabı açılışı, YouTube tarafı için Google Cloud projesi ve API anahtarı alınması, TikTok Developer başvurusunun şimdiden başlatılması (onay süresi uzun olabileceği için erken başlamak faydalı), ve MVP için basit bir teknik prototip iskeletinin kurulması (backend + veritabanı + tek bir platform bağlantısı ile "merhaba dünya" senkronizasyonu).

---

*Bu doküman bir başlangıç çerçevesi. Faz 1'i kodlamaya başlamak, teknik mimariyi daha detaylı tasarlamak ya da Instagram/YouTube API entegrasyonunun ilk kod iskeletini birlikte kurmak istersen buradan devam edebiliriz.*

## Kaynaklar

- [Instagram API Integration Guide 2026 — Phyllo](https://www.getphyllo.com/post/instagram-api-integration-101-for-developers-of-the-creator-economy)
- [TikTok API Pricing: Full Breakdown for 2026 — Blotato](https://www.blotato.com/blog/tiktok-api-pricing)
- [YouTube API Quota Limits 2026 — Phyllo](https://www.getphyllo.com/post/youtube-api-limits-how-to-calculate-api-usage-cost-and-fix-exceeded-api-quota)
- [Twitter/X API Pricing 2026: All Tiers — Xpoz](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/)
- [Metricool Pricing 2026 — Poster.ly](https://www.poster.ly/vs/metricool)
