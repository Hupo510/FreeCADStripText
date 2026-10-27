# -*- coding: utf-8 -*-
"""colordiff.py -- 源文件 vs 成品 的**逐面**配色对比。

比 colorarea.py 更细: 它按几何把成品的每张面配回源文件的那张面, 然后逐面比色,
只把"颜色真的变了"的面打出来(带面积/位置/法向/前后 RGBA), 供定位是哪一处被改。

匹配顺序:
  1. 中心+面积指纹(未被碰过的面必定精确命中)
  2. 外环指纹(擦字时重建的宿主面: 外环未变, 面积/中心变了)
     外环指纹加强为 (bbox, 环长, 边数), 避免"两块平行板共用一个环形状"撞车
  3. 找不到 -> 报 UNMATCHED

用法:
  freecadcmd.exe colordiff.py                 # 全部 out/*_noText.step
  freecadcmd.exe colordiff.py BULETM-SMD_22P  # 只查名字里含该串的
"""
import glob
import os
import sys

import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stepcolor import face_colors

SRC_DIR = "C:/Users/lhm/Downloads"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def load(path):
    sh = Part.Shape()
    sh.read(path)
    order, seq, _ = face_colors(path)
    if len(seq) < len(sh.Faces):
        seq = list(seq) + [None] * (len(sh.Faces) - len(seq))
    return sh, seq[:len(sh.Faces)]


def _r(v, n=4):
    return round(float(v), n)


def key_ca(f):
    c = f.CenterOfMass
    return (_r(c.x), _r(c.y), _r(c.z), _r(f.Area, 5))


def key_ow(f):
    """外环强指纹: bbox + 环长 + 边数 + 平面。"""
    try:
        w = f.OuterWire
        b = w.BoundBox
        return (_r(b.XMin, 5), _r(b.XMax, 5), _r(b.YMin, 5), _r(b.YMax, 5),
                _r(b.ZMin, 5), _r(b.ZMax, 5), _r(w.Length, 5), len(w.Edges))
    except Exception:
        return None


def nrm(f):
    try:
        n = f.normalAt(0.5, 0.5)
        if n.Length > 1e-9:
            n.normalize()
            return (_r(n.x, 3), _r(n.y, 3), _r(n.z, 3))
    except Exception:
        pass
    return None


def plane_key(f):
    try:
        if not f.Surface.isPlanar():
            return None
        n = f.normalAt(0.5, 0.5)
        if n.Length < 1e-9:
            return None
        n.normalize()
        c = f.CenterOfMass
        return (_r(n.x, 2), _r(n.y, 2), _r(n.z, 2),
                _r(n.x * c.x + n.y * c.y + n.z * c.z, 3))
    except Exception:
        return None


def same_color(a, b, tol=0.004):
    if a is None or b is None:
        return a is b
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a[:3], b[:3]))


