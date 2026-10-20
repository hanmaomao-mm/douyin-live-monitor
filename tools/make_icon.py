# -*- coding: utf-8 -*-
"""
生成程序图标 assets/app.ico（纯 Python，无第三方依赖）。

设计：深色圆角方块 + 红色录制圆点(内含播放三角) + 蓝色归档条。
运行：python tools/make_icon.py
"""

import math
import os
import struct
import zlib

S = 512  # 渲染画布（超采样后缩小，得到抗锯齿边缘）
SIZES = [256, 128, 64, 48, 32, 16]

BG_TOP = (0x23, 0x2A, 0x36)
BG_BOTTOM = (0x14, 0x18, 0x20)
BORDER = (0x3D, 0x47, 0x59)
RED = (0xFF, 0x4D, 0x4F)
WHITE = (0xFF, 0xFF, 0xFF)
BLUE = (0x4A, 0x9E, 0xFF)

FEATHER = 1.6  # 边缘羽化宽度（像素）


def _cov(sd: float) -> float:
    """有符号距离 -> 覆盖率。"""
    return min(1.0, max(0.0, 0.5 - sd / FEATHER))


def _sdf_round_rect(x, y, cx, cy, hw, hh, r) -> float:
    dx = abs(x - cx) - (hw - r)
    dy = abs(y - cy) - (hh - r)
    ax, ay = max(dx, 0.0), max(dy, 0.0)
    return math.hypot(ax, ay) + min(max(dx, dy), 0.0) - r


def _sdf_triangle(x, y, pts) -> float:
    """凸多边形（3 点）近似有符号距离：取各边半平面距离的最大值。"""
    best = -1e9
    for i in range(3):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % 3]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey) or 1.0
        # 内部在边左侧
        d = ((x - ax) * (-ey) + (y - ay) * ex) / length
        best = max(best, d)
    return best


def render(size: int) -> "list[bytearray]":
    """渲染一张 size x size 的 RGBA 图像（每行一个 bytearray）。"""
    c = float(size)
    margin = c * 0.045
    hw = hh = (c - 2 * margin) / 2
    radius = c * 0.205
    border_w = c * 0.018

    dot_cx, dot_cy = c * 0.5, c * 0.415
    dot_r = c * 0.185

    tri_hw, tri_hh = c * 0.070, c * 0.083
    tri = [
        (dot_cx - tri_hw * 0.72 + c * 0.012, dot_cy - tri_hh),
        (dot_cx - tri_hw * 0.72 + c * 0.012, dot_cy + tri_hh),
        (dot_cx + tri_hw * 1.28 + c * 0.012, dot_cy),
    ]

    bar_cx, bar_cy = c * 0.5, c * 0.725
    bar_hw, bar_hh = c * 0.21, c * 0.027

    rows = []
    for py in range(size):
        row = bytearray(size * 4)
        y = py + 0.5
        v = y / c
        bg = tuple(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * v for i in range(3))
        for px in range(size):
            x = px + 0.5
            a_outer = _cov(_sdf_round_rect(x, y, c / 2, c / 2, hw, hh, radius))
            if a_outer <= 0.0:
                continue
            r, g, b = bg
            a = 1.0

            # 边框
            a_inner = _cov(_sdf_round_rect(x, y, c / 2, c / 2, hw, hh, radius) + border_w)
            ring = max(0.0, a_outer - a_inner)
            if ring > 0:
                r = r * (1 - ring) + BORDER[0] * ring
                g = g * (1 - ring) + BORDER[1] * ring
                b = b * (1 - ring) + BORDER[2] * ring

            # 蓝色归档条
            a_bar = _cov(_sdf_round_rect(x, y, bar_cx, bar_cy, bar_hw, bar_hh, bar_hh))
            if a_bar > 0:
                r = r * (1 - a_bar) + BLUE[0] * a_bar
                g = g * (1 - a_bar) + BLUE[1] * a_bar
                b = b * (1 - a_bar) + BLUE[2] * a_bar

            # 红色录制圆点
            a_dot = _cov(math.hypot(x - dot_cx, y - dot_cy) - dot_r)
            if a_dot > 0:
                r = r * (1 - a_dot) + RED[0] * a_dot
                g = g * (1 - a_dot) + RED[1] * a_dot
                b = b * (1 - a_dot) + RED[2] * a_dot

            # 白色播放三角
            a_tri = _cov(_sdf_triangle(x, y, tri))
            if a_tri > 0:
                r = r * (1 - a_tri) + WHITE[0] * a_tri
                g = g * (1 - a_tri) + WHITE[1] * a_tri
                b = b * (1 - a_tri) + WHITE[2] * a_tri

            o = px * 4
            row[o] = int(max(0, min(255, r)))
            row[o + 1] = int(max(0, min(255, g)))
            row[o + 2] = int(max(0, min(255, b)))
            row[o + 3] = int(max(0, min(255, a_outer * 255)))
        rows.append(row)
    return rows


def downscale(src, src_size: int, dst_size: int):
    """面积平均缩放。"""
    rows = []
    ratio = src_size / dst_size
    for dy in range(dst_size):
        y0, y1 = dy * ratio, (dy + 1) * ratio
        iy0, iy1 = int(math.floor(y0)), max(int(math.ceil(y1)), int(math.floor(y0)) + 1)
        row = bytearray(dst_size * 4)
        for dx in range(dst_size):
            x0, x1 = dx * ratio, (dx + 1) * ratio
            ix0, ix1 = int(math.floor(x0)), max(int(math.ceil(x1)), int(math.floor(x0)) + 1)
            acc = [0.0] * 4
            n = 0
            for yy in range(iy0, min(iy1, src_size)):
                srow = src[yy]
                for xx in range(ix0, min(ix1, src_size)):
                    o = xx * 4
                    acc[0] += srow[o]
                    acc[1] += srow[o + 1]
                    acc[2] += srow[o + 2]
                    acc[3] += srow[o + 3]
                    n += 1
            n = max(n, 1)
            o = dx * 4
            for k in range(4):
                row[o + k] = int(max(0, min(255, acc[k] / n)))
        rows.append(row)
    return rows


def png_bytes(size: int, rows) -> bytes:
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    comp = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) + chunk(b"IEND", b"")


def build_ico(out_path: str) -> None:
    print(f"渲染 {S}x{S} 画布…")
    base = render(S)
    images = []
    for size in SIZES:
        rows = base if size == S else downscale(base, S, size)
        images.append((size, png_bytes(size, rows)))

    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries, blobs = b"", b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(header + entries + blobs)
    print(f"已生成：{out_path}（{count} 种尺寸，{os.path.getsize(out_path) / 1024:.1f} KB）")


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build_ico(os.path.join(root, "assets", "app.ico"))
