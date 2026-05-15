# 智审 CodeAudit — 多智能体代码审查与修复机器人

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY 或 DEEPSEEK_API_KEY

# 3. 启动（开发模式，热重载）
uv run dev

# 4. 访问
open http://localhost:8000
```

生产模式：`uv run start` 或 Docker 部署：

```bash
# 首次需构建沙箱镜像 + 启动 Milvus
docker build -t codeaudit-sandbox -f Dockerfile.sandbox .
docker run -d --name milvus-standalone -p 19530:19530 -p 9091:9091 milvusdb/milvus:latest milvus run standalone
docker compose up -d
```

## 这是什么

CodeAudit 是一个基于 **LangGraph 多智能体编排**的自动化代码审查系统。四个 AI 专家并行审查安全漏洞、性能瓶颈、代码质量和架构设计，结合静态分析工具（flake8 + pylint + radon）度量代码复杂度，最后由决策者汇总去重、生成修复方案和 Unified Diff。

**支持的输入方式**：粘贴代码 · 本地文件/目录 · GitHub 仓库（全仓或指定子路径）

## 工作流

```
代码输入 → 代码解析 → 静态分析 → AgentTeam 并行审查 → 汇总决策 → 修复方案 → 报告存档
                              ├─ 🔐 安全审查专家
                              ├─ ⚡ 性能优化师
                              ├─ 🧠 业务逻辑审核
                              └─ 🏗️ 架构审查师
```

## 功能亮点

### 🤖 四智能体并行协作
四个专业 AI 智能体基于 LangGraph StateGraph 并行执行，独立审查不同维度后由 Orchestrator 统一去重合并、校准严重等级、生成修复代码。单个智能体失败不影响其他。

### 📦 依赖安全检查
自动解析 Python 依赖文件（requirements.txt / pyproject.toml / Pipfile），通过 OSV.dev API 查询已知 CVE 漏洞，将高危依赖警告注入安全审查结果，建议修复版本。

### 📊 代码度量
集成 radon 静态分析，自动计算圈复杂度（Cyclomatic Complexity）、可维护性指数（Maintainability Index）和原始指标（LOC、注释率等），生成热度表定位高风险函数。

### 📈 趋势看板
独立趋势看板页面，展示审查任务总数、完成率、来源分布、Token 用量统计、平均问题发现数，以及最近 30 次审查的时间线柱状图。

### 🐳 Docker 沙箱 + Milvus 环境
沙箱镜像内置多语言工具链，Milvus 提供向量检索能力。启动前需预构建：

```bash
docker build -t codeaudit-sandbox -f Dockerfile.sandbox .
docker run -d --name milvus-standalone -p 19530:19530 -p 9091:9091 milvusdb/milvus:latest milvus run standalone
```

### 📥 报告导出
审查完成后支持一键导出 **Markdown**（含问题详情、修复代码、Diff）或 **JSON** 格式报告，方便存档或集成到其他工具。

### 🐳 Docker 沙箱闭环自修
修复代码在隔离 Docker 容器中自动运行 lint/test/compile 验证，利用热启动复用容器减少开销。发现错误后结构化提纯，多轮迭代修复（最多 3 轮），通过后输出最终代码。

### 💬 人工反馈回路
支持 finding 级点赞/点踩 + 整体星级评分，点踩数据索引到 RAG 知识库辅助后续审查避坑。每周定时自动分析各 Agent 误报率，生成 Prompt 优化建议报告。

### 💰 Token 用量追踪
每次审查记录 Prompt / Completion Token 消耗，在结果页和导出报告中展示，趋势看板提供累计用量统计。

### 🛡️ 安全围栏
代码发送给 LLM 之前自动扫描并替换敏感信息（API Key、密码、数据库连接串、私钥），使用内存映射表 + 占位符机制，审查结果仅展示脱敏特征描述，防止敏感数据泄露。

### 🔍 RAG 增强检索
集成 Milvus 向量数据库，对代码进行三层父子块切分（项目层→文件层→AST 块层），审查时自动检索跨文件引用上下文，让智能体理解函数调用链和依赖关系。

### 🗣️ 多智能体辩论
单轮交叉审查机制：各智能体审查完成后，交叉质疑其他人的发现，Orchestrator 综合原始审查和交叉意见做终裁，减少误报。

### 🔀 双模型自动降级
支持 Mimo 和 DeepSeek 两个 LLM 提供商。主模型调用失败后自动切换备用模型并带指数退避重试，无需人工干预。

### 🔍 多维审查覆盖

| 智能体 | 审查维度 |
|--------|----------|
| 安全专家 | SQL注入、XSS、命令注入、敏感信息泄露、认证缺陷、加密算法、路径遍历 |
| 性能优化师 | 算法复杂度、N+1查询、内存泄漏、IO瓶颈、缓存策略、并发竞争、数据结构 |
| 业务逻辑审核 | 命名规范、函数设计、圈复杂度、DRY原则、错误处理、设计模式、逻辑冗余、可测试性 |
| 架构审查师 | 模块划分、依赖方向、接口设计、分层架构、扩展性、技术选型合理性 |

### 🎨 审查过程可视化
审查进度页展示 7 阶段管线动画，实时显示当前执行阶段。审查完成后加载进度条自动跳转至结果页，结果页以 Tab 页切换查看安全/性能/业务/架构/度量/综合报告，支持 Diff 逐行对比视图。

### 📦 零依赖前端
前端为单个 HTML 文件，无框架、无构建步骤、无 node_modules。基于 hash 路由实现首页、审查输入、审查进度、审查结果、历史记录、趋势看板六个页面的切换。

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/review` | POST | 提交审查任务，返回 task_id |
| `/api/review/{id}` | GET | 查询任务状态与完整结果 |
| `/api/review/{id}` | DELETE | 删除历史记录 |
| `/api/review/{id}/export?format=md\|json` | GET | 导出审查报告 |
| `/api/history?limit=&offset=` | GET | 历史任务列表（分页） |
| `/api/trends` | GET | 趋势统计数据 |

