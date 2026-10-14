#!/usr/bin/env python3
"""Yerel paket ve kurulum formatlarının (.deb, .AppImage, arşivler, .flatpakref, .rpm) yönetimi."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from email.parser import Parser

from sourcedock.core.errors import BackendError
from sourcedock.core.models import (
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
    InstalledPackageStatus,
    LocalPackageInfo,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.portable import register_portable_app, load_portable_registry, validate_portable_path
from sourcedock.backend.archive_safety import safe_extract_archive
from sourcedock.backend.desktop_entries import render_desktop_entry


SUPPORTED_EXTENSIONS = (
    ".deb",
    ".appimage",
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".txz",
    ".tar.bz2",
    ".tbz2",
    ".zip",
    ".flatpakref",
    ".flatpak",
    ".rpm",
)


def detect_package_format(file_path: str) -> str | None:
    """Dosya yolundan paket formatını tespit eder."""
    lowered = file_path.lower()
    if lowered.endswith(".deb"):
        return "deb"
    if lowered.endswith(".appimage"):
        return "appimage"
    if any(
        lowered.endswith(ext)
        for ext in (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tbz2", ".zip", ".tar")
    ):
        return "archive"
    if lowered.endswith(".flatpakref"):
        return "flatpakref"
    if lowered.endswith(".flatpak"):
        return "flatpak"
    if lowered.endswith(".rpm"):
        return "rpm"
    return None


def _get_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def _clean_name(filename: str) -> str:
    name = Path(filename).name
    # bilinen uzantıları kaldır
    for ext in (
        ".tar.gz",
        ".tar.xz",
        ".tar.bz2",
        ".tgz",
        ".txz",
        ".tbz2",
        ".appimage",
        ".deb",
        ".zip",
        ".flatpakref",
        ".flatpak",
        ".rpm",
    ):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    # mimari ve sürüm kalıntılarını temizle
    name = re.sub(r"[-_](x86_64|amd64|arm64|aarch64|i386|all|linux)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[-_]v?\d+(\.\d+)*.*$", "", name)
    name = name.replace("-", " ").replace("_", " ").strip()
    return name.title() or "Uygulama"


# ---------------------------------------------------------------------------
# İnceleme (Inspection) Fonksiyonları
# ---------------------------------------------------------------------------


def inspect_deb(runner: CommandRunner, file_path: str) -> LocalPackageInfo:
    """Bir .deb dosyasının metaverilerini okur."""
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    info = LocalPackageInfo(
        file_path=file_path,
        format="deb",
        name=Path(file_path).stem.split("_")[0],
        size_bytes=size_bytes,
        icon="package-x-generic",
    )

    if runner.command_exists("dpkg-deb"):
        res = runner.run(["dpkg-deb", "--field", file_path], timeout=15)
        if res.returncode == 0:
            fields = Parser().parsestr(res.stdout)
            info.name = fields.get("Package", info.name).strip()
            info.version = fields.get("Version", "").strip()
            info.architecture = fields.get("Architecture", "").strip()
            info.maintainer = fields.get("Maintainer", "").strip()
            if fields.get("Installed-Size", "").strip().isdigit():
                kib = int(fields["Installed-Size"])
                info.installed_size = _format_size(kib * 1024)
            info.dependencies = [
                value.strip()
                for value in fields.get("Depends", "").replace("\n", " ").split(",")
                if value.strip()
            ]
            if fields.get("Description"):
                full_desc = fields["Description"].strip()
                lines = full_desc.splitlines()
                info.summary = lines[0].strip() if lines else ""
                info.description = "\n".join("" if line.strip() == "." else line.strip() for line in lines)
    return info


def inspect_appimage(runner: CommandRunner, file_path: str) -> LocalPackageInfo:
    """Bir .AppImage dosyasının metaverilerini inceler ve ikonunu ayıklar."""
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    name = _clean_name(file_path)
    ver_match = re.search(r"[-_]v?(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9]+)?)", Path(file_path).name)
    version = ver_match.group(1) if ver_match else ""

    info = LocalPackageInfo(
        file_path=file_path,
        format="appimage",
        name=name,
        version=version,
        summary="",
        description="",
        size_bytes=size_bytes,
        icon="application-x-executable",
        architecture="",
    )
    info.extra_info["verification"] = "unverified"
    info.extra_info["metadata_inspection"] = "filename-only"
    try:
        with open(file_path, "rb") as image:
            header = image.read(20)
        if header[:4] == b"\x7fELF" and len(header) >= 20:
            machine = int.from_bytes(header[18:20], "little" if header[5] == 1 else "big")
            info.architecture = {62: "x86_64", 183: "aarch64", 3: "i386", 40: "arm"}.get(machine, "")
    except OSError:
        pass

    # İkon ve gömülü masaüstü dosyasını ayıklamayı dene
    try:
        icon_path = _extract_appimage_icon_and_info(file_path, info)
        if icon_path:
            info.icon = icon_path
    except Exception:
        pass

    return info


def _extract_appimage_icon_and_info(file_path: str, info: LocalPackageInfo) -> str | None:
    """Use conservative metadata until a non-executing AppImage parser is available."""
    return None


def inspect_archive(runner: CommandRunner, file_path: str) -> LocalPackageInfo:
    """Taşınabilir bir arşivin (.tar.gz, .zip vb.) içeriğini inceler."""
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    name = _clean_name(file_path)
    ver_match = re.search(r"[-_]v?(\d+\.\d+(?:\.\d+)?)", Path(file_path).name)
    version = ver_match.group(1) if ver_match else ""

    info = LocalPackageInfo(
        file_path=file_path,
        format="archive",
        name=name,
        version=version,
        summary="",
        description="",
        size_bytes=size_bytes,
        icon="package-x-generic",
    )

    # Content is inspected only by the bounded extractor after user confirmation.
    info.extra_info["metadata_inspection"] = "filename-only"
    return info


def inspect_flatpakref(file_path: str) -> LocalPackageInfo:
    """Bir .flatpakref veya .flatpak paketini inceler."""
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    is_ref = file_path.lower().endswith(".flatpakref")
    info = LocalPackageInfo(
        file_path=file_path,
        format="flatpakref" if is_ref else "flatpak",
        name=Path(file_path).stem,
        size_bytes=size_bytes,
        icon="package-x-generic",
        summary="",
    )

    if is_ref:
        try:
            config = configparser.ConfigParser()
            config.read(file_path, encoding="utf-8")
            if "Flatpak Ref" in config:
                sec = config["Flatpak Ref"]
                info.name = sec.get("Title", sec.get("Name", info.name))
                info.version = sec.get("Branch", "")
                info.summary = sec.get("Comment", info.summary)
                info.description = sec.get("Description", info.summary)
                if "Icon" in sec:
                    info.icon = sec.get("Icon")
                if "Url" in sec:
                    info.extra_info["remote_url"] = sec.get("Url")
                if "Name" in sec:
                    info.extra_info["app_id"] = sec.get("Name")
        except Exception:
            pass
    else:
        # .flatpak bundle: ikili başlıktan ref ve sürüm bilgilerini çıkar
        try:
            with open(file_path, "rb") as fh:
                sample = fh.read(131072)
                match = re.search(rb"app/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)", sample)
                if match:
                    app_id = match.group(1).decode("ascii", errors="ignore")
                    arch = match.group(2).decode("ascii", errors="ignore")
                    branch = match.group(3).decode("ascii", errors="ignore")
                    info.extra_info["app_id"] = app_id
                    info.architecture = arch
                    info.version = branch
                    pretty_name = app_id.split(".")[-1].replace("-", " ").title()
                    info.name = pretty_name
            ver_m = re.search(r"[-_]v?(\d+\.\d+(?:\.\d+)?)", Path(file_path).name)
            if ver_m:
                info.version = ver_m.group(1)
        except Exception:
            pass

    return info


def inspect_rpm(runner: CommandRunner, file_path: str) -> LocalPackageInfo:
    """Bir .rpm dosyasını inceler."""
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    name = _clean_name(file_path)
    info = LocalPackageInfo(
        file_path=file_path,
        format="rpm",
        name=name,
        size_bytes=size_bytes,
        icon="package-x-generic",
        summary="",
    )

    if runner.command_exists("rpm"):
        res = runner.run(["rpm", "-qip", file_path], timeout=15)
        if res.returncode == 0:
            content = res.stdout
            name_m = re.search(r"^\s*Name\s*:\s*(.+)$", content, re.MULTILINE)
            ver_m = re.search(r"^\s*Version\s*:\s*(.+)$", content, re.MULTILINE)
            arch_m = re.search(r"^\s*Architecture\s*:\s*(.+)$", content, re.MULTILINE)
            summ_m = re.search(r"^\s*Summary\s*:\s*(.+)$", content, re.MULTILINE)
            desc_m = re.search(
                r"^\s*Description\s*:\s*\n(.+?)(?=\n[A-Z][a-zA-Z\s]+:|\Z)", content, re.MULTILINE | re.DOTALL
            )

            if name_m:
                info.name = name_m.group(1).strip()
            if ver_m:
                info.version = ver_m.group(1).strip()
            if arch_m:
                info.architecture = arch_m.group(1).strip()
            if summ_m:
                info.summary = summ_m.group(1).strip()
            if desc_m:
                info.description = desc_m.group(1).strip()

    return info


def inspect_local_package(runner: CommandRunner, file_path: str) -> LocalPackageInfo:
    """Dosya yolunu analiz edip formatına uygun LocalPackageInfo nesnesi döner."""
    fmt = detect_package_format(file_path)
    if fmt == "deb":
        return inspect_deb(runner, file_path)
    if fmt == "appimage":
        return inspect_appimage(runner, file_path)
    if fmt == "archive":
        return inspect_archive(runner, file_path)
    if fmt in ("flatpakref", "flatpak"):
        return inspect_flatpakref(file_path)
    if fmt == "rpm":
        return inspect_rpm(runner, file_path)

    # Desteklenmeyen veya genel dosya
    size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    return LocalPackageInfo(
        file_path=file_path,
        format=fmt or "unknown",
        name=Path(file_path).stem,
        size_bytes=size_bytes,
        icon="package-x-generic",
        summary="Yerel Dosya",
    )


def compare_versions(v1: str, v2: str) -> int:
    """v1 < v2 ise -1, v1 == v2 ise 0, v1 > v2 ise 1 döndürür."""
    v1_clean = re.sub(r"^[vV]", "", str(v1).strip())
    v2_clean = re.sub(r"^[vV]", "", str(v2).strip())
    if v1_clean == v2_clean:
        return 0

    if shutil.which("dpkg"):
        try:
            res_lt = subprocess.run(
                ["dpkg", "--compare-versions", v1_clean, "lt", v2_clean],
                capture_output=True,
                timeout=2,
            )
            if res_lt.returncode == 0:
                return -1
            res_gt = subprocess.run(
                ["dpkg", "--compare-versions", v1_clean, "gt", v2_clean],
                capture_output=True,
                timeout=2,
            )
            if res_gt.returncode == 0:
                return 1
            return 0
        except Exception:
            pass

    # Fallback akıllı token ayrıştırma
    def tokenize(v: str) -> list[int | str]:
        return [int(part) if part.isdigit() else part for part in re.findall(r"\d+|\D+", v)]

    t1 = tokenize(v1_clean)
    t2 = tokenize(v2_clean)
    for p1, p2 in zip(t1, t2):
        if type(p1) != type(p2):
            p1, p2 = str(p1), str(p2)
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1
    if len(t1) < len(t2):
        return -1
    elif len(t1) > len(t2):
        return 1
    return 0


def get_installed_package_status(runner: CommandRunner, info: LocalPackageInfo) -> InstalledPackageStatus:
    """Paketin kurulu olup olmadığını ve mevcut sürümünü karşılaştırarak durumunu döndürür."""
    if not info:
        return InstalledPackageStatus(is_installed=False, status="not_installed")

    fmt = info.format
    installed_ver = ""
    is_inst = False

    if fmt == "deb":
        pkg_name = info.extra_info.get("package_name") or info.name
        res = runner.run(["dpkg-query", "-W", "-f=${Status}###${Version}", pkg_name], timeout=5, check=False)
        if "install ok installed" in res.stdout:
            is_inst = True
            parts = res.stdout.strip().split("###")
            if len(parts) > 1:
                installed_ver = parts[-1].strip()

    elif fmt in ("flatpak", "flatpakref"):
        if runner.command_exists("flatpak"):
            candidates = []
            if "app_id" in info.extra_info:
                candidates.append(info.extra_info["app_id"])
            if info.name:
                candidates.append(info.name)

            for cand in candidates:
                res = runner.run(["flatpak", "info", cand], timeout=5, check=False)
                if res.returncode == 0:
                    is_inst = True
                    for line in res.stdout.splitlines():
                        if line.lower().startswith("version:"):
                            installed_ver = line.split(":", 1)[1].strip()
                    break

            if not is_inst:
                res = runner.run(
                    ["flatpak", "list", "--columns=application,name,version"], timeout=5, check=False
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.split("\t")
                        app_id = parts[0].strip() if len(parts) > 0 else ""
                        app_name = parts[1].strip() if len(parts) > 1 else ""
                        ver = parts[2].strip() if len(parts) > 2 else ""
                        for cand in candidates:
                            cand_l = cand.lower()
                            if cand_l in app_id.lower() or cand_l in app_name.lower():
                                is_inst = True
                                installed_ver = ver
                                break
                        if is_inst:
                            break

    elif fmt in ("appimage", "archive"):
        from sourcedock.backend.portable import find_portable_app

        app = find_portable_app(info.name)
        if app is not None:
            is_inst = True
            installed_ver = app.version or ""

    elif fmt == "rpm":
        if runner.command_exists("rpm"):
            pkg_name = info.extra_info.get("package_name") or info.name
            res = runner.run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", pkg_name], timeout=5, check=False)
            if res.returncode == 0 and res.stdout.strip() and "is not installed" not in res.stdout:
                is_inst = True
                installed_ver = res.stdout.strip()

    if not is_inst:
        return InstalledPackageStatus(is_installed=False, status="not_installed")

    new_ver = info.version.strip()
    if installed_ver and new_ver:
        cmp = compare_versions(installed_ver, new_ver)
        if cmp < 0:
            status = "upgradable"
        elif cmp > 0:
            status = "downgrade"
        else:
            status = "same_version"
    else:
        status = "same_version"

    return InstalledPackageStatus(
        is_installed=True,
        installed_version=installed_ver,
        status=status,
    )


def is_package_installed(runner: CommandRunner, info: LocalPackageInfo) -> bool:
    """Paketin sistemde halihazırda kurulu olup olmadığını kontrol eder."""
    return get_installed_package_status(runner, info).is_installed


# ---------------------------------------------------------------------------
# Kurulum (Installation) Fonksiyonları
# ---------------------------------------------------------------------------


def install_local_deb(runner: CommandRunner, file_path: str) -> None:
    """Yerel bir .deb dosyasını APT veya dpkg ile kurar."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise BackendError(f"Dosya bulunamadi: {abs_path}")

    # Modern apt-get doğrudan yerel dosya yolu ile bağımlılıkları çözerek kurar
    if runner.command_exists("apt-get"):
        cmd = ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "install", "-y", abs_path]
        runner.run_privileged(cmd, timeout=1800)
        return

    # Fallback: dpkg -i
    if runner.command_exists("dpkg"):
        runner.run_privileged(["dpkg", "-i", abs_path], timeout=900)
        if runner.command_exists("apt-get"):
            runner.run_privileged(["apt-get", "-f", "install", "-y"], timeout=900)
        return

    raise BackendError("Sistemde 'apt-get' veya 'dpkg' paket yoneticisi bulunamadi.")


