import os
import shutil
import subprocess
import tempfile
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from database.models import init_db
from database.crud import (
    create_task,
    update_task_status,
    get_task,
    get_history,
    delete_task,
    save_report,
    save_token_usage,
)
from agents.graph import review_graph
from security_fence import scan, desensitize_report, desensitize_report_str

# ── Constants ─────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".vue", ".svelte", ".sql", ".sh", ".yaml", ".yml",
    ".toml", ".json", ".xml", ".html", ".css", ".scss",
}
MAX_TOTAL_SIZE = 200_000  # ~200KB max for review

# ── Lifespan ──────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="CodeAudit API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static SPA frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")


@app.get("/")
async def root():
    """Serve the SPA entry page."""
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": "CodeAudit API is running"}


# ── Schemas ───────────────────────────────


class ReviewRequest(BaseModel):
    source: str = Field(default="local", pattern="^(local|github_full|github_path)$")
    code: str = Field(default="", description="直接粘贴的代码（source=local 时使用）")
    repo_url: str = Field(default="", description="GitHub 仓库 URL（source=github_* 时使用）")
    target_path: str = Field(default="", description="仓库内子路径 或 本地文件/目录路径")
    file_path: str = Field(default="", description="本地文件或目录的绝对路径（source=local 时可选）")


class ReviewResponse(BaseModel):
    task_id: str
    status: str
    resolved_info: dict = Field(default_factory=dict)


# ── Code Resolution ───────────────────────


def _is_code_file(filepath: str) -> bool:
    ext = os.path.splitext(filepath)[1].lower()
    return ext in CODE_EXTENSIONS


def _read_file_content(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _collect_files(root: str, relative_prefix: str = "") -> list[tuple[str, str]]:
    """递归收集目录下所有代码文件，返回 [(相对路径, 绝对路径), ...]"""
    files = []
    for dirpath, _, filenames in os.walk(root):
        # 跳过隐藏目录和常见非代码目录
        if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv", ".venv", "dist", "build", ".git")
               for part in Path(dirpath).relative_to(root).parts):
            continue
        for fname in filenames:
            abspath = os.path.join(dirpath, fname)
            if _is_code_file(abspath):
                rel = os.path.relpath(abspath, root)
                if relative_prefix:
                    rel = os.path.join(relative_prefix, rel)
                files.append((rel, abspath))
    return sorted(files, key=lambda x: x[0])


def _build_concatenated_code(files: list[tuple[str, str]], max_size: int = MAX_TOTAL_SIZE) -> str:
    """将多个文件拼接为一个代码字符串，带文件头标识。"""
    parts = []
    total = 0
    for rel_path, abs_path in files:
        content = _read_file_content(abs_path)
        if not content.strip():
            continue
        header = f"\n# ======== {rel_path} ========\n"
        chunk = header + content + "\n"
        if total + len(chunk) > max_size:
            parts.append(f"\n# ... (剩余文件已截断，共 {len(files)} 个文件) ...\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)


def resolve_local_files(file_path: str) -> str:
    """读取本地文件或目录，返回拼接后的代码字符串。"""
    path = os.path.abspath(file_path)
    if not os.path.exists(path):
        raise ValueError(f"路径不存在: {file_path}")

    if os.path.isfile(path):
        content = _read_file_content(path)
        return f"# ======== {os.path.basename(path)} ========\n{content}"

    # 目录
    files = _collect_files(path)
    if not files:
        raise ValueError(f"目录中未找到支持的代码文件: {file_path}")
    return _build_concatenated_code(files)


def resolve_github_repo(repo_url: str, target_path: str = "") -> str:
    """克隆 GitHub 仓库，读取代码文件，返回拼接后的代码字符串。"""
    tmpdir = tempfile.mkdtemp(prefix="codeaudit_repo_")
    try:
        # 浅克隆
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, tmpdir],
            capture_output=True, text=True, timeout=120, check=True,
        )
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError(f"仓库克隆失败: {e.stderr}")
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError("仓库克隆超时（超过120秒）")
    except FileNotFoundError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError("系统未安装 git，无法克隆仓库")

    try:
        # 查找仓库根目录下的实际目录名（git clone 会创建子目录）
        entries = os.listdir(tmpdir)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmpdir, entries[0])):
            repo_root = os.path.join(tmpdir, entries[0])
        else:
            repo_root = tmpdir

        if target_path:
            scan_root = os.path.join(repo_root, target_path)
            if not os.path.exists(scan_root):
                raise ValueError(f"仓库中路径不存在: {target_path}")
        else:
            scan_root = repo_root

        if os.path.isfile(scan_root):
            content = _read_file_content(scan_root)
            return f"# ======== {target_path or os.path.basename(scan_root)} ========\n{content}"

        files = _collect_files(scan_root, relative_prefix=target_path if target_path else "")
        if not files:
            raise ValueError("仓库中未找到支持的代码文件")
        return _build_concatenated_code(files)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def resolve_code(req: ReviewRequest) -> str:
    """根据请求解析出待审查的代码字符串。"""
    if req.source == "local":
        if req.file_path:
            return resolve_local_files(req.file_path)
        if req.code.strip():
            return req.code
        raise ValueError("请提供代码内容或本地文件路径")

    if req.source in ("github_full", "github_path"):
        if not req.repo_url.strip():
            raise ValueError("GitHub 模式需要提供仓库 URL")
        if req.source == "github_path" and not req.target_path.strip():
            raise ValueError("指定路径模式需要提供仓库内路径")
        return resolve_github_repo(
            req.repo_url.strip(),
            target_path=req.target_path if req.source == "github_path" else "",
        )

    raise ValueError(f"未知的 source 类型: {req.source}")


