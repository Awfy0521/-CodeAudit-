import json
from agents.state import ReviewState
from utils.llm_client import get_llm_client
from tools.code_metrics import metrics_to_text

# ── System Prompts ───────────────────────────────────────────

SECURITY_PROMPT = """你是一位资深代码安全专家。你的任务是对给定的代码进行全面的安全审查。

审查维度：
1. **注入漏洞**：SQL 注入、命令注入、LDAP 注入、XPath 注入
2. **XSS 跨站脚本**：反射型、存储型、DOM 型 XSS
3. **敏感信息泄露**：硬编码的 API Key、密码、Token、私钥、数据库连接字符串
4. **认证与授权**：缺失认证检查、越权风险、会话管理缺陷
5. **数据安全**：不安全的加密算法(MD5/SHA1用于密码)、明文传输敏感数据、不安全的反序列化
6. **文件安全**：路径遍历、任意文件读取/写入、不安全的文件上传
7. **依赖安全**：使用已知漏洞的第三方库版本

输出格式（严格 JSON）：
{
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "line": 行号(整数),
      "category": "注入漏洞|XSS|敏感信息|认证授权|数据安全|文件安全|依赖安全",
      "code_snippet": "触发问题的具体代码片段（必须是原文中的真实代码，2-5行为宜）",
      "description": "问题描述",
      "suggestion": "修复建议"
    }
  ],
  "summary": "总体安全评估（1-3句话）"
}
如果未发现问题，findings 为空数组。"""

PERFORMANCE_PROMPT = """你是一位资深性能优化专家。你的任务是对给定的代码进行性能分析。

审查维度：
1. **算法复杂度**：是否存在 O(n²) 或更高复杂度的算法，是否有更优的替代方案
2. **数据库查询**：N+1 查询问题、缺少索引的查询、批量操作替代逐条操作
3. **内存管理**：大对象未及时释放、内存泄漏风险(listener未解绑)、循环引用
4. **IO 操作**：不必要的磁盘/网络 IO、文件未使用缓冲、同义反复的 API 调用
5. **缓存策略**：可缓存的计算结果未缓存、重复数据获取
6. **并发与异步**：可并行操作是否串行执行、锁竞争风险
7. **数据结构选择**：不合适的数据结构导致低效操作

输出格式（严格 JSON）：
{
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "line": 行号(整数),
      "category": "算法复杂度|数据库查询|内存管理|IO操作|缓存策略|并发异步|数据结构",
      "code_snippet": "触发问题的具体代码片段（必须是原文中的真实代码，2-5行为宜）",
      "description": "问题描述",
      "suggestion": "优化建议"
    }
  ],
  "summary": "总体性能评估（1-3句话）"
}
如果未发现问题，findings 为空数组。"""

BUSINESS_LOGIC_PROMPT = """你是一位资深代码质量与业务逻辑审核专家。你的任务是对给定的代码进行可读性和逻辑审查。

审查维度：
1. **命名规范**：变量/函数/类名是否清晰达意，是否符合语言命名惯例
2. **函数设计**：函数是否过长(>50行)、参数是否过多(>5个)、是否单一职责
3. **圈复杂度**：是否存在过深的嵌套(>4层)、过多的条件分支
4. **代码重复**：是否存在可抽取的重复逻辑(DRY 原则违反)
5. **设计模式**：是否可应用合适的设计模式改善结构、现有设计模式是否使用正确
6. **错误处理**：异常捕获是否过于宽泛(except Exception)、是否吞掉异常、错误信息是否清晰
7. **逻辑冗余**：不可达代码、无用的变量赋值、多余的类型转换
8. **可测试性**：代码是否易于单元测试、是否存在过紧的耦合

输出格式（严格 JSON）：
{
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "line": 行号(整数),
      "category": "命名规范|函数设计|圈复杂度|代码重复|设计模式|错误处理|逻辑冗余|可测试性",
      "code_snippet": "触发问题的具体代码片段（必须是原文中的真实代码，2-5行为宜）",
      "description": "问题描述",
      "suggestion": "改进建议"
    }
  ],
  "summary": "总体质量评估（1-3句话）"
}
如果未发现问题，findings 为空数组。"""

