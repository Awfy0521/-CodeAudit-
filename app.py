import time
import difflib

import streamlit as st
import requests

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="智审 CodeAudit", page_icon="🔍", layout="wide")

# ── Session State Init ────────────────────────────────────────
for key in ["current_task_id", "task_result", "polling", "history_selected"]:
    if key not in st.session_state:
        st.session_state[key] = None


# ── Sidebar: History ──────────────────────────────────────────


def load_history():
    try:
        resp = requests.get(f"{API_BASE}/api/history", params={"limit": 50}, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return []


with st.sidebar:
    st.title("📋 审查历史")
    if st.button("🔄 刷新列表"):
        st.rerun()

    history = load_history()
    if not history:
        st.caption("暂无审查记录")

    for item in history:
        status_icon = {"pending": "⏳", "reviewing": "🔄", "completed": "✅", "failed": "❌"}
        icon = status_icon.get(item["status"], "❓")
        label = f"{icon} [{item['created_at'][:19]}] {item.get('target_path', '全仓库')}"
        if st.sidebar.button(label, key=f"hist_{item['id']}", use_container_width=True):
            st.session_state.history_selected = item["id"]
            st.session_state.current_task_id = item["id"]
            st.rerun()


# ── Main Area ─────────────────────────────────────────────────


def render_diff(original: str, fixed: str):
    """渲染代码 Diff 对比。"""
    if not fixed or fixed == original:
        st.info("修复代码与原始代码相同")
        return

    diff_html = difflib.HtmlDiff(wrapcolumn=80).make_table(
        original.splitlines(),
        fixed.splitlines(),
        fromdesc="原始代码",
        todesc="修复后代码",
        context=True,
        numlines=3,
    )
    st.components.v1.html(
        f"""
        <div style="font-size:13px; max-height:600px; overflow:auto;">
        <style>
            table.diff {{ font-family: monospace; width: 100%; }}
            .diff_header {{ background-color: #e0e0e0; }}
            .diff_next {{ background-color: #c0c0c0; }}
            .diff_add {{ background-color: #a8f0a8; }}
            .diff_chg {{ background-color: #ffff77; }}
            .diff_sub {{ background-color: #ffa0a0; }}
        </style>
        {diff_html}
        </div>
        """,
        height=620,
        scrolling=True,
    )


def render_findings_table(findings: list):
    """渲染 findings 表格。"""
    if not findings:
        st.success("✅ 未发现此类问题")
        return

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda x: severity_order.get(x.get("severity", "low"), 99))

    for f in sorted_findings:
        sev = f.get("severity", "low")
        sev_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        sev_icon = sev_color.get(sev, "⚪")
        with st.expander(f"{sev_icon} [{sev.upper()}] Line {f.get('line', '?')} — {f.get('category', '未分类')}"):
            st.markdown(f"**问题**: {f.get('description', '')}")
            st.markdown(f"**建议**: {f.get('suggestion', '')}")
            if f.get("found_by"):
                st.caption(f"发现者: {', '.join(f['found_by'])}")


def show_result():
    """展示审查结果。"""
    result = st.session_state.task_result
    if not result:
        return

    reports = {r["review_type"]: r for r in result.get("reports", [])}

    # Summary header
    merged = reports.get("merged", {})
    merged_findings = merged.get("findings") if merged.get("findings") else []
    sev_summary = merged.get("severity_summary") or {}

    st.subheader("📊 审查汇总")
    cols = st.columns(4)
    severity_count = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in (merged_findings or []):
        sev = f.get("severity", "low")
        severity_count[sev] = severity_count.get(sev, 0) + 1
    cols[0].metric("🔴 Critical", severity_count["critical"])
    cols[1].metric("🟠 High", severity_count["high"])
    cols[2].metric("🟡 Medium", severity_count["medium"])
    cols[3].metric("🟢 Low", severity_count["low"])

    summary_text = sev_summary.get("summary", "无汇总信息") if isinstance(sev_summary, dict) else str(sev_summary)
    fix_desc = sev_summary.get("fix_description", "") if isinstance(sev_summary, dict) else ""
    st.info(summary_text)
    if fix_desc:
        st.caption(f"修复说明: {fix_desc}")

    # Tabs
    tabs = st.tabs(["🔐 安全审查", "⚡ 性能审查", "🧠 业务逻辑", "📝 修复对比"])

    with tabs[0]:
        sec = reports.get("security", {})
        sec_findings = sec.get("findings") if sec.get("findings") else []
        render_findings_table(sec_findings)
        sec_summary = sec.get("severity_summary", {})
        if sec_summary and isinstance(sec_summary, dict):
            st.caption(sec_summary.get("summary", ""))

    with tabs[1]:
        perf = reports.get("performance", {})
        perf_findings = perf.get("findings") if perf.get("findings") else []
        render_findings_table(perf_findings)
        perf_summary = perf.get("severity_summary", {})
        if perf_summary and isinstance(perf_summary, dict):
            st.caption(perf_summary.get("summary", ""))

    with tabs[2]:
        biz = reports.get("business", {})
        biz_findings = biz.get("findings") if biz.get("findings") else []
        render_findings_table(biz_findings)
        biz_summary = biz.get("severity_summary", {})
        if biz_summary and isinstance(biz_summary, dict):
            st.caption(biz_summary.get("summary", ""))

    with tabs[3]:
        fixed_code = merged.get("fixed_code", "")
        render_diff(result.get("code", ""), fixed_code)

        if fixed_code:
            st.subheader("📋 修复后代码")
            st.code(fixed_code, language="python")
            st.download_button(
                "📥 下载修复代码",
                fixed_code,
                file_name="fixed_code.py",
                mime="text/plain",
            )