# ── Background task ───────────────────────


def run_review(task_id: str, code: str, source: str, scope: str, target_path: str):
    """后台执行审查流程。"""
    try:
        update_task_status(task_id, "reviewing")
        # 安全围栏：脱敏后发送给 LLM，映射表仅保留在内存中
        safe_code, secret_map = scan(code)
        if secret_map:
            print(f"[SecurityFence] 检测到 {len(secret_map)} 处敏感信息，已替换占位符")
        initial_state = {
            "code": safe_code,
            "scope": scope,
            "target_path": target_path,
            "security_review": {},
            "performance_review": {},
            "business_logic_review": {},
            "architecture_review": {},
            "code_metrics": {},
            "merged_review": {},
            "fixed_code": "",
            "diff": "",
            "token_usage": {},
            "error": "",
            "status": "reviewing",
            "task_id": task_id,
        }
        result = review_graph.invoke(initial_state)

        # Save token usage
        token_usage = result.get("token_usage", {})
        if token_usage:
            save_token_usage(task_id, token_usage)

        for review_type, key in [
            ("security", "security_review"),
            ("performance", "performance_review"),
            ("business", "business_logic_review"),
            ("architecture", "architecture_review"),
        ]:
            review_data = result.get(key, {})
            if review_data:
                review_data = desensitize_report(review_data, secret_map)
                save_report(
                    task_id=task_id,
                    review_type=review_type,
                    findings=review_data.get("findings"),
                    severity_summary={"summary": review_data.get("summary", "")},
                )

        # Save code metrics separately
        metrics = result.get("code_metrics", {})
        if metrics:
            save_report(
                task_id=task_id,
                review_type="metrics",
                findings=list(metrics.get("functions", [])),
                severity_summary={
                    "summary": metrics.get("summary", ""),
                    "maintainability": metrics.get("maintainability"),
                    "complexity_grades": metrics.get("complexity_grades", {}),
                    "raw_metrics": metrics.get("raw_metrics"),
                    "heat_table": metrics.get("heat_table", []),
                },
            )

        merged = result.get("merged_review", {})
        if merged:
            merged = desensitize_report(merged, secret_map)
            saved_fixed_code = desensitize_report_str(result.get("fixed_code", ""), secret_map)
            save_report(
                task_id=task_id,
                review_type="merged",
                findings=merged.get("findings"),
                severity_summary={
                    "summary": merged.get("summary", ""),
                    "fix_description": merged.get("fix_description", ""),
                },
                fixed_code=saved_fixed_code,
                diff=result.get("diff", ""),
            )

        update_task_status(task_id, result.get("status", "completed"))
    except Exception:
        update_task_status(task_id, "failed")
        save_report(
            task_id=task_id,
            review_type="merged",
            findings=[],
            severity_summary={"summary": f"审查流程异常: {traceback.format_exc()}"},
        )