def install_local_appimage(
    runner: CommandRunner,
    file_path: str,
    target_dir: str | None = None,
    create_desktop: bool = True,
) -> str:
    """AppImage dosyasını ~/Applications dizinine taşır/kopyalar ve kısayol oluşturur."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise BackendError(f"Dosya bulunamadi: {abs_path}")

    dest_dir = Path(target_dir).expanduser() if target_dir else Path.home() / "Applications"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / Path(abs_path).name
    if abs_path != str(dest_file):
        try:
            shutil.move(abs_path, dest_file)
        except Exception:
            shutil.copy2(abs_path, dest_file)
            try:
                os.remove(abs_path)
            except OSError:
                pass

    # Çalıştırma izni ver (chmod +x)
    try:
        os.chmod(
            dest_file, os.stat(dest_file).st_mode | stat.S_IXUSR | stat.S_IRUSR | stat.S_IXGRP | stat.S_IXOTH
        )
    except OSError:
        pass

    if create_desktop:
        try:
            info = inspect_appimage(runner, str(dest_file))
            desktop_dir = _get_data_home() / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)
            safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", info.name.lower())
            desktop_file = desktop_dir / f"appimage-{safe_slug}.desktop"

            icon_value = info.icon if info.icon and Path(info.icon).exists() else "application-x-executable"
            content = render_desktop_entry(info.name, dest_file, icon_value, appimage_path=dest_file)
            with open(desktop_file, "w", encoding="utf-8") as fh:
                fh.write(content)

            if runner.command_exists("update-desktop-database"):
                runner.run(["update-desktop-database", str(desktop_dir)], timeout=10, check=False)
        except OSError:
            pass

    return str(dest_file)


def _safe_extract_archive(archive_path: str, dest_dir: Path) -> None:
    safe_extract_archive(archive_path, dest_dir)


def install_local_archive(
    runner: CommandRunner,
    file_path: str,
    extract_dir: str | None = None,
    create_desktop: bool = True,
) -> tuple[str, str]:
    """Taşınabilir arşivi ~/.local/share/sourcedock/apps altına açar ve sisteme kaydeder."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise BackendError(f"Dosya bulunamadi: {abs_path}")

    info = inspect_archive(runner, abs_path)
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", info.name.lower())

    base_apps_dir = (
        Path(extract_dir).expanduser() if extract_dir else _get_data_home() / "sourcedock" / "apps"
    )
    if base_apps_dir.is_symlink():
        raise BackendError("Portable destination is a symbolic link.")
    base_apps_dir.mkdir(parents=True, exist_ok=True)
    base_apps_dir = base_apps_dir.resolve()
    target_app_dir = base_apps_dir / safe_slug
    if target_app_dir.is_symlink():
        raise BackendError("Portable installation is a symbolic link.")
    existing = None
    if target_app_dir.exists():
        existing = next(
            (
                (key, item)
                for key, item in load_portable_registry().items()
                if isinstance(item, dict) and item.get("install_path") == str(target_app_dir)
            ),
            None,
        )
        if not existing:
            raise BackendError("Refusing to replace an unmanaged application directory.")
        validate_portable_path(target_app_dir, existing[1], existing[0])

    desktop_file = None
    old_desktop = None
    if create_desktop:
        desktop_dir = _get_data_home() / "applications"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = desktop_dir / f"sourcedock-portable-{safe_slug}.desktop"
        if desktop_file.is_symlink() or (
            desktop_file.exists() and (not existing or existing[1].get("desktop_file") != str(desktop_file))
        ):
            raise BackendError("Refusing to replace an unmanaged desktop shortcut.")
        old_desktop = desktop_file.read_bytes() if desktop_file.exists() else None

    # Validate a complete candidate before replacing the working installation.
    with tempfile.TemporaryDirectory(prefix=f".{safe_slug}-", dir=base_apps_dir) as staging:
        staged_dir = Path(staging) / "payload"
        _safe_extract_archive(abs_path, staged_dir)
        staged_exec = _find_main_executable(staged_dir, info.name)
        if not staged_exec:
            raise BackendError("No executable was found in the archive.")
        exec_relative = staged_exec.relative_to(staged_dir)
        staged_exec.chmod(0o755)
        main_exec = target_app_dir / exec_relative
        icon_candidate = _find_archive_icon(staged_dir, safe_slug)
        icon_path = (
            str(target_app_dir / Path(icon_candidate).relative_to(staged_dir))
            if icon_candidate != "package-x-generic"
            else icon_candidate
        )
        desktop_text = (
            render_desktop_entry(info.name, main_exec, icon_path, target_app_dir) if desktop_file else ""
        )
        backup = Path(staging) / "previous"
        if target_app_dir.exists():
            target_app_dir.rename(backup)
        try:
            staged_dir.rename(target_app_dir)
            if desktop_file:
                desktop_file.write_text(desktop_text, encoding="utf-8")
            register_portable_app(
                info.name,
                info.version,
                str(target_app_dir),
                str(main_exec),
                str(desktop_file) if desktop_file else "",
                icon=icon_path,
                managed_root=str(base_apps_dir),
            )
        except Exception:
            if target_app_dir.exists():
                shutil.rmtree(target_app_dir)
            if backup.exists():
                backup.rename(target_app_dir)
            if desktop_file:
                if old_desktop is not None:
                    desktop_file.write_bytes(old_desktop)
                elif desktop_file.exists():
                    desktop_file.unlink()
            raise

    if desktop_file and runner.command_exists("update-desktop-database"):
        try:
            runner.run(["update-desktop-database", str(desktop_file.parent)], timeout=10, check=False)
        except BackendError:
            pass

    return str(target_app_dir), str(main_exec)