## 技术栈

| 层 | 技术 |
|----|------|
| 编排引擎 | LangGraph (StateGraph) |
| 后端 | FastAPI + Uvicorn |
| LLM 客户端 | OpenAI SDK（兼容 Mimo / DeepSeek） |
| 数据库 | SQLite + SQLAlchemy ORM |
| 静态分析 | flake8 + pylint + radon |
| 前端 | 原生 HTML/CSS/JS（SPA，零构建） |
| 容器化 | Docker + Docker Compose |
| 包管理 | uv (Astral) |

## 项目结构

```
CodeAudit/
├── agents/
│   ├── graph.py          # LangGraph 编排（并行分发 + 汇总）
│   ├── workers.py        # 四个审查 Worker 的 System Prompt
│   └── state.py          # 全局状态 TypedDict
├── security_fence/
│   ├── scanner.py        # 敏感信息扫描 + 占位符替换
│   ├── patterns.py       # 4 类敏感信息的正则模式
│   └── reporter.py       # LLM 结果脱敏还原
├── sandbox/
│   ├── runner.py         # Docker 容器热启动管理
│   └── executor.py       # 工具链调度 + 错误提纯
├── rag/
│   ├── chunker.py        # AST 感知三层父子块切分
│   ├── indexer.py        # Milvus 向量索引管理
│   └── retriever.py      # 关键词检索 + 父子上下文加载
├── debate/
│   └── cross_review.py   # 单轮交叉审查编排
├── dependency_checker/
│   ├── parsers.py        # 依赖文件解析（3 种格式）
│   └── osv_client.py     # OSV.dev API + LRU 缓存
├── feedback/
│   ├── api.py            # 反馈 API 端点
│   ├── storage.py        # 反馈数据持久化
│   ├── retriever.py      # 负样本检索 + 避坑提示
│   └── analyzer.py       # 误报统计 + 周报生成
├── database/
│   ├── models.py         # SQLAlchemy 模型（ReviewTask + ReviewReport）
│   └── crud.py           # 数据库操作
├── tools/
│   ├── code_linter.py    # flake8 + pylint 静态分析封装
│   └── code_metrics.py   # radon 代码度量封装
├── utils/
│   └── llm_client.py     # 统一 LLM 客户端（自动降级 + 重试）
├── static/
│   └── index.html        # 完整前端 SPA
├── main.py               # FastAPI 入口 + API 端点
├── config.py             # pydantic-settings 配置
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```
