# -*- coding: utf-8 -*-
"""rcmp.py -- 源文件 / 成品 的同视角、同缩放 配色对照渲染。
用法: freecadcmd.exe rcmp.py [模型名 ...]      (不给名字就渲染 JOBS 全部)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Part
from r3d import AXES
from rcol import render

W = os.path.dirname(os.path.abspath(__file__))
D = r"C:/Users/lhm/Downloads"
OUT = os.path.join(W, "render")
os.makedirs(OUT, exist_ok=True)

# (标签, 文件主干, 视图列表, zoom 或 None)
JOBS = [
    ("hdr", "HDR-TH_10P-P2.54-V-F-R2-C5-S2.54", ["top", "bot", "posY"], None),
    ("opto", "OPTO-SMD-4_L4.4-W4.1-P2.54-LS7.0-TL", ["top", "bot", "negY"], None),
    ("sod882", "SOD-882_L1.0-W0.6-BI", ["top", "bot"], None),
    ("wifim", "WIFIM-SMD_61P-L13.2-W12.5-P0.80", ["top", "bot"], None),
    ("bul", "BULETM-SMD_22P-P2.00_ESP8685-WROOM-01-XX", ["top", "bot"], None),
    ("sim", "SIM-SMD_L17.2-W15.4-H1.4", ["top", "bot"], None),
    ("tdfn", "TDFN-8_L3.0-W2.0-P0.50-BL-EP", ["top", "bot"], None),
    ("connsmd", "CONN-SMD_HC-1.25-2PLT", ["top", "bot"], None),
]

want = [x for x in sys.argv[1:] if not x.lower().endswith((".step", ".stp"))]
for tag, base, views, zoom in JOBS:
    if want and tag not in want:
        continue
    src = os.path.join(D, base + ".step")
    dst = os.path.join(W, "out", base + "_noText.step")
    if not (os.path.exists(src) and os.path.exists(dst)):
        print("skip", tag)
        continue
    # zoom 用源文件的包围盒算一次, 两边共用, 保证像素一一对应
    s0 = Part.Shape(); s0.read(src)
    for v in views:
        ax, ay, az, sx, sy, sz = AXES[v]
        bb = s0.BoundBox
        L = [bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax]
        u0, u1 = L[2 * ax] * sx, L[2 * ax + 1] * sx
        v0, v1 = L[2 * ay] * sy, L[2 * ay + 1] * sy
        if u0 > u1:
            u0, u1 = u1, u0
        if v0 > v1:
            v0, v1 = v1, v0
        pad = 0.06 * max(u1 - u0, v1 - v0)
        z = (u0 - pad, u1 + pad, v0 - pad, v1 + pad)
        for pre, p in (("src", src), ("dst", dst)):
            try:
                import stepcolor  # noqa
                from rcol import shape_colors
                sh, cols = shape_colors(p)
                render(sh, cols, v, os.path.join(OUT, "%s_%s_%s.png" % (tag, v, pre)),
                       W=900, H=720, zoom=z)
                print("  %s %s %s" % (tag, v, pre))
            except Exception as e:
                print("  !! %s %s %s: %s" % (tag, v, pre, e))