ARCHITECTURE_PROMPT = """你是一位资深软件架构审查专家。你的任务是对给定的代码进行架构级分析。

审查维度：
1. **模块耦合度**：模块间 import 依赖是否过于紧密，是否存在循环依赖、双向依赖
2. **依赖方向**：是否违反依赖倒置原则(DIP)，高层模块是否直接依赖低层实现细节
3. **分层架构**：是否存在跨层调用（如 UI 层直接访问数据库）、职责边界是否清晰
4. **God Class 检测**：单个类是否承担过多职责（>300行或>10个公开方法）
5. **接口隔离**：接口/基类是否过大，是否存在"胖接口"强制实现方引入无关方法
6. **包结构合理性**：目录和模块划分是否清晰，是否存在 util/common/misc 等过度集中的"垃圾堆"模块
7. **技术债务**：TODO/FIXME/HACK 标记、废弃代码、不一致的技术选型

输出格式（严格 JSON）：
{
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "line": 行号(整数),
      "category": "模块耦合|依赖方向|分层架构|God Class|接口隔离|包结构|技术债务",
      "code_snippet": "触发问题的具体代码片段（必须是原文中的真实代码，2-5行为宜）",
      "description": "问题描述",
      "suggestion": "改进建议"
    }
  ],
  "summary": "总体架构评估（1-3句话）",
  "architecture_score": "A|B|C|D|F"
}
如果未发现问题，findings 为空数组。architecture_score 根据整体架构质量从 A(优秀) 到 F(严重问题) 评分。"""

# ── Worker Functions ─────────────────────────────────────────


def _parse_review_result(raw: str) -> dict:
    """解析 LLM 返回的 JSON 字符串，失败时返回错误标记。"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"findings": [], "summary": "审查结果解析失败", "raw": raw}


def security_worker(state: ReviewState) -> ReviewState:
    """安全审查专家。"""
    client = get_llm_client()
    try:
        raw = client.chat_with_lint_context(
            code=state["code"],
            lint_results="",  # linter 结果不注入安全审查
            system_prompt=SECURITY_PROMPT,
        )
        result = _parse_review_result(raw["content"])
        result["_usage"] = raw["usage"]
        return {"security_review": result}
    except Exception as e:
        return {"security_review": {"findings": [], "summary": f"安全审查失败: {e}", "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}}


def performance_worker(state: ReviewState) -> ReviewState:
    """性能优化审查专家。"""
    client = get_llm_client()
    try:
        raw = client.chat_with_lint_context(
            code=state["code"],
            lint_results="",
            system_prompt=PERFORMANCE_PROMPT,
        )
        result = _parse_review_result(raw["content"])
        result["_usage"] = raw["usage"]
        return {"performance_review": result}
    except Exception as e:
        return {"performance_review": {"findings": [], "summary": f"性能审查失败: {e}", "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}}


def business_logic_worker(state: ReviewState) -> ReviewState:
    """业务逻辑审查专家。"""
    client = get_llm_client()
    try:
        metrics = state.get("code_metrics", {})
        metrics_text = metrics_to_text(metrics) if metrics else "无法获取代码度量数据"
        raw = client.chat(
            messages=[
                {"role": "system", "content": BUSINESS_LOGIC_PROMPT},
                {"role": "user", "content": f"""## 待审查代码
```python
{state["code"]}
```

## 代码度量数据（radon 分析）
{metrics_text}

请按 JSON 格式输出审查结果。"""},
            ],
            temperature=0.3,
            max_tokens=4096,
            json_mode=True,
        )
        result = _parse_review_result(raw["content"])
        result["_usage"] = raw["usage"]
        return {"business_logic_review": result}
    except Exception as e:
        return {"business_logic_review": {"findings": [], "summary": f"业务逻辑审查失败: {e}", "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}}


def architecture_worker(state: ReviewState) -> ReviewState:
    """架构设计审查专家。"""
    client = get_llm_client()
    try:
        metrics = state.get("code_metrics", {})
        metrics_text = metrics_to_text(metrics) if metrics else "无法获取代码度量数据"
        raw = client.chat(
            messages=[
                {"role": "system", "content": ARCHITECTURE_PROMPT},
                {"role": "user", "content": f"""## 待审查代码
```python
{state["code"]}
```

## 代码度量数据（radon 分析）
{metrics_text}

请按 JSON 格式输出审查结果。"""},
            ],
            temperature=0.3,
            max_tokens=4096,
            json_mode=True,
        )
        result = _parse_review_result(raw["content"])
        result["_usage"] = raw["usage"]
        return {"architecture_review": result}
    except Exception as e:
        return {"architecture_review": {"findings": [], "summary": f"架构审查失败: {e}", "_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}}
