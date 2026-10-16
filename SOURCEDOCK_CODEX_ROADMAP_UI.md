# SourceDock ⚡ — Codex Uygulama Planı, Teknik Borç ve UI/UX Tasarım Brifi

**Tarih:** 13 Ekim 2026  
**Repo:** https://github.com/aliafacan/SourceDock  
**Hedef:** Güvenli, test edilebilir, rahat kurulabilen, modern ve dağıtımlar arasında tutarlı bir Linux paket yöneticisi.  
**Hedef sürümler:** `v1.0.1` (güvenlik/kararlılık), `v1.1.0` (UI/UX ve yayınlama), `v1.2.0+` (ek özellikler).  
**Kullanım:** Bu dosyayı repo köküne `CODEX_PLAN.md` olarak koyabilir veya Codex'e doğrudan verebilirsin.

## Güncel Durum — 16 Ekim 2026

Bu dosyanın görev kutuları mevcut yerel `1.3.0` kaynakları ve çalışan testlerle
yeniden eşleştirildi. `[x]`, ilgili yerel uygulamanın/testin bulunduğunu;
`[ ]` yanındaki **Kısmi**, **BLOCKED**, **NOT TESTED** veya **Açık (P2)** notları
ise tam olarak neyin eksik olduğunu gösterir. Yerel birim testi gerçek paket
kurulumunun veya GitHub CI koşusunun yerine geçmez.

Bu turda örtük APT autoremove kaldırıldı; hassas toplu kaldırma onayı, kapsamlı
Flatpak temizlik önizlemesi, parola redaksiyonu, portable kaldırmada yeniden
deneme, tanılama çevirileri, bilgi/hata ayrımı ve kısmi checkbox durumu düzeltildi.
X11 kabul aracı dış pencere çerçevesi ile gerçek kök ekran piksellerini ayrı ölçer.
Eski ekran görüntüleri yeni sürüm adıyla paketlenmedi.

Devam turunda CI için host komut koruması ve geçici test verisi yalıtımı eklendi;
bağımsız detay/`--uninstall` işlemleri ortak onay ve worker akışına alındı.
1.000 kayıtla gerçek GTK arama/filtre/kaydırma ölçümü dört X11/ölçek koşulunda
geçti. Güncel takım: 193 test, hata ve atlama yok. Toplam 113 görev tikli,
54 görev gerekçeleriyle açık/kısmi; gerçek VM ve güncel yerel ağacın uzak CI kabulü açık.

Güncel dosya/test/ekran kanıtları ve kalan yayın engelleri:
[16 Ekim çalışma raporu](docs/ROADMAP_COMPLETION_REPORT.md).

## Önceki Uygulama Durumu — 14 Ekim 2026

`1.2.0` için güvenlik sınırları, sol gezinme, tema sistemi, mağaza kartları,
güncelleme merkezi, mini kurucu, kaynak görüntüleme ve uygulama listesi önizlemeli
geri yükleme uygulandı. Ayrıntılı kanıt ve açık kalan işler:
[Uygulama Raporu](docs/ROADMAP_IMPLEMENTATION.md),
[Tasarım](docs/UI_DESIGN.md), [Uyumluluk](docs/COMPATIBILITY.md).

Bu belgedeki geleceğe yönelik ve dış ortam gerektiren maddeler otomatik olarak
tamamlanmış kabul edilmez. Gerçek paket işlemleri, uzaktaki CI ve yayınlama ayrı
doğrulama gerektirir. Son ekran görüntüsü/ölçüm sonuçları `docs/screenshots/validation.json` içindedir.

> [!IMPORTANT]
> Bu belge bir uygulama planıdır; listelenen her madde kanıtlanmış hata değildir. Başlamadan önce **mevcut kodu yeniden analiz et**, sorunları testle doğrula. Depodaki `ROADMAP.md` Aşama 1–6'nın tamamlandığını ifade eder. Bu plan bunları çöpe atmak için değil, ürünü sağlamlaştırmak ve büyütmek içindir. Gerçek kullanıcı verisine ve makinenin paket yöneticisine zarar verme ihtimali bulunan işlemler özellikle dikkatli ele alınmalıdır.

---

## 0. Codex'in uyması gereken değişmez kurallar

