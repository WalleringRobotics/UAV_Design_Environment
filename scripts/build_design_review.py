"""Export executed notebooks, CAD drawings and a runnable independent-review snapshot."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/design_review")
    args = parser.parse_args()
    from uavdesign.design_review import export_design_review
    result = export_design_review(ROOT, args.out, progress=lambda message: print(message, flush=True))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
