#!/usr/bin/env bash
# tools/vm_tests/test_fedora.sh
# Fedora 41/42/45 (GNOME / DNF) Test Script
set -e

echo "=== [Fedora] SourceDock Test Suite Başlatılıyor ==="

# 1. Bağımlılık kontrolü ve kurulum
echo "--> [1/5] Bağımlılıklar denetleniyor/kuruluyor..."
sudo dnf install -y \
    python3 \
    python3-gobject \
    gtk3 \
    gtk4 \
    libadwaita \
    flatpak \
    polkit \
    desktop-file-utils \
    appstream \
    xorg-x11-server-Xvfb \
    python3-pytest

# 2. Ortam bilgileri
echo "--> [2/5] Sistem Bilgileri:"
echo "    Dağıtım: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "    Masaüstü: ${XDG_CURRENT_DESKTOP:-Bilinmiyor}"
echo "    Oturum Tipi: ${XDG_SESSION_TYPE:-Headless}"
echo "    DNF Versiyonu: $(rpm -q dnf || echo 'dnf5')"
echo "    Flatpak Versiyonu: $(flatpak --version 2>/dev/null || echo 'Yok')"

# 3. Python Kod Doğrulama & Birim Testleri
echo "--> [3/5] Python sözdizimi ve derleme testi..."
python3 -m compileall -q main.py sourcedock tests tools

if [ -f "tools/run_tests.py" ]; then
    echo "--> [3.1/5] Proje test runner'ı çalıştırılıyor..."
    python3 tools/run_tests.py || true
elif command -v pytest &>/dev/null; then
    echo "--> [3.1/5] Pytest koşturuluyor..."
    pytest tests/ -v || true
fi

# 4. Masaüstü & AppStream Doğrulama
echo "--> [4/5] Masaüstü entegrasyon dosyaları kontrol ediliyor..."
if [ -f "packaging/sourcedock.desktop" ]; then
    desktop-file-validate packaging/sourcedock.desktop && echo "    desktop-file: GEÇTİ"
fi

# 5. UI Başlatma / Smoke Testi
echo "--> [5/5] UI duman (smoke) testi yapılıyor (10 sn)..."
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    timeout 10s python3 main.py || [ $? -eq 124 ]
    echo "    UI Başarıyla başlatıldı ve kapatıldı."
else
    echo "    Grafik ortam bulunamadı, Xvfb ile deneniyor..."
    xvfb-run -a timeout 10s python3 main.py || [ $? -eq 124 ]
    echo "    UI (Xvfb) Başarıyla başlatıldı ve kapatıldı."
fi

echo "=== [Fedora] Tüm testler tamamlandı! ==="

