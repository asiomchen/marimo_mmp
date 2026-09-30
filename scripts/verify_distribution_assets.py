"""Verify that built distributions contain the generated widget assets."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

RUNTIME_ASSETS = (
    "marimo_mmp/static/transform_graph.js",
    "marimo_mmp/static/transform_graph.css",
)
SDIST_SOURCES = (
    "frontend/transform_graph.ts",
    "frontend/transform_graph/graph.ts",
    "frontend/transform_graph.css",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
)


def _names(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return set(archive.namelist())
    with tarfile.open(path, "r:gz") as archive:
        return set(archive.getnames())


def _contains(names: set[str], suffix: str) -> bool:
    return any(name == suffix or name.endswith(f"/{suffix}") for name in names)


def verify(path: Path) -> None:
    names = _names(path)
    missing = [asset for asset in RUNTIME_ASSETS if not _contains(names, asset)]
    if path.name.endswith(".tar.gz"):
        missing.extend(
            source for source in SDIST_SOURCES if not _contains(names, source)
        )
    if missing:
        raise SystemExit(f"{path}: missing {', '.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("distributions", nargs="+", type=Path)
    args = parser.parse_args()
    for distribution in args.distributions:
        verify(distribution)
        print(f"verified {distribution}")


if __name__ == "__main__":
    main()
