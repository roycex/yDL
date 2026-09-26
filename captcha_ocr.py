# -*- coding: utf-8 -*-
"""yifile.com 验证码识别模块（替代 pytesser3）

流程：RGB 饱和度/亮度双判据二值化 -> 连通域去噪 -> 连通域 x 区间分组分割
     （重叠归组/最小间隙合并/平滑谷底切分）-> 保持纵横比归一化(24 高) ->
     与内嵌模板库最近邻匹配。
纯 Python 实现（numpy + PIL），无外部依赖，可被 PyInstaller 直接打包。
"""
import base64
import zlib
from collections import deque

import numpy as np
from PIL import Image

GW = 16   # 归一化画布宽
GH = 24   # 归一化画布高

# ---------- 模板库（懒加载） ----------
_BANK = None      # {char: (templates_float32, dts_float32)}
_DT_CACHE = {}

def _distance_transform(fg):
    """两遍扫描 Chamfer 距离变换：每个像素到最近前景像素的距离（3-4 权重/3）"""
    h, w = fg.shape
    INF = 1e9
    dt = np.where(fg > 0.5, 0.0, INF).astype(np.float32)
    for y in range(h):
        for x in range(w):
            v = dt[y, x]
            if x > 0:
                v = min(v, dt[y, x - 1] + 1.0)
            if y > 0:
                v = min(v, dt[y - 1, x] + 1.0)
                if x > 0:
                    v = min(v, dt[y - 1, x - 1] + 4.0 / 3.0)
                if x < w - 1:
                    v = min(v, dt[y - 1, x + 1] + 4.0 / 3.0)
            dt[y, x] = v
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            v = dt[y, x]
            if x < w - 1:
                v = min(v, dt[y, x + 1] + 1.0)
            if y < h - 1:
                v = min(v, dt[y + 1, x] + 1.0)
                if x < w - 1:
                    v = min(v, dt[y + 1, x + 1] + 4.0 / 3.0)
                if x > 0:
                    v = min(v, dt[y + 1, x - 1] + 4.0 / 3.0)
            dt[y, x] = v
    return dt

def _chamfer_score(q_fg, q_dt, t_arr, t_dt, t_mask):
    """对称 Chamfer 距离：查询前景点到模板前景的平均距离 + 反向。越小越相似"""
    t2 = t_arr.reshape(GH, GW) if t_arr.ndim == 1 else t_arr
    qm = q_fg > 0.5
    tm = t_mask if t_mask is not None else (t2 > 0.5)
    if not qm.any() or not tm.any():
        return 1e9
    d1 = float(t_dt[qm].mean())   # 查询前景 -> 模板前景
    d2 = float(q_dt[tm].mean())   # 模板前景 -> 查询前景
    return (d1 + d2) / 2.0

def _get_bank():
    global _BANK
    if _BANK is None:
        from captcha_templates import DATA_B64, HEADER
        raw = zlib.decompress(base64.b64decode("".join(DATA_B64)))
        parts = HEADER.split("|")
        chars, counts = [], []
        for item in parts[1].split(","):
            ch, cnt = item.split(":")
            chars.append(ch)
            counts.append(int(cnt))
        bank, off = {}, 0
        gsize = GW * GH
        for ch, cnt in zip(chars, counts):
            block = np.frombuffer(raw[off:off + cnt * gsize], dtype=np.uint8)
            arrs = block.reshape(cnt, gsize).astype(np.float32) / 255.0
            arrs2d = [a.reshape(GH, GW) for a in arrs]
            dts = np.stack([_distance_transform(a) for a in arrs2d])
            masks = [a > 0.5 for a in arrs2d]
            bank[ch] = (arrs2d, dts, masks)
            off += cnt * gsize
        _BANK = bank
    return _BANK

# ---------- 图像处理 ----------
def binarize(pil_image):
    a = np.asarray(pil_image.convert("RGB")).astype(np.int32)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = (r * 299 + g * 587 + b * 114) // 1000
    sat = a.max(axis=2) - a.min(axis=2)
    fg = (sat > 60) | (lum < 175)
    fg[0, :] = fg[-1, :] = False
    fg[:, 0] = fg[:, -1] = False
    return fg

