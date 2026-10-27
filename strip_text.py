# -*- coding: utf-8 -*-
"""
strip_text.py -- 通用删除 STEP 模型上的 LCEDA/EasyEDA 文字浮雕(零残留)

一、残留是怎么来的
----------------
立创 EDA 导出的模型把文字做成宿主平面上的"贴花", 三种形态:
  A 凸起: 字面在平面外 h(1µm 量级), 宿主面上有字形内环, 环内是"岛面"
  B 凹刻: 字坑在平面内 h, 坑底是字形面, 宿主面上有字形内环
  C 共面: 字面与平面齐平, 宿主面上有字形内环, 环内是"岛面"
用一个大立方体去"削", 只能削掉 A 的凸起, 还会在平面上留下**切割矩形印记**;
字形内环是宿主面自身的边界, 布尔运算删不掉也补不平 -> 就剩"矩形框 + 字形线条"。

二、本脚本
--------
  1. 检测: 宿主大面上的"一簇小内环"(字形轮廓); 或平面两侧 ≤60µm 处的"一簇小面"(字面)。
     两种线索合并、去重, 得到 [宿主面, 平面 n/d, 区域 bbox]。
  2. 判向: 看字面的偏移符号 —— 在外侧(A)=削, 在内侧(B)=补, 偏移为 0(C)=只归并。
  3. 动作: 用一块**只覆盖该区域、厚度 = 字面深度+20µm** 的有向薄板做 cut/fuse。
     薄板厚度被限制在 0.06mm 以内, 所以真墙/真柱/真通孔不可能被削坏。
  4. 归并: removeSplitter() 把区域内被打散的共面碎片合并成一个整面,
     矩形印记、字形轮廓线一并消失。已验证几何等价(双向 cut 体积均为 0)。
  5. 复查: 区域内不得再有平面外残面、不得再有字形内环。

三、用法
------
  freecadcmd.exe strip_text.py <in.step> [out.step] [LIST]
     LIST   只检测报告, 不改文件
"""
import sys, os, re, time, locale
import Part
from FreeCAD import Vector

# --------------------------------------------------------------- 命令行编码修复
# 现象: 模型路径里有中文时, freecadcmd 一进来就抛
#   UnicodeEncodeError: 'utf-8' codec can't encode characters in position 39-42:
#   surrogates not allowed   ->  Application unexpectedly terminated
#
# 实测原因(freecadcmd 1.1.4): 它把自己收到的宽字符命令行按**本地代码页(中文系统
# 是 GBK)** 转成窄字节, 再交给 Python 用 surrogateescape 解出来 —— 于是每个 GBK
# 字节都变成一个 U+DC80~U+DCFF 的孤立代理。这种 str 只能当"字节容器"看:
#   'D:\\...\\Board(\\udcb4\\udcf3\\udcd3\\udcd0AI...)\\3D\\x.step'
#   .encode('utf-8')                 -> 炸 (就是上面那条报错)
#   os.fsencode()                    -> ed b2 b4 ...  (按 UTF-8 编成 CESU-8, 路径不存在)
#   .encode('utf-8','surrogateescape') -> b4 f3 d3 d0 ... (原始 GBK 字节, 正确)
# 所以先还原字节、再按候选代码页重解, 命令行参数就恢复成真正的汉字。

def _de_surrogate(s):
    """把带孤立代理的 str 还原成真正的 Unicode 文本(最多试几种代码页)。"""
    if not isinstance(s, str):
        return s
    if not any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        return s
    raw = None
    for err in ("surrogateescape", "surrogatepass"):
        try:
            raw = s.encode("utf-8", err)
            break
        except Exception:
            raw = None
    if raw is None:
        return "".join("?" if 0xD800 <= ord(c) <= 0xDFFF else c for c in s)
    cands = ["utf-8"]
    try:
        cands.append(locale.getpreferredencoding(False))
    except Exception:
        pass
    cands += ["gbk", "cp936", "mbcs", "latin-1"]
    for enc in cands:
        if not enc:
            continue
        try:
            t = raw.decode(enc)
        except Exception:
            continue
        if not any(0xD800 <= ord(c) <= 0xDFFF for c in t):
            return t
    return "".join("?" if 0xD800 <= ord(c) <= 0xDFFF else c for c in s)


def _console_safe():
    """控制台是 GBK 时, 打印到不了的字符会抛 UnicodeEncodeError -> 直接改成替换。"""
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass


def _norm_path(p):
    """收掉重复分隔符(D://a//b -> D:\\a\\b)与 "."/".."。
    ⚠ OCCT 的 Shape.read() 认不出重复分隔符 —— os.path.exists() 说 True,
      读却报 OSError: Error in reading STEP。命令行里手打/转义多了就中招。"""
    if not p:
        return p
    try:
        return os.path.normpath(p)
    except Exception:
        return p


_console_safe()
sys.argv = [_de_surrogate(x) for x in sys.argv]
# 让 `import colorize / stepcolor` 无论当前 cwd 在哪都能找到(脚本所在目录)
_HERE = _de_surrogate(os.path.dirname(os.path.abspath(__file__)))
if _HERE and _HERE not in sys.path:
    sys.path.insert(0, _HERE)

