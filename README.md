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

</div>

---

## ⚡ The Story Behind VoltApp / VoltApp'in Hikayesi

> *"VoltApp was born from an Electrical & Electronics Engineer's passion for Pikachu, high-voltage electricity, and a dream to manage Linux applications at lightning speed without distribution barriers."*
>
> *"VoltApp ⚡; bir Elektrik-Elektronik Mühendisinin Pikachu ve voltaj sevgisi ile Linux ekosistemindeki tüm uygulamaları dağıtım engellerine takılmadan, elektrik hızında yönetme tutkusundan doğdu."*

---

## 🌟 Features / Özellikler

- **🔌 Universal Multi-Store Support:** Search, install, and manage applications from **Flathub (Flatpak)**, **Snap Store**, and native package managers (**APT / DNF / Pacman / Zypper**).
- **📦 Multi-Format & Standalone Mini-Installer:** Double-click any `.deb`, `.AppImage`, `.flatpak`, or `.rpm` file to open a lightweight mini-installer with smart version detection (Installed/Reinstall, Update, Downgrade, New install).
- **🛡️ Smart Snap Confinement Handling:** Automatically detects `--classic` confinement requirements for developer IDEs (such as Antigravity, VS Code, JetBrains) with user-friendly confirmation dialogs.
- **⚡ Supercharged UI & Guidance:** Clean, responsive GTK interface with dark/light theme, built-in User Guide (`F1`), and localized tooltips for every action.
- **🌍 Bilingual (i18n):** Native support for both English and Turkish with instant runtime switching.
- **🐧 Distro-Agnostic:** Auto-detects Debian, Ubuntu, Zorin OS, Fedora, Arch Linux, Manjaro, openSUSE, and generic Linux platforms.

---

## 🚀 Installation & Usage / Kurulum ve Kullanım

### Seçenek 1: Debian (.deb) Paketi ile Kurulum (Önerilen)
```bash
# Paketi derleyin veya indirin:
./packaging/build_deb.sh

# Tek komutla kurun:
sudo apt install ./packaging/voltapp_1.0.0_all.deb
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

## 🧪 Testing / Testleri Çalıştırma

```bash
python3 -m unittest discover -s tests -v
```

---

## 🗺️ Roadmap / Yol Haritası

Tüm aşamaların ve tamamlanan hedeflerin detayları için [ROADMAP.md](ROADMAP.md) belgesini inceleyebilirsiniz.

---

## 🤝 Contributing / Katkıda Bulunma

Katkıda bulunma standartları, kod mimarisi ve kurallar için [CONTRIBUTING.md](CONTRIBUTING.md) ve [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) belgelerini inceleyebilirsiniz.

---

## 📄 License / Lisans

Distributed under the **GNU General Public License v3.0 (GPL-3.0)**. See [`LICENSE`](LICENSE) for more information.


