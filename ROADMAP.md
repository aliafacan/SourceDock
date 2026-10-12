# ⚡ VoltApp — Roadmap & Yapılacaklar Listesi

> *VoltApp ⚡, bir Elektrik-Elektronik Mühendisinin Pikachu ve voltaj sevgisi ile Linux sistemlerini elektrik hızında, engelsizce yönetme arzusundan doğdu.*

---

## 📌 Durum Özeti & İlerleme Tablosu

| Aşama | Konu | Durum |
| :--- | :--- | :--- |
| **Aşama 1** | Snap `--classic` Hatasının Giderilmesi | ✅ Tamamlandı |
| **Aşama 2** | Çoklu Dil & Yerelleştirme (i18n) Temizliği | ⏳ Sırada |
| **Aşama 3** | Yeni Paket Formatları (.deb, .AppImage, .tar.gz, vb.) | ⏳ Beklemede |
| **Aşama 4** | Dağıtımdan Bağımsız (Distro-Agnostic) Mimari & İsimlendirme | ⏳ Beklemede |
| **Aşama 5** | Açık Kaynak Hazırlığı (Lisans, Topluluk, Dokümantasyon) | ⏳ Beklemede |

---

## 🎯 Aşama 1: Kritik Hata Çözümü (Snap `--classic` Desteği)
- [x] **1.1. Snap `--classic` İhtiyacını Algılama**
  - `store.py` içindeki `_run_streaming` ve `_run_privileged_streaming` fonksiyonlarında "classic confinement" ve "--classic" çıktıları anında yakalanıp `SnapClassicRequiredError` fırlatılıyor.
- [x] **1.2. Kullanıcı Güvenlik Onay Penceresi**
  - UI'da kullanıcıya dostça ve açıklayıcı bir uyarı diyaloğu (`store_snap_classic_title` / `store_snap_classic_message`) gösterilerek tam sistem erişimi izni soruluyor.
- [x] **1.3. `--classic` Bayrağı ile Kurulumu Gerçekleştirme**
  - Kullanıcı onay verdiğinde komut `snap install --classic <paket>` şeklinde otomatik yeniden çalıştırılıp kurulum başarıyla tamamlanıyor.

---

## 🌍 Aşama 2: Tam Dil ve Çeviri Entegrasyonu (i18n / Yerelleştirme)
- [ ] **2.1. Backend Hata Mesajlarını Çok Dilli Hale Getirme**
  - `applications.py`, `backend.py` ve `store.py` içindeki gömülü Türkçe mesajları (`Komut basarisiz oldu`, `Komut calistirilamadi`, vb.) `i18n` anahtarlarına dönüştürme.
- [ ] **2.2. Arayüzdeki (UI) Hardcoded Türkçe Metinleri Temizleme**
  - `ui.py` içindeki diyalog başlıkları, hata pencereleri, PID sonlandırma/duraklatma mesajlarını `i18n.py`'ye bağlama.
- [ ] **2.3. Dinamik Dil Senkronizasyonu**
  - İngilizce veya Türkçe seçildiğinde tüm arayüzün ve terminal hata açıklamalarının tutarlı dilde sunulmasını sağlama.

---

## 📦 Aşama 3: Yeni Paket Formatları ve Yerel Kurulum Desteği
- [ ] **3.1. `.deb` Paket Kurulumu & Yönetimi**
  - Kullanıcının yerel `.deb` dosyasını seçebilmesi (`apt install ./dosya.deb` veya `dpkg -i`).
  - Paket metaverilerini (ad, sürüm, açıklama) önizleme ekranı.
- [ ] **3.2. `.AppImage` Entegrasyonu**
  - İndirilen `.AppImage` dosyalarına çalıştırma izni (`chmod +x`) verme.
  - Uygulamayı standart konuma (`~/Applications` veya `~/.local/bin`) taşıma seçeneği.
  - Masaüstü kısayolu (`.desktop` dosyası ve menü ikonu) otomatik oluşturma.
- [ ] **3.3. `.tar.gz` / `.tar.xz` / `.zip` Taşınabilir (Portable) Yazılımlar**
  - Arşivleri güvenli bir dizine açma (`~/.local/share/<uygulama>`).
  - Çalıştırılabilir ana dosyayı tespit edip uygulama menüsüne `.desktop` kısayolu ekleme.
  - Kaldırma sırasında bu dizini ve kısayolları güvenle temizleme.
- [ ] **3.4. Diğer Dağıtımlar ve Paketler**
  - Fedora/RHEL için `.rpm` desteği (`dnf install ./paket.rpm`).
  - `.flatpak` ve `.flatpakref` dosyalarını GUI'dan tek tıkla kurabilme.
- [ ] **3.5. "Paket Kur" / Sürükle-Bırak Arayüzü**
  - Pencereye doğrudan `.deb`, `.AppImage`, `.tar.gz` sürükleyip bırakarak kurma özelliği.

---

## 🐧 Aşama 4: Dağıtımdan Bağımsız Mimari & Yeniden Markalama
- [ ] **4.1. Yeniden Markalama (Yeni İsim & Logo)**
  - Sevimli elektrik temalı / Pikachu esintili özgün isim ve logo entegrasyonu.
  - `constants.py`, masaüstü dosyası (`.desktop`) ve arayüz başlıklarını güncelleme.
- [ ] **4.2. Çoklu Paket Yöneticisi Desteği**
  - Sistemdeki yöneticileri otomatik tanıma:
    - Debian / Ubuntu / Zorin: `apt`
    - Fedora / RHEL: `dnf`
    - Arch Linux: `pacman`
    - openSUSE: `zypper`
    - Evrensel: `flatpak`, `snap`

---

## 🚀 Aşama 5: Açık Kaynak Hazırlığı & GitHub Topluluğu
- [ ] **5.1. Lisans Seçimi**
  - `LICENSE` dosyası (Linux masaüstü araçlarında en popüler olan **GPL-3.0** veya **MIT**).
- [ ] **5.2. Uluslararası `README.md`**
  - İngilizce ana README + Türkçe dokümantasyon bağlantısı.
  - Özellikler, ekran görüntüleri, kurulum kılavuzu.
- [ ] **5.3. Topluluk ve Katkı Belgeleri**
  - `CONTRIBUTING.md` (Geliştirici katkı kuralları).
  - `CODE_OF_CONDUCT.md` (Topluluk kuralları).
  - `.github/ISSUE_TEMPLATE/` (Hata ve öneri şablonları).
  - `.github/pull_request_template.md`.
- [ ] **5.4. Otomasyon & Kurulum Scriptleri**
  - Tek satırda kurulum için `install.sh`.
  - GitHub Actions CI (kod kalitesi ve lint kontrolü).

