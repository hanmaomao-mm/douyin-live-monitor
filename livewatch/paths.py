# -*- coding: utf-8 -*-
"""路径解析与 ffmpeg 定位（兼容 PyInstaller 打包后的 exe）。"""

import os
import shutil
import sys


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的 exe 中。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """程序所在目录：exe 时为 exe 同级目录，源码运行时为项目根目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """读取打包进 exe 的只读资源。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def ensure_dir(path: str) -> str:
    """目录不存在则创建，返回原路径。"""
    if path:
        os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    """配置文件路径：始终放在 exe / 项目同级目录，方便用户直接改。"""
    return os.path.join(app_dir(), "config.yaml")


def log_dir() -> str:
    d = os.path.join(app_dir(), "logs")
    try:
        ensure_dir(d)
        probe = os.path.join(d, ".w")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return d
    except OSError:
        fallback = os.path.join(os.environ.get("TEMP", "."), "DouyinLiveMonitor-logs")
        ensure_dir(fallback)
        return fallback


def _imageio_ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return ""


def bundled_ffmpeg() -> str:
    """打包进程序的 ffmpeg。"""
    for cand in (
        resource_path("bin", "ffmpeg.exe"),
        os.path.join(app_dir(), "bin", "ffmpeg.exe"),
    ):
        if os.path.isfile(cand):
            return cand
    return ""


def resolve_ffmpeg(configured: str = "") -> str:
    """
    ffmpeg 查找顺序：
      1. 配置文件中显式指定的路径 / 命令名
      2. 程序自带（bin/ffmpeg.exe，打包时内置）
      3. imageio-ffmpeg 附带的静态 ffmpeg
      4. 系统 PATH 中的 ffmpeg
    """
    if configured:
        if os.path.isfile(configured):
            return configured
        found = shutil.which(configured)
        if found:
            return found

    local = bundled_ffmpeg()
    if local:
        return local

    static = _imageio_ffmpeg()
    if static:
        return static

    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def ffmpeg_available(configured: str = "") -> bool:
    """判断 ffmpeg 是否可用（不实际执行，只看路径是否存在）。"""
    exe = resolve_ffmpeg(configured)
    if os.path.isfile(exe):
        return True
    return bool(shutil.which(exe))


def default_output_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Videos", "DouyinRecord")
