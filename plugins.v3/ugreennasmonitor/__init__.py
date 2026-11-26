"""MoviePilot V3 plugin for read-only UGREEN NAS monitoring."""
from __future__ import annotations

import json
import ssl
import struct
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


def _metric(title: str, value: str, icon: str, color: str = "primary",
            progress: float | None = None, hint: str | None = None) -> dict:
    """Build a responsive native-style metric card."""
    content = [
        _node("div", props={"class": "d-flex align-center ga-2 text-medium-emphasis"}, content=[
            _node("VIcon", props={"icon": icon, "color": color, "size": "small"}),
            _node("span", title, {"class": "text-caption"}),
        ]),
        _node("div", value, {"class": "text-h5 font-weight-bold mt-2"}),
    ]
    if progress is not None:
        content.append(_node("VProgressLinear", props={
            "model-value": min(100, max(0, progress)), "height": 5,
            "rounded": True, "color": color, "class": "mt-2",
        }))
    if hint:
        content.append(_node("div", hint, {"class": "text-caption text-medium-emphasis mt-1"}))
    return _node("VCol", props={"cols": 6, "md": 3}, content=[
        _node("VCard", props={"variant": "tonal", "class": "pa-3 h-100 rounded-lg"}, content=content)
    ])

class UGreenNASMonitor(_PluginBase):
    """Display read-only UGREEN NAS health data in the plugin page and dashboard."""

    plugin_name = "绿联 NAS 监控"
    plugin_desc = "读取绿联 UGOS Pro 任务管理状态，展示 CPU、内存、温度、网络和磁盘健康。"
    plugin_icon = "https://raw.githubusercontent.com/Ray2023m/MoviePilot-Plugins/main/icons/ugreennasmonitor.svg"
    plugin_version = "1.2.0"
    plugin_author = "Ray2023m"
    author_url = "https://github.com/Ray2023m"
    plugin_config_prefix = "ugreennasmonitor_"
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._nas_url = "https://10.10.10.10:9443"
        self._token = ""
        self._verify_ssl = False
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
            self._nas_url = str(config.get("nas_url") or "https://10.10.10.10:9443").strip().rstrip("/")
            self._token = str(config.get("token") or "").strip()
            self._verify_ssl = config.get("verify_ssl", False) is True
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
            self._token = ""
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
        """Configure the NAS endpoint and its scoped OpenCLI access token."""
        return [
            {
                "component": "VForm",
                "content": [
                    {"component": "VSwitch", "props": {"model": "enabled", "label": "启用绿联 NAS 监控"}},
                    {"component": "VTextField", "props": {
                        "model": "nas_url", "label": "绿联 NAS 地址",
                        "hint": "例如 https://10.10.10.10:9443；填写 NAS 根地址，不要附加 API 路径。",
                        "persistentHint": True, "clearable": False,
                    }},
                    {"component": "VTextField", "props": {
                        "model": "token", "label": "绿联 NAS API Token",
                        "type": "password", "autocomplete": "new-password",
                        "hint": "填写 ugpoa_v1. 开头的访问令牌；只需任务管理读取权限。",
                        "persistentHint": True,
                    }},
                    {"component": "VSwitch", "props": {
                        "model": "verify_ssl", "label": "验证 HTTPS 证书",
                        "hint": "NAS 使用自签证书时关闭；使用可信证书时建议开启。",
                        "persistentHint": True,
                    }},
                    {"component": "VTextField", "props": {
                        "model": "refresh_seconds", "label": "数据缓存时间（秒）",
                        "type": "number", "min": 5, "max": 300,
                        "hint": "建议 10–30 秒。",
                        "persistentHint": True,
                    }},
                ],
            }
        ], {
            "enabled": False,
            "nas_url": "https://10.10.10.10:9443",
            "token": "",
            "verify_ssl": False,
            "refresh_seconds": 15,
        }

    @staticmethod
    def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
        value = 0
        shift = 0
        while pos < len(buf) and shift < 70:
            byte = buf[pos]
            pos += 1
            value |= (byte & 0x7f) << shift
            if byte < 0x80:
                return value, pos
            shift += 7
        raise ValueError("protobuf varint 不完整")

    @classmethod
    def _decode_message(cls, buf: bytes, schema: dict) -> dict:
        """Decode only the known RunOverview protobuf fields; safely skip unknown fields."""
        by_number = {item["number"]: item for item in schema}
        result: dict[str, Any] = {}
        pos = 0
        while pos < len(buf):
            tag, pos = cls._read_varint(buf, pos)
            number, wire = tag >> 3, tag & 7
            if number == 0:
                raise ValueError("protobuf 字段编号无效")
            field = by_number.get(number)
            if wire == 0:
                raw, pos = cls._read_varint(buf, pos)
            elif wire == 1:
                if pos + 8 > len(buf): raise ValueError("protobuf fixed64 越界")
                raw, pos = buf[pos:pos + 8], pos + 8
            elif wire == 2:
                length, pos = cls._read_varint(buf, pos)
                if length > 1024 * 1024 or pos + length > len(buf): raise ValueError("protobuf 长度越界")
                raw, pos = buf[pos:pos + length], pos + length
            elif wire == 5:
                if pos + 4 > len(buf): raise ValueError("protobuf fixed32 越界")
                raw, pos = buf[pos:pos + 4], pos + 4
            else:
                raise ValueError("protobuf wire type 不支持")
            if not field:
                continue
            kind = field["type"]
            if kind == "DOUBLE":
                if wire != 1: raise ValueError("protobuf DOUBLE wire type 错误")
                value = struct.unpack("<d", raw)[0]
            elif kind == "STRING":
                if wire != 2: raise ValueError("protobuf STRING wire type 错误")
                value = raw.decode("utf-8", errors="replace")
            elif kind == "MESSAGE":
                if wire != 2: raise ValueError("protobuf MESSAGE wire type 错误")
                value = cls._decode_message(raw, field["fields"])
            elif kind == "ENUM":
                value = ["UNSUPPORTED", "GOOD", "WARNING", "DANGER", "FAULT"][raw] if isinstance(raw, int) and 0 <= raw <= 4 else str(raw)
            else:
                value = raw
            name = field["name"]
            if field.get("repeated"):
                result.setdefault(name, []).append(value)
            else:
                result[name] = value
        return result

    def _fetch(self, force: bool = False) -> dict:
        """Call NAS OpenCLI GetRunOverview directly and decode its protobuf response."""
        with self._lock:
            if not self._enabled:
                return {"error": "插件未启用"}
            if not self._token:
                return {"error": "请先在插件设置中填写绿联 NAS API Token"}
            if not force and self._cache is not None and time.monotonic() - self._cache_at < self._refresh_seconds:
                return {"payload": self._cache, "cached": True}
            base_url = self._nas_url
            token = self._token
            verify_ssl = self._verify_ssl

        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment:
            return {"error": "NAS 地址格式无效，请填写 https://NAS_IP:9443"}
        if parsed.username or parsed.password:
            return {"error": "NAS 地址不能包含用户名或密码"}

        url = base_url.rstrip("/") + "/ugreen/opencli/v1/ugreen.taskmgr.internal.grpc/taskserv.TaskManage/GetRunOverview"
        request = Request(url, data=b"", method="POST", headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/x-protobuf",
            "Accept": "application/x-protobuf",
            "X-OpenCLI-Body-Format": "protobuf",
            "User-Agent": "MoviePilot-UGREEN-NAS-Monitor/1.1",
        })
        context = None if verify_ssl else ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=8, context=context) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("NAS 响应超过 1 MiB 限制")
                grpc_code = response.headers.get("X-GRPC-Code", "0")
                if grpc_code != "0":
                    raise RuntimeError("NAS 返回 gRPC 错误码 " + grpc_code)
            overview = self._decode_message(raw, [
                {"name": "cpu_used_percent", "number": 1, "type": "DOUBLE"},
                {"name": "cpu_temperature", "number": 2, "type": "INT32"},
                {"name": "gpu_used_percent", "number": 3, "type": "DOUBLE"},
                {"name": "mem_used_percent", "number": 4, "type": "DOUBLE"},
                {"name": "mem_used", "number": 5, "type": "UINT64"},
                {"name": "mem_total", "number": 6, "type": "UINT64"},
                {"name": "device_fans", "number": 7, "type": "MESSAGE", "repeated": True, "fields": [
                    {"name": "speed", "number": 1, "type": "INT32"},
                ]},
                {"name": "nets", "number": 8, "type": "MESSAGE", "repeated": True, "fields": [
                    {"name": "name", "number": 1, "type": "STRING"},
                    {"name": "send_rate", "number": 2, "type": "UINT64"},
                    {"name": "recv_rate", "number": 3, "type": "UINT64"},
                ]},
                {"name": "disks", "number": 9, "type": "MESSAGE", "repeated": True, "fields": [
                    {"name": "name", "number": 1, "type": "STRING"},
                    {"name": "status", "number": 2, "type": "ENUM"},
                    {"name": "disk_type", "number": 3, "type": "ENUM"},
                    {"name": "size", "number": 4, "type": "UINT64"},
                    {"name": "temperature", "number": 5, "type": "INT32"},
                    {"name": "used_percent", "number": 6, "type": "DOUBLE"},
                    {"name": "read_rate", "number": 7, "type": "UINT64"},
                    {"name": "write_rate", "number": 8, "type": "UINT64"},
                ]},
                {"name": "volume_read_rate", "number": 10, "type": "UINT64"},
                {"name": "volume_write_rate", "number": 11, "type": "UINT64"},
            ])
            payload = {"success": True, "data": overview}
            with self._lock:
                self._cache = payload
                self._cache_at = time.monotonic()
                self._error = ""
            return {"payload": payload, "cached": False}
        except HTTPError as exc:
            # Do not expose response bodies that could contain sensitive server details.
            reason = "NAS 拒绝访问（HTTP %s），请检查 Token 是否有效及是否有任务管理读取权限。" % exc.code
        except (URLError, TimeoutError, OSError):
            reason = "无法连接绿联 NAS，请检查地址、9443 端口和网络。"
        except (ValueError, RuntimeError, TypeError, AttributeError) as exc:
            reason = "读取或解析 NAS 数据失败：" + str(exc)
        logger.warning("绿联 NAS 监控读取失败：%s", reason)
        with self._lock:
            cached = self._cache
            self._error = "NAS 暂时不可用，当前显示最近一次成功数据。" if cached else reason
        if cached:
            return {"payload": cached, "cached": True, "warning": self._error}
        return {"error": self._error}

    def _view(self) -> tuple[dict | None, str, bool]:
        """Return data, user-safe error text and cache status."""
        result = self._fetch()
        return result.get("payload"), result.get("error") or result.get("warning", ""), bool(result.get("cached"))

    def _build_content(self) -> list[dict]:
        """Build a polished native-style overview from the cached NAS snapshot."""
        payload, error, cached = self._view()
        if payload is None:
            return [_node("VAlert", error or "暂无 NAS 数据", {"type": "warning", "variant": "tonal"})]

        data = payload["data"]
        cpu = _number(data.get("cpu_used_percent"))
        mem = _number(data.get("mem_used_percent"))
        gpu = _number(data.get("gpu_used_percent"))
        cpu_temp = data.get("cpu_temperature")
        fans = data.get("device_fans") or []
        fan_speed = fans[0].get("speed") if fans and isinstance(fans[0], dict) else None
        disks = data.get("disks") if isinstance(data.get("disks"), list) else []
        networks = data.get("nets") if isinstance(data.get("nets"), list) else []
        good_count = sum(1 for d in disks if isinstance(d, dict) and str(d.get("status", "")).upper() == "GOOD")

        nodes: list[dict] = []
        if error:
            nodes.append(_node("VAlert", error, {"type": "warning", "variant": "tonal", "class": "mb-3"}))

        header = [
            _node("div", "绿联 NAS · DXP4800", {"class": "text-subtitle-1 font-weight-bold"}),
            _node("div", "数据来自 NAS OpenCLI" + (" · 使用缓存数据" if cached else " · 已更新"),
                  {"class": "text-caption text-medium-emphasis"}),
            _node("VChip", "磁盘全部正常" if disks and good_count == len(disks) else
                  f"磁盘正常 {good_count}/{len(disks)}" if disks else "磁盘状态未知",
                  {"color": "success" if disks and good_count == len(disks) else "warning",
                   "size": "small", "variant": "tonal", "class": "mt-2"}),
        ]
        if fan_speed is not None:
            header.append(_node("VChip", f"风扇 {_fmt(fan_speed, 0)} RPM", {
                "prepend-icon": "mdi-fan", "size": "small", "variant": "outlined", "class": "ml-2 mt-2",
            }))
        nodes.append(_node("div", props={"class": "mb-4"}, content=header))

        nodes.append(_node("VRow", content=[
            _metric("CPU 使用率", _fmt(cpu) + "%", "mdi-cpu-64-bit", "primary", cpu),
            _metric("内存使用率", _fmt(mem) + "%", "mdi-memory", "info", mem),
            _metric("CPU 温度", f"{_fmt(cpu_temp, 0)} °C" if cpu_temp is not None else "—", "mdi-thermometer", "warning"),
            _metric("GPU 使用率", _fmt(gpu) + "%", "mdi-expansion-card", "success", gpu),
        ]))

        mem_used = _number(data.get("mem_used"))
        mem_total = _number(data.get("mem_total"))
        if mem_total > 0:
            nodes.append(_node("VCard", props={"variant": "outlined", "class": "pa-3 mt-3 rounded-lg"}, content=[
                _node("div", "内存占用详情", {"class": "text-subtitle-2 font-weight-bold mb-2"}),
                _node("div", f"{_bytes(mem_used)} / {_bytes(mem_total)}", {"class": "text-body-2 mb-2"}),
                _node("VProgressLinear", props={
                    "model-value": min(100, max(0, mem)), "height": 8, "rounded": True, "color": "info",
                }),
            ]))

        nodes.append(_node("div", props={"class": "d-flex align-center justify-space-between mt-5 mb-2"}, content=[
            _node("div", "磁盘与存储", {"class": "text-h6 font-weight-bold"}),
            _node("VChip", f"{len(disks)} 块磁盘", {"size": "small", "variant": "tonal"}),
        ]))
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
                    _node("td", content=[_node("VChip", status, {
                        "color": "success" if good else "error" if status.upper() in ("DANGER", "FAULT") else "warning",
                        "size": "small", "variant": "tonal",
                    })]),
                    _node("td", f"{_fmt(temp, 0)} °C" if temp is not None else "—"),
                    _node("td", _fmt(disk.get("used_percent")) + "%"),
                    _node("td", _bytes(disk.get("size"))),
                    _node("td", _rate(disk.get("read_rate"))),
                    _node("td", _rate(disk.get("write_rate"))),
                ]))
            nodes.append(_node("VCard", props={"variant": "outlined", "class": "rounded-lg overflow-hidden"}, content=[
                _node("VTable", props={"density": "comfortable", "hover": True}, content=[
                    _node("thead", content=[_node("tr", content=[
                        _node("th", label) for label in ["磁盘", "健康", "温度", "使用率", "容量", "读取", "写入"]
                    ])]),
                    _node("tbody", content=rows),
                ])
            ]))
        else:
            nodes.append(_node("VAlert", "接口暂未返回磁盘列表。", {"type": "info", "variant": "tonal"}))

        nodes.append(_node("div", "网络流量", {"class": "text-h6 font-weight-bold mt-5 mb-2"}))
        if networks:
            net_cards = []
            for net in networks:
                if not isinstance(net, dict):
                    continue
                net_cards.append(_node("VCol", props={"cols": 12, "sm": 6}, content=[
                    _node("VCard", props={"variant": "tonal", "class": "pa-3 rounded-lg h-100"}, content=[
                        _node("div", props={"class": "d-flex align-center ga-2 mb-3"}, content=[
                            _node("VIcon", props={"icon": "mdi-ethernet", "color": "primary"}),
                            _node("span", str(net.get("name") or "LAN"), {"class": "text-subtitle-2 font-weight-bold"}),
                        ]),
                        _node("VRow", content=[
                            _node("VCol", props={"cols": 6}, content=[
                                _node("div", "↓ 接收", {"class": "text-caption text-medium-emphasis"}),
                                _node("div", _rate(net.get("recv_rate")), {"class": "text-body-1 font-weight-bold"}),
                            ]),
                            _node("VCol", props={"cols": 6}, content=[
                                _node("div", "↑ 发送", {"class": "text-caption text-medium-emphasis"}),
                                _node("div", _rate(net.get("send_rate")), {"class": "text-body-1 font-weight-bold"}),
                            ]),
                        ]),
                    ])
                ]))
            nodes.append(_node("VRow", content=net_cards))
        else:
            nodes.append(_node("VAlert", "接口暂未返回网卡信息。", {"type": "info", "variant": "tonal"}))

        nodes.append(_node("div", "存储卷吞吐", {"class": "text-h6 font-weight-bold mt-5 mb-2"}))
        nodes.append(_node("VRow", content=[
            _node("VCol", props={"cols": 12, "md": 6}, content=[
                _node("VCard", props={"variant": "tonal", "class": "pa-3 rounded-lg h-100"}, content=[
                    _node("div", props={"class": "d-flex align-center ga-2"}, content=[
                        _node("VIcon", props={"icon": "mdi-download", "color": "success"}),
                        _node("div", "卷读取速度", {"class": "text-caption text-medium-emphasis"}),
                    ]),
                    _node("div", _rate(data.get("volume_read_rate")), {"class": "text-h6 font-weight-bold mt-2"}),
                ])
            ]),
            _node("VCol", props={"cols": 12, "md": 6}, content=[
                _node("VCard", props={"variant": "tonal", "class": "pa-3 rounded-lg h-100"}, content=[
                    _node("div", props={"class": "d-flex align-center ga-2"}, content=[
                        _node("VIcon", props={"icon": "mdi-upload", "color": "info"}),
                        _node("div", "卷写入速度", {"class": "text-caption text-medium-emphasis"}),
                    ]),
                    _node("div", _rate(data.get("volume_write_rate")), {"class": "text-h6 font-weight-bold mt-2"}),
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
