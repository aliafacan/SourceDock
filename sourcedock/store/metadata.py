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


XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _locale_parts(value: str) -> tuple[str, str]:
    normalized = (value or "").strip().casefold().replace("-", "_").split(".", 1)[0]
    language_base = normalized.split("_", 1)[0].split("@", 1)[0]
    return normalized, language_base


def _text(element) -> str:
    return " ".join(" ".join(element.itertext()).split()).strip()


def _localized(component, tag, language):
    """Select one locale without flattening sibling translated paragraphs.

    AppStream descriptions commonly store one unlabelled ``description`` node
    containing localized ``p`` children. Selecting only the outer node would
    concatenate every language into the detail view.
    """
    elements = component.findall(tag)
    requested, language_base = _locale_parts(language)

    def rank(value: str) -> int | None:
        normalized, base = _locale_parts(value)
        if normalized == requested and normalized:
            return 0
        if base == language_base and base:
            return 1
        if base == "en":
            return 2
        if not normalized:
            return 3
        return None

    direct = [
        (rank(element.get(XML_LANG, "")), element)
        for element in elements
        if element.get(XML_LANG) is not None
        or not any(child.get(XML_LANG) is not None for child in element)
    ]
    direct = [(priority, element) for priority, element in direct if priority is not None]
    if direct:
        priority = min(priority for priority, _element in direct)
        selected = [element for item_priority, element in direct if item_priority == priority]
        return "\n\n".join(text for text in (_text(element) for element in selected) if text)

    for element in elements:
        children = list(element)
        localized_children = [child for child in children if child.get(XML_LANG) is not None]
        if not localized_children:
            text = _text(element)
            if text:
                return text
            continue
        ranked_children = [(rank(child.get(XML_LANG, "")), child) for child in children]
        ranked_children = [(priority, child) for priority, child in ranked_children if priority is not None]
        if ranked_children:
            priority = min(priority for priority, _child in ranked_children)
            selected = [child for item_priority, child in ranked_children if item_priority == priority]
            return "\n\n".join(text for text in (_text(child) for child in selected) if text)

    return ""


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
