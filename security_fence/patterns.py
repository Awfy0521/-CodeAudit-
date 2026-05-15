import re

# ── API Key / Token ────────────────────────────

API_KEY_PATTERNS = [
    # 显式 api_key / token / secret 赋值
    re.compile(
        r"""(?i)(api[_-]?key|apikey|token|secret|access[_-]?key|auth[_-]?token)\s*[:=]\s*(["'][^"'\n]{8,}["'])""",
    ),
    # 已知平台前缀: sk-, github_pat_, ghp_, xoxb-, rk-
    re.compile(
        r"""\b(sk-[a-zA-Z0-9]{32,}|github_pat_[a-zA-Z0-9_]{20,}|ghp_[a-zA-Z0-9]{30,}|xox[bpasr]-[a-zA-Z0-9-]{20,})\b"""
    ),
    # Bearer / Basic auth headers
    re.compile(
        r"""(?i)authorization\s*[:=]\s*["']?(bearer|basic)\s+([^\s"'\n,;]+)["']?""",
    ),
]

# ── 密码字面量 ────────────────────────────────

PASSWORD_PATTERNS = [
    re.compile(
        r"""(?i)(password|passwd|pwd)\s*[:=]\s*(["'][^"'\n]{3,}["'])""",
    ),
]

# ── 数据库连接字符串 ──────────────────────────

CONNECTION_STRING_PATTERNS = [
    # mysql://user:pass@host/db, postgresql://user:pass@host/db, mongodb://user:pass@host/db
    re.compile(
        r"""\b(mysql|postgres(?:ql)?|mongodb|redis|sqlite|oracle)://[^\s"'`\n]+@[^\s"'`\n]+\b""",
    ),
    # JDBC: jdbc:mysql://host/db?user=x&password=y
    re.compile(
        r"""(?i)jdbc:[a-z]+://[^\s"'`\n]+password=[^\s"'`&\n]+""",
    ),
]

# ── 私钥 ───────────────────────────────────────

PRIVATE_KEY_PATTERNS = [
    re.compile(
        r"""-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----\s*[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----""",
    ),
]

# Pattern type → display name mapping
PATTERN_TYPE_LABELS = {
    "api_key": "API Key",
    "password": "密码字面量",
    "connection_string": "数据库连接串",
    "private_key": "私钥",
}
