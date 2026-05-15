import json
from datetime import datetime, timezone

from sqlalchemy import desc

from database.models import SessionLocal, ReviewTask, ReviewReport, init_db


def _utcnow():
    return datetime.now(timezone.utc)


def create_task(
    code: str,
    source: str = "local",
    scope: str = "full",
    target_path: str = "",
    repo_url: str = "",
) -> str:
    """创建审查任务，返回 task_id。"""
    task = ReviewTask(
        code=code,
        source=source,
        scope=scope,
        target_path=target_path,
        repo_url=repo_url,
        status="pending",
    )
    with SessionLocal() as session:
        session.add(task)
        session.commit()
        return task.id


def update_task_status(task_id: str, status: str):
    """更新任务状态。"""
    with SessionLocal() as session:
        task = session.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if task:
            task.status = status
            task.updated_at = _utcnow()
            session.commit()


def save_token_usage(task_id: str, usage: dict):
    """保存 Token 用量到任务记录。"""
    with SessionLocal() as session:
        task = session.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if task:
            task.token_usage = json.dumps(usage, ensure_ascii=False)
            session.commit()


def save_report(
    task_id: str,
    review_type: str,
    findings: dict | None = None,
    severity_summary: dict | None = None,
    fixed_code: str = "",
    diff: str = "",
):
    """保存审查报告。"""
    report = ReviewReport(
        task_id=task_id,
        review_type=review_type,
        findings=json.dumps(findings, ensure_ascii=False) if findings else None,
        severity_summary=json.dumps(severity_summary, ensure_ascii=False) if severity_summary else None,
        fixed_code=fixed_code,
        diff=diff,
    )
    with SessionLocal() as session:
        session.add(report)
        session.commit()


def get_task(task_id: str) -> dict | None:
    """获取任务详情（含所有报告）。"""
    with SessionLocal() as session:
        task = session.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if not task:
            return None
        return {
            "id": task.id,
            "code": task.code,
            "source": task.source,
            "scope": task.scope,
            "target_path": task.target_path,
            "repo_url": task.repo_url,
            "status": task.status,
            "token_usage": json.loads(task.token_usage) if task.token_usage else None,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "reports": [
                {
                    "id": r.id,
                    "review_type": r.review_type,
                    "findings": json.loads(r.findings) if r.findings else None,
                    "severity_summary": json.loads(r.severity_summary) if r.severity_summary else None,
                    "fixed_code": r.fixed_code,
                    "diff": r.diff,
                    "created_at": r.created_at.isoformat(),
                }
                for r in task.reports
            ],
        }


def get_history(limit: int = 20, offset: int = 0) -> list[dict]:
    """获取审查历史列表。"""
    with SessionLocal() as session:
        tasks = (
            session.query(ReviewTask)
            .order_by(desc(ReviewTask.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "id": t.id,
                "source": t.source,
                "scope": t.scope,
                "target_path": t.target_path,
                "repo_url": t.repo_url,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
                "code_preview": t.code[:200] + "..." if len(t.code) > 200 else t.code,
            }
            for t in tasks
        ]


def delete_task(task_id: str) -> bool:
    """删除任务及关联报告。"""
    with SessionLocal() as session:
        task = session.query(ReviewTask).filter(ReviewTask.id == task_id).first()
        if not task:
            return False
        session.delete(task)
        session.commit()
        return True
