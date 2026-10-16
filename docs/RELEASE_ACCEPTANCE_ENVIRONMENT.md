# SourceDock 1.3.0 | V9 Kabul Ortami Hazirlik Plani

> Bu belge ilk V9 ortam koşusunu kaydeder. 16 Ekim takip çalışmasında X11
> boyutlandırma aracındaki CSD kenarlık hatası düzeltildi; güncel ölçümler,
> kaynak timeout'ları ve kalan işler [çalışma raporunda](ROADMAP_COMPLETION_REPORT.md).
> Libvirt bağlantısı çalışır ve VM listesi boştur. Servisin socket ile etkinleşmesi
> mümkündür; yalnız `inactive` çıktısı bağlantının bozuk olduğunu kanıtlamaz.

**Tarih:** 16.10.2026  
**Kapsam:** Yayın test ortamı; yeni UI showcase veya UI kodu bu turda değiştirilmedi.  
**Güvenlik:** Aşağıdaki `sudo`, VM ve provider komutları yalnızca kullanıcı onayıyla ve disposable ortamda çalıştırılmalıdır.

## Durum tablosu

| Test / hazırlık | Durum | Somut kanıt |
| --- | --- | --- |
| Python + PyGObject + GTK 3 | **PASS** | `/usr/bin/python3` 3.12.3; GTK `3.24` import edildi |
| Xvfb | **PASS** | `/usr/bin/Xvfb`, 1024x768 ve 1366x768 root ekranları başlatıldı |
| İzole pencere yöneticisi | **PASS** | `/usr/bin/openbox`, iki Xvfb display üzerinde çalıştı |
| Gerçek X11 root ölçümü | **PASS** | `:99=1024x768`, `:100=1366x768`; `_NET_WORKAREA` root ile aynı |
| X11 kabul koşucusu | **PASS** | Her root'ta 72 matrix vakası, `clipped=[]` |
| 142 test takımı | **PASS** | İzole 1366x768 Xvfb root'ta `Ran 142 tests in 7.883s`, `OK` |
| GTK client / controls | **PASS** | İlgili root boyutlarında alt işlem butonları workarea içinde; clipped vaka yok |
| Dış frame/workarea uyumu | **FAIL** | 1024 root'ta frame `1034x778`, 1366 root'ta `1376x778`; her iki yönde 10 px taşma |
| %125 kesin viewport ölçümü | **FAIL** | Her root'ta 24 ilgili vakanın 3'ünde capture yüksekliği `771` oldu; istek `768` |
| Modal dış frame ölçümü | **NOT TESTED** | Mevcut smoke yalnızca modal capture render ediyor; ayrı outer/workarea metriği üretmiyor |
| Ruff | **PASS** | İzole `/tmp/sourcedock-lint-v9` venv; Ruff `0.17.0`, `All checks passed!` |
| Podman | **BLOCKED** | `/run/user/1000/libpod` read-only filesystem |
| libvirt | **BLOCKED** | Paket ve socket mevcut, fakat `libvirtd` şu an `inactive`; `virsh qemu:///system` listesi boş |
| QEMU / virt-install | **PASS** | Binary'ler kurulu; escalated `virt-host-validate qemu` KVM/TUN dahil gerekli kontrollerde PASS, yalnızca non-blocking cgroup/secure-guest WARN |
| Desktop/AppStream statik kimlik zinciri | **PASS** | `desktop-file-validate`, `appstreamcli --no-net`, paket yolları ve launcher referansları uyumlu |
| D-Bus runtime entegrasyonu | **NOT TESTED** | Uygulamada D-Bus service veya `Gtk.Application` yok; gerçek oturum testi gerekmiyor, GNOME testi ayrı bloklu |
| .deb gerçek yaşam döngüsü | **BLOCKED** | Disposable VM yok; ana sistemde install/remove/purge çalıştırılmadı |
| APT/Flatpak/Snap transaction | **BLOCKED** | İzole VM yok; gerçek provider işlemi çalıştırılmadı |
| GNOME Shell 46 sağ tık | **BLOCKED** | Gerçek GNOME Shell 46 oturumu ve extension etkinleştirme yapılmadı |

## 1. X11 test altyapısı

Kurulumdan sonra GTK bağımlılıkları, Xvfb ve Openbox kullanılabilir hale geldi. `Xephyr` tek başına yeterli değil; çalışan bir üst X display gerektiriyor. `Xorg`'u kullanıcı oturumuna zorla bağlamak güvenli bir kabul ortamı sayılmıyor.

