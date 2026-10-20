import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".vscode",
}
MAX_FILE_SIZE = 1_000_000
MAX_SEARCH_FILE_SIZE = 500_000


def safe_path(user_path: str) -> Path:
    raw = Path(user_path)
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        candidate = (ROOT / raw).resolve()
        
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError(f"路径越界，只能访问项目目录内的文件：{user_path}")
        
    return candidate

def read_file(path: str, start: int = 1, end: int | None = None) -> str:
    target = safe_path(path)
    
    if not target.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    if not target.is_file():
        raise IsADirectoryError(f"这不是文件：{path}")
    if target.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("文件太大，请用start和end分段读取")
        
    raw = target.read_bytes()
    
    if b"\x00" in raw[:1024]:
        raise ValueError("这是二进制文件，无法按文本读取")
        
    lines = raw.decode("utf-8",errors="replace").splitlines()
    
    if not lines:
        return "(空文件)"
    
    start = max(1, int(start or 1))
    end = min(len(lines), int(end) if end is not None else len(lines))

    if start > len(lines):
        return f"(起始行{start}超过文件总行数{len(lines)})"
    if start > end:
        return f"(无效范围：start={start},end={end})"

    return "\n".join(
        f"{number}:{lines[number - 1]}"
        for number in range(start, end + 1)
    )

def search_code(pattern: str, path: str = ".", max_results: int = 50) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"正则表达式错误：{exc}") from exc
        
    target = safe_path(path)
    
    if not target.exists():
        raise FileNotFoundError(f"路径不存在：{path}")
        
    files = [target] if target.is_file() else list(target.rglob("*"))
    matches = []
    
    for file in files:
        if not file.is_file():
            continue
        if any(part in IGNORED_DIRS for part in file.parts):
            continue
        if file.stat().st_size > MAX_SEARCH_FILE_SIZE:
            continue
        
        try:
            raw = file.read_bytes()
        except OSError:
            continue
        
        if b"\x00" in raw[:1024]:
            continue
        
        lines = raw.decode("utf-8",errors="replace").splitlines()
        
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                relative = file.relative_to(ROOT)
                matches.append(f"{relative}:{number}:{line.strip()}")
                if len(matches) >= max_results:
                    return "\n".join(matches)
                
    return "\n".join(matches) if matches else "未找到匹配"

TOOLS = {
    "read_file": read_file,
    "search_code": search_code,
}


def execute_tool(name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        return {"ok": False, "error": f"未知工具：{name}"}

    try:
        result = TOOLS[name](**arguments)
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}