import json

from llm import chat
from prompts import SYSTEM_PROMPT
from tools import execute_tool

ALLOWED_ACTIONS = {"read_file", "search_code", "final"}


def extract_json(text: str) -> dict:
    if not isinstance(text, str):
        raise ValueError("模型返回的不是文本")

    text = text.strip()

    if "```" in text:
        text = text.replace("```json", "").replace("```", "").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("模型没有返回 JSON 对象")

    return json.loads(text[start:end + 1])


def content_to_text(reply) -> str:
    if isinstance(reply, str):
        return reply

    content = getattr(reply, "content", None)
    if content is None:
        raise ValueError("模型返回内容为空")

    return content


def default_on_event(event: dict) -> None:
    """默认事件回调：打印到终端，保持 CLI 行为与原来完全一致。"""
    event_type = event["type"]

    if event_type == "step_start":
        print(f"\n[Agent 第 {event['step']} 步] 正在推理...")
    elif event_type == "tool_call":
        print(f"[工具调用] {event['tool']} {event['arguments']}")
    elif event_type == "tool_result":
        print(f"[工具结果] ok={event['ok']}")
    elif event_type == "parse_error":
        print(f"[解析失败] {event['error']}")


def run_agent(target_path: str, max_steps: int = 8, on_event=None) -> dict:
    """运行一次审查会话。

    on_event 接收进度事件，供 Web 层流式推送；不传时使用默认打印回调。
    事件类型：step_start / tool_call / tool_result / parse_error。
    """
    if on_event is None:
        on_event = default_on_event

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"请审查文件：{target_path}"},
    ]
    trace = []

    for step in range(1, max_steps + 1):
        on_event({"type": "step_start", "step": step})
        reply = content_to_text(chat(messages))

        try:
            action = extract_json(reply)
        except (ValueError, json.JSONDecodeError) as exc:
            on_event({"type": "parse_error", "step": step, "error": str(exc)})
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": f"你的输出不是合法 JSON：{exc}。请只输出一个 JSON 对象。",
            })
            continue

        if not isinstance(action, dict):
            on_event({"type": "parse_error", "step": step,
                      "error": "JSON 顶层必须是对象，请重新输出。"})
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": "JSON 顶层必须是对象，请重新输出。",
            })
            continue

        action_name = action.get("action")

        if action_name not in ALLOWED_ACTIONS:
            on_event({"type": "parse_error", "step": step,
                      "error": f"未知动作：{action_name}"})
            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": "action 只能是 read_file、search_code 或 final，"
                          "请重新输出 JSON。",
            })
            continue

        if action_name == "final":
            answer = (
                action.get("answer")
                or action.get("content")
                or "模型没有提供最终答案。"
            )
            return {"answer": answer, "trace": trace}

        arguments = action.get("arguments", {})

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        on_event({
            "type": "tool_call",
            "step": step,
            "tool": action_name,
            "arguments": arguments,
        })
        result = execute_tool(action_name, arguments)
        on_event({"type": "tool_result", "step": step, "ok": result["ok"]})

        trace.append({
            "step": step,
            "tool": action_name,
            "arguments": arguments,
            "ok": result["ok"],
        })

        messages.append({"role": "assistant", "content": reply})
        messages.append({
            "role": "user",
            "content": "工具执行结果如下：\n"
                       + json.dumps(result, ensure_ascii=False, indent=2),
        })

    return {
        "answer": "达到最大步数，Agent 已停止。请检查文件，或者增大 --max-steps。",
        "trace": trace,
    }
