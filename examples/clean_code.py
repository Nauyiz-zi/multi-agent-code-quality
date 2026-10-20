from pathlib import Path


def add(a: int, b: int) -> int:
    return a + b


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")