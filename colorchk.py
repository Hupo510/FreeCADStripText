# -*- coding: utf-8 -*-
"""按"颜色分组"核对: 每个颜色的总面积 + 包络盒。比数 STYLED_ITEM 条数可靠得多。
用法: freecadcmd.exe colorchk.py <orig.step> <new.step>"""
import sys
A = list(sys.argv)
import Part, stepcolor as S

ps = [x for x in A if x.lower().endswith((".step", ".stp"))]
o_path, n_path = ps[0], ps[1]
o = Part.Shape(); o.read(o_path)
n = Part.Shape(); n.read(n_path)
_, cs_o, _ = S.face_colors(o_path)
_, cs_n, _ = S.face_colors(n_path)
fo, fn = list(o.Faces), list(n.Faces)
print("faces %d -> %d ; colors %d -> %d" % (len(fo), len(fn), len(cs_o), len(cs_n)))


def groups(faces, cs):
    g = {}
    for f, c in zip(faces, cs):
        k = None if not c else tuple(round(v, 3) for v in c)
        b = f.BoundBox
        e = g.setdefault(k, [0, 0.0, [1e18, -1e18, 1e18, -1e18, 1e18, -1e18]])
        e[0] += 1
        e[1] += f.Area
        for i, v in enumerate((b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)):
            e[2][i] = min(e[2][i], v) if i % 2 == 0 else max(e[2][i], v)
    return g


go, gn = groups(fo, cs_o), groups(fn, cs_n)
print("%-22s %-24s %-24s %s" % ("color", "orig(n, area)", "new(n, area)", "area diff"))
for k in sorted(set(go) | set(gn), key=lambda k: -(go.get(k, [0, 0])[1])):
    a = go.get(k, [0, 0.0, None])
    b = gn.get(k, [0, 0.0, None])
    d = b[1] - a[1]
    flag = "" if abs(d) <= max(0.02 * a[1], 1e-4) else "  <== MISMATCH"
    print("%-22s %-24s %-24s %+.4f%s"
          % (str(k), "%d, %.4f" % (a[0], a[1]), "%d, %.4f" % (b[0], b[1]), d, flag))
    if flag and a[2] and b[2]:
        print("      orig bb %s" % ["%.2f" % v for v in a[2]])
        print("      new  bb %s" % ["%.2f" % v for v in b[2]])
