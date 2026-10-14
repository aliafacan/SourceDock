"""Read local AppStream declarations without inventing missing metadata."""

import gzip
from pathlib import Path
import xml.etree.ElementTree as ET

MAX_METADATA_BYTES = 8 * 1024 * 1024


def metadata_paths():
    paths = []
    for directory in (
        "/usr/share/metainfo",
        "/usr/share/appdata",
        "/var/cache/swcatalog/xml",
        "/var/lib/app-info/xmls",
    ):
        root = Path(directory)
        if root.is_dir():
            paths.extend(root.glob("*.xml"))
            paths.extend(root.glob("*.xml.gz"))
    return sorted(paths)


def _localized(component, tag, language):
    elements = component.findall(tag)
    preferred = next(
        (
            element
            for element in elements
            if element.get("{http://www.w3.org/XML/1998/namespace}lang") == language
        ),
        None,
    )
    if preferred is None:
        preferred = next(
            (
                element
                for element in elements
                if not element.get("{http://www.w3.org/XML/1998/namespace}lang")
            ),
            None,
        )
    return " ".join(preferred.itertext()).strip() if preferred is not None else ""


def load_metadata(paths=None, language="en"):
    index = {}
    ambiguous = set()
    for path in paths if paths is not None else metadata_paths():
        path = Path(path)
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rb") as source:
                data = source.read(MAX_METADATA_BYTES + 1)
            if len(data) > MAX_METADATA_BYTES or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                continue
            root = ET.fromstring(data)
        except (OSError, ET.ParseError):
            continue
        for component in [root] if root.tag == "component" else root.findall("component"):
            identity = component.findtext("id", "").strip()
            if not identity:
                continue
            homepage = next(
                (url.text or "" for url in component.findall("url") if url.get("type") == "homepage"), ""
            )
            metadata = {
                "identity": identity,
                "name": _localized(component, "name", language),
                "description": _localized(component, "description", language),
                "summary": _localized(component, "summary", language),
                "publisher": component.findtext("developer/name", component.findtext("developer_name", "")),
                "license": component.findtext("project_license", ""),
                "homepage": homepage if homepage.startswith(("https://", "http://")) else "",
                "category": ";".join(
                    category.text or "" for category in component.findall("categories/category")
                ),
                "screenshots": [
                    image.text
                    for image in component.findall("screenshots/screenshot/image")
                    if image.text and image.text.startswith("https://")
                ],
                "path": str(path),
            }
            keys = [
                identity,
                *[node.text for node in component.findall("pkgname")],
                *[node.text for node in component.findall("launchable") if node.get("type") == "desktop-id"],
            ]
            for key in keys:
                if key in index and index[key]["identity"] != identity:
                    index.pop(key)
                    ambiguous.add(key)
                if key and key not in ambiguous:
                    index[key] = metadata
    return index
