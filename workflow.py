import ast
import difflib
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from agent import extract_json
from llm import chat
from tools import safe_path

from workflow_prompts import (
    REVIEW_PROMPT,
    REPAIR_PROMPT,
    VERIFY_PROMPT,
)


ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"
MAX_REPAIR_ROUNDS = 2


def now():
    return datetime.now().isoformat(timespec="seconds")


def clean_code(text):
    """
    删除模型可能返回的 Markdown 代码围栏。
    """
    text = str(text).strip()

    match = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    if match:
        return match.group(1).strip()

    return text

def validate_result(data, role):
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是对象")

    def require(name, expected_type):
        if name not in data or type(data[name]) is not expected_type:
            raise ValueError(
                f"{name} 必须存在，类型必须是 {expected_type.__name__}"
            )

    def require_findings(name):
        require(name, list)
        if not all(isinstance(item, dict) for item in data[name]):
            raise ValueError(f"{name} 中的每个问题必须是对象")

    if role == "review":
        require_findings("findings")
        require("summary", str)

    elif role == "repair":
        require("candidate_code", str)
        if not clean_code(data["candidate_code"]):
            raise ValueError("candidate_code 不能为空")

    elif role == "verify":
        require("passed", bool)
        require_findings("remaining_findings")
        require("feedback", str)

        if data["passed"] and data["remaining_findings"]:
            raise ValueError("通过时 remaining_findings 必须为空")

    else:
        raise ValueError(f"未知角色：{role}")

    return data

