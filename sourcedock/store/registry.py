#!/usr/bin/env python3
"""Uygulama Mağazası (Flathub, Snap Store, APT) arama ve kurulum sağlayıcısı."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from dataclasses import replace
from dataclasses import asdict
import re

from sourcedock.core.errors import AuthRequiredError, BackendError, SnapClassicRequiredError
from sourcedock.core.models import (
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
    NATIVE_SOURCES,
    SOURCE_APT,
    SOURCE_DNF,
    SOURCE_FLATPAK,
    SOURCE_PACMAN,
    SOURCE_SNAP,
    SOURCE_ZYPPER,
    StoreResult,
    is_native_source,
)
from sourcedock.core.icons import find_flatpak_icon_path
from sourcedock.backend.distro import DistroInfo, detect_distro
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.dnf import DnfProvider
from sourcedock.backend.pacman import PacmanProvider
from sourcedock.backend.zypper import ZypperProvider
from sourcedock.store.metadata import load_metadata


_TECHNICAL_PACKAGE_PREFIXES = (
    "gir1.2-",
    "linux-headers",
    "linux-image",
    "python3-",
    "fonts-",
    "language-pack",
    "language-pack-",
    "xserver-xorg-",
)
_TECHNICAL_PACKAGE_SUFFIXES = (
    "-locale",
    "-common",
    "-data",
    "-dbg",
    "-dbgsym",
    "-dev",
    "-doc",
    "-translations",
)


def _looks_like_desktop_package(result: StoreResult, allow_transitional: bool = False) -> bool:
    """Keep implementation packages out of the application store.

    The complete package inventory remains available in the Packages page. Store
    search is deliberately biased toward user-facing applications, while exact
    package names that do not match these conventions remain searchable.
    """
    name = result.app_id.casefold()
    description = result.description.casefold()
    if ("transitional package" in description and not allow_transitional) or "dummy package" in description:
        return False
    if any(name.startswith(prefix) for prefix in _TECHNICAL_PACKAGE_PREFIXES):
        return False
    if name.startswith("lib") and re.search(r"-(?:[0-9]|dev|common|data|bin|utils)(?:-|$)", name):
        return False
    if any(name.endswith(suffix) for suffix in _TECHNICAL_PACKAGE_SUFFIXES):
        return False
    if re.search(r"-locale-[a-z]{2}(?:[_-][a-z0-9]+)?$", name):
        return False
    if name.endswith(("-plugin", "-plugins", "-extension", "-extensions")):
        return False
    return True


class StoreRegistry:
    # Remote store queries are independent. Flatpak may need longer than the
    # native package indexes while refreshing its remote metadata, so allow a
    # full provider window without delaying fast partial results.
    PROVIDER_TIMEOUT_SECONDS = 30.0
    SNAP_SEARCH_TIMEOUT_SECONDS = 2.0
    PARTIAL_CACHE_TTL_SECONDS = 15.0
    SEARCH_CACHE_TTL_SECONDS = 15 * 60
    SEARCH_PARTIAL_CACHE_TTL_SECONDS = 60
    SEARCH_CACHE_MAX_ENTRIES = 24

    """Mağazalardan (Flatpak, Snap, APT, DNF, Pacman, Zypper) arama ve kurulum işlemlerini yürüten sınıf."""

    def __init__(self, distro_info: DistroInfo | None = None):
        self._sudo_password: str | None = None
        self._output_callback: Callable[[str], None] | None = None
        self.host_bridge_available = self._detect_host_bridge()
        self._current_process: subprocess.Popen | None = None
        self._stream_runner = CommandRunner()
        self._search_context = threading.local()
        self.distro = distro_info or detect_distro()
        self.native_manager = self.distro.native_manager
        self.provider_errors = []
        self.missing_sources = []
        self._metadata = None
        self._search_cache: dict[tuple[str, tuple[str, ...]], list[StoreResult]] = {}
        self._search_cache_saved_at: dict[tuple[str, tuple[str, ...]], float] = {}
        self._search_cache_complete: dict[tuple[str, tuple[str, ...]], bool] = {}
        self._partial_search_cache: dict[
            tuple[str, tuple[str, ...]],
            tuple[float, list[StoreResult], list[str], dict[str, object], dict[str, str]],
        ] = {}
        self.last_search_metrics: dict[str, object] = {}
        self.last_search_source_states: dict[str, str] = {}
        cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        self._search_cache_path = os.path.join(cache_home, "sourcedock", "store-search.json")
        self._load_persistent_search_cache()

    @staticmethod
    def _cache_key_data(cache_key: tuple[str, tuple[str, ...]]) -> tuple[str, list[str]]:
        query, sources = cache_key
        return query, list(sources)

    def _load_persistent_search_cache(self) -> None:
        """Restore only fresh, complete, non-sensitive search results."""
        cache_path = getattr(self, "_search_cache_path", None)
        if not cache_path:
            return
        try:
            import json

            with open(cache_path, encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
            if payload.get("version") != 1 or not isinstance(payload.get("entries"), list):
                return
            now = time.time()
            allowed = set(StoreResult.__dataclass_fields__)
            for entry in payload["entries"][-self.SEARCH_CACHE_MAX_ENTRIES :]:
                saved_at = float(entry.get("saved_at", 0))
                query = str(entry.get("query", "")).strip().casefold()
                sources = tuple(sorted(str(source) for source in entry.get("sources", [])))
                raw_results = entry.get("results", [])
                complete = bool(entry.get("complete", True))
                ttl = self.SEARCH_CACHE_TTL_SECONDS if complete else self.SEARCH_PARTIAL_CACHE_TTL_SECONDS
                if (
                    not query
                    or not sources
                    or now - saved_at > ttl
                    or not isinstance(raw_results, list)
                ):
                    continue
                results = [
                    StoreResult(**{key: value for key, value in item.items() if key in allowed})
                    for item in raw_results
                    if isinstance(item, dict) and item.get("app_id") and item.get("source")
                ]
                if results:
                    cache_key = (query, sources)
                    states = entry.get("source_states", {})
                    source_states = {
                        source: str(states.get(source, "cached")) for source in sources
                    }
                    if complete:
                        self._search_cache[cache_key] = results
                        self._search_cache_saved_at[cache_key] = saved_at
                        self._search_cache_complete[cache_key] = True
                        if not hasattr(self, "_search_cache_source_states"):
                            self._search_cache_source_states = {}
                        self._search_cache_source_states[cache_key] = source_states
                    else:
                        self._partial_search_cache[cache_key] = (
                            time.monotonic() + max(0, ttl - (now - saved_at)),
                            results,
                            [],
                            {"cache_hit": True, "partial_cache": True, "source_states": source_states},
                            source_states,
                        )
        except (OSError, ValueError, TypeError, KeyError):
            return

    def _persist_search_cache(self) -> None:
        cache_path = getattr(self, "_search_cache_path", None)
        if not cache_path:
            return
        try:
            from sourcedock.core.json_store import write_json

            entries = []
            for (query, sources), results in list(self._search_cache.items())[-self.SEARCH_CACHE_MAX_ENTRIES :]:
                cache_key = (query, sources)
                entries.append(
                    {
                        "saved_at": self._search_cache_saved_at.get(cache_key, time.time()),
                        "query": query,
                        "sources": list(sources),
                        "complete": True,
                        "source_states": getattr(self, "_search_cache_source_states", {}).get(cache_key, {}),
                        "results": [asdict(result) for result in results],
                    }
                )
            for (query, sources), partial in list(self._partial_search_cache.items())[-self.SEARCH_CACHE_MAX_ENTRIES :]:
                expires_at, results, _errors, _metrics, source_states = partial
                saved_at = time.time() - max(0, self.PARTIAL_CACHE_TTL_SECONDS - (expires_at - time.monotonic()))
                entries.append(
                    {
                        "saved_at": saved_at,
                        "query": query,
                        "sources": list(sources),
                        "complete": False,
                        "source_states": dict(source_states),
                        "results": [asdict(result) for result in results],
                    }
                )
            write_json(Path(cache_path), {"version": 1, "entries": entries[-self.SEARCH_CACHE_MAX_ENTRIES :]})
        except (OSError, TypeError, ValueError):
            return

    def invalidate_search_cache(self, sources: set[str] | None = None) -> None:
        """Drop cached queries affected by a package mutation."""
        if not sources:
            self._search_cache.clear()
        else:
            for key, results in list(self._search_cache.items()):
                if any(result.source in sources for result in results) or any(
                    source in sources for source in key[1]
                ):
                    self._search_cache.pop(key, None)
        if hasattr(self, "_search_cache_source_states"):
            self._search_cache_source_states = {
                key: value for key, value in self._search_cache_source_states.items() if key in self._search_cache
            }
        if hasattr(self, "_search_cache_saved_at"):
            self._search_cache_saved_at = {
                key: value for key, value in self._search_cache_saved_at.items() if key in self._search_cache
            }
        if hasattr(self, "_search_cache_complete"):
            self._search_cache_complete = {
                key: value for key, value in self._search_cache_complete.items() if key in self._search_cache
            }
        if hasattr(self, "_partial_search_cache"):
            if not sources:
                self._partial_search_cache.clear()
            else:
                for key, partial in list(self._partial_search_cache.items()):
                    if any(result.source in sources for result in partial[1]) or any(
                        source in sources for source in key[1]
                    ):
                        self._partial_search_cache.pop(key, None)
        self._persist_search_cache()

    @property
    def runner(self) -> CommandRunner:
        return self._stream_runner

    def cancel_current(self, target: str | int | None = None) -> bool:
        return self._stream_runner.cancel_current(target=target)

    def bind_thread_op(self, op_id: str) -> None:
        self._stream_runner.bind_thread_op(op_id)

    def unbind_thread_op(self, op_id: str | None = None) -> None:
        self._stream_runner.unbind_thread_op(op_id)

    def set_sudo_password(self, password: str) -> None:
        self._sudo_password = password

    def clear_sudo_password(self) -> None:
        self._sudo_password = None
        self._stream_runner.clear_sudo_password()

    def _record_provider_error(self, message: str) -> None:
        if message not in self.provider_errors:
            self.provider_errors.append(message)

    def set_output_callback(
        self,
        callback: Callable[[str], None] | None,
        op_id: str | None = None,
    ) -> None:
        self._output_callback = callback
        self._stream_runner.set_output_callback(callback, op_id=op_id)

    def search(
        self,
        query: str,
        sources: set[str] | None = None,
        on_partial: Callable[[list[StoreResult], bool], None] | None = None,
        provider_timeout_seconds: float | None = None,
    ) -> list[StoreResult]:
        normalized_query = query.strip()
        if not normalized_query:
            return []
        if sources is None:
            sources = {SOURCE_FLATPAK, SOURCE_SNAP, self.native_manager}
        source_order = tuple(sorted(sources))
        cache_key = (normalized_query.casefold(), source_order)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            source_states = getattr(self, "_search_cache_source_states", {}).get(cache_key)
            cache_complete = getattr(self, "_search_cache_complete", {}).get(cache_key, True)
            if source_states is None:
                source_states = {result.source: "cached" for result in cached}
            else:
                source_states = {
                    source: state if state == "unavailable" else "cached"
                    for source, state in source_states.items()
                }
            self.last_search_source_states = dict(source_states)
            self.last_search_metrics = {
                "cache_hit": True,
                "total_ms": 0.0,
                "sources": {},
                "source_states": dict(source_states),
                "partial_cache": not cache_complete,
            }
            self.provider_errors = []
            self.missing_sources = []
            cached_results = list(cached)
            if on_partial:
                on_partial(cached_results, True)
            return cached_results

        partial_cached = self._partial_search_cache.get(cache_key)
        if partial_cached is not None:
            if len(partial_cached) == 4:
                expires_at, partial_results, partial_errors, partial_metrics = partial_cached
                partial_source_states = {
                    result.source: "cached" for result in partial_results
                }
            else:
                expires_at, partial_results, partial_errors, partial_metrics, partial_source_states = partial_cached
            if expires_at > time.monotonic():
                partial_source_states = {
                    source: "unavailable" if state == "unavailable" else "cached"
                    for source, state in partial_source_states.items()
                }
                self.provider_errors = list(partial_errors)
                self.missing_sources = []
                self.last_search_source_states = dict(partial_source_states)
                self.last_search_metrics = {
                    **partial_metrics,
                    "cache_hit": True,
                    "partial_cache": True,
                    "total_ms": 0.0,
                    "source_states": dict(partial_source_states),
                }
                if on_partial:
                    on_partial(list(partial_results), True)
                return list(partial_results)
            self._partial_search_cache.pop(cache_key, None)

        self.provider_errors = []
        self.missing_sources = []
        commands = {
            SOURCE_FLATPAK: "flatpak",
            SOURCE_SNAP: "snap",
            SOURCE_APT: "apt-cache",
            SOURCE_DNF: "dnf",
            SOURCE_PACMAN: "pacman",
            SOURCE_ZYPPER: "zypper",
        }
        results: list[StoreResult] = []
        started_at = time.perf_counter()
        source_timings: dict[str, float] = {}
        timed_out_sources: list[str] = []
        source_started_at: dict[str, float] = {}
        source_states: dict[str, str] = {}
        if not hasattr(self, "_search_context"):
            self._search_context = threading.local()
        search_controls = {
            source: (threading.Event(), CommandRunner()) for source in source_order
        }

        def search_source(source: str):
            source_started_at = time.perf_counter()
            command = commands.get(source, source)
            cancel_event, search_runner = search_controls[source]
            context = getattr(self, "_search_context", None)
            if context is None:
                context = threading.local()
                self._search_context = context
            context.runner = search_runner
            context.cancel_event = cancel_event
            try:
                if not self._command_exists(command):
                    return source, [], None, True, (time.perf_counter() - source_started_at) * 1000
                if source == SOURCE_FLATPAK:
                    found = self._search_flatpak(normalized_query)
                elif source == SOURCE_SNAP:
                    found = self._search_snap(normalized_query)
                else:
                    found = self._search_native(source, normalized_query)
                return source, found, None, False, (time.perf_counter() - source_started_at) * 1000
            except BackendError as exc:
                return source, [], str(exc), False, (time.perf_counter() - source_started_at) * 1000
            except Exception as exc:
                return source, [], str(exc), False, (time.perf_counter() - source_started_at) * 1000
            finally:
                for attribute in ("runner", "cancel_event"):
                    try:
                        delattr(context, attribute)
                    except AttributeError:
                        pass

        # Flatpak, Snap and the native package manager are independent remote
        # lookups. Publish completed sources, then stop waiting at the
        # read-only provider deadline so a stalled optional source cannot block
        # results that are already available.
        timeout = self.PROVIDER_TIMEOUT_SECONDS if provider_timeout_seconds is None else provider_timeout_seconds
        executor = ThreadPoolExecutor(
            max_workers=max(1, min(4, len(source_order))),
            thread_name_prefix="sourcedock-store-search",
        )
        future_to_source = {}
        for source in source_order:
            source_started_at[source] = time.perf_counter()
            future_to_source[executor.submit(search_source, source)] = source
        pending = set(future_to_source)
        deadline = None if timeout is None else time.perf_counter() + max(0.0, timeout)
        try:
            while pending:
                remaining = None if deadline is None else max(0.0, deadline - time.perf_counter())
                done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                if not done:
                    break
                for future in done:
                    source, found, error, missing, duration_ms = future.result()
                    source_timings[source] = round(duration_ms, 1)
                    if missing:
                        self.missing_sources.append(source)
                        source_states[source] = "unavailable"
                    elif error:
                        self._record_provider_error(f"{source.upper()}: {error}")
                        source_states[source] = "unavailable"
                    else:
                        results.extend(found)
                        source_states[source] = "live"
                    # Partial callbacks must describe this search, not the
                    # previous query's provider state. This keeps a fast
                    # APT/Flatpak result from being labelled unavailable while
                    # another provider is still running.
                    self.last_search_source_states = dict(source_states)
                    if on_partial:
                        on_partial(self._enrich_results(results, normalized_query), False)
            if pending:
                for future in pending:
                    source = future_to_source[future]
                    timed_out_sources.append(source)
                    source_timings[source] = round(
                        (time.perf_counter() - source_started_at[source]) * 1000, 1
                    )
                    source_states[source] = "unavailable"
                    self._record_provider_error(
                        f"{source.upper()}: timeout after {timeout:g}s"
                        if timeout is not None
                        else f"{source.upper()}: timeout"
                    )
                    search_controls[source][0].set()
                    search_controls[source][1].cancel_current()
                    future.cancel()
        finally:
            # Running workers are read-only and are not reused after this search.
            executor.shutdown(wait=False, cancel_futures=True)

        enrich_started = time.perf_counter()
        enriched = self._enrich_results(results, normalized_query)
        enrich_ms = round((time.perf_counter() - enrich_started) * 1000, 1)
        self.last_search_metrics = {
            "cache_hit": False,
            "total_ms": round((time.perf_counter() - started_at) * 1000, 1),
            "sources": source_timings,
            "metadata_enrich_ms": enrich_ms,
            "timeout_seconds": timeout,
            "timed_out": bool(timed_out_sources),
            "timed_out_sources": timed_out_sources,
            "provider_errors": list(self.provider_errors),
            "source_states": dict(source_states),
        }
        self.last_search_source_states = dict(source_states)
        if not results and self.provider_errors:
            raise BackendError("\n".join(self.provider_errors))
        # Displaying partial results is useful, but an errored provider response
        # must not be stored as a successful cache hit.
        if not self.provider_errors:
            if len(self._search_cache) >= self.SEARCH_CACHE_MAX_ENTRIES:
                self._search_cache.pop(next(iter(self._search_cache)))
            self._search_cache[cache_key] = list(enriched)
            if not hasattr(self, "_search_cache_saved_at"):
                self._search_cache_saved_at = {}
            if not hasattr(self, "_search_cache_complete"):
                self._search_cache_complete = {}
            self._search_cache_saved_at[cache_key] = time.time()
            self._search_cache_complete[cache_key] = True
            if not hasattr(self, "_search_cache_source_states"):
                self._search_cache_source_states = {}
            self._search_cache_source_states[cache_key] = {
                source: "live" for source in source_states
            }
            self._partial_search_cache.pop(cache_key, None)
            self._persist_search_cache()
        elif enriched:
            if not hasattr(self, "_search_cache_saved_at"):
                self._search_cache_saved_at = {}
            if not hasattr(self, "_search_cache_complete"):
                self._search_cache_complete = {}
            if not hasattr(self, "_search_cache_source_states"):
                self._search_cache_source_states = {}
            self._partial_search_cache[cache_key] = (
                time.monotonic() + self.PARTIAL_CACHE_TTL_SECONDS,
                list(enriched),
                list(self.provider_errors),
                dict(self.last_search_metrics),
                dict(source_states),
            )
            self._persist_search_cache()
        if on_partial:
            on_partial(list(enriched), True)
        return enriched

    def _enrich_results(self, results: list[StoreResult], exact_query: str = "") -> list[StoreResult]:
        if self._metadata is None:
            self._metadata = load_metadata()
        enriched = []
        for result in results:
            metadata = self._metadata.get(result.app_id)
            if result.source == SOURCE_SNAP or (
                result.source == SOURCE_FLATPAK and metadata and metadata["identity"] != result.app_id
            ):
                metadata = None
            if metadata:
                result = replace(
                    result,
                    identity=metadata["identity"],
                    publisher=metadata["publisher"],
                    license=metadata["license"],
                    homepage=metadata["homepage"],
                    category=metadata["category"],
                )
            elif result.source == SOURCE_FLATPAK:
                result = replace(result, identity=result.app_id)
            if is_native_source(result.source):
                result = replace(
                    result,
                    is_application=_looks_like_desktop_package(
                        result,
                        allow_transitional=bool(
                            exact_query and result.app_id.casefold() == exact_query.casefold()
                        ),
                    ),
                )
            enriched.append(result)
        return enriched

    def _search_native(self, native_src: str, query: str) -> list[StoreResult]:
        if native_src == SOURCE_APT:
            return self._search_apt(query)
        runner = CommandRunner()
        if native_src == SOURCE_DNF:
            return DnfProvider(runner, None).search_store(query)
        if native_src == SOURCE_PACMAN:
            return PacmanProvider(runner, None).search_store(query)
        if native_src == SOURCE_ZYPPER:
            return ZypperProvider(runner, None).search_store(query)
        return []

    def _search_flatpak(self, query: str) -> list[StoreResult]:
        if not self._command_exists("flatpak"):
            return []
        try:
            result_with_size = self._run(
                [
                    "flatpak",
                    "search",
                    "--columns=name,application,description,version,remote,download-size",
                    "--",
                    query,
                ],
                timeout=30,
            )
            has_size = result_with_size.returncode == 0 and "\t" in result_with_size.stdout
            if has_size:
                raw = result_with_size
            else:
                raw = self._run(
                    [
                        "flatpak",
                        "search",
                        "--columns=name,application,description,version,remote",
                        "--",
                        query,
                    ],
                    timeout=30,
                )

            items: list[StoreResult] = []
            if raw.returncode != 0:
                raise BackendError(raw.stderr or raw.stdout or "Flatpak search failed.")
            for line in raw.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                name = parts[0].strip()
                app_id = parts[1].strip()
                if not name or not app_id:
                    continue
                desc = parts[2].strip() if len(parts) > 2 else ""
                version = parts[3].strip() if len(parts) > 3 else ""
                remote = parts[4].strip() if len(parts) > 4 else "flathub"
                size_str = parts[5].strip() if has_size and len(parts) > 5 else ""
                icon_path = self._flatpak_icon_path(app_id, remote)
                items.append(
                    StoreResult(
                        name=name,
                        app_id=app_id,
                        description=desc,
                        source=SOURCE_FLATPAK,
                        version=version,
                        remote=remote,
                        download_size_str=size_str,
                        icon_path=icon_path,
                    )
                )
            return items
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"Flatpak arama hatası: {exc}") from exc

    def _flatpak_icon_path(self, app_id: str, remote: str) -> str:
        return find_flatpak_icon_path(app_id, remote)

    def _search_snap(self, query: str) -> list[StoreResult]:
        if not self._command_exists("snap"):
            return []
        try:
            # Snap Store is optional; a slow remote search must not block the
            # local/Flatpak results already published to the UI.
            result = self._run(["snap", "find", query], timeout=self.SNAP_SEARCH_TIMEOUT_SECONDS)
            if result.returncode != 0:
                raise BackendError(result.stderr or result.stdout or "Snap search failed.")
            items: list[StoreResult] = []
            for index, line in enumerate(result.stdout.splitlines()):
                if index == 0 or not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 1:
                    continue
                snap_name = parts[0]
                version = parts[1] if len(parts) > 1 else ""
                description = " ".join(parts[4:]) if len(parts) > 4 else ""
                items.append(
                    StoreResult(
                        name=snap_name,
                        app_id=snap_name,
                        description=description,
                        source=SOURCE_SNAP,
                        version=version,
                        remote="snap-store",
                    )
                )
            return items
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"Snap arama hatası: {exc}") from exc

    def _apt_candidate_versions(self, pkg_names: list[str]) -> dict[str, str]:
        if not pkg_names:
            return {}
        try:
            result = self._run(["apt-cache", "policy", "--"] + pkg_names, timeout=30)
            versions: dict[str, str] = {}
            current_pkg = ""
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if not line.startswith(" ") and stripped.endswith(":"):
                    current_pkg = stripped[:-1]
                elif current_pkg and stripped.startswith("Candidate:"):
                    ver = stripped.split(":", 1)[1].strip()
                    if ver and ver != "(none)":
                        versions[current_pkg] = ver
            return versions
        except Exception:
            return {}

    def _search_apt(self, query: str) -> list[StoreResult]:
        if not self._command_exists("apt-cache"):
            return []
        try:
            result = self._run(["apt-cache", "search", "--", query], timeout=30)
            if result.returncode != 0:
                raise BackendError(result.stderr or result.stdout or "APT search failed.")
            items: list[StoreResult] = []
            pkg_names: list[str] = []
            raw_results: list[tuple[str, str]] = []
            for line in result.stdout.splitlines():
                if " - " not in line:
                    continue
                pkg_name, description = line.split(" - ", 1)
                pkg_name = pkg_name.strip()
                description = description.strip()
                if not pkg_name:
                    continue
                raw_results.append((pkg_name, description))
                pkg_names.append(pkg_name)
            raw_results.sort(
                key=lambda item: (
                    item[0].casefold() != query.casefold(),
                    not item[0].casefold().startswith(query.casefold()),
                    len(item[0]),
                    item[0],
                )
            )
            raw_results = raw_results[:60]
            pkg_names = [name for name, _description in raw_results]
            versions = self._apt_candidate_versions(pkg_names)
            for pkg_name, description in raw_results:
                item = StoreResult(
                    name=pkg_name,
                    app_id=pkg_name,
                    description=description,
                    source=SOURCE_APT,
                    version=versions.get(pkg_name, ""),
                    remote="apt",
                )
                # Ubuntu/Zorin expose Firefox through an APT transitional
                # package which hands off to Snap. Keep that exact package
                # visible as a source variant so the user can compare it in
                # the details dialog; implementation packages remain hidden.
                if pkg_name.casefold() == query.casefold():
                    item = replace(
                        item,
                        is_application=_looks_like_desktop_package(item, allow_transitional=True),
                    )
                else:
                    item = replace(item, is_application=_looks_like_desktop_package(item))
                items.append(item)
            return items
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"APT arama hatası: {exc}") from exc

    def install(self, result: StoreResult, classic: bool = False) -> None:
        if result.source == SOURCE_FLATPAK:
            self._install_flatpak(result)
        elif result.source == SOURCE_SNAP:
            self._install_snap(result, classic=classic)
        elif is_native_source(result.source):
            self._install_native(result)
        else:
            raise BackendError(f"Bilinmeyen kaynak: {result.source}")
        self.invalidate_search_cache({result.source})

    def _install_native(self, result: StoreResult) -> None:
        if result.source == SOURCE_APT:
            self._install_apt(result)
        elif result.source == SOURCE_DNF:
            cmd = ["dnf", "install", "-y", result.app_id]
            self._run_privileged_streaming(cmd, timeout=1800)
        elif result.source == SOURCE_PACMAN:
            cmd = ["pacman", "-S", "--noconfirm", result.app_id]
            self._run_privileged_streaming(cmd, timeout=1800)
        elif result.source == SOURCE_ZYPPER:
            cmd = ["zypper", "--non-interactive", "install", "-y", result.app_id]
            self._run_privileged_streaming(cmd, timeout=1800)

    def _flatpak_remote_scope(self, remote: str) -> str:
        for scope_flag in ("--user", "--system"):
            r = self._run(["flatpak", "remotes", scope_flag, "--columns=name"], timeout=5)
            if r.returncode == 0:
                names = {line.strip().lower() for line in r.stdout.splitlines() if line.strip()}
                if remote.lower() in names:
                    return scope_flag
        return "--user"

    def _install_flatpak(self, result: StoreResult) -> None:
        remote = result.remote or "flathub"
        scope = self._flatpak_remote_scope(remote)
        cmd = ["flatpak", "install", scope, "-y", "--noninteractive", remote, result.app_id]
        if scope == "--system":
            self._run_privileged_streaming(cmd, timeout=1800)
        else:
            self._run_streaming(cmd, timeout=1800, check=True)

    def _install_snap(self, result: StoreResult, classic: bool = False) -> None:
        cmd = ["snap", "install"]
        if classic:
            cmd.append("--classic")
        cmd.append(result.app_id)
        self._run_privileged_streaming(cmd, timeout=1800, snap_pkg=result.app_id)

    def _install_apt(self, result: StoreResult) -> None:
        cmd = ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "install", "-y", result.app_id]
        self._run_privileged_streaming(cmd, timeout=1800)

    def _command_exists(self, command: str) -> bool:
        if self.host_bridge_available:
            r = self._run(["sh", "-lc", f"command -v {command} >/dev/null 2>&1"], timeout=5)
            return r.returncode == 0
        return shutil.which(command) is not None

    def _run(self, command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
        context = getattr(self, "_search_context", None)
        runner = getattr(context, "runner", None) if context is not None else None
        cancel_event = getattr(context, "cancel_event", None) if context is not None else None
        if cancel_event is not None and cancel_event.is_set():
            raise BackendError("Store provider search cancelled after timeout.")
        runner = runner or getattr(self, "_stream_runner", None) or CommandRunner()
        try:
            return runner.run_read_only(command, timeout=timeout)
        except BackendError:
            raise
        except OSError as exc:
            raise BackendError(f"Komut çalıştırılamadı: {' '.join(command)}\n{exc}") from exc

    def _run_streaming(
        self, command: list[str], timeout: int = 1800, check: bool = False, snap_pkg: str = ""
    ) -> None:
        self._stream_runner.set_output_callback(self._output_callback)
        result = self._stream_runner._run_streaming(self._wrap_host(command), timeout, False)
        self._check_stream_result(result, command, check, snap_pkg)

    def _check_stream_result(self, result, command, check, snap_pkg):
        if check and result.returncode != 0:
            combined = result.stdout.lower()
            if snap_pkg and ("classic confinement" in combined or "--classic" in combined):
                raise SnapClassicRequiredError(
                    f"Snap '{snap_pkg}' classic confinement gerektiriyor.",
                    package_name=snap_pkg,
                )
            raise BackendError(f"Command failed: {' '.join(command)}\n{result.stdout[-2000:]}")

    def _run_privileged_streaming(self, command: list[str], timeout: int = 1800, snap_pkg: str = "") -> None:
        self._stream_runner.set_output_callback(self._output_callback)
        if self._sudo_password:
            self._stream_runner.set_sudo_password(self._sudo_password)
        try:
            self._wait_for_native_locks(command)
            self._stream_runner.run_privileged(command, timeout=timeout)
        except BackendError as exc:
            if snap_pkg and ("classic confinement" in str(exc).lower() or "--classic" in str(exc)):
                raise SnapClassicRequiredError(str(exc), package_name=snap_pkg) from exc
            raise
        finally:
            self.clear_sudo_password()

    def _wait_for_native_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command:
            return
        binary = command[0]
        if binary in {"apt", "apt-get", "nala", "dpkg"}:
            self._wait_for_apt_locks(command, max_wait)
        elif binary == "pacman":
            self._wait_for_pacman_locks(command, max_wait)
        elif binary in {"dnf", "rpm"}:
            self._wait_for_dnf_locks(command, max_wait)
        elif binary == "zypper":
            self._wait_for_zypper_locks(command, max_wait)

    def _wait_for_pacman_locks(self, command: list[str], max_wait: int = 300) -> None:
        lock_file = "/var/lib/pacman/db.lck"
        started = time.monotonic()
        while os.path.exists(lock_file):
            if time.monotonic() - started >= max_wait:
                raise BackendError(f"Pacman veritabanı kilitli ({lock_file}). Başka bir işlem devam ediyor.")
            time.sleep(2)

    def _wait_for_dnf_locks(self, command: list[str], max_wait: int = 300) -> None:
        started = time.monotonic()
        while True:
            r = self._run(["pgrep", "-f", r"\b(dnf|rpm)\b"], timeout=5)
            pids = [p for p in r.stdout.splitlines() if p.strip() and p.strip() != str(os.getpid())]
            if not pids:
                return
            if time.monotonic() - started >= max_wait:
                raise BackendError("DNF/RPM şu anda başka bir işlem tarafından kullanılıyor.")
            time.sleep(2)

    def _wait_for_zypper_locks(self, command: list[str], max_wait: int = 300) -> None:
        lock_file = "/var/run/zypp.pid"
        started = time.monotonic()
        while os.path.exists(lock_file):
            if time.monotonic() - started >= max_wait:
                raise BackendError(f"Zypper kilitli ({lock_file}). Başka bir işlem devam ediyor.")
            time.sleep(2)

    def _wait_for_apt_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command or command[0] not in {"apt", "apt-get", "nala", "dpkg"}:
            return
        started = time.monotonic()
        while True:
            holders = self._apt_lock_holders()
            if not holders:
                return
            summary = "; ".join(f"PID {pid}: {args}" for pid, args in holders[:3])
            if time.monotonic() - started >= max_wait:
                raise BackendError(f"APT şu anda başka bir işlem tarafından kullanılıyor.\n{summary}")
            time.sleep(2)

    def _apt_lock_holders(self) -> list[tuple[str, str]]:
        script = r"""