# ── Endpoints ─────────────────────────────


@app.post("/api/review", response_model=ReviewResponse)
def submit_review(req: ReviewRequest, bg: BackgroundTasks):
    """提交代码审查任务。三种模式：
    - local: 粘贴代码 或 上传文件 或 本地路径
    - github_full: GitHub 仓库 URL，全仓库审查
    - github_path: GitHub 仓库 URL + 仓库内路径
    """
    try:
        code = resolve_code(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_id = create_task(
        code=code,
        source=req.source,
        scope="directory" if req.source == "github_path" else "full",
        target_path=req.target_path or req.file_path,
        repo_url=req.repo_url,
    )
    scope = "directory" if req.source == "github_path" else "full"
    bg.add_task(run_review, task_id, code, req.source, scope, req.target_path)
    return ReviewResponse(
        task_id=task_id,
        status="pending",
        resolved_info={
            "source": req.source,
            "code_size": len(code),
            "lines": code.count("\n") + 1,
        },
    )


@app.get("/api/review/{task_id}")
def query_review(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/history")
def list_history(limit: int = 20, offset: int = 0):
    return get_history(limit=limit, offset=offset)


@app.delete("/api/review/{task_id}")
def remove_review(task_id: str):
    if not delete_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"message": "已删除"}


@app.get("/api/review/{task_id}/export")
def export_report(task_id: str, format: str = Query("md", pattern="^(md|json)$")):
    """导出审查报告为 Markdown 或 JSON 格式，返回可下载文件。"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if format == "json":
        import json
        content = json.dumps(task, ensure_ascii=False, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=codeaudit_{task_id[:8]}.json"},
        )

    # Build Markdown report
    source_labels = {"github_full": "GitHub 全仓库", "github_path": "GitHub + 路径", "local": "本地代码"}
    code_lines = (task.get("code") or "").split("\n")
    reports = {}
    for r in task.get("reports") or []:
        reports[r["review_type"]] = r

    merged = reports.get("merged", {})
    findings = merged.get("findings") or []
    if isinstance(findings, str):
        import json
        try:
            findings = json.loads(findings)
        except json.JSONDecodeError:
            findings = []

    sev_labels = {"critical": "严重", "high": "高危", "medium": "中等", "low": "轻微"}
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.get("severity", "low")] = counts.get(f.get("severity", "low"), 0) + 1

    summary = merged.get("severity_summary") or {}
    if isinstance(summary, str):
        import json
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            summary = {}

    token_usage = task.get("token_usage") or {}

    md = f"""# 智审 CodeAudit — 审查报告

## 基本信息

| 项目 | 内容 |
|------|------|
| **任务 ID** | `{task_id}` |
| **审查模式** | {source_labels.get(task.get("source", ""), task.get("source", "本地"))} |
| **目标路径** | {task.get("target_path") or task.get("repo_url") or "直接输入"} |
| **代码规模** | {len(code_lines)} 行 · {len(task.get("code") or "")} 字符 |
| **审查时间** | {task.get("created_at", "")} |
| **状态** | {task.get("status", "")} |

## Token 用量

| 指标 | 数量 |
|------|------|
| **Prompt Tokens** | {token_usage.get("prompt_tokens", 0):,} |
| **Completion Tokens** | {token_usage.get("completion_tokens", 0):,} |
| **总计** | {token_usage.get("total_tokens", 0):,} |

## 审查裁定

{summary.get("summary", "无")}

{summary.get("fix_description", "") and f"**修复说明**: {summary['fix_description']}"}

## 问题汇总

| 严重等级 | 数量 |
|----------|------|
| 🔴 Critical | {counts["critical"]} |
| 🟠 High | {counts["high"]} |
| 🟡 Medium | {counts["medium"]} |
| 🟢 Low | {counts["low"]} |
| **合计** | **{sum(counts.values())}** |

"""
    # Append each finding
    for i, f in enumerate(findings, 1):
        sev = f.get("severity", "low")
        sev_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
        md += f"""### {i}. {sev_emoji} [{sev_labels.get(sev, sev)}] {f.get("category", "未分类")}

- **行号**: L{f.get("line", "?")}
- **描述**: {f.get("description", "")}
- **建议**: {f.get("suggestion", "")}
"""
        if f.get("code_snippet"):
            md += f"""
```python
{f['code_snippet']}
```

"""
        found_by = f.get("found_by", [])
        if found_by:
            by_labels = {"security": "安全专家", "performance": "性能优化师", "business_logic": "业务逻辑审核", "architecture": "架构审查师"}
            by_names = [by_labels.get(x, x) for x in found_by]
            md += f"**发现者**: {', '.join(by_names)}\n\n"

    # Fix code section
    fixed_code = merged.get("fixed_code") or ""
    if fixed_code:
        md += f"""## 修复后代码

```python
{fixed_code}
```

"""

    # Diff section
    diff = merged.get("diff") or ""
    if diff:
        md += f"""## Diff 对比

```diff
{diff}
```

"""

    md += f"""---
*由智审 CodeAudit 多智能体审查系统生成 · {task_id[:8]}*"""

    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=codeaudit_{task_id[:8]}.md"},
    )


@app.get("/api/trends")
def get_trends():
    """获取审查趋势数据，用于可视化看板。"""
    import json
    from database.models import SessionLocal, ReviewTask, ReviewReport
    from sqlalchemy import func

    with SessionLocal() as session:
        total_tasks = session.query(func.count(ReviewTask.id)).scalar() or 0
        completed = session.query(func.count(ReviewTask.id)).filter(ReviewTask.status == "completed").scalar() or 0
        failed = session.query(func.count(ReviewTask.id)).filter(ReviewTask.status == "failed").scalar() or 0

        # Reviews by source type
        source_counts = {}
        for row in session.query(ReviewTask.source, func.count(ReviewTask.id)).group_by(ReviewTask.source).all():
            source_counts[row[0]] = row[1]

        # Recent 30 tasks timeline
        recent_tasks = (
            session.query(ReviewTask)
            .order_by(ReviewTask.created_at.desc())
            .limit(30)
            .all()
        )
        timeline = []
        for t in reversed(recent_tasks):
            reports = session.query(ReviewReport).filter(ReviewReport.task_id == t.id).all()
            merged_report = next((r for r in reports if r.review_type == "merged"), None)
            findings_count = 0
            if merged_report and merged_report.findings:
                try:
                    f = json.loads(merged_report.findings)
                    findings_count = len(f) if isinstance(f, list) else 0
                except (json.JSONDecodeError, TypeError):
                    pass
            timeline.append({
                "id": t.id,
                "date": t.created_at.isoformat() if t.created_at else "",
                "status": t.status,
                "source": t.source,
                "findings_count": findings_count,
            })

        # Token usage aggregate
        total_prompt = 0
        total_completion = 0
        total_tokens = 0
        tasks_with_usage = 0
        for t in session.query(ReviewTask).filter(ReviewTask.token_usage.isnot(None)).all():
            try:
                u = json.loads(t.token_usage)
                total_prompt += u.get("prompt_tokens", 0)
                total_completion += u.get("completion_tokens", 0)
                total_tokens += u.get("total_tokens", 0)
                tasks_with_usage += 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Average findings per completed review
        avg_findings = 0
        if completed > 0:
            total_findings = 0
            for t in session.query(ReviewTask).filter(ReviewTask.status == "completed").all():
                merged = session.query(ReviewReport).filter(
                    ReviewReport.task_id == t.id,
                    ReviewReport.review_type == "merged"
                ).first()
                if merged and merged.findings:
                    try:
                        f = json.loads(merged.findings)
                        if isinstance(f, list):
                            total_findings += len(f)
                    except (json.JSONDecodeError, TypeError):
                        pass
            avg_findings = round(total_findings / completed, 1)

        return {
            "summary": {
                "total_tasks": total_tasks,
                "completed": completed,
                "failed": failed,
                "by_source": source_counts,
                "avg_findings": avg_findings,
            },
            "token_usage": {
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "tasks_tracked": tasks_with_usage,
            },
            "timeline": timeline,
        }


def start():
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)


def dev():
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    dev()
