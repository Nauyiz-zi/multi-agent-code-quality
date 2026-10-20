import json
import queue
import threading
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from agent import run_agent
from tools import MAX_FILE_SIZE, ROOT

from workflow import run_workflow

UPLOAD_DIR = ROOT / "uploads"

app = Flask(__name__)

# ---------- 上传 ----------

def is_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:1024]


@app.post("/upload")
def upload():
    file = request.files.get("file")
    if file is None:
        return jsonify({"ok": False, "error": "没有收到文件"}), 400

    raw = file.read(MAX_FILE_SIZE + 1)
    if len(raw) > MAX_FILE_SIZE:
        return jsonify({"ok": False, "error": "文件太大，最大 1MB"}), 400
    if is_binary(raw):
        return jsonify({"ok": False, "error": "不支持二进制文件"}), 400

    UPLOAD_DIR.mkdir(exist_ok=True)
    suffix = Path(file.filename or "upload.txt").suffix or ".txt"
    saved_name = f"{uuid.uuid4().hex}{suffix}"
    (UPLOAD_DIR / saved_name).write_bytes(raw)

    return jsonify({
        "ok": True,
        "path": f"uploads/{saved_name}",
        "original_name": file.filename,
    })


# ---------- 审查（SSE 流式推送） ----------

def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/review")
def review():
    payload = request.get_json(silent=True) or {}
    target = (payload.get("path") or "").strip()
    max_steps = payload.get("max_steps") or 8

    if not target:
        return jsonify({"ok": False, "error": "请提供文件路径"}), 400
    if not isinstance(max_steps, int) or not 1 <= max_steps <= 20:
        max_steps = 8

    events = queue.Queue()

    def run():
        try:
            result = run_agent(target, max_steps=max_steps,
                               on_event=events.put)
            events.put({
                "type": "done",
                "answer": result["answer"],
                "trace": result["trace"],
            })
        except Exception as exc:
            events.put({"type": "done", "error": str(exc)})

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            try:
                event = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"  # 心跳注释，防止连接超时
                continue
            yield sse(event)
            if event["type"] == "done":
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache"})

@app.post("/workflow")
def workflow():
    payload = request.get_json(silent=True) or {}
    target = (payload.get("path") or "").strip()

    if not target:
        return jsonify({
            "ok": False,
            "error": "请提供文件路径",
        }), 400

    try:
        result = run_workflow(target)

        run_dir = ROOT / "runs" / result["run_id"]

        report_path = run_dir / "report.md"
        diff_path = run_dir / "changes.diff"

        report = (
            report_path.read_text(encoding="utf-8")
            if report_path.exists()
            else "报告文件不存在"
        )

        diff = (
            diff_path.read_text(encoding="utf-8")
            if diff_path.exists()
            else "没有生成代码差异"
        )

        return jsonify({
            "ok": True,
            "status": result["status"],
            "run_id": result["run_id"],
            "report": report,
            "diff": diff,
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500

@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    UPLOAD_DIR.mkdir(exist_ok=True)
    print("代码审查 Agent 网页版已启动：http://127.0.0.1:5000")
    app.run(debug=False, threaded=True)
