# -*- coding: utf-8 -*-
"""STEP 逐面颜色解析: STYLED_ITEM -> COLOUR_RGB, 并验证面顺序"""
import re, sys

def split_entities(txt):
    """按 ; 切实体, 但跳过字符串内的分号。返回 {id: body}"""
    ents = {}
    i, n = 0, len(txt)
    cur = []
    in_str = False
    start_id = None
    while i < n:
        c = txt[i]
        if in_str:
            cur.append(c)
            if c == "'":
                if i + 1 < n and txt[i+1] == "'":
                    cur.append(txt[i+1]); i += 2; continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True; cur.append(c); i += 1; continue
        if c == ";":
            body = "".join(cur).strip()
            m = re.match(r"#(\d+)\s*=\s*(.*)$", body, re.S)
            if m:
                ents[int(m.group(1))] = " ".join(m.group(2).split())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    return ents

def etype(body):
    m = re.match(r"([A-Z0-9_]+)\s*\(", body)
    return m.group(1) if m else ""

def refs(body):
    """实体体里的所有 #id 引用(第一个括号外的类型名不算)"""
    return [int(x) for x in re.findall(r"#(\d+)", body)]

def first_str_args(body):
    """取参数中的数字串(用于 COLOUR_RGB)"""
    return body

# ISO 10303-46 draughting_pre_defined_colour 的 8 个枚举值 -> RGB
# 立创的导出件大量使用它(black 底色/white 罩面/yellow 标记), 只认 COLOUR_RGB 的话
# 这些面会静默退回"实体基础色", 于是白罩面变金黄、黑阻焊变金黄 —— 就是"颜色被篡改"。
PREDEF_COLOUR = {
    "black": (0.0, 0.0, 0.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "magenta": (1.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0),
    "white": (1.0, 1.0, 1.0),
}


def colour_of(ents, cid):
    b = ents.get(cid, "")
    t = etype(b)
    if t == "COLOUR_RGB":
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", b.split("(", 1)[1])
        if len(nums) >= 3:
            return (float(nums[0]), float(nums[1]), float(nums[2]))
        return None
    if t == "DRAUGHTING_PRE_DEFINED_COLOUR":
        m = re.search(r"'([^']*)'", b)
        if m:
            return PREDEF_COLOUR.get(m.group(1).strip().lower())
    return None

FILL_CHAIN = ("PRESENTATION_STYLE_ASSIGNMENT", "SURFACE_STYLE_USAGE",
              "SURFACE_SIDE_STYLE", "SURFACE_STYLE_FILL_AREA",
              "FILL_AREA_STYLE", "FILL_AREA_STYLE_COLOUR")


def _walk(ents, eid, allow, depth=0, seen=None):
    if seen is None:
        seen = set()
    if eid in seen or depth > 12:
        return None
    seen.add(eid)
    b = ents.get(eid)
    if not b:
        return None
    c = colour_of(ents, eid)
    if c:
        return c
    if allow is not None and etype(b) not in allow:
        return None
    for r in refs(b):
        c = _walk(ents, r, allow, depth + 1, seen)
        if c:
            return c
    return None


def find_colour(ents, eid, depth=0, seen=None):
    """从任意样式实体向下找颜色。

    **必须先走"填充色"分支**: 立创的基础样式常常是
        PRESENTATION_STYLE_ASSIGNMENT((SURFACE_STYLE_USAGE(...白色...),
                                      CURVE_STYLE(...,#深灰)))
    CURVE_STYLE 描述的是**棱边**颜色, 不是面的颜色。老代码碰到预定义色解析不出来
    就继续遍历, 一路走到 CURVE_STYLE 的深灰上 —— 于是"白色/银色外壳"被写成深灰,
    整块变暗沉。现在先只走 FILL_* 这一支, 实在没有才退回任意颜色。
    """
    c = _walk(ents, eid, FILL_CHAIN)
    if c:
        return c
    return _walk(ents, eid, None)

def split_args(body):
    """把 TYPE(a,b,(c,d),'x') 的括号内参数按顶层逗号切开"""
    try:
        s = body[body.index("(") + 1: body.rindex(")")]
    except ValueError:
        return []
    out, depth, cur, in_str = [], 0, [], False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str:
            cur.append(ch)
            if ch == "'":
                if i + 1 < len(s) and s[i+1] == "'":
                    cur.append(s[i+1]); i += 2; continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True; cur.append(ch); i += 1; continue
        if ch in "([":
            depth += 1; cur.append(ch); i += 1; continue
        if ch in ")]":
            depth -= 1; cur.append(ch); i += 1; continue
        if ch == "," and depth == 0:
            out.append("".join(cur).strip()); cur = []; i += 1; continue
        cur.append(ch); i += 1
    if cur:
        out.append("".join(cur).strip())
    return out

def ids_in(tok):
    return [int(x) for x in re.findall(r"#(\d+)", tok)]

def face_colors(path):
    txt = open(path, "r", encoding="utf-8", errors="ignore").read()
    ents = split_entities(txt)
    order = [i for i in sorted(ents) if etype(ents[i]) == "ADVANCED_FACE"]
    idx = {fid: k for k, fid in enumerate(order)}
    shell_col, face_col = {}, {}
    unres = set()
    for i in sorted(ents):
        t = etype(ents[i])
        # 逐面覆盖用 OVER_RIDING_STYLED_ITEM(名,(样式),几何项,被覆盖项)
        if t not in ("STYLED_ITEM", "OVER_RIDING_STYLED_ITEM"):
            continue
        a = split_args(ents[i])
        if len(a) < 3:
            continue
        styles = ids_in(a[1])
        target_l = ids_in(a[2])
        if not target_l:
            continue
        target = target_l[0]
        col = None
        for r in styles:
            col = find_colour(ents, r)
            if col:
                break
        if not col:
            if target in idx:
                unres.add(target)
            continue
        if target in idx:
            face_col[target] = col
            continue

        def expand(tid, col=col, depth=0):
            if depth > 4:
                return
            for r in ids_in(ents.get(tid, "")):
                if r in idx:
                    shell_col[r] = col
                elif etype(ents.get(r, "")) in ("CLOSED_SHELL", "OPEN_SHELL",
                                                "MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS",
                                                "SHELL_BASED_SURFACE_MODEL"):
                    expand(r, col, depth + 1)
        expand(target)
    seq = [face_col.get(fid, shell_col.get(fid)) for fid in order]
    if unres:
        print("  [warn] %d 个面的样式链解析不出颜色(已退回实体基础色): %s"
              % (len(unres), sorted(unres)[:6]))
    return order, seq, ents

def _run():
    ps = [x for x in sys.argv[1:] if x.lower().endswith((".step", ".stp"))]
    if not ps:
        print("usage: stepcolor.py <file.step>")
        return
    p = ps[0]
    order, seq, ents = face_colors(p)
    print("ADVANCED_FACE 数=%d, 有颜色=%d" % (len(order), sum(1 for c in seq if c)))
    uniq = {}
    for c in seq:
        if c:
            k = tuple(round(v, 3) for v in c)
            uniq[k] = uniq.get(k, 0) + 1
    print("颜色分布:", sorted(uniq.items(), key=lambda kv: -kv[1]))
    print("前 10 个面的颜色:", [None if not c else tuple(round(v, 2) for v in c) for c in seq[:10]])
    print("第 5..14 个:", [None if not c else tuple(round(v, 2) for v in c) for c in seq[5:14]])

if any(x.lower().endswith((".step", ".stp")) for x in sys.argv[1:]):
    _run()
