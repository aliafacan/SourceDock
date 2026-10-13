# VoltApp ⚡ — Codex Uygulama Planı, Teknik Borç ve UI/UX Tasarım Brifi

**Tarih:** 13 Ekim 2026  
**Repo:** https://github.com/aliafacan/VoltApp  
**Hedef:** Güvenli, test edilebilir, rahat kurulabilen, modern ve dağıtımlar arasında tutarlı bir Linux paket yöneticisi.  
**Hedef sürümler:** `v1.0.1` (güvenlik/kararlılık), `v1.1.0` (UI/UX ve yayınlama), `v1.2.0+` (ek özellikler).  
**Kullanım:** Bu dosyayı repo köküne `CODEX_PLAN.md` olarak koyabilir veya Codex'e doğrudan verebilirsin.

> [!IMPORTANT]
> Bu belge bir uygulama planıdır; listelenen her madde kanıtlanmış hata değildir. Başlamadan önce **mevcut kodu yeniden analiz et**, sorunları testle doğrula. Depodaki `ROADMAP.md` Aşama 1–6'nın tamamlandığını ifade eder. Bu plan bunları çöpe atmak için değil, ürünü sağlamlaştırmak ve büyütmek içindir. Gerçek kullanıcı verisine ve makinenin paket yöneticisine zarar verme ihtimali bulunan işlemler özellikle dikkatli ele alınmalıdır.

---

## 0. Codex'in uyması gereken değişmez kurallar