def call_json(system_prompt, user_prompt, role):
    """
    调用模型并解析 JSON。
    如果模型第一次输出格式错误，反馈一次后重试。
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for _ in range(2):
        reply = chat(messages)

        try:
            data = extract_json(reply)
            return validate_result(data, role)
        except Exception as exc:
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": (
                    f"你的输出不符合要求：{exc}。"
                    "请检查必填字段及字段类型，严格返回一个 JSON 对象。"
                ),
            })

    raise RuntimeError("模型连续两次输出不符合 JSON 协议")


def read_source_file(path):
    target = safe_path(path)

    if not target.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    if not target.is_file():
        raise IsADirectoryError(f"不是文件：{path}")

    raw = target.read_bytes()

    if b"\x00" in raw[:1024]:
        raise ValueError("不支持二进制文件")

    return target, raw.decode("utf-8", errors="replace")


def syntax_check(code):
    """
    本地语法验证，不执行用户代码。
    """
    try:
        ast.parse(code)
        return {
            "passed": True,
            "error": "",
        }
    except SyntaxError as exc:
        return {
            "passed": False,
            "error": f"第 {exc.lineno} 行语法错误：{exc.msg}",
        }


def append_event(run_dir, event_type, **data):
    event = {
        "time": now(),
        "type": event_type,
        **data,
    }

    with (run_dir / "events.jsonl").open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")

    print(f"[{event_type}] {data}")


def save_state(run_dir, state):
    with (run_dir / "state.json").open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def make_diff(original, candidate, filename):
    lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        candidate.splitlines(keepends=True),
        fromfile=f"{filename}.original",
        tofile=f"{filename}.fixed",
    )
    return "".join(lines)


def make_report(state):
    lines = [
        "# 代码审查—修复—验证报告",
        "",
        f"- 输入文件：`{state['input_path']}`",
        f"- 最终状态：`{state['status']}`",
        f"- 修复轮次：`{state['repair_round']}`",
        "",
        "## 审查结果",
        "",
        state["review_summary"],
        "",
    ]

    findings = state["findings"]

    if findings:
        for item in findings:
            lines.extend([
                f"### {item.get('id', 'UNKNOWN')} "
                f"[{item.get('severity', 'unknown')}]",
                "",
                f"- 行号：{item.get('line', '?')}",
                f"- 类型：{item.get('type', '')}",
                f"- 问题：{item.get('description', '')}",
                f"- 建议：{item.get('suggestion', '')}",
                "",
            ])
    else:
        lines.extend([
            "未发现需要修复的问题。",
            "",
        ])

    lines.extend([
        "## 验证历史",
        "",
    ])

    for item in state["verification_history"]:
        lines.extend([
            f"- 第 {item['round']} 轮："
            f"`{'通过' if item['passed'] else '未通过'}`",
            f"  - {item['feedback']}",
        ])
        
    lines.extend([
        "",
        "## 最终待解决问题",
        "",
    ])

    if state["remaining_findings"]:
        for finding in state["remaining_findings"]:
            lines.append(
                f"- {finding.get('id', 'UNKNOWN')}："
                f"{finding.get('description', '')}"
            )
    else:
        lines.append("无已记录的待解决问题。")
    
    lines.extend([
        "",
        "验证范围：AST 语法检查与模型静态审查，未执行候选代码的功能测试。",
        "",
    ])

    lines.extend([
        "",
        "## 产物",
        "",
        "- `original.py`：原始代码",
        "- `fixed.py`：最终候选代码",
        "- `changes.diff`：修改差异",
        "- `state.json`：共享状态",
        "- `events.jsonl`：执行日志",
    ])

    return "\n".join(lines)


def run_workflow(input_path):
    target, original_code = read_source_file(input_path)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    relative_path = str(target.relative_to(ROOT))

    state = {
        "run_id": run_id,
        "status": "running",
        "input_path": relative_path,
        "original_code": original_code,
        "candidate_code": original_code,
        "findings": [],
        "review_summary": "",
        "repair_round": 0,
        "remaining_findings": [],
        "verification_history": [],
        "stage": "initializing",
        "error": "",
    }
    
    save_state(run_dir, state)

    try:
        (run_dir / "original.py").write_text(
            original_code,
            encoding="utf-8",
        )
    
        append_event(run_dir, "workflow_started", path=relative_path)
    
        # Agent 1：审查
        state["stage"] = "review" 
        save_state(run_dir, state) 

        append_event(run_dir, "review_agent_started")
    
        review_result = call_json(
            REVIEW_PROMPT,
            f"""
    文件路径：{relative_path}
    
    代码如下：
    
    {original_code}
    """,
            role="review",
        )
    
        state["findings"] = review_result["findings"]
        state["remaining_findings"] = list(state["findings"])
        state["review_summary"] = review_result["summary"]
        
        save_state(run_dir, state) 
    
        append_event(
            run_dir,
            "review_agent_finished",
            finding_count=len(state["findings"]),
        )
    
        # 没有发现问题时，跳过修复和验证 Agent，仅执行本地语法检查
        if not state["findings"]:
            state["stage"] = "syntax_check"
            save_state(run_dir, state)
            
            syntax_result = syntax_check(original_code)
    
            state["verification_history"].append({
                "round": 0,
                "passed": syntax_result["passed"],
                "feedback": syntax_result["error"] or "没有发现问题，语法检查通过。",
            })
    
            state["status"] = (
                "passed"
                if syntax_result["passed"]
                else "manual_review"
            )
    
            state["candidate_code"] = original_code
    
        else:
            # Agent 2：修复；Agent 3：验证
            for repair_round in range(1, MAX_REPAIR_ROUNDS + 1):
                state["repair_round"] = repair_round
    
                state["stage"] = "repair"
                save_state(run_dir, state)
                
                append_event(
                    run_dir,
                    "repair_agent_started",
                    round=repair_round,
                )
    
                repair_result = call_json(
                    REPAIR_PROMPT,
                    f"""
    原始代码：
    
    {original_code}
    
    当前代码：
    
    {state['candidate_code']}
    
    原始审查问题：
    
    {json.dumps(state['findings'], ensure_ascii=False, indent=2)}
    
    当前待修复问题：
    
    {json.dumps(state['remaining_findings'], ensure_ascii=False, indent=2)}
    
    上一轮验证反馈：
    
    {json.dumps(
        state["verification_history"][-1]
        if state["verification_history"]
        else {},
        ensure_ascii=False,
        indent=2,
    )}
    """,
                        role="repair",
                    )
    
                candidate = clean_code(
                    repair_result.get("candidate_code", "")
                )
    
                if not candidate:
                    raise RuntimeError("修复 Agent 没有返回 candidate_code")
    
                state["candidate_code"] = candidate
                
                state["stage"] = "syntax_check" 
                save_state(run_dir, state)
    
                syntax_result = syntax_check(candidate)
    
                append_event(
                    run_dir,
                    "repair_agent_finished",
                    round=repair_round,
                    syntax_passed=syntax_result["passed"],
                )
    
                if not syntax_result["passed"]:
                    verification = {
                        "passed": False,
                        "remaining_findings": list(state["remaining_findings"]),
                        "feedback": syntax_result["error"],
                    }
                else:
                    state["stage"] = "verify"
                    save_state(run_dir, state)
                    
                    append_event(
                        run_dir,
                        "verify_agent_started",
                        round=repair_round,
                    )
    
                    verification = call_json(
                        VERIFY_PROMPT,
                        f"""
    原始代码：
    
    {original_code}
    
    候选修复代码：
    
    {candidate}
    
    原始审查问题：

    {json.dumps(state['findings'], ensure_ascii=False, indent=2)}
    
    上一轮待解决问题（包括后来发现的新问题）：
    
    {json.dumps(state['remaining_findings'], ensure_ascii=False, indent=2)}
    """,
                        role="verify",
                    )
    
                    append_event(
                        run_dir,
                        "verify_agent_finished",
                        round=repair_round,
                        passed=verification.get("passed", False),
                    )
    
                if type(verification.get("passed")) is not bool:
                    raise ValueError("验证结果的 passed 必须是布尔值")
    
                passed = verification["passed"]
    
                state["remaining_findings"] = verification["remaining_findings"]
    
                state["verification_history"].append({
                    "round": repair_round,
                    "passed": passed,
                    "feedback": verification["feedback"],
                    "remaining_findings": list(state["remaining_findings"]),
                })
    
                save_state(run_dir, state)
    
                if passed:
                    state["status"] = "passed"
                    break
    
            else:
                state["status"] = "manual_review"
    
        state["stage"] = "writing_outputs"
        save_state(run_dir, state)
    
        (run_dir / "fixed.py").write_text(
            state["candidate_code"],
            encoding="utf-8",
        )
    
        diff = make_diff(
            original_code,
            state["candidate_code"],
            Path(relative_path).name,
        )
    
        (run_dir / "changes.diff").write_text(
            diff,
            encoding="utf-8",
        )
    
        (run_dir / "report.md").write_text(
            make_report(state),
            encoding="utf-8",
        )
    
        state["stage"] = "completed"
        save_state(run_dir, state)
        append_event(run_dir, "workflow_finished", status=state["status"])
        
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
    
        save_state(run_dir, state)
    
        append_event(
            run_dir,
            "workflow_failed",
            stage=state["stage"],
            error=state["error"],
        )
    
        raise

    print()
    print(f"工作流完成：{state['status']}")
    print(f"运行目录：{run_dir}")
    print(f"报告文件：{run_dir / 'report.md'}")

    return state


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：py -3 workflow.py examples/buggy_code.py")
        raise SystemExit(1)

    run_workflow(sys.argv[1])