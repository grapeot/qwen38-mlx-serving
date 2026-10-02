---
name: qwen38-serving
description: 部署与维护基于 Apple MLX 的 Qwen3.8-Flash-Next (iQ 4.7bpw) 本地推理服务，管理第三方 mlx-serve 原生引擎生命周期、模型校验与基准测试。
---

# qwen38-serving 技能指南

本技能为自动化 Agent 在 Apple Silicon (macOS arm64) 环境下运维与调度 `qwen38-mlx-serving` 推理服务提供确定性的行动准则。


## 1. 目标与验收标准 (Goals & Acceptance Criteria)

### 核心目标
在兼容 Mac 上完成固定版本引擎与完整社区模型的安装、API 检查，并在需要时复测性能。遵守用户当前的任务范围、网络限制和暂停指令。

### 验收标准
实际部署以完整校验、健康 API、check 结果及启动配置记录为终点；性能任务另需七档原始数据和曲线。用户只要求离线规划时，交付计划与离线检查结果，并明确模型尚未实测。
1. **环境与计划审计**：`doctor` 如实报告硬件与内核状态；`install-engine --plan` 与 `download --plan` 能够以纯离线方式输出版本、大小、目标目录与命令，无任何外部网络外发请求。
2. **模型状态绑定**：`verify` 能够强校验 113 个文件及 32GB 规范 N-gram 的完整性，成功生成 `.qwen38-verified.json`。
3. **安全单例启停**：`start` 必须能够正确探测端口 11234 冲突；在端口空闲时启动单例进程；`stop` 能够准确回收受管 PID，正常停机或如实报告超时，不波及任何其他无关进程。
4. **功能冒烟通过**：`check` 能够顺序通过中文对话、本地合成 23°C 天气工具调用与思考模式算术 493 验证。


## 2. 常用 CLI 命令速查 (CLI Cheat Sheet)

使用 Python 3.12+；系统自带 `python3` 可能是旧版本（核心逻辑仅依赖标准库）：

```bash
# 1. 环境自检
python3.12 scripts/qwen38.py doctor

# 2. 离线规划审查 (当前推荐)
python3.12 scripts/qwen38.py install-engine --plan
python3.12 scripts/qwen38.py download --plan

# 3. 完整性校验
python3.12 scripts/qwen38.py verify

# 4. 服务启停与状态
python3.12 scripts/qwen38.py start
python3.12 scripts/qwen38.py status

# 5. 冒烟与性能测试（benchmark 需要扩展依赖，先停止普通实例）
python3.12 scripts/qwen38.py check
python3.12 scripts/qwen38.py stop
python3.12 scripts/qwen38.py start --cold-cache
.venv/bin/python scripts/qwen38.py benchmark --contexts 2048,4096,8192,16384,32768,65536,131072 --repeats 3
```


## 3. 高频操作陷阱与排错红线 (Real Traps & Guardrails)

1. **当前任务范围优先**：用户暂停下载时只做离线计划。明确安装请求可在已有授权范围内安装；不要把一次暂停变成对其他用户的永久限制。无网络或缺少依赖时报告缺项，保留可续传文件。

2. **前缀缓存内存配置陷阱**：
   - 引擎参数中 `--prefix-cache-mem 0GB` 表示**内存无限制**。若要禁用前缀缓存，必须配置条目数为 0（`--prefix-cache-entries 0`）。
3. **MTP 历史窗口与上下文边界**：
   - `--mtp-history-window 8192` 仅限制投机草稿头的预测视野，主模型的上下文窗口依然受 `--ctx-size 262144` 支配，配置上限为 262144；完整 262K 尚未验证。
4. **端口冲突绝对不强杀**：
   - 启动服务遇到 11234 端口被占用时，必须报错退出，**严禁对未受管的外部 PID 发送 kill 信号**，保护既有独立服务。
5. **模型文件安全删除红线**：
   - 严禁在脚本或命令行中使用 `rm -rf` 清理模型。未来清理旧权重必须经负责人明确授权后，调用 macOS 命令 `trash <PATH>` 移至废纸篓，且**绝不执行清空废纸篓**。
6. **算术用例的思考模式依赖**：
   - 默认非思考模式下算术可能输出 `503`；开启思考后输出 `493`。不要将该单点测试误作模型通用能力的全局担保。


## 4. 专题文档索引 (References)

- **产品规格与需求边界**：[../../docs/prd.md](../../docs/prd.md)
- **技术架构与进程设计**：[../../docs/rfc.md](../../docs/rfc.md)
- **测试用例与验证策略**：[../../docs/test.md](../../docs/test.md)
- **踩坑记录与技术经验**：[../../docs/working.md](../../docs/working.md)
- **硬件调优与参数剖析**：[../../docs/tuning.md](../../docs/tuning.md)
- **故障排查与诊断手册**：[../../docs/troubleshooting.md](../../docs/troubleshooting.md)
- **模型规格与下载规范**：[../../docs/download.md](../../docs/download.md)
- **基准测试与历史数据**：[../../docs/benchmark.md](../../docs/benchmark.md)
