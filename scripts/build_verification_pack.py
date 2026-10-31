"""Export small Core One process coupons and the current verification instructions."""
import argparse
from pathlib import Path
import sys,shutil,zipfile,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from uavdesign.fab.coupons import export_coupons


def export_interfaces(out):
    """Small fit-only parts from a current, checksum-verified aircraft export."""
    import cadquery as cq
    import numpy as np
    from uavdesign.fab.parts import Part,box
    from uavdesign.fab.printer import PrinterProfile,check_fit
    from uavdesign.fab.build import print_oriented
    from types import SimpleNamespace
    source=ROOT/'outputs/parts'
    manifest=json.loads((source/'manifest.json').read_text())
    release=json.loads((ROOT/'outputs/review/release_manifest.json').read_text())
    for rel,digest in release['source_sha256'].items():
        if rel.startswith(('uavdesign/','platforms/survey_wing/','payload/','mission/')):
            if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=digest:
                raise ValueError(f'Stale aircraft geometry; rebuild before exporting interfaces: {rel}')
    names=['servo_tray_R','servo_clamp_R','servo_cover_R',
           'pod_root_anchor_R','wing_root_anchor_R','wing_root_bridge_R']
    out.mkdir(parents=True,exist_ok=True)
    for name in names:
        rel='stl/'+name+'.stl';p=source/rel
        if hashlib.sha256(p.read_bytes()).hexdigest()!=manifest['file_sha256'][rel]:
            raise ValueError(f'Changed aircraft STL: {name}')
        shutil.copy2(p,out/('02_'+name+'_Rev1.stl'))
    def load(name):
        rel='step/'+name+'.step';path=source/rel
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['file_sha256'][rel]:
            raise ValueError(f'Changed aircraft STEP: {name}')
        return cq.importers.importStep(str(path)).val()
    anchor=load('wing_root_anchor_R');bounds=anchor.BoundingBox()
    xc=(bounds.xmin+bounds.xmax)/2;root=manifest['design']['pod_width_mm']/2
    cut=box(xc-18,xc+18,root,root+44,-200,200)
    wings=[r['part'] for r in manifest['parts'] if r['part'].startswith('wing_seg1_R')]
    pieces=[load(n).intersect(cut) for n in wings]
    pieces=[p for p in pieces if p.Volume()>1]
    if len(pieces)!=1:raise ValueError('Wing patch no longer lies inside one root part; revise crop')
    pod=load('pod_tail').intersect(box(xc-18,xc+18,root-35,root+.1,bounds.zmin-8,bounds.zmax+12))
    printer=PrinterProfile.from_dict(manifest['printer'])
    for name,solid,up in [('03_wing_root_seat_fit_fixture_Rev1',pieces[0],(0,1,0)),
                           ('03_pod_root_seat_fit_fixture_Rev1',pod,(1,0,0))]:
        if not solid.isValid() or len(solid.Solids())!=1:raise ValueError('Disconnected fit patch: '+name)
        vertices,_=solid.tessellate(.1)
        fit=check_fit(np.array([[v.x,v.y,v.z] for v in vertices]),printer,up)
        if not fit.fits:raise ValueError('Oversized fit patch: '+name)
        oriented=print_oriented(SimpleNamespace(part=Part(name,solid,'structural',up),fit=fit),printer)
        cq.exporters.export(oriented,str(out/(name+'.stl')),tolerance=.05)
    (out/'source_manifest.json').write_text(json.dumps({'result_signature':manifest['result_signature'],
       'source_manifest_sha256':hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
       'qualified_for_flight':False,'root_patches':'cropped fit fixtures; not complete load paths'},indent=2)+'\n')
    shutil.copy2(ROOT/'docs/interface_dry_fits.md',out/'START_HERE.md')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out')
    ap.add_argument('--interfaces',action='store_true',help='Use the current full CAD export for the next small dry-fit parts')
    args=ap.parse_args()
    default='Survey_Wing_Interface_Dry_Fit_Rev1' if args.interfaces else 'Survey_Wing_First_Prints_Rev1'
    out=Path(args.out) if args.out else ROOT/'outputs/verification'/default
    if args.interfaces:export_interfaces(out)
    else:
        export_coupons(out)
        shutil.copy2(ROOT/'docs/first_prints.md',out/'START_HERE.md')
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out))
    print(archive)

if __name__=='__main__':main()