### Kullanıcı onayından sonra Zorin kurulumu

```bash
sudo apt update
sudo apt install --no-install-recommends \
  xvfb openbox x11-utils python3-venv
```

- `xvfb`: 1024x768 ve 1366x768 sanal X11 root ekranları.
- `openbox`: pencere çerçevesi, workarea ve başlık çubuğunu gerçekçi ölçmek için hafif WM.
- `x11-utils`: `xdpyinfo` ve `_NET_WORKAREA` ölçümü.
- `python3-venv`: offline/izole Ruff ortamı.

Hazır koşucu:

```bash
chmod +x tools/run_acceptance_x11.sh
SOURCEDOCK_X11_OUTPUT=/tmp/sourcedock-x11-acceptance \
  tools/run_acceptance_x11.sh
```

Koşucu iki ayrı root açar:

- `:99`, `1024x768x24`
- `:100`, `1366x768x24`

Her root'ta `tools/ui_smoke.py --real-data --matrix` çalışır. Matrix 90/100/110/125 ölçeklerini ve 1024x768, 1366x768, 1920x1080 isteklerini tarar. Çıktı yalnızca `/tmp` altına yazılır; `docs/screenshots` ve showcase değiştirilmez. `xdpyinfo`, `_NET_WORKAREA`, `validation.json` içindeki outer frame, client, titlebar, sidebar, alt buton ve modal ölçümleri birlikte incelenmelidir. Sadece `clipped_controls=0` PASS sayılmamalıdır.

Koşucu hiçbir paket kurmaz; yalnızca iki Xvfb root'u başlatır ve read-only SourceDock metadata/UI smoke testi çalıştırır.

### Gerçek koşu kanıtı

```text
:99  dimensions: 1024x768 pixels
:100 dimensions: 1366x768 pixels
1024x768: 72 cases, clipped_cases=0
1366x768: 72 cases, clipped_cases=0
```

Her iki root'ta `Snap=live`, `APT=live`, `Flatpak=unavailable` ve Flatpak timeout `5s` olarak kaydedildi. Bu, timeout sonrası canlı/cache/unavailable ayrımının gerçek metadata koşusunda korunduğunu gösterir; provider transaction'ı değildir.

### Ölçüm bulgusu

İlgili root boyutunun 24 vakasında:

- 1024 root: dış frame `1034x778`; %125 bazı İngilizce vakalarda capture `1024x771`.
- 1366 root: dış frame `1376x778`; %125 bazı İngilizce vakalarda capture `1366x771`.
- Her iki root'ta `clipped_controls=0`.
- İlgili root boyutuyla çalışan sayfalarda alt işlem butonları workarea içindeydi.
- 1366 istek penceresini 1024 root'ta açmak doğal olarak ekranı aşırır; bu vaka root-fit kabulü değildir.

Bu nedenle altyapı **PASS**, tam küçük ekran frame kabulü **FAIL** durumundadır. UI veya test geometrisi bu bulguyu çözmeden dış frame sığdı diye raporlanmamalıdır. Modal outer/workarea metriği ise henüz üretilmediği için **NOT TESTED**.

## 2. Ruff ve offline doğrulama

### Ağ erişimli, kullanıcı onaylı yol

```bash
python3 -m venv /tmp/sourcedock-lint
/tmp/sourcedock-lint/bin/python -m pip install -r requirements-dev.txt
/tmp/sourcedock-lint/bin/ruff check .
```

### Mevcut koşu

```text
/tmp/sourcedock-lint-v9/bin/ruff --version
ruff 0.17.0
/tmp/sourcedock-lint-v9/bin/ruff check .
All checks passed!
```

Ruff artık çalıştırılabilir durumda ve bu çalışma ağacında **PASS**. Ağ/DNS kesintisi yaşanırsa aşağıdaki wheelhouse yolu kullanılmalıdır.

### İnternetsiz wheelhouse yolu

Ağ erişimli başka bir makinede:

```bash
mkdir sourcedock-wheelhouse
python3 -m pip download --only-binary=:all: \
  --dest sourcedock-wheelhouse ruff==0.17.0
```

Wheelhouse klasörü test makinesine taşındıktan sonra:

```bash
python3 -m venv /tmp/sourcedock-lint
/tmp/sourcedock-lint/bin/python -m pip install \
  --no-index --find-links /path/to/sourcedock-wheelhouse \
  ruff==0.17.0
/tmp/sourcedock-lint/bin/ruff check .
```

