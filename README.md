<div align="center">

<img src="assets/voltapp.png" alt="VoltApp Logo" width="140" style="border-radius: 28px;"/>

# VoltApp ⚡
### Universal, Blazing-Fast Linux Package & App Manager
*Evrensel, Şimşek Hızında Linux Paket ve Uygulama Yöneticisi*

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

- **🔌 Universal Multi-Store Support:** Search, install, and manage applications from **Flathub (Flatpak)**, **Snap Store**, and native repositories (**APT**).
- **🛡️ Smart Snap Confinement Handling:** Automatically detects `--classic` confinement requirements for developer IDEs (such as Antigravity, VS Code, JetBrains) with user-friendly confirmation dialogs.
- **📦 Multi-Format Ready:** Architected to support `.deb`, `.AppImage`, and portable `.tar.gz` packages directly from the UI.
- **⚡ Supercharged UI:** Clean, responsive, and intuitive GTK interface with dark/light theme support.
- **🌍 Bilingual (i18n):** Native support for both English and Turkish with dynamic switching.
- **🐧 Distro-Agnostic:** Designed to run seamlessly across Zorin OS, Ubuntu, Debian, and broad Linux distributions.

---

## 🚀 Getting Started / Başlangıç

### Prerequisites / Gereksinimler
- Python 3.10+
- PyGObject / GTK 3
- `flatpak`, `snapd` and `apt` (or your distro's package manager)

```bash
# Ubuntu / Debian / Zorin OS
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
```

### Running Locally / Yerel Çalıştırma
```bash
# Clone the repository
git clone https://github.com/USERNAME/VoltApp.git
cd VoltApp

# Run
python3 main.py
# or
./run.sh
```

---

## 🗺️ Roadmap

Check out [ROADMAP.md](ROADMAP.md) for our detailed development roadmap and upcoming features.

---

## 🤝 Contributing / Katkıda Bulunma

VoltApp is an open-source project welcoming all Linux enthusiasts and developers!
1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License / Lisans

Distributed under the **GNU General Public License v3.0 (GPL-3.0)**. See [`LICENSE`](LICENSE) for more information.
