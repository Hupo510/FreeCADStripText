# -*- coding: utf-8 -*-
"""verify_all.py -- 成品结构校验: 回读是否 valid/closed、颜色链是否完整、产品名是否正确
用法: freecadcmd.exe verify_all.py
"""
import sys, os, re, glob
import Part

W = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(W, "out")
SRC = r"C:/Users/lhm/Downloads"


def product_name(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    m = re.search(r"PRODUCT\s*\(\s*'((?:[^']|'')*)'", txt)
    return m.group(1).replace("''", "'").strip() if m else "?"


rows, bad = [], 0
for p in sorted(glob.glob(os.path.join(OUT, "*_noText.step"))):
    base = os.path.basename(p)[:-len("_noText.step")]
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    ns = len(re.findall(r"OVER_RIDING_STYLED_ITEM", txt))
    nsty = len(re.findall(r"STYLED_ITEM", txt))
    ncol = len(re.findall(r"COLOUR_RGB", txt))
    nmec = len(re.findall(r"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION", txt))
    try:
        sh = Part.Shape()
        sh.read(p)
        ok = sh.isValid() and sh.isClosed()
        det = "solids=%d faces=%d" % (len(sh.Solids), len(sh.Faces))
    except Exception as e:
        ok, det = False, "读取失败:%s" % e
    if not ok:
        bad += 1
    rows.append((base, ok, det, ns, nsty, ncol, nmec, product_name(p)))

print("%-46s %-4s %-22s %6s %6s %5s %5s" %
      ("模型", "有效", "拓扑", "覆盖色", "样式", "颜色", "MEC"))
for r in rows:
    print("%-46s %-4s %-22s %6d %6d %5d %5d" % (r[0][:46], "OK" if r[1] else "FAIL", r[2], r[3], r[4], r[5], r[6]))
print("\n共 %d 个成品, 失效 %d 个" % (len(rows), bad))
print("\n产品名抽查(前 5 个):")
for r in rows[:5]:
    print("  %-40s -> %s" % (r[0][:40], r[7]))
# 名字是否退化成 translator 默认名
badname = [r[0] for r in rows if "translator" in r[7].lower()]
print("\n退化为默认名的: %s" % ("无" if not badname else badname))
