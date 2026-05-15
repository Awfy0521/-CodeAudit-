"""反馈相关 FastAPI 端点。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .storage import save_feedback, save_rating, get_task_feedback_stats
from .analyzer import run_weekly_analysis, get_latest_analysis

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FindingFeedbackRequest(BaseModel):
    finding_index: int
    verdict: str = Field(pattern="^(agree|disagree)$")
    agent_name: str = ""
    note: str = ""
    finding: dict = Field(default_factory=dict)


class RatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    review_note: str = ""


@router.post("/{task_id}")
def submit_finding_feedback(task_id: str, req: FindingFeedbackRequest):
    """提交单条 finding 反馈（点赞/点踩）。"""
    try:
        fid = save_feedback(
            task_id=task_id,
            finding=req.finding,
            finding_index=req.finding_index,
            verdict=req.verdict,
            agent_name=req.agent_name,
            note=req.note,
        )
        return {"feedback_id": fid, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{task_id}/rating")
def submit_rating(task_id: str, req: RatingRequest):
    """提交整体评分。"""
    ok = save_rating(task_id, req.rating, req.review_note)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"status": "ok"}


@router.get("/{task_id}/stats")
def get_feedback_stats(task_id: str):
    """查询某任务的反馈统计。"""
    stats = get_task_feedback_stats(task_id)
    if stats["total_feedback"] == 0 and stats["rating"] is None:
        return {"task_id": task_id, "message": "暂无反馈数据"}
    return stats


@router.get("/analysis/latest")
def latest_analysis():
    """获取最新误报分析报告。"""
    report = get_latest_analysis()
    if not report:
        return {"message": "暂无分析报告，请通过 POST /api/feedback/analysis/run 手动触发"}
    return report


@router.post("/analysis/run")
def trigger_analysis():
    """手动触发误报分析。"""
    try:
        report = run_weekly_analysis()
        return {"status": "ok", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
