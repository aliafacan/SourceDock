# ⚡ SourceDock — Roadmap & Yapılacaklar Listesi

> *SourceDock, farklı Linux yazılım kaynaklarını anlaşılır ve güvenli bir masaüstü deneyiminde birleştirme amacıyla geliştirilir.*

---

## 📌 Durum Özeti & İlerleme Tablosu

| Aşama | Konu | Durum |
| :--- | :--- | :--- |
| **Aşama 1** | Snap `--classic` Hatasının Giderilmesi | ✅ Tamamlandı |
| **Aşama 2** | Modüler Mimari & Dosya Bölme & Markalama | ✅ Tamamlandı |
| **Aşama 3** | Çoklu Dil & Yerelleştirme (i18n) Temizliği | ✅ Tamamlandı |
| **Aşama 4** | Yeni Paket Formatları (.deb, .AppImage, .tar.gz, vb.) | ✅ Tamamlandı |
| **Aşama 5** | Dağıtımdan Bağımsız (Distro-Agnostic) Mimari | ✅ Tamamlandı |
| **Aşama 6** | Açık Kaynak Hazırlığı & Paketleme (.deb, CI/CD, Docs) | ✅ Tamamlandı |
| **Aşama 7** | Güvenlik, İşlem Kilitleri ve Kararlılık (1.3.0 RC1) | ✅ Tamamlandı |
| **Aşama 8** | Genişletilmiş Dağıtım ve Masaüstü Entegrasyonu | 📋 Planlandı |

---

> 📐 **Kalıcı Mimari Kuralımız:**  
> Hiçbir dosya gereksiz yere şişirilmeyecek (spagetti koda izin verilmeyecek). Büyük bileşenler (`ui.py`, `applications.py`, vb.) tek bir dev dosyada tutulmak yerine `core/`, `backend/`, `ui/views/`, `ui/components/` gibi işlevsel alt modüllere bölünecek.

---

## 🎯 Aşama 1: Kritik Hata Çözümü (Snap `--classic` Desteği)
- [x] **1.1. Snap `--classic` İhtiyacını Algılama**
  - `sourcedock/store/registry.py` içindeki streaming runner'da "classic confinement" ve "--classic" çıktıları anında yakalanıp `SnapClassicRequiredError` fırlatılıyor.
- [x] **1.2. Kullanıcı Güvenlik Onay Penceresi**
  - UI'da kullanıcıya dostça ve açıklayıcı bir uyarı diyaloğu (`store_snap_classic_title` / `store_snap_classic_message`) gösterilerek tam sistem erişimi izni soruluyor.
- [x] **1.3. `--classic` Bayrağı ile Kurulumu Gerçekleştirme**
  - Kullanıcı onay verdiğinde komut `snap install --classic <paket>` şeklinde otomatik yeniden çalıştırılıp kurulum başarıyla tamamlanıyor.

---

## 🏗️ Aşama 2: Modüler Mimari & Markalama (SourceDock)
- [x] **2.1. Kod Bölme (Clean Architecture)**
  - 3764 satırlık devasa `ui.py` ve 1402 satırlık `applications.py` paketlere bölündü (`sourcedock/core/`, `sourcedock/backend/`, `sourcedock/store/`, `sourcedock/ui/views/`, `sourcedock/ui/components/`).
  - `main.py`Giriş noktası  sadeleştirildi ve Snap ortam sızıntılarını önleyen temizleme mantığı eklendi.
- [x] **2.2. Yeniden Markalama & Logo**
  - Kaynak düğümlerini tek bir dock üzerinde birleştiren özgün vektörel logo (`assets/sourcedock.svg`, PNG türevleri) oluşturuldu ve pencere ikonu olarak bağlandı.
  - GPL-3.0 Lisansı ve çift dilli `README.md` hazırlandı, GitHub reposuna pushlandı.

---