Wheelhouse veya venv kaybolursa Ruff sonucu yeniden alınmalıdır. Aynı kontrol GitHub Actions `.github/workflows/ci.yml` içinde Ubuntu 22.04 ve 24.04 job'larında çalışır; yerel dirty ağacı push edilmediği sürece CI bu çalışma ağacını doğrulamış sayılmaz.

## 3. Disposable VM planı

Ana işletim sistemine paket kurulumu yapılmayacak. VM host'tan ayrı disk/snapshot ve ağ kurallarıyla hazırlanmalıdır.

### Libvirt/QEMU kurulumu

Kullanıcı onayıyla host üzerinde yalnızca VM araçlarını hazırlamak için:

```bash
sudo apt update
sudo apt install --no-install-recommends \
  qemu-system-x86 libvirt-daemon-system libvirt-clients \
  virtinst cloud-image-utils ovmf
sudo usermod -aG libvirt,kvm "$USER"
```

Oturum yeniden açıldıktan sonra libvirt erişimi doğrulanır:

```bash
virsh uri
virsh list --all
```

Bu komutlar SourceDock veya provider paketi kurmaz; yalnızca disposable VM altyapısını kurar. Paketler artık kurulu ve `virt-host-validate qemu` host yeteneklerini doğruluyor; fakat `libvirtd` şu an `inactive` ve tanımlı VM yok. Bu nedenle kullanılabilir disposable VM ortamı hâlâ **BLOCKED**.

Kullanıcı onayıyla sonraki host hazırlığı:

```bash
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt,kvm "$USER"
```

Oturum yeniden açıldıktan sonra `virsh -c qemu:///system list --all` ve `virt-host-validate qemu` tekrar çalıştırılmalı. `/dev/kvm` ve `/dev/net/tun` düzelmeden gerçek provider/`.deb` kabulü başlatılmamalıdır.

### VM kabul sırası

VM snapshot'ı `clean` adıyla alınır. `.deb` dosyaları VM'ye kopyalanır; hostta `apt install` çalıştırılmaz.

1. Temiz VM'de `sourcedock_1.3.0_all.deb` kurulumu.
2. Menüden ve terminalden `sourcedock` başlatma.
3. `gio mime`/`xdg-mime` ile `.deb`, AppImage ve Flatpak MIME ilişkileri.
4. Eski `voltapp_1.2.0_all.deb` snapshot'ı; ayar, portable kayıt ve history fixture'ları.
5. SourceDock 1.3.0 upgrade; `dpkg-query`, dosya sahipliği ve kullanıcı verisi karşılaştırması.
6. `apt remove sourcedock`; paket dışı kullanıcı verilerinin beklenen korunumu.
7. `apt purge sourcedock`; paket dosyaları, extension ve desktop cache davranışı.
8. Temiz snapshot'a dönüş, yeniden kurulum ve tekrar yükseltme.

Her adımda `dpkg -L`, `dpkg-query`, `find ~/.config ~/.local/share`, `gio mime` ve uygulama başlatma çıktısı kaydedilir. `Replaces`, `Breaks` ve `Provides` yalnızca gerçek upgrade ile PASS sayılır; mevcut metadata/simülasyon bunu kanıtlamaz.

VM içindeki örnek yaşam döngüsü komutları:

```bash
# VM snapshot: voltapp-old
sudo apt install ./voltapp_1.2.0_all.deb
dpkg-query -W -f='${Package} ${Version} ${Status}\n' voltapp
cp -a ~/.config/voltapp /tmp/voltapp-config-before 2>/dev/null || true

# VM snapshot: upgrade-source-dock
sudo apt install ./sourcedock_1.3.0_all.deb
dpkg-query -W -f='${Package} ${Version} ${Status}\n' sourcedock
command -v sourcedock
command -v voltapp
gio mime application/vnd.debian.binary-package

# Ayrı snapshot: remove ve purge
sudo apt remove -y sourcedock
sudo apt purge -y sourcedock
dpkg-query -W -f='${Package} ${Status}\n' sourcedock 2>/dev/null || true
```

`apt install`, `remove` ve `purge` satırları yalnızca disposable VM içinde çalıştırılmalıdır. Ana sistemde bu komutlar çalıştırılmayacaktır.

## 4. Provider kabul planı

Bu testler yalnızca disposable VM snapshot'ında ve açık kullanıcı onayıyla yapılmalıdır. Firmware yazma testi kapsam dışıdır.