def src_product_name(path):
    """取原 STEP 顶层 PRODUCT 名(立创 EDA 导出的就是模型自己的名字)。
    Shape.read() 会丢掉名字, 所以只能从文本里读。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    except Exception:
        return None
    m = re.search(r"PRODUCT\s*\(\s*'((?:[^']|'')*)'", txt)
    if not m:
        return None
    raw = m.group(1).replace("''", "'")
    # 有些导出器会把长名字按行宽硬折断(字符串里直接换行), 这里接回去
    raw = re.sub(r"[\r\n]+", "", raw)
    return raw.strip()

def export_named(sh, dst, name):
    """导出 STEP 并把产品名写成 name。
    直接 sh.exportStep() 会写成 'Open CASCADE STEP translator x.y 1',
    走文档对象 + Import.export 才会用对象的 Label 作为 PRODUCT 名。
    不加载 STEP 颜色表, 所以仍然不写 COLOUR_RGB/STYLED_ITEM。"""
    import FreeCAD, Import
    try:
        doc = FreeCAD.newDocument("strip_tmp")
        try:
            o = doc.addObject("Part::Feature", "Model")
            o.Shape = sh
            o.Label = name
            Import.export([o], dst)
            return True
        finally:
            FreeCAD.closeDocument(doc.Name)
    except Exception as e:
        # 宁可用默认名也不要没输出
        print("[warn] 按名称导出失败(%s), 回退 exportStep" % e)
        sh.exportStep(dst)
        return False

MIN_HOST = 0.30     # 宿主面最小面积 mm2 (上限, 小模型按尺度自动缩小)
WIRE_MAX = 1.0      # 字形内环面积上限 mm2
GAP      = 0.6      # 聚空间距 mm (上限, 小模型按尺度自动缩小)
MIN_N    = 3        # 一簇至少几个内环
MIN_RIB  = 4        # 一簇至少几个字面
OFF_MAX  = 0.06     # 字面离平面的最大偏移 mm
MAX_OFF_NOWIRE = 0.012   # "没有字形内环可对位"的纯贴片, 偏移上限 mm
MIN_OFF  = 3e-4     # 字面离平面的最小偏移 mm (立创的字高 1~10µm; 再小是 STEP 数值噪声)
_DBG = bool(os.environ.get("DEBUG_DETECT"))
INFLATE  = 0.12     # 区域外扩 mm (上限)
EPS      = 0.02     # 薄板比字面多出的余量 mm
PLANAR_TOL = 0.002

def scales(solid):
    """按模型自身尺寸给阈值: 1mm 的 SOD-923 不能用 0.8mm2 的宿主面门槛。
    ⚠ 上限也别给太大 —— 宿主面**可以比模型小得多**: 实测 HDR-TH_10P 的 10 处
    LCEDA 都写在每个针脚的 0.77mm2 侧壁上, 原来的 0.8mm2 门槛只差 0.03 就把它
    全漏掉了。识别靠的是"小内环 + 面积多样性 + 字形对位", 不是宿主面积。"""
    bb = solid.BoundBox
    diag = max(bb.XLength, bb.YLength, bb.ZLength, 1e-3)
    min_host = min(MIN_HOST, max(0.02, 0.05 * diag * diag))
    gap = min(GAP, max(0.08, 0.12 * diag))
    inflate = min(INFLATE, max(0.03, 0.15 * diag))
    return min_host, gap, inflate

def bb_reg(objs):
    bs = [o.BoundBox for o in objs]
    return [min(b.XMin for b in bs), max(b.XMax for b in bs),
            min(b.YMin for b in bs), max(b.YMax for b in bs),
            min(b.ZMin for b in bs), max(b.ZMax for b in bs)]

def bb_in(bb, r, tol=0.0):
    return (bb.XMin >= r[0]-tol and bb.XMax <= r[1]+tol and
            bb.YMin >= r[2]-tol and bb.YMax <= r[3]+tol and
            bb.ZMin >= r[4]-tol and bb.ZMax <= r[5]+tol)

def clust(items, gap=GAP):
    n = len(items); par = list(range(n))
    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i
    bs = [o.BoundBox for o in items]
    for i in range(n):
        a = bs[i]
        for j in range(i+1, n):
            b = bs[j]
            if (a.XMin <= b.XMax+gap and a.XMax >= b.XMin-gap and
                a.YMin <= b.YMax+gap and a.YMax >= b.YMin-gap and
                a.ZMin <= b.ZMax+gap and a.ZMax >= b.ZMin-gap):
                ri, rj = find(i), find(j)
                if ri != rj:
                    par[rj] = ri
    g = {}
    for i in range(n):
        g.setdefault(find(i), []).append(items[i])
    return list(g.values())

def vol(sh):
    try:
        return sum(x.Volume for x in sh.Solids)
    except Exception:
        return sh.Volume


def meshvol(sh, tol=0.02):
    """三角网格积分体积。GProp 的 Volume 在布尔后的碎拓扑上会算错 ——
    实测 LED-SMD 侧面切 10µm 字, GProp 说 +0.0045(加料), 网格积分说 -0.000322
    (正是字的体积)。只在体积守卫判定异常时拿来复核。"""
    v = 0.0
    for f in sh.Faces:
        try:
            pts, fac = f.tessellate(tol)
        except Exception:
            continue
        P = [(q.x, q.y, q.z) for q in pts]
        for t in fac:
            a, b, c = P[t[0]], P[t[1]], P[t[2]]
            v += (a[0] * (b[1] * c[2] - b[2] * c[1])
                  - a[1] * (b[0] * c[2] - b[2] * c[0])
                  + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return abs(v)

def region_area(j):
    """区域在平面内的面积(跳过法向轴)"""
    comp = (abs(j.n.x), abs(j.n.y), abs(j.n.z))
    ax = comp.index(max(comp))
    exts = [j.region[2*i+1] - j.region[2*i] for i in range(3)]
    vals = [e for i, e in enumerate(exts) if i != ax]
    return max(vals[0], 1e-6) * max(vals[1], 1e-6)

def wire_area(w):
    try:
        return Part.Face(w).Area
    except Exception:
        return 1e9


def fill_ratio(f, u, v):
    """面在平面内的"填充率" = 面积 / 平面内包围盒面积。

    矩形焊盘 = 1.0, 圆焊盘 = 0.785, 而**任何字形都远低于 0.75**(笔画只占字形
    外框的一部分, 实测字母 0.35~0.62)。所以一簇"填充率都很高"的面是同形状的
    焊盘/散热栅阵列, 不是字 —— 这条判据比"面积和小于宿主 30%"稳得多, 后者只是
    数量上的巧合(实测 WIFIM-SMD_61P 的 61 个邮票孔焊盘面积和 39.9 对上限 37.0,
    相差不到 8%, 一改簇内成员就会翻)。"""
    if f.Area <= 0:
        return 0.0
    b = _bb2(f, u, v)
    if b is None:
        return 0.0
    a = (b[1] - b[0]) * (b[3] - b[2])
    if a <= 1e-12:
        return 0.0
    return f.Area / a


class Job:
    pass

def _frame(n):
    """平面局部正交基 (u, v)，配合法向 n。所有"平面内"的比较都必须用它 ——
    用世界坐标的某两轴近似只在严格轴向平面上成立。实测 OPTO-SMD-4 的侧壁
    法向是 (0,-0.99,0.11)(约 6° 斜度), 0.86mm 长的文字簇在 Y 上就"厚"了 0.096mm,
    于是整簇被判成"两层结构"直接丢掉。"""
    ref = Vector(1, 0, 0) if abs(n.x) < 0.9 else Vector(0, 1, 0)
    u = ref - n * n.dot(ref)
    if u.Length < 1e-9:
        return None, None
    u.normalize()
    v = n.cross(u)
    v.normalize()
    return u, v


def _edge_pts(e):
    a, b = e.FirstParameter, e.LastParameter
    return [e.valueAt(a), e.valueAt(a + 0.5 * (b - a)), e.valueAt(b)]


def _bb2(o, u, v):
    """对象(线框或面)在平面局部坐标系里的二维包围盒 (umin,umax,vmin,vmax)。"""
    us, vs = [], []
    for e in o.Edges:
        for p in _edge_pts(e):
            us.append(p.dot(u))
            vs.append(p.dot(v))
    if not us:
        return None
    return (min(us), max(us), min(vs), max(vs))


def _bb2_of(objs, u, v):
    """一组对象的二维包围盒并集"""
    bs = [b for b in (_bb2(o, u, v) for o in objs) if b]
    if not bs:
        return None
    return (min(b[0] for b in bs), max(b[1] for b in bs),
            min(b[2] for b in bs), max(b[3] for b in bs))


def _ext_n(o, n):
    """对象沿 n 的投影范围 (min,max)。斜平面必须用投影, 不能用世界 AABB。"""
    ds = []
    for e in o.Edges:
        for p in _edge_pts(e):
            ds.append(p.dot(n))
    if not ds:
        return None
    return (min(ds), max(ds))


def thin_ok(n, objs, tol=0.03):
    """一簇东西沿 n 的厚度。贴花的特征是"法向只有 h 那么厚";
    跨了 0.1mm 就是两层不同结构被误聚, 不是文字。
    (注意别用 "hi > lo" 当有效判据: 严格落在平面上的簇 hi == lo, 会被误判成空。)"""
    lo, hi, got = 1e18, -1e18, False
    for o in objs:
        r = _ext_n(o, n)
        if r is None:
            continue
        got = True
        lo = min(lo, r[0])
        hi = max(hi, r[1])
    return got and (hi - lo) <= tol


def rib_matches_wire(n, f, wires, u=None, v=None):
    """这个"字面"是否恰好盖住某个字形内环(平面内二维包围盒尺寸相近、中心相近)。
    凸起的盖面、凹刻的坑底都与宿主面上的字形内环一一对应, 这是区分"文字"和
    "同平面的焊盘/散热盘"最硬的判据。"""
    if u is None:
        u, v = _frame(n)
        if u is None:
            return False
    a = _bb2(f, u, v)
    if a is None:
        return False
    for w in wires:
        b = _bb2(w, u, v)
        if b is None:
            continue
        ok = True
        for k in (0, 2):
            sz = a[k + 1] - a[k]
            wt = b[k + 1] - b[k]
            if wt <= 1e-9 or not (0.55 <= sz / wt <= 1.15):
                ok = False
                break
            cs = 0.5 * (a[k] + a[k + 1])
            ct = 0.5 * (b[k] + b[k + 1])
            if abs(cs - ct) > max(0.03, 0.30 * wt):
                ok = False
                break
        if ok:
            return True
    return False

def distinct_areas(objs, tol=0.03):
    """这簇面的面积有几个互不相同的档。字母大小不一 -> 多档; 焊盘阵列 -> 只有一档。
    (实测 TDFN-8 的 8 块焊盘面积全是 0.09329, 而 CONN-SMD 的 5 个字母是
     0.0439/0.0576/0.0647/0.0741/0.0846 —— 这是区分"字"和"焊盘"最省事的判据)"""
    bands = []
    for f in sorted(objs, key=lambda f: f.Area):
        a = f.Area
        if not bands or a > bands[-1] * (1 + tol):
            bands.append(a)
    return len(bands)

def detect(solid):
    faces = list(solid.Faces)
    min_host, gap, inflate = scales(solid)
    # 每面的法向/面积/中心先算一次。内层循环要拿每个面跟每个宿主面比,
    # 若在那里调 normalAt 就是 O(F²) 次几何调用(1498 面的 HDR 直接跑不完)。
    meta = []
    for f in faces:
        fn = _normal_at(f)
        meta.append((f, f.Area, fn, f.CenterOfMass))
    cands = []
    for B, BA, BN, BC in meta:
        if BN is None or BA < min_host:
            continue
        n = BN
        u, v = _frame(n)
        if u is None:
            continue
        d = BC.dot(n)
        th = min(WIRE_MAX, 0.25 * BA)
        bb2B = _bb2(B, u, v)
        # 线索1: 宿主面上的小内环簇 = 字形轮廓
        glyphs = [w for w in B.Wires if not w.isSame(B.OuterWire) and wire_area(w) < th]
        for c in clust(glyphs, gap):
            if len(c) < MIN_N or not thin_ok(n, c):
                continue
            # 字形轮廓的面积必然各档不同(每个字母形状不一样); 面积一致的一簇是
            # 焊盘开口/接触片/散热栅, 不是字。实测 WIFIM-SMD 底面 57 个内环面积
            # 只有 6 档(0.4 重复多次), 是 61 个邮票孔焊盘, 不是文字。
            wa = [type("W", (), {"Area": wire_area(w)})() for w in c]
            if distinct_areas(wa) < 0.6 * len(c):
                continue
            cands.append([B, n, d, c, [], bb_reg(c), "内环"])
        # 线索2: 平面两侧 <=OFF_MAX 处的一簇小面 = 字面
        inner = [w for w in B.Wires if not w.isSame(B.OuterWire)]
        bb2w = {}
        for w in inner:
            bb2w[id(w)] = _bb2(w, u, v)
        ribs = []
        for f, fa, fnn, fc in meta:
            if f is B or fnn is None:
                continue
            if fa > min(3.0, 0.50 * BA):
                continue
            if abs(abs(fnn.dot(n)) - 1) > 1e-4:
                continue
            off = fc.dot(n) - d
            if not (1e-7 < abs(off) <= OFF_MAX):
                continue
            # 平面内是否落在宿主面范围内(局部坐标, 斜平面也对)
            fb2 = _bb2(f, u, v)
            if fb2 is None or bb2B is None:
                continue
            if not (fb2[0] >= bb2B[0] - 0.02 and fb2[1] <= bb2B[1] + 0.02 and
                    fb2[2] >= bb2B[2] - 0.02 and fb2[3] <= bb2B[3] + 0.02):
                continue
            ribs.append(f)
        for c in clust(ribs, gap):
            # 按偏移分档: 同一层贴花的所有字面必然同偏移。一簇里常常混着
            # "1µm 深的字坑"和"严格共面的碎片", 若不分开, min|offset| 会被 0 拉平,
            # 整簇被误杀(实测 WIFIM-SMD 的 44 个字坑就是这样丢的)。
            bands = {}
            for f in c:
                bands.setdefault(round(f.CenterOfMass.dot(n) - d, 4), []).append(f)
            for off, cc in bands.items():
                if abs(off) < MIN_OFF:
                    continue                     # 共面碎片(STEP 数值噪声), 不是贴花
                if len(cc) < MIN_RIB:
                    continue
                reg = bb_reg(cc)
                if not thin_ok(n, cc):
                    continue
                dsum, dlim = sum(f.Area for f in cc), 0.30 * B.Area
                if _DBG:
                    print("      [dbg] host A=%.3f off=%+.5f n=%d sum=%.3f lim=%.3f"
                          % (B.Area, off, len(cc), dsum, dlim))
                if dsum > dlim:
                    continue                # 接受条件两条路, 满足其一:
                #  (1) 宿主面上有这个区域的字形内环, 且这簇小面逐个正好盖住内环 —— 铁证;
                #  (2) 没有内环(文字是贴在完整平面上的"贴片", 削掉就行), 但面积必须各档不同。
                #      等面积的一簇是同平面的焊盘阵列, 削掉会把器件削坏(实测 TDFN-8 底部
                #      8 块 0.09329mm2 的焊盘被当成字面切走, 整个模型只剩 14 个面)。
                reg2 = _bb2_of(cc, u, v)
                hit = [w for w in inner
                       if bb2w.get(id(w)) is not None and reg2 is not None and
                       bb2w[id(w)][0] >= reg2[0] - 0.01 and bb2w[id(w)][1] <= reg2[1] + 0.01 and
                       bb2w[id(w)][2] >= reg2[2] - 0.01 and bb2w[id(w)][3] <= reg2[3] + 0.01]
                nm = sum(1 for f in cc if rib_matches_wire(n, f, hit, u, v)) if hit else 0
                # 就算"逐个正好盖住内环", 若这簇面本身是等形状的实心块(矩形/圆),
                # 那是焊盘阵列而不是字形 —— 见 fill_ratio 的说明。
                solid_like = sum(1 for f in cc if fill_ratio(f, u, v) >= 0.75)
                pattern = len(cc) >= 6 and solid_like >= 0.6 * len(cc)
                if _DBG:
                    print("      [dbg2] hostA=%.2f off=%+.5f cc=%d hit=%d nm=%d solid=%d "
                          "pattern=%s reg=[%.2f..%.2f, %.2f..%.2f]"
                          % (B.Area, off, len(cc), len(hit), nm, solid_like, pattern,
                             reg2[0], reg2[1], reg2[2], reg2[3]))
                    if pattern and len(cc) <= 20:
                        for f in cc:
                            g = _bb2(f, u, v)
                            print("         rib A=%.4f fill=%.3f size=%.3fx%.3f"
                                  % (f.Area, fill_ratio(f, u, v),
                                     g[1] - g[0], g[3] - g[2]))
                if hit and nm >= MIN_RIB and nm >= 0.8 * len(cc) and not pattern:
                    pass
                else:
                    # 没有内环可对位的"纯贴片", 只认极薄的(1~10µm)。实测 HDR-TH_10P
                    # 有 5 处 -40µm 的台阶面靠"面积多样性"混了进来, 它们不是字,
                    # 补上去等于凭空加料。
                    if abs(off) > MAX_OFF_NOWIRE:
                        continue
                    if distinct_areas(cc) < max(3, 0.6 * len(cc)):
                        continue
                cands.append([B, n, d, hit, cc, reg, "字面"])
    # 同一处贴花会被线索1(内环)和线索2(字面)各报一次, 先按"字形内环指纹"去重;
    # 再去掉同平面内重叠的候选。不去重的话同一处会被擦两遍, 第二遍必然失败。
    cands.sort(key=lambda t: -t[0].Area)
    jobs = []
    for B, n, d, gl, rb, reg, kind in cands:
        j = Job()
        j.host, j.n, j.d = B, n, d
        j.u, j.v = _frame(n)
        j.glyphs, j.ribs, j.region, j.kind = list(gl), list(rb), reg, kind
        j.inflate = inflate
        jobs.append(j)
    # 去重: 同一平面上两个候选的字形内环有半数以上重合 -> 是同一处
    uniq = []
    for j in jobs:
        ks = set(_wkey(w) for w in j.glyphs)
        hit = None
        for q in uniq:
            if abs(q.n.dot(j.n) - 1) > 1e-5 or abs(q.d - j.d) > 0.01:
                continue
            qs = set(_wkey(w) for w in q.glyphs)
            if ks and qs and len(ks & qs) >= 0.5 * min(len(ks), len(qs)):
                hit = q
                break
        if hit is None:
            uniq.append(j)
        else:
            if len(j.glyphs) > len(hit.glyphs):
                hit.glyphs = j.glyphs + [w for w in hit.glyphs
                                         if _wkey(w) not in set(_wkey(x) for x in j.glyphs)]
            hit.ribs += [f for f in j.ribs if f.hashCode() not in
                         set(x.hashCode() for x in hit.ribs)]
    jobs = uniq
    # 合并同平面内重叠区域的候选
    merged = True
    while merged:
        merged = False
        for ii in range(len(jobs)):
            for kk in range(ii + 1, len(jobs)):
                a, b = jobs[ii], jobs[kk]
                if abs(a.n.dot(b.n) - 1) > 1e-5 or abs(a.d - b.d) > 0.01:
                    continue
                ra, rb_ = a.region, b.region
                ov = True
                for t in (0, 2, 4):        # 世界 bbox 三轴都要求有交集
                    if not (ra[t] <= rb_[t + 1] and ra[t + 1] >= rb_[t]):
                        ov = False
                        break
                if ov:
                    a.glyphs += b.glyphs
                    a.ribs += b.ribs
                    a.region = [min(ra[0], rb_[0]), max(ra[1], rb_[1]),
                                min(ra[2], rb_[2]), max(ra[3], rb_[3]),
                                min(ra[4], rb_[4]), max(ra[5], rb_[5])]
                    if b.host.Area > a.host.Area:
                        a.host = b.host
                    jobs.pop(kk)
                    merged = True
                    break
            if merged:
                break
    return jobs

def ultra_thin(cluster, lim=0.005, vmax=0.005):
    """1µm 级的薄片。真实结构件不存在 5µm 以下的壁厚, 所以哪怕它孤零零一个、
    凑不出"≥4 聚簇"这一条, 也仍然只能是贴上去的字模/logo 层。
    实测 WIFIM-SMD_ESP32-C3-MINI-1 的 EASYEDA 云朵 logo 就是这样: 单独一个
    1.38x1.01x0.001 的环状薄片(37 面), 和 12 个字母相隔 0.25mm, 被聚簇门限漏掉。"""
    for s in cluster:
        b = s.BoundBox
        dims = sorted([b.XLength, b.YLength, b.ZLength])
        if dims[0] > lim or s.Volume > vmax:
            return False
    return True


def detect_floating(solids):
    """SOD-882 型: 文字不是宿主面上的内环, 而是一簇独立小实体贴在宿主平面上。
    判据: 体积小 + 三个方向都薄 + 贴在大平面外侧 <=OFF_MAX + 至少 4 个聚在一起
          + 投影面积远小于宿主面。真实小零件(厚度 >0.06mm)会被排除。"""
    out = []
    small = []
    for i, s in enumerate(solids):
        b = s.BoundBox
        dims = sorted([b.XLength, b.YLength, b.ZLength])
        # dims[2]<=0.8 是"单个字母"的尺度上限; 整块 logo(实测云朵标 1.38x1.01x0.001)
        # 横向更大, 所以再给一条"超薄平板"通道: 厚度 <=5µm 的平板不论多大都算贴花。
        if (s.Volume <= 0.05 and dims[0] <= OFF_MAX and
                (dims[2] <= 0.8 or dims[0] <= 0.005)):
            small.append(i)
    if not small:
        return out
    for hi, s in enumerate(solids):
        if hi in small:
            continue
        min_host, gap, inflate = scales(s)
        for B in s.Faces:
            if not B.Surface.isPlanar() or B.Area < min_host:
                continue
            n = B.normalAt(0.3, 0.3)
            d = B.CenterOfMass.dot(n)
            bb = B.BoundBox
            hits, offs = [], {}
            for i in small:
                zb = solids[i].BoundBox
                c = solids[i].CenterOfMass
                off = c.dot(n) - d
                if not (1e-7 < off <= OFF_MAX):
                    continue
                if not bb_in(zb, [bb.XMin, bb.XMax, bb.YMin, bb.YMax, -1e18, 1e18], 0.02):
                    continue
                hits.append(solids[i])
                offs[i] = off + 0.5 * min(zb.XLength, zb.YLength, zb.ZLength)
            for c in clust(hits, gap):
                if len(c) < 4 and not ultra_thin(c):
                    continue
                reg = bb_reg(c)
                comp = (abs(n.x), abs(n.y), abs(n.z))
                ax = comp.index(max(comp))
                exts = [reg[2*i+1] - reg[2*i] for i in range(3)]
                vals = [e for i, e in enumerate(exts) if i != ax]
                area = max(vals[0], 1e-9) * max(vals[1], 1e-9)
                # 这里不能要求"文字只占宿主面一小块": 侧壁上的字(实测
                # LED-SMD_4P-L1.6-W1.5-TL 的字刻在 1.62x0.28 的窄侧壁上)必然
                # 占掉大半个面, 用 30% 的门槛会把整层字漏掉。判"是不是字"靠的是
                # 这些小实体本身又薄又轻(dims[0]<=60µm, 体积<=0.05mm3), 不是靠占比;
                # 只要别把整个面盖满就动手。
                if area > 0.90 * B.Area:
                    continue
                j = Job()
                j.host, j.n, j.d = B, n, d
                j.glyphs, j.ribs = [], []
                j.region, j.kind, j.inflate = reg, "贴片实体", inflate
                ids = set(id(x) for x in c)
                j.ids = ids
                j.sidx = [i for i in small if id(solids[i]) in ids]
                j.offs = [offs[i] for i in small if id(solids[i]) in ids]
                j.small_vol = sum(solids[i].Volume for i in small if id(solids[i]) in ids)
                # 同一条窄壁的两侧(或共面的两段)会各报一次, 同一批小实体只留一次
                if any(getattr(q, "ids", None) == ids for q in out):
                    continue
                out.append(j)
    return out

def clean_floating(sh, jobs, tag=""):
    """贴片实体文字(D 型): 这些字本来就是**独立的实体**, 直接从模型里摘掉即可。

    早期版本是拿一块薄板去 cut —— 薄板与壁面相切那一圈会把壁面切成碎片, 留下
    一圈矩形接缝(实测 LED-SMD_4P-L1.6-W1.5-TL 的侧壁就是这样), 还得再归并一次;
    而归并又会把配色小片合并掉。既然是独立实体, 摘掉最干净, 也不产生任何新面。"""
    drop = set()
    for j in jobs:
        drop |= set(getattr(j, "sidx", []))
    if not drop:
        return sh
    keep = [sd for i, sd in enumerate(sh.Solids) if i not in drop]
    if not keep:
        print("    [%s] 全部实体都被判为贴片, 放弃" % tag)
        return sh
    dvol = sum(sh.Solids[i].Volume for i in drop)
    ns = keep[0] if len(keep) == 1 else Part.makeCompound(keep)
    print("    摘掉 %d 个贴片实体: 去料 %.6f mm3, 剩余实体 %d 个"
          % (len(drop), dvol, len(keep)))
    return ns

def slab(region, n, d, off0, off1):
    """沿 n 方向从 off0 到 off1 的薄板, 区域由世界 bbox 投影到平面内确定。
    在平面局部坐标系里造盒子, 所以倾斜平面也能贴合(小器件的侧壁常带 3~5 度斜度)。"""
    import FreeCAD
    if abs(n.Length - 1) > 1e-9:
        n = n.normalize()
    ref = Vector(1, 0, 0) if abs(n.x) < 0.9 else Vector(0, 1, 0)
    u = ref - n * n.dot(ref)
    if u.Length < 1e-9:
        return None
    u.normalize()
    v = n.cross(u)
    v.normalize()
    pts = []
    for x in (region[0], region[1]):
        for y in (region[2], region[3]):
            for z in (region[4], region[5]):
                p = Vector(x, y, z)
                pts.append((p.dot(u), p.dot(v)))
    u0 = min(t[0] for t in pts); u1 = max(t[0] for t in pts)
    v0 = min(t[1] for t in pts); v1 = max(t[1] for t in pts)
    du, dv, th = u1 - u0, v1 - v0, off1 - off0
    if du <= 1e-9 or dv <= 1e-9 or th <= 1e-9:
        return None
    box = Part.makeBox(du, dv, th)
    o = u * u0 + v * v0 + n * (d + off0)
    # 显式正交基: 局部 x->u, y->v, z->n。用 Placement(Rotation) 时轴向不确定,
    # 板会被转到别处(实测切不到任何东西)。
    m = FreeCAD.Matrix()
    m.A11, m.A12, m.A13, m.A14 = u.x, v.x, n.x, o.x
    m.A21, m.A22, m.A23, m.A24 = u.y, v.y, n.y, o.y
    m.A31, m.A32, m.A33, m.A34 = u.z, v.z, n.z, o.z
    box.transformShape(m)
    return box

def _wkey(w):
    """环的指纹: 世界 bbox 取到 0.1µm。同一个环在宿主面和岛面上是同一条边, bbox 必然相同。"""
    b = w.BoundBox
    return (round(b.XMin, 5), round(b.XMax, 5), round(b.YMin, 5),
            round(b.YMax, 5), round(b.ZMin, 5), round(b.ZMax, 5))


def drop_inner_wires(sd, j, tag=""):
    """共面型(C): 字面与宿主面严格齐平, 体积为 0, 削不动也补不动。
    这纯粹是拓扑问题: 宿主面上有若干"字形内环", 环内各躺着一块齐平的岛面。
    做法 = 把这些内环从宿主面里去掉(用剩下的环重建面) + 删掉恰好被这些内环框住的岛面。
    关键约束: 只删"外环指纹命中被删内环"的岛面。同平面上往往还躺着焊盘/散热盘
    (实测 TDFN-8 有 9 块 0.093mm2 的焊盘面与宿主面同平面), 删错一块 shell 就漏,
    这也是之前"重组后不闭合"的真正原因。"""
    inf = getattr(j, "inflate", INFLATE)
    reg = [j.region[0] - inf, j.region[1] + inf, j.region[2] - inf,
           j.region[3] + inf, -1e18, 1e18]
    best, best_hit = None, 0
    for f in sd.Faces:
        if not f.Surface.isPlanar():
            continue
        try:
            n = f.normalAt(0.3, 0.3)
        except Exception:
            continue
        if abs(abs(n.dot(j.n)) - 1) > 1e-4:
            continue
        if abs(f.CenterOfMass.dot(j.n) - j.d) > PLANAR_TOL:
            continue
        hit = sum(1 for w in f.Wires
                  if not w.isSame(f.OuterWire) and bb_in(w.BoundBox, reg, 1e-3))
        if hit > best_hit or (hit == best_hit and best is not None and f.Area > best.Area):
            best, best_hit = f, hit
    if best is None or best_hit == 0:
        return None, 0
    keep, dropw = [best.OuterWire], []      # Part.Face 要求外环排第一
    for w in best.Wires:
        if w.isSame(best.OuterWire):
            continue
        if bb_in(w.BoundBox, reg, 1e-3):
            dropw.append(w)
        else:
            keep.append(w)
    if not dropw:
        return None, 0
    try:
        nf = Part.Face(keep)
        # 重建面的法向可能翻了个个儿, 方向不一致 shell 就不闭合
        try:
            if nf.normalAt(0.3, 0.3).dot(j.n) < 0:
                nf.reverse()
        except Exception:
            pass
    except Exception as e:
        print("    [%s] 重建宿主面失败: %s" % (tag, e))
        return None, 0
    kw = set(_wkey(w) for w in dropw)
    faces, nd = [], 0
    for f in sd.Faces:
        if f.isSame(best):
            faces.append(nf)
            continue
        if f.Surface.isPlanar() and _wkey(f.OuterWire) in kw:
            nd += 1                          # 这块岛面正是被删掉的某个内环围住的
            continue
        faces.append(f)
    try:
        ns = Part.makeSolid(Part.makeShell(faces))
    except Exception as e:
        print("    [%s] 重组实体失败: %s" % (tag, e))
        return None, 0
    if not (ns.isValid() and ns.isClosed()):
        print("    [%s] 拓扑重建后不闭合(valid=%s closed=%s), 放弃"
              % (tag, ns.isValid(), ns.isClosed()))
        return None, 0
    return ns, nd


def _bbv(bb):
    """包围盒 -> [(min,max)]*3"""
    return [(bb.XMin, bb.XMax), (bb.YMin, bb.YMax), (bb.ZMin, bb.ZMax)]


def _normal_at(f):
    """取一个平面面的法向(normalAt 在落到孔里的参数点会抛异常, 多点采样)。"""
    if not f.Surface.isPlanar():
        return None
    for u, v in ((0.3, 0.3), (0.5, 0.5), (0.1, 0.1), (0.7, 0.7), (0.9, 0.9),
                 (0.2, 0.8), (0.8, 0.2)):
        try:
            fn = f.normalAt(u, v)
            L = fn.Length
            if L > 1e-9:
                # FreeCAD 的 Vector 只有原地 normalize(), 没有 normalized()
                fn.normalize()
                return fn
        except Exception:
            continue
    return None


def _face_normal_along(f, n):
    """面法向是否与 n 平行(同向或反向)。"""
    fn = _normal_at(f)
    return fn is not None and abs(abs(fn.dot(n)) - 1) <= 1e-4


def _flip(f):
    """面的反向副本"""
    try:
        g = f.copy()
        g.reverse()
        return g
    except Exception:
        return f


def erase_patch(sd, j, tag=""):
    """纯拓扑擦除贴花: 删掉贴花自己的面, 再用"去掉字形内环"的宿主面顶上。

    ⚠ 为什么不用布尔运算(实测, 不是推测):
       OCCT 的布尔只要**真的与实体相交**就会重建整个实体, 重建过程会把
       "用来画颜色的共面小片"合并掉。实测 CONN-TH_2P-P2.00 一刀下去
       335 面 -> 133 面, 体积只差 0.0036 mm³(= 字的体积), 说明面是被合并不是被删;
       而拿一个碰不到模型的远处立方体去 cut, 面数 335 一个不少 —— 所以是"相交导致的
       重建", 不是布尔本身。
       后果: 218 个 (0.25,0.25,0.25) 面全并进 (0.10,0.10,0.10), 三种颜色只剩两种,
       打开就是"变暗沉、单色"。这类模型的配色本来就是靠**逐面小片**画的,
       合并即等于毁色。
       顺带: 薄板与宿主面相切那一圈会把平面切成碎片, 还会留矩形接缝 —— 一并没了。
    做法:
       1. 定位宿主面(同平面、内环与 j.glyphs 对得上的那个);
       2. 删掉"平面内 bbox 落在某个字形内环里 + 法向偏移在带内 + 面积够小"的面
          (凸起型的字面与侧壁、凹刻型的坑底与坑壁、共面型的岛面都在这个集合里);
       3. 宿主面用剩下的环重建(丢掉字形内环) -> 贴花位置变成一块完整的平面;
       4. 重组实体, 不闭合就放弃(交给调用方)。
    """
    n, d = j.n, j.d
    u, v = getattr(j, "u", None), getattr(j, "v", None)
    if u is None:
        u, v = _frame(n)

    gkeys = set(_wkey(w) for w in j.glyphs)
    if not gkeys:
        if os.environ.get("STRIP_DBG"):
            print("       [erase] 没有字形内环, 不适用")
        return None, 0

    # 1) 宿主面: 同平面内"内环命中字形"最多的那个
    best, besthit = None, 0
    for f in sd.Faces:
        if not _face_normal_along(f, n):
            continue
        if abs(f.CenterOfMass.dot(n) - d) > PLANAR_TOL:
            continue
        hit = sum(1 for w in f.Wires if _wkey(w) in gkeys)
        if hit > besthit or (hit == besthit and hit and f.Area > best.Area):
            best, besthit = f, hit
    if best is None or besthit == 0:
        if os.environ.get("STRIP_DBG"):
            print("       [erase] 当前实体里找不到带字形内环的宿主面")
        return None, 0

    boxes = []
    for w in best.Wires:
        if _wkey(w) in gkeys:
            b2 = _bb2(w, u, v)
            if b2 is not None:
                boxes.append(b2)

    ob = getattr(j, "offband", None)
    lim = min(OFF_MAX + 0.01, 1.6 * abs(ob) + 2e-4) if ob else OFF_MAX + 0.01
    als = [wire_area(w) for w in j.glyphs]
    alim = 4.0 * max(als) if als else 1e9

    # 2) 要删的面: 平面内 bbox 落在某个字形内环里 + 法向偏移在带内 + 面积够小
    #    (凸起型的字面与侧壁、凹刻型的坑底与坑壁、共面型的岛面都在这个集合里)
    drop_h = set()
    ndel = 0
    for f in sd.Faces:
        if f.isSame(best):
            continue
        if abs(f.CenterOfMass.dot(n) - d) > lim:
            continue
        if f.Area > alim:
            continue
        fb2 = _bb2(f, u, v)
        if fb2 is None:
            continue
        inside = False
        for gb in boxes:
            if (fb2[0] >= gb[0] - 5e-3 and fb2[1] <= gb[1] + 5e-3 and
                    fb2[2] >= gb[2] - 5e-3 and fb2[3] <= gb[3] + 5e-3):
                inside = True
                break
        if inside:
            drop_h.add(f.hashCode())
            ndel += 1
    if ndel == 0:
        if os.environ.get("STRIP_DBG"):
            print("       [erase] 宿主面找到了, 但没有面落在字形内环里(lim=%.5f alim=%.5f 字形框=%d)"
                  % (lim, alim, len(boxes)))
        return None, 0

    # 3) 重建宿主面: 外环排第一, 丢掉字形内环, 其它内环(真孔)保留
    keep, dropw = [best.OuterWire], []
    for w in best.Wires:
        if w.isSame(best.OuterWire):
            continue
        if _wkey(w) in gkeys:
            dropw.append(w)
        else:
            keep.append(w)
    if not dropw:
        return None, 0
    try:
        nf = Part.Face(keep)
        if not nf.isValid():
            print("    [%s] 重建宿主面无效, 放弃拓扑擦除" % tag)
            return None, 0
    except Exception as e:
        print("    [%s] 重建宿主面失败: %s" % (tag, e))
        return None, 0

    rest = [f for f in sd.Faces if not f.isSame(best) and f.hashCode() not in drop_h]

    def assemble(face):
        try:
            s2 = Part.makeSolid(Part.makeShell([face] + rest))
        except Exception:
            return None
        return s2 if (s2.isValid() and s2.isClosed()) else None

    # 朝向别靠 normalAt 采样去猜(宿主面常常一堆孔, 采样点可能全落孔里)。
    # 两个朝向都装一遍, 取"有效且体积最接近原实体"的那个 —— 装反了体积会离谱。
    cands = [x for x in (assemble(nf), assemble(_flip(nf))) if x is not None]
    if not cands:
        print("    [%s] 拓扑擦除后不闭合, 放弃" % tag)
        return None, 0
    v0 = vol(sd)
    ns = min(cands, key=lambda x: abs(vol(x) - v0))
    if len(cands) == 1 and abs(vol(ns) - v0) > 1e-3 * max(1.0, abs(v0)):
        print("    [%s] 只有一个朝向能闭合但体积差太多(%.6f), 放弃"
              % (tag, vol(ns) - v0))
        return None, 0
    if os.environ.get("STRIP_DBG"):
        print("       [erase] 原 %d 面, 删 %d 面 + 换 1 个宿主面 -> %d 面 (dV=%+.6f)"
              % (len(sd.Faces), ndel, len(ns.Faces), vol(ns) - v0))
    return ns, len(dropw)


def act(s, box, sign, cap):
    """sign=+1 削(凸起), -1 补(凹刻)。返回 (新实体, 变化量, 模式), 失败返回 (None,0,-1)。

    两道保险:
      1. 预期值校验 —— 去/补的量必须等于"板与实体的交集体积"(削)或
         "板减去实体的体积"(补)。OCCT 的布尔会**部分失败**(实测 SOD-923 的板
         明明盖住了云 logo, cut 只切掉 1/3 的字形, 体积守卫只看上界就放过了),
         有了预期值才判得出来。
      2. 精确工具 —— 整块板判不过就改用 板∩实体 / 板−实体 当刀具, 体积就等于
         字的体积, 不可能切过头。
    GProp 的 Volume 在碎拓扑上偶尔算错, 所以两道都不过时再用网格积分复核一次。

    ⚠ 一切"探测"必须在副本上做。OCCT 的布尔结果会原样复用入参中未被改动的面
    (同一个 TShape), 而 tessellate() 会把三角剖分**写进那个 TShape**; 之后再拿
    同一个实体做布尔, BOP 会走"已有三角剖分"的快速路径, 结果就变了:
        实测 SOD-923  未先网格化 -> cut 后面数 102, 归并后 82, 残留 0
                      先网格化一次 -> cut 后面数 138, 归并后 119, 残留 1
    这就是"预期值校验"自己把自己搞坏的那条路。"""
    exp = None
    for mode in (0, 1):
        try:
            if mode == 0:
                tool = box
            else:
                tool = s.common(box) if sign > 0 else box.cut(s)
            if tool is None or vol(tool) <= 0:
                continue
            s2 = s.cut(tool) if sign > 0 else s.fuse(tool)
        except Exception:
            continue
        if not (s2.isValid() and s2.isClosed()):
            continue
        dv = (vol(s) - vol(s2)) if sign > 0 else (vol(s2) - vol(s))
        if exp is None:
            try:                     # 副本, 见上面 ⚠
                exp = (vol(s.copy().common(box.copy())) if sign > 0
                       else vol(box.copy().cut(s.copy())))
            except Exception:
                exp = 0.0
        if os.environ.get("STRIP_DBG"):
            try:
                mexp = meshvol(s.copy().common(box.copy())) if sign > 0 else -1.0
            except Exception:
                mexp = -2.0
            print("       [dbg] mode=%d dv=%.8f exp=%.8f cap=%.8f meshexp=%.8f"
                  % (mode, dv, exp, cap, mexp))
        okexp = (exp <= 1e-12) or (0.5 * exp <= dv <= 1.5 * exp)
        if 0 < dv <= cap and okexp:
            return s2, dv, mode
        # 网格复核也只碰副本 —— 否则复核本身就会污染下一次布尔
        try:
            dm = meshvol(s.copy())
            dn = meshvol(s2.copy())
            dv2 = (dm - dn) if sign > 0 else (dn - dm)
        except Exception:
            continue
        okexp = (exp <= 1e-12) or (0.5 * exp <= dv2 <= 1.5 * exp)
        if 0 < dv2 <= cap and okexp:
            return s2, dv2, mode + 2
    return None, 0.0, -1


def cut_clean(s, j, box, cap, tries=3):
    """反复切, 直到这一层真的干净为止。
    OCCT 的布尔对"与目标面严格相切"的刀具会偶发部分失败 —— 实测 SOD-923: 同一个
    实体、同一块板, 一次运行把云 logo 切掉了, 另一次没切掉(dv 却都在预期范围内,
    所以体积守卫看不出来)。只能多试几次再看残留。返回 (结果, 去料量, 是否干净)。"""
    spare = None
    for _ in range(tries):
        s2, dv, mode = act(s, box, +1, cap)
        if s2 is None:
            continue
        if not band_faces(s2, j):
            return s2, dv, True
        spare = (s2, dv, False)
    return spare if spare else (None, 0.0, False)


def _plane_of(f):
    try:
        if not f.Surface.isPlanar():
            return None
        n = f.normalAt(0.5, 0.5)
        if n.Length < 1e-9:
            return None
        n.normalize()
        c = f.CenterOfMass
        return n, n.x * c.x + n.y * c.y + n.z * c.z
    except Exception:
        return None


def unify_patch(sd, j, tag=""):
    """布尔补/削之后, 把**宿主平面内、文字区附近**的碎面合并成一张。

    布尔只要与实体相交就会把宿主面上与刀口相邻的共面小片重新分割, 于是平面上留下
    一圈字形轮廓接缝 —— 几何已经是平的、颜色也对了, 但在显示棱线的查看器里
    "LCEDA" 的轮廓仍然是一圈细线, 看起来像没删干净。
    这里只合并"与 host 共面 + 落在文字区附近"的那几张, 不碰模型其它地方
    (绝不做全局 removeSplitter —— 那会把逐面配色小片并掉)。
    """
    ph = _plane_of(j.host)
    if ph is None:
        return sd, 0
    n, d = ph
    inf = getattr(j, "inflate", INFLATE) + 0.02
    reg = (j.region[0] - inf, j.region[1] + inf,
           j.region[2] - inf, j.region[3] + inf)
    grp = []
    for f in sd.Faces:
        pf = _plane_of(f)
        if pf is None:
            continue
        n2, d2 = pf
        if n2.dot(n) < 0.9995 or abs(d2 - d) > 2e-3:
            continue
        b = f.BoundBox
        if b.XMax < reg[0] or b.XMin > reg[1] or b.YMax < reg[2] or b.YMin > reg[3]:
            continue
        grp.append(f)
    if len(grp) < 2:
        return sd, 0
    a0 = sum(g.Area for g in grp)
    try:
        u = grp[0].fuse(grp[1:])
        u = u.removeSplitter()
    except Exception:
        return sd, 0
    fs = list(u.Faces) if u else []
    if len(fs) != 1:
        return sd, 0
    if abs(fs[0].Area - a0) > max(1e-5, 1e-4 * a0):
        return sd, 0
    hs = set(g.hashCode() for g in grp)
    rest = [f for f in sd.Faces if f.hashCode() not in hs]
    v0 = vol(sd)
    deg0 = sum(1 for f in sd.Faces if f.Area < 1e-6)
    best = None
    for face in (fs[0], _flip(fs[0])):
        try:
            s2 = Part.makeSolid(Part.makeShell(rest + [face]))
        except Exception:
            continue
        if s2.isValid() and s2.isClosed():
            if sum(1 for f in s2.Faces if f.Area < 1e-6) > deg0:
                continue            # 合并产生了退化碎面, 宁可不合
            dv = abs(vol(s2) - v0)
            if best is None or dv < best[0]:
                best = (dv, s2)
    if best is None or best[0] > max(1e-5, 1e-6 * abs(v0)):
        return sd, 0
    print("       (合并宿主平面碎面 %d 张 -> 1 张, 消掉接缝)" % len(grp))
    return best[1], len(grp)


def heal_region(s, j, tag):
    """布尔回退之后的收尾: 把区域内残留的字形内环从宿主面上摘掉并重建该面。
    不做全局 removeSplitter —— 那个会把整个模型里"用来画颜色的共面小片"合并掉
    (实测 335 面塌到 111 面), 只重建这一个面, 其它面原样不动。"""
    ns, nh = drop_inner_wires(s, j, tag)
    if ns is None:
        return s
    # 一次可能只收掉一个面, 收完还会冒出新的边 -> 反复收几次
    for _ in range(3):
        ns2, nh2 = drop_inner_wires(ns, j, tag)
        if ns2 is None:
            break
        ns, nh = ns2, nh + nh2
    print("       (收起残留内环 %d 个)" % nh)
    return ns


def clean_solid(sd, jobs, tag=""):
    s = sd
    flats = []
    for k, j in enumerate(jobs):
        n, d = j.n, j.d
        # 同一平面 60µm 内往往不止一层小面: 可能有 1µm 深的字, 也可能有 20µm 外的
        # 器件底面/台阶面。混在一起 h 就取到最大值, 会一刀切进实体(实测 SOD-882
        # 因此沿底面削掉 20µm、少了 0.0083mm3)。只认"正好盖住字形内环"最多的那一层。
        if len(j.ribs) > 1:
            bands = {}
            for f in j.ribs:
                bands.setdefault(round(f.CenterOfMass.dot(n) - d, 4), []).append(f)
            if len(bands) > 1:
                hw = [w for w in j.host.Wires if not w.isSame(j.host.OuterWire)]
                pick = max(bands.items(),
                           key=lambda kv: sum(1 for f in kv[1] if rib_matches_wire(n, f, hw)))
                j.ribs = pick[1]
        offs = [(f.CenterOfMass.dot(n) - d) for f in j.ribs]
        j.offband = (sum(offs) / len(offs)) if offs else None

        # ---- 首选: 纯拓扑擦除(不碰布尔, 配色与小面结构原样保留) ----
        ns, nd = erase_patch(s, j, "%s%d" % (tag, k + 1))
        if ns is not None:
            v0 = vol(s)
            s = ns
            print("    [%s%d] %s: 拓扑擦除(去字形内环 %d 个, 删贴花面, dV=%+.6f)"
                  % (tag, k + 1, j.kind, nd, vol(s) - v0))
            continue
        # ---- 兜底: 布尔(会在平面上留接缝、并可能合并配色小片) ----
        print("    [%s%d] %s: 拓扑擦除不可行, 退回布尔" % (tag, k + 1, j.kind))
        area = region_area(j)
        if offs and max(offs) > 1e-6:            # 字面在平面外侧 -> 削
            h = min(max(offs), OFF_MAX) + EPS
            box = slab(j.region, n, d, 0.0, h)
            if box is None:
                print("    [%s%d] 薄板构造失败, 跳过" % (tag, k+1)); continue
            s2, dv, ok = cut_clean(s, j, box, 0.6 * area * h)
            if s2 is None:
                print("    [%s%d] 凸起型: 去料异常, 回滚" % (tag, k+1)); continue
            s = s2
            note = ""
            if not ok:
                # 有些"字"是**零厚度的膜**(云 logo 常见): 它不占体积, 布尔切它有时
                # 会被保留下来。把板往下多扎 1.5 倍字高再扫一次 —— 这个深度比
                # 3D 打印精度还小一个量级, 装配和视觉上都等于没有。
                d2 = 1.5 * abs(j.offband or 0.001)
                box2 = slab(j.region, n, d, -d2, h)
                if box2 is not None:
                    s3, dv3, ok3 = cut_clean(s, j, box2, 0.6 * area * h + area * d2)
                    if s3 is not None:
                        s = s3
                        dv += dv3
                        note = ", 往材料里扎 %.4fmm 扫膜%s" % (d2, "" if ok3 else "(仍不净)")
            s = heal_region(s, j, "%s%d" % (tag, k + 1))
            s, _ = unify_patch(s, j, "%s%d" % (tag, k + 1))
            print("    [%s%d] 凸起型: 削 %.6f mm3 (字高 %.4f%s)"
                  % (tag, k+1, dv, h - EPS, note))
        elif offs and min(offs) < -1e-6:          # 字面在平面内侧 -> 补
            h = min(-min(offs), OFF_MAX) + EPS
            box = slab(j.region, n, d, -h, 0.0)
            if box is None:
                print("    [%s%d] 薄板构造失败, 跳过" % (tag, k+1)); continue
            s2, dv, mode = act(s, box, -1, 0.6 * area * h)
            if s2 is not None:
                s = heal_region(s2, j, "%s%d" % (tag, k + 1))
                s, _ = unify_patch(s, j, "%s%d" % (tag, k + 1))
                print("    [%s%d] 凹刻型: 补 %.6f mm3 (字深 %.4f%s)"
                      % (tag, k+1, dv, h - EPS,
                         (", 精确工具" if mode in (1, 3) else "")
                         + (", 网格复核" if mode >= 2 else "")))
            else:
                print("    [%s%d] 凹刻型: 补料异常, 回滚" % (tag, k+1))
        else:
            print("    [%s%d] 共面型: 稍后去掉字形内环" % (tag, k+1))
            flats.append((k, j))
    for k, j in flats:
        ns, nd = drop_inner_wires(s, j, "%s%d" % (tag, k + 1))
        if ns is not None:
            s = ns
            print("    [%s%d] 共面型: 拓扑重建成功, 去掉 %d 个字形内环" % (tag, k + 1, nd))
        else:
            print("    [%s%d] 共面型: 零厚度贴花, 无法在不动几何的前提下清除, 保持原样"
                  % (tag, k + 1))
    return s

def band_faces(sd, j):
    """这一层贴花(按字高定范围、按字形尺度定大小)还剩下的面 —— 残留判据的唯一来源。"""
    n, d = j.n, j.d
    inf = getattr(j, "inflate", INFLATE)
    reg = [j.region[0] - inf, j.region[1] + inf, j.region[2] - inf,
           j.region[3] + inf, -1e18, 1e18]
    ob = getattr(j, "offband", None)
    lim = min(OFF_MAX + 0.01, 1.6 * abs(ob) + 2e-4) if ob else OFF_MAX + 0.01
    als = [wire_area(w) for w in j.glyphs] or [f.Area for f in j.ribs]
    alim = 4.0 * max(als) if als else None
    out = []
    for f in sd.Faces:
        if not f.Surface.isPlanar():
            continue
        try:
            if abs(abs(f.normalAt(0.3, 0.3).dot(n)) - 1) > 1e-3:
                continue
        except Exception:
            continue
        if not (1e-7 < abs(f.CenterOfMass.dot(n) - d) <= lim):
            continue
        if alim is not None and f.Area > alim:
            continue
        if not bb_in(f.BoundBox, reg, 1e-6):
            continue
        out.append(f)
    return out


def audit(sd, jobs, tag=""):
    bad = 0
    for k, j in enumerate(jobs):
        n, d = j.n, j.d
        inf = getattr(j, "inflate", INFLATE)
        reg = [j.region[0] - inf, j.region[1] + inf, j.region[2] - inf,
               j.region[3] + inf, -1e18, 1e18]
        off = band_faces(sd, j)
        inner = 0
        for f in sd.Faces:
            if not f.Surface.isPlanar() or abs(f.CenterOfMass.dot(n) - d) > PLANAR_TOL:
                continue
            for w in f.Wires:
                if not w.isSame(f.OuterWire) and bb_in(w.BoundBox, reg, 1e-6):
                    inner += 1
        ok = (not off) and inner == 0
        if not ok:
            bad += 1
        print("    [%s%d] 复查: 平面外残面=%d 字形内环=%d %s"
              % (tag, k+1, len(off), inner, "OK 零残留" if ok else "<== 仍有残留"))
        if off:
            print("        残面: " + "; ".join(
                "off=%+.5f A=%.5f" % (f.CenterOfMass.dot(n) - d, f.Area)
                for f in off[:5]))
    return bad


def main():
    a = sys.argv[1:]
    paths = [x for x in a if x.lower().endswith((".step", ".stp"))]
    if not paths:
        print("用法: freecadcmd.exe strip_text.py <in.step> [out.step] [LIST]")
        return
    src = _norm_path(paths[0])
    dst = _norm_path(paths[1]) if len(paths) > 1 else \
        src.rsplit(".", 1)[0] + "_clean.step"
    listing = "LIST" in a
    t0 = time.time()
    sh = Part.Shape(); sh.read(src)
    v0 = sum(s.Volume for s in sh.Solids)
    m0 = meshvol(sh.copy())       # 副本: 见 act() 里的 ⚠, 网格化会改后续布尔
    nf0 = len(sh.Faces)
    print("=" * 96)
    print("输入 %s" % src)
    print("  solids=%d faces=%d vol=%.6f" % (len(sh.Solids), len(sh.Faces), v0))
    out, nj, all_jobs, nbad = [], 0, [], 0
    # 阶段 1: 贴在大平面上的独立小实体(SOD-882 型)
    fl = detect_floating(sh.Solids)
    if fl:
        print("  检出 %d 处贴片实体文字:" % len(fl))
        for k, j in enumerate(fl):
            print("     [F%d] 区域 X[%.3f,%.3f] Y[%.3f,%.3f] Z[%.4f,%.4f] n=(%.2f,%.2f,%.2f) 实体体积=%.6f"
                  % (k + 1, j.region[0], j.region[1], j.region[2], j.region[3],
                     j.region[4], j.region[5], j.n.x, j.n.y, j.n.z, j.small_vol))
        nj += len(fl)
        all_jobs += fl
        if not listing:
            v_before = vol(sh)
            sh = clean_floating(sh, fl, "F")
            print("  贴片实体削除后 solids=%d faces=%d vol=%.6f (dV=%+.6f)"
                  % (len(sh.Solids), len(sh.Faces), vol(sh), vol(sh) - v_before))
    for si, sd in enumerate(sh.Solids):
        jobs = detect(sd)
        nj += len(jobs)
        all_jobs += jobs
        print("  solid%d faces=%d -> 候选 %d 个" % (si, len(sd.Faces), len(jobs)))
        for k, j in enumerate(jobs):
            offs = [f.CenterOfMass.dot(j.n) - j.d for f in j.ribs]
            side = "-" if (offs and min(offs) < 0) else "+"
            print("     [%d] %s 宿主%.3fmm2 d=%.4f n=(%.0f,%.0f,%.0f) 内环=%d 字面=%d 侧=%s 区域 X[%.2f,%.2f] Y[%.2f,%.2f] Z[%.4f,%.4f]"
                  % (k+1, j.kind, j.host.Area, j.d, j.n.x, j.n.y, j.n.z,
                     len(j.glyphs), len(j.ribs), side,
                     j.region[0], j.region[1], j.region[2], j.region[3], j.region[4], j.region[5]))
        if listing or not jobs:
            out.append(sd); continue
        s2 = clean_solid(sd, jobs, tag="s%d." % si)
        print("     结果 valid=%s closed=%s faces=%d vol=%.6f (dV=%+.6f)"
              % (s2.isValid(), s2.isClosed(), len(s2.Faces), vol(s2), vol(s2) - vol(sd)))
        nbad += audit(s2, jobs, tag="s%d." % si)
        out.append(s2)
    if listing:
        print("\n[LIST] 共 %d 个候选" % nj); return
    if nj == 0:
        print("\n未检出候选, 未写出"); return
    res = out[0] if len(out) == 1 else Part.makeCompound(out)
    v1 = vol(res)
    print("\n合计 vol %.6f -> %.6f (dV=%+.6f) faces=%d" % (v0, v1, v1 - v0, len(res.Faces)))
    # 产品名沿用原模型: 优先原 STEP 的 PRODUCT 名, 其次 NAME= 参数, 最后文件主干
    name = None
    for x in a:
        if x.upper().startswith("NAME="):
            name = x.split("=", 1)[1].strip()
    if not name:
        name = src_product_name(src)
    if not name:
        name = os.path.splitext(os.path.basename(src))[0]
    print("[name] %s" % name)
    export_named(res, dst, name)
    colnote = "off" if "NOCOLOR" in a else "-"
    if "NOCOLOR" not in a:
        try:
            import colorize
            back = Part.Shape()
            back.read(dst)          # 读回: 面顺序 = 文件里 ADVANCED_FACE 的顺序
            cols, msg = colorize.build_color_map(src, back, all_jobs)
            if cols:
                ok, m2 = colorize.inject_colors(dst, cols)
                colnote = m2 if ok else "失败: " + m2
                print("  [color] %s" % colnote)
            else:
                print("  [color] %s" % msg)
        except Exception as e:
            print("  [color] 跳过: %s" % e)
    # GProp 的 Volume 在布尔后的碎拓扑上会算错(LED-SMD 上差了一个符号), 所以
    # 汇总里同时给网格积分的体积变化 —— 后者才是真实材料变化。
    print("[summ] cand=%d residue=%d faces=%d->%d dV=%+.6f dVmesh=%+.6f | %s"
          % (nj, nbad, nf0, len(res.Faces), v1 - v0, meshvol(res) - m0, colnote))
    print("[done] %s (%.1fs)" % (dst, time.time() - t0))

# 顶层兜底: 任何未预期的异常都要打印完整 traceback 并给出非 0 退出码, 而不是让
# freecadcmd 只丢一句 "Application unexpectedly terminated"。
def _run():
    try:
        main()
        return 0
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        print("[FAIL] 处理失败, 输出文件未生成 (exit 1)")
        return 1

_rc = _run()
try:
    sys.stdout.flush()
    sys.stderr.flush()
except Exception:
    pass
# 必须用 SystemExit 收尾, 不能让脚本"自然结束":
# 实测 freecadcmd 在命令行里带非 ASCII 参数时, 收尾路径会自己抛一个异常, 于是
# 在 C++ 侧打印 "Application unexpectedly terminated" 并以非 0 退出 —— 明明已经
# 处理成功, 用户却以为崩了。走 SystemExit 这条路径是干净的(实测 0 退出、无报错)。
sys.exit(_rc)
