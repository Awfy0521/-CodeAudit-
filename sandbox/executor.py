import re
from .runner import (
    exec_in_container,
    write_temp_file,
    copy_to_container,
)

# ── 工具链定义 ────────────────────────────────

TOOLCHAINS = {
    ".py": [
        {
            "name": "flake8",
            "cmd": ["flake8", "--max-line-length=150", "/code/{filename}"],
            "language": "python",
        },
        {
            "name": "pylint",
            "cmd": ["pylint", "--output-format=text", "/code/{filename}"],
            "language": "python",
        },
    ],
    ".js": [
        {
            "name": "eslint",
            "cmd": ["eslint", "--format=compact", "/code/{filename}"],
            "language": "javascript",
        },
    ],
    ".java": [
        {
            "name": "javac",
            "cmd": ["javac", "-Xlint", "/code/{filename}"],
            "language": "java",
        },
    ],
    ".go": [
        {
            "name": "go",
            "cmd": ["go", "vet", "/code/{filename}"],
            "language": "go",
        },
    ],
    # 次级工具（仅在主工具全部通过后执行）
    "_secondary": {
        ".py": [
            {
                "name": "pytest",
                "cmd": ["python", "-m", "pytest", "/code/"],
                "language": "python",
            },
        ],
        ".js": [
            {
                "name": "npm-test",
                "cmd": ["npm", "test"],
                "language": "javascript",
            },
        ],
    },
}

# ── 语言检测 ──────────────────────────────────


def detect_language(code: str) -> str:
    """根据代码特征检测语言，返回后缀如 '.py', '.js'。"""
    # Java: 优先检测，class 关键字 + public/private
    if re.search(r"\b(public\s+class|public\s+static\s+void\s+main)\b", code):
        return ".java"
    # Go
    if re.search(r"\bpackage\s+\w+\b", code) and re.search(r"\bfunc\s+\w+\(", code):
        return ".go"
    # Python
    if re.search(r"\b(def\s+\w+|import\s+\w+|from\s+\w+\s+import)\b", code):
        return ".py"
    # JS/TS
    if re.search(r"\b(const|let|var|function|=>|require|import\s*\{)\b", code):
        if re.search(r":"):
            return ".ts"
        return ".js"
    # 降级：统计各行顶格关键字
    return _fallback_detect(code)


def _fallback_detect(code: str) -> str:
    keywords = {"def": ".py", "func ": ".go", "function": ".js", "const": ".js", "var": ".js"}
    scores: dict[str, int] = {}
    for line in code.splitlines():
        stripped = line.strip()
        for kw, ext in keywords.items():
            if stripped.startswith(kw):
                scores[ext] = scores.get(ext, 0) + 1
    if scores:
        return max(scores, key=scores.get)
    return ".py"


# ── 错误提纯 ──────────────────────────────────


def purify_errors(tool_name: str, raw_output: str) -> list[dict]:
    """从工具原始输出中提取结构化错误。

    返回: [{tool, line, col, code, message}]
    """
    errors = []

    # 截断：超过 2000 字符保留首尾
    if len(raw_output) > 2000:
        head = raw_output[:800]
        tail = raw_output[-800:]
        omitted = len(raw_output) - 1600
        raw_output = f"{head}\n... (省略 {omitted} 字符) ...\n{tail}"

    if tool_name == "flake8":
        errors.extend(_parse_flake8(raw_output))
    elif tool_name == "pylint":
        errors.extend(_parse_pylint(raw_output))
    elif tool_name == "eslint":
        errors.extend(_parse_eslint(raw_output))
    elif tool_name == "javac":
        errors.extend(_parse_javac(raw_output))
    elif tool_name == "go":
        errors.extend(_parse_go_vet(raw_output))

    # 如果没有提取到结构化错误，返回尾部 800 字符的原始信息
    if not errors:
        return [{"tool": tool_name, "line": 0, "col": 0, "code": "RAW", "message": raw_output[-800:]}]

    return errors


def _parse_flake8(output: str) -> list[dict]:
    # path:line:col: CODE message
    errors = []
    for m in re.finditer(r"([^:]+):(\d+):(\d+):\s*(\w+)\s+(.+)", output):
        errors.append({
            "tool": "flake8",
            "line": int(m.group(2)),
            "col": int(m.group(3)),
            "code": m.group(4),
            "message": m.group(5).strip(),
        })
    return errors


