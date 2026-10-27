# -*- coding: utf-8 -*-
"""把原 STEP 的逐面颜色搬到清理后的模型上。

FreeCAD 的 STEP 导入不读颜色, 导出(console 模式)也不写, 所以颜色只能自己搬:
  1. 解析原文件的 STYLED_ITEM / OVER_RIDING_STYLED_ITEM -> COLOUR_RGB, 得到逐面色
  2. 清理后重新导出(无颜色), 再读回, 用几何指纹把每个新面映射回原面
  3. 在输出文件的 DATA 段注入 COLOUR_RGB + 样式链 + STYLED_ITEM
     + MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION
"""
import os
import re
import sys

import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stepcolor import face_colors, split_entities, etype, split_args

FALLBACK = (0.80, 0.80, 0.80)


def face_key(f):
    """几何指纹: 中心 + 面积。布尔运算不改动的面, 前后指纹完全一致。"""
    c = f.CenterOfMass
    return (round(c.x, 4), round(c.y, 4), round(c.z, 4), round(f.Area, 5))


def wire_key(w):
    """外环指纹。重建宿主面时外环原样保留、只是内环少了几个, 所以面积/中心变了,
    face_key 会失配; 外环指纹仍然精确命中 —— 这是补平后的面继承"宿主颜色"
    (而不是继承字色)最可靠的一条路。"""
    b = w.BoundBox
    return (round(b.XMin, 5), round(b.XMax, 5), round(b.YMin, 5),
            round(b.YMax, 5), round(b.ZMin, 5), round(b.ZMax, 5))


def ids_in(s):
    """从 '(...)' 或 '#123' 这类参数字面量里取出全部实体号。"""
    return [int(x) for x in re.findall(r"#(\d+)", s or "")]


def text_face_indices(orig_sh, jobs):
    """被判定为文字的面, 不参与颜色匹配(否则补平后的新面会继承字的颜色)"""
    hs = set()
    for j in jobs:
        for r in getattr(j, "ribs", []):
            try:
                hs.add(r.hashCode())
            except Exception:
                pass
    out = set()
    for i, f in enumerate(orig_sh.Faces):
        if f.hashCode() in hs:
            out.add(i)
    return out


def _nearest(osh, seq, skip, fn):
    cn = fn.CenterOfMass
    try:
        nn = fn.normalAt(0.5, 0.5)
    except Exception:
        nn = None
    best, bd = None, 1e18
    for i, fo in enumerate(osh.Faces):
        if i in skip or seq[i] is None:
            continue
        bb = fo.BoundBox
        if not (bb.XMin - 0.6 <= cn.x <= bb.XMax + 0.6 and
                bb.YMin - 0.6 <= cn.y <= bb.YMax + 0.6 and
                bb.ZMin - 0.6 <= cn.z <= bb.ZMax + 0.6):
            continue
        d = (fo.CenterOfMass - cn).Length
        if nn is not None and fo.Surface.isPlanar():
            try:
                if fo.normalAt(0.5, 0.5).dot(nn) < 0.9:
                    d += 5.0          # 法向不符的罚分, 避免把顶面涂成侧面色
            except Exception:
                pass
        if d < bd:
            bd, best = d, seq[i]
    return best


def plane_key(f, nd=2, dd=3):
    """共面指纹: (法向, 平面偏移)。布尔补平后新生成的面与宿主面**同平面**,
    而字形侧壁(竖直)、字形底面(差一个字的深度)都不在同一个平面上。
    旧版对这类面走"_nearest"(最近的面) —— 结果补平后的区域继承了字形那种
    深灰色, 整个文字区变成一块深色矩形, 看起来像"文字没删掉"。
    """
    try:
        if not f.Surface.isPlanar():
            return None
        n = f.normalAt(0.5, 0.5)
        if n.Length < 1e-9:
            return None
        n.normalize()
        c = f.CenterOfMass
        d = n.x * c.x + n.y * c.y + n.z * c.z
        return (round(n.x, nd), round(n.y, nd), round(n.z, nd), round(d, dd))
    except Exception:
        return None


def bbox_has(bb, p, pad=0.0):
    return (bb.XMin - pad <= p.x <= bb.XMax + pad and
            bb.YMin - pad <= p.y <= bb.YMax + pad and
            bb.ZMin - pad <= p.z <= bb.ZMax + pad)


