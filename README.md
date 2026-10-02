# qwen38-mlx-serving

`qwen38-mlx-serving` 是一个面向 Apple Silicon (macOS arm64) 的轻量级 Python 3.12+ 标准库包装器，用于管理第三方原生推理引擎 `mlx-serve` (v26.10.1) 并部署 `Qwen3.8-Flash-Next` (iQ 4.7bpw) 大语言模型，提供兼容 OpenAI 的本地 HTTP 推理接口。

> [!IMPORTANT]
> **项目定位与架构边界**
> - 本项目仅为**第三方开源引擎** `mlx-serve` 的 Python 标准库调度包装层，并非 Apple 官方维护或支持的 Serving 产品。
> - 核心管理逻辑不导入或运行 Python MLX 张量库，直接调度预编译的 macOS arm64 原生可执行文件。
> - 运行 Profile 基于 Apple Silicon M5 Max (40 核 GPU, 128 GiB 统一内存) 实机调优。在其他芯片架构或不同内存容量硬件上的可移植性与性能表现未经实测验证。


## 快速开始

核心命令行工具完全依赖 Python 3.12+ 标准库，基础管理流程无需安装外部 Python 包。

先 clone 本仓库，并确认 `python3.12 --version`。macOS 自带的 `python3` 可能低于 3.12。

```bash
git clone https://github.com/grapeot/qwen38-mlx-serving.git
cd qwen38-mlx-serving
```

### 1. 环境自检与规划
```bash
# 检查 Python 版本、CPU 架构、统一内存与系统内核参数
python3.12 scripts/qwen38.py doctor

# 查看原生引擎安装计划（完全离线，不产生网络请求）
python3.12 scripts/qwen38.py install-engine --plan

# 安装并核对固定 SHA 的原生 mlx-serve 引擎
python3.12 scripts/qwen38.py install-engine
```

### 2. 模型下载与完整性校验
```bash
# 查看模型版本、大小和目标路径；逐文件清单在 manifests/model.json（完全离线）
python3.12 scripts/qwen38.py download --plan

# 默认下载方式需要 Hugging Face CLI；按需安装扩展依赖
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[download,benchmark]'

# 执行下载；这会传输约 107.3 GB
.venv/bin/python scripts/qwen38.py download

# 强校验全部 113 个模型文件与 32GB 规范 N-gram 表
python3.12 scripts/qwen38.py verify
```

> 截至 2026-10-02，完整社区模型尚未下载和实测。当前发布已通过离线测试；历史组合包的结果见 [性能说明](docs/benchmark.md)，不能视作完整社区模型的结果。

### 3. 服务启停与状态检查
```bash
# 启动本地推理服务（默认监听 127.0.0.1:11234）
python3.12 scripts/qwen38.py start

# 查看受管 PID 与记录的启动配置
python3.12 scripts/qwen38.py status

# 运行自动化功能冒烟验证（中文对话、本地合成工具调用、思考算术）
python3.12 scripts/qwen38.py check

# 优雅停止推理服务
python3.12 scripts/qwen38.py stop
```


## 本地 API 接入

服务启动后，在本地环回地址暴露 OpenAI 兼容接口：
- **Base URL**: `http://127.0.0.1:11234/v1`
- **Model ID**: 动态解析自模型目录名称（默认为 `qwen38-flash-next-iq47`，可通过 `GET /v1/models` 获取）
- **API Key**: 本地调用若客户端要求认证，可传入占位符 `local`

### cURL 请求示例
```bash
curl http://127.0.0.1:11234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local" \
  -d '{
    "model": "qwen38-flash-next-iq47",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "用两句话介绍投机解码 (Speculative Decoding) 的核心价值。"}
    ],
    "temperature": 0.7
  }'
```

> [!TIP]
> **Token 预算约定**：请求中无需显式传递 `max_tokens` 或 `max_completion_tokens`。服务端在缺省情况下会自动使用剩余的主上下文预算，并在遇到 EOS 标记时自动终止。请注意，部分客户端 SDK可能会隐式注入 32768 的输出上限。


## 数据目录与运行边界

权重和引擎默认存放在 `~/.local/share/qwen38-serving`，PID、启动配置和日志存放在 `~/.local/state/qwen38-serving`。可通过 CLI 参数或环境变量改路径，见 [下载指南](docs/download.md)。

服务单请求并发，默认关闭视觉和思考，配置主上下文 262144（输入与输出共享）；完整 262K 尚未实测。包装器不设置服务端输出上限，也不安装登录自启项。端口占用时退出；停止操作只向确认属于本包装器的 PID 发送 SIGTERM。

## AI 安装与使用指南

人类用户可直接将本仓库 Git URL 提供给兼容环境上的 AI 安装 Agent：
1. **优先读取宿主环境规则**：AI Agent 应先查阅目标工作区的 `AGENTS.md`、`CLAUDE.md` 或相关路由规则。
2. **读取本仓库规范**：阅读本仓库根目录的 [AGENTS.md](AGENTS.md) 以及专属技能文件 [skills/qwen38-serving/SKILL.md](skills/qwen38-serving/SKILL.md)。
3. **集成技能定义**：将 [skills/qwen38-serving/SKILL.md](skills/qwen38-serving/SKILL.md) 按宿主环境约定注册至技能索引。本技能为纯 Markdown 指南，无需特定厂商打包格式。
4. **遵守授权约束**：遵守用户当前任务范围和暂停约束；明确的安装请求可在其授权范围内执行安装。


## 上游项目与开源协议

- **包装器源码**：采用 [MIT License](LICENSE)。
- **原生引擎**：基于第三方 [mlx-serve v26.10.1](https://github.com/ddalcu/mlx-serve/releases/tag/v26.10.1) 原生二进制，安装时保留上游包内 LICENSE 与 NOTICE，仓库不附带引擎二进制。引擎 API 参考请查阅 [mlx-serve API Documentation](https://github.com/ddalcu/mlx-serve/blob/v26.10.1/docs/api.md)。
- **社区模型权重**：基于 Hugging Face 社区模型 [ddalcu/Qwen3.8-Flash-Next-MLX-Serve-iQ-MLX-4.7bpw](https://huggingface.co/ddalcu/Qwen3.8-Flash-Next-MLX-Serve-iQ-MLX-4.7bpw)（指定 Revision `dafff5c3d8168c9d13275661153911096499a80a`），模型权重遵循原作者与 Qwen 社区许可协议。
- **性能讨论参考**：上游投机解码讨论参见 [mlx-serve PR #427](https://github.com/ddalcu/mlx-serve/pull/427)。
