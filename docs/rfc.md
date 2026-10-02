# 技术设计方案 (RFC) - qwen38-mlx-serving

## 1. 系统总体架构

客户端直接访问 `mlx-serve` 的 HTTP API。Python 包装器负责安装、文件校验和进程管理，不导入 Python MLX 张量库。权重和引擎在数据目录，日志和状态在运行目录，代码仓库只保存清单、配置、测试与说明。

代码入口：[CLI](../src/qwen38_serving/cli.py)、[管理模块](../src/qwen38_serving/core.py)、[benchmark](../src/qwen38_serving/benchmark.py)。

## 2. 原生引擎集成设计

1. **版本锁定与哈希校验**：
   - 绑定上游稳定版本 `mlx-serve` v26.10.1 macOS arm64 原生发布包。
   - 包内包含原生主二进制可执行文件及随附的动态库（`.dylib`）、LICENSE 和 NOTICE 文件。
   - `install-engine` 解压安装后，保持二进制属性不变，不执行二次重编译。
2. **纯原生运行模式**：
   - 控制器通过 `subprocess.Popen` 直接调度二进制文件，不通过 `import mlx` 或 Python 绑定加载权重，不额外维护 Python 推理实现。


## 3. 进程生命周期与端口检查

启停用 `lifecycle.lock` 互斥。启动前检查端口和模型校验标记，之后写入 `server.json`（PID、argv、端口、profile、revision 和启动时间），日志为 `server.log`。

停止前用 `ps` 核对 PID 对应的二进制和端口。发送一次 SIGTERM 后，仅检查进程状态，最多等待 40 秒；macOS 终止中的 argv 可能先清空，因此等待阶段不再依赖 argv。超时保留记录并报错，不发送 SIGKILL。

## 4. 推理配置

唯一候选 profile 在 [m5-max-128gb.json](../profiles/m5-max-128gb.json)。实际参数包括 `--ctx-size 262144`、`--max-resident-mem 96GB`、`--kv-quant 8`、`--mtp-head-kv-quant`、`--mtp-depth 6` 和 `--mtp-history-window 8192`。

环境变量 `MLX_SERVE_MTP_FORCE_DEPTH=3` 固定实际深度，`MLX_SERVE_MTP_DRAFT_GREEDY=0` 使用采样草稿。CPU mmap ngram 是未传 `--ple-gpu` 时的默认路径。8K 窗口仅限制草稿头历史，主上下文仍为 262144。

该配置来自历史组合包的速度筛选，对完整社区模型仍待验证；不承诺量化质量等价或相同输出。

## 5. 内存与系统设置

CPU 与 GPU 共享统一内存，CPU mmap 不意味着 32GB 表不占物理内存。`96GB` 是引擎的模型驻留预算，不能当作实际 GPU 使用量或给系统预留空间的精确计算。实际评估结合引擎 `/props` 和系统内存数据。

测试机曾手动设置 `iogpu.wired_limit_mb=118000`；该值重启后需检查。包装器只读取，不自动 sudo，也不把这套 128GB 设置套到更小内存设备。

## 6. 模型完整性验证

[model.json](../manifests/model.json) 固定 repo、revision、文件路径、大小与 LFS SHA-256 / Git blob SHA-1。完整校验全部通过后，标记绑定清单 SHA-256 及每个文件的大小和 mtime。

启动检查使用该标记，避免每次读取 107.3GB。它不能检测同时保留大小和 mtime 的内容修改；手工改动后应再次完整 `verify`。旧 ngram 表不会自动替代 canonical 表。
