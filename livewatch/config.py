# -*- coding: utf-8 -*-
"""YAML 配置读写。"""

import copy
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List

import yaml

from .paths import default_output_dir

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class RoomConfig:
    """单条监控条目。"""

    name: str = ""          # 达人名称（录制文件名前缀）；留空则自动使用检测到的主播昵称
    nickname: str = ""      # 自动识别到的主播昵称（只读，程序写入）
    url: str = ""           # 直播间链接（支持分享短链 v.douyin.com）
    enabled: bool = True    # 是否参与「启动全部监控」
    stream_url: str = ""    # 可选：直连流地址（自有 / 已授权的推流拉流地址），填写后跳过自动解析
    note: str = ""          # 备注

    @property
    def display_name(self) -> str:
        """列表展示 / 录制文件名用的名称。"""
        return self.name or self.nickname or ""


@dataclass
class AppConfig:
    """全局配置。"""

    # —— 输出 ——
    output_dir: str = field(default_factory=default_output_dir)

    # —— 检测 ——
    check_interval: int = 20        # 状态检测间隔（秒）
    detect_timeout: int = 10        # 单次 HTTP 请求超时（秒）
    failure_threshold: int = 5      # 连续失败多少次后标记为「异常」

    # —— 录制 ——
    record_mode: str = "copy"       # copy = 直录不转码（推荐）；transcode = 转码
    fps: int = 30                   # 录制帧率（仅 transcode 模式生效）
    video_bitrate: str = "4000k"    # 视频码率（仅 transcode 模式生效）
    audio_bitrate: str = "128k"     # 音频码率（仅 transcode 模式生效）
    max_duration_min: int = 0       # 单个文件最长时长（分钟），0 = 不限
    max_file_size_mb: int = 0       # 单个文件最大体积（MB），0 = 不限
    keep_ts_on_failure: bool = True  # 转 MP4 失败时保留中间 ts 文件

    # —— 环境 ——
    ffmpeg_path: str = ""           # 留空自动查找
    user_agent: str = DEFAULT_USER_AGENT
    cookie: str = ""                # 可选：自有账号 Cookie，提高检测成功率

    # —— 行为 ——
    auto_start_on_launch: bool = False
    rooms: List[RoomConfig] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def clone(self) -> "AppConfig":
        return copy.deepcopy(self)

    def get_room(self, url: str) -> RoomConfig | None:
        for r in self.rooms:
            if r.url == url:
                return r
        return None


def _coerce(value: Any, target_type: Any, fallback: Any) -> Any:
    """按 dataclass 声明的类型做一次宽松转换，坏值回退到默认值。"""
    try:
        if target_type is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on", "是")
            return bool(value)
        if target_type is int:
            return int(float(str(value).strip()))
        if target_type is float:
            return float(str(value).strip())
        if target_type is str:
            return "" if value is None else str(value)
    except (TypeError, ValueError):
        return fallback
    return value


def _build(dc_type, raw: Dict[str, Any], base):
    """把 dict 映射到 dataclass 实例上，未知键忽略、缺失键用默认值。"""
    kwargs: Dict[str, Any] = {}
    for f in fields(dc_type):
        if f.name not in raw:
            continue
        default = getattr(base, f.name, None)
        kwargs[f.name] = _coerce(raw[f.name], f.type if not isinstance(f.type, str) else str, default)
    return dc_type(**kwargs)


def load_config(path: str) -> AppConfig:
    """读取 YAML 配置，文件不存在或损坏时回退到默认配置。"""
    cfg = AppConfig()
    if not os.path.isfile(path):
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, dict):
            return cfg
    except Exception:
        return cfg

    rooms_raw = raw.pop("rooms", None)
    cfg = _build(AppConfig, raw, AppConfig())

    if isinstance(rooms_raw, list):
        rooms: List[RoomConfig] = []
        for item in rooms_raw:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rooms.append(_build(RoomConfig, item, RoomConfig()))
        cfg.rooms = rooms
    return cfg


def save_config(cfg: AppConfig, path: str) -> None:
    """写回 YAML（UTF-8、保留中文、不排序）。"""
    data = cfg.to_dict()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data,
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            indent=2,
        )
    os.replace(tmp, path)


_HEADER = """\
# ============================================================
#  抖音直播间监测录制器 - 配置文件
#  修改后可在程序「参数设置」页点击「保存配置」覆盖，或重启程序生效。
# ------------------------------------------------------------
#  output_dir          录制文件保存目录
#  check_interval      状态检测间隔（秒）
#  detect_timeout      单次 HTTP 请求超时（秒）
#  failure_threshold   连续失败多少次后标记为「异常」
#  record_mode         copy = 直录不转码（推荐）；transcode = 转码
#  fps                 录制帧率（仅 transcode 生效）
#  video_bitrate       视频码率（仅 transcode 生效），如 4000k / 6M
#  audio_bitrate       音频码率（仅 transcode 生效）
#  max_duration_min    单个文件最长时长（分钟），0 = 不限
#  max_file_size_mb    单个文件最大体积（MB），0 = 不限
#  keep_ts_on_failure  封装 MP4 失败时保留中间 TS 文件
#  ffmpeg_path         留空自动查找（内置 / 系统 PATH）
#  user_agent / cookie 如需更稳定的状态检测，可填入自有账号信息
#  auto_start_on_launch 程序启动后是否自动开始监控
#  rooms               监控列表；stream_url 可填自有 / 已授权的直连流地址
#                      name = 手动填写的达人名称；nickname = 自动识别的主播昵称（程序写入）
# ============================================================

"""


def default_config_yaml() -> str:
    """首次运行时生成的默认配置文件内容（带注释说明）。"""
    body = yaml.safe_dump(
        AppConfig().to_dict(),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
    )
    return _HEADER + body
