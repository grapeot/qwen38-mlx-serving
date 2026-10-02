# 模型规格与下载指南 (Model Download Guide)

本指南详细说明 `Qwen3.8-Flash-Next` (iQ 4.7bpw) 社区模型的规格参数、清单结构、传输方式以及安全下载规范。


## 1. 规范模型规格与元数据

- **模型标识**：`ddalcu/Qwen3.8-Flash-Next-MLX-Serve-iQ-MLX-4.7bpw`
- **目标 Git Revision**：`dafff5c3d8168c9d13275661153911096499a80a`
- **文件总数**：严格等于 **113 个文件**
- **总字节大小**：严格等于 **107,326,639,091 字节** (~107.3 GB)
- **文件构成**：
  - 101 个 `model-*.safetensors` 分块权重文件 (~75.3 GB)
  - 1 个规范 `ngram_table.bin` 模型 PLE embedding 表 (~32 GB)
  - 11 个配置文件、tokenizer 描述文件与词表映射文件

所有文件的规范大小、Git LFS SHA-256（或 Git blob SHA-1）均完整收录在仓库的 `manifests/model.json` 中。


## 2. 完全离线的下载预览

```bash
python3.12 scripts/qwen38.py download --plan
```

该命令不联网、不创建模型目录，输出版本、总大小、目标路径和 HF 命令。逐文件路径和哈希在 [model.json](../manifests/model.json)。实际 `download` 会联网，应遵守用户当前的网络与下载暂停约束。

## 3. 传输模式与执行方式

两种传输方式都使用固定 revision，下载后独立校验全部文件。默认 HF 模式需要先安装下载扩展依赖。

### 模式 A：Python 标准库 HTTP 传输（可选）
纯原生实现，无需在本地配置额外的 Python 虚拟环境或依赖包。
- **特性**：
  - 基于 `urllib.request` 实现断点续传。
  - 每个文件在拉取时先写入 `.part` 临时分块，避免网络中断导致半成品文件残留。
  - 同时下载最多 4 个文件；服务器忽略 Range 时重写该部分文件。单文件下载完成后核对大小和哈希，校验通过后再原子重命名为正式文件名。
- **执行命令**：
  ```bash
  python3.12 scripts/qwen38.py download --transport http
  ```

### 模式 B：Hugging Face CLI（默认）
适用于具备良好网络环境且希望利用官方多线程分块下载能力的场景。
- **环境准备**：
  ```bash
  python3.12 -m venv .venv
  .venv/bin/python -m pip install -e '.[download,benchmark]'
  ```
- **执行命令**：
  ```bash
  .venv/bin/python scripts/qwen38.py download --transport hf
  ```
- **关键约束**：
  - CLI 强制指定 `--local-dir ~/.local/share/qwen38-serving/models/qwen38-flash-next-iq47`。
  - HF 缓存目录严格隔离在数据目录下方（`~/.local/share/qwen38-serving/hf-cache`），绝不污染全局系统缓存，不导入其他旧目录的缓存；新数据目录内的正确文件可续传或复用。


## 4. 存储路径与数据隔离

1. **绝对不进 Git 仓库**：
   - 所有的模型权重、safetensors 以及 N-gram 表统一存放于数据存储目录：
     ```text
     ~/.local/share/qwen38-serving/models/qwen38-flash-next-iq47/
     ```
   - 仓库 `.gitignore` 已配置排除一切 `.safetensors`, `.bin`, `.part` 及大型数据文件。
2. **禁止重新量化与旧文件替换**：
   - 必须使用上游社区发布的原生 iQ 4.7bpw 权重文件。
   - 包装器绝不在本地对源 BF16 权重执行二次量化，绝不使用旧版或其他尺寸的 N-gram 表进行替代。


## 5. 下载后完整性强核验 (`verify`)

下载完成后，必须运行全局核验命令：
```bash
python3.12 scripts/qwen38.py verify
```
核验流程将比对 `manifests/model.json` 中的 113 个文件，确认字节数与 SHA 完全吻合，并在模型目录生成 `.qwen38-verified.json` 绑定标记。只有存在有效标记时，`start` 命令才允许启动服务。

## 6. 旧权重迁移与验证

默认模型目录与 repo 分开，不需要把权重提交或复制进源码。按用户授权清理旧权重时，先停止使用它们的服务，再 `trash PATH`，保留可恢复的 Trash。不要在已加载模型上覆盖文件。

完整下载和 `verify` 后执行 `start`、`check`，再按 [测试协议](benchmark.md) 复测七档性能。新包自带的 ngram 表与历史组合包不同，速度和质量需重新验证。下载无需 sudo；完整校验会读取约 107.3GB，可花费数分钟。
