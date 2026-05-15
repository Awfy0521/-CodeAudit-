# 智审 CodeAudit 第三阶段 — 依赖安全检查 + 人工反馈回路

**日期**: 2026-05-15 | **状态**: 已确认

## 概述

本阶段实现两个独立功能模块：依赖安全检查（自动查询 CVE 漏洞）和人工反馈回路（用户反馈收集 → 知识库优化 → Prompt 演进）。

---

## 模块一：依赖安全检查 (Dependency Checker)

### 目的

审查时自动解析 Python 依赖文件，通过 OSV.dev API 查询已知 CVE 漏洞，结果注入审查报告的安全章节。

### 解析器

| 解析器 | 文件匹配 | 提取内容 |
|--------|----------|----------|
| `RequirementsParser` | `requirements*.txt` | 包名、版本、约束符（`==` / `>=` / `~=`） |
| `PyprojectParser` | `pyproject.toml` | `[project.dependencies]` + `[project.optional-dependencies]` |
| `PipfileParser` | `Pipfile` | `[packages]` + `[dev-packages]` |

统一输出接口 `parse(content: str, filename: str) -> list[PackageInfo]`：

```python
@dataclass
class PackageInfo:
    name: str          # 包名（PEP 508 规范化）
    version: str       # 版本号（去除约束符），无版本则为 "*"
    specifier: str     # 原始约束符
    ecosystem: str     # "PyPI"
    line: int          # 源文件行号
```

- 版本号无法解析时标记为 `"*"`，查询结果取该包所有已知漏洞（用户自行判断影响范围）
- `requirements.txt` 支持 `-r` 引用递归解析，深度上限 3 层

### OSV 查询

**API**: `POST https://api.osv.dev/v1/query`

**请求示例**:
```json
{
  "package": {"name": "django", "ecosystem": "PyPI"},
  "version": "4.2.0"
}
```

**返回**: 空 `{}` 表示无已知漏洞，否则返回 `{vulns: [{id, summary, severity, aliases, references, affected}]}`。

**缓存策略**:
- 内存 LRU 缓存（`functools.lru_cache(maxsize=512)`）
- 同一 `(name, version)` 组合 24 小时内不重复查询
- 请求间隔 200ms，避免 OSV rate limit

**降级**:
- OSV API 超时（5s）→ 记录日志，返回空结果，不阻塞审查流程
- 网络不可达 → 跳过依赖检查，在报告中标注 "依赖检查不可用"

### 集成方式

**触发时机**: 审查开始阶段（`start_node`），自动检测代码中是否包含依赖文件名。

**检测逻辑**: 在原始代码（脱敏后）中搜索文件名匹配：
- `requirements*.txt` — 可能在 GitHub 目录扫描时出现
- `pyproject.toml` — 项目根目录常见
- `Pipfile` — Pipenv 项目

**结果格式** (`dependency_warnings`):

```python
[{
    "package_name": "django",
    "version": "4.2.0",
    "file": "requirements.txt",
    "line": 5,
    "vulnerabilities": [{
        "id": "GHSA-xxxx-xxxx-xxxx",
        "summary": "SQL injection via .explain()",
        "severity": "HIGH",
        "aliases": ["CVE-2024-xxxxx"],
        "references": ["https://github.com/advisories/..."],
        "affected_versions": ">=4.0.0,<4.2.14",
        "fixed_in": "4.2.14"
    }]
}]
```

**注入审查**:
- 结果以独立 `dependency_warnings` 字段传入 Orchestrator
- Orchestrator 在 security findings 中引用相关依赖漏洞，作为"依赖安全"类别
- 如果存在已知漏洞，Orchestrator 在 `fix_description` 中建议升级版本

### 组件

| 文件 | 职责 |
|------|------|
| `dependency_checker/__init__.py` | 模块入口，暴露 `check_dependencies()` |
| `dependency_checker/parsers.py` | 3 种解析器 + `PackageInfo` |
| `dependency_checker/osv_client.py` | OSV API 封装 + LRU 缓存 + 重试 |

---

## 模块二：人工反馈回路 (Feedback Loop)

### 目的

收集用户对审查结果的反馈（finding 级别 + 整体级别），存入知识库用于后续审查的上下文增强，定期分析误报模式辅助 Prompt 优化。

### 数据收集

**Finding 级别**（每个 finding 卡片右下角）:
- 按钮：👍 认同 / 👎 误报
- 点击 👎 后弹出可选文本框，用户输入误报原因（如"项目已使用参数化查询"）
- 前端调用 `POST /api/feedback/{task_id}`

