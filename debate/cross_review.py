"""单轮交叉审查：各 Agent 对其他 Agent 的 findings 发表质疑。"""

import json
from utils.llm_client import get_llm_client

CROSS_REVIEW_PROMPT = """你是一位资深代码审查员，现在参与一场交叉审查。你的同事审查员提出了一些发现（findings），其中部分可能来自你自己，部分来自其他审查员。

你的任务：对其他审查员的发现发表质疑或认同意见。对于你自己的发现，只需标注 "MINE"，不要重复审查。

对每个发现发表意见：
- "agree": 认同该发现
- "disagree": 不认同，问题不存在或描述有误
- "refine": 认同有问题，但严重等级或描述需要调整
- "MINE": 该发现是你自己提出的（跳过）

输出格式（严格 JSON）：
{
  "cross_opinions": [
    {
      "finding_index": 该发现在输入列表中的索引(整数，从0开始),
      "opinion": "agree|disagree|refine|MINE",
      "confidence": "high|medium|low",
      "reasoning": "简短理由（1-2句）",
      "revised_severity": "critical|high|medium|low（仅 opinion=refine 时填写，可选）"
    }
  ]
}"""


def run_cross_review(
    agent_name: str,
    findings: list[dict],
    code: str,
) -> dict:
    """让指定 Agent 对其他 findings 进行交叉审查。

    Args:
        agent_name: 审查员名称（security/performance/business_logic/architecture）
        findings: 预汇总的 findings 列表（不含 found_by 字段）
        code: 原始代码

    Returns:
        {"agent": agent_name, "cross_opinions": [...], "_usage": {...}}
    """
    if not findings:
        return {"agent": agent_name, "cross_opinions": [], "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

    # 标注哪些是该 agent 自己发现的
    own_indices = [i for i, f in enumerate(findings) if agent_name in (f.get("found_by") or [])]
    own_hint = f"你已经发现的问题索引: {own_indices}" if own_indices else ""

    findings_text = json.dumps(findings, ensure_ascii=False, indent=2)

    client = get_llm_client()
    try:
        raw = client.chat(
            messages=[
                {"role": "system", "content": CROSS_REVIEW_PROMPT},
                {"role": "user", "content": f"""## 原始代码
```python
{code[:6000]}
```

## 所有发现
```json
{findings_text}
```

## 你的身份
你是 **{agent_name}** 专家。
{own_hint}

请对其他审查员的发现发表意见。"""},
            ],
            temperature=0.2,
            max_tokens=4096,
            json_mode=True,
        )
        result = json.loads(raw["content"])
        return {
            "agent": agent_name,
            "cross_opinions": result.get("cross_opinions", []),
            "_usage": raw["usage"],
        }
    except Exception as e:
        return {
            "agent": agent_name,
            "cross_opinions": [],
            "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_error": str(e),
        }


def merge_cross_reviews(original_findings: list[dict],
                        cross_results: list[dict]) -> list[dict]:
    """根据交叉审查结果调整 findings。

    规则：
    - 2+ 人 disagree → 移除
    - 1 人 disagree + 1 人 refine → 降级（severity 降一档）
    - refine 最多 → 采纳第一个 refine 的 revised_severity
    """
    findings = original_findings[:]
    sev_levels = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    level_sevs = {4: "critical", 3: "high", 2: "medium", 1: "low"}

    for i in range(len(findings)):
        opinions_for_i = []
        for cr in cross_results:
            for op in cr.get("cross_opinions", []):
                if op.get("finding_index") == i:
                    opinions_for_i.append(op)

        if not opinions_for_i:
            continue

        disagree_count = sum(1 for o in opinions_for_i if o.get("opinion") == "disagree")
        refine_count = sum(1 for o in opinions_for_i if o.get("opinion") == "refine")

        if disagree_count >= 2:
            # 标记为争议项，不删除但降低严重等级
            cur_sev = sev_levels.get(findings[i].get("severity", "low"), 1)
            new_sev = level_sevs.get(max(cur_sev - 1, 1), "low")
            findings[i]["severity"] = new_sev
            findings[i]["_debate"] = f"交叉审查: {disagree_count} 人不认同，等级降为 {new_sev}"
        elif disagree_count == 1 and refine_count >= 1:
            # 有争议，微降
            cur_sev = sev_levels.get(findings[i].get("severity", "low"), 1)
            new_sev = level_sevs.get(max(cur_sev - 1, 1), "low")
            findings[i]["severity"] = new_sev
            findings[i]["_debate"] = "交叉审查: 存在争议，略降等级"
        elif refine_count > 0:
            # 采纳第一个 refine 建议
            for o in opinions_for_i:
                if o.get("opinion") == "refine" and o.get("revised_severity"):
                    findings[i]["severity"] = o["revised_severity"]
                    findings[i]["_debate"] = f"交叉审查: 等级调整为 {o['revised_severity']}"
                    break

    return findings