locks="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock"
pids=""
if command -v fuser >/dev/null 2>&1; then
  for lock in $locks; do
    [ -e "$lock" ] || continue
    found="$(fuser "$lock" 2>/dev/null || true)"
    pids="$pids $found"
  done
fi
pids="$(printf '%s\n' $pids | awk '!seen[$1]++')"
if [ -n "$pids" ]; then
  ps -p "$(printf '%s,' $pids | sed 's/,$//')" -o pid=,args= 2>/dev/null || true
else
  ps -eo pid=,args= | awk '/[a]pt |[a]pt-get |[d]pkg |[u]nattended-upgrade/ && !/wait-for-signal/ {print}'
fi
"""
        try:
            result = self._run(["sh", "-lc", script], timeout=5)
        except Exception:
            return []
        holders: list[tuple[str, str]] = []
        current_pid = str(os.getpid())
        for line in result.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid, args = parts
            if pid == current_pid:
                continue
            lowered = args.lower()
            if not any(token in lowered for token in ("apt", "apt-get", "dpkg", "unattended-upgrade")):
                continue
            holders.append((pid, args[:140]))
        return holders

    def _wrap_host(self, command: list[str]) -> list[str]:
        if self.host_bridge_available:
            return ["flatpak-spawn", "--host", *command]
        return command

    def _detect_host_bridge(self) -> bool:
        if not shutil.which("flatpak-spawn"):
            return False
        result = subprocess.run(
            ["flatpak-spawn", "--host", "true"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