def _find_main_executable(app_dir: Path, app_name: str) -> Path | None:
    """Arşiv dizinindeki ana çalıştırılabilir ikiliyi veya betiği bulur."""
    name_clean = re.sub(r"[^a-zA-Z0-9]", "", app_name.lower())
    candidates: list[Path] = []

    for path in app_dir.glob("**/*"):
        if not path.is_file() or path.is_symlink():
            continue
        # Hariç tutulan dosyalar
        fn = path.name.lower()
        if any(bad in fn for bad in ("uninstall", "helper", "crashpad", "update", ".so", ".a", ".o")):
            continue

        # İsim eşleşmesi yüksek öncelikli
        fn_clean = re.sub(r"[^a-zA-Z0-9]", "", fn)
        if fn_clean == name_clean:
            return path

        # Çalıştırma izni veya ELF/script kontrolü
        is_exec = os.access(path, os.X_OK)
        if not is_exec:
            try:
                with open(path, "rb") as fh:
                    header = fh.read(4)
                    if header == b"\x7fELF" or header.startswith(b"#!"):
                        is_exec = True
            except OSError:
                pass

        if is_exec:
            candidates.append(path)

    if not candidates:
        return None

    # En sığ dizindeki ve en uygun adlandırılmış dosyayı tercih et
    candidates.sort(key=lambda p: (len(p.parts), -p.stat().st_size))
    return candidates[0]


