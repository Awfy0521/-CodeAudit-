from typing import TypedDict


class ReviewState(TypedDict):
    code: str
    scope: str
    target_path: str
    security_review: dict
    performance_review: dict
    business_logic_review: dict
    architecture_review: dict
    code_metrics: dict
    merged_review: dict
    fixed_code: str
    diff: str
    token_usage: dict
    error: str
    status: str
    task_id: str
    # RAG
    chunks: list  # 代码块列表 (Chunk.to_dict())
    # Debate
    pre_merged_findings: list  # 预汇总 findings（辩论前）
    debate_results: list  # 交叉审查结果
    # Dependency check
    dependency_warnings: list  # 依赖漏洞警告
