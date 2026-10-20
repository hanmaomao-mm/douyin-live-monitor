# -*- coding: utf-8 -*-
"""
ffmpeg 录制器。

录制策略：先写入 MPEG-TS 中间文件（异常中断也可播放），
停止后无损封装（-c copy）为 MP4，保证文件名符合
``达人名称_年月日_时分秒.mp4`` 规则。
"""

import os
import subprocess
import threading
import time
import uuid
from typing import Callable, List, Optional

from .config import AppConfig
from .paths import ensure_dir, resolve_ffmpeg

LogFn = Callable[[str, str], None]  # (level, message)

HIDDEN_ATTR = 0x02  # FILE_ATTRIBUTE_HIDDEN


def _hide_path(path: str) -> None:
    """Windows 下把目录标记为隐藏，避免误打开正在写入的临时文件。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(path, HIDDEN_ATTR)
    except Exception:
        pass


def _quote_headers(headers: "dict[str, str]") -> str:
    """ffmpeg -headers 需要一个 CRLF 分隔的字符串。"""
    return "".join(f"{k}: {v}\r\n" for k, v in headers.items() if v)


class FfmpegRecorder:
    """单个直播间的录制任务。由工作线程持有，非线程安全（按约定使用即可）。"""

    def __init__(self, cfg: AppConfig, log: LogFn):
        self.cfg = cfg
        self._log = log
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._ts_path = ""
        self._mp4_path = ""
        self._start_ts = 0.0
        self._stopping = False
        self._exit_code: Optional[int] = None

    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def started_at(self) -> float:
        return self._start_ts

    @property
    def current_path(self) -> str:
        """录制中对外展示的目标文件路径。"""
        return self._mp4_path or self._ts_path

    @property
    def duration(self) -> float:
        if not self._start_ts:
            return 0.0
        return max(0.0, time.time() - self._start_ts)

    # ------------------------------------------------------------------ #
    def build_headers(self) -> "dict[str, str]":
        headers = {"User-Agent": self.cfg.user_agent, "Referer": "https://live.douyin.com/"}
        if self.cfg.cookie:
            headers["Cookie"] = self.cfg.cookie
        return headers

    def _input_args(self, stream_url: str) -> List[str]:
        args: List[str] = [
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-rw_timeout",
            "15000000",
        ]
        # -headers / -reconnect 是 HTTP 协议私有选项，本地文件输入时不能加
        if stream_url.lower().startswith(("http://", "https://")):
            args += [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "10",
                "-headers",
                _quote_headers(self.build_headers()),
            ]
        return args

    def _output_args(self, ts_path: str) -> List[str]:
        cfg = self.cfg
        args: List[str] = ["-map", "0:v?", "-map", "0:a?"]

        if (cfg.record_mode or "copy").lower() == "transcode":
            args += [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-r", str(max(1, int(cfg.fps or 30))),
                "-b:v", cfg.video_bitrate or "4000k",
                "-c:a", "aac",
                "-b:a", cfg.audio_bitrate or "128k",
            ]
        else:
            args += ["-c", "copy"]

        if cfg.max_duration_min and cfg.max_duration_min > 0:
            args += ["-t", str(int(cfg.max_duration_min * 60))]
        if cfg.max_file_size_mb and cfg.max_file_size_mb > 0:
            args += ["-fs", str(int(cfg.max_file_size_mb * 1024 * 1024))]

        args += ["-f", "mpegts", ts_path]
        return args

    # ------------------------------------------------------------------ #
    def start(self, stream_url: str, file_base: str) -> str:
        """
        开始录制。

        :param stream_url: 直连流地址（flv / m3u8）
        :param file_base: 不含扩展名的文件名（达人名称_年月日_时分秒）
        :return: 目标 MP4 路径；启动失败返回空串
        """
        if self.is_running:
            return self._mp4_path

        exe = resolve_ffmpeg(self.cfg.ffmpeg_path)
        out_dir = ensure_dir(self.cfg.output_dir)
        tmp_dir = ensure_dir(os.path.join(out_dir, ".tmp"))
        _hide_path(tmp_dir)

        self._ts_path = os.path.join(tmp_dir, f"{file_base}_{uuid.uuid4().hex[:6]}.ts")
        self._mp4_path = os.path.join(out_dir, f"{file_base}.mp4")
        self._exit_code = None
        self._stopping = False

        cmd = [exe] + self._input_args(stream_url) + ["-i", stream_url] + self._output_args(self._ts_path)
        self._log("DEBUG", "执行命令: " + " ".join(cmd))

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except FileNotFoundError:
            self._log("ERROR", f"找不到 ffmpeg：{exe}。请在「参数设置」中填写 ffmpeg.exe 的完整路径。")
            self._proc = None
            return ""
        except Exception as exc:  # pragma: no cover - 环境相关
            self._log("ERROR", f"启动 ffmpeg 失败：{exc}")
            self._proc = None
            return ""

        self._start_ts = time.time()
        self._reader = threading.Thread(target=self._pump_stderr, daemon=True)
        self._reader.start()
        self._log("INFO", f"开始录制 -> {self._mp4_path}")
        return self._mp4_path

    def _pump_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                low = line.lower()
                level = "WARNING" if ("error" in low or "failed" in low) else "DEBUG"
                self._log(level, f"[ffmpeg] {line}")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def poll(self) -> Optional[int]:
        """返回退出码；仍在运行时返回 None。"""
        if self._proc is None:
            return self._exit_code
        code = self._proc.poll()
        if code is not None:
            self._exit_code = code
        return code

    def stop(self, timeout: int = 20) -> "tuple[str, float, str]":
        """
        停止录制并封装为 MP4。

        :return: (最终文件路径, 录制时长秒, 说明)
        """
        proc = self._proc
        if proc is None:
            return "", 0.0, "未在录制"

        self._stopping = True
        duration = self.duration

        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._log("WARNING", "ffmpeg 未响应退出指令，强制结束")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=3)

        self._proc = None
        return self._finalize(duration)

    def _finalize(self, duration: float) -> "tuple[str, float, str]":
        """把中间 ts 无损封装成 mp4。"""
        ts_path = self._ts_path
        mp4_path = self._mp4_path

        if not os.path.isfile(ts_path) or os.path.getsize(ts_path) < 1024:
            self._log("WARNING", "没有录到有效数据，本次录制已跳过")
            self._safe_remove(ts_path)
            return "", duration, "未获取到视频数据（可能直播间已结束或流地址失效）"

        exe = resolve_ffmpeg(self.cfg.ffmpeg_path)
        attempts = [
            ["-c", "copy", "-movflags", "+faststart"],
            ["-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart"],
        ]
        for extra in attempts:
            cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", ts_path] + extra + [mp4_path]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                done = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=600,
                    creationflags=creationflags,
                )
            except Exception as exc:
                self._log("WARNING", f"封装 MP4 失败：{exc}")
                continue
            if done.returncode == 0 and os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0:
                self._safe_remove(ts_path)
                size_mb = os.path.getsize(mp4_path) / 1024 / 1024
                return mp4_path, duration, f"录制完成，文件大小 {size_mb:.1f} MB"

        # 封装失败：保留原始 ts
        fallback = os.path.splitext(mp4_path)[0] + ".ts"
        if self.cfg.keep_ts_on_failure:
            try:
                os.replace(ts_path, fallback)
                self._log("WARNING", f"封装 MP4 失败，已保留原始 TS 文件：{fallback}")
                return fallback, duration, "封装 MP4 失败，已保留 TS 源文件"
            except OSError as exc:
                self._log("ERROR", f"保留 TS 失败：{exc}")
        self._safe_remove(ts_path)
        return "", duration, "录制文件处理失败"

    def abort(self) -> None:
        """直接结束进程，不做封装（用于程序退出）。"""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None

    def _safe_remove(self, path: str) -> None:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
