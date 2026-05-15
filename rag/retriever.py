"""代码块检索：基于关键词 + 父子上下文加载。

设计为可扩展接口 — 当前用关键词匹配，后续可升级为 embeddings 向量检索。
"""

import re
from collections import Counter

from .chunker import Chunk


class SearchResult:
    """单条检索结果，包含 chunk + 相关度分数。"""

    def __init__(self, chunk: Chunk, score: float):
        self.chunk = chunk
        self.score = score

    def to_context(self) -> str:
        """格式化为可注入 LLM 的上下文字符串。"""
        header = f"// [{self.chunk.level}] {self.chunk.file_path}"
        if self.chunk.metadata.get("name"):
            header += f" — {self.chunk.metadata['name']} (L{self.chunk.metadata.get('lineno', '?')})"
        return f"{header}\n```\n{self.chunk.content}\n```"


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取关键词（函数名、变量名、类名）。"""
    keywords = []
    # 匹配标识符: snake_case, camelCase, PascalCase
    for m in re.finditer(r"\b([a-zA-Z_]\w{2,})\b", text):
        kw = m.group(1)
        # 过滤常见无意义词
        if kw.lower() not in {"the", "and", "for", "this", "that", "with", "from", "import", "def", "class", "return"}:
            keywords.append(kw)
    return keywords


def search(query: str, chunks: list[Chunk], top_k: int = 5,
           load_parents: bool = True) -> list[SearchResult]:
    """关键词检索 top_k 个最相关的 L2 块，自动加载其 L1 父文档。

    Args:
        query: 查询文本（如函数名、问题描述）
        chunks: 所有已索引的 Chunk 列表
        top_k: 返回最大结果数
        load_parents: 是否加载父级 L1 文档上下文
    """
    query_kw = _extract_keywords(query)
    if not query_kw:
        return []

    # 使用 TF 加权计分
    scored: list[SearchResult] = []
    for chunk in chunks:
        if chunk.level != "L2":
            continue
        content_lower = chunk.content.lower()
        score = 0.0
        for kw in query_kw:
            # 精确匹配加分更多
            count = content_lower.count(kw.lower())
            if count > 0:
                score += min(count, 5) * 2.0
            # 模糊匹配（子串包含）
            if len(kw) > 4:
                for word in re.findall(r"\b[a-zA-Z_]\w{2,}\b", content_lower):
                    if kw.lower() in word and kw.lower() != word:
                        score += 0.5
        # 标题/函数名匹配权重加倍
        name = chunk.metadata.get("name", "")
        if name and name.lower() in query.lower():
            score += 10.0
        if score > 0:
            scored.append(SearchResult(chunk, score))

    scored.sort(key=lambda r: r.score, reverse=True)
    results = scored[:top_k]

    if load_parents and results:
        # 加载 L1 父文档（去重）
        seen_parents = set()
        parent_chunks = []
        for sr in results:
            parent_id = sr.chunk.parent_id
            if parent_id and parent_id not in seen_parents:
                seen_parents.add(parent_id)
                parent = next((c for c in chunks if c.id == parent_id), None)
                if parent:
                    parent_chunks.append(SearchResult(parent, 0.0))
        # L1 父文档插入结果最前面
        results = parent_chunks + results

    return results


def search_by_symbol(symbol: str, chunks: list[Chunk]) -> list[SearchResult]:
    """按符号名精确查找（跨文件引用时使用）。"""
    results = []
    for chunk in chunks:
        if chunk.level == "L2" and chunk.metadata.get("name", "").lower() == symbol.lower():
            results.append(SearchResult(chunk, 10.0))
    return results
