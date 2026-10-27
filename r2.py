# -*- coding: utf-8 -*-
"""r2.py -- 随手对比渲染: 源文件 / 成品 同视角同缩放
用法: freecadcmd.exe r2.py <文件主干> <view> [zoom:xmin,xmax,ymin,ymax]
      view = top|bot|front|back|left|right|posY|negY
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Part
from r3d import AXES
from rcol import render, shape_colors

W = os.path.dirname(os.path.abspath(__file__))
D = r"C:/Users/lhm/Downloads"
OUT = os.path.join(W, "render")
os.makedirs(OUT, exist_ok=True)

# freecadcmd 会把不像脚本的参数当"要打开的文件", 所以用 KEY=VALUE 形式传参
def _de_surrogate(s):
    """freecadcmd 把命令行里的非 ASCII 字符按本地代码页塞进 argv(见 strip_text.py
    顶部注释), 不修就会被 os.path.exists 当成非法路径拒绝。"""
    if not isinstance(s, str) or not any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        return s
    try:
        raw = s.encode("utf-8", "surrogateescape")
    except Exception:
        return s
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            t = raw.decode(enc)
        except Exception:
            continue
        if not any(0xD800 <= ord(c) <= 0xDFFF for c in t):
            return t
    return s


a = [_de_surrogate(x) for x in sys.argv[1:]]
kv = {}
for x in a:
    if "=" in x:
        k, v = x.split("=", 1)
        kv[k.upper()] = v
base = kv.get("B") or kv.get("BASE")
if not base:
    print("usage: r2.py B=<文件主干> [V=top] [Z=xmin,xmax,ymin,ymax]")
    print("          [DIR=<源目录>] [ODIR=<成品目录>] [OSUF=_noText]")
    sys.exit()
view = kv.get("V", "top")
if view not in AXES:
    view = "top"
# ⚠ 路径不能带 ".step" 后缀当参数传: freecadcmd 会把"看起来像文件"的参数自己
# 打开一遍, 带中文时会因 OSError(22) 直接崩掉。所以只传目录 + 主干名。
sdir = kv.get("DIR") or kv.get("SDIR") or D
odir = kv.get("ODIR") or os.path.join(W, "out")
osuf = kv.get("OSUF", "_noText")
src = os.path.join(sdir, base + ".step")
dst = os.path.join(odir, base + osuf + ".step")

z = None
if "Z" in kv:
    z = tuple(float(t) for t in kv["Z"].split(","))
if z is None:
    s0 = Part.Shape(); s0.read(src)
    ax, ay, az, sx, sy, sz = AXES[view]
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
    if not os.path.exists(p):
        print("  skip", pre)
        continue
    sh, cols = shape_colors(p)
    render(sh, cols, view, os.path.join(OUT, "%s_%s_%s.png" % (base, view, pre)),
           W=900, H=720, zoom=z)
    print("  %s %s %s" % (base, view, pre))

# 命令行带中文时 freecadcmd 的自然退出路径会崩, 必须 flush + SystemExit(0),
# 否则上面的打印全丢在缓冲里(见 strip_text.py 顶部说明)
sys.stdout.flush()
sys.exit(0)