**整体级别**（审查结果页底部）:
- 星级评分 1-5 星 + 可选文字反馈
- 前端调用 `PUT /api/feedback/{task_id}/rating`

### 数据模型

**FindingFeedback 表**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| task_id | FK → ReviewTask | 关联审查任务 |
| finding_index | int | finding 在列表中的序号 |
| finding_hash | str(64) | finding 内容 SHA256（用于跨任务匹配） |
| verdict | str(16) | agree / disagree |
| note | text | 用户备注（可选） |
| agent_name | str(32) | 发现者 agent |
| severity | str(16) | 原 finding 严重等级 |
| category | str(64) | 原 finding 类别 |
| created_at | datetime | 时间戳 |

**ReviewTask 新增字段**:
```sql
ALTER TABLE review_tasks ADD COLUMN rating INTEGER;        -- 1-5 星
ALTER TABLE review_tasks ADD COLUMN review_note TEXT;       -- 文字反馈
```

### 负样本检索（feedback/retriever.py）

**职责**: 反馈数据 → RAG 可检索上下文

**流程**:
```
用户点击 👎 → 写入 FindingFeedback
                   ↓
         feedback/retriever.py 索引到 Milvus collection "feedback_negative"
                   ↓
         后续审查时，每个 worker 在调用 LLM 前搜索该 collection
                   ↓
         匹配到相似场景 → 注入 Prompt: "历史上类似代码曾被标记为误报（原因: xxx）"
```

**匹配策略**:
- 按 `category` 精确匹配 + 代码片段关键词相似度
- 相似度阈值: 匹配 2+ 个关键词 + 相同 category → 置信度高
- top-3 匹配结果注入上下文

**Prompt 注入格式**:
```
# 历史反馈提醒
以下类似场景在过去的审查中被用户标记为误报，请注意避免：
- [误报] 类别: SQL注入 (原因: 已使用 ORM 参数化查询)
- [误报] 类别: 硬编码密钥 (原因: 仅为示例占位符)
```

### 定时任务（APScheduler）

**调度**: 每周日凌晨 3:00（UTC+8），自动执行分析

**执行内容**:
1. 统计各 Agent 本周误报率 = disagree / (agree + disagree)
2. 识别高频误报模式（同一 category + 相似代码片段的 disagree >= 3 次）
3. 生成结构化分析报告，写入数据库 `analysis_reports` 表
4. 报告中列出"建议关注"的 Prompt 改进点

**任务定义** (`feedback/analyzer.py`):
```python
def run_weekly_analysis():
    # 1. 计算误报率
    # 2. 聚类高频误报
    # 3. 生成报告
    # 4. 持久化
```

**APScheduler 集成**: 在 `main.py` lifespan 中启动 `BackgroundScheduler`，注册每周任务。

### 前端适配

- 审查结果页每个 finding 卡片增加 👍👎 按钮
- 整体评分组件（星级 + 可选文字框）放在结果页底部
- 趋势看板新增 "反馈统计" 区块：各 Agent 误报率、最近 10 次反馈分布

### 组件

| 文件 | 职责 |
|------|------|
| `feedback/__init__.py` | 模块入口 |
| `feedback/api.py` | FastAPI 端点（POST/PUT feedback） |
| `feedback/storage.py` | FindingFeedback CRUD + ReviewTask 评分更新 |
| `feedback/retriever.py` | 负样本检索 + Prompt 上下文生成 |
| `feedback/analyzer.py` | 误报统计分析 + 周报生成 |

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/feedback/{task_id}` | POST | 提交 finding 级别反馈 |
| `/api/feedback/{task_id}/rating` | PUT | 提交整体评分 |
| `/api/feedback/{task_id}/stats` | GET | 查询某任务的反馈统计 |
| `/api/admin/feedback-analysis` | GET | 获取最新误报分析报告 |
| `/api/admin/run-analysis` | POST | 手动触发误报分析 |

---

## 实施顺序

1. 依赖安全检查（独立模块，对现有流程侵入小）
2. 人工反馈回路（数据模型 → 存储 → API → 前端 → 定时任务 → 检索注入）

每个模块完成后本地 git commit，暂停等待用户推送。

## 新增依赖

- `apscheduler>=3.10.0` — 定时任务调度
- `tomli>=2.0.0; python_version < "3.11"` — pyproject.toml 解析（Python 3.11+ 内置 tomllib）
- 无需额外依赖（OSV API 用 `requests`，已有）