| Sağlayıcı | Güvenli fixture | Kabul akışı |
| --- | --- | --- |
| APT | VM depolarındaki küçük test paketi | install, remove, update, cancel, history ve tekrar deneme |
| Flatpak | VM'de izin verilen küçük Flathub fixture'ı | user install/remove/update, network error, cancel, retry |
| Snap | VM'de `hello-world` gibi güvenli fixture | install/remove/refresh, timeout, cancel, retry ve subprocess temizliği |

Her işlem öncesi/sonrası provider listesi, SourceDock history kaydı, exit code, kullanıcı onayı ve süreç ağacı saklanır. Snap timeout senaryosunda `ps`, `/proc`, child PID ve thread cleanup ölçülmeden PASS yazılmaz.

VM snapshot'ında örnek gerçek transaction akışı:

```bash
# APT fixture
sudo apt install -y hello
sudo apt remove -y hello

# Flatpak fixture; VM'de önceden izin verilen remote kullanılmalı
flatpak --user install -y flathub org.gnome.Calculator
flatpak --user update -y org.gnome.Calculator
flatpak --user uninstall -y org.gnome.Calculator

# Snap fixture
sudo snap install hello-world
sudo snap refresh hello-world
sudo snap remove hello-world
```

Bu komutlar planın parçasıdır, bu ana sistemde çalıştırılmadı. Flatpak remote ve Snap daemon hazırlığı da VM snapshot'ının içinde yapılmalıdır.

## 5. GNOME Shell 46 kabul senaryosu

Gerçek GNOME 46 masaüstü oturumu gerekir; `gnome-shell --version` tek başına yeterli değildir.

1. VM'de GNOME Shell 46 oturumuna giriş yap.
2. Paket veya extension klasörünü kur; `gnome-extensions list` ile UUID'yi doğrula.
3. `gnome-extensions enable sourcedock-menu@aliafacan.dev` çalıştır.
4. Uygulamalar ekranında bir uygulamaya sağ tıkla.
5. `SourceDock ile ayrıntıları göster` ve `SourceDock ile kaldır` eylemlerinin görünmesini kontrol et.
6. Details action'ın doğru uygulama ID'sini, Uninstall action'ın kullanıcı onayını açtığını kontrol et.
7. Oturumu yeniden başlat; sağ tık menüsünü tekrar kontrol et.
8. `journalctl --user -b` ve GNOME Shell loglarında extension hatası ara.
9. Disable/remove sonrası menü eylemlerinin kaybolduğunu kontrol et.

Bu oturumda extension dosyası ve metadata statik olarak kontrol edildi; gerçek etkin oturum olmadığı için sonuç **BLOCKED**.

## 6. AppStream, desktop, D-Bus ve paket yolu denetimi

Mevcut statik zincir **PASS**:

- AppStream ID: `dev.aliafacan.sourcedock`.
- Metainfo dosyası: `/usr/share/metainfo/dev.aliafacan.sourcedock.metainfo.xml`.
- Launchable desktop ID: `sourcedock.desktop`.
- Desktop Exec: `/usr/bin/sourcedock %F`.
- Desktop icon/WM class: `sourcedock`.
- Package binary: `/usr/bin/sourcedock`.
- Legacy binary/desktop: `/usr/bin/voltapp`, hidden `voltapp.desktop`.
- `appstreamcli validate --no-net`: başarılı.
- `desktop-file-validate packaging/sourcedock.desktop`: başarılı; yalnızca kategori hint'i var.
- Paket içinde eski büyük harfli metainfo yolu bulunmuyor.

Kaynakta `Gtk.Application`, `Gio.Application`, `DBusActivatable`, D-Bus service veya bus-name tanımı bulunmuyor. Uygulama klasik `Gtk.main()` ile çalışıyor; bu nedenle AppStream ID değişikliğinin güncellenecek bir D-Bus well-known name'i yok. GNOME extension'ın session bus üzerinden enable edilmesi ayrı bir GNOME runtime kabulüdür ve henüz test edilmemiştir.

## Karar

Bu turda yeni showcase üretilmedi ve eski ekran görüntüleri yeni sürüm adıyla tekrar paketlenmedi. Ortam hazırlığı için koşucu ve bu plan eklendi. Yayın engelleri, araçlar kullanıcı onayıyla kurulup X11/VM/GNOME kabul kanıtları elde edilene kadar **BLOCKED** kalır.
