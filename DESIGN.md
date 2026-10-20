# 多智能体代码质量保障系统设计文档

## 1. 设计概述

本项目面向 Python 代码文件，提供“代码审查—代码修复—独立验证”的多智能体 Workflow。它不是一次性让大模型生成审查意见，而是由多个职责明确的智能体通过共享状态和结构化消息协作完成任务。

### 1.1 设计目标

- 展示至少两个 Agent 协作完成完整业务流程。
- 展示 Agent 之间的消息传递和状态共享。
- 支持顺序执行、条件分支、有限循环和失败终态。
- 生成可复核的代码差异、报告、状态和事件日志。
- 复用项目1中的模型客户端、文件工具、安全边界和 Web 入口。
- 保持 MVP 结构简单，便于课堂演示和本地运行。

### 1.2 非目标

- 不直接执行用户提交的 Python 代码。
- 不覆盖原始文件。
- 不实现生产级任务队列和多租户权限系统。
- 不宣称静态验证等同于完整测试或形式化证明。

## 2. 总体架构

```text
┌──────────────────────────────┐
│       CLI / Web 用户入口       │
└──────────────┬───────────────┘
               │ 输入文件路径
               ▼
┌──────────────────────────────┐
│        workflow.py            │
│  工作流编排器与共享状态管理     │
└──────┬──────────┬─────────────┘
       │          ├── syntax_check：本地 AST 语法检查
       │          └── make_diff：生成代码差异
       ▼
┌──────────────────────────────┐
│       代码审查智能体           │
│ REVIEW_PROMPT                 │
│ 输出 findings 和 summary       │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│       代码修复智能体           │
│ REPAIR_PROMPT                 │
│ 输出 candidate_code           │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│       独立验证智能体           │
│ VERIFY_PROMPT                 │
│ 输出 passed、反馈和遗留问题     │
└──────────────┬───────────────┘
               │
       ┌───────┴────────┐
       │                │
    通过 passed      未通过且未超限
       │                │
       ▼                ▼
   输出结果       反馈给修复智能体
                        │
                        └── 最多两轮
```

## 3. Agent 设计

### 3.1 代码审查智能体

输入：文件路径、原始 Python 代码、审查规则和 JSON 输出契约。

职责：识别安全问题、逻辑错误、运行时异常风险和代码质量问题，为每个问题生成稳定的 ID、行号、严重级别、类型、说明和建议。

输出格式：

```json
{
  "findings": [
    {
      "id": "F001",
      "line": 8,
      "severity": "medium",
      "type": "mutable_default",
      "description": "可变默认参数可能导致多次调用共享状态",
      "suggestion": "使用 None 作为默认值并在函数内创建列表"
    }
  ],
  "summary": "发现一个中等风险问题"
}
```

### 3.2 代码修复智能体

输入：原始代码、当前候选代码、审查问题列表和上一轮验证反馈。

职责：只修复审查问题，尽量保持原接口和功能，不引入第三方依赖，并输出完整候选文件。

输出格式：

```json
{
  "candidate_code": "完整 Python 源码",
  "fixed_findings": ["F001"],
  "change_summary": "将可变默认参数改为 None，并在函数内初始化列表"
}
```

### 3.3 独立验证智能体

输入：原始代码、候选修复代码和原始问题列表。

职责：判断原问题是否解决、是否引入新问题以及是否保持基本功能。

输出格式：

```json
{
  "passed": true,
  "remaining_findings": [],
  "feedback": "候选代码已解决原问题，未发现新的明显问题"
}
```

## 4. 共享状态设计

`workflow.py` 使用一个 Python 字典作为单次运行的共享状态，并在运行结束时写入 `state.json`。

```python
state = {
    "run_id": "运行编号",
    "status": "running|passed|manual_review",
    "input_path": "输入文件路径",
    "original_code": "原始代码",
    "candidate_code": "当前候选代码",
    "findings": [],
    "review_summary": "审查总结",
    "repair_round": 0,
    "verification_history": []
}
```

| 字段 | 写入者 | 读取者 | 作用 |
|---|---|---|---|
| `original_code` | 编排器 | 三个智能体 | 保存原始代码 |
| `findings` | 审查智能体 | 修复、验证智能体 | 传递问题清单 |
| `candidate_code` | 修复智能体 | 验证智能体、下一轮修复 | 保存最新候选代码 |
| `verification_history` | 验证阶段 | 下一轮修复、报告生成 | 保存每轮结果和反馈 |
| `repair_round` | 编排器 | 修复阶段、报告 | 控制最大轮次 |
| `status` | 编排器 | Web、报告 | 表示工作流终态 |

## 5. 流程控制

### 5.1 正常流程

```text
读取文件 → 审查 Agent → findings 非空 → 修复 Agent
→ AST 语法检查 → 验证 Agent → passed=true → 输出 passed
```

### 5.2 无问题分支

