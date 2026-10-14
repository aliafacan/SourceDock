#!/usr/bin/env python3
"""MIME türleri ve masaüstü dosya ilişkilendirmeleri yönetimi."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

PACKAGE_MIME_TYPES = (
    # Debian / Ubuntu / Zorin
    "application/vnd.debian.binary-package",
    "application/x-deb",
    "application/x-debian-package",
    # Fedora / RHEL / openSUSE
    "application/x-rpm",
    "application/x-redhat-package-manager",
    # AppImage
    "application/x-appimage",
    "application/vnd.appimage",
    # Flatpak
    "application/vnd.flatpak",
    "application/vnd.flatpak.ref",
    "application/vnd.flatpak.repo",
)


def _get_clean_env() -> dict[str, str]:
    """Snap ortam değişkenlerinden arındırılmış ve yerel XDG yollarını içeren sistem ortamını döndürür."""
    env = dict(os.environ)
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        if var in env and "/snap/" in env[var]:
            del env[var]
    if "XDG_DATA_DIRS" in env and "/snap/" in env["XDG_DATA_DIRS"]:
        parts = [p for p in env["XDG_DATA_DIRS"].split(":") if "/snap/" not in p and p.strip()]
        if parts:
            env["XDG_DATA_DIRS"] = ":".join(parts)
        else:
            del env["XDG_DATA_DIRS"]
    local_share = os.path.expanduser("~/.local/share")
    current_dirs = env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    if local_share not in current_dirs.split(":"):
        env["XDG_DATA_DIRS"] = f"{local_share}:{current_dirs}"
    return env


def get_project_root() -> Path:
    """SourceDock projesinin kök dizinini döndürür."""
    return Path(__file__).resolve().parent.parent.parent


def get_launcher_path() -> str:
    """Masaüstü kısayolu için çalıştırılabilir dosya yolunu döndürür."""
    if os.path.exists("/usr/bin/sourcedock") and os.access("/usr/bin/sourcedock", os.X_OK):
        return "/usr/bin/sourcedock"
    sys_bin = shutil.which("sourcedock")
    if sys_bin and os.path.isabs(sys_bin):
        return sys_bin
    root = get_project_root()
    run_sh = root / "run.sh"
    if run_sh.exists() and os.access(run_sh, os.X_OK):
        return str(run_sh.resolve())
    main_py = root / "main.py"
    return f"{shutil.which('python3') or 'python3'} {str(main_py.resolve())}"


def get_icon_path() -> str:
    """SourceDock logo ikon dosyasının yolunu döndürür."""
    if os.path.exists("/usr/share/icons/hicolor/scalable/apps/sourcedock.svg"):
        return "sourcedock"
    root = get_project_root()
    svg_icon = root / "assets" / "sourcedock.svg"
    if svg_icon.exists():
        return str(svg_icon.resolve())
    png_icon = root / "assets" / "sourcedock.png"
    if png_icon.exists():
        return str(png_icon.resolve())
    return "sourcedock"


def install_desktop_file(custom_dest: Path | None = None) -> Path:
    """Kullanıcının yerel uygulamalar dizinine (~/.local/share/applications) sourcedock.desktop dosyasını yazar."""
    if custom_dest is not None:
        desktop_file = custom_dest
        apps_dir = desktop_file.parent
    else:
        apps_dir = Path(os.path.expanduser("~/.local/share/applications"))
        desktop_file = apps_dir / "sourcedock.desktop"

    apps_dir.mkdir(parents=True, exist_ok=True)

    launcher = get_launcher_path()
    icon = get_icon_path()
    mime_str = ";".join(PACKAGE_MIME_TYPES) + ";"

    content = f"""[Desktop Entry]
