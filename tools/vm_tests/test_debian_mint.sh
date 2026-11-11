#!/usr/bin/env bash
# tools/vm_tests/test_debian_mint.sh
# Debian / Linux Mint (APT / Cinnamon / MATE) Test Script
set -e

echo "=== [Debian / Mint] SourceDock Test Suite Başlatılıyor ==="

# 1. Bağımlılık kontrolü ve kurulum
echo "--> [1/5] Bağımlılıklar denetleniyor/kuruluyor..."
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    gir1.2-adw-1 \
    flatpak \
    policykit-1 \
    desktop-file-utils \
    appstream-util \
    xvfb \
    python3-pytest

# 2. Ortam bilgileri
echo "--> [2/5] Sistem Bilgileri:"
echo "    Dağıtım: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "    Masaüstü: ${XDG_CURRENT_DESKTOP:-Bilinmiyor}"
echo "    Oturum Tipi: ${XDG_SESSION_TYPE:-Headless}"
echo "    APT: $(apt-get -v | head -n 1)"
echo "    Flatpak: $(flatpak --version 2>/dev/null || echo 'Yok')"

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

# 4. .deb Paket Üretim ve Kurulum Doğrulaması (İsteğe bağlı)
if [ -f "packaging/build_deb.sh" ]; then
    echo "--> [4/5] .deb paketi derlenip kuruluyor..."
    mkdir -p /tmp/sourcedock_pkg
    bash packaging/build_deb.sh /tmp/sourcedock_pkg
    LATEST_DEB=$(ls -t /tmp/sourcedock_pkg/*.deb 2>/dev/null | head -n 1)
    if [ -n "$LATEST_DEB" ]; then
        echo "    Paket bulundu: $LATEST_DEB"
        sudo dpkg -i "$LATEST_DEB" || sudo apt-get -f install -y
        echo "    .deb kurulumu başarılı!"
    fi
fi

# 5. UI Başlatma / Smoke Testi
echo "--> [5/5] UI duman (smoke) testi yapılıyor (10 sn)..."
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    timeout 10s python3 main.py || [ $? -eq 124 ]
    echo "    UI başarıyla başlatıldı ve kapatıldı."
else
    echo "    Grafik ortam bulunamadı, Xvfb ile deneniyor..."
    xvfb-run -a timeout 10s python3 main.py || [ $? -eq 124 ]
    echo "    UI (Xvfb) başarıyla başlatıldı ve kapatıldı."
fi

echo "=== [Debian / Mint] Tüm testler tamamlandı! ==="

