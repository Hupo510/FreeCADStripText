# -*- coding: utf-8 -*-
"""r3d.py -- 极简软件渲染: 着色 + 消隐棱线叠加(能看到残留接缝)"""
import numpy as np, os
from PIL import Image

LIGHT = np.array([0.35, 0.25, 0.90]); LIGHT /= np.linalg.norm(LIGHT)
AXES = {
    "top":   (0, 1, 2,  1,  1,  1),
    "bot":   (0, 1, 2,  1, -1, -1),
    "front": (0, 2, 1,  1,  1, -1),
    "back":  (0, 2, 1,  1, -1,  1),
    "left":  (1, 2, 0, -1,  1,  1),
    "right": (1, 2, 0,  1,  1,  1),
    "posY":  (0, 2, 1,  1,  1,  1),
    "negY":  (0, 2, 1,  1, -1, -1),
}

def render(shape, view, path, W=1300, H=900, zoom=None, edges=True, tol=0.02):
    ax, ay, az, sx, sy, sz = AXES[view]
    tris, V = [], []
    for f in shape.Faces:
        pts, fac = f.tessellate(tol)
        if not fac:
            continue
        b = len(V)
        V += [(p.x, p.y, p.z) for p in pts]
        tris += [(b + t[0], b + t[1], b + t[2]) for t in fac]
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
    for (a, b, c) in tris:
        p = [(px[a], py[a], d[a]), (px[b], py[b], d[b]), (px[c], py[c], d[c])]
        X = np.array([q[0] for q in p]); Y = np.array([q[1] for q in p]); Z = np.array([q[2] for q in p])
        w0v, w1v, w2v = V[a], V[b], V[c]
        n = np.cross([w1v[0] - w0v[0], w1v[1] - w0v[1], w1v[2] - w0v[2]],
                     [w2v[0] - w0v[0], w2v[1] - w0v[1], w2v[2] - w0v[2]])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            continue
        n = n / ln
        shade = 0.30 + 0.70 * abs(float(np.dot(n, LIGHT)))
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
        for k in range(3):
            ch = si[:, :, k]; ch[upd] = 0.75 * shade

    # --- 棱线 ---
    if edges:
        rgb = img * 255.0
        for e in shape.Edges:
            n = max(2, int(e.Length / 0.03))
            pts = [e.valueAt(e.FirstParameter + (e.LastParameter - e.FirstParameter) * i / n) for i in range(n + 1)]
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
                            rgb[yj, xj] *= 0.25
        img = rgb / 255.0
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(path)
    print("  saved", os.path.basename(path))
    return True
