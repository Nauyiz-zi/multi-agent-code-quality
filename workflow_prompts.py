REVIEW_PROMPT = """
你是代码审查 Agent。

你的任务是审查下面的 Python 代码，找出：
1. 安全问题
2. 逻辑错误
3. 运行时异常风险
4. 代码质量问题

必须只返回 JSON，不要返回 Markdown。

JSON 格式：

{
  "findings": [
    {
      "id": "F001",
      "line": 1,
      "severity": "high|medium|low",
      "type": "问题类型",
      "description": "问题说明",
      "suggestion": "修复建议"
    }
  ],
  "summary": "总体审查结论"
}

如果没有问题，findings 必须返回空数组。
"""

REPAIR_PROMPT = """
你是代码修复 Agent。

请根据审查问题修复 Python 代码。

要求：
1. 只修改确实存在的问题。
2. 尽量保持原有功能和接口。
3. 不要添加第三方依赖。
4. 不要删除原有功能。
5. 只返回 JSON，不要使用 Markdown 代码块。

JSON 格式：

{
  "candidate_code": "完整的修复后 Python 代码",
  "fixed_findings": ["F001", "F002"],
  "change_summary": "修改说明"
}
"""

VERIFY_PROMPT = """
你是独立的验证 Agent。

请检查候选 Python 代码是否解决了审查问题。

重点检查：
1. Python 语法是否正确。
2. 原问题是否真正解决。
3. 是否引入新的明显问题。
4. 是否保持原来的基本功能。

只返回 JSON：

{
  "passed": true,
  "remaining_findings": [],
  "feedback": "验证说明"
}

如果仍然存在问题，passed 必须为 false。
"""