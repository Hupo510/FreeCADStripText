# -*- coding: utf-8 -*-
"""colorarea.py -- 按**面积**对比配色(面数会被贴花自身那几百个细小侧面带偏)。
真正决定"看上去什么颜色"的是每一档颜色覆盖的面积。
用法: freecadcmd.exe colorarea.py
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Part
from stepcolor import face_colors

W = os.path.dirname(os.path.abspath(__file__))
D = r"C:/Users/lhm/Downloads"


def area_by_colour(path):
    sh = Part.Shape()
    sh.read(path)
    order, seq, _ = face_colors(path)
    tot = {}
    grand = 0.0
    for i, f in enumerate(sh.Faces):
        c = seq[i] if i < len(seq) else None
        k = tuple(round(v, 2) for v in c[:3]) if c else None
        a = f.Area
        tot[k] = tot.get(k, 0.0) + a
        grand += a
    return tot, grand


print("%-46s %-34s %-34s" % ("模型", "源(颜色:面积占比)", "成品"))
bad = []
for p in sorted(glob.glob(os.path.join(W, "out", "*_noText.step"))):
    base = os.path.basename(p)[:-len("_noText.step")]
    src = os.path.join(D, base + ".step")
    if not os.path.exists(src):
        continue
    try:
        s1, g1 = area_by_colour(src)
        s2, g2 = area_by_colour(p)
    except Exception as e:
        print("%-46s !! %s" % (base[:46], e))
        continue

    def fmt(d, g):
        it = sorted(d.items(), key=lambda kv: -kv[1])[:3]
        return " ".join("%s:%.0f%%(%.2f)" % ("无" if k is None else "%.2f/%.2f/%.2f" % k,
                                             100.0 * v / g if g else 0, v) for k, v in it)

    # 每档颜色在成品里的面积占比 vs 源
    issues = []
    for k, a1 in s1.items():
        a2 = s2.get(k, 0.0)
        r1 = a1 / g1 if g1 else 0
        r2 = a2 / g2 if g2 else 0
        if r1 >= 0.02 and r2 < 0.5 * r1:
            issues.append("%s %.0f%%->%.0f%%" % ("无" if k is None else "%.2f/%.2f/%.2f" % k,
                                                 100 * r1, 100 * r2))
    if issues:
        bad.append((base, issues))
    print("%-46s %-34s %-34s %s" % (base[:46], fmt(s1, g1), fmt(s2, g2),
                                    "OK" if not issues else "!! " + "; ".join(issues)))
print("\n配色明显丢档的模型 %d 个" % len(bad))