- [x] `README.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `.github/workflows/ci.yml`, `packaging/build_deb.sh`, `main.py`, `sourcedock/` ve `tests/` incelenmeden dosya değiştirme.
- [x] Önce kısa durum raporu hazırla: **mevcut / eksik / riskli / doğrulanmadı**; planı güncel `main` ile eşleştir.
- [ ] Mevcut çalışan özellikleri ve TR/EN çeviri anahtarlarını koru. Eksik çevirileri tamamla; arayüzde sabit Türkçe/İngilizce metin bırakma. **Durum (16.10.2026):** Kısmi: dinamik tanılama ve geçmiş çevirileri düzeltildi; tüm backend hata mesajlarının yerelleştirme denetimi açık.
- [ ] Büyük işi küçük PR/commit'lere ayır. Her aşama sonunda testleri çalıştır, sonucu raporla. Başarısız testleri saklama. **Durum (16.10.2026):** Kısmi: değişiklikler ve testler aşamalarla yürütüldü; kullanıcının izni olmadan commit/PR oluşturulmadı.
- [x] Özellikle paket kurma, silme, yükseltme, arşiv çıkarma ve sudo gerektiren işler için **dry-run/mocked tests** kullan; CI ortamında gerçek host sistemini değiştirme.
- [x] Root olarak GUI çalıştırma. Yetki yükseltmeyi olabildiğince dar tut. Kullanıcı parolasını loglama, diske yazma veya hata raporuna ekleme.
- [x] Güvenilmeyen paketin kodunu yalnızca ikon/metadata okumak için çalıştırma. `shell=True`, kontrolsüz `rm -rf`/`rmtree`, string birleştirmeli shell komutları kullanma.
- [x] `GTK 3 / PyGObject` mevcut teknik temel; UI yenilemesinde önce onunla yapılabilecekleri değerlendir. **GTK4/libadwaita'ya otomatik geçiş yapma**; maliyet/uyumluluk raporunu ayrı hazırla.
- [x] İzin vermeden kullanıcıdaki kurulu uygulamaları kaldırma, sistem paketlerini değiştirme, kurulu depoları manipüle etme veya mevcut çalışma dizinlerini temizleme.
- [x] Kullanıcıyı yanıltan göstergeler oluşturma: sahte derecelendirme, uydurma indirme sayısı, sahte güncelleme güvenliği, doğrulanmamış 'tested on' etiketleri yasak.
- [x] Her faz sonunda: değişen dosyalar, test komutları ve sonuçları, manuel test adımları, bilinen sınırlamalar, sonraki faz bağımlılıkları.

## 1. Mevcut proje envanteri (inceleme sırasında gözlenen)

- [x] GTK 3 + Python tabanlı modüler UI (`sourcedock/ui/views`, `sourcedock/ui/components`, `sourcedock/ui/window.py`).
- [x] Native backends: APT, DNF, Pacman, Zypper; ek kaynaklar Flatpak, Snap, AppImage, portable ve firmware.
- [x] TR/EN i18n, tema, mini paket kurucu, kurulu uygulamalar, mağaza, işlemler, ayarlar ve yardım ekranı.
- [x] `tests/` altında birim testleri ve GitHub Actions CI yapılandırması.
- [x] `packaging/sourcedock_1.0.0_all.deb` ve derleme betiği.
- [x] `CONTRIBUTING.md`, issue/PR şablonları, `ROADMAP.md`.
- [x] **GitHub Release** yoktu (13.10.2026 incelemesi); yeniden doğrula. **Kanıt (16.10.2026):** GitHub Releases API salt okunur sorgulandı; sonuç `[]`, henüz Release yok. Bu kutu yayımlama değil durum doğrulamasıdır.
- [x] Repository **topics** boştu; yeniden doğrula. **Kanıt (16.10.2026):** GitHub repository API `topics: []`; liste hâlâ boş, uzak ayarlar değiştirilmedi.
- [x] README'de gerçek arayüz ekran görüntüleri eklendi; kurulum gösterim GIF'i ayrıca doğrulanacak.
- [x] `LICENSE` dosyasındaki GPLv3 metni kısaltılmıştı: tam, değişmemiş GPLv3 metniyle düzelt.
- [ ] CI'nin farklı dağıtım ve Python/GTK kombinasyonlarında gerçekten geçtiğini doğrulamak gerekiyor. **Durum (16.10.2026):** Kısmi: uzak `13f6f0b` commit'inin CI koşusu başarılı; güncel yerel değişiklikler bu koşuda yok. Dağıtım matrisi sonucu güncel ağaç için doğrulanmadı.

## 2. P0 — Güvenlik ve veri koruma (v1.0.1'den önce)

### P0.1 Portable kaldırmada güvenli yol doğrulaması
**İlgili dosya:** `sourcedock/backend/portable.py`

- [x] `PortableProvider.remove()` içindeki `shutil.rmtree(application.install_path, ignore_errors=True)` yolunu gözden geçir.
- [x] Sadece **SourceDock tarafından yönetildiği kanıtlanan** uygulama dizinlerini sil; path'in yönetilen kök altında olduğunu `Path.resolve()` ve `relative_to()` ile doğrula. Sembolik bağları ve `..` geçişlerini reddet.
- [x] Kullanıcının seçtiği özel konuma kurulum destekleniyorsa, güvenli sahiplik kaydı/manifest olmadan asla otomatik dizin silme.
- [x] Desktop dosyası silme için de kullanıcı uygulama dizini ve SourceDock'ın oluşturduğu kayıt kontrolü yap.
- [x] `ignore_errors=True` yerine kullanıcıya anlaşılır hata raporu, başarısızsa kaydı silmeme ve geri denenebilir durum kullan.
- [x] Registre edilmiş sahte `/home/user/Documents`, symlink, bozuk kayıt, eksik dosya ve başarılı kaldırma testlerini ekle.

**Kabul kriteri:** Manipüle edilmiş registry kaydıyla SourceDock tarafından yönetilmeyen herhangi bir dizin silinemez.

### P0.2 Arşiv çıkarma: Zip Slip, symlink, tar filter, zip bomb
**İlgili dosya:** `sourcedock/backend/local_packages.py`

- [x] `_safe_extract_archive` içindeki `str(target).startswith(str(dest_resolved))` kontrolünü dizin bazlı `relative_to()` doğrulamasıyla değiştir.
- [x] `tar` için link, hardlink, device/special file, mutlak yol, `../`, mevcut symlink zincirleri ve izinleri güvenlik açısından ele al.
- [x] Eski Python sürümlerinde `tarfile` filtre davranışına güvenme: ya güvenli özel doğrulama uygula ya desteklenen minimum sürümü güncelle.
- [x] ZIP dosyalarında symlink girişlerini ve yazma sırasındaki symlink yarışlarını ele al.
- [x] Maksimum toplam açılmış veri, dosya adedi, dosya başına sınır ve isteğe bağlı boyut oranı koruması uygula.
- [x] Açma işlemini rastgele sistem konumuna değil, güvenli geçici dizine yap. Doğrulama sonrası hedefe atomik/geçişi güvenli taşı.
- [x] İşlem başarısızsa eski kurulumun korunacağını garanti et; kısmen açılmış içeriği temizle.
- [x] Güvenlik regresyon testleri: `app/../evil`, `apps-copy/evil`, absolute path, symlink escape, nested tar symlink, zip bomb simülasyonu.

**Kabul kriteri:** Kötü niyetli arşiv hedef dışına tek dosya dahi yazamaz; önceki kurulum hata sonrasında korunur.

### P0.3 AppImage metadata ayrıştırma güvenliği
**İlgili dosya:** `sourcedock/backend/local_packages.py`

- [x] `_extract_appimage_icon_and_info()` içindeki `[file_path, '--appimage-extract', ...]` çağrılarının güvenlik riskini doğrula.
- [x] Metadata okumada dosyanın executable kodunu çalıştırmayan güvenli ayrıştırıcı seçenekleri araştır; mümkün değilse açık güven onayı + izole yardımcı işlem + sağlam uyarı kullan.
- [x] Dosyaya `chmod +x` uygulamadan önce kullanıcıya davranışı açıkça göster ve yalnızca gerekli anda uygula.
- [x] Güvenilmeyen AppImage üzerinde metadata görüntülemenin beklenmedik kod yürütmediğini test et.

### P0.4 Sudo, yetki sınırı ve işlem iptali
**İlgili dosya:** `sourcedock/core/runner.py`, ilgili UI diyaloğu

- [x] `set_sudo_password()` / `sudo -S` akışındaki kimlik bilgisi ömrünü gözden geçir: yalnızca geçici bellek, temizleme, hata/iptalde temizleme.
- [ ] `polkit`/`pkexec` veya sistemin desteklediği yetkilendirme mekanizması için mimari öneri ve küçük proof-of-concept hazırla; güvenli olmayan acele geçiş yapma. **Durum (16.10.2026):** Kısmi: docs/AUTHORIZATION.md önerisi mevcut; çalışır, bağımsız denetlenmiş Polkit helper/policy henüz yok.
- [x] Hata loglarında komut argümanlarının gizli veri içerip içermediğini kontrol et; redaksiyon ekle.
- [x] `_run_streaming()` için mutlak zaman aşımı ve iptal davranışını sınır durumlarında test et (çıkış üretmeyen proses, child process, bloke stdout, SIGTERM'e direnme).
- [x] APT/DPKG sırasında zorla iptalin paket veritabanını bozma riskini UI'da belirt. Kritik işlemlerde güvenli iptal davranışı tasarla.
- [x] Aynı kaynağa yönelik eşzamanlı kur/kaldır/güncelle işlemlerini serileştir.

### P0.5 Paket kaynağı ve güven göstergeleri

- [x] Yerel `.deb`/`.rpm`/`.AppImage`/arşiv kurulumunda **kaynak, yayıncı (biliniyorsa), imza/doğrulama durumu, yetki seviyesi** göster.
- [x] “Güvenli” rozeti yalnızca gerçekten doğrulanan bir mekanizma varsa göster; aksi halde “Doğrulanmadı”.
- [x] Snap classic gibi geniş izinleri anlaşılır, manipülasyonsuz anlat ve kullanıcı onayını koru.
- [ ] Paket kurulumu yapılmadan önce etkilenecek bağımlılıkların ve olası kaldırmaların önizlemesini sun (backend destekliyorsa). **Durum (16.10.2026):** Kısmi: yerel .deb için APT simülasyonu mevcut; diğer sağlayıcıların değişiklik planları açık.

## 3. P1 — Test, CI, dağıtım ve bakım (v1.0.1 / v1.1.0)

### P1.1 Tekrarlanabilir test sistemi

- [x] Testleri birim, entegrasyon (mock/fake CLI) ve manuel dağıtım smoke test olarak ayır.
- [ ] APT, DNF, Pacman, Zypper, Flatpak, Snap için komut çıktısı fixture'ları ve hata senaryoları oluştur. **Durum (16.10.2026):** Kısmi: altı sağlayıcı için fake komut/parsing testleri var; bütün locale/hata fixture kombinasyonları tamamlanmadı.
- [ ] Veri/parsing testleri: farklı locale çıktıları, sürüm karşılaştırması, boş metadata, bağlantı kesintisi, yetki reddi, bozuk paket, depo erişilemezliği. **Durum (16.10.2026):** Kısmi: sürüm, boş metadata, yetki ve timeout testleri var; tüm bozuk-paket/depo/ağ/locale kombinasyonları açık.
- [x] İşlem kuyrukları, ilerleme, iptal, geri dönme ve UI thread donmaması için test ekle.
- [x] GUI smoke testlerini `Xvfb` altında çalıştır; gerektiğinde ekran görüntüsüyle manuel doğrulama raporu üret.
- [ ] `ruff`, uygun formatter, isteğe bağlı tip denetimi ve güvenlik taraması ekle; kural setini mevcut koda göre aşamalı uygula. **Durum (16.10.2026):** Kısmi: Ruff ve formatter yapılandırması var; depo genelinde formatter ve ayrı güvenlik taraması kabulü açık.
- [x] CI Python yorumlayıcısı ile sistem `python3-gi` modülünün uyumunu doğrula. Özel `setup-python` ile yanlış interpreter seçimi olursa matrix stratejisini düzelt.
- [x] CI'da repo üzerinde test yapılırken host paket yöneticisini çağırmadığını garanti et. **Kanıt (16.10.2026):** CI `tools/run_tests.py` audit korumasını kullanıyor; paket/yetki/kabuk/bilinmeyen komutlar engelleniyor, test verisi geçici dizinde. 193 testte 0 beklenmeyen çağrı; canlı sentinel engelleme testi var. Bu güvenilir testler için kaza korumasıdır, kötü niyetli Python/native kodu için OS sandbox değildir.
- [ ] CI başarısızlığında kırmızı badge'i gizleme; düzelt. **Durum (16.10.2026):** Kısmi: son uzak CI başarılı (38545352107); güncel yerel ağacın GitHub CI koşusu bekleniyor, badge gizlenmedi.

### P1.2 Gerçek dağıtım destek matrisi

- [ ] Öncelik: Zorin OS (gerçek makine), Ubuntu LTS, Debian stable. **Durum (16.10.2026):** BLOCKED: temiz Zorin/Ubuntu/Debian test VM'si ve gerçek kurulum kabulü yok.
- [ ] Sonra VM/container uygunluğuna göre Fedora, openSUSE, Arch/Manjaro. **Durum (16.10.2026):** BLOCKED: Fedora/openSUSE/Arch test ortamları yok.
- [ ] Her ortam için **başlatma, katalog, arama, kurulu uygulamalar, dry-run/izole kurulum, güncelleme bilgisi, kaldırma, MIME/çift tık, TR/EN, dark/light, HiDPI** testlerini kaydet. **Durum (16.10.2026):** BLOCKED: gerçek dağıtım/işlem matrisi tamamlanmadı.
- [ ] En az bir gerçek makinede Flatpak/Snap yokken davranışı doğrula. **Durum (16.10.2026):** NOT TESTED: gerçek Flatpak/Snap bulunmayan makine kabulü yapılmadı; otomatik eksik-sağlayıcı durumları ayrı.
- [x] Destek tablosunu `docs/COMPATIBILITY.md` olarak yayınla: **Tested / Experimental / Not tested / Unsupported**.
- [x] `Architecture: all` paketinin Python kodu açısından doğru olduğunu, ancak bağımlılık ve Debian aile sınırlarını belgede açık yaz.

### P1.3 Paketleme ve sürümleme

- [x] `packaging/build_deb.sh` içindeki hardcoded `VERSION=1.0.0` değerini tek sürüm kaynağına bağla (`sourcedock/constants.py`).
- [x] Build çıktısını kalıcı `packaging/` içinde commit etmek yerine release artifact olarak yönetmeyi değerlendir; mevcut kullanıcılar için geçişi açıklığa kavuştur.
- [ ] `dpkg-deb --build` sonrasında `lintian` benzeri kalite kontrolleri (mevcutsa) çalıştır. **Durum (16.10.2026):** BLOCKED: Lintian kurulu değil; betikte isteğe bağlı kontrolü var.
- [ ] İkon/MIME/Desktop Entry doğrulaması: `desktop-file-validate`, `appstreamcli validate`, uygun MIME testleri. **Durum (16.10.2026):** Kısmi: desktop/AppStream ve MIME birim kontrolleri mevcut; gerçek dosya ilişkilendirmeleri VM kabulünü bekliyor.
- [x] Bağımlılıklar ile README'de beyan edilen minimum Python/Ubuntu sürümlerini tutarlı hale getir.
- [ ] `install.sh` ve `uninstall.sh` işlemlerinin `.deb` ile kurulan dosyalara zarar vermediğini doğrula; iki yöntemin birlikte kullanım stratejisini tanımla. **Durum (16.10.2026):** Kısmi: APT sahiplik koruması ve iki manuel kurulumun kaldırma sırası düzeltildi; gerçek birlikte-kullanım yaşam döngüsü VM kabulünü bekliyor.
- [x] **Debian ailesi için yayınla; diğer dağıtımlar için aynı `.deb`'i evrensel çözüm diye sunma.** `rpm`/PKGBUILD/Flatpak paketleme daha sonra ayrı testli iş olabilir.
- [x] GitHub Actions ile tag bazlı build, test, SHA-256 ve **taslak release** oluşturma akışı kur (yayın kararı onayla).

### P1.4 Lisans ve dokümantasyon

- [x] Tam GPL-3.0 lisans metnini `LICENSE` içine ekle; GitHub'ın tanıması yayın sonrası doğrulanacak.
- [ ] Tüm üçüncü taraf asset, icon, bağımlılık ve lisansları kontrol et; gerekirse `THIRD_PARTY_NOTICES.md`. **Durum (16.10.2026):** Kısmi: üçüncü taraf bildirimleri ve tam GPL pakete eklendi; tüm upstream varlık/bağımlılık lisans envanteri henüz tamamlanmadı.
- [x] `README.md` içinde **Install → Screenshot → Features → Supported distros → FAQ → Contribute** sırası oluştur.
- [x] README'deki aşırı kesin iddiaları (“universal”, “blazing-fast”, “full support”) test durumuna göre kalibre et.
- [x] `SECURITY.md`: güvenlik bildirimi yöntemi, kapsam ve yanıt ilkeleri.
- [x] `CHANGELOG.md`, `docs/TROUBLESHOOTING.md`, `docs/ARCHITECTURE.md`, `docs/COMPATIBILITY.md`.
- [x] PR/issue şablonlarına dağıtım/sürüm, Python/GTK, backend, hata logu (kişisel veri redakte edilmiş) ve tekrar adımları ekle.

## 4. P1 — UI/UX yeniden tasarım (v1.1.0)

> **Özel kural:** Kullanıcı deneyimini yeniden tasarla, yalnızca renkleri değiştirme. Ama tek seferde tüm iş mantığını değiştirme. Önce tasarım sistemi, sonra ekran ekran güvenli entegrasyon. SourceDock'ın kaynakları tek dock'ta birleştiren özgün kimliğini koru; telifli karakter görsellerini marka öğesi olarak kullanma.

### 4.1 Gerçek uygulama referansları

1. **GNOME Software** — https://apps.gnome.org/Software/  
   Referans: ferah ve az gürültülü ana sayfa; kategoriler; uygulama detay ekranı; ekran görüntüsü galerisi; kurulu/güncelleme ekranları. **Ödünç alınacak:** içerik hiyerarşisi ve sakin bilgi sunumu. **Kopyalanmayacak:** logo, ikonlar, piksel düzeni.
2. **KDE Discover** — https://apps.kde.org/discover/  
   Referans: solda kalıcı gezinme, uygulama arama, kaynaklar ve güncellemeleri yönetme. **Ödünç alınacak:** çok kaynaklı katalog mimarisi ve gezinme; **kopyalanmayacak:** KDE görsel kimliği.
3. **Warehouse** — https://github.com/flattool/warehouse  
   Referans: Flatpak ayrıntı, veri temizleme, toplu eylemler, depo yönetimi. **Ödünç alınacak:** gelişmiş ayarları basit açıklamalarla gösterme, riskli işlemleri açık onaya bağlama.
4. **Pamac** — https://wiki.manjaro.org/index.php?title=Pamac  
   Referans: paket yöneticisi ile yazılım mağazası arasında dengeli kullanım; arama, kurulu uygulamalar, gelişmiş paket detayı. **Ödünç alınacak:** acemi ve deneyimli kullanıcıya farklı ayrıntı seviyesi.

**Özgün SourceDock yönü:** Tek ekranda uygulamanın alternatif kaynaklarını karşılaştırma (`APT / Flatpak / Snap`), yerel dosya için odaklı **mini installer**, güvenli toplu işlemler ve kaynağın ne anlama geldiğini kullanıcı dilinde açıklama.

### 4.2 Görsel kimlik ve tasarım sistemi

- [x] Koyu tema: koyu kömür/lacivert tonlarında nötr yüzey; beyaz yerine yumuşak açık metin; elektrik sarısı **yalnızca vurgu ve işlem durumu**. Koyu arayüzü neon reklam panosuna çevirme.
- [x] Açık tema: sıcak/nötr beyaz yüzey, çok hafif sınır çizgileri, okunaklı koyu metin, aynı vurgu semantiği.
- [x] Font: sistem fontu (GNOME'da Cantarell/Adwaita uyumu dahil), sistem fallback; ekstra font yüklemesi gerektirme.
- [ ] Spacing sistemi: 4/8/12/16/24/32; kart köşe yarıçapları 10–14 px; düzenli hizalama. **Durum (16.10.2026):** Kısmi: aralık sistemi mevcut; kart köşeleri docs/UI_DESIGN.md kararıyla en fazla 8 px, burada yazan 10–14 px uygulanmadı.
- [ ] Kontrast: normal metin için WCAG AA'ya hedefle; bilgi yalnızca renkle ifade edilmesin. **Durum (16.10.2026):** Kısmi: açık/koyu kontrast hataları düzeltildi; bütün durumların ölçülmüş WCAG AA denetimi açık.
- [x] İkonlar: GTK/Adwaita sembolik ikonları ve mevcut özgün SourceDock ikonu; anlam tutarlılığı. Emoji ile ikon ikamesi yapma.
- [ ] Hareket: 120–200 ms yumuşak geçişler, sistem reduced-motion tercihine saygı. **Durum (16.10.2026):** Kısmi: GTK geçişleri mevcut; reduced-motion kabul testi açık.
- [ ] Uygun ekranlar: 1024×768, 1366×768, 1920×1080 ve HiDPI; minimum pencere genişliği/scroll davranışı. **Durum (16.10.2026):** Kısmi: gerçek kök ekran ve modal ölçüm altyapısı düzeltildi; son çalışma sonuçları bağlantılı raporda.
- [x] GTK CSS token katmanı oluştur: background/surface/surface-hover/border/text-muted/accent/success/warning/danger/focus.
- [x] `sourcedock/theme.py` ve `sourcedock/ui/components` parçalarını yeniden kullanılabilir bileşenlere ayır.

### 4.3 Bilgi mimarisi ve genel pencere

- [x] **Sol yan çubuk**: Keşfet, Kurulu, Güncellemeler, İşlemler; alt bölüm: Yerel Paket Kur, Ayarlar, Yardım.
- [x] **Üst bar**: aktif sayfa başlığı, global arama (`Ctrl+K` veya `Ctrl+F`), güncelleme sayacı, işlem durum düğmesi, gerektiğinde kaynak filtresi.
- [x] 1100 px altında yan çubuğu daralt veya uyumlu hale getir. Pencere küçükken düğmeler kaybolmasın.
- [ ] Global boş/yükleniyor/hata durumları; ortak toast/snackbar; keyboard focus ve ekran okuyucu açıklamaları. **Durum (16.10.2026):** Kısmi: ortak yükleniyor/boş/hata bileşeni ve odak stilleri mevcut; ortak toast ve tam ekran okuyucu kabulü açık.
- [x] Verisi henüz gelmeyen kartlarda skeleton veya sakin spinner; kilitlenmiş gibi görünmesin.
- [ ] Uzun ağ/bekleme işlemleri GTK main thread'i bloklamasın. Biten veri UI thread'inde güncellensin. **Durum (16.10.2026):** Kısmi: sorgular ve bağımsız güncelleme/kaldırma artık worker'da; `--uninstall` ortak güvenlik onayını kullanıyor. GTK heartbeat, yetki/iptal/hata ve kapanma testleri geçti. İlk CLI uygulama araması ve yerel dosya önizlemesinin tüm ağır açılış yolları için yükleme akışı henüz denetlenmedi.

### 4.4 Keşfet / Mağaza ekranı

- [x] Üstte anlamlı arama alanı, kategori çipleri (Üretkenlik, Geliştirme, İnternet, Grafik, Sistem vb.).
- [ ] Tek büyük promosyon görseli yerine isteğe bağlı sade **öne çıkan uygulamalar** alanı; doğrulanmış veri yoksa sahte popülerlik bilgisi gösterme. **Durum (16.10.2026):** Açık (isteğe bağlı): doğrulanmış öne çıkan katalog alanı eklenmedi.
- [x] Grid kartında: gerçek ikon, isim, kısa açıklama, kaynaklar, kurulu/güncelleme durumu ve tek net eylem.
- [x] Aynı uygulamanın farklı kaynaklarını mümkünse **birleştirilmiş görünümde** sun; aynı uygulamaları anlaşılmaz tekrarlarla listeleme.
- [ ] Filtreler: kaynak, kurulu, kategori, istemci mimarisi (veri destekliyorsa). Sıralama net ve açıklanabilir olsun. **Durum (16.10.2026):** Kısmi: kaynak ve kategori arama/sıralaması mevcut; kurulu ve mimari filtreleri tüm sağlayıcılarda yok.
- [x] Arama sonucu yok, repo çevrimdışı, Flatpak kurulu değil, yetki yok gibi durumlara ayrı mesaj ve çözüm bağlantısı.

### 4.5 Uygulama detay sayfası

- [x] Başlık: ikon, ad, doğrulanabilen yayıncı, kısa açıklama, kur/kaldır/güncelle/aç.
- [x] Kaynak seçici: APT / Flatpak / Snap / diğer; sürüm, boyut, sandbox, kaynak ve izin karşılaştırması.
- [x] Açıklama; ekran görüntüsü galerisi (AppStream metadata varsa); sürüm, homepage, lisans, yüklü boyut, değişiklikler.
- [x] Güvenlik paneli: **Kaynak doğrulanmış / doğrulanmadı / bilinmiyor**, sandbox/izinler; kaynaklar arasında tarafsız rehber.
- [x] Metadata yoksa sahte ekran görüntüsü/yorum/derecelendirme uydurma.
- [x] Kurulum sırasında 'iptal' düğmesinin gerçek güvenli davranışını açıkça belirt.

### 4.6 Kurulu uygulamalar

- [x] Masaüstü uygulamaları ile çekirdek/sistem bağımlılıklarını ayır; varsayılan görünüm acemi kullanıcıyı paket kalabalığına boğmasın.
- [ ] Arama, kaynak filtreleri, isteğe bağlı ayrıntı tablosu, liste/grid geçişi. **Durum (16.10.2026):** Kısmi: arama/kaynak/kategori ve ayrıntılı tablo mevcut; Kurulu ekranında ayrı grid görünümü yok.
- [x] Toplu kaldırma için seçim, toplam sayı ve net onay; sistem açısından hassas paketlerde ekstra doğrulama.
- [x] Uygulamayı Aç, Dosyayı Göster, Ayrıntılar, Güncelle, Kaldır eylemleri gerçek backend desteğine göre koşullu gösterilsin.
- [x] Kaldırma sırasında kullanıcı verisi siliniyorsa bundan ayrıca bahset; varsayılan olarak silme.

### 4.7 Güncellemeler merkezi

- [x] APT/DNF/Pacman/Zypper, Flatpak, Snap, firmware, runtime öğelerini **kaynak etiketleriyle** tek listede sun.
- [x] Gruplar: Uygulamalar / Sistem / Firmware / Çalışma Ortamları; toplam sayı ve yalnızca doğru ölçülmüş indirme boyutunu göster.
- [x] Seçerek güncelle, hepsini güncelle (uygunsa), yeniden kontrol et, değişiklik notları.
- [x] Yeniden başlatma gerektiriyorsa tespit et ve işlemler sonrasında öner; kesin değilse kesin ifade kullanma.
- [x] Firmware/dbx güncellemelerinde özel onay ve güç/cihaz uyarıları; üretici bilgisi yalnızca metadata varsa gösterilir.
- [x] Güncelleme hatalarında çalışan öğeleri koru, başarısız öğeleri açık raporla.

### 4.8 Mini Installer: SourceDock'ın ayırt edici özelliği

- [x] Dosya çift tıklanınca ana mağazayı yüklemeden **hızlı, küçük, odaklı** pencere aç.
- [x] Dosya adı, format, boyut, algılanan paket adı, kurulu sürüm, kurulacak sürüm, kaynak yolu, mimari göster.
- [x] Eylemler: Yeni Kur / Güncelle / Yeniden Kur / Sürüm Düşür / Aç veya İptal; yalnızca mantıksal olarak mümkün olanları göster.
- [x] Sürüm düşürme ve şüpheli paket için belirgin ama bağırmayan uyarı.
- [x] Kurulum aşamasında aynı pencere içinde gerçek ilerleme, ayrıntı açılır bölümü ve başarısızlıkta yeniden dene.
- [x] Başarılıysa 'Uygulamayı Aç', 'Kapat', isteğe bağlı 'Ayrıntılar'.
- [ ] Ekran okuyucu, klavye, uzun dosya adı, TR/EN ve küçük ekran testleri. **Durum (16.10.2026):** Kısmi: TR/EN ve pencere ölçümleri mevcut; gerçek ekran okuyucu ve bütün klavye akışları açık.

### 4.9 İşlemler, ayarlar, yardım

- [x] İşlemler ekranında her işi **hazırlanıyor → indiriliyor → kuruluyor → tamamlandı/başarısız** şeklinde doğru durumla göster.
- [x] İşlem geçmişi: saat, işlem, kaynak, sonuç; maskeleme ve kullanıcı kontrollü temizleme.
- [x] Ayarlar: Tema (Sistem/Açık/Koyu), dil (TR/EN), arayüz yoğunluğu/ölçek, kaynak tercihleri, güncelleme kontrolü.
- [x] Riskli deneysel ayarlar 'Gelişmiş' bölümünde tutulmalı; varsayılanlar güvenli olmalı.
- [x] F1 yardım mevcut; yeni ekran isimleri ve tooltip'lere göre güncelle, bağlama duyarlı yardım ekle.

### 4.10 Erişilebilirlik ve kalite kontrol

- [ ] Tab sırası, odak halkası, ekran okuyucu isimleri, ESC/Enter davranışları. **Durum (16.10.2026):** Kısmi: odak/erişilebilir isim ve Enter/ESC/Space yolları var; tam Tab/Orca kabulü açık.
- [ ] Türkçe uzun kelime ve İngilizce metin taşmaları; 90/100/110/125% ölçekte kontrol. **Durum (16.10.2026):** Kısmi: son ölçümler raporda; tüm uzun metin/ölçek akışlarının manuel kabulü açık.
- [ ] Koyu/açık tema; klavye ile tüm ana görevler; minimum pencere boyutu. **Durum (16.10.2026):** Kısmi: tema ve pencere ölçümleri mevcut; bütün ana görevlerin klavye kabulü açık.
- [x] Gerçek veri ile ekran görüntüleri: ana sayfa, detay, kurulu, güncelleme, mini-installer, ayarlar.
- [x] UI performansı: 1.000+ uygulama kaydıyla scroll, arama ve filtreyi ölç; makul hedef belirle ve raporla. **Kanıt (16.10.2026):** `tools/ui_performance.py`, 1.000 sentetik kayıt, 5 ölçülen tekrar; 1024×768 ve 1366×768, %100/%125. Gerçek başlık araması/kaynak/kategori/son satıra kaydırma için ilk GTK çizimi ve p95 hedefleri raporlandı; dört koşu PASS. Bu GPU FPS, gerçek ağ araması veya tüm gerçek ikon kataloglarının sertifikası değildir.

## 5. P2 — Kullanıcı açısından değerli yeni özellikler (v1.2+)

- [x] **Kurulu uygulama listesini dışa aktar / içe aktar:** kaynak türü, paket kimliği, sürüm (bilgi amaçlı), hedef dağıtım uyumluluğu; geri yükleme önce simülasyon/önizleme.
- [ ] **Tek uygulama, farklı kaynaklar:** benzer eşleme hataları için açık kullanıcı kontrolü; yanlış eşleşme olmadan APT/Flatpak/Snap kıyaslaması. **Durum (16.10.2026):** Kısmi: kesin kimliklerle gruplama/kaynak seçimi var; kullanıcının eşleştirmeyi düzeltme akışı yok.
- [ ] **Paket kaynak yöneticisi:** Flatpak remote, Snap kanalı, native repo bilgilerinin güvenli gösterimi; değiştirme ayrı onayla. **Durum (16.10.2026):** Kısmi: URI/suite/component/kapsam bilgileri salt okunur gösteriliyor; depo değiştirme/kanal düzenleme akışı yok.
- [x] **Gereksiz/verisiz paket temizliği:** yalnızca sistem sağlayıcısının güvenli tahminiyle; neyin silineceği önce listelensin.
- [x] **İşlem geçmişi dışa aktarma:** kullanıcı adı/ev dizini ve parola gibi bilgileri redakte ederek.
- [ ] **Bildirim alanı:** arka planda güvenli kontrol / sistem bildirimleri, gereksiz sürekli arka plan servisi olmadan. **Durum (16.10.2026):** Açık (P2): isteğe bağlı arka plan kontrolü/sistem bildirimleri uygulanmadı.
- [ ] **Güncelleme öncesi snapshot entegrasyonu:** Timeshift/Btrfs varlığı ve uygun yetki kontrolü; desteklenmeyende pasif. **Durum (16.10.2026):** BLOCKED (P2): snapshot sağlayıcısı ve disposable Btrfs/Timeshift kabul ortamı yok.
- [ ] **AppImage update deneyimi:** yalnızca doğrulanmış update metadata varsa; AppImageUpdate bağımlılığı açıklansın. **Durum (16.10.2026):** Kısmi (P2): AppImageUpdate ve update-info varlığına bakılıyor; update metadata doğrulama kabulü açık.
- [ ] **İsteğe bağlı otomatik tema ve sistem vurgu uyumu.** **Durum (16.10.2026):** Kısmi (P2): otomatik sistem teması var; sistem vurgu rengi entegrasyonu yok.
- [ ] **Yeni yerelleştirmeler:** gettext/Weblate benzeri katkı akışı (mevcut sözlük yapısını dikkate al). **Durum (16.10.2026):** Açık (P2): ek diller için gettext/Weblate katkı altyapısı yok.

## 6. GitHub görünürlüğü ve topluluk (P1/P2)

- [ ] Repo topics: `linux`, `package-manager`, `gtk3`, `python`, `flatpak`, `snap`, `appimage`, `apt`, `linux-desktop`, `zorin-os`. **Durum (16.10.2026):** Açık: uzak topics doğrulandı ve boş (`[]`); önerilen başlıklar yayımlanmadı.
- [ ] README ilk ekran: logo, tek cümlelik değer önerisi, gerçek ekran görüntüsü/GIF, Release indirme bağlantısı, distro uyumu ve CI. **Durum (16.10.2026):** Kısmi: logo/gerçek ekran/uyumluluk/CI bağlantısı var; yayınlanmış sürüm bağlantısı ve demo kabulü açık.
- [x] Sürüm yayınında otomatik SHA-256 dosyası ve anlaşılır sürüm notları.
- [ ] `v1.0.1` release sonrası GIF/video: arama → kaynak seçimi → kurulum → güncelleme → mini installer. **Durum (16.10.2026):** BLOCKED: gerçek kurulum kabulü bitmeden kurulum demosu yayınlanmadı.
- [ ] `good first issue`, `help wanted`, `bug`, `enhancement`, `documentation` etiketleri oluştur; katkı isteyen küçük görevleri açık issue yap. **Durum (16.10.2026):** NOT TESTED: uzak etiket/issue kurulumu bu turda yapılmadı.
- [ ] GitHub Discussions: Q&A, Ideas, Announcements. Issue'larla görev takibini karıştırma. **Durum (16.10.2026):** Açık: repository API `has_discussions: false`; etkinleştirme/kategori değişikliği yapılmadı.
- [ ] `docs/COMPATIBILITY.md` sayfasını görünür kıl; Linux topluluklarından gerçek testçi iste. **Durum (16.10.2026):** Kısmi: uyumluluk tablosu görünür; dış testçi çağrısı yayınlanmadı.
- [ ] Sürüm hazır olunca DEV.to teknik yazı; Reddit r/linuxapps / r/linux (kurallara uy); Show HN; yalnızca samimi ve kanıtlanabilir bilgi. **Durum (16.10.2026):** BLOCKED: yayın kabulü bitmedi; dış tanıtım yapılmadı.
- [ ] Başarı metriği: yıldızlardan önce **başarılı kurulum, sorunsuz paket işlemi, geri dönen kullanıcı, kapatılan hata ve dış katkıcı** sayısı. **Durum (16.10.2026):** Açık: benimsenme/gerçek kurulum başarısı için veri toplanmadı.
- [x] Lisans, ekran görüntüsü ve demo tamamlanmadan aşırı tanıtıma çıkma.

## 7. Önerilen uygulama sırası ve GitHub PR'leri

| Sıra | PR / branch örneği | Teslim / DoD |
|---|---|---|
| 1 | `fix/safe-portable-removal` | Güvenli silme + adversarial testler |
| 2 | `fix/archive-extraction-hardening` | Path/symlink/zip-bomb koruması + test |
| 3 | `fix/appimage-metadata-security` | Güvenli metadata akışı + kullanıcı uyarısı |
| 4 | `hardening/privileged-operations` | Sudo audit, iptal/timeout testleri, dokümantasyon |
| 5 | `ci/test-and-lint-matrix` | CI yeşil, mock entegrasyon, lint |
| 6 | `release/deb-and-docs` | GPL metni, semver, build, Release hazırlığı |
| 7 | `design/tokens-and-components` | Temalar, bileşen sistemi, erişilebilirlik |
| 8 | `ui/navigation-and-store` | Sidebar, arama, mağaza, boş/hata durumları |
| 9 | `ui/details-and-installed` | Detay/kaynak karşılaştırması, kurulu uygulamalar |
| 10 | `ui/updates-and-installer` | Güncelleme merkezi, mini-installer, progress |
| 11 | `ui/settings-help-polish` | Ayarlar, yardım, TR/EN, responsive QA |
| 12 | `docs/showcase-release` | Screenshot, demo, release, tanıtım materyalleri |

**Definition of Done (her PR için):** İlgili testler yeşil; UI değişikliğinde açık/koyu TR/EN görüntü doğrulaması; yeni strings çevrili; README/CHANGELOG güncel; regresyon yok; riskli komutlar mock ile testli; yeniden üretim ve manuel kabul adımları yazılı.

---

# 8. Codex'e verilecek ANA uygulama promptu

Aşağıdaki bloğu Codex'e **ilk olarak** ver. Tek promptla bütün uygulamayı baştan yazmasını isteme.

```text
You are acting as the lead maintainer and senior Linux desktop engineer for https://github.com/aliafacan/SourceDock.

