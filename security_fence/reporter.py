from security_fence.patterns import PATTERN_TYPE_LABELS


def desensitize_report_str(text: str, mapping: dict[str, dict]) -> str:
    """替换字符串中的占位符为脱敏特征描述（用于 fixed_code 等纯文本字段）。"""
    if not mapping:
        return text
    replacements = {}
    for secret_id, info in mapping.items():
        ptype = info.get("pattern_type", "unknown")
        label = PATTERN_TYPE_LABELS.get(ptype, "敏感信息")
        replacements[secret_id] = _format_feature(label, info)
    for secret_id, feature_text in replacements.items():
        text = text.replace(secret_id, feature_text)
    return text


def desensitize_report(report_data: dict, mapping: dict[str, dict]) -> dict:
    """将 LLM 返回的审查结果中的占位符替换为脱敏特征描述。

    遍历 findings 的 description、suggestion、code_snippet、summary 等字段，
    将出现的 SECRET_XXXX 替换为人可读的特征描述。
    """
    if not mapping:
        return report_data

    # 构建替换映射: SECRET_XXXX → 特征描述
    replacements = {}
    for secret_id, info in mapping.items():
        ptype = info.get("pattern_type", "unknown")
        label = PATTERN_TYPE_LABELS.get(ptype, "敏感信息")
        replacements[secret_id] = _format_feature(label, info)

    return _replace_recursive(report_data, replacements)


def _format_feature(label: str, info: dict) -> str:
    """格式化脱敏特征描述。"""
    ptype = info.get("pattern_type", "")
    if ptype == "api_key":
        prefix = info.get("original_startswith", "")
        suffix = info.get("original_suffix", "")
        return f"[{label} (前缀 {prefix}..., 尾号 {suffix})]"
    elif ptype == "password":
        length = info.get("original_length", 0)
        return f"[{label} ({length}字符)]"
    elif ptype == "connection_string":
        return f"[{label} (含密码)]"
    elif ptype == "private_key":
        key_type = info.get("key_type", "通用")
        return f"[{label} ({key_type})]"
    return f"[{label}]"


def _replace_recursive(obj, replacements: dict[str, str]):
    """递归替换对象中所有字符串值里的占位符。"""
    if isinstance(obj, str):
        for secret_id, feature_text in replacements.items():
            obj = obj.replace(secret_id, feature_text)
        return obj
    if isinstance(obj, dict):
        return {k: _replace_recursive(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_recursive(item, replacements) for item in obj]
    return obj
