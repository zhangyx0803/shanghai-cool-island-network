# -*- coding: utf-8 -*-
"""Corridor-level evaluation: (1) dual-value sampling along each corridor (2) high-resistance segments/bottlenecks (3) cross-period stability"""
import csv
import os
import time

import arcpy
import numpy as np

arcpy.CheckOutExtension("Spatial")
arcpy.env.overwriteOutput = True
t0 = time.time()

F = r"data/intermediate"
TAB = r"outputs/tables"
GDB = r"data/analysis.gdb"
TMP = r"data/external"
REF = os.path.join(F, "RefGrid_30m.tif")
ref = arcpy.Raster(REF)
X0, Y0 = ref.extent.XMin, ref.extent.YMin
YMAX = ref.extent.YMax
NR, NC, CELL = 4376, 4004, 30.0
YEARS = ["2015", "2020", "2025"]


def log(m):
    print("[%5.1fs] %s" % (time.time() - t0, m), flush=True)


def read(p, nd=np.nan):
    return arcpy.RasterToNumPyArray(p, nodata_to_value=nd)


rows_out = []
for y in YEARS:
    lst = read(os.path.join(F, "LST_%s_v1.tif" % y))
    wet = read(os.path.join(F, "Wetland_%s.tif" % y), 0) == 1
    vnl = read(os.path.join(F, "VNL_%s_30m.tif" % y))
    vnl = np.where(np.isfinite(vnl), vnl, 0)
    rj = read(os.path.join(F, "R_joint_%s.tif" % y))
    city_lst = float(np.nanmean(lst))
    p75 = float(np.nanpercentile(rj, 75))

    fc = os.path.join(GDB, "Corridor_joint_%s" % y)
    n = 0
    with arcpy.da.SearchCursor(fc, ["PATHID", "PATHCOST", "SHAPE@"]) as cur:
        for pid, pcost, shp in cur:
            pts = [(p.X, p.Y) for part in shp for p in part]
            if len(pts) < 2:
                continue
            rr, cc = [], []
            for x, pt_y in pts:
                c = int((x - X0) / CELL)
                r = int((YMAX - pt_y) / CELL)
                if 0 <= r < NR and 0 <= c < NC:
                    rr.append(r)
                    cc.append(c)
            if not rr:
                continue
            rr = np.array(rr)
            cc = np.array(cc)
            l = np.asarray(lst[rr, cc], float)
            w = wet[rr, cc]
            v = vnl[rr, cc]
            j = rj[rr, cc]
            hres = j > p75
            rows_out.append(dict(
                年份=y, PATHID=int(pid), 长度km=round((shp.length or 0) / 1000, 3),
                平均阻力=round(float(np.nanmean(j)), 1),
                高阻力长度占比=round(float(hres.mean()) * 100, 1),
                LST均值=round(float(np.nanmean(l)), 2),
                湿地占比=round(float(w.mean()), 3),
                灯光均值=round(float(np.mean(v)), 2),
                降温强度=round(float(max(0, city_lst - np.nanmean(l))), 2),
                停歇适宜=round(float(w.mean() * (1 - min(np.mean(v) / 20, 1))), 3)))
            n += 1
    log("%s: sampled %d corridors (high-resistance threshold P75 = %.0f)" % (y, n, p75))

p = os.path.join(TAB, "廊道级评价.csv")
with open(p, "w", encoding="utf-8-sig") as f:
    cols = list(rows_out[0].keys())
    f.write(",".join(cols) + "\n")
    for r in rows_out:
        f.write(",".join(str(r[c]) for c in cols) + "\n")
log("Wrote: %s (%d rows)" % (p, len(rows_out)))

print()
print("%-6s %6s %10s %10s %10s %10s %10s %9s" %
      ("Year", "Corr", "MeanRes", "HiResPct", "LST", "WetFrac", "Cooling", "StopSuit"))
for y in YEARS:
    sub = [r for r in rows_out if r["年份"] == y]
    print("%-6s %6d %10.1f %9.1f%% %10.2f %10.3f %10.2f %9.3f"
          % (y, len(sub),
             np.mean([r["平均阻力"] for r in sub]),
             np.mean([r["高阻力长度占比"] for r in sub]),
             np.mean([r["LST均值"] for r in sub]),
             np.mean([r["湿地占比"] for r in sub]),
             np.mean([r["降温强度"] for r in sub]),
             np.mean([r["停歇适宜"] for r in sub])))

# Corridor classification based on absolute criteria
print()
print("Corridor classification (absolute criteria: LST<=35C and wetland>=0.5 and VNL<=5 = dual-excellent)")
for y in YEARS:
    sub = [r for r in rows_out if r["年份"] == y]
    n = len(sub)
    cold = sum(1 for r in sub if r["LST均值"] <= 35)
    hab = sum(1 for r in sub if r["湿地占比"] >= 0.5 and r["灯光均值"] <= 5)
    both = sum(1 for r in sub if r["LST均值"] <= 35 and r["湿地占比"] >= 0.5 and r["灯光均值"] <= 5)
    print("  %s: cold-source pass %d/%d (%.0f%%) | stopover pass %d (%.0f%%) | dual-excellent %d (%.0f%%)"
          % (y, cold, n, cold * 100.0 / n, hab, hab * 100.0 / n, both, both * 100.0 / n))

# ── Cross-period stability: 2015 vs 2025 corridor overlap ──
log("Computing 2015 vs 2025 corridor overlap ...")
for a, b in (("2015", "2025"), ("2015", "2020"), ("2020", "2025")):
    bufa = os.path.join(TMP, "buf_%s.shp" % a)
    if os.path.exists(bufa):
        arcpy.management.Delete(bufa)
    arcpy.analysis.Buffer(os.path.join(GDB, "Corridor_joint_%s" % a), bufa, "300 Meters", "FULL", "ROUND", "NONE")
    inter = os.path.join(TMP, "inter_%s_%s.shp" % (a, b))
    if os.path.exists(inter):
        arcpy.management.Delete(inter)
    arcpy.analysis.Intersect([os.path.join(GDB, "Corridor_joint_%s" % b), bufa], inter, "ONLY_FID")
    la = 0.0
    lb = 0.0
    with arcpy.da.SearchCursor(os.path.join(GDB, "Corridor_joint_%s" % a), ["SHAPE@LENGTH"]) as cur:
        for (l,) in cur:
            la += (l or 0)
    with arcpy.da.SearchCursor(os.path.join(GDB, "Corridor_joint_%s" % b), ["SHAPE@LENGTH"]) as cur:
        for (l,) in cur:
            lb += (l or 0)
    li = 0.0
    with arcpy.da.SearchCursor(inter, ["SHAPE@LENGTH"]) as cur:
        for (l,) in cur:
            li += (l or 0)
    log("%s->%s: overlap %.1f km (share of %s: %.1f%%, share of %s: %.1f%%)"
        % (a, b, li / 1000, a, li / la * 100, b, li / lb * 100))