当审查 Agent 返回空的 `findings` 时，系统跳过自动修复，保留原始代码作为候选代码，使用 `ast.parse` 进行本地语法检查。语法正确则状态为 `passed`，否则状态为 `manual_review`。

### 5.3 验证失败分支

当验证 Agent 返回 `passed=false` 时，系统保存 `feedback`，用 `remaining_findings` 更新问题列表，并进入下一轮修复。`MAX_REPAIR_ROUNDS` 当前为 2，超过上限则状态为 `manual_review`。

### 5.4 语法失败分支

修复 Agent 返回候选代码后，编排器先调用 `syntax_check`。如果 AST 解析失败，不调用验证智能体，而是把语法错误作为反馈传给下一轮修复。两轮仍失败则进入 `manual_review`。

## 6. 消息协议与模型调用

三个智能体均通过 `workflow.py` 的 `call_json` 调用 `llm.chat`。每次调用使用独立的 system prompt 和 user prompt。

`call_json` 的容错流程：

1. 发送角色 Prompt 和任务内容。
2. 使用 `extract_json` 解析模型返回值。
3. 解析失败时将错误反馈给模型。
4. 最多重新请求一次。
5. 连续失败后抛出异常，由上层 Web 或 CLI 捕获。

## 7. 运行产物与可审计性

每次运行生成唯一目录：

```text
runs/<run_id>/
├── original.py
├── fixed.py
├── changes.diff
├── report.md
├── state.json
└── events.jsonl
```

`events.jsonl` 一行记录一个 JSON 事件。主要事件为：

```text
workflow_started
review_agent_started
review_agent_finished
repair_agent_started
repair_agent_finished
verify_agent_started
verify_agent_finished
workflow_finished
```

## 8. 模块职责

| 模块 | 职责 |
|---|---|
| `workflow.py` | 读取代码、调用三个智能体、管理状态、控制分支和生成产物 |
| `workflow_prompts.py` | 定义三个智能体的角色、任务约束和 JSON 输出格式 |
| `llm.py` | 创建 OpenAI 兼容客户端，处理模型调用和重试 |
| `tools.py` | 提供安全路径、文本读取、代码搜索和统一工具入口 |
| `agent.py` | 保留项目1的单 Agent 循环和通用 JSON 提取逻辑 |
| `web.py` | 提供上传、旧版 `/review` 和新版 `/workflow` 接口 |
| `templates/index.html` | 提供代码质量保障系统网页界面 |
| `test_tools.py` | 测试工具层边界和安全行为 |
| `test_workflow.py` | 测试 Workflow 使用的本地语法检查函数 |

## 9. 安全性设计

- 所有输入路径经过 `safe_path`，禁止访问项目根目录外的文件。
- 文件读取限制大小，并检测二进制内容。
- 上传文件使用 UUID 文件名，避免直接使用用户原始文件名拼接路径。
- 不执行候选代码，不调用任意 Shell 命令。
- 候选代码写入独立的 `runs/<run_id>/fixed.py`，不覆盖原文件。
- 模型密钥从 `.env` 读取，不写入源码。

## 10. 测试与验收

### 10.1 工具层验收

```powershell
.\.venv\Scripts\python.exe test_tools.py
```

覆盖文件读取、搜索、路径越界、非法正则、二进制文件、未知工具和错误参数。

### 10.2 Workflow 本地测试

```powershell
.\.venv\Scripts\python.exe test_workflow.py
```

覆盖合法 Python 和非法 Python 的 AST 检查。

### 10.3 端到端验收

```powershell
.\.venv\Scripts\python.exe workflow.py examples\buggy_code.py
```

检查是否生成三个 Agent 阶段事件、`fixed.py`、`changes.diff`、`report.md` 和 `state.json`，以及验证失败时是否最多执行两轮。

### 10.4 Web 验收

```powershell
.\.venv\Scripts\python.exe web.py
```

打开 `http://127.0.0.1:5000`，输入 `examples/buggy_code.py`，点击“运行代码质量保障流程”。页面应显示流程完成、最终状态、运行编号、报告和修改差异。

## 11. 设计取舍与局限

审查、修复和验证存在明确的数据依赖关系，因此采用顺序 Workflow，而不是并行调度。使用结构化状态而不是自然语言串联，可以明确数据边界，降低 Agent 间理解偏差，并方便测试和审计。

当前限制：

- 面向单个 Python 文件。
- Web Workflow 请求同步等待，尚未实时展示每个事件。
- `state.json` 用于记录结果，但尚未实现中断后的自动恢复。
- AST 检查没有执行程序行为测试。
- 模型输出仍可能存在误报或漏报，需要人工复核。

## 12. 可扩展方向

1. 增加测试生成智能体和隔离测试执行智能体。
2. 增加安全规则扫描和代码风格检查工具。
3. 支持目录级、多文件依赖分析。
4. 将 Workflow 事件通过 SSE 实时推送到页面。
5. 增加人工确认节点、断点恢复和运行历史查询。