- [ ] `README.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `.github/workflows/ci.yml`, `packaging/build_deb.sh`, `main.py`, `voltapp/` ve `tests/` incelenmeden dosya değiştirme.
- [ ] Önce kısa durum raporu hazırla: **mevcut / eksik / riskli / doğrulanmadı**; planı güncel `main` ile eşleştir.
- [ ] Mevcut çalışan özellikleri ve TR/EN çeviri anahtarlarını koru. Eksik çevirileri tamamla; arayüzde sabit Türkçe/İngilizce metin bırakma.
- [ ] Büyük işi küçük PR/commit'lere ayır. Her aşama sonunda testleri çalıştır, sonucu raporla. Başarısız testleri saklama.
- [ ] Özellikle paket kurma, silme, yükseltme, arşiv çıkarma ve sudo gerektiren işler için **dry-run/mocked tests** kullan; CI ortamında gerçek host sistemini değiştirme.
- [ ] Root olarak GUI çalıştırma. Yetki yükseltmeyi olabildiğince dar tut. Kullanıcı parolasını loglama, diske yazma veya hata raporuna ekleme.
- [ ] Güvenilmeyen paketin kodunu yalnızca ikon/metadata okumak için çalıştırma. `shell=True`, kontrolsüz `rm -rf`/`rmtree`, string birleştirmeli shell komutları kullanma.
- [ ] `GTK 3 / PyGObject` mevcut teknik temel; UI yenilemesinde önce onunla yapılabilecekleri değerlendir. **GTK4/libadwaita'ya otomatik geçiş yapma**; maliyet/uyumluluk raporunu ayrı hazırla.
- [ ] İzin vermeden kullanıcıdaki kurulu uygulamaları kaldırma, sistem paketlerini değiştirme, kurulu depoları manipüle etme veya mevcut çalışma dizinlerini temizleme.
- [ ] Kullanıcıyı yanıltan göstergeler oluşturma: sahte derecelendirme, uydurma indirme sayısı, sahte güncelleme güvenliği, doğrulanmamış 'tested on' etiketleri yasak.
- [ ] Her faz sonunda: değişen dosyalar, test komutları ve sonuçları, manuel test adımları, bilinen sınırlamalar, sonraki faz bağımlılıkları.

## 1. Mevcut proje envanteri (inceleme sırasında gözlenen)

- [x] GTK 3 + Python tabanlı modüler UI (`voltapp/ui/views`, `voltapp/ui/components`, `voltapp/ui/window.py`).
- [x] Native backends: APT, DNF, Pacman, Zypper; ek kaynaklar Flatpak, Snap, AppImage, portable ve firmware.
- [x] TR/EN i18n, tema, mini paket kurucu, kurulu uygulamalar, mağaza, işlemler, ayarlar ve yardım ekranı.
- [x] `tests/` altında birim testleri ve GitHub Actions CI yapılandırması.
- [x] `packaging/voltapp_1.0.0_all.deb` ve derleme betiği.
- [x] `CONTRIBUTING.md`, issue/PR şablonları, `ROADMAP.md`.
- [ ] **GitHub Release** yoktu (13.10.2026 incelemesi); yeniden doğrula.
- [ ] Repository **topics** boştu; yeniden doğrula.
- [ ] README'de gerçek arayüz ekran görüntüleri ve gösterim GIF'i yoktu.
- [ ] `LICENSE` dosyasındaki GPLv3 metni kısaltılmıştı: tam, değişmemiş GPLv3 metniyle düzelt.
- [ ] CI'nin farklı dağıtım ve Python/GTK kombinasyonlarında gerçekten geçtiğini doğrulamak gerekiyor.

## 2. P0 — Güvenlik ve veri koruma (v1.0.1'den önce)

### P0.1 Portable kaldırmada güvenli yol doğrulaması
**İlgili dosya:** `voltapp/backend/portable.py`

- [ ] `PortableProvider.remove()` içindeki `shutil.rmtree(application.install_path, ignore_errors=True)` yolunu gözden geçir.
- [ ] Sadece **VoltApp tarafından yönetildiği kanıtlanan** uygulama dizinlerini sil; path'in yönetilen kök altında olduğunu `Path.resolve()` ve `relative_to()` ile doğrula. Sembolik bağları ve `..` geçişlerini reddet.
- [ ] Kullanıcının seçtiği özel konuma kurulum destekleniyorsa, güvenli sahiplik kaydı/manifest olmadan asla otomatik dizin silme.
- [ ] Desktop dosyası silme için de kullanıcı uygulama dizini ve VoltApp'ın oluşturduğu kayıt kontrolü yap.
- [ ] `ignore_errors=True` yerine kullanıcıya anlaşılır hata raporu, başarısızsa kaydı silmeme ve geri denenebilir durum kullan.
- [ ] Registre edilmiş sahte `/home/user/Documents`, symlink, bozuk kayıt, eksik dosya ve başarılı kaldırma testlerini ekle.

**Kabul kriteri:** Manipüle edilmiş registry kaydıyla VoltApp tarafından yönetilmeyen herhangi bir dizin silinemez.

### P0.2 Arşiv çıkarma: Zip Slip, symlink, tar filter, zip bomb
**İlgili dosya:** `voltapp/backend/local_packages.py`

- [ ] `_safe_extract_archive` içindeki `str(target).startswith(str(dest_resolved))` kontrolünü dizin bazlı `relative_to()` doğrulamasıyla değiştir.
- [ ] `tar` için link, hardlink, device/special file, mutlak yol, `../`, mevcut symlink zincirleri ve izinleri güvenlik açısından ele al.
- [ ] Eski Python sürümlerinde `tarfile` filtre davranışına güvenme: ya güvenli özel doğrulama uygula ya desteklenen minimum sürümü güncelle.
- [ ] ZIP dosyalarında symlink girişlerini ve yazma sırasındaki symlink yarışlarını ele al.
- [ ] Maksimum toplam açılmış veri, dosya adedi, dosya başına sınır ve isteğe bağlı boyut oranı koruması uygula.
- [ ] Açma işlemini rastgele sistem konumuna değil, güvenli geçici dizine yap. Doğrulama sonrası hedefe atomik/geçişi güvenli taşı.
- [ ] İşlem başarısızsa eski kurulumun korunacağını garanti et; kısmen açılmış içeriği temizle.
- [ ] Güvenlik regresyon testleri: `app/../evil`, `apps-copy/evil`, absolute path, symlink escape, nested tar symlink, zip bomb simülasyonu.

**Kabul kriteri:** Kötü niyetli arşiv hedef dışına tek dosya dahi yazamaz; önceki kurulum hata sonrasında korunur.

### P0.3 AppImage metadata ayrıştırma güvenliği
**İlgili dosya:** `voltapp/backend/local_packages.py`

- [ ] `_extract_appimage_icon_and_info()` içindeki `[file_path, '--appimage-extract', ...]` çağrılarının güvenlik riskini doğrula.
- [ ] Metadata okumada dosyanın executable kodunu çalıştırmayan güvenli ayrıştırıcı seçenekleri araştır; mümkün değilse açık güven onayı + izole yardımcı işlem + sağlam uyarı kullan.
- [ ] Dosyaya `chmod +x` uygulamadan önce kullanıcıya davranışı açıkça göster ve yalnızca gerekli anda uygula.
- [ ] Güvenilmeyen AppImage üzerinde metadata görüntülemenin beklenmedik kod yürütmediğini test et.

### P0.4 Sudo, yetki sınırı ve işlem iptali
**İlgili dosya:** `voltapp/core/runner.py`, ilgili UI diyaloğu

- [ ] `set_sudo_password()` / `sudo -S` akışındaki kimlik bilgisi ömrünü gözden geçir: yalnızca geçici bellek, temizleme, hata/iptalde temizleme.
- [ ] `polkit`/`pkexec` veya sistemin desteklediği yetkilendirme mekanizması için mimari öneri ve küçük proof-of-concept hazırla; güvenli olmayan acele geçiş yapma.
- [ ] Hata loglarında komut argümanlarının gizli veri içerip içermediğini kontrol et; redaksiyon ekle.
- [ ] `_run_streaming()` için mutlak zaman aşımı ve iptal davranışını sınır durumlarında test et (çıkış üretmeyen proses, child process, bloke stdout, SIGTERM'e direnme).
- [ ] APT/DPKG sırasında zorla iptalin paket veritabanını bozma riskini UI'da belirt. Kritik işlemlerde güvenli iptal davranışı tasarla.
- [ ] Aynı kaynağa yönelik eşzamanlı kur/kaldır/güncelle işlemlerini serileştir.

### P0.5 Paket kaynağı ve güven göstergeleri

- [ ] Yerel `.deb`/`.rpm`/`.AppImage`/arşiv kurulumunda **kaynak, yayıncı (biliniyorsa), imza/doğrulama durumu, yetki seviyesi** göster.
- [ ] “Güvenli” rozeti yalnızca gerçekten doğrulanan bir mekanizma varsa göster; aksi halde “Doğrulanmadı”.
- [ ] Snap classic gibi geniş izinleri anlaşılır, manipülasyonsuz anlat ve kullanıcı onayını koru.
- [ ] Paket kurulumu yapılmadan önce etkilenecek bağımlılıkların ve olası kaldırmaların önizlemesini sun (backend destekliyorsa).

## 3. P1 — Test, CI, dağıtım ve bakım (v1.0.1 / v1.1.0)

### P1.1 Tekrarlanabilir test sistemi

- [ ] Testleri birim, entegrasyon (mock/fake CLI) ve manuel dağıtım smoke test olarak ayır.
- [ ] APT, DNF, Pacman, Zypper, Flatpak, Snap için komut çıktısı fixture'ları ve hata senaryoları oluştur.
- [ ] Veri/parsing testleri: farklı locale çıktıları, sürüm karşılaştırması, boş metadata, bağlantı kesintisi, yetki reddi, bozuk paket, depo erişilemezliği.
- [ ] İşlem kuyrukları, ilerleme, iptal, geri dönme ve UI thread donmaması için test ekle.
- [ ] GUI smoke testlerini `Xvfb` altında çalıştır; gerektiğinde ekran görüntüsüyle manuel doğrulama raporu üret.
- [ ] `ruff`, uygun formatter, isteğe bağlı tip denetimi ve güvenlik taraması ekle; kural setini mevcut koda göre aşamalı uygula.
- [ ] CI Python yorumlayıcısı ile sistem `python3-gi` modülünün uyumunu doğrula. Özel `setup-python` ile yanlış interpreter seçimi olursa matrix stratejisini düzelt.
- [ ] CI'da repo üzerinde test yapılırken host paket yöneticisini çağırmadığını garanti et.
- [ ] CI başarısızlığında kırmızı badge'i gizleme; düzelt.

### P1.2 Gerçek dağıtım destek matrisi

- [ ] Öncelik: Zorin OS (gerçek makine), Ubuntu LTS, Debian stable.
- [ ] Sonra VM/container uygunluğuna göre Fedora, openSUSE, Arch/Manjaro.
- [ ] Her ortam için **başlatma, katalog, arama, kurulu uygulamalar, dry-run/izole kurulum, güncelleme bilgisi, kaldırma, MIME/çift tık, TR/EN, dark/light, HiDPI** testlerini kaydet.
- [ ] En az bir gerçek makinede Flatpak/Snap yokken davranışı doğrula.
- [ ] Destek tablosunu `docs/COMPATIBILITY.md` olarak yayınla: **Tested / Experimental / Not tested / Unsupported**.
- [ ] `Architecture: all` paketinin Python kodu açısından doğru olduğunu, ancak bağımlılık ve Debian aile sınırlarını belgede açık yaz.

### P1.3 Paketleme ve sürümleme

- [x] `packaging/build_deb.sh` içindeki hardcoded `VERSION=1.0.0` değerini tek sürüm kaynağına bağla (`voltapp/constants.py`).
- [ ] Build çıktısını kalıcı `packaging/` içinde commit etmek yerine release artifact olarak yönetmeyi değerlendir; mevcut kullanıcılar için geçişi açıklığa kavuştur.
- [ ] `dpkg-deb --build` sonrasında `lintian` benzeri kalite kontrolleri (mevcutsa) çalıştır.
- [ ] İkon/MIME/Desktop Entry doğrulaması: `desktop-file-validate`, `appstreamcli validate`, uygun MIME testleri.
- [ ] Bağımlılıklar ile README'de beyan edilen minimum Python/Ubuntu sürümlerini tutarlı hale getir.
- [ ] `install.sh` ve `uninstall.sh` işlemlerinin `.deb` ile kurulan dosyalara zarar vermediğini doğrula; iki yöntemin birlikte kullanım stratejisini tanımla.
- [ ] **Debian ailesi için yayınla; diğer dağıtımlar için aynı `.deb`'i evrensel çözüm diye sunma.** `rpm`/PKGBUILD/Flatpak paketleme daha sonra ayrı testli iş olabilir.
- [ ] GitHub Actions ile tag bazlı build, test, SHA-256 ve **taslak release** oluşturma akışı kur (yayın kararı onayla).

### P1.4 Lisans ve dokümantasyon

- [ ] Tam GPL-3.0 lisans metnini `LICENSE` içine ekle; GitHub'ın tanıdığını doğrula.
- [ ] Tüm üçüncü taraf asset, icon, bağımlılık ve lisansları kontrol et; gerekirse `THIRD_PARTY_NOTICES.md`.
- [ ] `README.md` içinde **Install → Screenshot → Features → Supported distros → FAQ → Contribute** sırası oluştur.
- [ ] README'deki aşırı kesin iddiaları (“universal”, “blazing-fast”, “full support”) test durumuna göre kalibre et.
- [ ] `SECURITY.md`: güvenlik bildirimi yöntemi, kapsam ve yanıt ilkeleri.
- [ ] `CHANGELOG.md`, `docs/TROUBLESHOOTING.md`, `docs/ARCHITECTURE.md`, `docs/COMPATIBILITY.md`.
- [ ] PR/issue şablonlarına dağıtım/sürüm, Python/GTK, backend, hata logu (kişisel veri redakte edilmiş) ve tekrar adımları ekle.

## 4. P1 — UI/UX yeniden tasarım (v1.1.0)

> **Özel kural:** Kullanıcı deneyimini yeniden tasarla, yalnızca renkleri değiştirme. Ama tek seferde tüm iş mantığını değiştirme. Önce tasarım sistemi, sonra ekran ekran güvenli entegrasyon. Tasarımda mevcut VoltApp'ın yıldırım/elektrik kimliğini koru; Pikachu/telifli karakter görsellerini marka öğesi olarak kullanma.

### 4.1 Gerçek uygulama referansları

1. **GNOME Software** — https://apps.gnome.org/Software/  
   Referans: ferah ve az gürültülü ana sayfa; kategoriler; uygulama detay ekranı; ekran görüntüsü galerisi; kurulu/güncelleme ekranları. **Ödünç alınacak:** içerik hiyerarşisi ve sakin bilgi sunumu. **Kopyalanmayacak:** logo, ikonlar, piksel düzeni.
2. **KDE Discover** — https://apps.kde.org/discover/  
   Referans: solda kalıcı gezinme, uygulama arama, kaynaklar ve güncellemeleri yönetme. **Ödünç alınacak:** çok kaynaklı katalog mimarisi ve gezinme; **kopyalanmayacak:** KDE görsel kimliği.
3. **Warehouse** — https://github.com/flattool/warehouse  
   Referans: Flatpak ayrıntı, veri temizleme, toplu eylemler, depo yönetimi. **Ödünç alınacak:** gelişmiş ayarları basit açıklamalarla gösterme, riskli işlemleri açık onaya bağlama.
4. **Pamac** — https://wiki.manjaro.org/index.php?title=Pamac  
   Referans: paket yöneticisi ile yazılım mağazası arasında dengeli kullanım; arama, kurulu uygulamalar, gelişmiş paket detayı. **Ödünç alınacak:** acemi ve deneyimli kullanıcıya farklı ayrıntı seviyesi.

**Özgün VoltApp yönü:** Tek ekranda uygulamanın alternatif kaynaklarını karşılaştırma (`APT / Flatpak / Snap`), yerel dosya için odaklı **mini installer**, güvenli toplu işlemler ve kaynağın ne anlama geldiğini kullanıcı dilinde açıklama.

### 4.2 Görsel kimlik ve tasarım sistemi

- [ ] Koyu tema: koyu kömür/lacivert tonlarında nötr yüzey; beyaz yerine yumuşak açık metin; elektrik sarısı **yalnızca vurgu ve işlem durumu**. Koyu arayüzü neon reklam panosuna çevirme.
- [ ] Açık tema: sıcak/nötr beyaz yüzey, çok hafif sınır çizgileri, okunaklı koyu metin, aynı vurgu semantiği.
- [ ] Font: sistem fontu (GNOME'da Cantarell/Adwaita uyumu dahil), sistem fallback; ekstra font yüklemesi gerektirme.
- [ ] Spacing sistemi: 4/8/12/16/24/32; kart köşe yarıçapları 10–14 px; düzenli hizalama.
- [ ] Kontrast: normal metin için WCAG AA'ya hedefle; bilgi yalnızca renkle ifade edilmesin.
- [ ] İkonlar: GTK/Adwaita sembolik ikonları ve mevcut özgün VoltApp ikonu; anlam tutarlılığı. Emoji ile ikon ikamesi yapma.
- [ ] Hareket: 120–200 ms yumuşak geçişler, sistem reduced-motion tercihine saygı.
- [ ] Uygun ekranlar: 1024×768, 1366×768, 1920×1080 ve HiDPI; minimum pencere genişliği/scroll davranışı.
- [ ] GTK CSS token katmanı oluştur: background/surface/surface-hover/border/text-muted/accent/success/warning/danger/focus.
- [ ] `voltapp/theme.py` ve `voltapp/ui/components` parçalarını yeniden kullanılabilir bileşenlere ayır.

### 4.3 Bilgi mimarisi ve genel pencere

- [ ] **Sol yan çubuk**: Keşfet, Kurulu, Güncellemeler, İşlemler; alt bölüm: Yerel Paket Kur, Ayarlar, Yardım.
- [ ] **Üst bar**: aktif sayfa başlığı, global arama (`Ctrl+K` veya `Ctrl+F`), güncelleme sayacı, işlem durum düğmesi, gerektiğinde kaynak filtresi.
- [ ] 1100 px altında yan çubuğu daralt veya uyumlu hale getir. Pencere küçükken düğmeler kaybolmasın.
- [ ] Global boş/yükleniyor/hata durumları; ortak toast/snackbar; keyboard focus ve ekran okuyucu açıklamaları.
- [ ] Verisi henüz gelmeyen kartlarda skeleton veya sakin spinner; kilitlenmiş gibi görünmesin.
- [ ] Uzun ağ/bekleme işlemleri GTK main thread'i bloklamasın. Biten veri UI thread'inde güncellensin.

### 4.4 Keşfet / Mağaza ekranı

- [ ] Üstte anlamlı arama alanı, kategori çipleri (Üretkenlik, Geliştirme, İnternet, Grafik, Sistem vb.).
- [ ] Tek büyük promosyon görseli yerine isteğe bağlı sade **öne çıkan uygulamalar** alanı; doğrulanmış veri yoksa sahte popülerlik bilgisi gösterme.
- [ ] Grid kartında: gerçek ikon, isim, kısa açıklama, kaynaklar, kurulu/güncelleme durumu ve tek net eylem.
- [ ] Aynı uygulamanın farklı kaynaklarını mümkünse **birleştirilmiş görünümde** sun; aynı uygulamaları anlaşılmaz tekrarlarla listeleme.
- [ ] Filtreler: kaynak, kurulu, kategori, istemci mimarisi (veri destekliyorsa). Sıralama net ve açıklanabilir olsun.
- [ ] Arama sonucu yok, repo çevrimdışı, Flatpak kurulu değil, yetki yok gibi durumlara ayrı mesaj ve çözüm bağlantısı.

### 4.5 Uygulama detay sayfası

- [ ] Başlık: ikon, ad, doğrulanabilen yayıncı, kısa açıklama, kur/kaldır/güncelle/aç.
- [ ] Kaynak seçici: APT / Flatpak / Snap / diğer; sürüm, boyut, sandbox, kaynak ve izin karşılaştırması.
- [ ] Açıklama; ekran görüntüsü galerisi (AppStream metadata varsa); sürüm, homepage, lisans, yüklü boyut, değişiklikler.
- [ ] Güvenlik paneli: **Kaynak doğrulanmış / doğrulanmadı / bilinmiyor**, sandbox/izinler; kaynaklar arasında tarafsız rehber.
- [ ] Metadata yoksa sahte ekran görüntüsü/yorum/derecelendirme uydurma.
- [ ] Kurulum sırasında 'iptal' düğmesinin gerçek güvenli davranışını açıkça belirt.

### 4.6 Kurulu uygulamalar

- [ ] Masaüstü uygulamaları ile çekirdek/sistem bağımlılıklarını ayır; varsayılan görünüm acemi kullanıcıyı paket kalabalığına boğmasın.
- [ ] Arama, kaynak filtreleri, isteğe bağlı ayrıntı tablosu, liste/grid geçişi.
- [ ] Toplu kaldırma için seçim, toplam sayı ve net onay; sistem açısından hassas paketlerde ekstra doğrulama.
- [ ] Uygulamayı Aç, Dosyayı Göster, Ayrıntılar, Güncelle, Kaldır eylemleri gerçek backend desteğine göre koşullu gösterilsin.
- [ ] Kaldırma sırasında kullanıcı verisi siliniyorsa bundan ayrıca bahset; varsayılan olarak silme.

### 4.7 Güncellemeler merkezi

- [ ] APT/DNF/Pacman/Zypper, Flatpak, Snap, firmware, runtime öğelerini **kaynak etiketleriyle** tek listede sun.
- [ ] Gruplar: Uygulamalar / Sistem / Firmware / Çalışma Ortamları; toplam sayı ve yalnızca doğru ölçülmüş indirme boyutunu göster.
- [ ] Seçerek güncelle, hepsini güncelle (uygunsa), yeniden kontrol et, değişiklik notları.
- [ ] Yeniden başlatma gerektiriyorsa tespit et ve işlemler sonrasında öner; kesin değilse kesin ifade kullanma.
- [ ] Firmware/dbx güncellemelerinde özel onay, güç/cihaz uyarıları ve üretici kaynak bilgisi.
- [ ] Güncelleme hatalarında çalışan öğeleri koru, başarısız öğeleri açık raporla.

### 4.8 Mini Installer: VoltApp'ın ayırt edici özelliği

- [ ] Dosya çift tıklanınca ana mağazayı yüklemeden **hızlı, küçük, odaklı** pencere aç.
- [ ] Dosya adı, format, boyut, algılanan paket adı, kurulu sürüm, kurulacak sürüm, kaynak yolu, mimari göster.
- [ ] Eylemler: Yeni Kur / Güncelle / Yeniden Kur / Sürüm Düşür / Aç veya İptal; yalnızca mantıksal olarak mümkün olanları göster.
- [ ] Sürüm düşürme ve şüpheli paket için belirgin ama bağırmayan uyarı.
- [ ] Kurulum aşamasında aynı pencere içinde gerçek ilerleme, ayrıntı açılır bölümü ve başarısızlıkta yeniden dene.
- [ ] Başarılıysa 'Uygulamayı Aç', 'Kapat', isteğe bağlı 'Ayrıntılar'.
- [ ] Ekran okuyucu, klavye, uzun dosya adı, TR/EN ve küçük ekran testleri.

### 4.9 İşlemler, ayarlar, yardım

- [ ] İşlemler ekranında her işi **hazırlanıyor → indiriliyor → kuruluyor → tamamlandı/başarısız** şeklinde doğru durumla göster.
- [ ] İşlem geçmişi: saat, işlem, kaynak, sonuç; maskeleme ve kullanıcı kontrollü temizleme.
- [ ] Ayarlar: Tema (Sistem/Açık/Koyu), dil (TR/EN), arayüz yoğunluğu/ölçek, kaynak tercihleri, güncelleme kontrolü.
- [ ] Riskli deneysel ayarlar 'Gelişmiş' bölümünde tutulmalı; varsayılanlar güvenli olmalı.
- [ ] F1 yardım mevcut; yeni ekran isimleri ve tooltip'lere göre güncelle, bağlama duyarlı yardım ekle.

### 4.10 Erişilebilirlik ve kalite kontrol

- [ ] Tab sırası, odak halkası, ekran okuyucu isimleri, ESC/Enter davranışları.
- [ ] Türkçe uzun kelime ve İngilizce metin taşmaları; 90/100/110/125% ölçekte kontrol.
- [ ] Koyu/açık tema; klavye ile tüm ana görevler; minimum pencere boyutu.
- [ ] Gerçek veri ile ekran görüntüleri: ana sayfa, detay, kurulu, güncelleme, mini-installer, ayarlar.
- [ ] UI performansı: 1.000+ uygulama kaydıyla scroll, arama ve filtreyi ölç; makul hedef belirle ve raporla.

## 5. P2 — Kullanıcı açısından değerli yeni özellikler (v1.2+)

- [ ] **Kurulu uygulama listesini dışa aktar / içe aktar:** kaynak türü, paket kimliği, sürüm (bilgi amaçlı), hedef dağıtım uyumluluğu; geri yükleme önce simülasyon/önizleme.
- [ ] **Tek uygulama, farklı kaynaklar:** benzer eşleme hataları için açık kullanıcı kontrolü; yanlış eşleşme olmadan APT/Flatpak/Snap kıyaslaması.
- [ ] **Paket kaynak yöneticisi:** Flatpak remote, Snap kanalı, native repo bilgilerinin güvenli gösterimi; değiştirme ayrı onayla.
- [ ] **Gereksiz/verisiz paket temizliği:** yalnızca sistem sağlayıcısının güvenli tahminiyle; neyin silineceği önce listelensin.
- [ ] **İşlem geçmişi dışa aktarma:** kullanıcı adı/ev dizini ve parola gibi bilgileri redakte ederek.
- [ ] **Bildirim alanı:** arka planda güvenli kontrol / sistem bildirimleri, gereksiz sürekli arka plan servisi olmadan.
- [ ] **Güncelleme öncesi snapshot entegrasyonu:** Timeshift/Btrfs varlığı ve uygun yetki kontrolü; desteklenmeyende pasif.
- [ ] **AppImage update deneyimi:** yalnızca doğrulanmış update metadata varsa; AppImageUpdate bağımlılığı açıklansın.
- [ ] **İsteğe bağlı otomatik tema ve sistem vurgu uyumu.**
- [ ] **Yeni yerelleştirmeler:** gettext/Weblate benzeri katkı akışı (mevcut sözlük yapısını dikkate al).

## 6. GitHub görünürlüğü ve topluluk (P1/P2)

- [ ] Repo topics: `linux`, `package-manager`, `gtk3`, `python`, `flatpak`, `snap`, `appimage`, `apt`, `linux-desktop`, `zorin-os`.
- [ ] README ilk ekran: logo, tek cümlelik değer önerisi, gerçek ekran görüntüsü/GIF, Release indirme bağlantısı, distro uyumu ve CI.
- [ ] Sürüm yayınında otomatik SHA-256 dosyası ve anlaşılır sürüm notları.
- [ ] `v1.0.1` release sonrası GIF/video: arama → kaynak seçimi → kurulum → güncelleme → mini installer.
- [ ] `good first issue`, `help wanted`, `bug`, `enhancement`, `documentation` etiketleri oluştur; katkı isteyen küçük görevleri açık issue yap.
- [ ] GitHub Discussions: Q&A, Ideas, Announcements. Issue'larla görev takibini karıştırma.
- [ ] `docs/COMPATIBILITY.md` sayfasını görünür kıl; Linux topluluklarından gerçek testçi iste.
- [ ] Sürüm hazır olunca DEV.to teknik yazı; Reddit r/linuxapps / r/linux (kurallara uy); Show HN; yalnızca samimi ve kanıtlanabilir bilgi.
- [ ] Başarı metriği: yıldızlardan önce **başarılı kurulum, sorunsuz paket işlemi, geri dönen kullanıcı, kapatılan hata ve dış katkıcı** sayısı.
- [ ] Lisans, ekran görüntüsü ve demo tamamlanmadan aşırı tanıtıma çıkma.

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
You are acting as the lead maintainer and senior Linux desktop engineer for https://github.com/aliafacan/VoltApp.

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
You are a senior product designer AND senior Python GTK desktop engineer. Redesign the UI/UX of VoltApp, an open-source Linux multi-source package manager (https://github.com/aliafacan/VoltApp), without losing existing features, compatibility or performance.

FIRST READ: CODEX_PLAN.md sections 0, 1 and 4, README.md, ROADMAP.md, current voltapp/ui/views/*, voltapp/ui/components/*, voltapp/ui/window.py, voltapp/theme.py, voltapp/i18n.py and relevant backend model interfaces.

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
- VoltApp's visual personality is clean, confident, fast, technically capable and friendly. Keep its original lightning/voltage brand identity.
- Avoid generic AI dashboard aesthetics: excessive gradients, huge rounded cards, glowing accents, meaningless counters, 01/02 section titles, oversized whitespace, repeated emoji, fake ratings and endless statistic tiles.
- Use a restrained electric-yellow accent, charcoal/neutral dark surfaces, comfortable off-white light theme and system fonts. Make accent colors meaningful, not ubiquitous. Respect system dark/light setting and provide an override.
- Preserve existing VoltApp assets where appropriate. Do not imitate GNOME/KDE assets pixel-by-pixel and do not add copyrighted mascot imagery.
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
3) Take real screenshots of running VoltApp in dark and light themes (Xvfb allowed); compare visual results against the specification, and iterate.
4) Execute tests and provide a file-by-file summary. Include screenshots or say honestly why capture was impossible.
5) STOP at this phase and ask for review before moving to Discover, Details, Installed, Updates and Mini Installer sequentially.

SUCCESS: VoltApp should feel like a credible daily-use native Linux application, not a web dashboard wrapped in GTK. Functional trust and clarity matter more than decorative effects.
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

- [ ] Yeni ve temiz Zorin kurulumunda `.deb` kurulur, açılır, çalışır ve kaldırılabilir.
- [ ] `.deb` kaldırma kullanıcı belgelerini veya diğer uygulamaları silmez.
- [ ] `.deb`, `.AppImage`, `.flatpakref` ve portable arşivler için gerçek örneklerle güvenli kurulum akışı doğrulanır.
- [ ] Kötü niyetli arşiv ve manipüle edilmiş portable kayıtları testlerden geçer.
- [ ] Yetki hatası veya ağ kesilmesinde kullanıcı net hata ve çözüm görür; uygulama donmaz.
- [ ] Farklı provider'lar eksik olduğunda arayüz kırılmaz.
- [ ] TR/EN; dark/light; 1024×768, 1366×768, 1920×1080 testleri geçer.
- [ ] `unittest`, kalite kontrolleri ve CI yeşil; sonuçlar Release notlarına yazılır.
- [ ] `LICENSE` tam; üçüncü taraf lisansları uygun; README gerçeği yansıtıyor.
- [ ] Tag, Release, indirilebilir `.deb`, checksum, destek matrisi, ekran görüntüsü ve kısa demo mevcut.
- [ ] İlk kullanıcı raporları için Issues/Discussions açık ve güvenlik bildirim kanalı net.

## 12. Kaynaklar

- VoltApp repo: https://github.com/aliafacan/VoltApp
- GNOME Software: https://apps.gnome.org/Software/
- GNOME AppStream screenshot metadata: https://gnome.pages.gitlab.gnome.org/gnome-software/help/C/software-metadata.html
- KDE Discover: https://apps.kde.org/discover/
- Warehouse: https://github.com/flattool/warehouse
- Manjaro Pamac: https://wiki.manjaro.org/index.php?title=Pamac

**Not:** Bu referanslar tasarım ve ürün davranışı örnekleridir. Kod/kullanıcı arayüzü birebir kopyalanmamalıdır. Mevcut VoltApp deposu değişebileceğinden Codex güncel `main` durumunu her faz başında kontrol etmelidir.
