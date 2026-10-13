# ⚡ VoltApp — Geliştirici & Katkı Kılavuzu (Contributing Guide)

> *VoltApp ⚡, bir Elektrik-Elektronik Mühendisinin Pikachu ve voltaj sevgisi ile Linux sistemlerini elektrik hızında, engelsizce yönetme arzusundan doğdu.*

Açık kaynak dünyasına ve VoltApp projesine katkıda bulunmak istediğiniz için teşekkür ederiz! Bu belge, projenin mimari standartlarını, kodlama kurallarını ve geliştirme iş akışını açıklar.

---

## 📐 1. Altın Mimari Kuralımız (Clean Architecture)

> **Önemli Kural:**  
> Hiçbir dosya gereksiz yere şişirilmeyecek, spagetti koda izin verilmeyecektir.  
> Yeni bir özellik eklerken mevcut dosyaları yüzlerce satır uzatmak yerine, işlevsel alt modüller oluşturulmalı veya ilgili katmana (`core/`, `backend/`, `ui/views/`, `ui/components/`) yerleştirilmelidir.

### Modüler Dizin Yapısı:
```text
voltapp/
├── core/                  # İş mantığından bağımsız temel çekirdek
│   ├── models.py          # Veri modelleri ve tip tanımları
│   ├── errors.py          # Proje geneli hata sınıfları
│   └── runner.py          # Güvenli komut çalıştırma ve sudo yönetimi
│
├── backend/               # Paket yöneticisi entegrasyonları
│   ├── base_native.py     # Dağıtım-bağımsız yerel paket yöneticisi soyutlaması
│   ├── distro.py          # Linux dağıtımı otomatik algılama
│   ├── apt.py             # Debian / Ubuntu / Zorin yerel yöneticisi
│   ├── dnf.py             # Fedora / RHEL yerel yöneticisi
│   ├── pacman.py          # Arch Linux / Manjaro yerel yöneticisi
│   ├── zypper.py          # openSUSE yerel yöneticisi
│   ├── flatpak.py         # Flatpak sandbox yönetimi
│   ├── snap.py            # Snap ve --classic yönetimi
│   ├── appimage.py        # AppImage çalıştırma ve masaüstü entegrasyonu
│   ├── portable.py        # Taşınabilir arşiv (tar.gz/zip) yöneticisi
│   ├── local_packages.py  # Çevrimdışı paket inceleme ve kurucu
│   ├── mime_integration.py# MIME türleri ve varsayılan yükleyici entegrasyonu
│   ├── scanner.py         # Masaüstü uygulamaları tarayıcısı
│   └── manager.py         # Birleşik ApplicationRegistry
│
├── store/                 # Mağaza ve depo entegrasyonu
│   └── registry.py        # Flathub, Snap Store ve yerel depo arama motoru
│
├── ui/                    # Kullanıcı arayüzü (GTK 3)
│   ├── views/             # Sekme görünümleri (ViewMixin'ler)
│   │   ├── installed_view.py # Yüklü uygulamalar sekmesi
│   │   ├── store_view.py     # Mağaza sekmesi
│   │   ├── packages_view.py  # Sistem paketleri sekmesi
│   │   ├── operations_view.py# Süreç izleme sekmesi
│   │   ├── settings_view.py  # Ayarlar diyaloğu
│   │   └── help_view.py      # Yardım kılavuzu diyaloğu (F1)
│   ├── components/        # Tekrar kullanılabilir UI bileşenleri
│   │   ├── dialogs.py        # Onay ve şifre pencereleri
│   │   ├── progress.py       # İlerleme penceresi (OperationProgressWindow)
│   │   └── package_installer_dialog.py # Bağımsız mini kurucu diyaloğu
│   └── window.py          # MainWindow (tüm mixin'leri birleştiren ana pencere)
│
├── constants.py           # Uygulama sabitleri
├── i18n.py                # Türkçe ve İngilizce tam dil sözlüğü
├── preferences.py         # JSON tabanlı kullanıcı tercihleri
└── theme.py               # Modern GTK CSS renk ve stil motoru
```

---

## 🌍 2. Çift Dilli Yerelleştirme (i18n) Zorunluluğu

Kullanıcı arayüzünde görünen **hiçbir metin koda doğrudan (hardcoded) yazılmamalıdır**.
- Her yeni etiket, buton metni, hata mesajı veya araç ipucu (tooltip) hem `tr` hem de `en` dillerinde [`voltapp/i18n.py`](file:///home/ali/Desktop/projeler/zorin/app_manager/voltapp/i18n.py) dosyasına eklenmelidir.
- Arayüzde `t(lang, "anahtar_adi")` fonksiyonu kullanılmalıdır.
- Ayarlar penceresinden dil değiştirildiğinde arayüzün anında güncellenebilmesi için dinamik yenileme (`_refresh_texts`) metoduna dahil edilmelidir.

---

## 🛠️ 3. Geliştirme Ortamı ve Çalıştırma

### Sistem Gereksinimleri (Ubuntu/Debian tabanlı sistemler):
```bash
sudo apt update
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0
```

### Projeyi Çalıştırma:
```bash
# Geliştirme modunda başlatıcı betik ile çalıştırma:
./run.sh

# Veya doğrudan Python ile:
python3 main.py

# Bağımsız mini kurucu modunu test etme:
python3 main.py /ornek/paket.deb
```

---

## 🧪 4. Birim Testleri Çalıştırma (Testing)

Yeni bir özellik eklediğinizde veya hata düzelttiğinizde lütfen mevcut testlerin geçtiğinden emin olun ve gerekirse yeni testler ekleyin:
```bash
python3 -m unittest discover -s tests -v
```

---

## 📦 5. Debian (.deb) Paketi Üretme

Uygulamayı Debian paketi olarak derlemek için:
```bash
./packaging/build_deb.sh
```
Oluşturulan paket `packaging/voltapp_1.0.0_all.deb` dosyasında yer alacaktır.

---

## 🚀 6. Katkı ve Pull Request (PR) Gönderme

1. Depoyu fork'layın ve kendi dalınızı (branch) oluşturun:
   ```bash
   git checkout -b feature/yeni-ozellik
   ```
2. Değişikliklerinizi yapın ve test edin:
   ```bash
   python3 -m unittest discover -s tests -v
   ```
3. Anlaşılır bir commit mesajı yazın (Conventional Commits önerilir):
   - `feat: Yeni özellik açıklaması`
   - `fix: Düzeltilen hata açıklaması`
   - `docs: Dokümantasyon güncellemesi`
   - `refactor: Kod temizliği ve modülerleştirme`
4. Dalınızı push'layın ve GitHub üzerinden Pull Request açın.
