"""sdfmesh: printable meshes from signed distance fields.

Describe a part as a field F(x, y, z) that is negative inside the solid. The
helpers here sample it on a regular lattice in slabs along y, run marching
cubes on each slab and stitch the slabs into one closed mesh. The 2D helpers
turn an image mask into a signed distance map and a local-thickness map, which
is how a traced silhouette becomes a heightfield relief that unions with true
3D primitives (ellipsoids, tubes, rings).

Typical use (see models/snicker_snack/build.py):

    xs, ys, zs = sdfmesh.lattice((-20, 20), (0, 150), (-5, 5), 0.1)
    def field(j0, j1):          # rows ys[j0:j1] -> array (j1-j0, len(xs), len(zs))
        ...
    mesh = sdfmesh.mesh_from_field(field, xs, ys, zs)

INVARIANTS:
  - Adjacent slabs share one sample row and all slabs use the same x and z
    lattice, so the boundary vertices of two slabs are bit-identical and merge
    into a closed mesh.
  - Fields are negative inside and positive outside; the surface is level 0.
  - z samples sit at half-steps (z = (k + 0.5) * res), so the plane z = 0 lies
    between samples and a cut there is clean.
"""

from __future__ import annotations

from typing import cast

import numpy as np
from scipy import ndimage as ndi


# ------------------------------------------------------------------ lattice

def lattice(xr, yr, zr, res):
    """Sample coordinates for a box. x and y include 0 when the range does;
    z is offset by half a step so z = 0 falls between two samples."""
    xs = np.round(np.arange(xr[0], xr[1] + res / 2, res), 6)
    ys = np.round(np.arange(yr[0], yr[1] + res / 2, res), 6)
    k0 = int(np.floor(zr[0] / res - 0.5))
    k1 = int(np.ceil(zr[1] / res - 0.5))
    zs = np.round((np.arange(k0, k1 + 1) + 0.5) * res, 6)
    return xs, ys, zs


# --------------------------------------------------------------- 2D helpers

def edt(mask: np.ndarray) -> np.ndarray:
    """Euclidean distance (pixels) from each True pixel to the nearest False."""
    return np.asarray(ndi.distance_transform_edt(mask), dtype=np.float64)


def sdf2d(mask: np.ndarray, res: float) -> np.ndarray:
    """Signed distance (mm) to the edge of a boolean mask, negative inside."""
    inside = edt(mask)
    outside = edt(~mask)
    return (outside - inside) * res


def local_thickness(mask: np.ndarray, res: float, r_max: float) -> np.ndarray:
    """Radius (mm) of the largest disk inside `mask` that covers each pixel,
    capped at r_max, 0 outside. A vine 2 mm wide reads 1.0 along its whole
    cross-section, which is what a round-tube profile needs."""
    dt = edt(mask) * res
    lt = np.zeros(mask.shape)
    for r in np.arange(res / 2, r_max + 1e-9, res / 2):
        core = dt >= r
        if not core.any():
            break
        reach = (edt(~core) * res) < r   # core dilated by r
        lt[reach & mask] = r
    return lt


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------- 3D helpers

def smin(a, b, k):
    """Polynomial smooth union; k is the blend radius in mm."""
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def ellipsoid(u, v, w, a, b, c):
    """Approximate signed distance to an axis-aligned ellipsoid with semi-axes
    a, b, c (exact on the surface, which is all marching cubes needs)."""
    k0 = np.sqrt((u / a) ** 2 + (v / b) ** 2 + (w / c) ** 2)
    k1 = np.sqrt((u / a ** 2) ** 2 + (v / b ** 2) ** 2 + (w / c ** 2) ** 2)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def rounded_box2(p, q, hx, hy, r):
    """Signed distance to a 2D rounded rectangle centred at 0 with half-sizes
    hx, hy and corner radius r."""
    dx = np.abs(p) - (hx - r)
    dy = np.abs(q) - (hy - r)
    out = np.hypot(np.maximum(dx, 0), np.maximum(dy, 0))
    return np.minimum(np.maximum(dx, dy), 0) + out - r


