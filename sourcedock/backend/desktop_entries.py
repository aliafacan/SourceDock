"""Serialize managed desktop entries using the freedesktop escaping rules."""

from configparser import ConfigParser
from io import StringIO

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


def render_desktop_entry(name, executable, icon, directory="", appimage_path=""):
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    fields = {
        "Type": "Application",
        "Name": _string(name),
        "Exec": desktop_exec(executable),
        "Icon": _string(icon),
        "Terminal": "false",
        "Categories": "Utility;",
        "X-SourceDock-Managed": "true",
    }
    if directory:
        fields["Path"] = _string(directory)
    if appimage_path:
        fields["X-AppImage-Path"] = _string(appimage_path)
    parser["Desktop Entry"] = fields
    buffer = StringIO()
    parser.write(buffer, space_around_delimiters=False)
    return buffer.getvalue()
