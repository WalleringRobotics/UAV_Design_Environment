# First-print verification pack

[Download Survey_Wing_First_Prints_Rev1.zip](Survey_Wing_First_Prints_Rev1.zip)
and read `START_HERE.md` inside it. It contains nine independent process-coupon
STLs plus a geometry/fit manifest. These are small test pieces, not aircraft
parts or G-code. All dimensions are millimetres.

Source: `uavdesign/fab/coupons.py`; regenerate using
`python scripts/build_verification_pack.py`. The checked-in ZIP makes the first
prints available without installing the CAD environment. Use
[the detailed print/measurement guide](../../../docs/first_prints.md) for the
order, materials and measurements. Structural and servo/root dry-fit work is
tracked in [the improvement register](../../../docs/build_improvements.md).

After the coupons, use
[Survey_Wing_Interface_Dry_Fit_Rev1.zip](Survey_Wing_Interface_Dry_Fit_Rev1.zip)
for the six small servo/root parts and two cropped seat-fit fixtures from the
revised aircraft. Its `START_HERE.md` describes hardware, material profiles and
measurements. The seat fixtures check fit and bonding access; they are not full
wing-root load paths. Regenerate using
`python scripts/build_verification_pack.py --interfaces` after a current full
CAD/review export.

After changing coupon geometry or the guide, regenerate and deliberately
replace this versioned pack; do not serve a stale generated ZIP as current.
