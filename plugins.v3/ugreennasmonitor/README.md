# 绿联 NAS 监控（MoviePilot V3）

直接通过绿联 UGOS Pro OpenCLI API 读取 NAS 监控数据，在 MoviePilot 插件详情页和仪表板展示。

## v1.2.0 界面优化

- 顶部设备状态与磁盘健康概览
- CPU、内存、GPU 指标增加可视化进度条
- 磁盘健康状态使用颜色标签区分
- 网卡收发速度改为独立流量卡片
- 存储卷读写速度采用卡片式展示
- 详情页继续沿用 MoviePilot 原生 Vuetify 主题，适配明暗主题

## 功能

- CPU、GPU、内存使用率
- CPU 温度、风扇转速
- HDD / SSD 健康状态、温度、容量、使用率、读写速度
- LAN 网卡收发速度
- 存储卷读写速度
- 最近一次成功数据缓存；NAS 暂时不可用时保留最后一次成功结果
- 只读访问，不执行 NAS 写入操作

## 前置条件

- 绿联 UGOS Pro，已启用 OpenCLI 访问令牌
- 令牌至少具有「任务管理」的只读权限（taskmgr_get_run_overview）
- MoviePilot 容器能够访问 NAS 的 HTTPS 管理端口（默认 9443）

## 安装与配置

1. 在 MoviePilot 设置中将 `PLUGIN_MARKET` 增加：
   `https://github.com/Ray2023m/MoviePilot-Plugins`
2. 刷新插件市场并安装「绿联 NAS 监控」。
3. 在插件设置中启用插件。
4. NAS 地址填写例如 `https://10.10.10.10:9443`。
5. 填写绿联后台生成的访问令牌（`ugpoa_v1.` 开头）。
6. NAS 使用自签 HTTPS 证书时，关闭「验证 HTTPS 证书」；若使用受信任证书则建议开启。
7. 保存后打开插件详情页。如需首页展示，在仪表板编辑中手动添加「绿联 NAS 状态」。

## 安全

- 令牌只保存在 MoviePilot 本机插件配置中，不写入 Git 仓库。
- 建议使用只读、最小权限令牌；本插件只调用 Task Manager 的 `GetRunOverview`。
- 不要把访问令牌提交到 GitHub、日志或公开聊天。
- 建议不要将 NAS 的 OpenCLI 端口直接暴露到公网。

## 接口与兼容性

- HTTP：`POST /ugreen/opencli/v1/ugreen.taskmgr.internal.grpc/taskserv.TaskManage/GetRunOverview`
- 认证：`Authorization: Bearer <access-token>`
- 请求体：Protobuf Empty（空消息）
- 响应：Protobuf RunOverview，由插件内置的轻量解码器解析。
- 默认缓存 15 秒，配置范围 5–300 秒。
- NAS 固件升级后如字段协议变化，可能需要更新插件解码器。

仪表板组件需要用户手动添加，不会擅自修改已有仪表板布局。