## 🌍 Aşama 3: Tam Dil ve Çeviri Entegrasyonu (i18n / Yerelleştirme)
- [x] **3.1. İlerleme ve İndirme Pencerelerinin Yerelleştirilmesi**
  - `OperationProgressWindow` bileşenindeki hazırlık, indirme, kurulum, APT kilidi, DPKG uyarıları ve tamamlama metinleri TR/EN dinamik `t(lang, ...)` yapısına bağlandı.
  - İndirme boyut ve paket sayaçları çok dilli olarak formatlandı.
- [x] **3.2. Arayüzdeki (UI) Hardcoded Metinlerin Temizlenmesi**
  - İşlemler (Operations) sekmesi başlıkları, PID/İşlem sütunları, Duraklat/İptal butonları yerelleştirildi.
  - Toplu kaldırma, AppImage ekleme, Flatpak izinleri, sürüm geri alma ve changelog diyalogları tamamen TR ve EN anahtarlarıyla bağlandı.
- [x] **3.3. Dinamik Dil Senkronizasyonu**
  - Ayarlardan dil değiştirildiğinde hem ana sekmelerin hem de alt bileşenlerin anında güncellenmesi (`_refresh_texts`) sağlandı.

---

## 📦 Aşama 4: Yeni Paket Formatları ve Yerel Kurulum Desteği
- [x] **4.1. `.deb` Paket Kurulumu & Yönetimi**
  - Kullanıcının yerel `.deb` dosyasını seçebilmesi (`apt install ./dosya.deb` veya `dpkg -i`).
  - Paket metaverilerini (ad, sürüm, açıklama, bağımlılıklar, mimari, boyut) önizleme ekranı (`PackageInstallerDialog`).
- [x] **4.2. `.AppImage` Entegrasyonu**
  - İndirilen `.AppImage` dosyalarına çalıştırma izni (`chmod +x`) verme.
  - Uygulamayı standart konuma (`~/Applications`) taşıma/kopyalama seçeneği.
  - Masaüstü kısayolu (`.desktop` dosyası ve menü ikonu) otomatik oluşturma ve entegrasyonu.
- [x] **4.3. `.tar.gz` / `.tar.xz` / `.zip` Taşınabilir (Portable) Yazılımlar**
  - Arşivleri güvenli bir dizine açma (`~/.local/share/sourcedock/apps/<uygulama>`).
  - Çalıştırılabilir ana dosyayı tespit edip uygulama menüsüne `.desktop` kısayolu ekleme.
  - `PortableProvider` ile yüklü uygulamalar listesinde görünme, çalıştırma ve temiz kaldırma desteği.
- [x] **4.4. Diğer Dağıtımlar ve Paketler**
  - Fedora/RHEL için `.rpm` desteği (`dnf install ./paket.rpm` ve metaveri inceleme).
  - `.flatpak` ve `.flatpakref` dosyalarını GUI'dan tek tıkla kurabilme ve metaveri görüntüleme.
- [x] **4.5. "Paket Kur" / Sürükle-Bırak Arayüzü**
  - Toolbar üzerinde "Paket Kur" butonu ve pencereye doğrudan `.deb`, `.AppImage`, `.tar.gz`, vb. sürükleyip bırakarak kurma (Drag-and-Drop) özelliği.

---

## 🐧 Aşama 5: Dağıtımdan Bağımsız Mimari (Distro-Agnostic)
- [x] **5.1. Çoklu Paket Yöneticisi Desteği**
  - Sistemdeki yöneticileri otomatik tanıma (`sourcedock/backend/distro.py`):
    - Debian / Ubuntu / Zorin: `apt`
    - Fedora / RHEL: `dnf`
    - Arch Linux / Manjaro / SteamOS: `pacman`
    - openSUSE / SUSE: `zypper`
    - Evrensel: `flatpak`, `snap`, `appimage`, `portable`
