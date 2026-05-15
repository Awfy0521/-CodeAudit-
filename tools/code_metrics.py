import json
import os
import subprocess
import tempfile


def _complexity_grade(cc: int) -> str:
    if cc <= 5: return "A"
    if cc <= 10: return "B"
    if cc <= 20: return "C"
    if cc <= 30: return "D"
    if cc <= 40: return "E"
    return "F"


def _run_radon_cc(filepath: str) -> list[dict]:
    """Run radon cc --json, return parsed list of function metrics."""
    try:
        result = subprocess.run(
            ["radon", "cc", "--json", filepath],
            capture_output=True, text=True, timeout=30,
        )
        raw = result.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        functions = []
        for file_path, blocks in data.items():
            for block in blocks:
                functions.append({
                    "name": block.get("name", ""),
                    "type": block.get("type", "function") if block.get("type") else "function",
                    "line": block.get("lineno", 0),
                    "end_line": block.get("endline", block.get("lineno", 0)),
                    "complexity": block.get("complexity", 0),
                    "grade": _complexity_grade(block.get("complexity", 0)),
                    "col_offset": block.get("col_offset", 0),
                })
        return functions
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return []


def _run_radon_mi(filepath: str) -> dict | None:
    """Run radon mi --json, return maintainability index."""
    try:
        result = subprocess.run(
            ["radon", "mi", "--json", filepath],
            capture_output=True, text=True, timeout=30,
        )
        raw = result.stdout.strip()
        if not raw:
            return None
        data = json.loads(raw)
        scores = [v.get("mi", 0) for v in data.values() if isinstance(v, dict)]
        if not scores:
            return None
        avg_mi = sum(scores) / len(scores)
        grade = "A" if avg_mi >= 80 else "B" if avg_mi >= 60 else "C" if avg_mi >= 40 else "D" if avg_mi >= 20 else "F"
        return {"mi_score": round(avg_mi, 1), "grade": grade, "per_file": scores}
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def _run_radon_raw(filepath: str) -> dict | None:
    """Run radon raw --json, return raw metrics (LOC, comments, multi, blank)."""
    try:
        result = subprocess.run(
            ["radon", "raw", "--json", filepath],
            capture_output=True, text=True, timeout=30,
        )
        raw = result.stdout.strip()
        if not raw:
            return None
        data = json.loads(raw)
        totals = {"loc": 0, "lloc": 0, "sloc": 0, "comments": 0, "multi": 0, "blank": 0, "single_comments": 0}
        for _, v in data.items():
            if isinstance(v, dict):
                for key in totals:
                    totals[key] += v.get(key, 0)
        return totals
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def run_code_metrics(code: str) -> dict:
    """Analyze code with radon, return structured metrics dict."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        functions = _run_radon_cc(tmp_path)
        mi_result = _run_radon_mi(tmp_path)
        raw_result = _run_radon_raw(tmp_path)

        # Build complexity summary
        grades = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
        for fn in functions:
            g = fn["grade"]
            if g in grades:
                grades[g] += 1

        # Build heat table: top functions by complexity
        sorted_fns = sorted(functions, key=lambda x: x["complexity"], reverse=True)
        heat_table = sorted_fns[:20]  # top 20

        return {
            "functions": functions,
            "heat_table": heat_table,
            "complexity_grades": grades,
            "maintainability": mi_result,
            "raw_metrics": raw_result,
            "summary": _build_metrics_summary(grades, mi_result, raw_result, len(functions)),
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _build_metrics_summary(grades: dict, mi: dict | None, raw: dict | None, fn_count: int) -> str:
    parts = []
    # Complexity distribution
    risky = grades.get("D", 0) + grades.get("E", 0) + grades.get("F", 0)
    if risky > 0:
        parts.append(f"{risky}/{fn_count} 个函数圈复杂度过高 (≥D 级)")
    else:
        parts.append(f"全部 {fn_count} 个函数圈复杂度在 C 级以内")
    # MI
    if mi:
        parts.append(f"可维护性指数 {mi['mi_score']} (评级 {mi['grade']})")
    # Raw
    if raw:
        parts.append(f"总行数 {raw['loc']}, 逻辑行 {raw['lloc']}, 注释率 {_comment_rate(raw):.0f}%")
    return " · ".join(parts) if parts else "代码度量完成"


def _comment_rate(raw: dict) -> float:
    loc = raw.get("loc", 1)
    comments = raw.get("comments", 0)
    return (comments / loc) * 100 if loc > 0 else 0


def metrics_to_text(metrics: dict) -> str:
    """Convert metrics dict to a concise text summary for LLM context."""
    if not metrics or not metrics.get("functions"):
        return "无法获取代码度量数据"
    lines = []
    lines.append(f"可维护性指数: {metrics.get('maintainability',{}).get('mi_score','?')} (评级 {metrics.get('maintainability',{}).get('grade','?')})")
    raw = metrics.get("raw_metrics", {})
    lines.append(f"总行数: {raw.get('loc','?')}, 逻辑行: {raw.get('lloc','?')}, 注释: {raw.get('comments','?')}")
    lines.append(f"函数总数: {len(metrics.get('functions',[]))}")
    lines.append(f"复杂度分布: {metrics.get('complexity_grades',{})}")
    heat = metrics.get("heat_table", [])[:10]
    if heat:
        lines.append("高复杂度函数 Top 10:")
        for fn in heat:
            lines.append(f"  {fn['name']}(L{fn['line']}) - CC={fn['complexity']} ({fn['grade']})")
    return "\n".join(lines)
