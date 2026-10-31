"""Small, independently designed process coupons; never aircraft flight parts.

Dimensions are millimetres. Bore labels give DIAMETRAL clearance, not radial.
These solids intentionally do not encode material/process qualification.
"""
from __future__ import annotations

import json
from pathlib import Path
import zipfile

import cadquery as cq

from .parts import box, cylinder


def bore_gauge(nominal_mm: float, clearances=(0, .1, .2, .3, .4, .5, .6)):
    pitch = nominal_mm + 7
    width = nominal_mm + 19
    solid = box(0, len(clearances)*pitch + 5, 0, width, 0, 12)
    for i, clearance in enumerate(clearances):
        x, y = 2.5 + (i+.5)*pitch, nominal_mm/2+4
        solid = solid.cut(cylinder([x,y,-1], [x,y,13], nominal_mm+clearance))
        label = cq.Workplane('XY').text(f'+{clearance:.1f}', 3.2, .5, combine=False).val()
        solid = solid.fuse(label.translate((x,width-5,12)))
    return solid.clean()


def insert_gauge(diameters=(4.6,4.8,5.0,5.2,5.4), depth_mm=5.3):
    solid=box(0,len(diameters)*16,0,25,0,10)
    for i,d in enumerate(diameters):
        x=8+16*i
        solid=solid.cut(cylinder([x,8,10-depth_mm],[x,8,11],d))
        solid=solid.cut(cylinder([x,8,-1],[x,8,11],3.2))
        label=cq.Workplane('XY').text(f'{d:.1f}',3.5,.5,combine=False).val()
        solid=solid.fuse(label.translate((x,19,10)))
    return solid.clean()


def bond_strip():
    solid=box(0,80,0,20,0,3)
    return solid.cut(cylinder([7,10,-1],[7,10,4],3.4)).clean()


def build_coupons():
    parts={f'01_tube_{d:02d}mm_diametral_gauge_Rev1':bore_gauge(d)
           for d in (3,6,10,14,16)}
    parts['01_M3_insert_pilot_gauge_Rev1']=insert_gauge()
    parts['01_density_20x20x10_Rev1']=box(0,20,0,20,0,10)
    parts['01_wall_mass_30x30x20_Rev1']=box(0,30,0,30,0,20)
    parts['01_bond_strip_print_twice_Rev1']=bond_strip()
    return parts


def export_coupons(out_dir):
    from .printer import PrinterProfile, check_fit
    import numpy as np
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    printer=PrinterProfile('Prusa CORE One',250,220,270,5)
    records=[]
    for name,solid in build_coupons().items():
        if not solid.isValid() or len(solid.Solids())!=1:
            raise ValueError(f'Invalid/disconnected coupon: {name}')
        vertices,_=solid.tessellate(.1)
        fit=check_fit(np.array([[v.x,v.y,v.z] for v in vertices]),printer)
        if not fit.fits:raise ValueError(f'Coupon exceeds printer: {name}')
        path=out/(name+'.stl')
        cq.exporters.export(solid,str(path),tolerance=.05,angularTolerance=.1)
        b=solid.BoundingBox()
        records.append(dict(file=path.name,size_mm=[b.xlen,b.ylen,b.zlen],fits=True,
                            purpose='process/tolerance test only; not a flight part'))
    manifest=dict(schema_version='1.0',units='mm',bore_labels='added DIAMETRAL clearance in mm',
                  qualified_for_flight=False,parts=records)
    (out/'coupon_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
