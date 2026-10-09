"""Helpers for building notebooks from Python strings."""

from __future__ import annotations

import hashlib


def _id(kind: str, source: str) -> str:
    """Deterministic 8-char cell id derived from kind + source.

    Stable across regeneration so reruns of the build script only diff cells
    whose content actually changed.
    """
    h = hashlib.sha1(f"{kind}\0{source}".encode("utf-8")).hexdigest()
    return h[:8]


def md(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": _id("markdown", source),
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "id": _id("code", source),
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def bootstrap(platform: str) -> str:
    """Shared first code cell: locate the repo, import `uavdesign`, set paths."""
    return f'''\
"""Locate the repo root so `import uavdesign` works without `pip install -e .`."""
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
while not (REPO_ROOT / "uavdesign").is_dir() and REPO_ROOT != REPO_ROOT.parent:
    REPO_ROOT = REPO_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

PLATFORM_DIR = REPO_ROOT / "platforms" / "{platform}"
FIG_DIR = REPO_ROOT / "outputs" / "figures" / "{platform}"
FIG_DIR.mkdir(parents=True, exist_ok=True)

import yaml
import numpy as np
import matplotlib.pyplot as plt
'''
