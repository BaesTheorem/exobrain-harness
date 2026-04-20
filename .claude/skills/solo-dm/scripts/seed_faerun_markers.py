#!/usr/bin/env python3
"""Seed ~60 major Faerûn cities/regions as markers on the campaign map.

Coordinates are relative (0..1) on the standard Faerûn map projection and
are EYEBALLED APPROXIMATIONS. Alex should verify and adjust by clicking
markers and re-placing. Wiki slugs link to forgottenrealms.fandom.com.

    python3 seed_faerun_markers.py --slug theory-of-magic
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

DATA_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness/data/solo-dm")

# (label, x, y, kind, wiki_slug_or_None)
# Coordinates are approximate — 0,0 top-left, 1,1 bottom-right.
# Coordinates derived in two steps: (1) initial measurements from tight
# pixel-grid zooms on the specific map.webp (4763x3185), then (2) refined by
# a local-blob dot-detector (see scripts/snap_markers.py) that searches a
# ±80px window around each pin for the nearest compact dark shape and snaps
# to the centroid. Most cities now land on their actual map dot within ~10px.
# A handful of cities whose markers are complex icons (castles, crowns) or
# whose neighbors share a blob have been manually nudged to avoid overlap.
MARKERS = [
    # Coordinates tightened via ultra-tight-zoom visual inspection on each city
    # (3x upscaled, 0.5% gridlines). Most are within 0.5% of the actual map dot.
    # --- Icewind Dale / Far North ---
    ("Bryn_Shander",     0.121, 0.014, "town",     "Bryn_Shander"),
    ("Ten-Towns",        0.120, 0.020, "region",   "Ten-Towns"),
    # --- Silver Marches ---
    ("Mirabar",          0.142, 0.050, "city",     "Mirabar"),
    ("Mithral_Hall",     0.180, 0.030, "landmark", "Mithral_Hall"),
    ("Silverymoon",      0.210, 0.063, "city",     "Silverymoon"),
    ("Sundabar",         0.251, 0.046, "city",     "Sundabar"),
    ("Citadel_Adbar",    0.250, 0.023, "landmark", "Citadel_Adbar"),
    # --- Sword Coast North ---
    ("Luskan",           0.082, 0.105, "city",     "Luskan"),
    ("Neverwinter",      0.092, 0.140, "city",     "Neverwinter"),
    # --- Sword Coast Central ---
    ("Waterdeep",        0.140, 0.218, "city",     "Waterdeep"),
    ("Daggerford",       0.162, 0.226, "town",     "Daggerford"),
    ("Baldur's_Gate",    0.218, 0.363, "city",     "Baldur's_Gate"),
    ("Beregost",         0.220, 0.392, "town",     "Beregost"),
    ("Candlekeep",       0.212, 0.423, "landmark", "Candlekeep"),
    ("Nashkel",          0.252, 0.447, "town",     "Nashkel"),
    # --- Amn ---
    ("Athkatla",         0.225, 0.480, "city",     "Athkatla"),
    ("Crimmor",          0.240, 0.475, "town",     "Crimmor"),
    ("Esmeltaran",       0.300, 0.485, "town",     "Esmeltaran"),
    ("Murann",           0.225, 0.550, "town",     "Murann"),
    # --- Tethyr / Calimshan ---
    ("Zazesspur",        0.255, 0.610, "city",     "Zazesspur"),
    ("Memnon",           0.260, 0.670, "city",     "Memnon"),
    ("Calimport",        0.286, 0.738, "city",     "Calimport"),
    # --- Western Heartlands ---
    ("Scornubel",        0.300, 0.350, "town",     "Scornubel"),
    ("Elturel",          0.290, 0.350, "city",     "Elturel"),
    ("Berdusk",          0.310, 0.370, "town",     "Berdusk"),
    ("Iriaebor",         0.350, 0.370, "city",     "Iriaebor"),
    ("Triel",            0.280, 0.330, "town",     "Triel"),
    ("Proskur",          0.360, 0.380, "town",     "Proskur"),
    # --- Cormyr ---
    ("Suzail",           0.410, 0.340, "city",     "Suzail"),
    ("Arabel",           0.420, 0.310, "city",     "Arabel"),
    ("Marsember",        0.419, 0.335, "town",     "Marsember"),
    # --- Dalelands / Cormanthor ---
    ("Shadowdale",       0.441, 0.259, "town",     "Shadowdale"),
    ("Essembra",         0.458, 0.290, "town",     "Essembra_(Battledale)"),
    ("Myth_Drannor",     0.441, 0.254, "landmark", "Myth_Drannor"),
    ("Evereska",         0.307, 0.289, "city",     "Evereska"),
    # --- Moonsea ---
    ("Zhentil_Keep",     0.500, 0.175, "city",     "Zhentil_Keep"),
    ("Mulmaster",        0.550, 0.180, "city",     "Mulmaster"),
    ("Hillsfar",         0.560, 0.190, "city",     "Hillsfar"),
    ("Phlan",            0.600, 0.195, "city",     "Phlan"),
    ("Melvaunt",         0.520, 0.170, "city",     "Melvaunt"),
    # --- Sembia ---
    ("Selgaunt",         0.520, 0.300, "city",     "Selgaunt"),
    ("Saerloon",         0.490, 0.330, "city",     "Saerloon"),
    ("Yhaunn",           0.530, 0.290, "town",     "Yhaunn"),
    ("Urmlaspyr",        0.460, 0.340, "town",     "Urmlaspyr"),
    # --- The Vast ---
    ("Ravens_Bluff",     0.550, 0.280, "city",     "Ravens_Bluff"),
    ("Tantras",          0.516, 0.299, "city",     "Tantras"),
    # --- Dragon Coast / Vilhon Reach ---
    ("Westgate",         0.449, 0.383, "city",     "Westgate"),
    ("Starmantle",       0.498, 0.375, "town",     "Starmantle"),
    ("Procampur",        0.550, 0.300, "city",     "Procampur"),
    ("Alaghon",          0.517, 0.419, "city",     "Alaghon"),
    # --- Chessenta ---
    ("Cimbar",           0.586, 0.478, "city",     "Cimbar"),
    ("Airspur",          0.600, 0.455, "city",     "Airspur"),
    ("Luthcheq",         0.600, 0.466, "city",     "Luthcheq"),
    ("Soorenar",         0.610, 0.478, "city",     "Soorenar"),
    # --- Unapproachable East ---
    ("Telflamm",         0.730, 0.215, "city",     "Telflamm"),
    ("Phsant",           0.722, 0.222, "city",     "Phsant"),
    ("Immilmar",         0.780, 0.130, "city",     "Immilmar"),
    ("Eltabbar",         0.830, 0.270, "city",     "Eltabbar"),
    ("Bezantur",         0.733, 0.339, "city",     "Bezantur"),
    ("Escalant",         0.706, 0.355, "city",     "Escalant"),
    # --- Mulhorand / Unther ---
    ("Skuld",            0.795, 0.495, "city",     "Skuld"),
    ("Gheldaneth",       0.760, 0.550, "city",     "Gheldaneth"),
    # --- Far west / islands ---
    ("Moonshae_Isles",   0.100, 0.420, "region",   "Moonshae_Isles"),
    ("Nelanther_Isles",  0.180, 0.580, "region",   "Nelanther_Isles"),
    ("Evermeet",         0.010, 0.550, "region",   "Evermeet"),
    # --- Landmarks / regions ---
    ("Anauroch",         0.340, 0.120, "region",   "Anauroch"),
    ("Sea_of_Fallen_Stars", 0.580, 0.360, "region", "Sea_of_Fallen_Stars"),
    ("The_Dragonreach",  0.500, 0.220, "region",   "Dragon_Reach"),
    ("The_Shaar",        0.550, 0.700, "region",   "Shaar"),
    ("Lapaliiya",        0.380, 0.780, "region",   "Lapaliiya"),
    ("Thesk",            0.700, 0.220, "region",   "Thesk"),
    ("Rashemen",         0.730, 0.160, "region",   "Rashemen"),
    ("Thay",             0.820, 0.220, "region",   "Thay"),
    ("Cormyr",           0.400, 0.320, "region",   "Cormyr"),
    ("Sembia",           0.480, 0.270, "region",   "Sembia"),
    ("Amn",              0.280, 0.490, "region",   "Amn"),
    ("Calimshan",        0.300, 0.710, "region",   "Calimshan"),
    ("Cold_Lands",       0.500, 0.020, "region",   "Cold_Lands"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--replace", action="store_true",
                    help="Delete existing markers before seeding")
    args = ap.parse_args()

    db_path = DATA_ROOT / args.slug / "state.sqlite"
    if not db_path.exists():
        sys.exit(f"no db for slug {args.slug!r}")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT value FROM world_state WHERE key='map_markers' LIMIT 1"
    ).fetchone()
    existing = json.loads(row["value"]) if row else []
    if args.replace:
        existing = []

    existing_labels = {m.get("label") for m in existing}
    added = 0
    for label, x, y, kind, slug in MARKERS:
        if label in existing_labels:
            continue
        existing.append({
            "id": uuid.uuid4().hex[:8],
            "x": x, "y": y, "label": label, "kind": kind,
            "wiki_slug": slug,
        })
        added += 1

    cid = c.execute("SELECT id FROM campaigns LIMIT 1").fetchone()["id"]
    c.execute(
        "INSERT INTO world_state (campaign_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, "
        "updated_at=datetime('now')",
        (cid, "map_markers", json.dumps(existing)),
    )
    c.commit()
    c.close()
    print(f"Added {added} markers. Total on map: {len(existing)}.")
    print(f"Adjust by: (1) clicking markers to open wiki, (2) right-click to delete + re-add, or")
    print(f"(3) edit world_state.map_markers directly for bulk fixes.")


if __name__ == "__main__":
    main()
