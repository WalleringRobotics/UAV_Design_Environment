"""Generate every platform's notebooks from source-of-truth Python strings.

Notebooks are checked in (so they render on GitHub), but this script lets us
regenerate them after editing cells without juggling JSON by hand. Cell
content lives in `scripts/nbdefs/<platform>.py`.

Run from repo root:
    python scripts/build_notebooks.py              # all platforms
    python scripts/build_notebooks.py multirotor   # one platform
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nbdefs import multirotor, survey_wing  # noqa: E402
from nbdefs._nb import notebook  # noqa: E402

PLATFORMS = {
    "multirotor": multirotor.NOTEBOOKS,
    "survey_wing": survey_wing.NOTEBOOKS,
}


def main(selected: list[str]) -> None:
    for platform in selected or PLATFORMS:
        if platform not in PLATFORMS:
            raise SystemExit(f"unknown platform {platform!r}; choose from {list(PLATFORMS)}")
        for name, cells in PLATFORMS[platform].items():
            path = ROOT / "platforms" / platform / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(notebook(cells), indent=1) + "\n")
            print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
