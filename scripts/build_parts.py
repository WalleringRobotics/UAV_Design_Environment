"""Design -> printable parts for the survey wing.

    python scripts/build_parts.py                 # converge design <-> CAD, export everything
    python scripts/build_parts.py --no-converge   # one build with the current calibration.yaml
    python scripts/build_parts.py --config cm5    # place the light payload for the balance report

Writes outputs/parts/:
    stl/<part>.stl     print-oriented, centred on the CORE One+ bed
    step/<part>.step   aircraft frame, for CAD / inspection
    assembly.step      every part in place
    manifest.json      design numbers, balance, per-part fit / mass / print settings
    PRINT_LIST.md      the print queue with PrusaSlicer settings and assembly notes
    preview_*.png      shaded renders
and platforms/survey_wing/calibration.yaml (CAD-measured masses for the sizing loop).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uavdesign.fab import build as B  # noqa: E402
from uavdesign.fab.render import render  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform", default="survey_wing")
    ap.add_argument("--config", default="orin", help="payload config placed for the balance report")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "parts"))
    ap.add_argument("--no-converge", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    t0 = time.time()

    def say(msg):
        print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)

    if args.no_converge:
        result = B.build(args.platform, args.config, progress=say)
        history = []
    else:
        result, history = B.converge(args.platform, args.config, progress=say)
        for h in history:
            say("  " + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in h.items()))

    say("exporting")
    B.export(result, args.out)
    if not args.no_render:
        say("rendering")
        render(result.parts, Path(args.out) / "preview_iso.png", title="Survey wing — printed parts")
        render(result.parts, Path(args.out) / "preview_top.png", view=(90, -90))
        render(result.parts, Path(args.out) / "preview_exploded.png", exploded=60, view=(22, -140))
        render([bp for bp in result.parts if bp.part.group != "wing" and not bp.name.startswith("hatch")],
               Path(args.out) / "preview_pod.png", view=(16, 62), tol=0.8, cutaway_groups=("pod",),
               title="Pod cut-away: survey cage, spar box, avionics tray", zoom=1.0)

    b = result.balance
    say(f"parts: {len(result.parts)}, all fit: {result.all_fit}")
    say(f"printed mass: " + ", ".join(f"{k} {v:.0f} g" for k, v in result.printed_mass_g.items()))
    say(f"AUW {b.auw_g:.0f} g, CG {b.cg_x_mm:.1f} mm, NP {b.x_np_mm:.1f} mm, SM {b.static_margin:.1%} "
        f"(target {b.target_static_margin:.0%}), battery at x={b.battery_x_mm:.0f} mm")
    if not result.all_fit:
        bad = [bp.name for bp in result.parts if not bp.fit.fits]
        raise SystemExit(f"parts do not fit the printer: {bad}")


if __name__ == "__main__":
    main()