def _parse_pylint(output: str) -> list[dict]:
    # path:line:col: CODE: message
    for m in re.finditer(r"(\d+):(\d+):\s*(\w\d+):\s*(.+?)(?=\n\S|\Z)", output):
        errors = []
        errors.append({
            "tool": "pylint",
            "line": int(m.group(1)),
            "col": int(m.group(2)),
            "code": m.group(3),
            "message": m.group(4).strip(),
        })
    # Also try simpler pattern
    if not errors:
        for m in re.finditer(r"(\w\d+):\s*(\d+):(\d+):\s*(.+?)(?=\n|$)", output):
            errors.append({
                "tool": "pylint",
                "line": int(m.group(2)),
                "col": int(m.group(3)),
                "code": m.group(1),
                "message": m.group(4).strip(),
            })
    return errors


def _parse_eslint(output: str) -> list[dict]:
    # path: line line:col severity rule message
    errors = []
    for m in re.finditer(r"(\d+):(\d+)\s+(error|warning)\s+(.+?)\s+-\s+(.+?)(?=\n|$)", output):
        errors.append({
            "tool": "eslint",
            "line": int(m.group(1)),
            "col": int(m.group(2)),
            "code": m.group(4).strip(),
            "message": m.group(5).strip(),
        })
    return errors


def _parse_javac(output: str) -> list[dict]:
    # path:line: error: message
    errors = []
    for m in re.finditer(r"(\d+):\s*(error|warning):\s*(.+?)(?=\n|$)", output):
        errors.append({
            "tool": "javac",
            "line": int(m.group(1)),
            "col": 0,
            "code": m.group(2),
            "message": m.group(3).strip(),
        })
    return errors


def _parse_go_vet(output: str) -> list[dict]:
    errors = []
    for m in re.finditer(r"(\d+):(\d+):\s*(.+?)(?=\n|$)", output):
        errors.append({
            "tool": "go",
            "line": int(m.group(1)),
            "col": int(m.group(2)),
            "code": "vet",
            "message": m.group(3).strip(),
        })
    return errors


# ── 工具链执行 ────────────────────────────────


class ToolResult:
    def __init__(self):
        self.passed: bool = True
        self.errors: list[dict] = []
        self.total_errors: int = 0


def run_toolchain(
    code: str,
    container_id: str,
    language: str | None = None,
) -> ToolResult:
    """在容器中运行对应语言的工具链，返回结构化结果。"""
    result = ToolResult()
    suffix = language or detect_language(code)

    primary_tools = TOOLCHAINS.get(suffix, [])
    secondary_tools = TOOLCHAINS.get("_secondary", {}).get(suffix, [])

    if not primary_tools:
        result.passed = True
        return result

    # 写入临时文件并拷贝到容器
    filepath = write_temp_file(code, suffix)
    filename = filepath.rsplit(os.sep, 1)[-1]
    try:
        copy_to_container(container_id, filepath, f"/code/{filename}")
    except Exception as e:
        result.passed = False
        result.errors = [{"tool": "sandbox", "line": 0, "col": 0, "code": "INTERNAL", "message": f"文件拷贝失败: {e}"}]
        return result
    finally:
        try:
            os.unlink(filepath)
        except OSError:
            pass

    # 执行主工具链
    for tool in primary_tools:
        cmd = [part.format(filename=filename) if "{filename}" in part else part for part in tool["cmd"]]
        exit_code, stdout, stderr = exec_in_container(container_id, cmd)
        if exit_code != 0 or stdout.strip():
            tool_errors = purify_errors(tool["name"], stdout)
            result.errors.extend(tool_errors)
            result.total_errors += len(tool_errors)

    # 仅当主工具全部通过时执行次级工具
    if result.total_errors == 0 and secondary_tools:
        for tool in secondary_tools:
            cmd = [part.format(filename=filename) if "{filename}" in part else part for part in tool["cmd"]]
            exit_code, stdout, stderr = exec_in_container(container_id, cmd)
            if exit_code != 0:
                tool_errors = purify_errors(tool["name"], stdout)
                result.errors.extend(tool_errors)
                result.total_errors += len(tool_errors)

    result.passed = result.total_errors == 0
    return result
