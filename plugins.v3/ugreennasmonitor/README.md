# 绿联 NAS 监控（MoviePilot V3）

<p align="center">
  <img src="https://raw.githubusercontent.com/Ray2023m/MoviePilot-Plugins/main/icons/ugreennasmonitor.svg" width="96" alt="绿联 NAS 监控图标">
</p>

通过绿联 UGOS Pro OpenCLI 只读接口获取 NAS 运行概览，在 MoviePilot 插件详情页展示状态。

## v1.0.0 首发功能

- CPU、GPU、内存使用率
- CPU 温度与风扇转速
- HDD / SSD 健康状态、温度、容量、使用率、读写速度
- 网卡实时接收与发送速度
- 存储卷读写吞吐
- 指标卡片、磁盘状态标签及响应式布局
- NAS 数据本地缓存；短暂连接失败时保留最近一次成功数据
- 仅调用只读监控接口，不执行 NAS 写入操作

## 环境要求

- MoviePilot V3（系统版本 3.2.3 或更高，且低于 4）
- 绿联 UGOS Pro，已启用 OpenCLI 访问令牌
- Token 至少具有「任务管理」读取权限（`taskmgr_get_run_overview`）
- MoviePilot 容器能够访问 NAS 的 HTTPS 管理端口（默认 9443）

## 安装与配置

1. 在 MoviePilot 插件市场添加仓库：

   `https://github.com/Ray2023m/MoviePilot-Plugins`
2. 刷新插件市场并安装「绿联 NAS 监控」。
3. 在插件设置中启用监控。
4. NAS 地址填写根地址，例如 `https://10.10.10.10:9443`，不要附加 API 路径。
5. 填写绿联 NAS 后台生成的 API Token（通常以 `ugpoa_v1.` 开头）。
6. NAS 使用自签名证书时关闭「验证 HTTPS 证书」；使用可信证书时建议开启。
7. 保存设置后进入插件详情页查看监控数据。

## 安全说明

- Token 仅保存在 MoviePilot 本机插件配置中，不会写入仓库。
- 建议使用仅含任务管理读取权限的最小权限 Token。
- 不要将 Token 提交到 GitHub、日志或公开聊天中。
- 不建议将 NAS 的 OpenCLI 管理端口直接暴露到公网。

## 接口说明

- 请求方式：`POST`
- 接口路径：`/ugreen/opencli/v1/ugreen.taskmgr.internal.grpc/taskserv.TaskManage/GetRunOverview`
- 认证方式：`Authorization: Bearer <access-token>`
- 请求体：Protobuf Empty（空消息）
- 响应：Protobuf RunOverview，由插件内置轻量解码器解析
- 默认缓存：15 秒，可在 5–300 秒范围内调整
