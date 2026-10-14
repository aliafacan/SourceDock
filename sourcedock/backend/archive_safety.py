"""Bounded archive extraction without links or paths outside the destination."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import zipfile

from sourcedock.core.errors import BackendError

MAX_MEMBERS = 20_000
MAX_TOTAL_BYTES = 2 * 1024**3
MAX_FILE_BYTES = 1024**3
MAX_COMPRESSION_RATIO = 200


def _target(root: Path, name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or (path.parts and ":" in path.parts[0]):
        raise BackendError(f"Unsafe archive path: {name}")
    target = root.joinpath(*path.parts)
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise BackendError(f"Unsafe archive path: {name}") from exc
    for component in (target, *target.parents):
        if component.is_symlink():
            raise BackendError(f"Archive path contains a symbolic link: {name}")
        if component == root:
            break
    return target


def _check_size(count: int, size: int, total: int) -> None:
    if count > MAX_MEMBERS or size < 0 or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
        raise BackendError("Archive exceeds the extraction limits.")


def _copy(source, target: Path, size: int, executable: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    with target.open("xb") as output:
        while remaining:
            data = source.read(min(64 * 1024, remaining))
            if not data:
                raise BackendError("Truncated archive member.")
            output.write(data)
            remaining -= len(data)
    target.chmod(0o755 if executable else 0o644)


def safe_extract_archive(archive_path: str, dest_dir: Path) -> None:
    if dest_dir.is_symlink():
        raise BackendError("Archive destination is a symbolic link.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                for count, member in enumerate(members, 1):
                    _target(dest_dir, member.filename)
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise BackendError("Archive links and special files are not supported.")
                    total += member.file_size
                    _check_size(count, member.file_size, total)
                    if (
                        member.file_size > 1024 * 1024
                        and member.file_size / max(1, member.compress_size) > MAX_COMPRESSION_RATIO
                    ):
                        raise BackendError("Archive compression ratio exceeds the extraction limit.")
                for member in members:
                    target = _target(dest_dir, member.filename)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        with archive.open(member) as source:
                            _copy(
                                source, target, member.file_size, bool((member.external_attr >> 16) & 0o111)
                            )
        elif tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as archive:
                members = []
                for count, member in enumerate(archive, 1):
                    _target(dest_dir, member.name)
                    if not (member.isfile() or member.isdir()) or member.sparse:
                        raise BackendError("Archive links and special files are not supported.")
                    total += member.size
                    _check_size(count, member.size, total)
                    members.append(member)
                for member in members:
                    target = _target(dest_dir, member.name)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        with archive.extractfile(member) as source:
                            _copy(source, target, member.size, bool(member.mode & 0o111))
        else:
            raise BackendError("Unsupported or corrupt archive format.")
    except (OSError, tarfile.TarError, zipfile.BadZipFile, RuntimeError) as exc:
        raise BackendError(f"Archive extraction failed: {exc}") from exc
