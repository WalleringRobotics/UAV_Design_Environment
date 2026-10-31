"""Export small Core One process coupons and the current verification instructions."""
import argparse
from pathlib import Path
import sys,shutil,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from uavdesign.fab.coupons import export_coupons

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',default=str(ROOT/'outputs/verification/Survey_Wing_First_Prints_Rev1'))
    args=ap.parse_args();out=Path(args.out)
    export_coupons(out)
    shutil.copy2(ROOT/'docs/first_prints.md',out/'START_HERE.md')
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out))
    print(archive)

if __name__=='__main__':main()
