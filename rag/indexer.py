"""Milvus 向量索引管理：全量/增量索引。"""

import json
from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility,
)

from .chunker import chunk_code, Chunk

COLLECTION_NAME = "codeaudit_chunks"
MILVUS_HOST = "localhost"
MILVUS_PORT = 19530
VECTOR_DIM = 1024  # embedding 维度（后续可通过 embedding 模型调整，先用文本占位）


def _connect():
    try:
        # 检查是否已连接
        if not connections.has_connection("default"):
            connections.connect("default", host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=5)
        return True
    except Exception:
        return False


def _get_or_create_collection() -> Collection | None:
    """获取或创建 Milvus collection。"""
    if not _connect():
        return None

    if utility.has_collection(COLLECTION_NAME):
        return Collection(COLLECTION_NAME)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=32),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=16384),
        FieldSchema(name="level", dtype=DataType.VARCHAR, max_length=4),
        FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="file_path", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=4096),
    ]
    schema = CollectionSchema(fields, description="CodeAudit 代码块索引")
    collection = Collection(COLLECTION_NAME, schema)

    # 创建 IVF_FLAT 索引（后续可升级为 HNSW）
    index_params = {
        "metric_type": "IP",
    }
    collection.create_index("id", index_params)
    collection.load()
    return collection


def index_code(code: str, file_path: str = "input", ext: str | None = None,
               source: str = "local", repo_url: str = "") -> list[Chunk]:
    """索引代码并返回所有 Chunk 对象。

    Args:
        code: 代码字符串
        file_path: 文件路径标识
        ext: 文件扩展名（如 '.py'），None 则自动检测
        source: 来源类型（local / github_full / github_path）
        repo_url: GitHub 仓库 URL（增量索引时用于识别已有 collection）
    """
    if ext is None:
        # 简单检测
        code_head = code[:200]
        if "import " in code_head or "def " in code_head:
            ext = ".py"
        elif "function " in code_head or "const " in code_head:
            ext = ".js"
        elif "public class" in code_head:
            ext = ".java"
        elif "package " in code_head and "func " in code_head:
            ext = ".go"
        else:
            ext = ".py"

    chunks = chunk_code(code, file_path, ext)

    collection = _get_or_create_collection()
    if collection is not None:
        try:
            data = [
                [c.id for c in chunks],
                [c.content for c in chunks],
                [c.level for c in chunks],
                [c.parent_id for c in chunks],
                [c.file_path for c in chunks],
                [json.dumps(c.metadata, ensure_ascii=False) for c in chunks],
            ]
            collection.insert(data)
            collection.flush()
        except Exception:
            pass  # Milvus 不可用时静默跳过

    return chunks


def delete_all():
    """清空索引（调试用）。"""
    if not _connect():
        return
    if utility.has_collection(COLLECTION_NAME):
        utility.drop_collection(COLLECTION_NAME)
