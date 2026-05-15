import uuid
from security_fence.patterns import (
    API_KEY_PATTERNS,
    PASSWORD_PATTERNS,
    CONNECTION_STRING_PATTERNS,
    PRIVATE_KEY_PATTERNS,
)


def _short_id() -> str:
    return uuid.uuid4().hex[:6].upper()


def scan(code: str) -> tuple[str, dict]:
    """扫描代码中的敏感信息，返回 (脱敏代码, 内存映射表)。

    映射表仅在内存中，不落盘、不发送给 LLM。
    """
    mapping: dict[str, dict] = {}  # SECRET_XXXX -> {type, features}
    desensitized = code

    # 按优先级处理：先处理完整的私钥块（多行），再处理单行模式
    # 私钥
    for pattern in PRIVATE_KEY_PATTERNS:
        for match in pattern.finditer(desensitized):
            secret_id = f"SECRET_{_short_id()}"
            secret_text = match.group(0)
            start_line = desensitized[: match.start()].count("\n") + 1
            end_line = desensitized[: match.end()].count("\n") + 1
            lines = list(range(start_line, end_line + 1))
            mapping[secret_id] = {
                "pattern_type": "private_key",
                "original_length": len(secret_text),
                "key_type": "RSA" if "RSA" in secret_text else "通用",
                "occurrence_lines": lines,
            }
            desensitized = desensitized.replace(secret_text, secret_id, 1)

    # 连接字符串
    for pattern in CONNECTION_STRING_PATTERNS:
        for match in pattern.finditer(desensitized):
            secret_id = f"SECRET_{_short_id()}"
            secret_text = match.group(0)
            start_line = desensitized[: match.start()].count("\n") + 1
            end_line = desensitized[: match.end()].count("\n") + 1
            mapping[secret_id] = {
                "pattern_type": "connection_string",
                "original_length": len(secret_text),
                "occurrence_lines": list(range(start_line, end_line + 1)),
            }
            desensitized = desensitized.replace(secret_text, secret_id, 1)

    # API Key / Token
    for pattern in API_KEY_PATTERNS:
        for match in pattern.finditer(desensitized):
            secret_id = f"SECRET_{_short_id()}"
            secret_text = match.group(0)
            start_line = desensitized[: match.start()].count("\n") + 1
            end_line = desensitized[: match.end()].count("\n") + 1
            mapping[secret_id] = {
                "pattern_type": "api_key",
                "original_startswith": secret_text[:3],
                "original_suffix": secret_text[-4:] if len(secret_text) > 7 else secret_text[-2:],
                "occurrence_lines": list(range(start_line, end_line + 1)),
            }
            desensitized = desensitized.replace(secret_text, secret_id, 1)

    # 密码
    for pattern in PASSWORD_PATTERNS:
        for match in pattern.finditer(desensitized):
            secret_id = f"SECRET_{_short_id()}"
            secret_text = match.group(0)
            start_line = desensitized[: match.start()].count("\n") + 1
            end_line = desensitized[: match.end()].count("\n") + 1
            mapping[secret_id] = {
                "pattern_type": "password",
                "original_length": len(secret_text),
                "occurrence_lines": list(range(start_line, end_line + 1)),
            }
            desensitized = desensitized.replace(secret_text, secret_id, 1)

    return desensitized, mapping
