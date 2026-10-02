# AGENTS.md - AI 运维与接入准则

本文件为自动化 Agent（包括安装 Agent、巡检 Agent 及编码助手）在接入、配置和维护 `qwen38-mlx-serving` 时的首要行动指南与操作规范。


## 1. 目标与当前边界

在兼容的 Mac 上安装固定版本的完整社区模型，提供可检查、可复测的本地 API。先读宿主工作区规则；用户当前的下载暂停和任务范围优先。本仓库不代替用户授予发布、删除数据或新增后台任务的权限。

截至 2026-10-02，完整社区模型尚未实测，发布仅完成离线检查。历史数据属于旧组合包。不得把历史速度写成完整社区模型的结果。

保留旧服务和权重时，避免同时加载两份大模型。包装器遇到端口占用会退出，停止时校验 PID 归属。旧权重清理仅在用户授权后使用 `trash PATH`；不自动删除或清空 Trash。

公开文件不包含个人路径、凭证、运行日志或权重。默认模型和状态目录均在 repo 外。修改源码后更新 `docs/working.md`；只有用户明确要求时才 commit 或 push。

## 2. CLI 命令矩阵速查

核心调度脚本为 `scripts/qwen38.py`，基础命令仅依赖 Python 3.12+ 标准库。

| 命令 | 参数与选项 | 说明与前置条件 |
| :--- | :--- | :--- |
| `doctor` | 无 | 环境自检：检查 Python 版本、CPU 架构、统一内存及 `iogpu.wired_limit_mb` |
| `install-engine` | `[--plan]` | 安装原生 `mlx-serve` 26.10.1 二进制；带 `--plan` 时仅离线打印下载源与 SHA |
| `download` | `[--plan] [--transport hf\|http]` | 下载模型权重与 N-gram 表；`--plan` 完全离线；实际下载遵守用户当前约束 |
| `verify` | 无 | 强校验模型目录内 113 个文件的大小与 LFS SHA-256 / Git blob SHA-1 |
| `start` | `[--cold-cache]` | 启动本地推理服务；检测端口冲突；`--cold-cache` 禁用前缀缓存，供冷缓存测试 |
| `stop` | 无 | 读取受管 PID，向其发送 SIGTERM 优雅停机；最多等待 40 秒，超时保留记录并报错，不追加信号 |
| `status` | 无 | 查询受管 PID、启动配置及配置的 API 地址 |
| `check` | 无 | 自动化冒烟测试：中文对话生成、本地合成 23°C 天气工具调用、思考算术 493 |
| `benchmark` | `[--contexts ...] [--repeats 3]` | 自动化 7 上下文 (2K-128K) 性能基准；要求独立冷缓存实例 |
| `plot` | `--input PATH --output PATH` | 基于 matplotlib 渲染基准测试 JSON 数据为可视化吞吐曲线图 |

### 全局可选参数
所有子命令均支持显式指定以下环境参数（若未传入则回退至环境变量或默认路径）：
- `--data-dir PATH`：数据存储根目录（默认 `~/.local/share/qwen38-serving`，环境变量 `QWEN38_DATA_DIR`）
- `--state-dir PATH`：运行时状态目录（默认 `~/.local/state/qwen38-serving`，环境变量 `QWEN38_STATE_DIR`）
- `--engine PATH`：原生 `mlx-serve` 可执行文件路径（环境变量 `QWEN38_ENGINE`）
- `--model-dir PATH`：模型权重目录（默认 `<data-dir>/models/qwen38-flash-next-iq47`）
- `--profile PATH`：引擎启动 Profile 配置文件路径
- `--port N`：服务监听端口（默认 `11234`）


## 3. 标准运行环境与 Python 虚拟环境规则

1. **标准库运行**：
   - `doctor`, `install-engine --plan`, `download --plan`, `verify`, `start`, `stop`, `status`, `check` 使用 Python 3.12+；macOS 自带 `python3` 可能是旧版本。
2. **扩展依赖隔离**：
   - 若后续需要执行 HuggingFace CLI 高速下载（`--transport hf`）或生成基准折线图（`plot`），需在本地创建专属虚拟环境：
     ```bash
     python3.12 -m venv .venv
     .venv/bin/python -m pip install -e '.[download,benchmark]'
     ```
   - 运行相应功能时明确使用 `.venv/bin/python scripts/qwen38.py ...`。
3. **环境变量加载**：
   - 仓库提供 `.env.example` 模板。CLI 不会自动隐式加载环境变量，按需复制为 `.env`、编辑占位路径后使用 `set -a; . ./.env; set +a` 或通过命令行显式传参。


## 4. 测试与 CI 约束

- **单元测试**：使用标准库 `unittest`：`python3.12 -m unittest discover -s tests -v`。所有单元测试必须保证完全离线，不产生网络 IO，不依赖 GPU。
- **语法校验**：`python3.12 -m compileall -q src scripts tests`。
- **CI 流水线**：GitHub Actions 在 Linux 上针对 Python 3.12 和 3.13 验证代码语法与离线单元测试。本项目不引入 Pyright 静态类型强校验作为阻断门禁。


## 5. 项目文档路由图

在执行具体任务前，优先查阅对应专题技术文档：

- **产品需求与功能规格**：[docs/prd.md](docs/prd.md)
- **系统架构与技术设计**：[docs/rfc.md](docs/rfc.md)
- **测试策略与冒烟用例**：[docs/test.md](docs/test.md)
- **开发记录与踩坑经验 (Lessons Learned)**：[docs/working.md](docs/working.md)
- **硬件调优与配置解析**：[docs/tuning.md](docs/tuning.md)
- **故障排查与诊断手册**：[docs/troubleshooting.md](docs/troubleshooting.md)
- **模型规格与下载指南**：[docs/download.md](docs/download.md)
- **性能基准与历史数据**：[docs/benchmark.md](docs/benchmark.md)
- **AI 技能定义规范**：[skills/qwen38-serving/SKILL.md](skills/qwen38-serving/SKILL.md)
