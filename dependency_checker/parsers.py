"""依赖文件解析器：requirements.txt / pyproject.toml / Pipfile。"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PackageInfo:
    name: str
    version: str
    specifier: str
    ecosystem: str = "PyPI"
    line: int = 0
    file: str = ""


def parse(content: str, filename: str) -> list[PackageInfo]:
    """根据文件名分发到对应解析器。"""
    basename = Path(filename).name.lower()
    if basename.startswith("requirements") and basename.endswith(".txt"):
        return _parse_requirements(content, filename)
    if basename == "pyproject.toml" or basename.endswith("/pyproject.toml"):
        return _parse_pyproject(content, filename)
    if basename in ("pipfile",):
        return _parse_pipfile(content, filename)
    return []


# ── requirements.txt ──────────────────────────


def _parse_requirements(content: str, filename: str, depth: int = 0) -> list[PackageInfo]:
    if depth > 3:
        return []
    packages: list[PackageInfo] = []
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("--"):
            continue
        # -r 引用，递归解析（深度限制 3 层）
        if stripped.startswith("-r "):
            # 返回引用标记，由调用方处理；此处跳过
            continue
        pkg = _parse_pip_line(stripped)
        if pkg:
            pkg.line = i
            pkg.file = filename
            packages.append(pkg)
    return packages


def _parse_pip_line(line: str) -> PackageInfo | None:
    """解析单行 pip 依赖。"""
    # 处理: name==version ; python_version >= "3.8"
    line = re.sub(r"\s*;.*$", "", line)
    # 处理: name [extras] specifier
    match = re.match(r"^([^=<>!~\[\s]+)\s*(\[.*?\])?\s*([^;]*)", line)
    if not match:
        return None
    name = match.group(1).strip().lower()
    spec_part = match.group(3).strip() if match.group(3) else ""
    version, specifier = _extract_version(spec_part)
    return PackageInfo(name=name, version=version, specifier=specifier)


# ── pyproject.toml ─────────────────────────────


def _parse_pyproject(content: str, filename: str) -> list[PackageInfo]:
    packages: list[PackageInfo] = []
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return packages

    try:
        data = tomllib.loads(content)
    except Exception:
        return packages

    deps = data.get("project", {}).get("dependencies", [])
    opt_deps = data.get("project", {}).get("optional-dependencies", {})

    line = 1
    for dep in deps:
        pkg = _parse_pip_line(dep)
        if pkg:
            pkg.line = line
            pkg.file = filename
            packages.append(pkg)
        line += 1

    for group, dep_list in opt_deps.items():
        for dep in dep_list:
            pkg = _parse_pip_line(dep)
            if pkg:
                pkg.line = line
                pkg.file = filename
                packages.append(pkg)
            line += 1

    return packages


# ── Pipfile ───────────────────────────────────


def _parse_pipfile(content: str, filename: str) -> list[PackageInfo]:
    packages: list[PackageInfo] = []
    in_packages = False
    in_dev = False
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("["):
            in_packages = stripped in ("[packages]",) or stripped in ("[dev-packages]",)
            in_dev = stripped == "[dev-packages]"
            continue
        if not in_packages:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        # "package" = ">=1.0"
        m = re.match(r'"([^"]+)"\s*=\s*"([^"]*)"', stripped)
        if m:
            name = m.group(1).lower()
            version, specifier = _extract_version(m.group(2))
            packages.append(PackageInfo(name=name, version=version, specifier=specifier, line=i, file=filename))
    return packages


# ── 公共工具 ──────────────────────────────────


def _extract_version(spec_part: str) -> tuple[str, str]:
    """从约束符中提取版本号和原始约束。"""
    spec = spec_part.strip()
    if not spec:
        return "*", ""
    m = re.search(r"([\d]+(?:\.[\d]+)*)", spec)
    if m:
        return m.group(1), spec.replace(m.group(1), "").strip() or spec[:2]
    return "*", spec


def _detect_dep_files(code: str) -> list[str]:
    """在代码字符串中检测依赖文件名（用于 GitHub 仓库扫描场景）。"""
    found = []
    for pattern in ["requirements", "pyproject.toml", "Pipfile"]:
        if pattern in code:
            found.append(pattern)
    return found
