# -*- coding: utf-8 -*-
"""
每个直播间一个工作线程：定时探测开播状态 -> 自动开始 / 停止录制。
"""

import os
import re
import threading
import time
import traceback

from PySide6.QtCore import QObject, QThread, Signal

from .config import AppConfig, RoomConfig
from .constants import RoomStatus
from .douyin import DouyinClient, LiveInfo, _rid_from_url
from .paths import ensure_dir
from .recorder import FfmpegRecorder

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_filename(name: str, fallback: str = "直播间") -> str:
    """清理 Windows 文件名非法字符。"""
    cleaned = ILLEGAL_CHARS.sub("_", (name or "").strip()).strip(" ._")
    return cleaned[:60] or fallback


class RoomWorker(QThread):
    """单一直播间的监测 + 录制线程。"""

    sig_status = Signal(str, str, str)                    # key, status, detail
    sig_record_start = Signal(str, str, float)            # key, 目标文件, 开始时间戳
    sig_record_stop = Signal(str, str, float, str)        # key, 文件, 时长, 说明
    sig_log = Signal(str, str, str)                       # key, level, message
    sig_nickname = Signal(str, str)                       # key, 主播昵称

    def __init__(self, key: str, room: RoomConfig, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.key = key
        self.room = room
        self.cfg = cfg
        self._stop_evt = False
        self._client: DouyinClient | None = None
        self._recorder = FfmpegRecorder(cfg, self._log)
        self._recording = False
        self._failures = 0
        self._name_retries = 0
        self._last_finish_ts = 0.0
        self._record_started_at = 0.0
        self._record_path = ""
        self._reported_nickname = ""

    # ------------------------------------------------------------------ #
    def _log(self, level: str, message: str) -> None:
        self.sig_log.emit(self.room.name or self.key, level, message)

    def _set_status(self, status: RoomStatus, detail: str = "") -> None:
        self.sig_status.emit(self.key, status.value, detail)

    # ------------------------------------------------------------------ #
    def run(self) -> None:  # noqa: D102 - QThread 入口
        self._client = DouyinClient(self.cfg.user_agent, self.cfg.cookie, self.cfg.detect_timeout)
        self._log("INFO", f"开始监测：{self.room.url}" + ("（使用自填直连地址）" if self.room.stream_url else ""))
        self._set_status(RoomStatus.WAITING, "监测中")

        while not self._stop_evt:
            try:
                self._tick()
            except Exception:
                self._log("ERROR", "运行异常：" + traceback.format_exc(limit=3))
                self._set_status(RoomStatus.ERROR, "内部异常，详见日志")
            self._sleep(self.cfg.check_interval)

        self._shutdown()

    def _tick(self) -> None:
        # 1) 录制进程是否已自行退出（断流、达到时长 / 体积上限）
        if self._recording and not self._recorder.is_running:
            self._finish_recording("流已中断或达到录制上限，本段结束")

        if not self.room.enabled:
            return

        # 2) 状态探测
        if self.room.stream_url:
            info = LiveInfo(is_live=True, nickname=self.room.name, room_id="", source="自填直连")
        else:
            self._client.update(self.cfg.user_agent, self.cfg.cookie, self.cfg.detect_timeout)
            info = self._client.fetch_status(self.room.url)

        if info.error:
            self._failures += 1
            self._log("WARNING", f"检测失败（第 {self._failures} 次）：{info.error}")
            if self._failures >= max(1, self.cfg.failure_threshold):
                self._set_status(RoomStatus.ERROR, info.error)
            elif not self._recording:
                self._set_status(RoomStatus.WAITING, f"检测异常重试中（{self._failures}）")
            return

        self._failures = 0
        if info.nickname and info.nickname != self._reported_nickname:
            self._reported_nickname = info.nickname
            self._log("INFO", f"识别到主播：{info.nickname}")
            if info.nickname != self.room.nickname:
                self.room.nickname = info.nickname
                self.sig_nickname.emit(self.key, info.nickname)

        # 3) 开播 -> 起录；下播 -> 停录
        if info.is_live and not self._recording:
            if time.time() - self._last_finish_ts < 5:
                return  # 避免刚结束就立刻重录
            info = self._ensure_name(info)
            self._start_recording(info)
        elif not info.is_live and self._recording:
            self._finish_recording("检测到下播，已停止录制")
        elif info.is_live and self._recording:
            title = info.title or "直播中"
            self._set_status(RoomStatus.RECORDING, f"{info.nickname or self.room.name} · {title}")
        elif info.ok:
            self._set_status(RoomStatus.WAITING, "等待开播")

    # ------------------------------------------------------------------ #
    def _ensure_name(self, info: LiveInfo) -> LiveInfo:
        """
        开播瞬间若还拿不到主播名称，先短暂重探（最多约 6 秒），
        避免录制文件名落到 ``直播间xxx`` 或占位符上。
        只补充昵称，不影响流地址等其他字段。
        """
        if self.room.display_name or info.nickname:
            self._name_retries = 0
            return info
        if self._name_retries >= 2:
            return info

        self._name_retries += 1
        self._log("INFO", "检测到开播，先获取主播名称（最多等待 6 秒）…")
        for _ in range(2):
            if self._stop_evt:
                return info
            time.sleep(3)
            if self._client is None:
                return info
            try:
                again = self._client.fetch_status(self.room.url)
            except Exception:
                continue
            if again.ok and again.nickname:
                self._log("INFO", f"识别到主播：{again.nickname}")
                if again.nickname != self.room.nickname:
                    self.room.nickname = again.nickname
                    self.sig_nickname.emit(self.key, again.nickname)
                info.nickname = again.nickname
                if not info.title and again.title:
                    info.title = again.title
                self._name_retries = 0
                break
        return info

    def _start_recording(self, info: LiveInfo) -> None:
        stream = self.room.stream_url or info.best_stream_url()
        if not stream:
            self._log("WARNING", "检测到已开播，但未取到可用的流地址；可在条目中填写直连地址")
            self._set_status(RoomStatus.WAITING, "已开播，等待可用流地址")
            return

        rid = info.room_id or _rid_from_url(self.room.url)
        # 名称优先级：手动填写 > 之前识别的昵称 > 本次识别的昵称 > 房间号
        display = self.room.display_name or info.nickname or f"直播间{rid}"
        base = f"{safe_filename(display)}_{time.strftime('%Y%m%d_%H%M%S')}"
        ensure_dir(self.cfg.output_dir)

        path = self._recorder.start(stream, base)
        if not path:
            self._set_status(RoomStatus.ERROR, "启动录制失败，请检查 ffmpeg 与日志")
            return

        self._recording = True
        self._record_started_at = self._recorder.started_at
        self._record_path = path
        self.sig_record_start.emit(self.key, path, self._record_started_at)
        self._set_status(RoomStatus.RECORDING, f"{display} · {info.title or '直播中'}")

    def _finish_recording(self, reason: str) -> None:
        self._recording = False
        self._last_finish_ts = time.time()
        path, duration, message = self._recorder.stop()
        final = path or self._record_path
        self._record_path = final
        self.sig_record_stop.emit(self.key, final, duration, f"{reason}；{message}")
        self._log("INFO" if path else "WARNING", f"{reason}；{message}")
        self._set_status(RoomStatus.FINISHED, final or message)

    # ------------------------------------------------------------------ #
    def _sleep(self, seconds: float) -> None:
        """可被打断的等待。"""
        end = time.time() + max(1.0, float(seconds or 1))
        while not self._stop_evt and time.time() < end:
            time.sleep(0.2)

    def request_stop(self) -> None:
        """请求线程退出（会等待当前录制收尾）。"""
        self._stop_evt = True

    def force_abort(self) -> None:
        """强制退出：直接结束 ffmpeg（程序关闭时兜底）。"""
        self._stop_evt = True
        self._recording = False
        self._recorder.abort()

    def _shutdown(self) -> None:
        if self._recording:
            self._finish_recording("监控已停止，录制结束")
        else:
            self._recorder.abort()
        if self._client:
            self._client.close()
        self._set_status(RoomStatus.IDLE, "监控已停止")
        self._log("INFO", "监测线程已退出")


class NameFetcher(QObject):
    """
    一次性探测主播昵称：添加直播间后立刻把真实名称填进列表。

    用守护线程而非 QThread —— 程序退出时不必等它结束，避免
    「QThread destroyed while thread is still running」导致的崩溃。
    """

    done = Signal(str, str, bool)  # url, nickname, 是否成功

    def __init__(self, url: str, user_agent: str, cookie: str, timeout: int, parent=None):
        super().__init__(parent)
        self.url = url
        self.user_agent = user_agent
        self.cookie = cookie
        self.timeout = timeout
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"NameFetcher-{self.url[-20:]}", daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait(self, timeout_ms: int) -> bool:
        if not self._thread:
            return True
        self._thread.join(timeout_ms / 1000.0)
        return not self._thread.is_alive()

    def _run(self) -> None:
        client = DouyinClient(self.user_agent, self.cookie, self.timeout)
        nickname, ok = "", False
        try:
            info = client.fetch_status(self.url)
            nickname, ok = info.nickname, info.ok
        except Exception:
            nickname, ok = "", False
        finally:
            client.close()
        self.done.emit(self.url, nickname, ok)
