# -*- coding: utf-8 -*-
"""主窗口：监控列表 + 总开关 + 日志面板 + 参数设置。"""

import html
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import ui_theme as T
from .config import AppConfig, RoomConfig, save_config
from .constants import APP_NAME, APP_VERSION, STATUS_COLORS, RoomStatus
from .douyin import extract_room_ref
from .paths import ensure_dir, ffmpeg_available, resolve_ffmpeg, resource_path
from .worker import NameFetcher, RoomWorker, safe_filename

log = logging.getLogger(__name__)

COL_NAME, COL_URL, COL_STATUS, COL_DURATION, COL_PATH, COL_ACTION = range(6)
HEADERS = ["达人名称", "直播间链接", "状态", "录制时长", "文件路径", "操作"]


def fmt_duration(seconds: float) -> str:
    total = int(max(0, seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


# --------------------------------------------------------------------------- #
# 状态徽标绘制
# --------------------------------------------------------------------------- #
class StatusBadgeDelegate(QStyledItemDelegate):
    """把状态列画成圆角色块。"""

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: D102
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        base = QColor("#1a1f28" if index.row() % 2 else "#1d222c")
        painter.fillRect(option.rect, base)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(74, 158, 255, 46))

        text = str(index.data(Qt.DisplayRole) or "")
        color = QColor(index.data(Qt.UserRole) or "#8b93a7")

        rect = option.rect.adjusted(6, 7, -6, -7)
        fm = painter.fontMetrics()
        width = min(rect.width(), max(66, fm.horizontalAdvance(text) + 30))
        pill = QRectF(
            rect.x() + (rect.width() - width) / 2.0,
            rect.y(),
            float(width),
            float(rect.height()),
        )
        bg = QColor(color)
        bg.setAlpha(48)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)

        text_rect = QRectF(pill)
        if text == RoomStatus.RECORDING.value:
            dot_r = 3.5
            cx = pill.x() + 12
            cy = pill.center().y()
            painter.setBrush(color)
            painter.drawEllipse(QRectF(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2))
            text_rect = QRectF(pill.x() + 10, pill.y(), pill.width() - 10, pill.height())

        painter.setPen(color)
        f = QFont(painter.font())
        f.setBold(text == RoomStatus.RECORDING.value)
        painter.setFont(f)
        painter.drawText(text_rect, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: D102
        return QSize(110, 40)


# --------------------------------------------------------------------------- #
@dataclass
class RoomRow:
    """表格中一行的运行时状态（与 RoomConfig 一一对应）。"""

    room: RoomConfig
    status: RoomStatus = RoomStatus.IDLE
    detail: str = ""
    path: str = ""
    started_at: float = 0.0
    duration: float = 0.0
    worker: Optional[RoomWorker] = None
    items: List[QTableWidgetItem] = field(default_factory=list)


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, cfg_file: str, log_bridge=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.cfg_file = cfg_file
        self.log_bridge = log_bridge
        self._rows: Dict[str, RoomRow] = {}
        self._fetchers: Dict[str, NameFetcher] = {}
        self._shutting_down = False

        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(1240, 800)
        self.setMinimumSize(980, 620)

        icon_path = resource_path("assets", "app.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._build_ui()
        self._load_settings_into_ui()
        self._rebuild_table()

        if self.log_bridge is not None:
            self.log_bridge.message.connect(self._on_log_message)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._check_ffmpeg(verbose=True)

        if self.cfg.auto_start_on_launch and self.cfg.rooms:
            QTimer.singleShot(600, self._on_start_all)

        # 已有条目但还没有名称时，启动后自动识别一次
        QTimer.singleShot(1500, self._autofill_names)

    # ================================================================== #
    # 界面搭建
    # ================================================================== #
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)

        root.addWidget(self._build_header())
        root.addWidget(self._build_add_bar())

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_bottom_tabs())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([430, 320])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)
        self.summary_label = QLabel("")
        self.statusBar().addPermanentWidget(self.summary_label)

    # ------------------------------------------------------------------ #
    def _build_header(self) -> QWidget:
        box = QFrame()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(2, 0, 2, 0)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel("定时检测开播状态 · 开播自动录制 · 下播自动停止　|　仅用于自有 / 已授权达人素材归档")
        sub.setObjectName("Subtitle")
        left.addWidget(title)
        left.addWidget(sub)
        lay.addLayout(left)
        lay.addStretch(1)

        self.btn_start_all = QPushButton("启动全部监控")
        self.btn_start_all.setObjectName("Start")
        self.btn_start_all.clicked.connect(self._on_start_all)
        lay.addWidget(self.btn_start_all)

        self.btn_stop_all = QPushButton("停止全部监控")
        self.btn_stop_all.setObjectName("Stop")
        self.btn_stop_all.setEnabled(False)
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        lay.addWidget(self.btn_stop_all)

        btn_refresh_names = QPushButton("刷新名称")
        btn_refresh_names.setToolTip("为名称仍是「（自动）」的条目重新识别主播昵称")
        btn_refresh_names.clicked.connect(self._on_refresh_names)
        lay.addWidget(btn_refresh_names)

        btn_open_dir = QPushButton("打开输出目录")
        btn_open_dir.clicked.connect(self._open_output_dir)
        lay.addWidget(btn_open_dir)

        btn_help = QPushButton("使用说明")
        btn_help.clicked.connect(self._show_help)
        lay.addWidget(btn_help)
        return box

    # ------------------------------------------------------------------ #
    def _build_add_bar(self) -> QWidget:
        box = QGroupBox("添加直播间")
        lay = QHBoxLayout(box)
        lay.setSpacing(8)

        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("达人名称（可留空，自动取主播昵称）")
        self.input_name.setFixedWidth(250)

        self.input_url = QLineEdit()
        self.input_url.setPlaceholderText("粘贴抖音直播间链接或 App 分享文案，例如 https://live.douyin.com/123456789")
        self.input_url.returnPressed.connect(self._on_add_room)

        btn_add = QPushButton("添加到监控列表")
        btn_add.setObjectName("Primary")
        btn_add.setFixedWidth(140)
        btn_add.clicked.connect(self._on_add_room)

        lay.addWidget(QLabel("达人名称"))
        lay.addWidget(self.input_name)
        lay.addWidget(QLabel("直播间"))
        lay.addWidget(self.input_url, 1)
        lay.addWidget(btn_add)
        return box

    # ------------------------------------------------------------------ #
    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setItemDelegateForColumn(COL_STATUS, StatusBadgeDelegate(self.table))
        self.table.doubleClicked.connect(self._on_row_activated)

        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_URL, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_STATUS, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_DURATION, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_PATH, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_ACTION, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_NAME, 150)
        self.table.setColumnWidth(COL_STATUS, 110)
        self.table.setColumnWidth(COL_DURATION, 104)
        self.table.setColumnWidth(COL_ACTION, 196)
        return self.table

    # ------------------------------------------------------------------ #
    def _build_bottom_tabs(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_log_tab(), "运行日志")
        self.tabs.addTab(self._build_settings_tab(), "参数设置")
        return self.tabs

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("级别"))
        self.log_level = QComboBox()
        self.log_level.addItems(["全部", "INFO 及以上", "WARNING 及以上", "ERROR"])
        self.log_level.setFixedWidth(140)
        bar.addWidget(self.log_level)

        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        bar.addWidget(self.chk_autoscroll)
        bar.addStretch(1)

        btn_save_log = QPushButton("导出日志")
        btn_save_log.clicked.connect(self._export_log)
        bar.addWidget(btn_save_log)

        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(lambda: self.log_view.clear())
        bar.addWidget(btn_clear)
        lay.addLayout(bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(6000)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.log_view.setFont(font)
        lay.addWidget(self.log_view, 1)
        return page

    # ------------------------------------------------------------------ #
    def _build_settings_tab(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # —— 录制参数 ——
        gb_rec = QGroupBox("录制参数")
        form = QFormLayout(gb_rec)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)

        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(5, 3600)
        self.sp_interval.setSuffix(" 秒")
        self.sp_interval.setToolTip("每隔多久检测一次直播间是否开播")
        form.addRow("检测间隔", self.sp_interval)

        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(3, 60)
        self.sp_timeout.setSuffix(" 秒")
        form.addRow("请求超时", self.sp_timeout)

        self.sp_failures = QSpinBox()
        self.sp_failures.setRange(1, 50)
        self.sp_failures.setSuffix(" 次")
        self.sp_failures.setToolTip("连续失败多少次后把该条目标记为「异常」")
        form.addRow("异常阈值", self.sp_failures)

        self.cb_mode = QComboBox()
        self.cb_mode.addItem("直录不转码（推荐，低 CPU，画质原样）", "copy")
        self.cb_mode.addItem("转码录制（可自定义帧率 / 码率）", "transcode")
        self.cb_mode.currentIndexChanged.connect(self._sync_mode_enabled)
        form.addRow("录制模式", self.cb_mode)

        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(5, 60)
        self.sp_fps.setToolTip("仅「转码录制」模式生效")
        form.addRow("录制帧率", self.sp_fps)

        self.ed_vbitrate = QLineEdit()
        self.ed_vbitrate.setPlaceholderText("如 4000k / 6M")
        self.ed_vbitrate.setToolTip("仅「转码录制」模式生效")
        form.addRow("视频码率", self.ed_vbitrate)

        self.ed_abitrate = QLineEdit()
        self.ed_abitrate.setPlaceholderText("如 128k")
        self.ed_abitrate.setToolTip("仅「转码录制」模式生效")
        form.addRow("音频码率", self.ed_abitrate)

        self.sp_maxdur = QSpinBox()
        self.sp_maxdur.setRange(0, 1440)
        self.sp_maxdur.setSuffix(" 分钟")
        self.sp_maxdur.setSpecialValueText("不限")
        form.addRow("单文件最长", self.sp_maxdur)

        self.sp_maxsize = QSpinBox()
        self.sp_maxsize.setRange(0, 102400)
        self.sp_maxsize.setSuffix(" MB")
        self.sp_maxsize.setSpecialValueText("不限")
        form.addRow("单文件最大", self.sp_maxsize)

        lay.addWidget(gb_rec)

        # —— 输出 ——
        gb_out = QGroupBox("输出目录")
        out_lay = QHBoxLayout(gb_out)
        self.ed_outdir = QLineEdit()
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._choose_output_dir)
        btn_open = QPushButton("打开")
        btn_open.clicked.connect(self._open_output_dir)
        out_lay.addWidget(self.ed_outdir, 1)
        out_lay.addWidget(btn_browse)
        out_lay.addWidget(btn_open)
        lay.addWidget(gb_out)

        # —— 环境 ——
        gb_env = QGroupBox("运行环境")
        env_form = QFormLayout(gb_env)
        env_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        ff_lay = QHBoxLayout()
        self.ed_ffmpeg = QLineEdit()
        self.ed_ffmpeg.setPlaceholderText("留空自动查找（内置 / 系统 PATH）")
        btn_detect = QPushButton("检测")
        btn_detect.clicked.connect(lambda: self._check_ffmpeg(verbose=True))
        self.lbl_ffmpeg = QLabel("")
        self.lbl_ffmpeg.setObjectName("Hint")
        ff_lay.addWidget(self.ed_ffmpeg, 1)
        ff_lay.addWidget(btn_detect)
        env_form.addRow("ffmpeg 路径", ff_lay)
        env_form.addRow("ffmpeg 状态", self.lbl_ffmpeg)

        self.ed_ua = QLineEdit()
        env_form.addRow("User-Agent", self.ed_ua)

        self.ed_cookie = QLineEdit()
        self.ed_cookie.setPlaceholderText("可选：填入自有账号 Cookie，可提高检测成功率")
        self.ed_cookie.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        env_form.addRow("Cookie", self.ed_cookie)

        self.chk_autostart = QCheckBox("程序启动后自动开始监控全部条目")
        env_form.addRow("", self.chk_autostart)
        lay.addWidget(gb_env)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_settings)
        row.addWidget(btn_reset)
        btn_save = QPushButton("保存配置")
        btn_save.setObjectName("Primary")
        btn_save.setMinimumWidth(120)
        btn_save.clicked.connect(lambda: self._apply_settings(True))
        row.addWidget(btn_save)
        lay.addLayout(row)
        lay.addStretch(1)

        area.setWidget(page)
        return area

    # ================================================================== #
    # 配置 <-> 界面
    # ================================================================== #
    def _load_settings_into_ui(self) -> None:
        c = self.cfg
        self.sp_interval.setValue(int(c.check_interval))
        self.sp_timeout.setValue(int(c.detect_timeout))
        self.sp_failures.setValue(int(c.failure_threshold))
        idx = self.cb_mode.findData(c.record_mode if c.record_mode in ("copy", "transcode") else "copy")
        self.cb_mode.setCurrentIndex(max(0, idx))
        self.sp_fps.setValue(int(c.fps))
        self.ed_vbitrate.setText(c.video_bitrate)
        self.ed_abitrate.setText(c.audio_bitrate)
        self.sp_maxdur.setValue(int(c.max_duration_min))
        self.sp_maxsize.setValue(int(c.max_file_size_mb))
        self.ed_outdir.setText(c.output_dir)
        self.ed_ffmpeg.setText(c.ffmpeg_path)
        self.ed_ua.setText(c.user_agent)
        self.ed_cookie.setText(c.cookie)
        self.chk_autostart.setChecked(bool(c.auto_start_on_launch))
        self._sync_mode_enabled()

    def _apply_settings(self, persist: bool = True) -> None:
        c = self.cfg
        c.check_interval = self.sp_interval.value()
        c.detect_timeout = self.sp_timeout.value()
        c.failure_threshold = self.sp_failures.value()
        c.record_mode = self.cb_mode.currentData()
        c.fps = self.sp_fps.value()
        c.video_bitrate = self.ed_vbitrate.text().strip() or "4000k"
        c.audio_bitrate = self.ed_abitrate.text().strip() or "128k"
        c.max_duration_min = self.sp_maxdur.value()
        c.max_file_size_mb = self.sp_maxsize.value()
        c.output_dir = self.ed_outdir.text().strip() or c.output_dir
        c.ffmpeg_path = self.ed_ffmpeg.text().strip()
        c.user_agent = self.ed_ua.text().strip() or c.user_agent
        c.cookie = self.ed_cookie.text().strip()
        c.auto_start_on_launch = self.chk_autostart.isChecked()
        self._sync_mode_enabled()
        if persist:
            self._save_config(silent=False)

    def _sync_mode_enabled(self) -> None:
        transcoding = self.cb_mode.currentData() == "transcode"
        for w in (self.sp_fps, self.ed_vbitrate, self.ed_abitrate):
            w.setEnabled(transcoding)

    def _reset_settings(self) -> None:
        if QMessageBox.question(self, "确认", "恢复为默认参数？（监控列表不会被清空）") != QMessageBox.Yes:
            return
        from .config import AppConfig

        default = AppConfig()
        default.rooms = self.cfg.rooms
        default.output_dir = self.cfg.output_dir
        self.cfg.__dict__.update(default.__dict__)
        self._load_settings_into_ui()
        self._save_config(silent=False)

    def _save_config(self, silent: bool = True) -> None:
        try:
            save_config(self.cfg, self.cfg_file)
            if not silent:
                log.info(f"配置已保存：{self.cfg_file}")
                self.status_label.setText("配置已保存")
        except OSError as exc:
            log.error(f"配置保存失败：{exc}")
            if not silent:
                QMessageBox.warning(self, "保存失败", f"无法写入配置文件：\n{exc}")

    def _choose_output_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择录制文件保存目录", self.ed_outdir.text() or os.path.expanduser("~"))
        if chosen:
            self.ed_outdir.setText(os.path.normpath(chosen))

    # ================================================================== #
    # 表格
    # ================================================================== #
    def _rebuild_table(self) -> None:
        # 丢弃已从配置中移除的条目
        for url in list(self._rows):
            if not self.cfg.get_room(url):
                del self._rows[url]

        self.table.setRowCount(0)
        for room in self.cfg.rooms:
            row = self._rows.get(room.url) or RoomRow(room=room)
            row.room = room
            self._rows[room.url] = row
            self._append_table_row(row)
        self._refresh_summary()

    def _append_table_row(self, row: RoomRow) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        row.items = []

        for col, text in (
            (COL_NAME, row.room.display_name or "（自动）"),
            (COL_URL, row.room.url),
            (COL_STATUS, str(row.status)),
            (COL_DURATION, fmt_duration(row.duration)),
            (COL_PATH, row.path or "—"),
        ):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            if col in (COL_DURATION,):
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, col, item)
            row.items.append(item)

        # 状态列额外数据（items 下标与列号 0..4 一一对应）
        status_item = row.items[COL_STATUS]
        status_item.setData(Qt.UserRole, STATUS_COLORS.get(row.status, "#8b93a7"))

        self.table.setCellWidget(r, COL_ACTION, self._make_action_widget(row))
        self._refresh_row(row)

    def _make_action_widget(self, row: RoomRow) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(5)

        btn_toggle = QPushButton("停止" if (row.worker and row.worker.isRunning()) else "开始")
        btn_toggle.setObjectName("RowAction")
        btn_toggle.setFixedWidth(52)
        btn_toggle.clicked.connect(lambda _=False, r=row: self._toggle_row(r))

        btn_open = QPushButton("打开")
        btn_open.setObjectName("RowAction")
        btn_open.setFixedWidth(52)
        btn_open.clicked.connect(lambda _=False, r=row: self._open_row_folder(r))

        btn_del = QPushButton("删除")
        btn_del.setObjectName("RowAction")
        btn_del.setFixedWidth(52)
        btn_del.clicked.connect(lambda _=False, r=row: self._on_delete_room(r))

        lay.addWidget(btn_toggle)
        lay.addWidget(btn_open)
        lay.addWidget(btn_del)
        row.toggle_btn = btn_toggle
        return w

    def _refresh_row(self, row: RoomRow) -> None:
        if not row.items:
            return
        name_item = row.items[COL_NAME]
        name_item.setText(row.room.display_name or "（自动）")
        if row.room.name:
            tip = f"手动填写：{row.room.name}"
        elif row.room.nickname:
            tip = f"自动识别：{row.room.nickname}\n可在添加时填写「达人名称」覆盖"
        else:
            tip = "尚未识别到主播名称，开始监控后或点「刷新名称」会自动识别"
        name_item.setToolTip(tip)

        status_item = row.items[COL_STATUS]
        status_item.setText(str(row.status))
        status_item.setData(Qt.UserRole, STATUS_COLORS.get(row.status, "#8b93a7"))
        status_item.setToolTip(row.detail or str(row.status))

        row.items[COL_DURATION].setText(fmt_duration(row.duration))

        path_item = row.items[COL_PATH]
        path_item.setText(row.path or "—")
        path_item.setToolTip(row.path or "")

        btn = getattr(row, "toggle_btn", None)
        if btn is not None:
            running = bool(row.worker and row.worker.isRunning())
            btn.setText("停止" if running else "开始")
            btn.setEnabled(row.worker is not None or True)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = len(self.cfg.rooms)
        running = sum(1 for r in self._rows.values() if r.worker and r.worker.isRunning())
        recording = sum(1 for r in self._rows.values() if r.status == RoomStatus.RECORDING)
        self.summary_label.setText(f"监控条目 {total}　运行中 {running}　录制中 {recording}")

    # ================================================================== #
    # 增删 / 开关
    # ================================================================== #
    def _on_add_room(self) -> None:
        raw = self.input_url.text().strip()
        name = self.input_name.text().strip()
        if not raw:
            QMessageBox.information(self, "提示", "请先粘贴直播间链接或分享文案。")
            return

        url = extract_room_ref(raw)
        if not url:
            QMessageBox.warning(
                self,
                "无法识别链接",
                "没能从输入内容中解析出直播间链接。\n\n"
                "请粘贴形如 https://live.douyin.com/123456789 的直播间地址，\n"
                "或直接粘贴抖音 App 的「分享 → 复制链接」文案。",
            )
            return

        if self.cfg.get_room(url):
            QMessageBox.information(self, "提示", "该直播间已在监控列表中。")
            return

        room = RoomConfig(name=name, url=url)
        self.cfg.rooms.append(room)
        self.input_url.clear()
        self.input_name.clear()
        self._save_config(silent=True)
        self._rebuild_table()
        log.info(f"已添加监控条目：{room.display_name or '（自动）'} {url}")

        # 没填达人名称时，立刻在后台识别一次主播昵称
        if not room.name:
            self._fetch_name(room)

    # ------------------------------------------------------------------ #
    # 主播昵称识别
    # ------------------------------------------------------------------ #
    def _fetch_name(self, room: RoomConfig) -> None:
        """后台取一次主播昵称，成功后写回配置并刷新列表。"""
        if room.name or room.url in self._fetchers:
            return  # 手动填了名称的无需识别
        fetcher = NameFetcher(room.url, self.cfg.user_agent, self.cfg.cookie, self.cfg.detect_timeout, self)
        fetcher.done.connect(self._on_name_fetched)
        self._fetchers[room.url] = fetcher
        fetcher.start()
        row = self._rows.get(room.url)
        if row:
            row.detail = "正在识别主播名称…"
            self._refresh_row(row)

    def _on_name_fetched(self, url: str, nickname: str, ok: bool) -> None:
        fetcher = self._fetchers.pop(url, None)
        if fetcher is not None:
            fetcher.wait(2000)

        row = self._rows.get(url)
        room = self.cfg.get_room(url)
        if not room:
            return
        if nickname:
            room.nickname = nickname
            self._save_config(silent=True)
            log.info(f"已识别主播名称：{nickname}（{url}）")
        else:
            log.warning(
                f"暂未识别到主播名称（{url}）"
                + (f"：{ok}" if not ok else "，该直播间当前可能未开播；开始监控后会自动重试")
            )
        if row:
            row.detail = ""
            self._refresh_row(row)

    def _on_refresh_names(self) -> None:
        targets = [r for r in self.cfg.rooms if not r.name and r.url not in self._fetchers]
        if not targets:
            self.status_label.setText("所有条目都有名称，或正在识别中")
            return
        for room in targets:
            self._fetch_name(room)
        self.status_label.setText(f"正在识别 {len(targets)} 个条目的主播名称…")

    def _autofill_names(self) -> None:
        """启动后为没有名称的条目静默补一次识别。"""
        targets = [r for r in self.cfg.rooms if not r.name and not r.nickname and r.url not in self._fetchers]
        for room in targets:
            self._fetch_name(room)
        if targets:
            log.info(f"正在自动识别 {len(targets)} 个条目的主播名称…")

    def _on_delete_room(self, row: RoomRow) -> None:
        if row.worker and row.worker.isRunning():
            if QMessageBox.question(self, "确认", f"该条目正在监控中，删除会同时停止监控并结束录制。\n\n确定删除？") != QMessageBox.Yes:
                return
            self._stop_row(row, wait_ms=6000)
        else:
            if QMessageBox.question(self, "确认", "确定从监控列表移除该条目？") != QMessageBox.Yes:
                return

        room = self.cfg.get_room(row.room.url)
        if room in self.cfg.rooms:
            self.cfg.rooms.remove(room)
        fetcher = self._fetchers.pop(row.room.url, None)
        if fetcher is not None:
            fetcher.wait(1500)
        self._rows.pop(row.room.url, None)
        self._save_config(silent=True)
        self._rebuild_table()
        log.info(f"已移除监控条目：{row.room.url}")

    def _toggle_row(self, row: RoomRow) -> None:
        if row.worker and row.worker.isRunning():
            self._stop_row(row)
        else:
            self._start_row(row)

    def _start_row(self, row: RoomRow) -> None:
        if row.worker and row.worker.isRunning():
            return
        worker = RoomWorker(row.room.url, row.room, self.cfg, self)
        worker.sig_status.connect(self._on_worker_status)
        worker.sig_record_start.connect(self._on_record_start)
        worker.sig_record_stop.connect(self._on_record_stop)
        worker.sig_log.connect(self._on_worker_log)
        worker.sig_nickname.connect(self._on_worker_nickname)
        worker.finished.connect(lambda key=row.room.url: self._on_worker_finished(key))
        row.worker = worker
        row.status = RoomStatus.WAITING
        row.detail = "监测中"
        row.path = ""
        row.duration = 0.0
        worker.start()
        self._refresh_row(row)

    def _stop_row(self, row: RoomRow, wait_ms: int = 0) -> None:
        worker = row.worker
        if not worker or not worker.isRunning():
            return
        worker.request_stop()
        if wait_ms:
            if not worker.wait(wait_ms):
                worker.force_abort()
                worker.wait(3000)
            self._on_worker_finished(row.room.url)
        else:
            row.detail = "正在停止…"
            self._refresh_row(row)

    def _on_start_all(self) -> None:
        self._apply_settings(persist=False)
        targets = [r for r in self._rows.values() if r.room.enabled and not (r.worker and r.worker.isRunning())]
        if not targets:
            self.status_label.setText("没有可启动的监控条目")
            return
        for row in targets:
            self._start_row(row)
        self.status_label.setText(f"已启动 {len(targets)} 个监控")
        log.info(f"启动全部监控：{len(targets)} 个条目")

    def _on_stop_all(self) -> None:
        running = [r for r in self._rows.values() if r.worker and r.worker.isRunning()]
        if not running:
            self.status_label.setText("当前没有运行中的监控")
            return
        for row in running:
            row.detail = "正在停止…"
            row.worker.request_stop()
            self._refresh_row(row)
        self.status_label.setText(f"正在停止 {len(running)} 个监控（录制文件会正常收尾）…")
        log.info(f"停止全部监控：{len(running)} 个条目")

    def _on_worker_finished(self, key: str) -> None:
        row = self._rows.get(key)
        if not row:
            return
        row.worker = None
        self._refresh_row(row)

    # ================================================================== #
    # 工作线程回调
    # ================================================================== #
    def _on_worker_status(self, key: str, status_value: str, detail: str) -> None:
        row = self._rows.get(key)
        if not row:
            return
        try:
            row.status = RoomStatus(status_value)
        except ValueError:
            row.status = RoomStatus.IDLE
        row.detail = detail
        self._refresh_row(row)

    def _on_record_start(self, key: str, path: str, started_at: float) -> None:
        row = self._rows.get(key)
        if not row:
            return
        row.path = path
        row.started_at = started_at
        row.duration = 0.0
        self._refresh_row(row)
        self.status_label.setText(f"开始录制：{os.path.basename(path)}")

    def _on_record_stop(self, key: str, path: str, duration: float, message: str) -> None:
        row = self._rows.get(key)
        if not row:
            return
        row.path = path
        row.duration = duration
        row.started_at = 0.0
        self._refresh_row(row)
        self.status_label.setText(f"录制结束：{fmt_duration(duration)}")

    def _on_worker_nickname(self, key: str, nickname: str) -> None:
        room = self.cfg.get_room(key)
        if not room:
            return
        room.nickname = nickname
        self._save_config(silent=True)
        self._refresh_row(self._rows.get(key) or RoomRow(room=room))

    def _on_worker_log(self, name: str, level: str, message: str) -> None:
        getattr(log, level.lower() if level.lower() in ("debug", "info", "warning", "error") else "info")(
            f"[{name}] {message}"
        )

    # ================================================================== #
    # 日志面板
    # ================================================================== #
    def _on_log_message(self, ts: str, level: str, text: str) -> None:
        rank = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}.get(level, 20)
        need = {0: 10, 1: 20, 2: 30, 3: 40}.get(self.log_level.currentIndex(), 10)
        if rank < need:
            return
        color = T.LOG_COLORS.get(level, "#c3cad8")
        line = (
            f'<span style="color:#6b7484">{ts}</span> '
            f'<span style="color:{color};font-weight:600">{level:<7}</span> '
            f'<span style="color:{color}">{html.escape(text)}</span>'
        )
        self.log_view.appendHtml(line)
        if self.chk_autoscroll.isChecked():
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _export_log(self) -> None:
        default = os.path.join(ensure_dir(self.cfg.output_dir), f"livewatch-log-{time.strftime('%Y%m%d_%H%M%S')}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", default, "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.log_view.toPlainText())
            log.info(f"日志已导出：{path}")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    # ================================================================== #
    # 其他
    # ================================================================== #
    def _tick(self) -> None:
        now = time.time()
        changed = False
        for row in self._rows.values():
            if row.status == RoomStatus.RECORDING and row.started_at:
                row.duration = now - row.started_at
                changed = True
        if changed:
            for row in self._rows.values():
                if row.items:
                    row.items[COL_DURATION].setText(fmt_duration(row.duration))
        self._refresh_summary()
        any_running = any(r.worker and r.worker.isRunning() for r in self._rows.values())
        self.btn_start_all.setEnabled(not any_running and bool(self.cfg.rooms))
        self.btn_stop_all.setEnabled(any_running)

    def _on_row_activated(self, index) -> None:
        row = self._row_at(index.row())
        if row:
            self._open_row_folder(row)

    def _row_at(self, index: int) -> Optional[RoomRow]:
        if index < 0 or index >= self.table.rowCount():
            return None
        url_item = self.table.item(index, COL_URL)
        if not url_item:
            return None
        return self._rows.get(url_item.text())

    def _open_row_folder(self, row: RoomRow) -> None:
        target = row.path if row.path and os.path.isfile(row.path) else self.cfg.output_dir
        self._open_path(target)

    def _open_output_dir(self) -> None:
        self._apply_settings(persist=False)
        self._open_path(self.cfg.output_dir)

    def _open_path(self, path: str) -> None:
        if not path:
            return
        if os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
            return
        ensure_dir(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _check_ffmpeg(self, verbose: bool = False) -> None:
        exe = resolve_ffmpeg(self.cfg.ffmpeg_path)
        ok = ffmpeg_available(self.cfg.ffmpeg_path)
        if ok:
            self.lbl_ffmpeg.setText(f"可用：{exe}")
            self.lbl_ffmpeg.setStyleSheet(f"color:{T.SUCCESS}")
            if verbose:
                log.info(f"ffmpeg 就绪：{exe}")
        else:
            self.lbl_ffmpeg.setText("未找到 ffmpeg，请手动指定 ffmpeg.exe 路径或安装后加入 PATH")
            self.lbl_ffmpeg.setStyleSheet(f"color:{T.DANGER}")
            if verbose:
                log.error("未找到 ffmpeg：录制功能不可用。请在「参数设置 → 运行环境」中指定 ffmpeg.exe 路径。")
        return ok

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "使用说明",
            "<b>使用流程</b><br>"
            "1. 粘贴直播间链接（支持 App 分享文案）→ 添加到监控列表；<br>"
            "2. 点击「启动全部监控」；<br>"
            "3. 程序按设定间隔检测开播状态，开播自动录制、下播自动停止；<br>"
            "4. 录制文件保存在输出目录，命名规则：<i>达人名称_年月日_时分秒.mp4</i>。<br><br>"
            "<b>说明</b><br>"
            "· 监测基于直播间公开页面数据；若某条目始终显示「异常」，"
            "可在日志面板查看具体原因，或在该条目中填写自有 / 已授权的直连流地址。<br>"
            "· 本工具不包含任何 AI / 视觉识别功能，也不做签名破解或风控规避。<br>"
            "· 请仅用于自有或已获授权的达人素材归档，遵守平台规则与相关法律法规。",
        )

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: D102
        self._apply_settings(persist=True)

        # 等待名称识别线程结束
        for fetcher in list(self._fetchers.values()):
            fetcher.wait(1500)
        self._fetchers.clear()

        running = [r for r in self._rows.values() if r.worker and r.worker.isRunning()]
        if running:
            if QMessageBox.question(
                self, "退出确认", f"还有 {len(running)} 个监控在运行，退出会结束当前录制（文件会正常收尾）。\n\n确定退出？"
            ) != QMessageBox.Yes:
                event.ignore()
                return
            for row in running:
                row.worker.request_stop()
            deadline = time.time() + 8
            while time.time() < deadline and any(r.worker and r.worker.isRunning() for r in running):
                for row in running:
                    if row.worker and row.worker.isRunning():
                        row.worker.wait(200)
            for row in running:
                if row.worker and row.worker.isRunning():
                    row.worker.force_abort()
                    row.worker.wait(1500)
        self._timer.stop()
        event.accept()
