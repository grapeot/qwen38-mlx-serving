# 测试策略与验证体系 - qwen38-mlx-serving

本项目遵循离线优先、分层验证与可度量的测试原则，保障系统在各阶段的确定性与可靠性。


## 1. 离线单元测试与语法编译

### 1.1 单元测试套件
单元测试基于 Python 3.12+ 原生 `unittest` 框架实现，完全隔离外部网络、GPU 资源与模型权重文件。

- **测试用例位置**：`tests/`
- **执行命令**：
  ```bash
  python3.12 -m unittest discover -s tests -v
  ```
- **核心测试覆盖面**：
  - CLI 参数解析与环境覆盖逻辑（`--data-dir`, `--port`, `--profile` 等）。
  - 模型清单文件 `manifests/model.json` 的解析与数据完整性断言。
  - 进程 PID 读写、心跳检测与端口探测模拟逻辑。
  - 离线计划输出格式（`--plan`）与无副作用验证。

### 1.2 静态代码编译验证
验证代码在目标 Python 环境下的语法完备性：
```bash
python3.12 -m compileall -q src scripts tests
```

### 1.3 持续集成 (CI) 策略
- **平台环境**：GitHub Actions Ubuntu 运行环境。
- **Python 版本**：针对 Python 3.12 与 Python 3.13 矩阵运行。
- **执行内容**：仅运行 `compileall` 与 `unittest discover` 离线套件，不触发任何外部模型下载，不强行依赖 Pyright 等外部重型类型检查器。


## 2. 功能冒烟测试套件 (`check`)

当本地服务通过 `python3.12 scripts/qwen38.py start` 成功启动后，使用 `check` 命令对运行实例进行端到端功能验证：
```bash
python3.12 scripts/qwen38.py check
```

冒烟套件依次执行以下三个确定性测试：

### 2.1 测试 1：中文对话连贯性测试
- **请求内容**：向 `/v1/chat/completions` 发送单条中文对话请求。
- **断言标准**：
  - HTTP 状态码为 200。
  - 响应包含合法 `choices[0].message.content`。
  - 输出包含至少一个中文字符；这不等于语言质量评估。

### 2.2 测试 2：本地合成工具调用回路 (Synthetic Function Calling)
- **请求内容**：向模型注入虚构天气查询函数：
  ```json
  {
    "name": "get_weather",
    "description": "获取指定城市的天气状态",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {"type": "string"}
      },
      "required": ["city"]
    }
  }
  ```
- **测试机制**：
  1. 验证模型正确输出 `tool_calls`，且调用函数名为 `get_weather`。
  2. 测试脚本在**本地直接合成虚构天气响应** `{"temperature_c":23,"source":"synthetic protocol test"}`，**绝对不发起外部真实天气网络请求**。
  3. 将合成结果以 `role: tool` 回传给模型，验证模型基于 23°C 的天气输出最终中文回复。

### 2.3 测试 3：思考模式算术

请求 `19×23+7×8`，设置 `enable_thinking:true`、`reasoning_budget_tokens:128`，要求最终答案为 `493`。历史无思考请求错答 `503`，开启思考后答对；这个单点测试不能保证一般推理正确性。测试请求中的 512-token 上限仅用于检查，不是服务端默认上限。

## 3. 基准测试套件 (`benchmark`)

### 3.1 运行前置条件
基准测试必须在专用冷启动实例上运行，确保数据不受先前对话的前缀缓存污染：
```bash
# 以冷缓存标志启动专用服务
python3.12 scripts/qwen38.py start --cold-cache

# 运行 7 个上下文梯度评测
.venv/bin/python scripts/qwen38.py benchmark \
  --contexts 2048,4096,8192,16384,32768,65536,131072 \
  --repeats 3 \
  --output-tokens 192 \
  --temperature 1.0
```

### 3.2 测量严谨性保障
1. **冷缓存断言**：测试脚本从每次响应 usage 中断言 `cached_tokens == 0`，另读 `/metrics.json` 计算服务端阶段速率。若检测到缓存残留，立即中止测试。
2. **随机前缀注入**：每次测试动态生成至少 256-token 的随机提示词前缀，避免底层前缀表隐式命中。
3. **指标解耦**：服务端内部计数器上报的 Prefill 与 Decode 速率与客户端接收到的 TTFT、总耗时分别记录，并计算 3 次测定的中位数。


## 4. 历史评测记录说明

在早期原型验证中，曾对模型进行过 8 个代码任务与 3 个工具调用的手工评估（综合通过率为 10/11）。需要强调的是，该数据属于早期研发过程中的定性抽样，绝非正规学术基准（如 HumanEval、SWE-bench 或 BFCL），不代表生产环境下的代码或工具调用成功率。

截至 2026-10-02：19 项离线测试和语法检查通过，绘图用测试数据验证；本机已确认占用端口时退出且原服务健康。完整社区模型的 `check` 和性能测试尚未执行。