Read CODEX_PLAN.md in full and inspect the actual repository before modifying anything. Existing code is the source of truth; the roadmap is a prioritized plan, not proof that all listed bugs exist. Preserve working functionality.

Technology: Python, GTK 3/PyGObject, modular providers (APT, DNF, Pacman, Zypper, Flatpak, Snap, AppImage, portable), Turkish and English UI. Do not migrate to GTK4/libadwaita automatically, do not rewrite from scratch and do not break the standalone mini-installer.

Start with an audit ONLY. Deliver:
1) current architecture and module responsibility map;
2) which P0 problems are confirmed by code and which require reproduction;
3) concrete tests to demonstrate the risks;
4) an ordered PR-sized execution plan with dependencies;
5) compatibility risks for Zorin OS / Ubuntu and other distributions.

Then IMPLEMENT ONLY PR #1: safe portable-app removal, including regression tests. Before every destructive operation validate managed roots, symlinks and user-owned paths. Never operate on actual installed system packages during tests. Provide a diff summary and exact tests executed. Stop after PR #1, and report clearly rather than silently continuing.

Quality requirements: least privilege, deterministic behavior, no fabricated status, readable Python, backward compatibility, TR/EN i18n, tests for dangerous edge cases. Do not claim tests ran unless they actually did.
```

# 9. Codex'e verilecek AYRINTILI UI/UX promptu

> Bu promptu **P0 güvenlik maddeleri halledildikten ve CI doğrulandıktan sonra** ayrı bir Codex oturumunda kullan. Kod öncesinde ekran planı ve tasarım sistemi çıkarsın, sonra ekran ekran uygulasın.

```text
You are a senior product designer AND senior Python GTK desktop engineer. Redesign the UI/UX of SourceDock, an open-source Linux multi-source package manager (https://github.com/aliafacan/SourceDock), without losing existing features, compatibility or performance.

FIRST READ: CODEX_PLAN.md sections 0, 1 and 4, README.md, ROADMAP.md, current sourcedock/ui/views/*, sourcedock/ui/components/*, sourcedock/ui/window.py, sourcedock/theme.py, sourcedock/i18n.py and relevant backend model interfaces.

DO NOT write code immediately. Begin with:
A) current UI audit: strengths, pain points, screen map, navigation, reuse opportunities;
B) proposed information architecture and wireframes for desktop and compact windows;
C) theme tokens, typography, spacing, icon and component specifications;
D) component-to-existing-file mapping, engineering cost and regression risks;
E) an incremental implementation plan separated into small commits.

REFERENCE REAL APPLICATIONS (analyze the layout patterns, not their exact artwork):
- GNOME Software: https://apps.gnome.org/Software/ . Learn from airy layout, useful application detail pages, screenshots, categories, installed and updates views.
- KDE Discover: https://apps.kde.org/discover/ . Learn from clear left navigation, multi-source package browsing, source management, and updates.
- Warehouse: https://github.com/flattool/warehouse . Learn from understandable advanced package/data management, batch actions and high-quality confirmation flows.
- Pamac: https://wiki.manjaro.org/index.php?title=Pamac . Learn from balancing simple software discovery with expert package-manager controls.

PRODUCT IDENTITY:
- SourceDock's visual personality is clean, confident, technically capable and friendly. Keep its source-and-dock brand identity.
- Avoid generic AI dashboard aesthetics: excessive gradients, huge rounded cards, glowing accents, meaningless counters, 01/02 section titles, oversized whitespace, repeated emoji, fake ratings and endless statistic tiles.
- Use a restrained electric-yellow accent, charcoal/neutral dark surfaces, comfortable off-white light theme and system fonts. Make accent colors meaningful, not ubiquitous. Respect system dark/light setting and provide an override.
- Preserve existing SourceDock assets where appropriate. Do not imitate GNOME/KDE assets pixel-by-pixel and do not add copyrighted mascot imagery.
- Prefer native GTK behavior and accessible controls. Keep GTK3/PyGObject; provide a separate migration feasibility memo if GTK4/libadwaita would clearly help, but do NOT migrate now.

INFORMATION ARCHITECTURE:
- Left navigation: Discover, Installed, Updates, Operations; bottom actions: Install Local File, Settings, Help.
- Header bar: active page name, global search, visible updates count (only if measured), operation status.
- Discover: search first; helpful categories; compact readable app cards; source badges; sensible loading/empty/error states; never fabricate popularity.
- Application Detail: name/icon/publisher; clear install/update/open/remove CTA; AppStream screenshots only when available; versions, size, license, package origin, permissions and alternatives from APT/Flatpak/Snap where reliably matched.
- Installed: simple app-first default and optional advanced package list; filters, search, source labels, safe uninstall and batch preview.
- Updates: unified view grouped into Applications/System/Firmware/Runtimes; actual status/progress; select update where provider supports it, safe warnings and no fictitious size estimates.
- Standalone Mini Installer: separate lightweight dialog for .deb/.rpm/.flatpakref/.AppImage/portable archives; package metadata, detected installed version, exact action (Install/Update/Reinstall/Downgrade), security warning, real progress, error and retry, final Open button only if an executable exists. Keep mini-installer fast and independent of loading full store.
- Operations: readable progress for long-running actions, detailed expandable logs, persistent enough result summary, safe cancellation semantics.
- Settings: language TR/EN live switching, System/Light/Dark, density/scale, provider-related preferences, nonintrusive help.

VISUAL SPEC:
- 8px baseline spacing: 4, 8, 12, 16, 24, 32. Moderate radius 10-14px, 1px subtle borders, no heavy shadows or neon.
- Desktop baseline at 1366x768; validate at 1024x768 and 1920x1080, plus 125% scale.
- Sidebar approximate 220-240px when expanded; adapt at narrow widths rather than clipping content.
- Cards with 48-64px app icons, 1-2 line descriptions, aligned action button. Do not force giant cards when there is little content.
- Clear typography hierarchy, high contrast (aim for WCAG AA), fully visible keyboard focus, accessible names and sensible Tab/Enter/Escape behavior.
- Buttons: one primary action per region; destructive actions clearly marked and confirmed. Differentiated hover/focus/disabled/busy states.
- Subtle 120-200ms motion where GTK supports it without stutter; honor reduced-motion settings where possible.
- Unified Gtk.CSS style token layer and reusable components; no one-off styling duplicated over all view files.

ENGINEERING REQUIREMENTS:
- Keep existing backend models and operations intact unless a minimal typed extension is necessary. Never rewrite package operations to suit mock UI.
- No fake/mock data in production. You may use controlled fixtures in tests/screenshots only, marked as such.
- GTK main thread must remain responsive during scans, downloads and operations; marshal results back safely.
- Do not make a new mega ui.py. Favor small components, clear view boundaries, and centralized theme tokens.
- Every new string must exist in Turkish and English. Reuse the existing translation mechanism or propose a safe migration separately.
- Thoroughly test error handling, slow/offline state, missing optional package providers, loading indicator, no results, no icon, very long app names and RTL feasibility.
- Preserve F1 help and all mini-installer file associations.
- Do not edit CI/release/packaging unless essential and explicitly explained.

WORKFLOW AND DELIVERABLES:
1) First produce a written audit and a proposed screenshot-level visual specification; identify real-app inspiration for each screen.
2) Implement Phase UI-1 only: design tokens + reusable common components + window shell/navigation. Do NOT change all screens at once.
3) Take real screenshots of running SourceDock in dark and light themes (Xvfb allowed); compare visual results against the specification, and iterate.
4) Execute tests and provide a file-by-file summary. Include screenshots or say honestly why capture was impossible.
5) STOP at this phase and ask for review before moving to Discover, Details, Installed, Updates and Mini Installer sequentially.

SUCCESS: SourceDock should feel like a credible daily-use native Linux application, not a web dashboard wrapped in GTK. Functional trust and clarity matter more than decorative effects.
```

## 10. UI ekranlarına özel kısa Codex devam promptları

### UI-2 — Mağaza ve uygulama detayları
```text
Proceed with UI Phase 2 only: Discover/Store and Application Detail. Follow CODEX_PLAN.md sections 4.4-4.5 and previously approved design tokens. Maintain real provider data and TR/EN translations. Implement unified source representation carefully, without guessing app identity or inventing ratings/screenshots. Test loading, offline, no-results, absent providers and long labels. Capture screenshots and report tests, then stop.
```

### UI-3 — Kurulu uygulamalar ve güncellemeler
```text
Proceed with UI Phase 3 only: Installed Applications + Unified Updates. Follow CODEX_PLAN.md sections 4.6-4.7. Ensure safe separation of user applications vs system dependencies, clear source labels, batch confirmation, firmware warnings, accurate progress and safe cancellation. Mock privileged operations in automated tests. Capture dark/light TR/EN screens, then stop.
```

### UI-4 — Mini Installer, işlemler ve son kalite
```text
Proceed with UI Phase 4 only: Standalone Mini Installer, Operations, Settings and Help. Follow CODEX_PLAN.md sections 4.8-4.10. Do not sacrifice startup speed of the standalone installer. Verify version comparison, local package security warnings, retry, success, file associations, F1 help, keyboard accessibility, dark/light themes, 1024x768 and 125% scaling. Provide before/after screenshots and test logs, then stop.
```

---

## 11. Doğrulama kontrol listesi (yayından önce)

- [ ] Yeni ve temiz Zorin kurulumunda `.deb` kurulur, açılır, çalışır ve kaldırılabilir. **Durum (16.10.2026):** BLOCKED: temiz Zorin VM kurulum/kaldırma kabulü yok.
- [ ] `.deb` kaldırma kullanıcı belgelerini veya diğer uygulamaları silmez. **Durum (16.10.2026):** BLOCKED: gerçek .deb remove/purge VM kanıtı yok.
- [ ] `.deb`, `.AppImage`, `.flatpakref` ve portable arşivler için gerçek örneklerle güvenli kurulum akışı doğrulanır. **Durum (16.10.2026):** BLOCKED: gerçek paket kurulumları disposable ortamda henüz çalıştırılmadı.
- [x] Kötü niyetli arşiv ve manipüle edilmiş portable kayıtları testlerden geçer.
- [ ] Yetki hatası veya ağ kesilmesinde kullanıcı net hata ve çözüm görür; uygulama donmaz. **Durum (16.10.2026):** Kısmi: timeout/auth/hata ve donmama regresyonları var; gerçek ağ/işlem VM kabulü açık.
- [x] Farklı provider'lar eksik olduğunda arayüz kırılmaz.
- [ ] TR/EN; dark/light; 1024×768, 1366×768, 1920×1080 testleri geçer. **Durum (16.10.2026):** Kısmi: gerçek X11 ölçümleri raporda; bütün görevlerin manuel çoklu ekran/HiDPI kabulü açık.
- [ ] `unittest`, kalite kontrolleri ve CI yeşil; sonuçlar Release notlarına yazılır. **Durum (16.10.2026):** Kısmi: yerel test/lint/derleme var; güncel çalışma ağacının uzak CI kanıtı ve Release notları yok.
- [ ] `LICENSE` tam; üçüncü taraf lisansları uygun; README gerçeği yansıtıyor. **Durum (16.10.2026):** Kısmi: tam GPL/README kalibrasyonu/bildirimler var; eksiksiz üçüncü taraf lisans denetimi açık.
- [ ] Tag, Release, indirilebilir `.deb`, checksum, destek matrisi, ekran görüntüsü ve kısa demo mevcut. **Durum (16.10.2026):** BLOCKED: onaylı tag/Release/demo ve gerçek kurulum kabulü henüz yok.
- [ ] İlk kullanıcı raporları için Issues/Discussions açık ve güvenlik bildirim kanalı net. **Durum (16.10.2026):** Kısmi: güvenlik kanalı ve yerel şablonlar var; uzak API Issues açık, Discussions kapalı gösteriyor.

## 12. Kaynaklar

- SourceDock repo: https://github.com/aliafacan/SourceDock
- GNOME Software: https://apps.gnome.org/Software/
- GNOME AppStream screenshot metadata: https://gnome.pages.gitlab.gnome.org/gnome-software/help/C/software-metadata.html
- KDE Discover: https://apps.kde.org/discover/
- Warehouse: https://github.com/flattool/warehouse
- Manjaro Pamac: https://wiki.manjaro.org/index.php?title=Pamac

**Not:** Bu referanslar tasarım ve ürün davranışı örnekleridir. Kod/kullanıcı arayüzü birebir kopyalanmamalıdır. Mevcut SourceDock deposu değişebileceğinden Codex güncel `main` durumunu her faz başında kontrol etmelidir.
