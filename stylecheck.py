# -*- coding: utf-8 -*-
"""stylecheck.py -- 校验成品 STEP 的颜色表结构是否与原始文件同构
(纯文本解析, 不需要 FreeCAD)

查三件事:
  1. 各样式实体数量对比(源 vs 成品)
  2. 每条 OVER_RIDING_STYLED_ITEM 的 over_ride 必须是**单个** #id, 不能是 (#id)
     —— 写成集合时严格的解析器会整条忽略, 面全退回基础色(看起来"单色/发暗")
  3. over_ride 指向的实体必须真的是一条 STYLED_ITEM, 且是本实体那条
"""
import os
import re
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stepcolor import split_entities, etype, split_args, ids_in

W = os.path.dirname(os.path.abspath(__file__))
D = r"C:/Users/lhm/Downloads"
TYPES = ["COLOUR_RGB", "FILL_AREA_STYLE_COLOUR", "FILL_AREA_STYLE",
         "SURFACE_STYLE_FILL_AREA", "SURFACE_SIDE_STYLE", "SURFACE_STYLE_USAGE",
         "PRESENTATION_STYLE_ASSIGNMENT", "STYLED_ITEM", "OVER_RIDING_STYLED_ITEM",
         "MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"]


def counts(path):
    txt = open(path, "r", encoding="utf-8", errors="ignore").read()
    ents = split_entities(txt)
    c = {t: 0 for t in TYPES}
    bad = []
    for i in sorted(ents):
        t = etype(ents[i])
        if t == "STYLED_ITEM":
            c[t] += 1
        elif t in c:
            c[t] += 1
        if t != "OVER_RIDING_STYLED_ITEM":
            continue
        a = split_args(ents[i])
        if len(a) < 4:
            bad.append("#%d 参数不足: %s" % (i, ents[i][:70]))
            continue
        over = a[3].strip()
        if over.startswith("(") or " " in over:
            bad.append("#%d over_ride 写成了集合: %s" % (i, over))
            continue
        ids = ids_in(over)
        if len(ids) != 1:
            bad.append("#%d over_ride 不是单个引用: %s" % (i, over))
            continue
        if etype(ents.get(ids[0], "")) != "STYLED_ITEM":
            bad.append("#%d over_ride 指向的不是 STYLED_ITEM: #%d=%s"
                       % (i, ids[0], etype(ents.get(ids[0], ""))))
        if not ids_in(a[2]):
            bad.append("#%d 缺少 item 面引用" % i)
    return c, bad, len(ents)


rows = []
for p in sorted(glob.glob(os.path.join(W, "out", "*_noText.step"))):
    base = os.path.basename(p)[:-len("_noText.step")]
    src = os.path.join(D, base + ".step")
    if not os.path.exists(src):
        continue
    c1, b1, n1 = counts(src)
    c2, b2, n2 = counts(p)
    rows.append((base, c1, c2, b2))

print("%-44s %s" % ("模型", "COLOUR / FASC / FAS / SSFA / SSS / SSU / PSA / STY / OVR / MEC"))
bad_n = 0
for base, c1, c2, b2 in rows:
    f = lambda c: "/".join(str(c[t]) for t in TYPES)
    print("%-44s\n   源: %s\n   新: %s" % (base[:44], f(c1), f(c2)))
    if b2:
        bad_n += 1
        for m in b2[:3]:
            print("   !! %s" % m)
print("\n结构有问题的成品: %d / %d" % (bad_n, len(rows)))
