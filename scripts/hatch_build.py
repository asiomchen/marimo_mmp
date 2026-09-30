"""Build hook for the generated Anywidget frontend assets."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

ROOT = Path(__file__).resolve().parent.parent
ASSETS = (
    ROOT / "src/marimo_mmp/static/transform_graph.js",
    ROOT / "src/marimo_mmp/static/transform_graph.css",
)


class CustomBuildHook(BuildHookInterface):
    """Generate missing JavaScript and CSS before Hatch collects artifacts."""

    PLUGIN_NAME = "marimo-mmp-frontend"

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if all(asset.is_file() for asset in ASSETS):
            return
        if os.environ.get("MARIMO_MMP_SKIP_FRONTEND_BUILD") == "1":
            return

        try:
            subprocess.run(["npm", "run", "build"], cwd=ROOT, check=True)
        except FileNotFoundError as error:
            raise RuntimeError(
                "Node/npm is required to build marimo_mmp from a clean source checkout. "
                "Run `npm ci` before building the Python distribution."
            ) from error

        missing = [
            str(asset.relative_to(ROOT)) for asset in ASSETS if not asset.is_file()
        ]
        if missing:
            raise RuntimeError(
                f"Frontend build did not create required assets: {', '.join(missing)}"
            )
