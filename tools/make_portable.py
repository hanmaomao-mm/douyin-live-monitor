# -*- coding: utf-8 -*-
"""
把 dist/DouyinLiveMonitor 组装成可分发到其他电脑的便携压缩包。

用法（在项目根目录）：
    python tools/make_portable.py

产物：
    DouyinLiveMonitor_v<版本>_便携版.zip
    └─ DouyinLiveMonitor/
       ├─ DouyinLiveMonitor.exe
       ├─ _internal/          （Qt 运行库 + 内置 ffmpeg）
       └─ 使用说明.txt

注意：config.yaml / logs 属于本机使用痕迹，不会打进包里，
      由对方电脑首次运行时自动生成（输出目录按对方用户名计算）。
"""

import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from livewatch.constants import APP_VERSION  # noqa: E402

TOP = "DouyinLiveMonitor"
SRC = os.path.join(ROOT, "dist", TOP)
STAGE = os.path.join(ROOT, "release", TOP)
GUIDE = os.path.join(ROOT, "docs", "使用说明.txt")
EXCLUDE_DIRS = {"logs", ".tmp", "__pycache__"}
EXCLUDE_FILES = {"config.yaml", "config.yaml.tmp", "livewatch.log"}


def stage_files() -> str:
    if not os.path.isdir(SRC):
        raise SystemExit(f"找不到 {SRC}\n请先执行 build.bat 打包出 exe。")

    if os.path.isdir(os.path.join(ROOT, "release")):
        shutil.rmtree(os.path.join(ROOT, "release"), ignore_errors=True)
    os.makedirs(STAGE, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        rel = os.path.relpath(dirpath, SRC)
        target = STAGE if rel == "." else os.path.join(STAGE, rel)
        os.makedirs(target, exist_ok=True)
        for name in filenames:
            if name in EXCLUDE_FILES:
                continue
            shutil.copy2(os.path.join(dirpath, name), os.path.join(target, name))

    if os.path.isfile(GUIDE):
        shutil.copy2(GUIDE, os.path.join(STAGE, "使用说明.txt"))
    else:
        print("[警告] 未找到 docs/使用说明.txt，压缩包内将没有说明文件")
    return STAGE


def make_zip(stage_dir: str) -> str:
    out = os.path.join(ROOT, f"DouyinLiveMonitor_v{APP_VERSION}_便携版.zip")
    if os.path.exists(out):
        os.remove(out)

    entries = [
        (os.path.join(d, f), os.path.relpath(os.path.join(d, f), os.path.dirname(stage_dir)))
        for d, _, fs in os.walk(stage_dir)
        for f in fs
    ]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for full, arc in entries:
            z.write(full, arc)
    return out


def main() -> int:
    stage_dir = stage_files()
    count = sum(len(fs) for _, _, fs in os.walk(stage_dir))
    zip_path = make_zip(stage_dir)
    size = os.path.getsize(zip_path) / 1024 / 1024
    print(f"已打包 {count} 个文件 -> {os.path.basename(zip_path)}（{size:.1f} MB）")
    print(f"完整路径：{zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
