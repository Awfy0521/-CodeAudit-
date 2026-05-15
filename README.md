# 智审 CodeAudit — 多智能体代码审查与修复机器人

## 快速部署

```bash
# 1. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY 或 DEEPSEEK_API_KEY

# 2. 启动
docker compose up -d

# 3. 访问
open http://localhost:8000
```

不使用 Docker：

```bash
pip install -r requirements.txt
python main.py
# 访问 http://localhost:8000
```

## 这是什么

CodeAudit 是一个基于 **LangGraph 多智能体编排**的自动化代码审查系统。你提交一段代码（或一个 GitHub 仓库），三个 AI 专家并行审查安全漏洞、性能瓶颈和代码质量，最后由决策者汇总去重、生成修复方案。

**支持的输入方式**：粘贴代码 · 上传文件 · 本地目录路径 · GitHub 仓库 URL（含子路径）

## 工作流

```
代码输入 → 代码解析 → 静态分析 → AgentTeam 并行审查 → 汇总决策 → 修复方案 → 报告存档
                              ├─ 🔐 安全审查专家（7 维度）
                              ├─ ⚡ 性能优化师（7 维度）
                              └─ 🧠 业务逻辑审核（8 维度）
```

## 亮点

### 🤖 多智能体并行协作
三个专业 AI 智能体基于 LangGraph 并行执行，互不阻塞。各自独立审查不同维度后，由 Orchestrator 统一去重合并、校准严重等级、生成修复代码。单智能体失败不影响其他智能体。

### 🔀 双模型自动降级
支持 Mimo 和 DeepSeek 两个 LLM 提供商。当主模型调用失败时，自动切换到备用模型并带指数退避重试，无需人工干预。

### 📊 完整修复方案
不仅发现问题，还生成**修复后的完整代码**和 **Unified Diff**。结果页提供左右逐行对比视图，可一键查看修复后代码。

### 🎨 审查过程可视化
审查进度页展示 7 阶段管线动画，代码实时标注每个智能体正在扫描的行区域，发现的问题用色条标记。三个智能体的审查进度独立显示。

### 📦 零依赖前端
前端为单个 HTML 文件（~1700 行），无框架、无构建步骤、无 node_modules。基于 hash 路由实现首页、审查输入、审查进度、审查结果、历史记录五个页面的切换。

### 🔍 多维度覆盖
| 智能体 | 审查维度 |
|--------|----------|
| 安全专家 | SQL注入、XSS、命令注入、敏感信息泄露、认证缺陷、加密算法、路径遍历 |
| 性能优化师 | 算法复杂度、N+1查询、内存泄漏、IO瓶颈、缓存策略、并发竞争、数据结构 |
| 业务逻辑审核 | 命名规范、函数设计、圈复杂度、DRY原则、错误处理、设计模式、逻辑冗余、可测试性 |

## 技术栈

| 层 | 技术 |
|----|------|
| 编排引擎 | LangGraph (StateGraph) |
| 后端 | FastAPI + Uvicorn |
| LLM 客户端 | OpenAI SDK（兼容 Mimo / DeepSeek） |
| 数据库 | SQLite + SQLAlchemy ORM |
| 静态分析 | flake8 + pylint |
| 前端 | 原生 HTML/CSS/JS（SPA，零构建） |
| 容器化 | Docker + Docker Compose |

## 项目结构

```
CodeAudit/
├── agents/
│   ├── graph.py          # LangGraph 编排（并行分发 + 汇总）
│   ├── workers.py        # 三个审查 Worker 的 System Prompt
│   └── state.py          # 全局状态 TypedDict
├── database/
│   ├── models.py         # SQLAlchemy 模型（ReviewTask + ReviewReport）
│   └── crud.py           # 数据库操作
├── tools/
│   └── code_linter.py    # flake8 + pylint 静态分析封装
├── utils/
│   └── llm_client.py     # 统一 LLM 客户端（自动降级 + 重试）
├── static/
│   └── index.html        # 完整前端 SPA
├── main.py               # FastAPI 入口
├── config.py             # pydantic-settings 配置
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
