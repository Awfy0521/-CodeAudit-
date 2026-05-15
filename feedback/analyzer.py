"""误报统计分析 + 周报生成。"""

import json
import uuid
from datetime import datetime
from collections import Counter

from database.models import SessionLocal
from database.models import Base, engine
from sqlalchemy import Column, String, Text, DateTime

from .storage import get_agent_feedback_stats
from .retriever import get_all_negative_patterns


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_type = Column(String(32), default="weekly")
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def _ensure_table():
    Base.metadata.create_all(bind=engine)


_ensure_table()


def run_weekly_analysis() -> dict:
    """执行每周分析，生成结构化报告并持久化。

    返回报告内容 dict。
    """
    agent_stats = get_agent_feedback_stats(days=7)
    patterns = get_all_negative_patterns()

    # 各 Agent 误报率
    agent_summary = []
    for stat in agent_stats:
        total = stat["agree"] + stat["disagree"]
        rate = round(stat["disagree"] / total * 100, 1) if total > 0 else 0
        agent_summary.append({
            "agent": stat["agent"],
            "agree": stat["agree"],
            "disagree": stat["disagree"],
            "total": total,
            "disagree_rate": rate,
        })

    # 高频误报模式（同 category 被 disagree >= 3 次）
    category_counter = Counter(p.get("category") for p in patterns if p.get("category"))
    hot_categories = [
        {"category": cat, "count": count}
        for cat, count in category_counter.most_common(10)
        if count >= 3
    ]

    # 常被误报的 Agent
    agent_counter = Counter(p.get("agent_name") for p in patterns if p.get("agent_name"))
    hot_agents = [
        {"agent": agent, "count": count}
        for agent, count in agent_counter.most_common(5)
    ]

    # 生成建议
    suggestions = []
    if hot_categories:
        cats = ", ".join(c["category"] for c in hot_categories[:3])
        suggestions.append(f"高频误报类别: {cats}，建议检查对应 Agent 的 Prompt 描述是否需要调整边界")
    for stat in agent_summary:
        if stat["disagree_rate"] > 30 and stat["total"] >= 5:
            suggestions.append(
                f"Agent [{stat['agent']}] 误报率 {stat['disagree_rate']}%（{stat['total']} 条反馈），建议重点审查其 Prompt"
            )

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "period_days": 7,
        "agent_summary": agent_summary,
        "hot_categories": hot_categories,
        "hot_agents": hot_agents,
        "suggestions": suggestions,
    }

    # 持久化
    with SessionLocal() as session:
        analysis = AnalysisReport(
            report_type="weekly",
            content=json.dumps(report, ensure_ascii=False),
        )
        session.add(analysis)
        session.commit()

    return report


def get_latest_analysis() -> dict | None:
    """获取最近一次分析报告。"""
    with SessionLocal() as session:
        report = (
            session.query(AnalysisReport)
            .filter(AnalysisReport.report_type == "weekly")
            .order_by(AnalysisReport.created_at.desc())
            .first()
        )
        if report:
            try:
                return json.loads(report.content)
            except json.JSONDecodeError:
                return None
        return None