def remove_small_components(fg, min_px=8):
    h, w = fg.shape
    visited = np.zeros_like(fg, dtype=bool)
    out = np.zeros_like(fg)
    for y in range(h):
        for x in range(w):
            if fg[y, x] and not visited[y, x]:
                comp = []
                q = deque([(y, x)])
                visited[y, x] = True
                while q:
                    cy, cx = q.popleft()
                    comp.append((cy, cx))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and fg[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                q.append((ny, nx))
                if len(comp) >= min_px:
                    for cy, cx in comp:
                        out[cy, cx] = True
    return out

def _connected_components(fg):
    """返回每个连通分量的 (x_min, x_max+1)"""
    h, w = fg.shape
    visited = np.zeros_like(fg, dtype=bool)
    comps = []
    for y in range(h):
        for x in range(w):
            if fg[y, x] and not visited[y, x]:
                q = deque([(y, x)])
                visited[y, x] = True
                x0, x1 = x, x
                while q:
                    cy, cx = q.popleft()
                    if cx < x0: x0 = cx
                    if cx + 1 > x1: x1 = cx + 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and fg[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                q.append((ny, nx))
                comps.append([x0, x1])
    comps.sort()
    return comps

def _split_group_n(fg, s, e, n_parts):
    """把 [s,e) 切成 n_parts 段：取平滑列投影最深的 n_parts-1 个谷底（间隔>=4px）"""
    inner = fg[:, s:e].sum(axis=0).astype(float)
    k = np.array([1.0, 2.0, 1.0])
    sm = np.convolve(inner, k, mode="same")
    width = e - s
    lo, hi = max(2, int(width * 0.18)), width - max(2, int(width * 0.18))
    if hi - lo < 1:
        return None
    # 找局部极小值
    cands = []
    for x in range(lo, hi):
        if sm[x] <= sm[x - 1] and sm[x] <= sm[x + 1]:
            cands.append((sm[x], x))
    if not cands:
        cands = [(sm[int((lo + hi) / 2)], int((lo + hi) / 2))]
    cands.sort()
    cuts = []
    for _, x in cands:
        if all(abs(x - c) >= 4 for c in cuts):
            cuts.append(x)
        if len(cuts) == n_parts - 1:
            break
    if len(cuts) < n_parts - 1:
        return None
    return sorted(cuts)

def _glyph_cost(fg, s, e, bank):
    """片段 [s,e) 归一化后与模板库的最小匹配代价（chamfer + L1 组合）"""
    g = fg[:, s:e]
    if g.sum() < 6:
        return 1e9
    q = normalize_glyph(g)
    qm = q > 0.5
    if not qm.any():
        return 1e9
    q_dt = _distance_transform(qm)
    best = 1e9
    for ch, (arrs, dts, masks) in bank.items():
        for t_arr, t_dt, t_mask in zip(arrs, dts, masks):
            d_chamfer = _chamfer_score(q, q_dt, t_arr, t_dt, t_mask)
            d_l1 = float(np.abs(t_arr - q.ravel()).mean())
            d = d_chamfer + d_l1
            if d < best:
                best = d
    return best

def _dp_split(fg, s, e, n_parts, bank):
    """DP 切分：在 [s,e) 内选 n_parts-1 个切点，使各段模板匹配代价之和最小"""
    width = e - s
    if width < n_parts * 6:
        return None
    INF = 1e18
    # dp[j][x]: 前 x 列切成 j 段的最小代价
    dp = [[INF] * (width + 1) for _ in range(n_parts + 1)]
    cut = [[-1] * (width + 1) for _ in range(n_parts + 1)]
    dp[0][0] = 0.0
    for j in range(1, n_parts + 1):
        for x in range(6 * j, width + 1):
            for a in range(max(0, x - 14), x - 6 + 1):
                if dp[j - 1][a] >= INF:
                    continue
                c = _glyph_cost(fg, s + a, s + x, bank)
                if dp[j - 1][a] + c < dp[j][x]:
                    dp[j][x] = dp[j - 1][a] + c
                    cut[j][x] = a
    if dp[n_parts][width] >= INF:
        return None
    # 回溯切点（starts 含首端 0，去掉后即为内部边界）
    cuts, x = [], width
    j = n_parts
    while j > 0:
        a = cut[j][x]
        cuts.append(a)
        x = a
        j -= 1
    return sorted(cuts[:-1])

def segment4(fg):
    """连通域分组 -> 重叠归组 -> 数量修正 -> 恰好4个字形；失败返回 None"""
    comps = _connected_components(fg)
    if not comps:
        return None
    # 1) x 区间重叠/相接的分量归为一组
    groups = [list(comps[0])]
    for x0, x1 in comps[1:]:
        if x0 <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], x1)
        else:
            groups.append([x0, x1])
    # 2) 组数 > 4：合并 x 间隙最小的相邻组
    while len(groups) > 4:
        gaps = [groups[i + 1][0] - groups[i][1] for i in range(len(groups) - 1)]
        k = int(np.argmin(gaps))
        groups[k][1] = groups[k + 1][1]
        del groups[k + 1]
    # 3) 组数 < 4：优先 DP 切分（识别驱动），失败退回谷底切分
    guard = 0
    while len(groups) < 4 and guard < 8:
        guard += 1
        widths = [g[1] - g[0] for g in groups]
        k = int(np.argmax(widths))
        s, e = groups[k]
        n_parts = int(round((e - s) / 10.5))
        n_parts = max(2, min(n_parts, 4 - len(groups) + 1))
        if e - s < 12:
            break
        cuts = None
        try:
            cuts = _dp_split(fg, s, e, n_parts, _get_bank())
        except Exception:
            cuts = None
        if cuts is None:
            cuts = _split_group_n(fg, s, e, n_parts)
        if cuts is None:
            break
        bounds = [s] + [s + c for c in cuts] + [e]
        new_pieces = [[bounds[j], bounds[j + 1]] for j in range(len(bounds) - 1)]
        groups[k:k + 1] = new_pieces
    if len(groups) != 4:
        return None
    return [fg[:, s:e] for s, e in groups]