- [x] **5.2. Paket Yöneticisi Soyutlama Katmanı (Backend Abstraction)**
  - Ortak paket arama, kurma, kaldırma ve güncelleme arayüzü (`BaseNativeProvider`):
    - `AptProvider`, `DnfProvider`, `PacmanProvider`, `ZypperProvider`.
    - `ApplicationRegistry` ve `StoreRegistry` üzerinden dinamik yönlendirme ve kilit yönetimi.


---

## 🚀 Aşama 6: Açık Kaynak Hazırlığı & GitHub Topluluğu
- [x] **6.1. Topluluk ve Katkı Belgeleri**
  - `CONTRIBUTING.md` (Geliştirici katkı kuralları ve modüler dosya kuralı).
  - `CODE_OF_CONDUCT.md` (Topluluk kuralları).
  - `.github/ISSUE_TEMPLATE/` (Hata ve öneri şablonları).
  - `.github/pull_request_template.md`.
- [x] **6.2. Otomasyon & CI/CD**
  - Tek komutla global sistem kurulumu için `install.sh` ve `uninstall.sh`.
  - GitHub Actions CI (`.github/workflows/ci.yml`: syntax, Ubuntu 22.04 ve 24.04 matrisi, Xvfb altında unittest çalıştırma ve paketleme doğrulaması).
- [x] **6.3. SourceDock `.deb` Paketi & Dağıtımı**
  - Modernize edilmiş `packaging/build_deb.sh` ile tek komutla standart Debian paketi (`sourcedock_1.3.0_all.deb`) inşası.
  - Bağımsız masaüstü başlatıcı (`sourcedock.desktop`), masaüstü sağ tık eylemleri (Desktop Actions: Ayrıntılar, Kaldır, Güncellemeler), uygulama detay sayfası (`InstalledAppDetailsDialog`), tam ikon setleri ve MIME ilişkilendirmeleri.


---

## 🔒 Aşama 7: Güvenlik, İşlem Kilitleri ve Kararlılık (1.3.0 RC1)
- [x] **7.1. Boru Hattı Kilitlenmesi (Pipe Deadlock) Koruması**
  - `sourcedock/core/runner.py` içinde stderr-only ve uzun süren süreçlerde non-blocking `select.select` I/O mekanizması kurularak pipe kilitlenmeleri tamamen engellendi.
- [x] **7.2. Süreç Çıkış Kodu Senkronizasyonu**
  - Akışlı süreçlerde çıkış kodunun erken 0 sayılması önlenerek gerçek `returncode` doğrulaması sağlandı.
- [x] **7.3. Cross-Runner Kilit Koordinasyonu**
  - Farklı `CommandRunner` örnekleri ve eşzamanlı süreçler arasında çakışmayı önlemek için dosya tabanlı kilit (`flock`) ve işlem bazlı mutex eklendi.
- [x] **7.4. UI Yaşam Döngüsü ve Callback Güvenliği**
  - Uzun süren işlemlerde log akışının diyaloglara kesintisiz aktarımı sağlandı.
  - Gecikmiş `GLib.idle_add` sinyallerinde çifte `finish()` ve kapanmış widget erişimleri koruma altına alındı.
- [x] **7.5. Kapsamlı Test ve Doğrulama**
  - 281 birim testinin tamamı Xvfb/Openbox altında başarıyla doğrulandı; X11 1024x768 ve 1366x768 çift çözünürlük kabul testleri tamamlandı.

---

## 🔮 Aşama 8: Gelecek Planları (Gelecek Sürümler)
- [ ] **8.1. Genişletilmiş Masaüstü Eklentisi**
  - GNOME Shell 46+ AppMenu eklentisinin farklı masaüstü kabukları ve sürümleri için genişletilmesi.
- [ ] **8.2. Alternatif Yerel Paketleme**
  - Fedora/RHEL için bağımsız `.rpm` ve Arch Linux için PKGBUILD paketleme altyapısının hazırlanması.
- [ ] **8.3. Çevrimdışı Metaveri Önbelleği**
  - Düşük bant genişliğinde daha hızlı mağaza gezinmesi için yerel AppStream katalog önbelleğinin optimize edilmesi.
