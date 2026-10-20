# -*- coding: utf-8 -*-
"""
抖音直播间状态探测与流地址解析。

合规声明
--------
本模块只做两件事：
  1. 请求直播间公开页面 / 公开 Web 接口，读取其中「是否在播」等公开字段；
  2. 从这些公开返回的数据里读取播放器自身使用的流地址（与浏览器播放同一来源）。
不涉及签名破解、加密逆向、付费内容绕过或任何风控规避手段。
若目标直播间无法自动解析，使用者可填写自有 / 已授权的直连流地址。
"""

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import requests

# --------------------------------------------------------------------------- #
# 链接解析
# --------------------------------------------------------------------------- #

URL_RE = re.compile(r"https?://[^\s，,。；;'\"）)】\]]+", re.I)
LIVE_RID_RE = re.compile(r"live\.douyin\.com/(\d+)", re.I)
ROOM_ID_RE = re.compile(r"^\d{5,20}$")


@dataclass
class LiveInfo:
    """一次状态探测的结果。"""

    is_live: bool = False
    title: str = ""
    nickname: str = ""
    room_id: str = ""
    flv_urls: Dict[str, str] = field(default_factory=dict)
    hls_urls: Dict[str, str] = field(default_factory=dict)
    source: str = ""            # 数据来源，便于排查
    error: str = ""             # 非空表示本次探测失败

    @property
    def ok(self) -> bool:
        return not self.error

    def best_stream_url(self) -> str:
        """按清晰度优先级挑选一条流地址。"""
        for key in ("FULL_HD1", "HD1", "SD1", "SD2", "ORIGIN"):
            if self.flv_urls.get(key):
                return self.flv_urls[key]
        for key in ("FULL_HD1", "HD1", "SD1", "SD2"):
            if self.hls_urls.get(key):
                return self.hls_urls[key]
        if self.flv_urls:
            return next(iter(self.flv_urls.values()))
        if self.hls_urls:
            return next(iter(self.hls_urls.values()))
        return ""


def extract_room_ref(text: str) -> str:
    """
    从用户粘贴的内容中提取直播间标识。

    支持：完整链接、App 分享文案（含 v.douyin.com 短链）、纯房间号。
    返回形如 ``https://live.douyin.com/123456`` 的规范链接，无法识别时返回空串。
    """
    text = (text or "").strip()
    if not text:
        return ""

    if ROOM_ID_RE.match(text):
        return f"https://live.douyin.com/{text}"

    m = LIVE_RID_RE.search(text)
    if m:
        return f"https://live.douyin.com/{m.group(1)}"

    u = URL_RE.search(text)
    if u:
        return u.group(0).rstrip("/")
    return ""


def _rid_from_url(url: str) -> str:
    m = LIVE_RID_RE.search(url or "")
    return m.group(1) if m else ""


# React flight 数据里的占位符（undefined 会被序列化成 "$undefined"）
JUNK_VALUES = {"$undefined", "undefined", "null", "none", "nan", "-"}


def clean_text(value: Any) -> str:
    """
    清理从页面数据里取到的文本。

    flight 数据中的 undefined 会以 ``"$undefined"`` 字面量出现，
    若不过滤就会混进文件名（例如 ``$undefined_20261015_134800.mp4``）。
    """
    if not isinstance(value, str):
        return ""
    v = value.strip()
    if not v or v.lower() in JUNK_VALUES or v.startswith("$"):
        return ""
    return v


# --------------------------------------------------------------------------- #
# 公开 Web 接口 / 页面解析
# --------------------------------------------------------------------------- #

ENTER_API = "https://live.douyin.com/webcast/room/web/enter/"

ENTER_PARAMS = {
    "aid": "6383",
    "app_name": "douyin_web",
    "live_id": "1",
    "device_platform": "web",
    "language": "zh-CN",
    "enter_from": "web_live",
    "cookie_enabled": "true",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_version": "126.0.0.0",
}

# 直播中 / 未开播 的关键词（页面兜底判断用）
OFFLINE_HINTS = ("直播已结束", "暂未开播", "未开播", "已下播")
LIVE_HINTS = ("flv_pull_url", "hls_pull_url", "stream_url")


