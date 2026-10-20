# 多智能体代码质量保障系统

## 1. 项目简介

本项目是一个面向 Python 源代码的多智能体代码质量保障系统。系统将一次代码处理任务拆分为三个具有不同职责的智能体：

1. **代码审查智能体**：识别安全问题、逻辑错误、运行时异常风险和代码质量问题。
2. **代码修复智能体**：根据结构化问题列表生成候选修复代码。
3. **独立验证智能体**：检查候选代码是否解决原问题、是否存在语法错误以及是否引入新的明显问题。

系统通过共享状态、结构化 JSON 消息和事件日志实现智能体之间的协作。验证失败时，系统将验证反馈传回修复智能体，最多进行两轮修复与验证，最终生成修复代码、修改差异、状态文件和 Markdown 报告。

核心流程：

```text
输入 Python 文件 → 代码审查智能体 → 代码修复智能体 → 独立验证智能体
                                      ↑                 │
                                      └─ 验证失败反馈 ───┘
```

## 2. 项目目标

本项目的目标是将项目1中的单智能体代码审查程序扩展为一个可运行、可观察、可复用的多智能体代码质量保障流程。

具体目标如下：

1. **实现多智能体协作**：由代码审查智能体、代码修复智能体和独立验证智能体共同完成一次代码处理任务。
2. **实现消息传递和状态共享**：使用结构化 JSON 数据传递问题列表、候选代码和验证反馈，避免智能体之间只依赖自然语言描述。
3. **实现完整流程控制**：支持顺序执行、无问题分支、语法检查、验证失败回退和最大修复轮次限制。
4. **实现可复核的结果输出**：保存原始代码、修复代码、修改差异、工作流状态、执行事件和 Markdown 报告。
5. **提供简单的使用入口**：同时提供命令行入口和 Web 页面，便于本地运行、调试和课堂演示。
6. **保留扩展空间**：通过独立 Prompt、统一输出协议和集中式流程编排，便于后续增加测试、安全扫描或文档生成等智能体。

## 3. 主要功能

### 3.1 多智能体代码工作流

- 审查 Agent 返回结构化问题列表。
- 修复 Agent 根据问题列表生成完整候选代码。
- 验证 Agent 独立检查修复结果。
- 验证失败时，保存反馈并进入下一轮修复。
- 最多执行两轮修复，避免无限循环。
- 无问题时跳过自动修复，保留原代码并执行本地语法检查。

### 3.2 共享状态管理

每次运行创建一个独立运行目录，主要状态包括：

```text
run_id
status
input_path
original_code
candidate_code
findings
review_summary
repair_round
verification_history
```

状态值包括 `running`、`passed` 和 `manual_review`。

### 3.3 安全的代码读取

- 限制文件必须位于项目根目录内。
- 拒绝路径越界访问。
- 拒绝二进制文件并限制文件大小。
- 不执行用户上传的 Python 代码。
- 使用 `ast.parse` 做语法检查，而不是直接运行候选代码。

### 3.4 Web 交互

网页支持输入项目内文件路径、上传待处理文件、启动代码质量保障流程，以及展示最终报告和修改差异。原项目的 `/review` 单 Agent 接口仍作为兼容入口保留；本项目演示应使用 `/workflow` 接口。

## 4. 目录结构

```text
code-review-agent-workflow/
├── workflow.py              # 多智能体流程编排与共享状态管理
├── workflow_prompts.py      # 三个智能体的角色 Prompt 与 JSON 契约
├── web.py                   # Flask Web 入口，包含 /workflow 接口
├── templates/index.html     # 代码质量保障系统前端页面
├── agent.py                 # 原有单 Agent 循环与 JSON 解析工具
├── tools.py                 # 文件读取、代码搜索、路径安全和工具注册表
├── llm.py                   # OpenAI 兼容模型客户端与重试
├── prompts.py               # 原有代码审查 Agent Prompt
├── main.py                  # 原有单文件审查 CLI 入口
├── examples/                # 演示代码
├── test_tools.py            # 工具层测试
├── test_workflow.py         # Workflow 本地语法检查测试
├── runs/                    # 每次运行生成的结果目录
├── uploads/                 # Web 上传文件目录
├── requirements.txt         # Python 依赖
├── DESIGN.md                # 详细设计文档
└── README.md                # 项目说明与使用文档
```

