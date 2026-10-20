# -*- coding: utf-8 -*-
"""日志：同时输出到文件与 GUI 日志面板。"""

import logging
import os
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal


class LogBridge(QObject):
    """把 logging 记录转发到 Qt 信号（跨线程安全）。"""

    message = Signal(str, str, str)  # 时间, 级别, 文本


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: LogBridge, level=logging.INFO):
        super().__init__(level)
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            self.bridge.message.emit(ts, record.levelname, self.format(record))
        except Exception:  # pragma: no cover - 日志本身不应抛错
            pass


def setup_logging(log_dir: str, bridge: LogBridge, filename: str = "livewatch.log") -> str:
    """配置根 logger，返回日志文件路径。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    log_file = ""
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, filename)
        today = time.strftime("%Y-%m-%d")
        if os.path.isfile(log_file) and os.path.getmtime(log_file) < time.time() - 7 * 86400:
            os.replace(log_file, os.path.join(log_dir, f"livewatch-{today}.log"))
    except OSError:
        log_file = ""

    if log_file:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            log_file = ""

    ui = QtLogHandler(bridge)
    ui.setLevel(logging.INFO)
    ui.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ui)

    # 第三方库降噪
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    logging.getLogger(__name__).info("日志系统就绪" + (f"，文件：{log_file}" if log_file else ""))
    return log_file
