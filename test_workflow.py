"""离线测试：不读取 API Key，不调用真实模型，不执行候选代码。"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


def load_local(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def block_network(*args, **kwargs):
    raise AssertionError("测试禁止调用真实模型")


fake_llm = types.ModuleType("llm")
fake_llm.chat = block_network
with patch.dict(sys.modules, {"llm": fake_llm}):
    local_agent = load_local("_agent_under_test", "agent.py")
    with patch.dict(sys.modules, {"agent": local_agent}):
        workflow = load_local("_workflow_under_test", "workflow.py")


def finding(identifier="F001"):
    return {"id": identifier, "line": 1, "severity": "medium",
            "type": "logic", "description": "示例问题", "suggestion": "修复问题"}


def review(findings=None):
    return {"findings": [finding()] if findings is None else findings,
            "summary": "审查完成"}


def repair(code="x = 2\n"):
    return {"candidate_code": code}


def verify(passed=True, remaining=None):
    return {"passed": passed, "remaining_findings": [] if remaining is None else remaining,
            "feedback": "验证通过" if passed else "请继续修复"}


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name) / "runs"
        self.original_code = "x = 1\n"
        self.source = workflow.ROOT / "examples" / "buggy_code.py"
        for patcher in [
            patch.object(workflow, "RUNS_DIR", self.runs),
            patch.object(workflow, "MAX_REPAIR_ROUNDS", 2),
            patch.object(workflow, "read_source_file",
                         side_effect=lambda _: (self.source, self.original_code)),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def execute(self, replies):
        responses = iter(replies)

        def respond(messages):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

        with patch.object(workflow, "chat", side_effect=respond) as chat:
            self.chat = chat
            with contextlib.redirect_stdout(io.StringIO()):
                return workflow.run_workflow("examples/buggy_code.py")

    def artifacts(self):
        directories = list(self.runs.iterdir())
        self.assertEqual(len(directories), 1)
        return directories[0]

    def disk_state(self):
        return json.loads((self.artifacts() / "state.json").read_text(encoding="utf-8"))

    def events(self):
        return [json.loads(line) for line in
                (self.artifacts() / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_valid_python(self):
        self.assertTrue(workflow.syntax_check("x = 1\nprint(x)")["passed"])

    def test_invalid_python(self):
        self.assertFalse(workflow.syntax_check("def broken(:")["passed"])

    def test_first_round_success_and_artifacts(self):
        state = self.execute([review(), repair(), verify()])
        self.assertEqual((state["status"], state["repair_round"]), ("passed", 1))
        self.assertEqual(self.chat.call_count, 3)
        self.assertEqual(state["stage"], "completed")
        for filename in ["original.py", "fixed.py", "changes.diff", "report.md",
                         "state.json", "events.jsonl"]:
            self.assertTrue((self.artifacts() / filename).is_file(), filename)
        self.assertEqual(self.disk_state(), state)
        self.assertEqual(self.events()[-1]["type"], "workflow_finished")

    def test_second_round_success(self):
        state = self.execute([review(), repair(), verify(False, [finding()]), repair(), verify()])
        self.assertEqual((state["status"], state["repair_round"]), ("passed", 2))
        self.assertEqual([x["passed"] for x in state["verification_history"]], [False, True])
        self.assertEqual(self.chat.call_count, 5)

    def test_two_failures_require_manual_review(self):
        state = self.execute([review(), repair(), verify(False, [finding()]),
                              repair(), verify(False, [finding()])])
        self.assertEqual((state["status"], state["repair_round"]), ("manual_review", 2))
        self.assertEqual(self.chat.call_count, 5)

    def test_syntax_failure_skips_verifier_then_retries(self):
        state = self.execute([review(), repair("def broken(:"), repair(), verify()])
        self.assertEqual(state["status"], "passed")
        self.assertFalse(state["verification_history"][0]["passed"])
        starts = [e for e in self.events() if e["type"] == "verify_agent_started"]
        self.assertEqual([e["round"] for e in starts], [2])
        self.assertEqual(self.chat.call_count, 4)

    def test_clean_input_skips_repair_and_verifier(self):
        state = self.execute([review([])])
        self.assertEqual((state["status"], state["repair_round"]), ("passed", 0))
        self.assertEqual(self.chat.call_count, 1)
        self.assertEqual(state["candidate_code"], self.original_code)

    def test_clean_review_with_invalid_syntax_needs_manual_review(self):
        self.original_code = "def broken(:"
        state = self.execute([review([])])
        self.assertEqual(state["status"], "manual_review")

    def test_missing_review_fields_retry(self):
        state = self.execute([{}, review([])])
        self.assertEqual(state["status"], "passed")
        self.assertEqual(self.chat.call_count, 2)

    def test_invalid_review_fails_and_saves_state(self):
        with self.assertRaisesRegex(RuntimeError, "JSON"):
            self.execute([{}, {}])
        self.assertEqual(self.disk_state()["status"], "failed")
        self.assertEqual(self.disk_state()["stage"], "review")
        self.assertEqual(self.events()[-1]["type"], "workflow_failed")

    def test_string_false_rejected(self):
        invalid = {"passed": "false", "remaining_findings": [], "feedback": "未通过"}
        with self.assertRaises(RuntimeError):
            self.execute([review(), repair(), invalid, invalid])
        self.assertEqual(self.disk_state()["status"], "failed")
        self.assertEqual(self.disk_state()["stage"], "verify")

    def test_api_failure_saves_review_and_error(self):
        with self.assertRaisesRegex(RuntimeError, "模拟 API 故障"):
            self.execute([review(), RuntimeError("模拟 API 故障")])
        state = self.disk_state()
        self.assertEqual((state["status"], state["stage"]), ("failed", "repair"))
        self.assertEqual(state["findings"], [finding()])
        self.assertIn("模拟 API 故障", state["error"])
        self.assertEqual(self.events()[-1]["type"], "workflow_failed")

    def test_original_findings_preserved_and_new_issue_forwarded(self):
        original = [finding("F001"), finding("F002")]
        remaining = [finding("F002"), finding("F003")]
        state = self.execute([review(original), repair(), verify(False, remaining), repair(), verify()])
        self.assertEqual(state["findings"], original)
        self.assertEqual(state["remaining_findings"], [])
        self.assertEqual(state["verification_history"][0]["remaining_findings"], remaining)
        calls = self.chat.call_args_list
        self.assertIn("F003", calls[3].args[0][1]["content"])
        self.assertIn("F003", calls[4].args[0][1]["content"])
        report = (self.artifacts() / "report.md").read_text(encoding="utf-8")
        self.assertIn("F001", report)
        self.assertIn("F002", report)

    def test_empty_repair_retries_and_fails(self):
        with self.assertRaises(RuntimeError):
            self.execute([review(), repair(""), repair("  ")])
        self.assertEqual(self.disk_state()["stage"], "repair")
        self.assertEqual(self.disk_state()["status"], "failed")

    def test_passed_with_remaining_findings_rejected(self):
        with self.assertRaises(ValueError):
            workflow.validate_result(verify(True, [finding()]), "verify")


if __name__ == "__main__":
    unittest.main(verbosity=2)