## 5. 环境要求

- Python 3.10 或以上版本。
- 一个 OpenAI 兼容的大模型 API Key。
- Windows、Linux 或 macOS 均可运行。

## 6. 安装与配置

Windows PowerShell：

```powershell
cd D:\code-review-agent-workflow
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
```

如果不能激活虚拟环境，可以直接调用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

在项目根目录 `.env` 中配置模型，例如：

```text
DEEPSEEK_API_KEY=你的APIKey
```

或：

```text
OPENAI_API_KEY=你的APIKey
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o-mini
```

密钥只保存在本地 `.env`，不要提交到仓库或压缩包中。

## 7. 使用方法

### 7.1 命令行运行多智能体 Workflow

```powershell
cd D:\code-review-agent-workflow
.\.venv\Scripts\python.exe workflow.py examples\buggy_code.py
```

### 7.2 启动 Web 页面

```powershell
cd D:\code-review-agent-workflow
.\.venv\Scripts\python.exe web.py
```

浏览器打开 `http://127.0.0.1:5000`，输入 `examples/buggy_code.py`，点击“运行代码质量保障流程”。停止服务使用 `Ctrl+C`。

### 7.3 运行测试

```powershell
.\.venv\Scripts\python.exe test_tools.py
.\.venv\Scripts\python.exe test_workflow.py
```

## 8. 运行产物

每次运行会在 `runs/` 下创建独立目录：

```text
runs/<run_id>/
├── original.py       # 原始代码副本
├── fixed.py          # 修复后的候选代码
├── changes.diff      # 原始代码与候选代码的统一差异
├── report.md         # 审查、修复和验证汇总报告
├── state.json        # 工作流最终共享状态
└── events.jsonl      # 按时间记录的执行事件
```

主要事件为：

```text
workflow_started → review_agent_started → review_agent_finished
→ repair_agent_started → repair_agent_finished
→ verify_agent_started → verify_agent_finished → workflow_finished
```

## 9. 典型运行流程

1. 工作流读取原始 Python 文件。
2. 代码审查智能体输出 `F001`、`F002` 等结构化问题。
3. 编排器把问题列表写入共享状态 `findings`。
4. 代码修复智能体读取问题列表，输出 `candidate_code`。
5. 系统使用 `ast.parse` 检查候选代码语法。
6. 独立验证智能体检查问题是否解决。
7. 验证通过则状态为 `passed`。
8. 验证不通过则保存反馈，并在下一轮传给修复智能体。
9. 两轮修复仍未通过则状态为 `manual_review`。
10. 系统保存差异、状态、报告和事件日志。

## 10. 错误处理与边界情况

| 情况 | 系统行为 |
|---|---|
| 文件不存在 | 返回错误，不生成有效工作流结果 |
| 路径越界 | 通过 `safe_path` 拒绝访问 |
| 二进制文件 | 拒绝按文本处理 |
| 模型输出不是 JSON | 反馈格式错误并重试一次 |
| 修复结果为空 | 工作流报错并停止 |
| 修复代码语法错误 | 记录验证失败，并进入下一轮或人工处理 |
| 验证持续失败 | 最多两轮，最终状态为 `manual_review` |
| 没有审查问题 | 跳过自动修复，保留原代码并进行本地语法检查 |
| 模型调用失败 | 由 `llm.py` 进行最多三次指数退避重试 |
| 上传文件超大或为二进制 | Web 上传接口拒绝请求 |

## 11. 已知限制

1. 当前主要面向 Python 单文件代码。
2. 候选代码不会直接覆盖原文件。
3. 系统没有执行用户代码，静态验证不等同于完整测试。
4. Workflow 网页接口是同步等待请求，长时间任务不适合生产环境。
5. `state.json` 用于记录结果，但尚未实现中断后的自动恢复。
6. 修复质量受所配置的大模型能力影响，最终结果仍需人工复核。

## 12. 后续扩展

- 增加测试生成智能体和隔离测试执行智能体。
- 增加安全规则扫描和代码风格检查工具。
- 支持目录级、多文件依赖分析。
- 将 Workflow 事件通过 SSE 实时推送到页面。
- 增加人工确认节点、断点恢复和运行历史查询。
=======
# code-review-agent-workflow
>>>>>>> f22b013d60cf8e27d487f72190cf351eecb9c58d
