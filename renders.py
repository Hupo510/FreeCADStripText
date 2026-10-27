# -*- coding: utf-8 -*-
"""前后对照渲染: 带消隐棱线, 残留的接缝/框线在这个视图下无所遁形。
用法: freecadcmd.exe renders.py"""
import sys, os
sys.path.insert(0, r"C:/Users/lhm/WorkBuddy/2026-10-26-14-54-26")
import Part
from r3d import render

W = r"C:/Users/lhm/WorkBuddy/2026-10-26-14-54-26"
D = r"C:/Users/lhm/Downloads"
OUT = os.path.join(W, "render")
os.makedirs(OUT, exist_ok=True)

# (标签, 原文件, 结果文件, 视图, zoom 或 None)
JOBS = [
    ("sim_bot", "SIM-SMD_L17.2-W15.4-H1.4", "bot", None),
    ("sim_top", "SIM-SMD_L17.2-W15.4-H1.4", "top", None),
    ("connsmd_bot", "CONN-SMD_HC-1.25-2PLT", "bot", None),
    ("tdfn_top", "TDFN-8_L3.0-W2.0-P0.50-BL-EP", "top", (0.20, 1.40, -0.90, -0.35)),
    ("tdfn_bot", "TDFN-8_L3.0-W2.0-P0.50-BL-EP", "bot", (-0.30, 0.30, -0.45, 0.45)),
    ("sod882_bot", "SOD-882_L1.0-W0.6-BI", "bot", None),
    ("bul_bot", "BULETM-SMD_22P-P2.00_ESP8685-WROOM-01-XX", "bot", (-3.0, 1.0, -3.0, 1.0)),
    ("wifim_bot", "WIFIM-SMD_61P-L13.2-W12.5-P0.80", "bot", (-3.0, 2.0, -5.0, -1.0)),
]
for tag, base, view, zoom in JOBS:
    src = os.path.join(D, base + ".step")
    dst = os.path.join(W, "out", base + "_noText.step")
    for pre, p in (("before", src), ("after", dst)):
        if not os.path.exists(p):
            print("  skip", pre, base)
            continue
        sh = Part.Shape(); sh.read(p)
        render(sh, view, os.path.join(OUT, "%s_%s.png" % (tag, pre)),
               W=1100, H=800, zoom=zoom)
