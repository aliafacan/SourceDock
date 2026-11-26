"""XDG Autostart (~/.config/autostart) yönetimi."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import subprocess

from sourcedock.core.models import UnifiedApplication


@dataclass
class AutostartEntry:
    filename: str
    name: str
    exec_cmd: str
    icon: str
    comment: str
    enabled: bool
    is_system: bool
    path: Path


def _autostart_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "autostart"


def _candidate_filenames(app: UnifiedApplication) -> list[str]:
    names: list[str] = []
    if app.desktop_file:
        names.append(Path(app.desktop_file).name)
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", app.package_name or app.id or app.name).strip("_") or "app"
    names.append(f"sourcedock-{safe_id}.desktop")
    return list(dict.fromkeys(names))


def _find_user_autostart_file(app: UnifiedApplication) -> Path | None:
    auto_dir = _autostart_dir()
    if not auto_dir.is_dir():
        return None
    for name in _candidate_filenames(app):
        path = auto_dir / name
        if path.is_file():
            return path
    return None


def _parse_autostart_enabled(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    hidden = False
    enabled = True
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Hidden="):
            hidden = stripped.split("=", 1)[1].strip().lower() == "true"
        elif stripped.startswith("X-GNOME-Autostart-enabled="):
            enabled = stripped.split("=", 1)[1].strip().lower() != "false"
    return (not hidden) and enabled


def is_autostart_enabled(app: UnifiedApplication) -> bool:
    """Uygulamanın oturum açılışında otomatik başlatılıp başlatılmadığını döner."""
    user_file = _find_user_autostart_file(app)
    if user_file is not None:
        return _parse_autostart_enabled(user_file)
    for name in _candidate_filenames(app):
        sys_file = Path("/etc/xdg/autostart") / name
        if sys_file.is_file():
            return _parse_autostart_enabled(sys_file)
    return False


def set_autostart_enabled(app: UnifiedApplication, enabled: bool) -> None:
    """Uygulama için XDG autostart girdisini oluşturur, günceller veya kaldırır."""
    auto_dir = _autostart_dir()
    auto_dir.mkdir(parents=True, exist_ok=True)
    target_name = _candidate_filenames(app)[0]
    target_path = auto_dir / target_name
    sys_counterpart = Path("/etc/xdg/autostart") / target_name

    if not enabled:
        existing = _find_user_autostart_file(app)
        if existing is not None and not sys_counterpart.is_file():
            existing.unlink(missing_ok=True)
            return
        if sys_counterpart.is_file():
            content = sys_counterpart.read_text(encoding="utf-8", errors="replace")
            lines = [
                ln for ln in content.splitlines()
                if not ln.strip().startswith(("Hidden=", "X-GNOME-Autostart-enabled="))
            ]
            lines.append("Hidden=true")
            lines.append("X-GNOME-Autostart-enabled=false")
            target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    # enabled == True
    source_path: Path | None = None
    if app.desktop_file and Path(app.desktop_file).is_file():
        source_path = Path(app.desktop_file)
    elif sys_counterpart.is_file():
        source_path = sys_counterpart

    if source_path is not None:
        content = source_path.read_text(encoding="utf-8", errors="replace")
        lines = [
            ln for ln in content.splitlines()
            if not ln.strip().startswith(("Hidden=", "X-GNOME-Autostart-enabled="))
        ]
        lines.append("X-GNOME-Autostart-enabled=true")
        target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    exec_cmd = (app.executable or "").strip()
    if not exec_cmd:
        raise ValueError("Application has no executable command for autostart.")
    desktop_content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={app.name}\n"
        f"Exec={exec_cmd}\n"
        f"Icon={app.icon or 'application-x-executable'}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    target_path.write_text(desktop_content, encoding="utf-8")


def _parse_desktop_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    in_entry = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fields
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            in_entry = stripped == "[Desktop Entry]"
            continue
        if in_entry and "=" in stripped:
            k, v = stripped.split("=", 1)
            fields[k.strip()] = v.strip()
    return fields


def list_autostart_entries() -> list[AutostartEntry]:
    """Kullanıcı (~/.config/autostart) ve sistem (/etc/xdg/autostart) başlangıç öğelerini listeler."""
    by_name: dict[str, tuple[Path, bool]] = {}
    sys_dir = Path("/etc/xdg/autostart")
    if sys_dir.is_dir():
        for entry in sorted(sys_dir.glob("*.desktop")):
            by_name[entry.name] = (entry, True)
    user_dir = _autostart_dir()
    if user_dir.is_dir():
        for entry in sorted(user_dir.glob("*.desktop")):
            is_sys = (sys_dir / entry.name).is_file()
            by_name[entry.name] = (entry, is_sys)

    results: list[AutostartEntry] = []
    for filename, (path, is_sys) in by_name.items():
        fields = _parse_desktop_fields(path)
        name = fields.get("Name") or filename.removesuffix(".desktop")
        exec_cmd = fields.get("Exec", "")
        icon = fields.get("Icon", "application-x-executable")
        comment = fields.get("Comment", "")
        hidden = fields.get("Hidden", "false").lower() == "true"
        gnome_enabled = fields.get("X-GNOME-Autostart-enabled", "true").lower() != "false"
        enabled = (not hidden) and gnome_enabled
        results.append(
            AutostartEntry(
                filename=filename,
                name=name,
                exec_cmd=exec_cmd,
                icon=icon,
                comment=comment,
                enabled=enabled,
                is_system=is_sys,
                path=path,
            )
        )
    return sorted(results, key=lambda item: (item.is_system, item.name.casefold()))


def toggle_autostart_entry(entry: AutostartEntry, enabled: bool) -> None:
    """Bir başlangıç öğesini etkinleştirir veya devre dışı bırakır."""
    auto_dir = _autostart_dir()
    auto_dir.mkdir(parents=True, exist_ok=True)
    target_path = auto_dir / entry.filename
    source_path = target_path if target_path.is_file() else entry.path
    if source_path.is_symlink() and not source_path.exists():
        if not enabled:
            target_path.unlink(missing_ok=True)
            return
        raise FileNotFoundError(f"Broken symlink target does not exist: {source_path}")
    content = source_path.read_text(encoding="utf-8", errors="replace")
    lines = [
        ln for ln in content.splitlines()
        if not ln.strip().startswith(("Hidden=", "X-GNOME-Autostart-enabled="))
    ]
    if enabled:
        lines.append("X-GNOME-Autostart-enabled=true")
    else:
        lines.append("Hidden=true")
        lines.append("X-GNOME-Autostart-enabled=false")
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_user_autostart_entry(entry: AutostartEntry) -> None:
    """Kullanıcı tarafından eklenmiş bir başlangıç öğesini (bozuk sembolik bağ dahil) kaldırır."""
    user_path = _autostart_dir() / entry.filename
    if (user_path.is_file() or user_path.is_symlink()) and not entry.is_system:
        user_path.unlink(missing_ok=True)


def create_user_autostart_entry(
    name: str,
    exec_cmd: str,
    *,
    mode: str = "normal",
    icon: str = "application-x-executable",
    comment: str = "",
) -> Path:
    """Kullanıcı için yeni bir XDG autostart .desktop dosyası oluşturur."""
    clean_name = name.strip()
    clean_exec = exec_cmd.strip()
    if not clean_name or not clean_exec:
        raise ValueError("Name and command are required.")

    auto_dir = _autostart_dir()
    auto_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", clean_name.lower()).strip("-") or "custom"
    target = auto_dir / f"sourcedock-{slug}.desktop"
    counter = 2
    while target.exists():
        target = auto_dir / f"sourcedock-{slug}-{counter}.desktop"
        counter += 1

    terminal = "false"
    final_exec = clean_exec
    if mode == "terminal":
        terminal = "true"
    elif mode == "background":
        escaped = clean_exec.replace("'", "'\"'\"'")
        final_exec = f"sh -c '{escaped} >/dev/null 2>&1 &'"

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={clean_name}",
        f"Exec={final_exec}",
        f"Icon={icon.strip() or 'application-x-executable'}",
    ]
    if comment.strip():
        lines.append(f"Comment={comment.strip()}")
    lines.append(f"Terminal={terminal}")
    lines.append("X-GNOME-Autostart-enabled=true")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def detect_autostart_mode(entry: AutostartEntry) -> str:
    """Başlangıç öğesinin mevcut çalışma modunu (normal/background/terminal) tespit eder."""
    fields = _parse_desktop_fields(entry.path)
    if fields.get("Terminal", "false").lower() == "true":
        return "terminal"
    if ">/dev/null 2>&1 &" in entry.exec_cmd:
        return "background"
    return "normal"


def unwrap_autostart_exec(exec_cmd: str) -> str:
    """Arka plan sarmalayıcısı (sh -c '... >/dev/null 2>&1 &') varsa içindeki komutu çıkarır."""
    m = re.match(r"^sh\s+-c\s+'(.+)\s+>/dev/null\s+2>&1\s+&'$", exec_cmd.strip())
    if m:
        return m.group(1).replace("'\"'\"'", "'")
    return exec_cmd


def update_autostart_entry(
    entry: AutostartEntry,
    name: str,
    exec_cmd: str,
    *,
    mode: str = "normal",
    comment: str = "",
) -> Path:
    """Mevcut bir başlangıç öğesini düzenleyip kullanıcı autostart dizinine kaydeder."""
    clean_name = name.strip()
    clean_exec = exec_cmd.strip()
    if not clean_name or not clean_exec:
        raise ValueError("Name and command are required.")

    auto_dir = _autostart_dir()
    auto_dir.mkdir(parents=True, exist_ok=True)
    target = auto_dir / entry.filename
    source = target if target.is_file() else entry.path

    terminal = "true" if mode == "terminal" else "false"
    final_exec = clean_exec
    if mode == "background":
        escaped = clean_exec.replace("'", "'\"'\"'")
        final_exec = f"sh -c '{escaped} >/dev/null 2>&1 &'"

    existing_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    filtered = [
        ln for ln in existing_lines
        if not ln.strip().startswith(("Name=", "Exec=", "Terminal=", "Comment="))
    ]
    filtered.append(f"Name={clean_name}")
    filtered.append(f"Exec={final_exec}")
    filtered.append(f"Terminal={terminal}")
    if comment.strip():
        filtered.append(f"Comment={comment.strip()}")
    target.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    return target


def run_autostart_entry(entry: AutostartEntry) -> None:
    """Başlangıç öğesinin komutunu arka planda test amaçlı çalıştırır."""
    raw = (entry.exec_cmd or "").strip()
    if not raw:
        raise ValueError("No command defined for this entry.")
    cleaned = re.sub(r"\s+%[uUfFickdnvm]", "", raw).strip()
    fields = _parse_desktop_fields(entry.path)
    if fields.get("Terminal", "false").lower() == "true":
        subprocess.Popen(
            ["x-terminal-emulator", "-e", "sh", "-c", cleaned],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    if cleaned.startswith("sh -c "):
        subprocess.Popen(
            shlex.split(cleaned),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    subprocess.Popen(
        shlex.split(cleaned),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
