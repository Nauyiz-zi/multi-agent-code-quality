import tempfile
import unittest
from pathlib import Path

from tools import ROOT, execute_tool, read_file, search_code


class TestReadFile(unittest.TestCase):
    """read_file 的正常流程与边界情况。"""

    def test_read_returns_numbered_lines(self):
        result = read_file("llm.py", 1, 5)
        self.assertIn(":", result)
        self.assertTrue(result.splitlines()[0].startswith("1:"))
        self.assertEqual(len(result.splitlines()), 5)

    def test_missing_file(self):
        result = execute_tool("read_file", {"path": "not_exist.py"})
        self.assertFalse(result["ok"])
        self.assertIn("文件不存在", result["error"])

    def test_directory_not_file(self):
        result = execute_tool("read_file", {"path": "examples"})
        self.assertFalse(result["ok"])
        self.assertIn("这不是文件", result["error"])

    def test_start_beyond_total_lines(self):
        result = read_file("llm.py", 999999)
        self.assertIn("超过文件总行数", result)

    def test_invalid_range(self):
        result = read_file("llm.py", 10, 5)
        self.assertIn("无效范围", result)

    def test_empty_file(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            empty = Path(tmp) / "empty.py"
            empty.write_bytes(b"")
            result = read_file(str(empty.relative_to(ROOT)))
            self.assertEqual(result, "(空文件)")

    def test_binary_file_rejected(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            binary = Path(tmp) / "data.bin"
            binary.write_bytes(b"\x00\x01\x02")
            result = execute_tool(
                "read_file", {"path": str(binary.relative_to(ROOT))}
            )
            self.assertFalse(result["ok"])
            self.assertIn("二进制", result["error"])


class TestSearchCode(unittest.TestCase):
    """search_code 的正常流程与边界情况。"""

    def test_search_finds_definitions(self):
        result = search_code("def ", ".")
        self.assertIn("def ", result)

    def test_invalid_regex(self):
        result = execute_tool("search_code", {"pattern": "["})
        self.assertFalse(result["ok"])
        self.assertIn("正则表达式错误", result["error"])

    def test_no_match(self):
        result = search_code("zzz_no_such_pattern_zzz", "examples")
        self.assertEqual(result, "未找到匹配")


class TestExecuteTool(unittest.TestCase):
    """execute_tool 统一入口的错误封装。"""

    def test_unknown_tool(self):
        result = execute_tool("unknown_tool", {})
        self.assertFalse(result["ok"])
        self.assertIn("未知工具", result["error"])

    def test_relative_path_escape_rejected(self):
        result = execute_tool("read_file", {"path": "../secret.txt"})
        self.assertFalse(result["ok"])
        self.assertIn("路径越界", result["error"])

    def test_absolute_path_outside_root_rejected(self):
        outside = str(ROOT.parent / "outside.txt")
        result = execute_tool("read_file", {"path": outside})
        self.assertFalse(result["ok"])
        self.assertIn("路径越界", result["error"])

    def test_missing_required_argument(self):
        result = execute_tool("read_file", {})
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
