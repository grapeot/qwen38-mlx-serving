# 故障排查与诊断手册 (Troubleshooting)

本手册汇总了在部署、维护与运行 `qwen38-mlx-serving` 过程中可能遇到的典型故障场景、排查路径与恢复方案。


## 1. 模型路径与运行时状态核查 (Model Location & Runtime Inspection)

### 故障现象与排查场景

在环境诊断、模型定位或验证权重是否存在时，常见误区包括：将旧实验路径当成当前标准路径；仅因 HTTP 接口有响应就推断模型必定存在于某个默认目录；或者因为历史路径不存在而误以为权重丢失进而盲目重新下载或重启服务。

### 排查步骤

1. **获取受管进程与实际启动参数**：
   在仓库根目录执行：
   ```bash
   python3.12 scripts/qwen38.py status
   ```
   检查活跃的受管 PID、启动配置中的 `record.model` 与 `record.argv`。
   > [!NOTE]
   > 当 `pid` 为 null 或服务非正常退出时，状态记录可能已过时（stale）。此时应配合系统进程命令（如 `ps -p PID -o command=`；将 PID 替换为实际进程号，未知时先用 `lsof -nP -iTCP:11234 -sTCP:LISTEN` 定位）核对真实运行中的进程参数，并核实对应文件在文件系统中是否存在。
2. **查看当前请求的配置与目录规划**：
   执行自检命令：
   ```bash
   python3.12 scripts/qwen38.py doctor
   ```
   查看当前解析的 `model_directory`、数据根目录以及运行时状态目录。
   默认模型路径为 `~/.local/share/qwen38-serving/models/qwen38-flash-next-iq47`，运行时状态文件为 `~/.local/state/qwen38-serving/server.json`。命令行参数与环境变量可覆盖上述默认值；需注意 `status` 展示的是实际启动时的参数记录，而 `doctor` 展示的是当前环境请求的配置，两者在覆盖生效时可能存在差异。
3. **区分历史实验路径与当前规范路径**：
   早期实验路径 `qwen38_flash_bench/models/flash-next-iq47-local-ngram` 为历史复合包路径，其不存在本身不能说明当前服务权重缺失。规范公开下载路径已在 [下载指南](download.md) 中完整记录。
4. **验证文件存在性与完整性**：
   服务接口能够正常响应并不证明特定路径下的文件必然存在，必须检查运行进程实际 `--model` 参数所指向的目录及逐文件清单。仅在怀疑权重损坏或需要进行全量校验时，才运行 `python3.12 scripts/qwen38.py verify` 执行逐文件哈希核对；若启动时使用了 `--model-dir` 等覆盖参数，核验时也应传入对应参数。

### 运维规范与边界

- 严禁仅仅因为旧历史路径不存在就盲目重新下载、删除数据或重启服务。
- 确认模型目录时，始终以实际启动进程的参数与文件系统检查为准。


## 2. 端口冲突与已被占用 (Address already in use)

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


## 3. 原生引擎丢失或哈希校验失败

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


## 4. 模型验证失败 (`verify` 报错)

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


## 5. 内存分配失败

检查 `sysctl iogpu.wired_limit_mb`、其他大模型进程、引擎 `/props` 以及 `server.log`。重启可能改变 wired limit；0 可能表示自动配置，不能仅凭数值判断故障。

对已测试的 128GB 机器，可核对 [调优说明](tuning.md) 中的人工设置。更小内存机器可能不满足权重加载需求，不能保证降低 context 或驻留预算就能运行。

## 6. 算术测试输出 503 而非 493

检查实际请求是否包含 `enable_thinking:true` 与 `reasoning_budget_tokens:128`。历史无思考模式曾错答 503，但新模型的失败原因仍需看原始响应，不能保证开启思考就答对所有题目。

## 7. 输出提前结束

检查 EOS、stop、剩余上下文和客户端实际请求体。某些 SDK 会注入输出上限，例如曾观察到 pi-ai 写入 `max_completion_tokens:32768`。wrapper 不设置服务端输出上限；配置上限 262144 由输入和输出共享。

## 8. 基准测试报告 `cached_tokens > 0` 失败

### 故障现象
运行 `python3.12 scripts/qwen38.py benchmark` 时，脚本立即报错并拒绝测试。

### 解决方案
基准测试必须在未受污染的全新冷缓存实例上运行。必须先停止当前运行的服务，并以 `--cold-cache` 标志重新启动服务：
```bash
python3.12 scripts/qwen38.py stop
python3.12 scripts/qwen38.py start --cold-cache
.venv/bin/python scripts/qwen38.py benchmark
```


## 9. 日志排查与追踪

运行期标准输出与错误日志统一输出至：
```bash
~/.local/state/qwen38-serving/server.log
```
可使用标准命令实时跟踪推理请求与内核指标：
```bash
tail -f ~/.local/state/qwen38-serving/server.log
```


### Python 转发器导致虚拟环境异常排障

本机曾因 `python3.12` 转发器路径配置而在使用 `python3.12 -m venv .venv` 创建虚拟环境时出现 `pyvenv.cfg` 的 `home` 错误指向转发器目录，报错为标准库缺失（报错如 `/install/lib/python3.12` 及 `ModuleNotFoundError: encodings`）；缺少 ensurepip 也可能导致 pip 安装失败。本次显式指定真实解释器、用 `uv` 重建环境后，依赖安装与 19 项离线测试通过。推荐使用以下备用命令：

```bash
uv venv --allow-existing --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[download,benchmark]'
```

若 `uv` 自动探测的解释器依然不正确，可在正常的 Python 环境中打印 `sys._base_executable`，再把该真实解释器的绝对路径显式传给 `--python`。此方法专门针对转发器路径配置偏差，无法断言能修复所有的 Python 环境损坏问题。
