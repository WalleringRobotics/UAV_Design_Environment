"""Write portable, unsliced 3MF geometry using millimetres and named objects."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
ET.register_namespace("", CORE)


def write_plate(path: Path, objects: list[tuple[str, np.ndarray]], title: str) -> None:
    """Placements are baked into vertices; no slicer-specific settings are implied."""
    model = ET.Element(f"{{{CORE}}}model", unit="millimeter", attrib={"{http://www.w3.org/XML/1998/namespace}lang": "en-US"})
    ET.SubElement(model, f"{{{CORE}}}metadata", name="Title").text = title
    ET.SubElement(model, f"{{{CORE}}}metadata", name="Description").text = "Arranged geometry; not sliced. Confirm printer, material, supports and toolpaths in a slicer."
    resources = ET.SubElement(model, f"{{{CORE}}}resources")
    build = ET.SubElement(model, f"{{{CORE}}}build")
    for number, (name, triangles) in enumerate(objects, 1):
        obj = ET.SubElement(resources, f"{{{CORE}}}object", id=str(number), type="model", name=name)
        mesh = ET.SubElement(obj, f"{{{CORE}}}mesh")
        vertices = ET.SubElement(mesh, f"{{{CORE}}}vertices")
        faces = ET.SubElement(mesh, f"{{{CORE}}}triangles")
        # Exact coordinate deduplication preserves the input mesh, without a weld
        # tolerance that could remove fine features or collapse faces.
        points, inverse = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
        for x, y, z in points:
            ET.SubElement(vertices, f"{{{CORE}}}vertex", x=format(x, ".12g"), y=format(y, ".12g"), z=format(z, ".12g"))
        for a, b, c in inverse.reshape(-1, 3):
            ET.SubElement(faces, f"{{{CORE}}}triangle", v1=str(a), v2=str(b), v3=str(c))
        ET.SubElement(build, f"{{{CORE}}}item", objectid=str(number))
    files = {
        "[Content_Types].xml": b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>',
        "_rels/.rels": b'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        "3D/3dmodel.model": ET.tostring(model, encoding="utf-8", xml_declaration=True),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            # Fixed metadata makes identical plans byte reproducible.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