def _same_plane(osh, seq, plane2, fn):
    """新面找不到对应源面时, 按"同平面"继承宿主面的颜色。

    优先取"平面内包围住新面中心"的源面里面积最小的那个(最具体);
    没有包围的, 取该平面上面积最大的面(通常就是宿主面)。
    """
    pk = plane_key(fn)
    if pk is None:
        return None
    cand = plane2.get(pk)
    if not cand:
        # 法向按 2 位小数取整可能对不上(重建面的法向有数值噪声), 放宽到 1 位再试
        pk2 = plane_key(fn, nd=1)
        for k, v in plane2.items():
            if k[:3] == pk2[:3] and abs(k[3] - pk2[3]) <= 2e-3:
                cand = v
                break
        if not cand:
            return None
    c = fn.CenterOfMass
    inside = [i for i in cand if bbox_has(osh.Faces[i].BoundBox, c, 1e-6)]
    if inside:
        # 宿主面不会比它上面的补块还小: 先筛掉明显太小的, 再取最"贴身"的那个
        big = [i for i in inside if osh.Faces[i].Area >= 0.9 * fn.Area]
        pool = big or inside
        pick = min(pool, key=lambda i: osh.Faces[i].Area)
    else:
        pick = max(cand, key=lambda i: osh.Faces[i].Area)
    return seq[pick]


def build_color_map(src, new_sh, jobs, verbose=True):
    """返回 (每面颜色列表, 说明)。列表下标与 new_sh.Faces 一一对应。"""
    order, seq, _ = face_colors(src)
    osh = Part.Shape()
    osh.read(src)
    if len(order) != len(osh.Faces):
        return None, "原文件面数不一致(%d vs %d), 放弃颜色" % (len(order), len(osh.Faces))
    skip = text_face_indices(osh, jobs)
    key2col = {}
    wkey2col = {}
    plane2 = {}
    for i, f in enumerate(osh.Faces):
        if i in skip or seq[i] is None:
            continue
        key2col.setdefault(face_key(f), seq[i])
        try:
            wkey2col.setdefault(wire_key(f.OuterWire), seq[i])
        except Exception:
            pass
        pk = plane_key(f)
        if pk is not None:
            plane2.setdefault(pk, []).append(i)
    out = []
    hit = 0
    hitw = 0
    hitp = 0
    for fn in new_sh.Faces:
        c = key2col.get(face_key(fn))
        if c is not None:
            out.append(c)
            hit += 1
            continue
        try:
            c = wkey2col.get(wire_key(fn.OuterWire))
        except Exception:
            c = None
        if c is not None:
            out.append(c)
            hitw += 1
            continue
        # 同平面继承: 优先"包围住本面"的源面(最具体的那个), 否则取该平面最大的面。
        c = _same_plane(osh, seq, plane2, fn)
        if c is not None:
            out.append(c)
            hitp += 1
            continue
        c = _nearest(osh, seq, skip, fn)
        out.append(c if c else FALLBACK)
    if verbose:
        print("  颜色: 原文件 %d 面, 中心+面积命中 %d, 外环命中 %d, 同平面宿主命中 %d,"
              " 其余就近继承 %d"
              % (len(osh.Faces), hit, hitw, hitp, len(new_sh.Faces) - hit - hitw - hitp))
    return out, "ok"


def _style_chain(nid, color):
    """一个完整的面颜色样式链: COLOUR_RGB -> FILL_AREA_STYLE_COLOUR -> FILL_AREA_STYLE
    -> SURFACE_STYLE_FILL_AREA -> SURFACE_SIDE_STYLE -> SURFACE_STYLE_USAGE
    -> PRESENTATION_STYLE_ASSIGNMENT。返回 (PSA 的 id, 行列表, 下一个可用 id)。"""
    k = tuple(round(float(v), 4) for v in color[:3])
    L = []
    a = nid; nid += 1
    L.append("#%d = COLOUR_RGB('',%.6f,%.6f,%.6f);" % (a, k[0], k[1], k[2]))
    b = nid; nid += 1
    L.append("#%d = FILL_AREA_STYLE_COLOUR('',#%d);" % (b, a))
    d = nid; nid += 1
    L.append("#%d = FILL_AREA_STYLE('',(#%d));" % (d, b))
    e = nid; nid += 1
    L.append("#%d = SURFACE_STYLE_FILL_AREA(#%d);" % (e, d))
    g = nid; nid += 1
    L.append("#%d = SURFACE_SIDE_STYLE('',(#%d));" % (g, e))
    h = nid; nid += 1
    L.append("#%d = SURFACE_STYLE_USAGE(.BOTH.,#%d);" % (h, g))
    m = nid; nid += 1
    L.append("#%d = PRESENTATION_STYLE_ASSIGNMENT((#%d));" % (m, h))
    return m, L, nid


