# -*- coding: utf-8 -*-
"""
抖音直播间监测录制器 —— 程序入口。

仅用于自有 / 已授权达人直播间素材归档；不包含任何 AI / 视觉识别功能。
"""

import logging
import os
import sys


def _bootstrap() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)


_bootstrap()

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from livewatch import ui_theme  # noqa: E402
from livewatch.config import default_config_yaml, load_config  # noqa: E402
from livewatch.constants import APP_NAME, APP_NAME_EN, APP_VERSION  # noqa: E402
from livewatch.logging_ext import LogBridge, setup_logging  # noqa: E402
from livewatch.main_window import MainWindow  # noqa: E402
from livewatch.paths import config_path, ensure_dir, log_dir, resource_path  # noqa: E402


def _prepare_config() -> str:
    """配置文件不存在时生成一份带注释的默认配置。"""
    path = config_path()
    if os.path.isfile(path):
        return path
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(default_config_yaml())
    except OSError as exc:
        logging.getLogger(__name__).warning("无法创建默认配置：%s", exc)
    return path


def main() -> int:
    if "--version" in sys.argv or "-v" in sys.argv:
        # 无控制台（windowed）模式下 stdout 可能不可用，这里静默容错
        try:
            sys.stdout.write(f"{APP_NAME} v{APP_VERSION}\n")
        except Exception:
            pass
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME_EN)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(ui_theme.QSS)

    icon_path = resource_path("assets", "app.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    cfg_file = _prepare_config()
    cfg = load_config(cfg_file)
    ensure_dir(cfg.output_dir)

    bridge = LogBridge()
    setup_logging(log_dir(), bridge)
    logger = logging.getLogger(__name__)
    logger.info(f"{APP_NAME} v{APP_VERSION} 启动｜配置文件：{cfg_file}")

    window = MainWindow(cfg, cfg_file, bridge)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
