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

输入：原始代码、当前候选代码、原始审查问题、当前待修复问题和上一轮验证反馈。

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

输入：原始代码、候选修复代码、原始问题列表和上一轮待解决问题（包括后来发现的新问题）。

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

`workflow.py` 使用一个 Python 字典作为单次运行的共享状态，在初始化、阶段切换、审查结果更新、每轮验证结束及正常或异常退出时保存到 `state.json`。快照用于排查问题，目前不支持从快照恢复执行。

```python
state = {
    "run_id": "运行编号",
    "status": "running|passed|manual_review|failed",
    "input_path": "输入文件路径",
    "original_code": "原始代码",
    "candidate_code": "当前候选代码",
    "findings": [],
    "review_summary": "审查总结",
    "repair_round": 0,
    "verification_history": [],
    "remaining_findings": [],
    "stage": "initializing",
    "error": ""
}
```

| 字段 | 写入者 | 读取者 | 作用 |
|---|---|---|---|
| `original_code` | 编排器 | 三个智能体 | 保存原始代码 |
| `findings` | 审查阶段 | 修复、验证智能体和报告 | 保留原始问题清单，后续不覆盖 |
| `remaining_findings` | 审查初始化、验证阶段 | 修复和验证智能体、报告 | 保存当前待解决问题，包括新发现的问题 |
| `candidate_code` | 修复智能体 | 验证智能体、下一轮修复 | 保存最新候选代码 |
| `verification_history` | 验证阶段 | 下一轮修复、报告生成 | 保存每轮结果和反馈 |
| `repair_round` | 编排器 | 修复阶段、报告 | 控制最大轮次 |
| `status` | 编排器 | Web、报告 | 表示正在运行、静态检查通过、需要人工复核或异常失败 |
| `stage` | 编排器 | 诊断与日志 | 保存当前或失败阶段 |
| `error` | 异常处理 | 诊断 | 保存异常类型与信息 |

阶段依次涉及 `initializing`、`review`、`repair`、`syntax_check`、`verify`、`writing_outputs`、`completed`；分支会跳过部分阶段。
`status=passed` 只表示本系统静态检查通过，不代表候选代码已通过功能测试。
`status=manual_review` 表示修复预算耗尽或无问题分支中的语法检查失败；`status=failed` 表示受保护流程出现异常。

## 5. 流程控制

### 5.1 正常流程

```text
读取文件 → 审查 Agent → findings 非空 → 修复 Agent
→ AST 语法检查 → 验证 Agent → passed=true → 输出 passed
```

### 5.2 无问题分支

当审查 Agent 返回空的 `findings` 时，系统跳过修复和验证 Agent，保留原始代码作为候选代码，使用 `ast.parse` 进行本地语法检查。语法正确则状态为 `passed`，否则状态为 `manual_review`。

### 5.3 验证失败分支

当验证 Agent 返回 `passed=false` 时，系统保存 `feedback`，更新状态中的 `remaining_findings`，在验证历史中记录反馈和剩余问题，原始 `findings` 保持不变，再进入下一轮修复。`MAX_REPAIR_ROUNDS` 当前为 2，超过上限则状态为 `manual_review`。

### 5.4 语法失败分支

修复 Agent 返回候选代码后，编排器先调用 `syntax_check`。如果 AST 解析失败，不调用验证智能体，而是把语法错误作为反馈传给下一轮修复。两轮仍失败则进入 `manual_review`。

### 5.5 异常失败

创建运行目录和初始状态后，受保护流程中的异常会将状态设为 `failed`，保存失败阶段及 `error`，追加 `workflow_failed` 事件，再向上抛出异常。
此时不保证已经生成最终候选文件、差异或报告。输入文件读取失败发生在运行目录创建前，不保证生成运行记录；磁盘故障也可能使状态或日志无法保存。

## 6. 消息协议与模型调用

三个智能体均通过 `workflow.py` 的 `call_json` 调用 `llm.chat`。每次调用使用独立的 system prompt 和 user prompt。

`call_json(system_prompt, user_prompt, role)` 的容错流程：

1. 使用对应角色的提示词请求模型。
2. 通过 `extract_json` 解析返回值，并通过 `validate_result` 检查协议。
3. 顶层必须是对象；审查要求 `findings` 为对象列表、`summary` 为字符串；修复要求 `candidate_code` 为去除代码围栏后非空的字符串。
4. 验证要求 `passed` 为真正的布尔值、`remaining_findings` 为对象列表、`feedback` 为字符串；通过时剩余问题必须为空。
5. JSON 解析或字段校验失败时反馈错误并重试一次，连续失败则抛出异常。不得把字符串 `"false"` 转换成通过结果。
6. API 异常由 `llm.py` 的调用重试处理；重试耗尽后向 Workflow 传播并记录失败。

目前未校验每条问题对象的全部内部字段，模型静态判断仍可能误报或漏报。

## 7. 运行产物与可审计性

输入读取成功后创建唯一运行目录，正常完成时包含：

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
workflow_failed
```

`workflow_finished` 与 `workflow_failed` 对应正常完成和异常退出；失败目录可能只包含原始代码、状态快照与已记录事件。

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
| `test_workflow.py` | 离线测试输出协议、状态流转、修复循环、异常留痕与产物 |

## 9. 安全性设计

- 所有输入路径经过 `safe_path`，禁止访问项目根目录外的文件。
- Web 上传限制为 1 MB；Workflow 直接读取项目内路径尚无大小上限。二进制判断使用前 1024 字节中的 NUL 字节检测。
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

### 10.2 Workflow 离线测试

```powershell
.\.venv\Scripts\python.exe -m unittest test_tools test_workflow -v
```

`test_workflow.py` 在隔离模块中加载真实 Workflow 和 JSON 解析代码，以模拟响应替代模型请求，绕过 API 客户端初始化，不需要密钥。使用临时目录保存测试产物，不执行候选代码。

覆盖合法与非法语法、第一轮通过、第二轮通过、两轮失败转人工、语法失败跳过验证后重试、无问题分支、无问题但语法错误、缺字段重试、协议错误失败留痕、字符串 false 拒绝、API 故障留痕、原始问题保留与新问题传递、空修复结果以及通过与剩余问题矛盾。

离线测试验证编排逻辑，不验证真实模型质量、供应商连接或浏览器交互。端到端和 Web 验收另行执行。

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
- `state.json` 保存阶段快照和失败信息，但尚未实现中断后的自动恢复，也未采用原子写入。
- AST 检查没有执行程序行为测试。
- 模型输出仍可能存在误报或漏报，需要人工复核。

## 12. 可扩展方向

1. 增加测试生成智能体和隔离测试执行智能体。
2. 增加安全规则扫描和代码风格检查工具。
3. 支持目录级、多文件依赖分析。
4. 将 Workflow 事件通过 SSE 实时推送到页面。
5. 增加人工确认节点、断点恢复和运行历史查询。
