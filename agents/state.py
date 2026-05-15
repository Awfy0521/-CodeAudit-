from typing import TypedDict


class ReviewState(TypedDict):
    code: str
    scope: str
    target_path: str
    security_review: dict
    performance_review: dict
    business_logic_review: dict
    merged_review: dict
    fixed_code: str
    diff: str
    error: str
    status: str
    task_id: str
