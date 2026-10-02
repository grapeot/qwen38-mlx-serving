# 产品需求文档 (PRD) - qwen38-mlx-serving

## 1. 项目目标

让拥有兼容 Apple Silicon Mac 的人或 AI，凭本仓库完成固定版本引擎和完整社区模型的安装、校验、启停与 API 检查，并在需要时复测性能。推理实现由第三方 `mlx-serve` 和 Apple MLX 提供，本项目维护配置与运行入口。

## 2. 目标用户与使用场景

1. **拥有高配 Apple Silicon 的开发者与研究人员**：
   - 拥有 M5 Max 128GB 等设备，需要利用本地统一内存运行超长上下文（最高 262K）推理，作为日常开发、长文档分析或本地 Agent 的后端引擎。
2. **自动化部署与运维 AI Agent**：
   - 作为宿主环境的子系统，由 AI Agent 自动化安装、验证、调度与自检，要求 CLI 行为确定、具备离线预检能力且具备清晰的错误边界。


## 3. 非目标 (Non-Goals)

为保持软件纯粹与稳定，本项目明确将以下功能列为非目标：
- **不开发独立的推理张量内核**：不重写 Python MLX 或 C++ 推理算子，完全复用第三方原生发布版 `mlx-serve`。
- **不做多模型多租户调度器**：专注于 `Qwen3.8-Flash-Next` 专用 Profile 的单例管理，不提供模型热切换、多租户配额或微服务集群编排。
- **不提供 Web UI**：不开发独立前端；引擎自带的界面由上游维护。
- **不注册开机守护进程**：不修改系统 `launchd` 配置，不注册常驻登录启动项。
- **不自动清理用户数据**：绝不隐式删除旧模型或缓存文件。


## 4. 功能性需求

- `doctor` 报告 Python、系统、架构、磁盘空间及可读取的内存参数，不自动修改系统设置。
- `install-engine` 使用固定 release、大小和 SHA-256，保留二进制、动态库和许可文件。
- `download` 默认调用 Hugging Face CLI，指定 revision 和独立缓存；另提供标准库 HTTP 续传。两种方式均在下载后独立校验全部文件。
- `install-engine --plan`、`download --plan` 不联网、不创建数据目录；逐文件清单见 `manifests/model.json`。
- `verify` 检查 113 个文件的大小与哈希，写入 `.qwen38-verified.json`；启动时检查清单、文件大小和 mtime 是否仍与标记一致。
- `start`、`stop`、`status` 管理受管进程，记录保存在 `server.json`；只发送 SIGTERM，最多等待 40 秒。
- `check` 验证中文输出、合成工具往返和启用思考的算术结果，原始结果留在运行目录。
- `benchmark` 测七档上下文，记录冷缓存、实际 tokens、原始请求/响应及两种速率；`plot` 生成曲线。测试协议见 [benchmark.md](benchmark.md)。

## 5. 非功能性需求 (Non-Functional Requirements)

1. **依赖极简性**：核心管理和 HTTP 下载使用 Python 3.12+ 标准库；默认 HF 下载以及 benchmark / plot 需要相应扩展依赖。
2. **文件隔离与整洁**：
   - 仓库工作区保持干净，仅包含代码、脚本、文档与清单。
   - 权重与引擎二进制分别隔离在 `~/.local/share/qwen38-serving`。
   - 进程 PID、日志与运行时配置存放在 `~/.local/state/qwen38-serving`。
3. **真实性与可信度**：所有基准测试数据必须明确来源。文档中保留的测试数据统一注明为 `HISTORICAL LOCAL COMPOSITE, canonical NOT tested`。