def wrap_angle(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


# ---------------------------------------------------------------- meshing

def mesh_from_field(field, xs, ys, zs, slab: int = 128, level: float = 0.0, progress=None):
    """Mesh the level set of `field` over the lattice.

    field(j0, j1) must return a float array of shape (j1 - j0, len(xs),
    len(zs)) for the rows ys[j0:j1]. Slabs overlap by one row; vertices are
    built from integer lattice indices so shared rows match exactly."""
    import trimesh
    from skimage.measure import marching_cubes

    res = float(xs[1] - xs[0])
    origin = np.array([xs[0], ys[0], zs[0]], dtype=np.float64)
    verts, faces, nv = [], [], 0
    ny = len(ys)
    j0 = 0
    while j0 < ny - 1:
        j1 = min(ny, j0 + slab + 1)
        F = field(j0, j1)
        if F.min() < level < F.max():
            v, f, _, _ = marching_cubes(F, level=level, allow_degenerate=False)
            idx = np.empty_like(v, dtype=np.float64)
            idx[:, 0] = v[:, 1]            # x index
            idx[:, 1] = v[:, 0] + j0       # y index (global)
            idx[:, 2] = v[:, 2]            # z index
            verts.append(idx * res + origin)
            faces.append(f + nv)
            nv += len(v)
        if progress:
            progress(j1, ny)
        j0 = j1 - 1
    if not verts:
        raise ValueError("field has no surface inside the lattice")
    m = trimesh.Trimesh(np.concatenate(verts), np.concatenate(faces), process=True)
    m.remove_unreferenced_vertices()
    if m.volume < 0:
        m.invert()
    return m


def decimate(mesh, faces: int):
    """Quadric decimation to about `faces` triangles; returns the mesh as-is
    when it is already under budget."""
    import fast_simplification
    import trimesh

    if len(mesh.faces) <= faces:
        return mesh
    reduction = 1.0 - faces / len(mesh.faces)
    simplified = fast_simplification.simplify(np.asarray(mesh.vertices, dtype=np.float64),
                                              np.asarray(mesh.faces), target_reduction=reduction)
    out = trimesh.Trimesh(simplified[0], simplified[1], process=True)
    if out.volume < 0:
        out.invert()
    return out


def drop_specks(mesh, min_faces: int = 50):
    """Remove pieces under `min_faces` triangles. Decimation can leave
    zero-volume two-triangle flaps that a slicer reports as loose parts."""
    import trimesh

    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh
    keep = [q for q in parts if len(q.faces) >= min_faces]
    return cast("trimesh.Trimesh", trimesh.util.concatenate(keep)) if keep else mesh


def tidy(mesh, tol: float = 2e-3):
    """Make the in-memory mesh match what a slicer will load.

    Vertices closer than `tol` mm are welded (a sliver triangle collapses
    instead of leaving a pin-hole when it is removed), faces that lost a
    corner to the weld and face pairs that use the same three vertices
    (zero-volume flaps) are deleted, loose specks are dropped, and the
    result snaps to a 0.1 um grid, coarser than float32 spacing at 200 mm,
    so an STL round trip keeps the same topology. Run it last, after any
    transform."""
    import trimesh
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import KDTree

    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces)
    pairs = KDTree(v).query_pairs(r=tol, output_type="ndarray")
    if len(pairs):
        n = len(v)
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, labels = connected_components(g, directed=False)
        rep = np.full(labels.max() + 1, n)
        np.minimum.at(rep, labels, np.arange(n))
        f = rep[labels][f]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    key = np.sort(f, axis=1)
    _, inverse, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    f = f[counts[inverse.ravel()] == 1]
    m = trimesh.Trimesh(np.round(v, 4), f, process=True)
    m.remove_unreferenced_vertices()
    return drop_specks(m)


def ensure_closed(mesh):
    """Tidy the mesh, then repair with MeshFix if a hole or a bad edge is
    left."""
    import trimesh

    mesh = tidy(mesh)
    if mesh.is_watertight and mesh.is_winding_consistent:
        return mesh
    import pymeshfix

    mf = pymeshfix.MeshFix(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    mf.repair()
    out = tidy(trimesh.Trimesh(mf.points, mf.faces, process=True))
    if out.volume < 0:
        out.invert()
    return out