def _iter_dicts(obj: Any) -> Iterator[Any]:
    """深度遍历嵌套结构。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


def _deep_get(obj: Any, key: str) -> Any:
    """在嵌套结构中按 key 深度查找，返回首个命中值。"""
    for d in _iter_dicts(obj):
        if key in d:
            return d[key]
    return None


def _collect_pull_urls(blob: Any) -> "tuple[Dict[str, str], Dict[str, str]]":
    """
    从任意嵌套结构中收集 flv / hls 地址表。

    兼容几种常见结构：
      {"flv_pull_url": {"FULL_HD1": "http://...flv"}}
      {"hls_pull_url_map": {"FULL_HD1": "http://...m3u8"}}
      {"hls_pull_url": "http://...m3u8"}
      {"default_pull_url": "http://...flv"}
    """
    flv: Dict[str, str] = {}
    hls: Dict[str, str] = {}

    def is_url(v: Any) -> bool:
        return isinstance(v, str) and v.startswith("http")

    for d in _iter_dicts(blob):
        for key, val in d.items():
            lk = str(key).lower()
            if lk in ("flv_pull_url", "flv_pull_url_map") and isinstance(val, dict):
                for q, u in val.items():
                    if is_url(u):
                        flv.setdefault(str(q), u)
            elif lk in ("hls_pull_url_map", "hls_pull_url") and isinstance(val, dict):
                for q, u in val.items():
                    if is_url(u):
                        hls.setdefault(str(q), u)
            elif lk == "hls_pull_url" and is_url(val):
                hls.setdefault("ORIGIN", val)
            elif lk == "default_pull_url" and is_url(val):
                flv.setdefault("DEFAULT", val)
    return flv, hls


class DouyinClient:
    """轻量 HTTP 客户端，只读取公开数据。"""

    def __init__(self, user_agent: str, cookie: str = "", timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://live.douyin.com/",
            }
        )
        if cookie:
            self.session.headers["Cookie"] = cookie

    def update(self, user_agent: str, cookie: str, timeout: int) -> None:
        self.timeout = timeout
        self.session.headers["User-Agent"] = user_agent
        if cookie:
            self.session.headers["Cookie"] = cookie
        else:
            self.session.headers.pop("Cookie", None)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def expand(self, url: str) -> str:
        """展开短链，拿到最终直播间链接。"""
        if _rid_from_url(url):
            return url
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            final = str(resp.url)
            if _rid_from_url(final):
                return final
            m = LIVE_RID_RE.search(resp.text[:20000])
            if m:
                return f"https://live.douyin.com/{m.group(1)}"
        except requests.RequestException:
            pass
        return url

    def fetch_status(self, url: str) -> LiveInfo:
        """
        探测直播间状态。

        :param url: 直播间链接（live.douyin.com/<rid>）或纯房间号
        """
        ref = extract_room_ref(url) or url
        if not _rid_from_url(ref):
            ref = self.expand(ref)
        rid = _rid_from_url(ref)
        if not rid:
            return LiveInfo(error="无法从链接中解析出直播间号，请粘贴 live.douyin.com 开头的直播间链接")

        errors: List[str] = []

        info = self._via_enter_api(rid)
        if info and info.ok:
            return info
        if info and info.error:
            errors.append(f"接口: {info.error}")

        info = self._via_page(rid)
        if info and info.ok:
            return info
        if info and info.error:
            errors.append(f"页面: {info.error}")

        return LiveInfo(room_id=rid, error="；".join(errors) or "状态探测失败")

    # ------------------------------------------------------------------ #
    def _via_enter_api(self, rid: str) -> Optional[LiveInfo]:
        """读取直播间公开 Web 接口。"""
        params = dict(ENTER_PARAMS)
        params["web_rid"] = rid
        try:
            resp = self.session.get(ENTER_API, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return LiveInfo(room_id=rid, error=f"HTTP {resp.status_code}")
            payload = resp.json()
        except ValueError:
            return LiveInfo(room_id=rid, error="返回内容不是 JSON")
        except requests.RequestException as exc:
            return LiveInfo(room_id=rid, error=type(exc).__name__)

        if payload.get("status_code") not in (0, None):
            return LiveInfo(room_id=rid, error=f"业务码 {payload.get('status_code')}")

        data = payload.get("data") or {}
        rooms = data.get("data") or []
        room = rooms[0] if isinstance(rooms, list) and rooms else {}

        flv, hls = _collect_pull_urls(room)
        status = room.get("status")
        room_status = data.get("room_status")
        owner = room.get("owner") or {}
        nickname = owner.get("nickname") or _deep_get(data, "nickname") or ""
        is_live = bool(status == 2 or flv or hls)
        if not is_live and room_status == 0 and status is None:
            is_live = False

        return LiveInfo(
            is_live=is_live,
            title=clean_text(room.get("title")),
            nickname=clean_text(nickname),
            room_id=str(room.get("id_str") or rid),
            flv_urls=flv,
            hls_urls=hls,
            source="web接口",
        )

    # ------------------------------------------------------------------ #
    def _via_page(self, rid: str) -> Optional[LiveInfo]:
        """请求直播间页面，从内嵌数据中解析状态。"""
        url = f"https://live.douyin.com/{rid}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return LiveInfo(room_id=rid, error=f"HTTP {resp.status_code}")
            html = resp.text
        except requests.RequestException as exc:
            return LiveInfo(room_id=rid, error=type(exc).__name__)

        for marker in ("_ROUTER_DATA", "RENDER_DATA", "__INIT_PROPS__"):
            blob = self._extract_embedded_json(html, marker)
            if not blob:
                continue
            flv, hls = _collect_pull_urls(blob)
            if flv or hls:
                return LiveInfo(
                    is_live=True,
                    nickname=clean_text(_deep_get(blob, "nickname")),
                    title=clean_text(_deep_get(blob, "title")),
                    room_id=rid,
                    flv_urls=flv,
                    hls_urls=hls,
                    source=f"页面/{marker}",
                )

        # 页面数据通常是 React flight 分块（含转义引号），先反转义再做括号配对提取
        plain = self._unescape_html(html)
        flv: Dict[str, str] = {}
        hls: Dict[str, str] = {}
        for key in ("flv_pull_url", "flv_pull_url_map"):
            obj = self._extract_object_after(plain, key)
            if isinstance(obj, dict):
                for q, u in obj.items():
                    if isinstance(u, str) and u.startswith("http"):
                        flv.setdefault(str(q), u)
        for key in ("hls_pull_url_map",):
            obj = self._extract_object_after(plain, key)
            if isinstance(obj, dict):
                for q, u in obj.items():
                    if isinstance(u, str) and u.startswith("http"):
                        hls.setdefault(str(q), u)
        m = re.search(r'"hls_pull_url"\s*:\s*"(https?://[^"]+)"', plain)
        if m:
            hls.setdefault("ORIGIN", m.group(1))

        if flv or hls:
            return LiveInfo(
                is_live=True,
                nickname=self._regex_str(plain, "nickname"),
                title=self._regex_str(plain, "title"),
                room_id=rid,
                flv_urls=flv,
                hls_urls=hls,
                source="页面/内嵌数据",
            )

        # 未开播时也尝试取一次主播昵称（用于「添加链接后立刻显示真实名称」）
        fallback_nick = self._regex_str(plain, "nickname")
        if fallback_nick:
            return LiveInfo(
                is_live=False,
                nickname=fallback_nick,
                title=self._regex_str(plain, "title"),
                room_id=rid,
                source="页面/内嵌数据",
            )

        if any(h in plain for h in OFFLINE_HINTS) or '"room_status":2' in plain:
            return LiveInfo(is_live=False, room_id=rid, source="页面/关键词")

        if not any(h in plain for h in LIVE_HINTS) and len(plain) > 2000:
            # 页面能打开但没有播放相关字段，通常就是未开播
            return LiveInfo(is_live=False, room_id=rid, source="页面/无流字段")

        return LiveInfo(room_id=rid, error="未能从页面中识别开播状态")

    # ------------------------------------------------------------------ #
    @staticmethod
    def _unescape_html(html: str) -> str:
        """还原 flight 分块数据里的转义字符，便于直接匹配 JSON 片段。"""
        return (
            html.replace("\\u0026", "&")
            .replace("\\u002F", "&")
            .replace("\\/", "/")
            .replace('\\"', '"')
        )

    @staticmethod
    def _extract_object_after(text: str, key: str) -> Optional[Any]:
        """定位 ``"<key>":{`` 并返回括号配对得到的 JSON 对象。"""
        m = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', text)
        if not m:
            return None
        start = m.end() - 1
        depth, i, in_str, esc = 0, start, False, False
        while i < len(text):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except Exception:
                            return None
            i += 1
        return None

    @staticmethod
    def _extract_embedded_json(html: str, marker: str) -> Optional[Any]:
        """
        提取页面内嵌 JSON，兼容两种写法：

          marker = { ... }                      普通 JSON
          marker = "%7B%22state%22..."          URL 编码字符串
        """
        idx = html.find(marker)
        if idx < 0:
            return None

        qm = re.search(rf'{re.escape(marker)}\s*=\s*"([^"]+)"', html[idx : idx + 300])
        if qm:
            return DouyinClient._try_loads(urllib.parse.unquote(qm.group(1)))

        start = html.find("{", idx)
        if start < 0:
            return None
        depth, i, in_str, esc = 0, start, False, False
        while i < len(html):
            ch = html[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        raw = html[start : i + 1]
                        return DouyinClient._try_loads(raw)
            i += 1
        return None

    @staticmethod
    def _try_loads(raw: str) -> Optional[Any]:
        for candidate in (raw, urllib.parse.unquote(raw)):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _regex_str(html: str, key: str) -> str:
        """取该 key 的第一个有效文本值（跳过 $undefined 之类占位符）。"""
        for m in re.finditer(rf'"{re.escape(key)}"\s*:\s*"([^"]{{1,80}})"', html):
            cleaned = clean_text(m.group(1))
            if cleaned:
                return cleaned
        return ""