def check(base):
    src = os.path.join(SRC_DIR, base + ".step")
    dst = os.path.join(OUT_DIR, base + "_noText.step")
    if not (os.path.exists(src) and os.path.exists(dst)):
        print("  [skip] %s (缺文件)" % base)
        return None
    osh, ocol = load(src)
    nsh, ncol = load(dst)
    ca = {}
    ow = {}
    pl = {}
    for i, f in enumerate(osh.Faces):
        if ocol[i] is None:
            continue
        ca.setdefault(key_ca(f), i)
        k = key_ow(f)
        if k is not None:
            ow.setdefault(k, []).append(i)
        k = plane_key(f)
        if k is not None:
            pl.setdefault(k, []).append(i)
    hit_ca = hit_ow = hit_ow_amb = hit_pl = 0
    bad, unm = [], []
    for j, f in enumerate(nsh.Faces):
        i = ca.get(key_ca(f))
        how = "CA"
        if i is None:
            cand = ow.get(key_ow(f)) or []
            if cand:
                how = "OW"
                # 同一外环有多个源面时, 用法向 + 共面点再筛一次, 仍多就取面积最近
                if len(cand) > 1:
                    hit_ow_amb += 1
                    nj = nrm(f)
                    same = [x for x in cand if nrm(osh.Faces[x]) == nj]
                    if same:
                        cand = same
                    cand = sorted(cand, key=lambda x: abs(osh.Faces[x].Area - f.Area))
                i = cand[0]
        if i is None:
            # 布尔补/削后与宿主面同平面的碎面 -> 用与 colorize 相同的同平面规则
            cand = pl.get(plane_key(f)) or []
            if cand:
                c = f.CenterOfMass
                ins = [x for x in cand
                       if osh.Faces[x].BoundBox.XMin - 1e-6 <= c.x <=
                       osh.Faces[x].BoundBox.XMax + 1e-6
                       and osh.Faces[x].BoundBox.YMin - 1e-6 <= c.y <=
                       osh.Faces[x].BoundBox.YMax + 1e-6
                       and osh.Faces[x].BoundBox.ZMin - 1e-6 <= c.z <=
                       osh.Faces[x].BoundBox.ZMax + 1e-6]
                big = [x for x in ins if osh.Faces[x].Area >= 0.9 * f.Area]
                i = min(big or ins, key=lambda x: osh.Faces[x].Area) if (big or ins) \
                    else max(cand, key=lambda x: osh.Faces[x].Area)
                how = "PL"
        if i is None:
            unm.append(j)
            continue
        if how == "CA":
            hit_ca += 1
        elif how == "OW":
            hit_ow += 1
        else:
            hit_pl += 1
        if not same_color(ncol[j], ocol[i]):
            b = f.BoundBox
            bad.append((j, i, how, f.Area, (f.CenterOfMass.x, f.CenterOfMass.y,
                                            f.CenterOfMass.z), nrm(f),
                        ocol[i], ncol[j],
                        (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)))
    print("  %-46s 源 %d 面 / 成品 %d 面 | 中心+面积 %d, 外环 %d(歧义 %d),"
          " 同平面 %d, 未匹配 %d, **变色 %d**"
          % (base[:46], len(osh.Faces), len(nsh.Faces), hit_ca, hit_ow,
             hit_ow_amb, hit_pl, len(unm), len(bad)))
    for (j, i, how, a, c, n, co, cn, bb) in bad:
        print("      [变色] 成品面#%-4d <- 源面#%-4d (%s) A=%.4f  C=(%.3f,%.3f,%.3f) n=%s"
              % (j, i, how, a, c[0], c[1], c[2], n))
        print("             源 %s  ->  成品 %s   bbox X[%.2f..%.2f] Y[%.2f..%.2f] Z[%.2f..%.2f]"
              % (tuple(round(float(v), 3) for v in co[:3]),
                 tuple(round(float(v), 3) for v in cn[:3]),
                 bb[0], bb[1], bb[2], bb[3], bb[4], bb[5]))
    for j in unm[:8]:
        f = nsh.Faces[j]
        print("      [未匹配] 成品面#%-4d A=%.4f C=(%.3f,%.3f,%.3f) n=%s 色=%s"
              % (j, f.Area, f.CenterOfMass.x, f.CenterOfMass.y, f.CenterOfMass.z,
                 nrm(f), tuple(round(float(v), 3) for v in (ncol[j] or (0, 0, 0))[:3])))
    return len(bad) + len(unm)


def main():
    pat = None
    for a in sys.argv[1:]:
        if a.lower().endswith(".py"):
            continue                      # freecadcmd 把脚本名也塞进 argv
        if a.lower().endswith((".step", ".stp")):
            pat = os.path.basename(a).rsplit(".", 1)[0].replace("_noText", "")
        elif not a.startswith("-"):
            pat = a
    bases = sorted(os.path.basename(p).replace("_noText.step", "")
                   for p in glob.glob(os.path.join(OUT_DIR, "*_noText.step")))
    if pat:
        bases = [b for b in bases if pat in b]
    print("== 逐面配色对比 (源 vs 成品) ==")
    tot = 0
    for b in bases:
        tot += (check(b) or 0)
    print("合计 变色+未匹配 = %d" % tot)


main()
