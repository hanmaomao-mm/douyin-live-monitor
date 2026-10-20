# -*- coding: utf-8 -*-
"""全局常量与状态枚举。"""

from enum import Enum

APP_NAME = "抖音直播间监测录制器"
APP_NAME_EN = "DouyinLiveMonitor"
APP_VERSION = "1.0.0"


class RoomStatus(str, Enum):
    """监控条目的运行状态。"""

    IDLE = "未启动"
    WAITING = "等待开播"
    RECORDING = "录制中"
    FINISHED = "已结束"
    ERROR = "异常"

    def __str__(self) -> str:  # 便于日志与表格显示
        return self.value


# 状态 -> 主题色（用于表格徽标）
STATUS_COLORS = {
    RoomStatus.IDLE: "#8b93a7",
    RoomStatus.WAITING: "#4a9eff",
    RoomStatus.RECORDING: "#ff4d4f",
    RoomStatus.FINISHED: "#39c07a",
    RoomStatus.ERROR: "#ff9f43",
}
