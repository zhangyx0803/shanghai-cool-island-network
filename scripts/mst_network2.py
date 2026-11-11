# -*- coding: utf-8 -*-
"""Minimum-cost network (self-tracing version): cost-distance matrix + Prim MST + paths traced manually with the backlink array"""
import csv
import os
import sys
import time

import arcpy
import numpy as np
from arcpy.sa import *

arcpy.CheckOutExtension("Spatial")
arcpy.env.overwriteOutput = True
t0 = time.time()

TMP = r"data/external"
TAB = r"outputs/tables"
GDB = r"data/analysis.gdb"
FACTOR = int(sys.argv[2]) if len(sys.argv) > 2 else 10
CELL_M = 30 * FACTOR
MIN_KM2 = 1.0
# CostBackLink codes: 1 right, 2 lower-right, 3 down, 4 lower-left, 5 left, 6 upper-left, 7 up, 8 upper-right
DIRS = {1: (0, 1), 2: (1, 1), 3: (1, 0), 4: (1, -1), 5: (0, -1), 6: (-1, -1), 7: (-1, 0), 8: (-1, 1)}


def log(m):
    print("[%6.1fs] %s" % (time.time() - t0, m), flush=True)


def main(year):
    cost_p = os.path.join(TMP, "cost%d_%s.tif" % (CELL_M, year))
    if not os.path.exists(cost_p):
        Aggregate(Raster(os.path.join(TMP, "R_joint_%s.tif" % year)) + 1, FACTOR, "MEAN").save(cost_p)
    d = arcpy.Describe(cost_p)
    log("%s: cost surface %.0f m, %d x %d" % (year, CELL_M, d.width, d.height))
    X0, YMAX = d.extent.XMin, d.extent.YMax

    rows = [r for r in csv.DictReader(open(os.path.join(TAB, "复合斑块_双值与分区_v2.csv"),
                                            encoding="utf-8-sig"))
            if r["年份"] == year and float(r["面积km2"]) >= MIN_KM2]
    xs = np.array([float(r["X"]) for r in rows])
    ys = np.array([float(r["Y"]) for r in rows])
    n = len(rows)
    rc = [((int((YMAX - y) / CELL_M)), int((x - X0) / CELL_M)) for x, y in zip(xs, ys)]
    log("%d nodes" % n)

    sr = d.spatialReference
    cost = Raster(cost_p)
    CD, CB = {}, {}
    for i in range(n):
        p = arcpy.PointGeometry(arcpy.Point(xs[i], ys[i]), sr)
        cd = CostDistance(p, cost)
        cb = CostBackLink(p, cost)
        CD[i] = arcpy.RasterToNumPyArray(cd, nodata_to_value=np.nan)
        CB[i] = arcpy.RasterToNumPyArray(cb, nodata_to_value=0).astype(np.int16)
        if (i + 1) % 25 == 0:
            log("  cost distance %d/%d" % (i + 1, n))

    M = np.full((n, n), np.inf)
    for i in range(n):
        arr = CD[i]
        for j in range(n):
            r, c = rc[j]
            if 0 <= r < arr.shape[0] and 0 <= c < arr.shape[1]:
                v = float(arr[r, c])
                if np.isfinite(v):
                    M[i, j] = v
    log("distance matrix completed")

    in_tree = [0]
    best = M[0].copy()
    best_from = np.zeros(n, int)
    best[0] = np.inf
    edges = []
    while len(in_tree) < n:
        cand = best.copy()
        cand[np.isin(np.arange(n), in_tree)] = np.inf
        k = int(np.argmin(cand))
        if not np.isfinite(cand[k]):
            break
        edges.append((int(best_from[k]), k, float(cand[k])))
        in_tree.append(k)
        for j in range(n):
            if j not in in_tree and M[k, j] < best[j]:
                best[j] = M[k, j]
                best_from[j] = k
    log("MST: %d edges" % len(edges))

    out_fc = os.path.join(GDB, "Corridor_joint_%s" % year)
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)
    arcpy.management.CreateFeatureclass(os.path.dirname(out_fc), os.path.basename(out_fc),
                                        "POLYLINE", spatial_reference=sr)
    arcpy.management.AddField(out_fc, "PATHID", "LONG")
    arcpy.management.AddField(out_fc, "PATHCOST", "DOUBLE")
    arcpy.management.AddField(out_fc, "R1", "LONG")
    arcpy.management.AddField(out_fc, "R2", "LONG")

    ok = 0
    with arcpy.da.InsertCursor(out_fc, ["SHAPE@", "PATHID", "PATHCOST", "R1", "R2"]) as ic:
        for (i, j, c) in edges:
            cb = CB[i]
            r, cc = rc[j]
            pts = []
            for _ in range(20000):
                if not (0 <= r < cb.shape[0] and 0 <= cc < cb.shape[1]):
                    break
                pts.append(arcpy.Point(X0 + cc * CELL_M + CELL_M / 2, YMAX - r * CELL_M - CELL_M / 2))
                code = int(cb[r, cc])
                if code == 0:
                    break
                dr, dc = DIRS.get(code, (0, 0))
                if dr == 0 and dc == 0:
                    break
                r, cc = r + dr, cc + dc
            if len(pts) >= 2:
                ic.insertRow([arcpy.Polyline(arcpy.Array(pts), sr), i * 1000 + j, c, i, j])
                ok += 1
    log("generated %d/%d paths" % (ok, len(edges)))

    cnt = int(arcpy.GetCount_management(out_fc).getOutput(0))
    tot = 0.0
    with arcpy.da.SearchCursor(out_fc, ["SHAPE@LENGTH"]) as cur:
        for (l,) in cur:
            tot += (l or 0)
    log("%s: %d corridors | total %.1f km | mean %.1f km" % (year, cnt, tot / 1000, tot / 1000 / max(cnt, 1)))
    return out_fc


if __name__ == "__main__":
    main(sys.argv[1])