def inject_colors(path, colors):
    """把逐面颜色写进已导出的 STEP。colors 的下标 = 文件里 ADVANCED_FACE 的先后顺序。

    写法必须与立创导出的原件同构, 否则很多读取器不认:
        整体   STYLED_ITEM('color',(#基础样式),#实体)
        逐面   OVER_RIDING_STYLED_ITEM('overriding color',(#面样式),(#面),#基础样式)
    之前写成"逐面 STYLED_ITEM", 数值全对但打开是灰的 —— OCCT 的 CAF 读入走的是
    覆盖(overriding)那条路径, 面级 STYLED_ITEM 常常被忽略。"""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    ents = split_entities(txt)
    for i in sorted(ents):
        if etype(ents[i]) == "MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION":
            return False, "文件已含颜色表示, 跳过重复注入"
    order = [i for i in sorted(ents) if etype(ents[i]) == "ADVANCED_FACE"]
    if len(order) != len(colors):
        return False, "文件面数 %d 与颜色数 %d 不符" % (len(order), len(colors))
    # 表示上下文: 单实体是 ADVANCED_BREP_SHAPE_REPRESENTATION, 多实体是 SHAPE_REPRESENTATION
    ctx = None
    for want in ("ADVANCED_BREP_SHAPE_REPRESENTATION", "SHAPE_REPRESENTATION"):
        for i in sorted(ents):
            if etype(ents[i]) != want:
                continue
            a = split_args(ents[i])
            if a:
                ids = re.findall(r"#(\d+)", a[-1])
                if ids:
                    ctx = int(ids[0])
                    break
        if ctx is not None:
            break
    if ctx is None:
        return False, "找不到 SHAPE_REPRESENTATION 的 context"

    nid = max(ents) + 1
    lines, psas = [], {}
    # 基础样式: 用面积最大的一组颜色, 铺在整块实体上
    area = {}
    for face_id, c in zip(order, colors):
        k = tuple(round(float(v), 4) for v in c[:3])
        area[k] = area.get(k, 0) + 1
    base_k = max(area.items(), key=lambda kv: kv[1])[0]
    psas[base_k], L, nid = _style_chain(nid, base_k)
    lines += L
    base_psa = psas[base_k]
    bases = [i for i in sorted(ents)
             if etype(ents[i]) in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS")]
    base_items, insp = [], []
    for bi in bases:
        s = nid; nid += 1
        lines.append("#%d = STYLED_ITEM('color',(#%d),#%d);" % (s, base_psa, bi))
        base_items.append(s)
        insp.append(s)
    ref = base_items[0] if base_items else None

    # 每个面属于哪个实体 -> 覆盖时要引用"自己那个实体"的基础样式
    # (原始文件就是这样: 6 个实体 6 条基础 STYLED_ITEM, 覆盖项各引各的)
    shell_faces, face2solid = {}, {}
    for i in sorted(ents):
        if etype(ents[i]) != "CLOSED_SHELL":
            continue
        a = split_args(ents[i])
        if a:
            shell_faces[i] = ids_in(a[-1])
    for i in sorted(ents):
        if etype(ents[i]) not in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS"):
            continue
        a = split_args(ents[i])
        if not a:
            continue
        # MANIFOLD_SOLID_BREP('',#shell)  /  BREP_WITH_VOIDS('',#shell,(#voids..))
        sh = ids_in(a[1] if len(a) > 1 and etype(ents[i]) == "BREP_WITH_VOIDS" else a[-1])
        if etype(ents[i]) == "BREP_WITH_VOIDS" and len(a) > 2:
            sh += ids_in(a[2])          # 内腔 shell 上的面也归这个实体
        for sid in sh:
            for fid in shell_faces.get(sid, []):
                face2solid[fid] = i
    base_by_solid = dict(zip(bases, base_items))

    plain = 0
    for face_id, c in zip(order, colors):
        k = tuple(round(float(v), 4) for v in c[:3])
        if k not in psas:
            psas[k], L, nid = _style_chain(nid, k)
            lines += L
        s = nid; nid += 1
        rf = base_by_solid.get(face2solid.get(face_id), ref)
        if rf is not None:
            # over_ride 是**单个**实体引用, 不能写成集合 (#n) —— 原始文件是
            # "...(#'overriding color',(#样式),#面,#基础样式)"。写成 (#n) 时严格的
            # 解析器会把这整条覆盖忽略掉, 于是面全退回基础色:
            # 看起来就是"整个模型变成单一颜色、发暗"。
            lines.append("#%d = OVER_RIDING_STYLED_ITEM('overriding color',(#%d),#%d,#%d);"
                         % (s, psas[k], face_id, rf))
            insp.append(s)
        else:
            # 没有实体可挂基础样式时退回面级 STYLED_ITEM(某些读取器仍认)
            lines.append("#%d = STYLED_ITEM('color',(#%d),#%d);" % (s, psas[k], face_id))
            insp.append(s)
            plain += 1
    pst = nid; nid += 1
    parts = []
    for i in range(0, len(insp), 10):
        parts.append("".join("#%d," % s for s in insp[i:i + 10]))
    body = "\n".join(parts).rstrip(",")
    lines.append("#%d = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"
                 "('',(%s),#%d);" % (pst, body, ctx))
    cut = txt.rfind("ENDSEC;")
    if cut < 0:
        return False, "找不到 DATA 段结尾"
    new = txt[:cut] + "\n" + "\n".join(lines) + "\n" + txt[cut:]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return True, ("覆盖式: %d 个面 + %d 个实体基础样式, %d 种颜色"
                  % (len(order), len(base_items), len(psas)))