# ── Main Layout ────────────────────────────────────────────────

st.title("🔍 智审 CodeAudit")
st.caption("基于多智能体的全栈代码审查与修复机器人")

# Input area
col1, col2 = st.columns([3, 1])
with col1:
    code_input = st.text_area(
        "📝 粘贴待审查代码",
        height=300,
        placeholder="在此粘贴代码片段...",
        key="code_input",
    )
    uploaded_file = st.file_uploader("或上传代码文件", type=["py", "js", "ts", "java", "go", "cpp", "c", "rs"])

with col2:
    scope = st.radio("审查范围", ["full", "directory"], format_func=lambda x: "全仓库" if x == "full" else "指定目录")
    target_path = st.text_input("目标路径", value="", placeholder="src/ 或留空")

    submit_btn = st.button("🚀 开始审查", type="primary", use_container_width=True)

    if st.session_state.current_task_id:
        st.divider()
        st.caption(f"当前任务: {st.session_state.current_task_id[:8]}...")
        if st.button("清除结果"):
            st.session_state.current_task_id = None
            st.session_state.task_result = None
            st.rerun()

# Handle file upload
if uploaded_file is not None:
    code_input = uploaded_file.read().decode("utf-8", errors="replace")
    st.text_area("已加载文件", code_input, height=150, disabled=True)

# Submit review
if submit_btn:
    code = code_input.strip()
    if not code:
        st.error("请输入待审查代码")
    else:
        try:
            resp = requests.post(
                f"{API_BASE}/api/review",
                json={"code": code, "scope": scope, "target_path": target_path},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.current_task_id = data["task_id"]
                st.session_state.task_result = None
                st.success(f"审查任务已提交: {data['task_id']}")
                st.rerun()
            else:
                st.error(f"提交失败: {resp.text}")
        except requests.RequestException as e:
            st.error(f"无法连接后端 API: {e}")

# Polling
if st.session_state.current_task_id and not st.session_state.task_result:
    task_id = st.session_state.current_task_id
    placeholder = st.empty()

    with placeholder.container():
        st.info("🔍 正在审查中...")
        progress_bar = st.progress(30, text="等待审查完成...")
        status_text = st.empty()

    max_wait = 300  # 5 minutes timeout
    poll_interval = 3
    elapsed = 0

    while elapsed < max_wait:
        try:
            resp = requests.get(f"{API_BASE}/api/review/{task_id}", timeout=5)
            if resp.status_code == 200:
                result = resp.json()
                status = result.get("status", "pending")

                if status == "completed":
                    st.session_state.task_result = result
                    progress_bar.progress(100, text="审查完成")
                    status_text.success("✅ 审查完成")
                    time.sleep(0.5)
                    placeholder.empty()
                    st.rerun()
                elif status == "failed":
                    st.session_state.task_result = result
                    progress_bar.progress(100, text="审查失败")
                    status_text.error(f"❌ 审查失败: {result.get('error', '未知错误')}")
                    time.sleep(0.5)
                    placeholder.empty()
                    st.rerun()
                elif status == "reviewing":
                    progress_bar.progress(min(80, 30 + elapsed // 5), text="智能体正在并行审查...")
                    status_text.info("三个审查专家正在并行分析代码...")
            else:
                status_text.warning(f"查询状态失败: HTTP {resp.status_code}")
        except requests.RequestException:
            status_text.warning("等待后端响应...")

        time.sleep(poll_interval)
        elapsed += poll_interval

    # Timeout
    st.warning("审查超时，请检查后端日志或重试")

# Show result
if st.session_state.task_result:
    show_result()

# Load history item
if st.session_state.history_selected and not st.session_state.task_result:
    task_id = st.session_state.history_selected
    try:
        resp = requests.get(f"{API_BASE}/api/review/{task_id}", timeout=5)
        if resp.status_code == 200:
            st.session_state.task_result = resp.json()
            st.session_state.current_task_id = task_id
            st.session_state.history_selected = None
            st.rerun()
    except requests.RequestException:
        st.error("无法加载历史记录")
        st.session_state.history_selected = None
