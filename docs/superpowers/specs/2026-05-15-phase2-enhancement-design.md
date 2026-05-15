# 智审 CodeAudit 第二阶段增强 — 需求设计文档

**日期**: 2026-05-15 | **状态**: 已确认

## 概述

基于自我检查文档的路线图分析，本阶段聚焦三个核心模块：安全围栏、Docker 沙箱闭环自修、RAG 增强检索 + 多智能体辩论。

## 模块一：安全围栏 (Security Fence)

### 目的
在代码发送给 LLM 之前，检测并替换敏感信息（API Key、密码、数据库连接串、私钥），防止数据泄露。LLM 返回结果后，用脱敏特征替代占位符展示。

### 组件

| 文件 | 职责 |
|------|------|
| `security_fence/__init__.py` | 模块入口，暴露 `scan()` 和 `desensitize_report()` |
| `security_fence/scanner.py` | 正则扫描代码，生成内存映射表，返回脱敏代码 |
| `security_fence/patterns.py` | 4 类敏感信息的正则模式定义 |
| `security_fence/reporter.py` | 将 LLM 结果中的占位符替换为脱敏特征描述 |

### 映射表格式

仅在内存中，不落盘，不发送给 LLM：

```python
{
    "SECRET_A3F2": {
        "pattern_type": "api_key",
        "original_startswith": "sk-",
        "original_suffix": "b1c3",
        "occurrence_lines": [12, 45]
    }
}
```

### 报告展示规则

| 类型 | 展示格式 |
|------|----------|
| api_key | "API Key (前缀 sk-..., 尾号 b1c3)" |
| password | "密码字面量 (8字符)" |
| connection_string | "数据库连接串 (含密码)" |
| private_key | "私钥 (RSA 2048)" |

### 流程

```
原始代码 → scanner.py → (内存映射表 + 脱敏代码) → LLM
LLM 结果 → reporter.py → 脱敏特征描述 → 数据库 → 前端展示
```

## 模块二：Docker 沙箱 + 闭环自修

### 目的
在隔离环境中对 Orchestrator 生成的修复代码自动运行 lint/test/compile，失败则多轮迭代修复，最多 3 轮。

### Docker 策略

- **预构建镜像** `codeaudit-sandbox`：基于 `python:3.13-slim`，内置 flake8/pylint/pytest/radon/eslint/javac/go
- **热启动**：审查开始时 `docker create`，整个生命周期内 `docker exec` 复用，审查结束 `docker rm`
- 用户需预先执行一次 `docker build -t codeaudit-sandbox -f Dockerfile.sandbox .`

### 工具链

| 语言 | 执行内容 |
|------|----------|
| Python | flake8 → pylint → pytest (如有) |
| JS/TS | eslint → npm test (如有) |
| Java | javac 编译检查 |
| Go | go vet → go test (如有) |

### 错误日志提纯

- **截断**：超过 2000 字符保留前 800 + 后 800
- **结构化提取**：正则匹配 pylint/flake8/eslint/javac 标准格式，统一为 `[{tool, line, col, code, message}]`
- 发给 Orchestrator 只传结构化数组；数组为空但 exit code 非零时传尾部 800 字符兜底

### 多轮修复上下文管理

- 第 1 轮：首次修复后执行，失败则传递结构化错误列表
- 第 2 轮：仅传递上一轮 diff + 本轮错误，不发完整代码
- 第 3 轮：同上，失败后标注"无法自动修复"

### 组件

| 文件 | 职责 |
|------|------|
| `sandbox/__init__.py` | 模块入口 |
| `sandbox/runner.py` | Docker 容器生命周期管理 |
| `sandbox/executor.py` | 工具链调度 + 错误提纯 |
| `Dockerfile.sandbox` | 预构建沙箱镜像定义 |

### 闭环流程

```
Orchestrator 生成修复代码
       ↓
sandbox.executor 执行工具链
    ┌─ 通过 → 返回最终代码
    └─ 失败 → 提纯错误 → Orchestrator 针对性修复 → 重试（最多 3 轮）
```

## 模块三：RAG 增强检索 + 多智能体辩论

### RAG 基础设施

- **向量数据库**：Milvus，Docker 独立服务，常驻后台
- **代码切分**：三层父子块机制

### 三层切分

| 层级 | 粒度 | 内容 |
|------|------|------|
| L0 项目层 | 目录/包 | 目录结构、包依赖图、模块关系 |
| L1 文件层 | 完整文件 | 文件内容 + imports/导出关系 |
| L2 块层 | 函数/类/方法 | AST 切分，`parent_id` 指向 L1 |

### 检索流程

```
Agent 发现疑似问题
    → 向量检索 L2 块层（找到相关函数）
    → parent_id 加载 L1 文件层（完整上下文）
    → 拼接父子文档注入审查 prompt
```

### 辩论机制（单轮交叉审查）

```
4 Agent 并行审查 → Orchestrator 预汇总
                         ↓
       预汇总结果分发给各 Agent（移除来源标注）
                         ↓
       各 Agent 对其他 findings 发表质疑
                         ↓
       Orchestrator 综合原始审查 + 交叉质疑 → 终裁
```

### 增量索引

- 首次审查：全量索引
- 后续同一仓库：按 git diff 增量索引（新增/修改文件重新索引，删除文件移除）
- 按仓库 URL 建立独立 Milvus collection

### 组件

| 文件 | 职责 |
|------|------|
| `rag/__init__.py` | 模块入口 |
| `rag/indexer.py` | 代码索引构建（全量/增量） |
| `rag/chunker.py` | 三层父子块切分（AST 感知） |
| `rag/retriever.py` | 向量检索 + 父子上下文加载 |
| `debate/__init__.py` | 模块入口 |
| `debate/cross_review.py` | 交叉审查编排（分发预汇总结果、收集质疑） |

## 实施顺序

1. 安全围栏（最低侵入，可独立验证）
2. Docker 沙箱 + 闭环自修（依赖 Orchestrator 改造）
3. RAG + 辩论（依赖 Milvus 服务 + 索引基础设施）

每个模块完成后本地 git commit，暂停等待用户推送后再继续下一个。

## 依赖

- `pymilvus>=2.4.0` — Milvus Python SDK
- `docker>=7.0.0` — Docker SDK for Python（沙箱管理）
- Docker 镜像需预构建：`codeaudit-sandbox`、Milvus standalone