def _find_archive_icon(app_dir: Path, slug: str) -> str:
    """Arşiv içindeki en yüksek çözünürlüklü ikonu tespit eder ve sisteme kaydeder."""
    icons: list[Path] = []
    for ext in ("*.png", "*.svg"):
        icons.extend(app_dir.glob(f"**/{ext}"))

    if not icons:
        return "package-x-generic"

    # En büyük boyutlu ikonu al
    icons.sort(key=lambda p: p.stat().st_size, reverse=True)
    best = icons[0]

    return str(best)


def install_local_flatpak(
    runner: CommandRunner,
    file_path: str,
    scope: str = "--user",
    reinstall: bool = False,
) -> None:
    """Flatpak paketini (.flatpak bundle) veya .flatpakref referansını kurar."""
    abs_path = os.path.abspath(file_path)
    if not runner.command_exists("flatpak"):
        raise BackendError("Sistemde 'flatpak' paket yoneticisi yuklu degil.")

    scope_flag = "--system" if scope == "--system" else "--user"

    if runner._output_callback is not None:
        action_desc = "yeniden kuruluyor" if reinstall else "kuruluyor"
        runner._output_callback(f"Flatpak paketi çözümleniyor ({scope_flag}, {action_desc})...")
        runner._output_callback(f"Dosya: {Path(abs_path).name}")
        runner._output_callback("Depo bilgileri ve bağımlı çalışma ortamı (runtime) taranıyor...")

    base_cmd = ["flatpak", "install", scope_flag, "-y"]
    if reinstall:
        base_cmd.append("--reinstall")

    if abs_path.lower().endswith(".flatpakref"):
        cmd = [*base_cmd, "--from", abs_path]
    else:
        cmd = [*base_cmd, abs_path]

    try:
        if scope_flag == "--system":
            runner.run_privileged(cmd, timeout=1800)
        else:
            try:
                runner.run(cmd, timeout=1800, check=True)
            except BackendError as exc:
                err_text = str(exc).lower()
                # Eğer ConfigureRemote veya polkit izni hatası alınırsa sistem seviyesinde (sudo ile) tekrar dene
                if (
                    "not allowed for user" in err_text
                    or "configureremote" in err_text
                    or "system operation" in err_text
                    or "permission denied" in err_text
                ):
                    if runner._output_callback is not None:
                        runner._output_callback(
                            "Sistem seviyesinde izin gerekiyor, yönetici moduna geçiliyor..."
                        )
                    sys_cmd = ["flatpak", "install", "--system", "-y"]
                    if reinstall:
                        sys_cmd.append("--reinstall")
                    if abs_path.lower().endswith(".flatpakref"):
                        sys_cmd.extend(["--from", abs_path])
                    else:
                        sys_cmd.append(abs_path)
                    runner.run_privileged(sys_cmd, timeout=1800)
                else:
                    raise
    except BackendError as exc:
        err_text = str(exc).lower()
        if "already installed" in err_text or "zaten kurulu" in err_text:
            if runner._output_callback is not None:
                runner._output_callback(
                    "✓ Bu uygulama zaten sisteminizde kurulu durumda. Kurulum başarıyla doğrulandı."
                )
            return
        raise


