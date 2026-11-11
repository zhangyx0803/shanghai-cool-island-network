# -*- coding: utf-8 -*-
"""Supplement: identify corridor bottlenecks using P95 and absolute thresholds, and output the highest-resistance segments"""
import csv
import os

import arcpy
import numpy as np

arcpy.CheckOutExtension("Spatial")
F = r"data/intermediate"
TAB = r"outputs/tables"
GDB = r"data/analysis.gdb"
REF = os.path.join(F, "RefGrid_30m.tif")
ref = arcpy.Raster(REF)
X0, YMAX = ref.extent.XMin, ref.extent.YMax
NR, NC, CELL = 4376, 4004, 30.0
YEARS = ["2015", "2020", "2025"]

rows = []
for y in YEARS:
    rj = arcpy.RasterToNumPyArray(os.path.join(F, "R_joint_%s.tif" % y), nodata_to_value=np.nan)
    p95 = float(np.nanpercentile(rj, 95))
    fc = os.path.join(GDB, "Corridor_joint_%s" % y)
    with arcpy.da.SearchCursor(fc, ["PATHID", "SHAPE@"]) as cur:
        for pid, shp in cur:
            pts = [(p.X, p.Y) for part in shp for p in part]
            v = []
            for x, py in pts:
                c = int((x - X0) / CELL)
                r = int((YMAX - py) / CELL)
                if 0 <= r < NR and 0 <= c < NC:
                    val = rj[r, c]
                    if np.isfinite(val):
                        v.append(val)
            if not v:
                continue
            v = np.array(v)
            rows.append(dict(年份=y, PATHID=int(pid), 长度km=round((shp.length or 0) / 1000, 3),
                             最大阻力=round(float(v.max()), 1),
                             平均阻力=round(float(v.mean()), 1),
                             P95阈值=round(p95, 1),
                             超P95占比=round(float((v > p95).mean()) * 100, 2),
                             超600占比=round(float((v > 600).mean()) * 100, 2)))

p = os.path.join(TAB, "廊道瓶颈.csv")
with open(p, "w", encoding="utf-8-sig") as f:
    cols = list(rows[0].keys())
    f.write(",".join(cols) + "\n")
    for r in rows:
        f.write(",".join(str(r[c]) for c in cols) + "\n")
print("Wrote:", p)

print()
print("%-6s %6s %8s %8s %8s %10s %10s" % ("Year", "Corr", "MeanRes", "MeanMax", "Max", "PctP95", "Pct600"))
for y in YEARS:
    sub = [r for r in rows if r["年份"] == y]
    print("%-6s %6d %8.1f %10.1f %10.0f %9.2f%% %9.2f%%"
          % (y, len(sub),
             np.mean([r["平均阻力"] for r in sub]),
             np.mean([r["最大阻力"] for r in sub]),
             max(r["最大阻力"] for r in sub),
             np.mean([r["超P95占比"] for r in sub]),
             np.mean([r["超600占比"] for r in sub])))

print()
print("Top 5 corridors by maximum resistance in each period (bottleneck first)")
for y in YEARS:
    sub = sorted([r for r in rows if r["年份"] == y], key=lambda x: -x["最大阻力"])[:5]
    print("  %s:" % y)
    for r in sub:
        print("    PATHID=%-7d len %6.2f km | max res %6.1f | mean %6.1f | pct>600 %5.2f%%"
              % (r["PATHID"], r["长度km"], r["最大阻力"], r["平均阻力"], r["超600占比"]))
