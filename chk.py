# -*- coding: utf-8 -*-
"""双向布尔对比: 判断"去文字"之外有没有动到别的几何。用法:
  freecadcmd.exe chk.py <orig.step> <new.step>
判据: 删除材料的 bbox 必须落在文字区内、总量 = 字浮雕体积; 新增材料为 0 或 = 被填的坑体积。"""
import sys
A = list(sys.argv)
import Part

paths = [x for x in A if x.lower().endswith((".step", ".stp"))]
if len(paths) < 2:
    print("usage: freecadcmd.exe chk.py <orig.step> <new.step>")
    print("argv=%s" % A)
    sys.exit(1)
a, b = paths[0], paths[1]
o = Part.Shape(); o.read(a)
c = Part.Shape(); c.read(b)
vo = sum(s.Volume for s in o.Solids); vc = sum(s.Volume for s in c.Solids)
print("ORIG solids=%d faces=%d vol=%.6f" % (len(o.Solids), len(o.Faces), vo))
print("NEW  solids=%d faces=%d vol=%.6f dV=%+.6f (%.5f%%) valid=%s closed=%s"
      % (len(c.Solids), len(c.Faces), vc, vc - vo, 100 * (vc - vo) / vo,
         c.isValid(), c.isClosed()))
for tag, s in (("ADDED", c.cut(o)), ("REMOVED", o.cut(c))):
    v = sum(x.Volume for x in s.Solids)
    print("%s vol=%.6f solids=%d" % (tag, v, len(s.Solids)))
    for x in sorted(s.Solids, key=lambda x: -x.Volume)[:5]:
        bb = x.BoundBox
        print("   %+.6f X[%.3f,%.3f] Y[%.3f,%.3f] Z[%.3f,%.3f]"
              % (x.Volume, bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax))
