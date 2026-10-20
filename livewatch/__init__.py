# -*- coding: utf-8 -*-
"""
抖音直播间开播监测 + 自动录制（纯本地工具）

设计原则：
  * 只读取直播间页面公开返回的数据，不破解签名、不逆向加密算法、不抓取付费内容；
  * 仅供自有 / 已授权的达人直播间素材归档使用；
  * 不包含任何 AI / VL 视觉识别代码。
"""

from .constants import APP_NAME, APP_VERSION, RoomStatus

__all__ = ["APP_NAME", "APP_VERSION", "RoomStatus"]
