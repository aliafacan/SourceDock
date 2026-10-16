#!/usr/bin/env python3
"""Measure read-only cold and hot registry paths without changing system state."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.icons import find_flatpak_icon_path
from sourcedock.core.models import SOURCE_FLATPAK
from sourcedock.store.registry import StoreRegistry


ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 1)


def summary(values: list[float]) -> dict:
    return {
        "samples_ms": [round(value, 1) for value in values],
        "median_ms": round(statistics.median(values), 1) if values else None,
        "p95_ms": percentile(values, 0.95),
    }


def measure_application_load(registry: ApplicationRegistry) -> tuple[float, int, dict, float | None]:
    started = time.perf_counter()
    first_meaningful = None

    def observe(snapshot, _complete):
        nonlocal first_meaningful
        if snapshot.applications and first_meaningful is None:
            first_meaningful = (time.perf_counter() - started) * 1000

    snapshot = registry.load_progressive(observe)
    return (
        (time.perf_counter() - started) * 1000,
        len(snapshot.applications),
        dict(registry.last_provider_metrics),
        first_meaningful,
    )


def measure_store_search(registry: StoreRegistry) -> tuple[float, int, dict, dict]:
    started = time.perf_counter()
    try:
        results = registry.search("firefox")
    except Exception as exc:
        return (time.perf_counter() - started) * 1000, 0, {"error": str(exc)}, {}
    search_elapsed_ms = (time.perf_counter() - started) * 1000
    icon_started = time.perf_counter()
    icon_count = 0
    icon_hits = 0
    for result in results:
        if result.source != SOURCE_FLATPAK:
            continue
        icon_count += 1
        if result.icon_path or find_flatpak_icon_path(result.app_id, result.remote):
            icon_hits += 1
    icon_metrics = {
        "flatpak_results": icon_count,
        "resolved": icon_hits,
        "icon_resolution_ms": round((time.perf_counter() - icon_started) * 1000, 1),
    }
    return (
        search_elapsed_ms,
        len(results),
        dict(registry.last_search_metrics),
        icon_metrics,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", default=str(ROOT / "docs/screenshots/performance_benchmark.json"))
    args = parser.parse_args()
    iterations = max(5, args.iterations)

    app_cold = []
    app_counts = []
    app_cold_metrics = []
    app_cold_first = []
    for index in range(iterations):
        started = time.perf_counter()
        registry = ApplicationRegistry()
        elapsed, count, metrics, first_meaningful = measure_application_load(registry)
        app_cold.append((time.perf_counter() - started) * 1000)
        app_counts.append(count)
        app_cold_metrics.append(metrics)
        app_cold_first.append(first_meaningful)
        print(f"application cold {index + 1}/{iterations}: {app_cold[-1]:.1f} ms ({count} apps)", flush=True)

    hot_registry = ApplicationRegistry()
    measure_application_load(hot_registry)
    app_hot = []
    app_hot_metrics = []
    app_hot_first = []
    for index in range(iterations):
        elapsed, count, metrics, first_meaningful = measure_application_load(hot_registry)
        app_hot.append(elapsed)
        app_counts.append(count)
        app_hot_metrics.append(metrics)
        app_hot_first.append(first_meaningful)
        print(f"application hot {index + 1}/{iterations}: {elapsed:.1f} ms ({count} apps)", flush=True)

    store_cold = []
    store_hot = []
    store_counts = []
    store_cold_metrics = []
    store_cold_icon_metrics = []
    store_hot_metrics = []
    store_hot_icon_metrics = []
    for index in range(iterations):
        started = time.perf_counter()
        registry = StoreRegistry()
        elapsed, count, metrics, icon_metrics = measure_store_search(registry)
        store_cold.append((time.perf_counter() - started) * 1000)
        store_counts.append(count)
        store_cold_metrics.append(metrics)
        store_cold_icon_metrics.append(icon_metrics)
        print(f"store cold {index + 1}/{iterations}: {store_cold[-1]:.1f} ms ({count} results)", flush=True)

    hot_store_registry = StoreRegistry()
    measure_store_search(hot_store_registry)
    for index in range(iterations):
        elapsed, count, metrics, icon_metrics = measure_store_search(hot_store_registry)
        store_hot.append(elapsed)
        store_counts.append(count)
        store_hot_metrics.append(metrics)
        store_hot_icon_metrics.append(icon_metrics)
        print(f"store hot {index + 1}/{iterations}: {elapsed:.1f} ms ({count} results)", flush=True)

    result = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "iterations": iterations,
        "read_only": True,
        "application_load_ms": {"cold": summary(app_cold), "hot": summary(app_hot)},
        "application_first_meaningful_ms": {
            "cold": summary([value for value in app_cold_first if value is not None]),
            "hot": summary([value for value in app_hot_first if value is not None]),
        },
        "application_provider_metrics": {"cold": app_cold_metrics, "hot": app_hot_metrics},
        "store_search_ms": {"cold": summary(store_cold), "hot": summary(store_hot)},
        "store_cold_provider_metrics": store_cold_metrics,
        "store_hot_provider_metrics": store_hot_metrics,
        "store_cold_icon_metrics": store_cold_icon_metrics,
        "store_hot_icon_metrics": store_hot_icon_metrics,
        "application_counts": app_counts,
        "store_result_counts": store_counts,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
