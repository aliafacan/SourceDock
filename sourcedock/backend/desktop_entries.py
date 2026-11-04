"""Serialize managed desktop entries using the freedesktop escaping rules."""

from configparser import ConfigParser
from io import StringIO
import re

from sourcedock.core.errors import BackendError


def _string(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def desktop_exec(path):
    value = str(path)
    if "=" in value or "\n" in value or "\r" in value:
        raise BackendError("The executable path cannot be represented in a desktop shortcut.")
    value = value.replace("\\", "\\\\\\\\")
    for character in ('"', "`", "$"):
        value = value.replace(character, "\\\\" + character)
    return '"' + value.replace("%", "%%") + '" %U'


def electron_desktop_exec(executable, wm_class):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", wm_class):
        raise BackendError("Invalid managed window class.")
    return desktop_exec(executable).removesuffix(" %U") + f" --class={wm_class} %U"


def render_desktop_entry(name, executable, icon, directory="", appimage_path="", startup_wm_class="", force_wm_class=False, launch_wm_class=""):
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    fields = {
        "Type": "Application",
        "Name": _string(name),
        "Exec": electron_desktop_exec(executable, launch_wm_class or startup_wm_class) if force_wm_class else desktop_exec(executable),
        "Icon": _string(icon),
        "Terminal": "false",
        "StartupNotify": "true",
        "Categories": "Utility;",
        "X-SourceDock-Managed": "true",
    }
    if directory:
        fields["Path"] = _string(directory)
    if appimage_path:
        fields["X-AppImage-Path"] = _string(appimage_path)
    if startup_wm_class:
        fields["StartupWMClass"] = _string(startup_wm_class)
    parser["Desktop Entry"] = fields
    buffer = StringIO()
    parser.write(buffer, space_around_delimiters=False)
    return buffer.getvalue()
