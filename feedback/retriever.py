"""负样本检索：将点踩 finding 索引到 RAG，生成 Prompt 上下文。"""

import json
from collections import Counter

from .storage import get_disagree_samples


def build_negative_context(category: str, keywords: list[str]) -> str:
    """为给定向量的审查场景检索历史负样本，生成 Prompt 避坑提示。

    Args:
        category: 当前 finding 的类别
        keywords: 当前代码/问题的关键词

    Returns:
        格式化的上下文文本，无法匹配时返回 ""
    """
    samples = get_disagree_samples(limit=100)
    if not samples:
        return ""

    # 按 category 匹配 + 关键词相似度计分
    scored = []
    for s in samples:
        score = 0
        if s.get("category") == category:
            score += 3
        note = (s.get("note") or "").lower()
        for kw in keywords:
            if kw.lower() in note:
                score += 2
        if score >= 2:
            scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:3]

    if not top:
        return ""

    lines = ["## 历史反馈提醒"]
    lines.append("以下类似场景在过去被用户标记为误报，请谨慎判断，避免重复误报：\n")
    for i, (score, s) in enumerate(top, 1):
        note = s.get("note") or "（无备注）"
        lines.append(
            f"- [误报] 类别: {s.get('category', '-')} "
            f"| 严重等级: {s.get('severity', '-')} "
            f"| 用户备注: {note}"
        )
    return "\n".join(lines)


def get_all_negative_patterns() -> list[dict]:
    """获取所有负样本的聚类模式（供 analyzer 使用）。"""
    samples = get_disagree_samples(limit=200)
    patterns = []
    for s in samples:
        patterns.append({
            "category": s.get("category", ""),
            "severity": s.get("severity", ""),
            "agent_name": s.get("agent_name", ""),
            "note": s.get("note", ""),
        })
    return patterns
