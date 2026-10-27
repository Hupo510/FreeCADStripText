# -*- coding: utf-8 -*-
"""rcol.py -- 带逐面颜色的软件渲染(读 STEP 自己的 STYLED_ITEM), 用于核对配色是否被改坏。

面顺序约定: Part.Shape.read() 的 Faces 顺序 == 文件里 ADVANCED_FACE 的书写顺序,
所以 colors[i] 直接对应 shape.Faces[i]。
"""
import os
import sys

import numpy as np
from PIL import Image

import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r3d import AXES, LIGHT
from stepcolor import face_colors

GREY = (0.82, 0.82, 0.82)


def shape_colors(path):
    """返回 (shape, 每面 RGB)。读不到颜色的面给浅灰。"""
    sh = Part.Shape()
    sh.read(path)
    try:
        order, seq, _ = face_colors(path)
    except Exception:
        seq = []
    cols = []
    for i in range(len(sh.Faces)):
        c = seq[i] if i < len(seq) else None
        cols.append(tuple(c[:3]) if c else GREY)
    return sh, cols


def render(shape, cols, view, path, W=1300, H=900, zoom=None, edges=True, tol=0.02,
           flat=False):
    ax, ay, az, sx, sy, sz = AXES[view]
    tris, V, C = [], [], []
    for fi, f in enumerate(shape.Faces):
        pts, fac = f.tessellate(tol)
        if not fac:
            continue
        b = len(V)
        V += [(p.x, p.y, p.z) for p in pts]
        c = cols[fi] if fi < len(cols) else GREY
        for t in fac:
            tris.append((b + t[0], b + t[1], b + t[2]))
            C.append(c)
    if not V:
        return False
    V = np.array(V)
    u = V[:, ax] * sx
    v = V[:, ay] * sy
    d = V[:, az] * sz
    if zoom:
        umin, umax, vmin, vmax = zoom
    else:
        umin, umax, vmin, vmax = u.min(), u.max(), v.min(), v.max()
        pad = 0.04 * max(umax - umin, vmax - vmin)
        umin -= pad; umax += pad; vmin -= pad; vmax += pad
    s = min(W / (umax - umin), H / (vmax - vmin))
    px = (u - umin) * s
    py = H - (v - vmin) * s

    img = np.full((H, W, 3), 1.0)
    zb = np.full((H, W), -1e18)
    for k, (a, b, c) in enumerate(tris):
        X = np.array([px[a], px[b], px[c]])
        Y = np.array([py[a], py[b], py[c]])
        Z = np.array([d[a], d[b], d[c]])
        w0, w1, w2 = V[a], V[b], V[c]
        n = np.cross([w1[0] - w0[0], w1[1] - w0[1], w1[2] - w0[2]],
                     [w2[0] - w0[0], w2[1] - w0[1], w2[2] - w0[2]])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            continue
        n = n / ln
        # 固定光照, 保持颜色可辨认(太强会把浅色压成深色, 不利于核对)
        shade = 1.0 if flat else (0.62 + 0.38 * abs(float(np.dot(n, LIGHT))))
        xmi, xma = max(int(np.floor(X.min())), 0), min(int(np.ceil(X.max())), W - 1)
        ymi, yma = max(int(np.floor(Y.min())), 0), min(int(np.ceil(Y.max())), H - 1)
        if xma < xmi or yma < ymi:
            continue
        gx, gy = np.meshgrid(np.arange(xmi, xma + 1) + .5, np.arange(ymi, yma + 1) + .5)
        den = (Y[1] - Y[2]) * (X[0] - X[2]) + (X[2] - X[1]) * (Y[0] - Y[2])
        if abs(den) < 1e-12:
            continue
        l0 = ((Y[1] - Y[2]) * (gx - X[2]) + (X[2] - X[1]) * (gy - Y[2])) / den
        l1 = ((Y[2] - Y[0]) * (gx - X[2]) + (X[0] - X[2]) * (gy - Y[2])) / den
        l2 = 1 - l0 - l1
        mk = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        dep = l0 * Z[0] + l1 * Z[1] + l2 * Z[2]
        sub = zb[ymi:yma + 1, xmi:xma + 1]
        upd = mk & (dep > sub)
        if not upd.any():
            continue
        sub[upd] = dep[upd]
        si = img[ymi:yma + 1, xmi:xma + 1]
        col = C[k]
        for ch in range(3):
            si[:, :, ch][upd] = min(1.0, col[ch] * shade)
    if edges:
        rgb = img * 255.0
        for e in shape.Edges:
            n = max(2, int(e.Length / 0.03))
            pts = [e.valueAt(e.FirstParameter + (e.LastParameter - e.FirstParameter) * i / n)
                   for i in range(n + 1)]
            for p in pts:
                w = (p.x, p.y, p.z)
                x = (w[ax] * sx - umin) * s
                y = H - (w[ay] * sy - vmin) * s
                z = w[az] * sz
                xi, yi = int(round(x)), int(round(y))
                for ddx, ddy in ((0, 0), (1, 0), (0, 1)):
                    xj, yj = xi + ddx, yi + ddy
                    if 0 <= xj < W and 0 <= yj < H:
                        if z >= zb[yj, xj] - 0.05:
                            rgb[yj, xj] *= 0.45
        img = rgb / 255.0
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(path)
    return True


def render_file(path, view, out, W=1300, H=900, zoom=None, edges=True, flat=False):
    sh, cols = shape_colors(path)
    ok = render(sh, cols, view, out, W=W, H=H, zoom=zoom, edges=edges, flat=flat)
    if ok:
        print("  saved %s" % os.path.basename(out))
    return ok


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if x.lower().endswith((".step", ".stp"))]
    if not a:
        print("usage: freecadcmd.exe rcol.py <in.step> [view]")
    else:
        v = "top"
        for x in sys.argv[2:]:
            if x in AXES:
                v = x
        render_file(a[0], v, a[0].rsplit(".", 1)[0] + "_" + v + ".png")
