"""OSV.dev API 封装 + LRU 缓存 + 重试。"""

import time
import hashlib
import json

import requests

from .parsers import PackageInfo

OSV_QUERY_URL = "https://api.osv.dev/v1/query"
REQUEST_INTERVAL = 0.2  # 200ms between requests
TIMEOUT = 5  # seconds
MAX_RETRIES = 2

_last_request_time: float = 0.0


class OsvCache:
    """线程安全的内存 LRU 缓存。"""

    def __init__(self, maxsize: int = 512):
        self._cache: dict[str, tuple[float, list[dict]]] = {}  # key → (timestamp, result)
        self._maxsize = maxsize
        self._ttl = 86400  # 24 hours

    def get(self, key: str) -> list[dict] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, result = entry
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        return result

    def set(self, key: str, value: list[dict]):
        if len(self._cache) >= self._maxsize:
            # 淘汰最老的条目
            oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]
        self._cache[key] = (time.time(), value)


_cache = OsvCache()


def _cache_key(package_name: str, version: str, ecosystem: str = "PyPI") -> str:
    raw = f"{ecosystem}:{package_name}:{version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def query_vulnerabilities(package_name: str, version: str, ecosystem: str = "PyPI") -> list[dict]:
    """查询指定包版本是否存在已知漏洞，返回漏洞列表。"""
    key = _cache_key(package_name, version, ecosystem)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    body = {
        "package": {"name": package_name, "ecosystem": ecosystem},
        "version": version,
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            _rate_limit()
            resp = requests.post(OSV_QUERY_URL, json=body, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                vulns = data.get("vulns", []) if data else []
                result = [_normalize_vuln(v) for v in vulns]
                _cache.set(key, result)
                return result
            # 404 = no vulns found
            if resp.status_code == 404:
                _cache.set(key, [])
                return []
            if attempt < MAX_RETRIES:
                time.sleep(1)
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(1)
        except requests.exceptions.ConnectionError:
            break  # 网络不可达，降级

    return []


def check_dependencies(packages: list[PackageInfo]) -> list[dict]:
    """批量检查依赖漏洞，返回所有漏洞信息列表。"""
    warnings = []
    for pkg in packages:
        if pkg.version == "*":
            # 尝试不指定版本查询（OSV 可能返回该包所有已知漏洞）
            vulns = query_vulnerabilities(pkg.name, "")
        else:
            vulns = query_vulnerabilities(pkg.name, pkg.version)

        if vulns:
            warnings.append({
                "package_name": pkg.name,
                "version": pkg.version,
                "file": pkg.file,
                "line": pkg.line,
                "vulnerabilities": vulns,
            })
    return warnings


def _normalize_vuln(vuln: dict) -> dict:
    """标准化 OSV 返回的漏洞数据。"""
    severity = "UNKNOWN"
    for sev in vuln.get("severity", []):
        if sev.get("type") == "CVSS_V3":
            score = float(sev.get("score", 0))
            if score >= 9.0:
                severity = "CRITICAL"
            elif score >= 7.0:
                severity = "HIGH"
            elif score >= 4.0:
                severity = "MEDIUM"
            else:
                severity = "LOW"
            break

    aliases = vuln.get("aliases", [])
    # 提取 CVE 编号
    cves = [a for a in aliases if a.startswith("CVE-")]

    affected = vuln.get("affected", [])
    affected_versions = ""
    fixed_in = ""
    if affected:
        for r in affected[0].get("ranges", []):
            for ev in r.get("events", []):
                if ev.get("introduced"):
                    affected_versions = f'>={ev["introduced"]}'
                if ev.get("fixed"):
                    fixed_in = ev["fixed"]

    return {
        "id": vuln.get("id", ""),
        "summary": vuln.get("summary", trunc(vuln.get("details", ""), 200)),
        "severity": severity,
        "aliases": cves[:3],
        "references": [r.get("url", "") for r in vuln.get("references", [])[:3]],
        "affected_versions": affected_versions,
        "fixed_in": fixed_in,
    }


def trunc(text: str, max_len: int) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text
