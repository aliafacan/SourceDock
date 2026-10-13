# ⚡ VoltApp — Roadmap & Yapılacaklar Listesi

> *VoltApp ⚡, bir Elektrik-Elektronik Mühendisinin Pikachu ve voltaj sevgisi ile Linux sistemlerini elektrik hızında, engelsizce yönetme arzusundan doğdu.*

---

## 📌 Durum Özeti & İlerleme Tablosu

| Aşama | Konu | Durum |
| :--- | :--- | :--- |
| **Aşama 1** | Snap `--classic` Hatasının Giderilmesi | ✅ Tamamlandı |
| **Aşama 2** | Modüler Mimari & Dosya Bölme & Markalama | ✅ Tamamlandı |
| **Aşama 3** | Çoklu Dil & Yerelleştirme (i18n) Temizliği | ✅ Tamamlandı |
| **Aşama 4** | Yeni Paket Formatları (.deb, .AppImage, .tar.gz, vb.) | ✅ Tamamlandı |
| **Aşama 5** | Dağıtımdan Bağımsız (Distro-Agnostic) Mimari | ✅ Tamamlandı |
| **Aşama 6** | Açık Kaynak Hazırlığı (Topluluk, CI/CD, Dokümantasyon) | ⏳ Sırada |

---

> 📐 **Kalıcı Mimari Kuralımız:**  
> Hiçbir dosya gereksiz yere şişirilmeyecek (spagetti koda izin verilmeyecek). Büyük bileşenler (`ui.py`, `applications.py`, vb.) tek bir dev dosyada tutulmak yerine `core/`, `backend/`, `ui/views/`, `ui/components/` gibi işlevsel alt modüllere bölünecek.

---

## 🎯 Aşama 1: Kritik Hata Çözümü (Snap `--classic` Desteği)
- [x] **1.1. Snap `--classic` İhtiyacını Algılama**
  - `voltapp/store/registry.py` içindeki streaming runner'da "classic confinement" ve "--classic" çıktıları anında yakalanıp `SnapClassicRequiredError` fırlatılıyor.
- [x] **1.2. Kullanıcı Güvenlik Onay Penceresi**
  - UI'da kullanıcıya dostça ve açıklayıcı bir uyarı diyaloğu (`store_snap_classic_title` / `store_snap_classic_message`) gösterilerek tam sistem erişimi izni soruluyor.
- [x] **1.3. `--classic` Bayrağı ile Kurulumu Gerçekleştirme**
  - Kullanıcı onay verdiğinde komut `snap install --classic <paket>` şeklinde otomatik yeniden çalıştırılıp kurulum başarıyla tamamlanıyor.

---

## 🏗️ Aşama 2: Modüler Mimari & Markalama (VoltApp ⚡)
- [x] **2.1. Kod Bölme (Clean Architecture)**
  - 3764 satırlık devasa `ui.py` ve 1402 satırlık `applications.py` paketlere bölündü (`voltapp/core/`, `voltapp/backend/`, `voltapp/store/`, `voltapp/ui/views/`, `voltapp/ui/components/`).
  - `main.py` 26 satıra indirildi; kök dosyalar geriye dönük uyumlu re-exporter haline getirildi.
- [x] **2.2. Yeniden Markalama & Logo**
  - Elektrik-Elektronik Mühendisi Pikachu temalı özgün vektörel logo (`assets/voltapp.svg`, `voltapp.png` 128/64/48px) oluşturuldu ve pencere ikonu olarak bağlandı.
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
  - Arşivleri güvenli bir dizine açma (`~/.local/share/voltapp/apps/<uygulama>`).
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
  - Sistemdeki yöneticileri otomatik tanıma (`voltapp/backend/distro.py`):
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
- [ ] **6.1. Topluluk ve Katkı Belgeleri**
  - `CONTRIBUTING.md` (Geliştirici katkı kuralları ve modüler dosya kuralı).
  - `CODE_OF_CONDUCT.md` (Topluluk kuralları).
  - `.github/ISSUE_TEMPLATE/` (Hata ve öneri şablonları).
  - `.github/pull_request_template.md`.
- [ ] **6.2. Otomasyon & CI/CD**
  - Tek komutla kurulum için `install.sh`.
  - GitHub Actions CI (syntax, lint ve import kontrolleri).