Name=SourceDock
GenericName=Paket ve Uygulama Yöneticisi
GenericName[en]=Package and Application Manager
Comment=Linux yazılım kaynaklarını tek yerde yönetin
Comment[en]=Manage Linux software sources in one place
Exec={launcher} %F
Icon={icon}
Terminal=false
Type=Application
Categories=System;PackageManager;Settings;
MimeType={mime_str}
Keywords=sourcedock;package;deb;rpm;appimage;flatpak;install;manager;
StartupWMClass=sourcedock
Actions=Details;Uninstall;Updates;

[Desktop Action Details]
Name=Uygulama Ayrıntıları
Name[en]=Application Details
Exec={launcher} --details sourcedock
Icon=document-properties

[Desktop Action Uninstall]
Name=SourceDock'i Kaldır
Name[en]=Uninstall SourceDock
Exec={launcher} --uninstall sourcedock
Icon=edit-delete

[Desktop Action Updates]
Name=Güncellemeleri Denetle
Name[en]=Check for Updates
Exec={launcher} --updates
Icon=software-update-available
"""
    desktop_file.write_text(content, encoding="utf-8")
    try:
        os.chmod(desktop_file, 0o755)
    except OSError:
        pass

    # İkonu hicolor ikon dizinlerine de kopyala (sistem menüleri için)
    _install_system_icons()

    # Masaüstü veritabanını yenile
    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                env=_get_clean_env(),
            )
        except Exception:
            pass

    return desktop_file


def _install_system_icons() -> None:
    """İkonları ~/.local/share/icons altına yerleştirir."""
    root = get_project_root()
    svg_src = root / "assets" / "sourcedock.svg"
    png_128_src = root / "assets" / "sourcedock_128.png"

    try:
        if svg_src.exists():
            scalable_dir = Path(os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps"))
            scalable_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(svg_src, scalable_dir / "sourcedock.svg")

        if png_128_src.exists():
            png_dir = Path(os.path.expanduser("~/.local/share/icons/hicolor/128x128/apps"))
            png_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png_128_src, png_dir / "sourcedock.png")
    except OSError:
        pass


def update_mimeapps_list(custom_path: Path | None = None) -> None:
    """~/.config/mimeapps.list dosyasına paket türleri için sourcedock.desktop kaydını ekler/günceller."""
    mimeapps_file = custom_path or Path(os.path.expanduser("~/.config/mimeapps.list"))
    try:
        lines: list[str] = []
        if mimeapps_file.exists():
            lines = mimeapps_file.read_text(encoding="utf-8", errors="ignore").splitlines()

        new_lines: list[str] = []
        in_default_section = False
        default_section_found = False
        added_types: set[str] = set()

        for line in lines:
            trimmed = line.strip()
            if trimmed == "[Default Applications]":
                in_default_section = True
                default_section_found = True
                new_lines.append(line)
                continue
            elif trimmed.startswith("[") and in_default_section:
                for mt in PACKAGE_MIME_TYPES:
                    if mt not in added_types:
                        new_lines.append(f"{mt}=sourcedock.desktop;")
                        added_types.add(mt)
                in_default_section = False

            if in_default_section and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                if key in PACKAGE_MIME_TYPES:
                    handlers = [h.strip() for h in val.split(";") if h.strip()]
                    if "sourcedock.desktop" in handlers:
                        handlers.remove("sourcedock.desktop")
                    handlers.insert(0, "sourcedock.desktop")
                    new_lines.append(f"{key}={';'.join(handlers)};")
                    added_types.add(key)
                    continue

            new_lines.append(line)

        if not default_section_found:
            new_lines.append("[Default Applications]")
            for mt in PACKAGE_MIME_TYPES:
                new_lines.append(f"{mt}=sourcedock.desktop;")
        elif in_default_section:
            for mt in PACKAGE_MIME_TYPES:
                if mt not in added_types:
                    new_lines.append(f"{mt}=sourcedock.desktop;")
                    added_types.add(mt)

        mimeapps_file.parent.mkdir(parents=True, exist_ok=True)
        mimeapps_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def is_default_package_handler() -> bool:
    """SourceDock'in birincil paket türleri için varsayılan olup olmadığını kontrol eder."""
    primary_types = (
        "application/vnd.debian.binary-package",
        "application/x-deb",
        "application/x-rpm",
        "application/vnd.appimage",
        "application/x-appimage",
    )
    clean_env = _get_clean_env()

    # 1. gio mime ile kontrol et
    if shutil.which("gio"):
        for mime_type in primary_types:
            try:
                res = subprocess.run(
                    ["gio", "mime", mime_type],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    env=clean_env,
                )
                for line in res.stdout.splitlines():
                    if "default application" in line.lower() or "öntanımlı uygulama" in line.lower():
                        if "sourcedock.desktop" in line.lower():
                            return True
            except Exception:
                pass

    # 2. xdg-mime query default ile kontrol et
    if shutil.which("xdg-mime"):
        for mime_type in primary_types:
            try:
                res = subprocess.run(
                    ["xdg-mime", "query", "default", mime_type],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    env=clean_env,
                )
                if "sourcedock.desktop" in res.stdout.strip().lower():
                    return True
            except Exception:
                pass

    # 3. mimeapps.list dosyasını kontrol et
    mimeapps_path = Path(os.path.expanduser("~/.config/mimeapps.list"))
    if mimeapps_path.exists():
        try:
            content = mimeapps_path.read_text(encoding="utf-8", errors="ignore")
            for line in content.splitlines():
                line = line.strip()
                for mime_type in primary_types:
                    if line.startswith(f"{mime_type}="):
                        val = line.split("=", 1)[1]
                        first_handler = val.split(";")[0].strip()
                        if first_handler == "sourcedock.desktop":
                            return True
        except Exception:
            pass

    return False


