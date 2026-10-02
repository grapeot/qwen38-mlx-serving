# 故障排查与诊断手册 (Troubleshooting)

本手册汇总了在部署、维护与运行 `qwen38-mlx-serving` 过程中可能遇到的典型故障场景、排查路径与恢复方案。


## 1. 端口冲突与已被占用 (Address already in use)

### 故障现象
执行 `python3.12 scripts/qwen38.py start` 时报错：
```text
RuntimeError: Port occupied; existing service was left untouched
```

### 排查步骤
1. 查看占用 11234 端口的具体进程信息：
   ```bash
   lsof -i :11234
   ```
2. 运行状态查询命令检查是否为先前受管实例：
   ```bash
   python3.12 scripts/qwen38.py status
   ```

### 解决方案
- **若为先前的受管实例**：运行 `python3.12 scripts/qwen38.py stop` 正常退出进程。
- **若为独立运行的历史复合服务 (Historical Composite Service)**：
  - 包装器严禁向非受管进程发送退出信号。
  - 用户应根据需要，在原服务管理端退出历史服务；或通过 `--port` 参数为新服务指定其他端口（例如 `--port 11235`）。


## 2. 原生引擎丢失或哈希校验失败

### 故障现象
执行 `start` 提示找不到 `mlx-serve`，或 `install-engine` 报告下载包 SHA-256 不匹配。

### 解决方案
1. 运行自检命令确认环境：
   ```bash
   python3.12 scripts/qwen38.py doctor
   ```
2. 先通过离线计划核对引擎版本与哈希：
   ```bash
   python3.12 scripts/qwen38.py install-engine --plan
   ```
3. 重新执行安装命令：
   ```bash
   python3.12 scripts/qwen38.py install-engine
   ```


## 3. 模型验证失败 (`verify` 报错)

### 故障现象
执行 `python3.12 scripts/qwen38.py verify` 报错，提示部分 `safetensors` 文件损坏、字节缺失或 `ngram_table.bin` 校验未通过。

### 排查步骤
1. 检查报错输出中提示的具体文件名和预期大小。
2. 确认本地文件清单中的 113 个文件是否完整；校验标记与 HF 元数据不计入清单字节数。
3. 检查是否存在从旧模型目录手工软链接过来的文件或未经核准的第三方量化版本。

### 解决方案
- 严禁擅自修改 `manifests/model.json`。
- 若部分分块损坏，使用 HTTP 模式重新拉取，或先把损坏文件移到 Trash 再重试 HF 模式；HF 元数据可能使它跳过文件：
  ```bash
  python3.12 scripts/qwen38.py download --transport http
  ```
- 下载完成后再次运行 `python3.12 scripts/qwen38.py verify`，确认生成 `.qwen38-verified.json`。


## 4. 内存分配失败

检查 `sysctl iogpu.wired_limit_mb`、其他大模型进程、引擎 `/props` 以及 `server.log`。重启可能改变 wired limit；0 可能表示自动配置，不能仅凭数值判断故障。

对已测试的 128GB 机器，可核对 [调优说明](tuning.md) 中的人工设置。更小内存机器可能不满足权重加载需求，不能保证降低 context 或驻留预算就能运行。

## 5. 算术测试输出 503 而非 493

检查实际请求是否包含 `enable_thinking:true` 与 `reasoning_budget_tokens:128`。历史无思考模式曾错答 503，但新模型的失败原因仍需看原始响应，不能保证开启思考就答对所有题目。

## 6. 输出提前结束

检查 EOS、stop、剩余上下文和客户端实际请求体。某些 SDK 会注入输出上限，例如曾观察到 pi-ai 写入 `max_completion_tokens:32768`。wrapper 不设置服务端输出上限；配置上限 262144 由输入和输出共享。

## 7. 基准测试报告 `cached_tokens > 0` 失败

### 故障现象
运行 `python3.12 scripts/qwen38.py benchmark` 时，脚本立即报错并拒绝测试。

### 解决方案
基准测试必须在未受污染的全新冷缓存实例上运行。必须先停止当前运行的服务，并以 `--cold-cache` 标志重新启动服务：
```bash
python3.12 scripts/qwen38.py stop
python3.12 scripts/qwen38.py start --cold-cache
.venv/bin/python scripts/qwen38.py benchmark
```


## 8. 日志排查与追踪

运行期标准输出与错误日志统一输出至：
```bash
~/.local/state/qwen38-serving/server.log
```
可使用标准命令实时跟踪推理请求与内核指标：
```bash
tail -f ~/.local/state/qwen38-serving/server.log
```
