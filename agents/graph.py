import difflib
import json

from langgraph.graph import StateGraph, END

from agents.state import ReviewState
from agents.workers import (
    security_worker,
    performance_worker,
    business_logic_worker,
    architecture_worker,
)
from utils.llm_client import get_llm_client
from tools.code_metrics import run_code_metrics

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
      "found_by": ["security", "performance", "business_logic", "architecture"]
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

FIX_PROMPT = """你是一位代码修复专家。你的代码修复方案在自动化工具中检查时发现了以下错误，请根据错误信息修复代码。

要求：
1. 只修复与报错相关的问题，不要做无关改动
2. 返回完整的修复后代码
3. 保持原有功能逻辑不变

输出格式（严格 JSON）：
{
  "fixed_code": "修复后的完整代码",
  "fix_description": "本轮修改说明"
}"""


def start_node(state: ReviewState) -> ReviewState:
    """初始化审查状态。"""
    state["status"] = "reviewing"
    state["error"] = ""
    state["security_review"] = {}
    state["performance_review"] = {}
    state["business_logic_review"] = {}
    state["architecture_review"] = {}
    state["code_metrics"] = {}
    state["merged_review"] = {}
    state["fixed_code"] = ""
    state["diff"] = ""
    # Run code metrics (radon) for business logic & architecture workers
    try:
        state["code_metrics"] = run_code_metrics(state["code"])
    except Exception:
        state["code_metrics"] = {}
    return state


def orchestrator(state: ReviewState) -> ReviewState:
    """决策者：汇总审查意见、去重、定级、生成修复代码，并在沙箱中多轮自修。"""
    # 收集四个 Worker 的结果
    reviews = {
        "security": state.get("security_review", {}).get("findings", []),
        "performance": state.get("performance_review", {}).get("findings", []),
        "business_logic": state.get("business_logic_review", {}).get("findings", []),
        "architecture": state.get("architecture_review", {}).get("findings", []),
    }

    review_summary_parts = []
    for role, findings in reviews.items():
        if isinstance(findings, list) and findings:
            findings_text = json.dumps(findings, ensure_ascii=False, indent=2)
        else:
            findings_text = "无发现问题"
        review_summary_parts.append(f"### {role} 审查结果\n{findings_text}")
    review_summary = "\n\n".join(review_summary_parts)

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
        merged = json.loads(raw["content"])
        orch_usage = raw["usage"]
    except Exception as e:
        return {
            "status": "failed",
            "error": f"决策者汇总失败: {e}",
            "merged_review": {"findings": [], "summary": f"汇总失败: {e}"},
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # ── Docker 沙箱多轮自修 ──────────────────
    fixed_code = merged.get("fixed_code", state["code"])
    sandbox_rounds = 0
    sandbox_errors = []
    try:
        from sandbox import create_container, destroy_container, run_toolchain

        container_id = create_container()
        try:
            for round_num in range(3):
                tool_result = run_toolchain(fixed_code, container_id)
                if tool_result.passed:
                    sandbox_rounds = round_num + 1
                    break
                sandbox_errors = tool_result.errors[:20]
                sandbox_rounds = round_num + 1

                # 构建聚焦提示：仅传上一轮 diff + 结构化错误
                errors_text = json.dumps(sandbox_errors, ensure_ascii=False, indent=2)
                current_diff = "".join(
                    difflib.unified_diff(
                        state["code"].splitlines(keepends=True),
                        fixed_code.splitlines(keepends=True),
                        fromfile="原始代码", tofile=f"第{round_num + 1}轮修复",
                        lineterm="",
                    )
                )
                try:
                    fix_raw = client.chat(
                        messages=[
                            {"role": "system", "content": FIX_PROMPT},
                            {
                                "role": "user",
                                "content": f"""## 当前修复的 Diff
```diff
{current_diff}
```

## 工具链报错（结构化）
```json
{errors_text}
```

请根据上述错误信息修复代码。""",
                            },
                        ],
                        temperature=0.2,
                        max_tokens=8192,
                        json_mode=True,
                    )
                    fix_result = json.loads(fix_raw["content"])
                    fixed_code = fix_result.get("fixed_code", fixed_code)
                    for k in ["prompt_tokens", "completion_tokens", "total_tokens"]:
                        orch_usage[k] = orch_usage.get(k, 0) + fix_raw["usage"].get(k, 0)
                except Exception:
                    break
        finally:
            destroy_container(container_id)
    except Exception:
        # Docker 不可用时跳过沙箱
        sandbox_errors = [{"tool": "sandbox", "line": 0, "col": 0, "code": "SKIP", "message": "沙箱不可用（Docker 未启动或镜像未构建）"}]

    if sandbox_errors and sandbox_rounds >= 3:
        merged["fix_description"] = (merged.get("fix_description", "") +
            f"（经 {sandbox_rounds} 轮沙箱修复，仍存在 {len(sandbox_errors)} 个工具链错误，需人工检查）")
    elif sandbox_rounds > 0:
        merged["fix_description"] = (merged.get("fix_description", "") +
            f"（经沙箱 {sandbox_rounds} 轮修复验证通过）")
    # ── 沙箱自修结束 ──────────────────────────

    # 汇总所有 token 用量
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for review_key in ["security_review", "performance_review", "business_logic_review", "architecture_review"]:
        review = state.get(review_key, {})
        u = review.get("_usage", {})
        for k in total_usage:
            total_usage[k] += u.get(k, 0)
    for k in total_usage:
        total_usage[k] += orch_usage.get(k, 0)

    # 生成最终 Diff（原始代码 vs 最终修复后代码）
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
        "token_usage": total_usage,
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
    builder.add_node("architecture_worker", architecture_worker)
    builder.add_node("orchestrator", orchestrator)

    # 设置入口
    builder.set_entry_point("start")

    # start → 并行分发给四个 Worker
    builder.add_edge("start", "security_worker")
    builder.add_edge("start", "performance_worker")
    builder.add_edge("start", "business_logic_worker")
    builder.add_edge("start", "architecture_worker")

    # 四个 Worker 完成后 → orchestrator（LangGraph 自动等待所有前置节点完成）
    builder.add_edge("security_worker", "orchestrator")
    builder.add_edge("performance_worker", "orchestrator")
    builder.add_edge("business_logic_worker", "orchestrator")
    builder.add_edge("architecture_worker", "orchestrator")

    # orchestrator → 结束
    builder.add_edge("orchestrator", END)

    return builder.compile()


# 全局编译好的 graph 实例
review_graph = build_graph()
