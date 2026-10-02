# 工作记录与踩坑经验 (Lessons Learned)

本文件系统记录 `qwen38-mlx-serving` 的版本演进历史，以及在 Apple Silicon (M5 Max 128GB) 上调优原生 `mlx-serve` 与 `Qwen3.8-Flash-Next` 过程中总结的真实技术陷阱与避坑经验。


## 1. 变更日志

### 2026-10-02

- 将服务管理收敛为 `scripts/qwen38.py`，原生推理由第三方引擎完成。
- 固定完整社区模型的 113 文件清单及引擎 release 哈希；默认权重和运行状态位于 repo 外。
- 新增完全离线的下载预览、独立哈希校验、PID / 端口检查及可复测的七档 benchmark。
- 中文文档由 Antigravity 起草，再按实现校对；保留历史组合包数据并标明其边界。
- 19 项离线测试、语法检查和绘图检查通过；完整社区模型尚未下载或实测。

## 2. 真实技术陷阱与教训

- `--prefix-cache-mem 0GB` 表示无预算上限，禁用缓存应使用 `--prefix-cache-entries 0`。早期探索出现 7-token 命中，已从最终冷缓存比较中排除。
- 历史筛选中更深的 MTP 和 GPU ngram 没有持续胜过采用配置；不要凭参数大小判断更快。
- CLI 深度上限 6 与 `MLX_SERVE_MTP_FORCE_DEPTH=3` 的实际固定深度要同时记录。
- 8K 草稿历史不限制主上下文；完整 262K 尚未实测。
- 默认无思考对 `19×23+7×8` 错答 503；启用思考后答对 493。不能用速度替代质量判断。
- 原 community ngram 与公开 iQ 仓库的表字节不同。历史组合包不等于 canonical checkpoint，不承诺质量等价。
- 部分客户端 SDK 会注入输出上限；DSH 的 pi-ai 链路曾在请求体中写入 `max_completion_tokens:32768`，即使 profile 未设置上限。应检查实际请求体，不能只看配置。
- macOS 终止中的进程可能先清空 argv；PID 归属在发送 SIGTERM 前检查，等待只查进程状态。
- macOS 的 `python3` 可能是 3.9。本项目明确要求 Python 3.12+，不要靠系统命令名推断版本。
