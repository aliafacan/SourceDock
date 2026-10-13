<div align="center">

[ 🇹🇷 **Türkçe** ](#-türkçe) &nbsp;&bull;&nbsp; [ 🇬🇧 **English** ](#-english)

</div>

---

<a id="-türkçe"></a>
# 🇹🇷 VoltApp — Geliştirici & Katkı Kılavuzu (Contributing Guide)

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
│   ├── firmware.py        # Donanım yazılımı / fwupd entegrasyonu
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

### Sistem Gereksinimleri (Ubuntu/Debian/Zorin tabanlı sistemler):
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

---

## 📬 7. İletişim

Her türlü soru, öneri ve güvenlik bildirimi için proje yöneticisine [aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com) adresinden ulaşabilirsiniz.

---
---

<a id="-english"></a>
# 🇬🇧 VoltApp — Developer & Contributing Guide

> *VoltApp ⚡ was born from an Electrical & Electronics Engineer's passion for Pikachu, high-voltage electricity, and a dream to manage Linux applications at lightning speed without distribution barriers.*

Thank you for your interest in contributing to VoltApp! This guide outlines the project's architectural standards, coding conventions, and development workflow.

---

## 📐 1. Clean Architecture & Modular Code Structure

> **Golden Rule:**  
> No monolithic files or spaghetti code are allowed.  
> When introducing new functionality, do not append hundreds of lines to existing files. Create well-isolated submodules in their respective layer (`core/`, `backend/`, `ui/views/`, `ui/components/`).

### Project Structure Overview:
```text
voltapp/
├── core/                  # Core domain models and utilities
│   ├── models.py          # Unified data models & type definitions
│   ├── errors.py          # Custom error hierarchy
│   └── runner.py          # Process execution & privileged command runner
│
├── backend/               # Package manager backends
│   ├── base_native.py     # Distro-agnostic native package manager base
│   ├── distro.py          # OS & Linux distribution auto-detection
│   ├── apt.py             # Debian / Ubuntu / Zorin backend
│   ├── dnf.py             # Fedora / RHEL backend
│   ├── pacman.py          # Arch Linux / Manjaro backend
│   ├── zypper.py          # openSUSE backend
│   ├── flatpak.py         # Flatpak sandboxed application manager
│   ├── snap.py            # Snap Store and --classic confinement manager
│   ├── firmware.py        # Hardware firmware / fwupd provider
│   ├── appimage.py        # AppImage runtime & desktop integration
│   ├── portable.py        # Portable archives (tar.gz/zip) backend
│   ├── local_packages.py  # Standalone package inspection and installer
│   ├── mime_integration.py# Desktop MIME types & default handler setup
│   ├── scanner.py         # Desktop entry parser & icon resolution
│   └── manager.py         # Unified ApplicationRegistry coordinator
│
├── store/                 # Online store catalog & multi-source search
│   └── registry.py        # Flathub, Snap Store & native repository search
│
├── ui/                    # GTK 3 User Interface
│   ├── views/             # Tab views (ViewMixins)
│   │   ├── installed_view.py # Installed applications tab
│   │   ├── store_view.py     # App store catalog tab
│   │   ├── packages_view.py  # System packages & upgrade tab
│   │   ├── operations_view.py# Process monitor & lock status tab
│   │   ├── settings_view.py  # Preferences dialog
│   │   └── help_view.py      # Help guide dialog (F1)
│   ├── components/        # Reusable UI widgets
│   │   ├── dialogs.py        # Confirmation, auth & permission dialogs
│   │   ├── progress.py       # Operation progress dialog
│   │   └── package_installer_dialog.py # Standalone mini-installer dialog
│   └── window.py          # MainWindow combining all view mixins
│
├── constants.py           # Application constants
├── i18n.py                # Complete English and Turkish translation catalog
├── preferences.py         # JSON-backed configuration storage
└── theme.py               # Modern GTK CSS styling engine
```

---

## 🌍 2. Bilingual Localization (i18n) Requirement

**Zero Hardcoded Strings:**
- Every new label, button text, error message, or tooltip must be defined in both `en` and `tr` within [`voltapp/i18n.py`](file:///home/ali/Desktop/projeler/zorin/app_manager/voltapp/i18n.py).
- Use `t(lang, "key_name")` in UI components.
- Ensure all text elements are registered in `_refresh_texts()` so language changes apply instantly without requiring an application restart.

---

## 🛠️ 3. Development Setup & Running

### Prerequisites (Ubuntu/Debian/Zorin):
```bash
sudo apt update
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0
```

### Running the App:
```bash
# Run with launcher script in development:
./run.sh

# Or directly with Python:
python3 main.py

# Test standalone mini-installer mode:
python3 main.py /path/to/sample.deb
```

---

## 🧪 4. Running Unit Tests

Ensure all unit tests pass before submitting changes:
```bash
python3 -m unittest discover -s tests -v
```

---

## 📦 5. Building Debian (.deb) Package

To build the standalone installation package:
```bash
./packaging/build_deb.sh
```
The output file will be generated at `packaging/voltapp_1.0.0_all.deb`.

---

## 🚀 6. Contributing & Pull Requests Workflow

1. Fork the repository and create your feature branch:
   ```bash
   git checkout -b feature/awesome-feature
   ```
2. Make your changes and run the test suite:
   ```bash
   python3 -m unittest discover -s tests -v
   ```
3. Write clear commit messages following Conventional Commits:
   - `feat: New feature summary`
   - `fix: Bug fix summary`
   - `docs: Documentation update`
   - `refactor: Code restructuring`
4. Push your branch and open a Pull Request on GitHub.

---

## 📬 7. Contact

For inquiries, support, or security reports, reach out to the maintainer at [aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com).