def normalize_glyph(glyph):
    """保持纵横比：高度缩放到 GH，宽度等比缩放后居中放到 GW 画布"""
    h, w = glyph.shape
    if h == 0 or w == 0:
        return np.zeros((GH, GW), dtype=np.float32)
    new_w = max(1, min(GW, int(round(w * GH / h))))
    im = Image.fromarray((glyph * 255).astype(np.uint8)).resize((new_w, GH), Image.LANCZOS)
    canvas = np.zeros((GH, GW), dtype=np.float32)
    x0 = (GW - new_w) // 2
    canvas[:, x0:x0 + new_w] = np.asarray(im).astype(np.float32) / 255.0
    return canvas

# ---------- 对外接口 ----------
def recognize(pil_image):
    """识别验证码，返回 4 位大写字符串；失败返回 ''"""
    try:
        fg = remove_small_components(binarize(pil_image))
        glyphs = segment4(fg)
        if glyphs is None:
            return ""
        bank = _get_bank()
        code = []
        for g in glyphs:
            q = normalize_glyph(g)
            q_fg_bool = q > 0.5
            q_dt = _distance_transform(q_fg_bool)
            best_ch, best_d = "", 1e9
            for ch, (arrs, dts, masks) in bank.items():
                for t_arr, t_dt, t_mask in zip(arrs, dts, masks):
                    d_c = _chamfer_score(q, q_dt, t_arr, t_dt, t_mask)
                    d_l1 = float(np.abs(t_arr.ravel() - q.ravel()).mean())
                    d = d_c + d_l1
                    if d < best_d:
                        best_ch, best_d = ch, d
            code.append(best_ch)
        return "".join(code)
    except Exception:
        return ""

if __name__ == "__main__":
    import sys
    for fp in sys.argv[1:]:
        print(fp, "->", recognize(Image.open(fp)))