def install_local_rpm(runner: CommandRunner, file_path: str) -> None:
    """Fedora / RHEL / openSUSE RPM paketini kurar."""
    abs_path = os.path.abspath(file_path)
    if runner.command_exists("dnf"):
        runner.run_privileged(["dnf", "install", "-y", abs_path], timeout=1800)
    elif runner.command_exists("zypper"):
        runner.run_privileged(["zypper", "install", "-y", abs_path], timeout=1800)
    elif runner.command_exists("rpm"):
        runner.run_privileged(["rpm", "-ivh", abs_path], timeout=1800)
    else:
        raise BackendError("Sistemde RPM, DNF veya Zypper paket yoneticisi bulunamadi.")


def launch_local_package(runner: CommandRunner, info: LocalPackageInfo) -> bool:
    """Kurulan yerel paketi sistemde başlatır."""
    if not info:
        return False

    fmt = info.format
    # 1. Flatpak
    if fmt in ("flatpak", "flatpakref"):
        app_id = info.extra_info.get("app_id") or info.name
        if runner.command_exists("flatpak"):
            runner.spawn(["flatpak", "run", app_id])
            return True

    # 2. AppImage
    if fmt == "appimage":
        candidates = [
            Path.home() / "Applications" / Path(info.file_path).name,
            Path(info.file_path),
        ]
        for cand in candidates:
            if cand.exists() and os.access(cand, os.X_OK):
                runner.spawn([str(cand)])
                return True

    # 3. Archive
    if fmt == "archive":
        from sourcedock.backend.portable import find_portable_app

        app = find_portable_app(info.name)
        if app and app.executable and os.path.exists(app.executable):
            runner.spawn([app.executable])
            return True

    # 4. Debian / RPM (.desktop dosyaları veya komut)
    pkg_name = (info.extra_info.get("package_name") or info.name).lower()
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", pkg_name)

    desktop_dirs = [
        Path.home() / ".local/share/applications",
        Path("/usr/share/applications"),
    ]
    for d in desktop_dirs:
        if not d.exists():
            continue
        for cand_name in (f"{pkg_name}.desktop", f"{info.name}.desktop"):
            df = d / cand_name
            if df.exists():
                if runner.command_exists("gtk-launch"):
                    runner.spawn(["gtk-launch", cand_name])
                    return True
                if runner.command_exists("gio"):
                    runner.spawn(["gio", "launch", str(df)])
                    return True

        for df in d.glob("*.desktop"):
            df_stem = df.stem.lower()
            if pkg_name in df_stem or (
                len(clean_name) > 3 and clean_name in re.sub(r"[^a-zA-Z0-9]", "", df_stem)
            ):
                if runner.command_exists("gtk-launch"):
                    runner.spawn(["gtk-launch", df.name])
                    return True
                if runner.command_exists("gio"):
                    runner.spawn(["gio", "launch", str(df)])
                    return True

    for cand_cmd in (pkg_name, info.name.lower()):
        if runner.command_exists(cand_cmd):
            runner.spawn([cand_cmd])
            return True

    return False
