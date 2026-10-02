# 硬件调优与配置解析 (Tuning Guide)

本指南针对 Apple Silicon 统一内存架构，深入解析 `qwen38-mlx-serving` 的各项配置参数与系统底层内核调优策略。


## 1. 目标硬件平台与基准规格

- **芯片型号**：Apple Silicon M5 Max
- **GPU 核心**：40 核 GPU
- **统一内存**：128 GiB 统一内存 (Unified Memory)
- **操作系统**：macOS (arm64)

> 本配置在 M5 Max 40 核 GPU、128 GiB 机器上筛选；其他硬件的可用性和性能未验证。

## 2. 候选配置

实际配置见 [m5-max-128gb.json](../profiles/m5-max-128gb.json)，由 wrapper 生成原生启动命令，不需要手工拼接引擎参数。

| 配置 | 用途 |
|---|---|
| `--ctx-size 262144` | 主模型输入与输出共享的配置上限；完整 262K 尚未测试 |
| `--max-resident-mem 96GB` | 引擎驻留预算，不等于实际占用或系统预留量 |
| `--kv-quant 8`、`--mtp-head-kv-quant` | 主模型及 MTP 头的 KV8；未做质量等价评估 |
| `--mtp-depth 6`、`MLX_SERVE_MTP_FORCE_DEPTH=3` | CLI 上限 6、实际固定深度 3 |
| `MLX_SERVE_MTP_DRAFT_GREEDY=0` | 采样草稿，保留采用配置 |
| `--mtp-history-window 8192` | 只缩短草稿头历史，历史长上下文速度筛选胜出 |
| `--reasoning-budget 0` | 默认关闭思考，推理题可在请求中明确开启 |
| 不传 `--ple-gpu` | 保持 CPU mmap ngram 路径 |
| `--prefix-cache-entries 4`、`--prefix-cache-mem 4GB` | 正常服务的前缀缓存预算；测试用 entries 0 |

这是历史组合包的采用配置，对完整社区模型仍是待测候选。

## 3. 系统 wired memory 设置

测试机手动使用以下设置：

```bash
sysctl iogpu.wired_limit_mb
sudo sysctl -w iogpu.wired_limit_mb=118000
```

包装器只读取并报告。重启 macOS 后应重新检查。这个数值只用于已测试的 128GB 机器，其他内存规格需重新评估。

## 4. 调优时复测

在相同提示词、采样、输出长度和冷缓存条件下比较配置，同时保留客户端与服务端速率。历史 GPU ngram 配置可加载但没有赢得速度筛选；更深 MTP 也不总更快。

CPU mmap 与 GPU 共享统一内存，不能把 32GB 表当作零物理内存开销。更小内存设备可能连权重都无法加载，不能靠降低上下文保证可运行。
