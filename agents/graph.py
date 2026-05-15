import difflib
import json

from langgraph.graph import StateGraph, END

from agents.state import ReviewState
from agents.workers import (
    security_worker,
    performance_worker,
    business_logic_worker,
)
from utils.llm_client import get_llm_client

ORCHESTRATOR_PROMPT = """你是一位代码审查决策者(Orchestrator)，负责汇总多个专家的审查意见并做出最终决策。

你的任务：
1. **去重合并**：如果多个专家提到了相同或相似的问题，合并为一条，标注被哪些专家发现
2. **严重等级校准**：审视每条 finding 的 severity，根据实际影响重新校准(critical/high/medium/low)
3. **优先级排序**：按严重程度从高到低排列所有 findings
4. **生成修复代码**：根据所有 findings，生成一份完整的修复后代码
5. **修复说明**：简要说明主要修改了什么

输出格式（严格 JSON）：
{
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "line": 行号(整数),
      "category": "问题类别",
      "code_snippet": "触发问题的具体代码片段（原文中的真实代码，2-5行为宜）",
      "description": "问题描述",
      "suggestion": "修复建议",
      "found_by": ["security", "performance", "business_logic"]
    }
  ],
  "summary": "综合评审总结（含各维度评分概要）",
  "fixed_code": "修复后的完整代码",
  "fix_description": "修复说明"
}

注意：
- fixed_code 必须是完整可运行的代码，不能有省略号或占位符
- 如果某个问题无法自动修复，在 fix_description 中说明原因
- 保留原代码的功能逻辑，只修复问题"""


def start_node(state: ReviewState) -> ReviewState:
    """初始化审查状态。"""
    state["status"] = "reviewing"
    state["error"] = ""
    state["security_review"] = {}
    state["performance_review"] = {}
    state["business_logic_review"] = {}
    state["merged_review"] = {}
    state["fixed_code"] = ""
    state["diff"] = ""
    return state


def orchestrator(state: ReviewState) -> ReviewState:
    """决策者：汇总审查意见、去重、定级、生成修复代码和 Diff。"""
    # 收集三个 Worker 的结果
    reviews = {
        "security": state.get("security_review", {}).get("findings", []),
        "performance": state.get("performance_review", {}).get("findings", []),
        "business_logic": state.get("business_logic_review", {}).get("findings", []),
    }

    # 构建给决策者的审查摘要
    review_summary_parts = []
    for role, findings in reviews.items():
        if isinstance(findings, list) and findings:
            findings_text = json.dumps(findings, ensure_ascii=False, indent=2)
        else:
            findings_text = "无发现问题"
        review_summary_parts.append(f"### {role} 审查结果\n{findings_text}")

    review_summary = "\n\n".join(review_summary_parts)

    # 调用 LLM 进行汇总决策
    client = get_llm_client()
    try:
        raw = client.chat(
            messages=[
                {"role": "system", "content": ORCHESTRATOR_PROMPT},
                {
                    "role": "user",
                    "content": f"""## 原始代码
```python
{state["code"]}
```

## 各专家审查结果
{review_summary}

请汇总并生成修复代码。""",
                },
            ],
            temperature=0.2,
            max_tokens=8192,
            json_mode=True,
        )
        merged = json.loads(raw)
    except Exception as e:
        return {
            "status": "failed",
            "error": f"决策者汇总失败: {e}",
            "merged_review": {"findings": [], "summary": f"汇总失败: {e}"},
        }

    # 生成 Diff
    fixed_code = merged.get("fixed_code", state["code"])
    original_lines = state["code"].splitlines(keepends=True)
    fixed_lines = fixed_code.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile="原始代码",
            tofile="修复后代码",
            lineterm="",
        )
    )

    return {
        "merged_review": merged,
        "fixed_code": fixed_code,
        "diff": diff,
        "status": "completed",
    }


def build_graph() -> StateGraph:
    """构建 LangGraph 审查工作流。"""
    builder = StateGraph(ReviewState)

    # 添加节点
    builder.add_node("start", start_node)
    builder.add_node("security_worker", security_worker)
    builder.add_node("performance_worker", performance_worker)
    builder.add_node("business_logic_worker", business_logic_worker)
    builder.add_node("orchestrator", orchestrator)

    # 设置入口
    builder.set_entry_point("start")

    # start → 并行分发给三个 Worker
    builder.add_edge("start", "security_worker")
    builder.add_edge("start", "performance_worker")
    builder.add_edge("start", "business_logic_worker")

    # 三个 Worker 完成后 → orchestrator（LangGraph 自动等待所有前置节点完成）
    builder.add_edge("security_worker", "orchestrator")
    builder.add_edge("performance_worker", "orchestrator")
    builder.add_edge("business_logic_worker", "orchestrator")

    # orchestrator → 结束
    builder.add_edge("orchestrator", END)

    return builder.compile()


# 全局编译好的 graph 实例
review_graph = build_graph()
