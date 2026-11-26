"""MoviePilot V3 plugin for read-only UGREEN NAS monitoring."""
from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.sdk.plugin import _PluginBase
from app.sdk.logging import logger


def _node(component: str, text: str | None = None,
          props: dict | None = None, content: list | None = None) -> dict:
    """Build a MoviePilot native Vuetify renderer node."""
    item: dict[str, Any] = {"component": component}
    if text is not None:
        item["text"] = text
    if props:
        item["props"] = props
    if content is not None:
        item["content"] = content
    return item


def _number(value: Any, default: float = 0.0) -> float:
    """Convert a numeric API field without allowing malformed values to break the page."""
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _fmt(value: Any, digits: int = 1) -> str:
    """Format a percentage or temperature for display."""
    return f"{_number(value):.{digits}f}"


def _bytes(value: Any) -> str:
    """Format byte counts using binary units."""
    size = max(0.0, _number(value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _rate(value: Any) -> str:
    """Format bytes per second."""
    return f"{_bytes(value)}/s"


def _metric(title: str, value: str, icon: str, color: str = "primary") -> dict:
    """Build one compact metric card."""
    return _node("VCol", props={"cols": 6, "md": 3}, content=[
        _node("VCard", props={"variant": "tonal", "class": "pa-3 h-100"}, content=[
            _node("div", props={"class": "d-flex align-center ga-2 text-medium-emphasis"}, content=[
                _node("VIcon", props={"icon": icon, "color": color, "size": "small"}),
                _node("span", title, {"class": "text-caption"}),
            ]),
            _node("div", value, {"class": "text-h5 font-weight-bold mt-2"}),
        ])
    ])


class UGreenNASMonitor(_PluginBase):
    """Display read-only UGREEN NAS health data in the plugin page and dashboard."""

    plugin_name = "绿联 NAS 监控"
    plugin_desc = "读取绿联 UGOS Pro 任务管理状态，展示 CPU、内存、温度、网络和磁盘健康。"
    plugin_icon = "https://raw.githubusercontent.com/Ray2023m/MoviePilot-Plugins/main/icons/ugreennasmonitor.svg"
    plugin_version = "1.0.0"
    plugin_author = "Ray2023m"
    author_url = "https://github.com/Ray2023m"
    plugin_config_prefix = "ugreennasmonitor_"
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._url = "http://10.10.10.233:8765/api/ugreen"
        self._api_key = ""
        self._refresh_seconds = 15
        self._cache: dict | None = None
        self._cache_at = 0.0
        self._error = ""
        self._lock = threading.RLock()

    def init_plugin(self, config: dict | None = None) -> None:
        """Load settings and invalidate stale cached data after configuration changes."""
        config = config or {}
        with self._lock:
            self._enabled = config.get("enabled", False) is True
            self._url = str(config.get("url") or "http://10.10.10.233:8765/api/ugreen").strip()
            self._api_key = str(config.get("api_key") or "").strip()
            try:
                self._refresh_seconds = min(300, max(5, int(config.get("refresh_seconds", 15))))
            except (TypeError, ValueError):
                self._refresh_seconds = 15
            self._cache = None
            self._cache_at = 0.0
            self._error = ""

    def get_state(self) -> bool:
        """Return whether the plugin is enabled."""
        return self._enabled

    def stop_service(self) -> None:
        """Clear runtime credentials and cached data when the plugin is stopped."""
        with self._lock:
            self._enabled = False
            self._api_key = ""
            self._cache = None
            self._cache_at = 0.0

    @staticmethod
    def get_command() -> list[dict]:
        """This read-only monitoring plugin does not register remote commands."""
        return []

    def get_api(self) -> list[dict]:
        """No public plugin API is needed; data is fetched server-side."""
        return []

    def get_form(self) -> tuple[list[dict], dict]:
        """Return plugin settings; the bridge key is stored only in MoviePilot config."""
        return [
            {
                "component": "VForm",
                "content": [
                    {"component": "VSwitch", "props": {
                        "model": "enabled", "label": "启用绿联 NAS 监控",
                    }},
                    {"component": "VTextField", "props": {
                        "model": "url", "label": "JSON 转换服务地址",
                        "hint": "例如 http://10.10.10.233:8765/api/ugreen",
                        "persistentHint": True, "clearable": False,
                    }},
                    {"component": "VTextField", "props": {
                        "model": "api_key", "label": "转换服务访问密钥",
                        "type": "password", "autocomplete": "new-password",
                    }},
                    {"component": "VTextField", "props": {
                        "model": "refresh_seconds", "label": "数据缓存时间（秒）",
                        "type": "number", "min": 5, "max": 300,
                        "hint": "建议 10–30 秒；不会改变 NAS 本身的采样频率。",
                        "persistentHint": True,
                    }},
                ],
            }
        ], {
            "enabled": False,
            "url": "http://10.10.10.233:8765/api/ugreen",
            "api_key": "",
            "refresh_seconds": 15,
        }

    def _fetch(self, force: bool = False) -> dict:
        """Fetch a bounded JSON snapshot and retain the last good response on failure."""
        with self._lock:
            if not self._enabled:
                return {"error": "插件未启用"}
            if not self._api_key:
                return {"error": "请先在插件设置中填写转换服务访问密钥"}
            if not force and self._cache is not None and time.monotonic() - self._cache_at < self._refresh_seconds:
                return {"payload": self._cache, "cached": True}
            url = self._url
            key = self._api_key

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return {"error": "转换服务地址必须是有效的 HTTP/HTTPS URL"}
        if parsed.username or parsed.password:
            return {"error": "转换服务地址不能包含用户名或密码"}

        request = Request(url, headers={
            "Accept": "application/json",
            "X-API-Key": key,
            "User-Agent": "MoviePilot-UGREEN-NAS-Monitor/1.0",
        })
        try:
            with urlopen(request, timeout=6) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("JSON 响应超过 1 MiB 限制")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
                raise RuntimeError("NAS API 返回的数据格式不正确")
            with self._lock:
                self._cache = payload
                self._cache_at = time.monotonic()
                self._error = ""
            return {"payload": payload, "cached": False}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError, TypeError, AttributeError) as exc:
            logger.warning("绿联 NAS 监控读取失败：%s", type(exc).__name__)
            with self._lock:
                cached = self._cache
                self._error = "暂时无法连接转换服务，当前显示最近一次成功数据。" if cached else "无法连接转换服务，请检查地址、密钥和网络。"
            if cached:
                return {"payload": cached, "cached": True, "warning": self._error}
            return {"error": self._error}

    def _view(self) -> tuple[dict | None, str, bool]:
        """Return data, user-safe error text and cache status."""
        result = self._fetch()
        return result.get("payload"), result.get("error") or result.get("warning", ""), bool(result.get("cached"))

    def _build_content(self) -> list[dict]:
        """Build the full monitoring page from the same cached snapshot used by dashboard."""
        payload, error, cached = self._view()
        if payload is None:
            return [_node("VAlert", error or "暂无 NAS 数据", {"type": "warning", "variant": "tonal"})]

        data = payload["data"]
        cpu = _number(data.get("cpu_used_percent"))
        mem = _number(data.get("mem_used_percent"))
        cpu_temp = data.get("cpu_temperature")
        gpu = _number(data.get("gpu_used_percent"))
        fans = data.get("device_fans") or []
        fan_speed = fans[0].get("speed") if fans and isinstance(fans[0], dict) else None

        nodes = []
        if error:
            nodes.append(_node("VAlert", error, {"type": "warning", "variant": "tonal", "class": "mb-3"}))
        nodes.append(_node("div", "绿联 NAS 实时状态" + (" · 缓存数据" if cached else ""), {
            "class": "text-caption text-medium-emphasis mb-3",
        }))
        nodes.append(_node("VRow", content=[
            _metric("CPU 使用率", _fmt(cpu) + "%", "mdi-cpu-64-bit"),
            _metric("内存使用率", _fmt(mem) + "%", "mdi-memory"),
            _metric("CPU 温度", f"{_fmt(cpu_temp, 0)} °C" if cpu_temp is not None else "—", "mdi-thermometer"),
            _metric("GPU 使用率", _fmt(gpu) + "%", "mdi-expansion-card"),
            _metric("风扇转速", f"{_fmt(fan_speed, 0)} RPM" if fan_speed is not None else "—", "mdi-fan"),
        ]))

        mem_used = _number(data.get("mem_used"))
        mem_total = _number(data.get("mem_total"))
        if mem_total > 0:
            nodes.append(_node("VCard", props={"variant": "outlined", "class": "pa-3 mt-3"}, content=[
                _node("div", "内存占用", {"class": "text-subtitle-2 mb-2"}),
                _node("div", f"{_bytes(mem_used)} / {_bytes(mem_total)}", {"class": "text-body-2 mb-2"}),
                _node("VProgressLinear", props={
                    "model-value": min(100, max(0, mem)), "height": 8, "rounded": True,
                    "color": "primary",
                }),
            ]))

        disks = data.get("disks") if isinstance(data.get("disks"), list) else []
        nodes.append(_node("div", "磁盘状态", {"class": "text-h6 mt-5 mb-2"}))
        if disks:
            rows = []
            for disk in disks:
                if not isinstance(disk, dict):
                    continue
                status = str(disk.get("status") or "UNKNOWN")
                good = status.upper() == "GOOD"
                temp = disk.get("temperature")
                rows.append(_node("tr", content=[
                    _node("td", str(disk.get("name") or "未命名磁盘")),
                    _node("td", status, {"class": "text-success" if good else "text-error"}),
                    _node("td", f"{_fmt(temp, 0)} °C" if temp is not None else "—"),
                    _node("td", _fmt(disk.get("used_percent")) + "%"),
                    _node("td", _bytes(disk.get("size"))),
                    _node("td", _rate(disk.get("read_rate"))),
                    _node("td", _rate(disk.get("write_rate"))),
                ]))
            nodes.append(_node("VTable", props={"density": "comfortable", "hover": True}, content=[
                _node("thead", content=[_node("tr", content=[
                    _node("th", label) for label in ["磁盘", "健康", "温度", "使用率", "容量", "读取", "写入"]
                ])]),
                _node("tbody", content=rows),
            ]))
        else:
            nodes.append(_node("VAlert", "接口暂未返回磁盘列表。", {"type": "info", "variant": "tonal"}))

        networks = data.get("nets") if isinstance(data.get("nets"), list) else []
        nodes.append(_node("div", "网络状态", {"class": "text-h6 mt-5 mb-2"}))
        if networks:
            net_rows = []
            for net in networks:
                if not isinstance(net, dict):
                    continue
                net_rows.append(_node("tr", content=[
                    _node("td", str(net.get("name") or "LAN")),
                    _node("td", _rate(net.get("recv_rate"))),
                    _node("td", _rate(net.get("send_rate"))),
                ]))
            nodes.append(_node("VTable", props={"density": "comfortable"}, content=[
                _node("thead", content=[_node("tr", content=[
                    _node("th", label) for label in ["网卡", "接收", "发送"]
                ])]),
                _node("tbody", content=net_rows),
            ]))

        nodes.append(_node("VRow", content=[
            _node("VCol", props={"cols": 12, "md": 6}, content=[
                _node("VCard", props={"variant": "outlined", "class": "pa-3 mt-3"}, content=[
                    _node("div", "卷读取速度", {"class": "text-caption text-medium-emphasis"}),
                    _node("div", _rate(data.get("volume_read_rate")), {"class": "text-h6"}),
                ])
            ]),
            _node("VCol", props={"cols": 12, "md": 6}, content=[
                _node("VCard", props={"variant": "outlined", "class": "pa-3 mt-3"}, content=[
                    _node("div", "卷写入速度", {"class": "text-caption text-medium-emphasis"}),
                    _node("div", _rate(data.get("volume_write_rate")), {"class": "text-h6"}),
                ])
            ]),
        ]))
        return nodes

    def get_page(self) -> list[dict]:
        """Render CPU, memory, temperatures, disks, network and volume throughput."""
        if not self.get_state():
            return [_node("VAlert", "请先在插件设置中启用绿联 NAS 监控。", {
                "type": "info", "variant": "tonal",
            })]
        return self._build_content()

    def get_dashboard_meta(self) -> list[dict[str, str]]:
        """Register one optional dashboard tile without changing user dashboard settings."""
        return [{"key": "overview", "name": "绿联 NAS 状态"}] if self.get_state() else []

    def get_dashboard(self, key: str, **kwargs):
        """Return a compact status tile using the host's dashboard renderer."""
        if key != "overview" or not self.get_state():
            return None
        payload, error, cached = self._view()
        if payload is None:
            return (
                {"cols": 12, "md": 6},
                {"title": "绿联 NAS", "refresh": 60, "border": True},
                [_node("VAlert", error or "暂无 NAS 数据", {"type": "warning", "variant": "tonal"})],
            )
        data = payload["data"]
        disks = data.get("disks") if isinstance(data.get("disks"), list) else []
        bad_disks = [d for d in disks if isinstance(d, dict) and str(d.get("status", "")).upper() != "GOOD"]
        cpu = _fmt(data.get("cpu_used_percent")) + "%"
        mem = _fmt(data.get("mem_used_percent")) + "%"
        temp = f"{_fmt(data.get('cpu_temperature'), 0)} °C" if data.get("cpu_temperature") is not None else "—"
        disk_label = f"{len(disks) - len(bad_disks)}/{len(disks)} 磁盘正常" if disks else "未获取磁盘信息"
        status_color = "success" if not bad_disks and disks else "warning"
        content = []
        if error:
            content.append(_node("VAlert", error, {"type": "warning", "variant": "tonal", "density": "compact"}))
        content.append(_node("VRow", content=[
            _metric("CPU", cpu, "mdi-cpu-64-bit"),
            _metric("内存", mem, "mdi-memory"),
            _metric("CPU 温度", temp, "mdi-thermometer"),
            _metric("磁盘健康", disk_label, "mdi-harddisk", status_color),
        ]))
        if bad_disks:
            content.append(_node("VAlert", "异常磁盘：" + "、".join(str(d.get("name") or "未命名") for d in bad_disks),
                                 {"type": "error", "variant": "tonal", "class": "mt-2"}))
        return (
            {"cols": 12, "md": 6},
            {"title": "绿联 NAS 状态" + (" · 缓存" if cached else ""), "refresh": 60, "border": True},
            content,
        )
