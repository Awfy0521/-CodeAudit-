"""反馈数据 CRUD：FindingFeedback + ReviewTask 评分。"""

import json
import hashlib
import uuid
from datetime import datetime

from database.models import SessionLocal, ReviewTask
from database.models import Base, engine
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship


class FindingFeedback(Base):
    __tablename__ = "finding_feedback"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_index = Column(Integer, nullable=False)
    finding_hash = Column(String(64), nullable=False, index=True)
    verdict = Column(String(16), nullable=False)          # agree / disagree
    note = Column(Text, nullable=True)
    agent_name = Column(String(32), nullable=True)
    severity = Column(String(16), nullable=True)
    category = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("ReviewTask", backref="feedback_entries")


def _ensure_tables():
    """自动建表（如果不存在）。"""
    Base.metadata.create_all(bind=engine)
    # 确保 review_tasks 新增字段
    with engine.connect() as conn:
        for col, col_type in [("rating", "INTEGER"), ("review_note", "TEXT")]:
            try:
                conn.exec_driver_sql(
                    f"ALTER TABLE review_tasks ADD COLUMN {col} {col_type}"
                )
            except Exception:
                pass  # 列已存在
        conn.commit()


_ensure_tables()


def save_feedback(
    task_id: str,
    finding: dict,
    finding_index: int,
    verdict: str,
    agent_name: str = "",
    note: str = "",
) -> str:
    """保存单条 finding 反馈，返回 feedback_id。"""
    finding_json = json.dumps(finding, sort_keys=True, ensure_ascii=False)
    finding_hash = hashlib.sha256(finding_json.encode()).hexdigest()

    feedback = FindingFeedback(
        task_id=task_id,
        finding_index=finding_index,
        finding_hash=finding_hash,
        verdict=verdict,
        note=note,
        agent_name=agent_name,
        severity=finding.get("severity", ""),
        category=finding.get("category", ""),
    )
    with SessionLocal() as session:
        session.add(feedback)
        session.commit()
        return feedback.id


def save_rating(task_id: str, rating: int, review_note: str = "") -> bool:
    """保存整体评分。"""
    with SessionLocal() as session:
        task = session.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if not task:
            return False
        task.rating = rating
        task.review_note = review_note
        session.commit()
        return True


def get_task_feedback_stats(task_id: str) -> dict:
    """查询某任务的所有反馈统计。"""
    with SessionLocal() as session:
        task = session.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        entries = session.query(FindingFeedback).filter(
            FindingFeedback.task_id == task_id
        ).all()
        agrees = sum(1 for e in entries if e.verdict == "agree")
        disagrees = sum(1 for e in entries if e.verdict == "disagree")
        return {
            "task_id": task_id,
            "rating": task.rating if task else None,
            "review_note": task.review_note if task else None,
            "total_feedback": len(entries),
            "agrees": agrees,
            "disagrees": disagrees,
        }


def get_disagree_samples(limit: int = 100) -> list[dict]:
    """获取所有点踩的 finding（用于 RAG 索引和分析）。"""
    with SessionLocal() as session:
        entries = (
            session.query(FindingFeedback)
            .filter(FindingFeedback.verdict == "disagree")
            .order_by(FindingFeedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_feedback_to_dict(e) for e in entries]


def get_feedback_by_category(category: str, limit: int = 20) -> list[dict]:
    """按类别获取点踩的 finding。"""
    with SessionLocal() as session:
        entries = (
            session.query(FindingFeedback)
            .filter(
                FindingFeedback.verdict == "disagree",
                FindingFeedback.category == category,
            )
            .order_by(FindingFeedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_feedback_to_dict(e) for e in entries]


def get_agent_feedback_stats(days: int = 7) -> list[dict]:
    """统计各 Agent 在最近 N 天的反馈数据。"""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as session:
        entries = (
            session.query(FindingFeedback)
            .filter(FindingFeedback.created_at >= cutoff)
            .all()
        )
        stats: dict[str, dict] = {}
        for e in entries:
            agent = e.agent_name or "unknown"
            if agent not in stats:
                stats[agent] = {"agent": agent, "agree": 0, "disagree": 0}
            if e.verdict == "agree":
                stats[agent]["agree"] += 1
            else:
                stats[agent]["disagree"] += 1
        return list(stats.values())


def _feedback_to_dict(e: FindingFeedback) -> dict:
    return {
        "id": e.id,
        "task_id": e.task_id,
        "finding_index": e.finding_index,
        "finding_hash": e.finding_hash,
        "verdict": e.verdict,
        "note": e.note,
        "agent_name": e.agent_name,
        "severity": e.severity,
        "category": e.category,
        "created_at": e.created_at.isoformat() if e.created_at else "",
    }
