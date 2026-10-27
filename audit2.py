# -*- coding: utf-8 -*-
import Part

CASES = [
 ("SIM-SMD  top",   r"C:/Users/lhm/WorkBuddy/2026-10-26-14-54-26/SIM-SMD_noText.step",  "z", 1.350, (-2.45,1.45,-1.05,0.75)),
 ("SIM-SMD  bot",   r"C:/Users/lhm/WorkBuddy/2026-10-26-14-54-26/SIM-SMD_noText.step",  "z", 0.000, (-3.25,4.05,-3.05,-0.65)),
 ("CONN-SMD bot",   r"C:/Users/lhm/WorkBuddy/2026-10-26-14-54-26/CONN-SMD_noText.step", "z", 0.300, (-0.45,0.70,-1.75,0.95)),
 ("CONN-TH  side",  r"C:/Users/lhm/WorkBuddy/2026-10-26-14-54-26/CONN-TH_noText.step",  "y", 2.725, (-1.45,1.15,-3.75,-2.65)),
]
def reg_in(bb, axis, r):
    if axis == "z":
        return (r[0] <= bb.XMin and bb.XMax <= r[1] and r[2] <= bb.YMin and bb.YMax <= r[3])
    return (r[0] <= bb.XMin and bb.XMax <= r[1] and r[2] <= bb.ZMin and bb.ZMax <= r[3])

cache = {}
for tag, path, axis, d, r in CASES:
    if path not in cache:
        s = Part.Shape(); s.read(path); cache[path] = s
        print("==", path.split("\\")[-1], "faces=%d valid=%s" % (len(s.Faces), s.isValid()))
    s = cache[path]
    inp = []
    for f in s.Faces:
        if not f.Surface.isPlanar() or not reg_in(f.BoundBox, axis, r):
            continue
        n = f.normalAt(0.5, 0.5)
        c = f.CenterOfMass
        dd = {"z": c.z, "y": c.y, "x": c.x}[axis]
        if abs(abs(getattr(n, axis)) - 1.0) > 1e-6:
            continue
        if abs(dd - d) > 3e-3:
            continue
        inp.append(f)
    inner = 0
    for f in inp:
        for w in f.Wires:
            if not w.isSame(f.OuterWire):
                inner += 1
    print("   %-14s 区域内共面面=%d 内环合计=%d  %s"
          % (tag, len(inp), inner, "OK" if (len(inp) == 1 and inner == 0) or (len(inp) == 0) else "<== 有残留"))
