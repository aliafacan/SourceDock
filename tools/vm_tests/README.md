# SourceDock Dağıtım VM Testleri Rehberi

Bu dizin, SourceDock'un farklı Linux dağıtımları ve masaüstü ortamlarında test edilmesi için otomatik test betiklerini içerir.

## Dosya Yapısı

* `test_fedora.sh`: Fedora (GNOME / DNF / Wayland / Flatpak)
* `test_cachyos.sh`: CachyOS / Arch (KDE Plasma / Pacman / Wayland / Flatpak)
* `test_debian_mint.sh`: Debian & Linux Mint (APT / Cinnamon / MATE / X11)
* `test_opensuse.sh`: openSUSE Tumbleweed (Zypper / KDE Plasma)
* `serve_bundle.sh`: Ana makinede tek komutla test paketini sunan HTTP sunucu betiği

---

## 1. Ana Makinede Paketi Yayına Açma

VM'lere dosya kopyalamanın en hızlı yolu:

```bash
bash tools/vm_tests/serve_bundle.sh
```
Bu komut projeyi `sourcedock_test_bundle.zip` olarak paketler ve yerel ağda port `8888` üzerinde bir HTTP sunucu açar. Ekranda sana bağlanman gereken IP adresini ve komutu verir.

---

## 2. Sanal Makine (VM) İçinde Çalıştırma

VM açıldığında terminale şu adımları yapıştır:

```bash
# Ana makine IP'si diyelim ki 192.168.1.50 olsun:
curl -O http://192.168.1.50:8888/sourcedock_test_bundle.zip
unzip sourcedock_test_bundle.zip -d sourcedock
cd sourcedock

# İlgili dağıtımın testini koştur:
# Fedora için:
bash tools/vm_tests/test_fedora.sh

# CachyOS için:
bash tools/vm_tests/test_cachyos.sh

# Linux Mint veya Debian için:
bash tools/vm_tests/test_debian_mint.sh

# openSUSE Tumbleweed için:
bash tools/vm_tests/test_opensuse.sh
```

---

## 3. Testlerin Kontrol Ettiği Adımlar
1. **Bağımlılıklar:** GTK3/4, PyGObject, Libadwaita, Polkit, Flatpak.
2. **Sistem Entegrasyonu:** Masaüstü türü (GNOME, KDE, Cinnamon, MATE), oturum tipi (Wayland/X11).
3. **Kod Bütünlüğü:** `python3 -m compileall`, birim testleri (pytest / run_tests.py).
4. **Masaüstü Standartları:** `desktop-file-validate`.
5. **Arayüz Duman Testi (Smoke Test):** UI'ın çökmeden ayağa kalktığının ve düzgün kapandığının teyidi.

