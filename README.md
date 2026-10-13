<div align="center">

<img src="assets/voltapp.png" alt="VoltApp Logo" width="140" style="border-radius: 28px;"/>

# VoltApp ⚡
### Universal, Blazing-Fast Linux Package & App Manager
*Evrensel, Şimşek Hızında Linux Paket ve Uygulama Yöneticisi*

[![VoltApp CI](https://github.com/aliafacan/VoltApp/actions/workflows/ci.yml/badge.svg)](https://github.com/aliafacan/VoltApp/actions)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![GTK](https://img.shields.io/badge/GUI-GTK%203-4A90D9?style=flat&logo=gnome&logoColor=white)](https://www.gtk.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Linux](https://img.shields.io/badge/Platform-Linux%20Universal-FCC624?style=flat&logo=linux&logoColor=black)](https://kernel.org)

<br/>

[ 🇹🇷 **Türkçe** ](#-türkçe) &nbsp;&bull;&nbsp; [ 🇬🇧 **English** ](#-english)

</div>

---

<a id="-türkçe"></a>
# 🇹🇷 Türkçe

## ⚡ VoltApp'in Hikayesi

> *"VoltApp ⚡; bir Elektrik-Elektronik Mühendisinin Pikachu ve voltaj sevgisi ile Linux ekosistemindeki tüm uygulamaları dağıtım engellerine takılmadan, elektrik hızında yönetme tutkusundan doğdu."*

---

## 🌟 Temel Özellikler

- **🔌 Evrensel Çoklu Mağaza Desteği:** **Flathub (Flatpak)**, **Snap Store** ve yerel paket depolarındaki (**APT / DNF / Pacman / Zypper**) uygulamaları tek ekrandan arayın, kurun ve güncelleyin.
- **📦 Çoklu Format ve Bağımsız Mini Kurucu:** `.deb`, `.AppImage`, `.flatpak` veya `.rpm` dosyalarına çift tıklandığında akıllı sürüm algılamalı (Kurulu/Tekrar Kur, Güncelle, Eski Sürüme Dön, Yeni Kur) bağımsız mini kurulum penceresi açılır.
- **🛡️ Akıllı Snap Confinement Yönetimi:** Geliştirici IDE'leri (Antigravity, VS Code, JetBrains vb.) için gerekli `--classic` yetkilendirmelerini otomatik algılar ve kullanıcı onay diyaloğu sunar.
- **⚙️ Sistem, Bellenim & Çalışma Ortamı Güncellemeleri:** Donanım bellenimleri (`fwupd` / UEFI dbx) ve Flatpak/Snap sistem platformları/çalışma ortamları (Mesa, GNOME, KDE, Wine) için tam güncelleme desteği.
- **🔍 Uygulama Detayları ve Masaüstü Sağ Tık Eylemleri (Desktop Actions):** Zorin OS / GNOME masaüstü menüsünden doğrudan VoltApp ayrıntılarını açma veya kaldırma eylemleri; uygulama listesinde çift tık veya sağ tık ile sürüm, boyut, kaynak ve izinleri inceleyebileceğiniz kapsamlı detay penceresi.
- **⚡ Modern ve Hızlı GTK Arayüzü:** Koyu/Açık tema, `%90-%125` arayüz ölçekleme, yerleşik Kullanıcı Kılavuzu (`F1`) ve her işlem için etkileşimli araç ipuçları (tooltips).
- **🌍 Çift Dilli (i18n):** Türkçe ve İngilizce dilleri arasında çalışma anında anında geçiş.
- **🐧 Dağıtım Bağımsız:** Ubuntu, Zorin OS, Debian, Fedora, Arch Linux, Manjaro, openSUSE ve genel Linux dağıtımlarını otomatik tanır.

---

## 🚀 Kurulum ve Kullanım

### Seçenek 1: Debian (.deb) Paketi ile Kurulum (Önerilen)
```bash
# Paketi derleyin:
./packaging/build_deb.sh

# Tek komutla kurun:
sudo apt install ./packaging/voltapp_1.1.0_all.deb
```

### Seçenek 2: Otomatik Kurulum Betiği (Global Installer)
```bash
sudo ./install.sh
```

### Seçenek 3: Kurulum Yapmadan Çalıştırma
```bash
# Sistem bağımlılıkları:
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0

# Çalıştır:
./run.sh
# veya
python3 main.py
```

### Bağımsız Mini Kurucu Kullanımı
Herhangi bir paket dosyasını bağımsız mini kurucu penceresiyle açmak için:
```bash
voltapp /yol/paket.deb
# veya
voltapp /yol/uygulama.AppImage
```

---

## 🧪 Birim Testleri Çalıştırma

```bash
python3 -m unittest discover -s tests -v
```

---

## 🤝 Katkıda Bulunma & Topluluk

- Katkı rehberi için: [CONTRIBUTING.md](CONTRIBUTING.md)
- Topluluk kuralları için: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Yol haritası için: [ROADMAP.md](ROADMAP.md)
- İletişim: [aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com)

---
---

<a id="-english"></a>
# 🇬🇧 English

## ⚡ The Story Behind VoltApp

> *"VoltApp was born from an Electrical & Electronics Engineer's passion for Pikachu, high-voltage electricity, and a dream to manage Linux applications at lightning speed without distribution barriers."*

---

## 🌟 Key Features

- **🔌 Universal Multi-Store Catalog:** Search, install, and update applications from **Flathub (Flatpak)**, **Snap Store**, and native package managers (**APT / DNF / Pacman / Zypper**) in one place.
- **📦 Multi-Format & Standalone Mini-Installer:** Double-click any `.deb`, `.AppImage`, `.flatpak`, or `.rpm` file to open a lightweight mini-installer with intelligent version detection (Installed/Reinstall, Update, Downgrade, Fresh Install).
- **🛡️ Smart Snap Confinement Handling:** Automatically detects `--classic` confinement requirements for developer IDEs (such as Antigravity, VS Code, JetBrains) with seamless confirmation dialogs.
- **⚙️ System, Firmware & Runtime Updates:** Full update support for hardware firmware (`fwupd` / UEFI dbx) and Flatpak/Snap platform runtimes (Mesa, GNOME, KDE, Wine).
- **🔍 Application Details & Desktop Actions:** Native Zorin OS / GNOME desktop actions for opening App Details, direct uninstall, and update checks right from the application menu; comprehensive in-app details dialog with version comparison, launch, and safe uninstall.
- **⚡ Blazing GTK User Interface:** Clean dark/light theme styling, `90%-125%` UI scaling, integrated User Guide (`F1`), and localized interactive tooltips.
- **🌍 Fully Bilingual (i18n):** Native support for English and Turkish with instant runtime switching.
- **🐧 Distro-Agnostic Engine:** Auto-detects Debian, Ubuntu, Zorin OS, Fedora, Arch Linux, Manjaro, openSUSE, and generic Linux platforms.

---

## 🚀 Installation & Usage

### Option 1: Debian (.deb) Package (Recommended)
```bash
# Build the package:
./packaging/build_deb.sh

# Install with single command:
sudo apt install ./packaging/voltapp_1.1.0_all.deb
```

### Option 2: Automatic Global Installer Script
```bash
sudo ./install.sh
```

### Option 3: Run Without Installing
```bash
# System dependencies:
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0

# Run:
./run.sh
# or
python3 main.py
```

### Standalone Mini-Installer Usage
To open any package in the dedicated lightweight installer window:
```bash
voltapp /path/to/package.deb
# or
voltapp /path/to/application.AppImage
```

---

## 🧪 Running Unit Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## 🤝 Contributing & Community

- Contribution guidelines: [CONTRIBUTING.md](CONTRIBUTING.md)
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Project roadmap: [ROADMAP.md](ROADMAP.md)
- Maintainer contact: [aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com)

---

## 📄 License

Distributed under the **GNU General Public License v3.0 (GPL-3.0)**. See [`LICENSE`](LICENSE) for more details.
