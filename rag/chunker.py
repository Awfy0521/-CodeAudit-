"""三层父子块切分：L0 项目层 → L1 文件层 → L2 块层（AST 感知）。"""

import ast
import re
import hashlib


class Chunk:
    """代码块，携带层级和父子关系。"""

    def __init__(self, chunk_id: str, level: str, content: str, parent_id: str = "",
                 file_path: str = "", metadata: dict | None = None):
        self.id = chunk_id
        self.level = level        # "L0" | "L1" | "L2"
        self.content = content
        self.parent_id = parent_id
        self.file_path = file_path
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level,
            "content": self.content,
            "parent_id": self.parent_id,
            "file_path": self.file_path,
            "metadata": self.metadata,
        }


def chunk_code(code: str, file_path: str = "input", ext: str = ".py") -> list[Chunk]:
    """将代码字符串切分为三层块。"""
    chunks: list[Chunk] = []

    # L0: 项目层（单文件时为文件摘要）
    l0_id = _id_for(file_path, "L0")
    l0_content = _extract_project_structure(code, ext)
    chunks.append(Chunk(l0_id, "L0", l0_content, file_path=file_path,
                        metadata={"type": "project_root", "ext": ext}))

    # L1: 文件层
    l1_id = _id_for(file_path, "L1")
    # 截断过大的文件内容（保留前 4000 字符 + 尾部 2000）
    l1_content = code
    if len(code) > 8000:
        l1_content = code[:4000] + f"\n... (省略 {len(code) - 6000} 字符) ...\n" + code[-2000:]
    chunks.append(Chunk(l1_id, "L1", l1_content,
                        parent_id=l0_id, file_path=file_path,
                        metadata={"type": "file", "ext": ext, "parent_id": l0_id}))

    # L2: 块层（AST 切分）
    l2_chunks = _split_to_blocks(code, file_path, ext, l1_id)
    chunks.extend(l2_chunks)

    return chunks


def _extract_project_structure(code: str, ext: str) -> str:
    """提取项目结构摘要：imports / packages / 顶层类函数声明。"""
    lines = []
    if ext == ".py":
        # 收集 import 语句和顶层 def/class 签名
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                lines.append(stripped)
            elif stripped.startswith(("def ", "class ")) and not stripped.startswith("    "):
                lines.append(stripped)
    else:
        # 其他语言：收集 import/require 和顶层声明
        for line in code.splitlines():
            stripped = line.strip()
            if re.match(r"^(import|package|#include|require|const|var|function|func)\b", stripped):
                lines.append(stripped)
    return "\n".join(lines) if lines else code[:2000]


def _split_to_blocks(code: str, file_path: str, ext: str, parent_id: str) -> list[Chunk]:
    """将代码切分为 AST 感知的 L2 块。"""
    if ext == ".py":
        return _split_python(code, file_path, parent_id)
    return _split_regex(code, file_path, ext, parent_id)


def _split_python(code: str, file_path: str, parent_id: str) -> list[Chunk]:
    """使用 ast 模块进行 Python AST 切分。"""
    chunks = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # 语法有问题的代码，降级为 regex 切分
        return _split_regex(code, file_path, ".py", parent_id)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            try:
                node_code = ast.get_source_segment(code, node)
                if node_code:
                    node_id = _id_for(f"{file_path}::{node.name}", "L2")
                    chunks.append(Chunk(
                        node_id, "L2", node_code,
                        parent_id=parent_id, file_path=file_path,
                        metadata={
                            "type": type(node).__name__,
                            "name": node.name,
                            "lineno": node.lineno,
                            "parent_id": parent_id,
                        },
                    ))
            except Exception:
                pass
    return chunks


def _split_regex(code: str, file_path: str, ext: str, parent_id: str) -> list[Chunk]:
    """使用正则表达式切分（JS/TS/Java/Go 降级方案）。"""
    chunks = []
    patterns = {
        ".js": r"^\s*(async\s+)?function\s+(\w+)|^\s*(const|let|var)\s+\w+\s*=\s*(async\s*)?\(|^\s*class\s+\w+",
        ".ts": r"^\s*(async\s+)?function\s+(\w+)|^\s*(const|let|var)\s+\w+\s*=\s*(async\s*)?\(|^\s*class\s+\w+|^\s*interface\s+\w+",
        ".java": r"^\s*(public|private|protected)?\s*(static)?\s*\w+\s+\w+\s*\([^)]*\)\s*\{|^\s*(public|private)?\s*class\s+\w+",
        ".go": r"^\s*func\s+(\(\w+\s+\*?\w+\)\s+)?\w+\(|^\s*type\s+\w+\s+struct",
    }

    pattern = patterns.get(ext, patterns[".py"])
    # 按行匹配，找到函数/类/方法边界
    lines = code.splitlines()
    i = 0
    while i < len(lines):
        if re.match(pattern, lines[i]):
            start = i
            # 简单启发式：收集直到找到匹配的闭合大括号或下一个顶层声明
            indent = len(lines[i]) - len(lines[i].lstrip())
            block_lines = [lines[i]]
            i += 1
            brace_depth = lines[start].count("{") - lines[start].count("}")
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped and not stripped.startswith("//"):
                    brace_depth += stripped.count("{") - stripped.count("}")
                block_lines.append(lines[i])
                i += 1
                if brace_depth <= 0 and (stripped == "}" or (stripped and "}" in stripped)):
                    break
            block_code = "\n".join(block_lines)
            name = _extract_name(lines[start])
            node_id = _id_for(f"{file_path}::{name or start}", "L2")
            chunks.append(Chunk(
                node_id, "L2", block_code,
                parent_id=parent_id, file_path=file_path,
                metadata={"type": "function", "name": name, "lineno": start + 1, "parent_id": parent_id},
            ))
        else:
            i += 1
    return chunks


def _extract_name(line: str) -> str:
    """从声明行提取函数/类名。"""
    m = re.search(r"\b(?:function|class|def|func|const|let|var)\s+(\w+)", line)
    if m:
        return m.group(1)
    m = re.search(r"\s+(\w+)\s*\([^)]*\)\s*\{", line)
    if m:
        return m.group(1)
    return ""


def _id_for(path: str, level: str) -> str:
    """生成稳定的块 ID。"""
    raw = f"{level}:{path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
