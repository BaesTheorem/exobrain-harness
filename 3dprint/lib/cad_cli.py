"""cad: build, check, preview, and slice 3D-printable models from code.

Subcommands:
  build   <model.py> [-p k=v ...] [--out DIR] [--name N] [--formats stl,step,3mf] [--no-preview]
  scad    <model.scad> [-D k=v ...] [--out DIR] [--name N] [--no-preview]
  check   <mesh> [--printer NAME]
  fix     <mesh> [-o OUT]
  view    <mesh> [-o PNG] [--views iso,top,front,right,bottom] [--size WxH] [--crop y=a:b]
  slice   <mesh> [--printer NAME] [--layer MM] [--infill PCT] [--supports] [--gcode OUT]
  render  <mesh> [--material clay|color] [--up y] [--focus X,Y,Z --frame MM] [-o PNG]
  convert <in> <out>
  info

A model script sets a module-level ``result``: one build123d Shape or
trimesh.Trimesh, or a dict of name -> either for multi-part prints. The CLI
injects ``PARAMS`` (from -p k=v), ``OUT_DIR`` and ``NAME`` into the script
namespace before it runs, and puts lib/ on the import path (sdfmesh lives
there).

INVARIANTS:
  - ``check`` exits 1 when the mesh is not watertight or does not fit the
    selected printer. Callers rely on the exit code.
  - Every export goes under ``--out`` (default ``3dprint/out/<name>/``), which
    is gitignored. Nothing writes next to the source model.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import trimesh

HERE = Path(__file__).resolve().parent.parent
OUT_ROOT = HERE / "out"
PRINTERS_FILE = HERE / "printers.json"
PRUSA = Path("/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer")
OPENSCAD = shutil.which("openscad") or "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"
F3D = shutil.which("f3d") or "/opt/homebrew/bin/f3d"

PLA_DENSITY = 1.24  # g/cm3
OVERHANG_DEG = 45.0

VIEWS = {
    # name: (camera direction, view up)
    "iso": ("-1,1,-0.8", "0,0,1"),
    "iso2": ("1,-1,-0.8", "0,0,1"),
    "top": ("0,0,-1", "0,1,0"),
    "bottom": ("0,0,1", "0,1,0"),
    "front": ("0,1,0", "0,0,1"),
    "back": ("0,-1,0", "0,0,1"),
    "right": ("-1,0,0", "0,0,1"),
    "left": ("1,0,0", "0,0,1"),
}


# ---------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    log(f"cad: {msg}")
    sys.exit(code)


def load_printers() -> dict:
    if not PRINTERS_FILE.exists():
        return {"default": "generic", "printers": {"generic": {"bed": [220, 220], "height": 250, "nozzle": 0.4}}}
    return json.loads(PRINTERS_FILE.read_text())


def printer(name: str | None) -> tuple[str, dict]:
    data = load_printers()
    name = name or data.get("default", "generic")
    try:
        return name, data["printers"][name]
    except KeyError:
        die(f"unknown printer {name!r}; known: {', '.join(data['printers'])}")
    raise AssertionError  # unreachable, keeps pyright happy


def parse_kv(items: list[str] | None) -> dict:
    out: dict = {}
    for item in items or []:
        if "=" not in item:
            die(f"bad parameter {item!r}, want key=value")
        k, v = item.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def out_dir(args, src: Path) -> tuple[str, Path]:
    # models/<name>/build.py is named after its folder
    name = args.name or (src.parent.name if src.stem == "build" else src.stem)
    d = Path(args.out) if args.out else OUT_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    return name, d


def load_mesh(path: Path) -> "trimesh.Trimesh":
    import trimesh

    if not path.exists():
        die(f"no such file {path}")
    m = trimesh.load(str(path), force="mesh")
    if isinstance(m, trimesh.Scene):  # pragma: no cover - force=mesh prevents this
        m = trimesh.util.concatenate(list(m.geometry.values()))
    return cast("trimesh.Trimesh", m)


# ------------------------------------------------------------------ build

def export_meshes(meshes: dict, name: str, d: Path, formats: list[str]) -> list[Path]:
    """Export trimesh results (from sdfmesh or any mesh workflow). STEP needs
    exact B-rep geometry, so mesh results skip it."""
    import trimesh

    written: list[Path] = []
    multi = len(meshes) > 1
    for key, mesh in meshes.items():
        base = f"{name}_{key}" if multi else name
        if "stl" in formats:
            p = d / f"{base}.stl"
            mesh.export(str(p))
            written.append(p)
        if "3mf" in formats and not multi:
            p = d / f"{base}.3mf"
            trimesh.Scene({key: mesh}).export(str(p))
            written.append(p)
    if multi and "3mf" in formats:
        p = d / f"{name}.3mf"
        trimesh.Scene(dict(meshes)).export(str(p))
        written.append(p)
    return written


def export_shapes(shapes: dict, name: str, d: Path, formats: list[str]) -> list[Path]:
    from build123d import Mesher, export_step, export_stl

    written: list[Path] = []
    multi = len(shapes) > 1
    for key, shape in shapes.items():
        base = f"{name}_{key}" if multi else name
        if "stl" in formats:
            p = d / f"{base}.stl"
            export_stl(shape, str(p), tolerance=0.01, angular_tolerance=0.1)
            written.append(p)
        if "step" in formats:
            p = d / f"{base}.step"
            export_step(shape, str(p))
            written.append(p)
        if "3mf" in formats and not multi:
            p = d / f"{base}.3mf"
            m = Mesher()
            m.add_shape(shape, part_number=key)
            m.write(str(p))
            written.append(p)
    if multi and "3mf" in formats:
        p = d / f"{name}.3mf"
        m = Mesher()
        for key, shape in shapes.items():
            m.add_shape(shape, part_number=key)
        m.write(str(p))
        written.append(p)
    return written


def cmd_build(args) -> int:
    src = Path(args.model).resolve()
    if not src.exists():
        die(f"no such model {src}")
    name, d = out_dir(args, src)
    params = parse_kv(args.param)
    formats = [f.strip().lower() for f in args.formats.split(",")]

    import build123d  # noqa: F401  (import error surfaces here, before exec)
    import trimesh

    # OUT_DIR and NAME let a script write extra artifacts (a coloured preview,
    # debug maps) next to the exports; lib/ is importable for helpers such as
    # sdfmesh.
    ns: dict = {"__name__": "__cad__", "__file__": str(src), "PARAMS": params,
                "OUT_DIR": d, "NAME": name}
    sys.path.insert(0, str(src.parent))
    sys.path.insert(0, str(HERE / "lib"))
    code = compile(src.read_text(), str(src), "exec")
    exec(code, ns)  # noqa: S102 - the model script is Alex's own code
    result = ns.get("result")
    if result is None:
        die("model script must set `result` (a Shape, a trimesh, or a dict of either)")
    shapes = result if isinstance(result, dict) else {"part": result}

    if all(isinstance(v, trimesh.Trimesh) for v in shapes.values()):
        written = export_meshes(shapes, name, d, formats)
    else:
        written = export_shapes(shapes, name, d, formats)
    (d / f"{name}.params.json").write_text(json.dumps(params, indent=2) + "\n")
    for p in written:
        log(f"wrote {p}")
    log("embed in the Console with: ![name](<absolute .stl or .3mf path>)")

    rc = 0
    for p in written:
        if p.suffix == ".stl":
            rc |= report_mesh(p, args.printer)
            if not args.no_preview:
                sheet = render_views(p, p.with_suffix(".png"), list(VIEWS)[:1] + ["top", "front", "right"], (640, 480))
                log(f"preview {sheet}")
    return rc


# ------------------------------------------------------------------- scad

def cmd_scad(args) -> int:
    src = Path(args.model).resolve()
    if not src.exists():
        die(f"no such model {src}")
    name, d = out_dir(args, src)
    stl = d / f"{name}.stl"
    cmd = [OPENSCAD, "-o", str(stl), "--export-format", "binstl", "--backend", "manifold"]
    for item in args.define or []:
        cmd += ["-D", item]
    cmd.append(str(src))
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = "\n".join(r.stderr.strip().splitlines()[-8:])
    if r.returncode != 0 or not stl.exists():
        die(f"openscad failed:\n{tail}")
    for line in tail.splitlines():
        if "WARNING" in line or "ERROR" in line:
            log(line)
    log(f"wrote {stl}")
    rc = report_mesh(stl, args.printer)
    if not args.no_preview:
        sheet = render_views(stl, stl.with_suffix(".png"), ["iso", "top", "front", "right"], (640, 480))
        log(f"preview {sheet}")
    return rc


# ------------------------------------------------------------------ check

def mesh_stats(m, prof: dict) -> dict:
    import numpy as np

    ext = m.bounding_box.extents
    zmin = float(m.bounds[0][2])
    normals = m.face_normals
    areas = m.area_faces
    total_area = float(areas.sum()) or 1.0

    # Faces touching the bed: all three vertices within 0.05 mm of z-min, facing down.
    vz = m.vertices[m.faces][:, :, 2]
    on_bed = (vz.max(axis=1) < zmin + 0.05) & (normals[:, 2] < -0.9)
    bed_area = float(areas[on_bed].sum())

    # Overhangs: faces whose normal points down more than OVERHANG_DEG from vertical,
    # excluding the bed contact faces.
    thresh = -math.sin(math.radians(OVERHANG_DEG))
    over = (normals[:, 2] < thresh) & ~on_bed
    over_area = float(areas[over].sum())
    worst = 0.0
    if over.any():
        worst = float(np.degrees(np.arccos(np.clip(-normals[over, 2], -1, 1))).min())
        worst = 90.0 - worst  # angle of the surface from vertical

    bodies = len(m.split(only_watertight=False))
    bed = sorted(prof["bed"])
    dims_xy = sorted(ext[:2])
    fits = bool(dims_xy[0] <= bed[0] and dims_xy[1] <= bed[1] and ext[2] <= prof["height"])
    footprint_min = max(min(ext[0], ext[1]), 1e-6)

    vol_mm3 = float(m.volume) if m.is_volume else float("nan")
    return {
        "size_mm": [round(float(x), 2) for x in ext],
        "volume_cm3": round(vol_mm3 / 1000, 2) if not math.isnan(vol_mm3) else None,
        "mass_pla_solid_g": round(vol_mm3 / 1000 * PLA_DENSITY, 1) if not math.isnan(vol_mm3) else None,
        "faces": int(len(m.faces)),
        "watertight": bool(m.is_watertight),
        "winding_consistent": bool(m.is_winding_consistent),
        "bodies": bodies,
        "bed_contact_mm2": round(bed_area, 1),
        "overhang_pct": round(100 * over_area / total_area, 1),
        "worst_overhang_deg": round(worst, 1) if bool(over.any()) else 0.0,
        "tall_ratio": round(float(ext[2]) / footprint_min, 2),
        "fits_printer": fits,
    }


def report_mesh(path: Path, printer_name: str | None) -> int:
    pname, prof = printer(printer_name)
    m = load_mesh(path)
    s = mesh_stats(m, prof)
    x, y, z = s["size_mm"]
    print(f"{path.name}: {x} x {y} x {z} mm, {s['faces']} faces, {s['bodies']} body(ies)")
    if s["volume_cm3"] is not None:
        print(f"  volume {s['volume_cm3']} cm3, about {s['mass_pla_solid_g']} g PLA solid "
              f"(~{round(s['mass_pla_solid_g'] * 0.45, 1)} g at 15% infill, walls dominate small parts)")
    print(f"  watertight: {'yes' if s['watertight'] else 'NO'}   winding: {'ok' if s['winding_consistent'] else 'BAD'}")
    print(f"  bed contact {s['bed_contact_mm2']} mm2   overhangs >{OVERHANG_DEG:g}deg: {s['overhang_pct']}% of surface"
          + (f" (worst {s['worst_overhang_deg']}deg from vertical)" if s["overhang_pct"] else ""))
    bed = prof["bed"]
    print(f"  printer {pname}: bed {bed[0]}x{bed[1]}x{prof['height']} mm -> {'fits' if s['fits_printer'] else 'DOES NOT FIT'}"
          + ("" if prof.get("confirmed", True) else "  [profile unconfirmed]"))
    flags = []
    if not s["watertight"]:
        flags.append("not watertight: run `cad fix`")
    if s["bodies"] > 1:
        flags.append(f"{s['bodies']} separate bodies in one file; intended?")
    if s["overhang_pct"] > 5:
        flags.append("overhangs need supports or a different orientation")
    if s["bed_contact_mm2"] < 100 and z > 20:
        flags.append("small bed contact: brim or reorient")
    if s["tall_ratio"] > 3:
        flags.append("tall and thin: tip-over risk, brim or lay flat")
    for f in flags:
        print(f"  ! {f}")
    (path.with_suffix(".check.json")).write_text(json.dumps(s, indent=2) + "\n")
    return 0 if (s["watertight"] and s["fits_printer"]) else 1


def cmd_check(args) -> int:
    return report_mesh(Path(args.mesh).resolve(), args.printer)


# -------------------------------------------------------------------- fix

def cmd_fix(args) -> int:
    import trimesh

    src = Path(args.mesh).resolve()
    m = load_mesh(src)
    before = m.is_watertight
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(m)
    trimesh.repair.fix_winding(m)
    trimesh.repair.fill_holes(m)
    if not m.is_watertight:
        # MeshFix closes real holes and removes self-intersections; trimesh's
        # fill_holes only handles single-triangle gaps.
        import numpy as np
        import pymeshfix

        mf = pymeshfix.MeshFix(np.asarray(m.vertices), np.asarray(m.faces))
        mf.repair()
        m = trimesh.Trimesh(mf.points, mf.faces)
    out = Path(args.output) if args.output else src.with_name(src.stem + "_fixed" + src.suffix)
    m.export(str(out))
    print(f"{src.name}: watertight {before} -> {m.is_watertight}; wrote {out}")
    return 0 if m.is_watertight else 1


# ------------------------------------------------------------------- view

def crop_mesh(mesh: Path, spec: str, td: str) -> Path:
    """Cut a mesh to an axis box ("y=150:192" or "x=-5:5,y=100:140") so f3d
    frames that region; f3d always fits the camera to the whole file."""
    import numpy as np
    import trimesh

    m = load_mesh(mesh)
    keep = np.ones(len(m.faces), dtype=bool)
    centres = m.triangles_center
    for part in spec.split(","):
        axis, rng = part.split("=")
        lo, hi = (float(v) for v in rng.split(":"))
        k = "xyz".index(axis.strip())
        keep &= (centres[:, k] >= lo) & (centres[:, k] <= hi)
    m = cast("trimesh.Trimesh", m.submesh([np.nonzero(keep)[0]], append=True))
    out = Path(td) / f"{mesh.stem}_crop.stl"
    trimesh.Trimesh(m.vertices, m.faces).export(str(out))
    return out


def render_views(mesh: Path, out_png: Path, views: list[str], size: tuple[int, int],
                 crop: str | None = None) -> Path:
    from PIL import Image, ImageDraw

    tiles: list[tuple[str, Path]] = []
    with tempfile.TemporaryDirectory() as td:
        if crop:
            mesh = crop_mesh(mesh, crop, td)
        # edge lines help on a few-thousand-face CAD part and black out a dense
        # mesh; a binary STL is 84 bytes plus 50 per face
        edges = mesh.suffix.lower() == ".stl" and (mesh.stat().st_size - 84) / 50 < 20000
        for v in views:
            if v not in VIEWS:
                die(f"unknown view {v!r}; known: {', '.join(VIEWS)}")
            direction, up = VIEWS[v]
            png = Path(td) / f"{v}.png"
            cmd = [F3D, str(mesh), "--output", str(png), "--resolution", f"{size[0]},{size[1]}",
                   "--up=+Z", f"--camera-direction={direction}", f"--camera-view-up={up}",
                   "--grid", "--grid-absolute", "--axis", "--anti-aliasing", "--ambient-occlusion",
                   "--background-color=#f4f1ea", "--color=#8aa0b8", "--verbose=error"]
            if edges:
                cmd += ["--edges", "--line-width=0.6"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not png.exists():
                die(f"f3d failed on {v}: {r.stderr.strip()[-400:]}")
            tiles.append((v, png))
        cols = 2 if len(tiles) > 1 else 1
        rows = math.ceil(len(tiles) / cols)
        w, h = size
        sheet = Image.new("RGB", (cols * w, rows * h), "#f4f1ea")
        draw = ImageDraw.Draw(sheet)
        for i, (label, png) in enumerate(tiles):
            im = Image.open(png).convert("RGB")
            x, y = (i % cols) * w, (i // cols) * h
            sheet.paste(im, (x, y))
            draw.rectangle([x + 8, y + 8, x + 16 + 7 * len(label), y + 26], fill="#222")
            draw.text((x + 12, y + 11), label, fill="#f4f1ea")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_png)
    return out_png


def cmd_view(args) -> int:
    mesh = Path(args.mesh).resolve()
    out = Path(args.output) if args.output else mesh.with_suffix(".png")
    w, h = (int(x) for x in args.size.lower().split("x"))
    views = [v.strip() for v in args.views.split(",")]
    p = render_views(mesh, out, views, (w, h), crop=args.crop)
    print(p)
    return 0


# ------------------------------------------------------------------ slice

def cmd_slice(args) -> int:
    if not PRUSA.exists():
        die("PrusaSlicer.app not installed (brew install --cask prusaslicer)")
    mesh = Path(args.mesh).resolve()
    pname, prof = printer(args.printer)
    gcode = Path(args.gcode) if args.gcode else mesh.with_suffix(".gcode")
    bx, by = prof["bed"]
    cmd = [str(PRUSA), "--export-gcode", "--output", str(gcode),
           "--bed-shape", f"0x0,{bx}x0,{bx}x{by},0x{by}",
           "--max-print-height", str(prof["height"]),
           "--nozzle-diameter", str(prof.get("nozzle", 0.4)),
           "--filament-diameter", "1.75", "--filament-density", str(PLA_DENSITY),
           "--layer-height", str(args.layer), "--first-layer-height", str(max(args.layer, 0.2)),
           "--fill-density", f"{args.infill}%", "--perimeters", "3",
           "--temperature", "210", "--bed-temperature", "60", "--first-layer-temperature", "215",
           "--gcode-flavor", prof.get("gcode_flavor", "marlin2")]
    if args.infill >= 100:
        cmd += ["--fill-pattern", "rectilinear"]   # the default gyroid refuses 100%
    if args.supports:
        cmd += ["--support-material", "--support-material-auto"]
    for ini in prof.get("prusa_ini", []):
        cmd += ["--load", str(Path(ini).expanduser())]
    cmd.append(str(mesh))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not gcode.exists():
        die(f"prusa-slicer failed:\n{r.stderr.strip()[-800:]}\n{r.stdout.strip()[-800:]}")
    text = gcode.read_text(errors="ignore")
    info = {}
    for key, pat in {
        "time": r"; estimated printing time \(normal mode\) = (.+)",
        "filament_m": r"; filament used \[mm\] = ([\d.]+)",
        "filament_g": r"; total filament used \[g\] = ([\d.]+)",
        "layers": r"; total layers count = (\d+)",
    }.items():
        mo = re.search(pat, text)
        if mo:
            info[key] = mo.group(1)
    # "Alert if supports needed" is a progress step printed on every slice; the
    # real signal is the stability warning and the issue list on the next line.
    out_all = r.stdout + r.stderr
    issues = ""
    mo = re.search(r"Detected print stability issues:\s*\n\s*\n?.*?\n(.+?)\n", out_all)
    if mo:
        issues = mo.group(1).strip()
    supports_needed = "Detected print stability issues" in out_all
    fil_m = float(info.get("filament_m", 0)) / 1000
    print(f"{mesh.name} on {pname}: layer {args.layer} mm, infill {args.infill}%"
          + (", supports" if args.supports else ""))
    print(f"  print time {info.get('time', '?')}, filament {fil_m:.2f} m / {info.get('filament_g', '?')} g PLA"
          + (f", {info['layers']} layers" if "layers" in info else ""))
    if supports_needed:
        print(f"  ! slicer stability warning: {issues or 'see PrusaSlicer output'}")
    print(f"  gcode {gcode} (generic profile; for the Bambu, slice the STL/3MF in Bambu Studio)")
    return 0


# ----------------------------------------------------------------- render

def find_blender() -> str:
    for c in (shutil.which("blender"), "/Applications/Blender.app/Contents/MacOS/Blender"):
        if c and Path(c).exists():
            return c
    die("Blender not found (brew install --cask blender)")
    raise AssertionError


def cmd_render(args) -> int:
    mesh = Path(args.mesh).resolve()
    if not mesh.exists():
        die(f"no such file {mesh}")
    out = Path(args.output).resolve() if args.output else mesh.with_name(f"{mesh.stem}_{args.material}.png")
    cmd = [find_blender(), "-b", "--factory-startup", "-P", str(HERE / "lib" / "blender_render.py"), "--",
           str(mesh), str(out), "--material", args.material, "--up", args.up,
           "--azimuth", str(args.azimuth), "--elevation", str(args.elevation),
           "--size", args.size, "--samples", str(args.samples), "--lens", str(args.lens)]
    if args.focus:
        cmd += ["--focus", args.focus]
    if args.frame:
        cmd += ["--frame", str(args.frame)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        die(f"blender failed:\n{(r.stdout + r.stderr).strip()[-1500:]}")
    print(out)
    return 0


# ---------------------------------------------------------------- convert

def cmd_convert(args) -> int:
    m = load_mesh(Path(args.src).resolve())
    out = Path(args.dst).resolve()
    m.export(str(out))
    print(f"wrote {out} ({len(m.faces)} faces)")
    return 0


# ------------------------------------------------------------------- info

def cmd_info(_args) -> int:
    def ver(cmd: list[str]) -> str:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except Exception as e:  # noqa: BLE001
            return f"missing ({e.__class__.__name__})"

    from importlib.metadata import version

    print(f"python      {sys.version.split()[0]}  ({sys.executable})")
    for pkg in ("build123d", "trimesh", "manifold3d", "pymeshfix"):
        print(f"{pkg:<11} {version(pkg)}")
    print(f"openscad    {ver([OPENSCAD, '--version'])}")
    print(f"f3d         {ver([F3D, '--version'])}")
    print(f"prusaslicer {ver([str(PRUSA), '--help']) if PRUSA.exists() else 'missing'}")
    bosl = Path.home() / "Documents/OpenSCAD/libraries/BOSL2"
    print(f"BOSL2       {'present' if bosl.exists() else 'missing'} ({bosl})")
    data = load_printers()
    print(f"printers    default={data.get('default')}  known={', '.join(data['printers'])}")
    return 0


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cad", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="run a build123d model script and export it")
    b.add_argument("model")
    b.add_argument("-p", "--param", action="append", help="k=v passed as PARAMS[k]")
    b.add_argument("--out")
    b.add_argument("--name")
    b.add_argument("--formats", default="stl,step,3mf")
    b.add_argument("--printer")
    b.add_argument("--no-preview", action="store_true")
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("scad", help="render an OpenSCAD file to STL (manifold backend)")
    s.add_argument("model")
    s.add_argument("-D", "--define", action="append", help="OpenSCAD -D var=value")
    s.add_argument("--out")
    s.add_argument("--name")
    s.add_argument("--printer")
    s.add_argument("--no-preview", action="store_true")
    s.set_defaults(fn=cmd_scad)

    c = sub.add_parser("check", help="printability report for a mesh")
    c.add_argument("mesh")
    c.add_argument("--printer")
    c.set_defaults(fn=cmd_check)

    f = sub.add_parser("fix", help="repair a mesh (normals, holes, duplicates)")
    f.add_argument("mesh")
    f.add_argument("-o", "--output")
    f.set_defaults(fn=cmd_fix)

    v = sub.add_parser("view", help="render a contact sheet of views to PNG")
    v.add_argument("mesh")
    v.add_argument("-o", "--output")
    v.add_argument("--views", default="iso,top,front,right")
    v.add_argument("--size", default="640x480")
    v.add_argument("--crop", help='only this region, e.g. "y=150:197" or "x=-8:8,y=100:140"')
    v.set_defaults(fn=cmd_view)

    sl = sub.add_parser("slice", help="slice with PrusaSlicer for time and filament estimates")
    sl.add_argument("mesh")
    sl.add_argument("--printer")
    sl.add_argument("--layer", type=float, default=0.2)
    sl.add_argument("--infill", type=int, default=15)
    sl.add_argument("--supports", action="store_true")
    sl.add_argument("--gcode")
    sl.set_defaults(fn=cmd_slice)

    rd = sub.add_parser("render", help="studio render in Blender (Cycles, GPU): clay or vertex colours")
    rd.add_argument("mesh")
    rd.add_argument("-o", "--output")
    rd.add_argument("--material", default="clay", choices=["clay", "color"])
    rd.add_argument("--up", default="z", choices=["x", "y", "z"], help="model axis that points up in the shot")
    rd.add_argument("--azimuth", type=float, default=-30.0)
    rd.add_argument("--elevation", type=float, default=10.0)
    rd.add_argument("--focus", help="centre of the shot, model mm: X,Y,Z")
    rd.add_argument("--frame", type=float, help="height of the framed region, mm")
    rd.add_argument("--size", default="1080x1620")
    rd.add_argument("--samples", type=int, default=96)
    rd.add_argument("--lens", type=float, default=70.0)
    rd.set_defaults(fn=cmd_render)

    cv = sub.add_parser("convert", help="convert between stl/obj/3mf/ply/off")
    cv.add_argument("src")
    cv.add_argument("dst")
    cv.set_defaults(fn=cmd_convert)

    i = sub.add_parser("info", help="toolchain versions and printer profiles")
    i.set_defaults(fn=cmd_info)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
