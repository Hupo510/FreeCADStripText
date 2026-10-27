# -*- coding: utf-8 -*-
"""resweep.py -- 回归自检: 把"找文字"的那套检测器**再跑一遍在成品上**。

成品如果还残留同一类贴花(内环 / 窄壁上的贴片实体 / 平铺薄板), 检测器必然又能
找出来 —— 这正是 WIFIM-SMD_ESP32-C3-MINI-1 那个云朵 logo 的漏洞被发现的方式:
它当年没被检出, 但用修好的检测器回头扫成品, 它立刻现形。

判据: 成品上检出候选数 == 0。非 0 就说明还有残留。
"""
import glob
import os
import sys

W = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, W)
import Part

import strip_text as S

bad = 0
for p in sorted(glob.glob(os.path.join(W, "out", "*_noText.step"))):
    base = os.path.basename(p)[:-len("_noText.step")]
    sh = Part.Shape()
    sh.read(p)
    jobs = []
    try:
        jobs += S.detect_floating(sh.Solids)
    except Exception as e:
        print("%-46s !! floating 异常 %s" % (base[:46], e))
        bad += 1
        continue
    for sd in sh.Solids:
        try:
            jobs += S.detect(sd)
        except Exception as e:
            print("%-46s !! detect 异常 %s" % (base[:46], e))
            bad += 1
            break
    if jobs:
        bad += 1
        print("%-46s !! 残留候选 %d 个" % (base[:46], len(jobs)))
        for j in jobs[:6]:
            r = getattr(j, "region", None)
            print("      %s n=(%.2f,%.2f,%.2f) 区域=%s" %
                  (getattr(j, "kind", "?"), j.n.x, j.n.y, j.n.z,
                   "None" if r is None else "[%.3f..%.3f, %.3f..%.3f, %.3f..%.3f]" % tuple(r)))
    else:
        print("%-46s OK  (solids=%d faces=%d)" % (base[:46], len(sh.Solids), len(sh.Faces)))
print("\n成品残留扫描: %d 个有问题" % bad)
