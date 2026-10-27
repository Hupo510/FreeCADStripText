# -*- coding: utf-8 -*-
"""colorstat.py -- 逐模型对比"源文件 / 成品"的配色: 颜色档数、各档面数、是否有新造颜色。
用法: python colorstat.py        (纯文本处理, 不需要 FreeCAD)
"""
import os
import re
import glob
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stepcolor import face_colors

W = os.path.dirname(os.path.abspath(__file__))
D = r"C:/Users/lhm/Downloads"


def stat(path):
    order, seq, _ = face_colors(path)
    n = len(order)
    cnt = {}
    for c in seq:
        if not c:
            continue
        k = tuple(round(v, 3) for v in c)
        cnt[k] = cnt.get(k, 0) + 1
    return n, cnt


def fmt(cnt, top=4):
    it = sorted(cnt.items(), key=lambda kv: -kv[1])[:top]
    return "  ".join("%s×%d" % ("(%.2f,%.2f,%.2f)" % k, v) for k, v in it)


rows = []
for p in sorted(glob.glob(os.path.join(W, "out", "*_noText.step"))):
    base = os.path.basename(p)[:-len("_noText.step")]
    src = os.path.join(D, base + ".step")
    if not os.path.exists(src):
        continue
    n1, c1 = stat(src)
    n2, c2 = stat(p)
    lost = [k for k in c1 if k not in c2]
    new = [k for k in c2 if k not in c1]
    rows.append((base, n1, len(c1), n2, len(c2), lost, new))

print("%-46s %5s %4s %5s %4s  %s" % ("模型", "面", "档", "面", "档", "结论"))
bad = 0
for base, n1, k1, n2, k2, lost, new in rows:
    note = "OK"
    if lost or new or k2 < k1:
        bad += 1
        bits = []
        if lost:
            bits.append("丢%d档:" % len(lost) + " ".join("(%.2f,%.2f,%.2f)" % k for k in lost))
        if new:
            bits.append("新造%d档:" % len(new) + " ".join("(%.2f,%.2f,%.2f)" % k for k in new))
        note = "; ".join(bits)
    print("%-46s %5d %4d %5d %4d  %s" % (base[:46], n1, k1, n2, k2, note))
print("\n共 %d 个, 配色有问题 %d 个" % (len(rows), bad))

print("\n--- 明细(前 3 个有问题的) ---")
c = 0
for base, n1, k1, n2, k2, lost, new in rows:
    if not (lost or new or k2 < k1):
        continue
    _, c1 = stat(os.path.join(D, base + ".step"))
    _, c2 = stat(os.path.join(W, "out", base + "_noText.step"))
    print("\n%s\n  源: %s\n  成品: %s" % (base, fmt(c1), fmt(c2)))
    c += 1
    if c >= 3:
        break