def set_as_default_package_handler() -> tuple[bool, str]:
    """SourceDock'i tüm desteklenen paket türleri için varsayılan uygulama olarak atar."""
    try:
        install_desktop_file()
    except Exception as exc:
        return False, f"Masaüstü dosyası oluşturulamadı: {exc}"

    # mimeapps.list güncelle
    update_mimeapps_list()

    has_xdg = bool(shutil.which("xdg-mime"))
    has_gio = bool(shutil.which("gio"))

    if not has_xdg and not has_gio:
        return True, "Masaüstü kısayolu oluşturuldu (xdg-mime veya gio komutu bulunamadı)."

    clean_env = _get_clean_env()
    errors: list[str] = []
    for mime_type in PACKAGE_MIME_TYPES:
        if has_xdg:
            try:
                res = subprocess.run(
                    ["xdg-mime", "default", "sourcedock.desktop", mime_type],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    env=clean_env,
                )
                if res.returncode != 0 and res.stderr.strip():
                    errors.append(f"xdg-mime {mime_type}: {res.stderr.strip()}")
            except Exception as exc:
                errors.append(f"xdg-mime {mime_type}: {exc}")

        if has_gio:
            try:
                res = subprocess.run(
                    ["gio", "mime", mime_type, "sourcedock.desktop"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    env=clean_env,
                )
                if res.returncode != 0 and res.stderr.strip():
                    errors.append(f"gio {mime_type}: {res.stderr.strip()}")
            except Exception as exc:
                errors.append(f"gio {mime_type}: {exc}")

    # MIME önbelleğini yenile
    if shutil.which("update-desktop-database"):
        apps_dir = str(Path(os.path.expanduser("~/.local/share/applications")))
        try:
            subprocess.run(
                ["update-desktop-database", apps_dir], capture_output=True, check=False, env=clean_env
            )
        except Exception:
            pass

    if errors:
        return True, "Büyük ölçüde atandı, ancak bazı türlerde uyarı alındı:\n" + "\n".join(errors[:3])
    return True, "SourceDock başarıyla varsayılan paket yükleyici olarak ayarlandı."
