# 绿联 NAS 监控（MoviePilot V3）

在 MoviePilot V3 插件详情页和首页仪表板查看绿联 UGOS Pro NAS 状态。

## 功能

- CPU、GPU、内存使用率
- CPU 温度、风扇转速
- HDD / SSD 健康状态、温度、容量、使用率、读写速度
- LAN 网卡收发速度
- 存储卷读写速度
- 最近一次成功数据缓存；转换服务暂时不可用时保留最后一次成功结果
- 只读访问，不执行 NAS 写入操作

## 前置条件

需要先在 NAS 侧或同一内网主机部署 JSON 转换服务。当前插件使用已验证的接口：

`http://10.10.10.233:8765/api/ugreen`

转换服务请求头：

`X-API-Key: <bridge-api-key>`

响应结构应与 `unc taskmgr overview` 一致：

```json
{
  "success": true,
  "data": {
    "cpu_used_percent": 12.53,
    "cpu_temperature": 34,
    "gpu_used_percent": 0,
    "mem_used_percent": 40.38,
    "mem_used": "6677118976",
    "mem_total": "16535777280",
    "device_fans": [{"speed": 660}],
    "nets": [{"name": "LAN1", "send_rate": "0", "recv_rate": "0"}],
    "disks": []
  }
}
```

## 安装

1. 在 GitHub 创建公开仓库 `Ray2023m/MoviePilot-Plugins`。
2. 将本仓库文件按原目录提交到仓库 `main` 分支。
3. MoviePilot 设置中将 `PLUGIN_MARKET` 增加：
   `https://github.com/Ray2023m/MoviePilot-Plugins`
4. 在插件市场刷新并安装「绿联 NAS 监控」。
5. 在插件设置中启用插件，填写转换服务 URL 和 `API_KEY`。
6. 保存后打开插件详情页；如需首页展示，在 MoviePilot 仪表板编辑中手动添加「绿联 NAS 状态」。

## 安全

- NAS OpenCLI Token 只保存在 JSON 转换服务，不要填入 MoviePilot 插件或 GitHub。
- 插件只保存转换服务的 API_KEY。请使用随机生成的高强度密钥。
- 不要把转换服务端口暴露到公网。
- 建议转换服务仅监听内网地址，并限制访问来源。
- 插件请求超时为 6 秒，最大读取响应体为 1 MiB；日志不会输出 URL 查询参数或密钥。

## 说明

- 插件只负责读取和展示数据；NAS 指标的采样频率由 UGOS API 决定。
- 页面刷新与仪表板刷新会命中插件缓存，默认缓存 15 秒。
- 仪表板组件需要用户手动添加，不会擅自修改已有仪表板布局。
