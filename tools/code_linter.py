import subprocess
import tempfile
import os


def run_flake8(code: str) -> str:
    """使用 flake8 对代码片段进行静态分析，返回格式化的结果字符串。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["flake8", "--max-line-length=120", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            # 将临时文件路径替换为可读标识
            output = output.replace(tmp_path, "<code>")
        return output if output else "flake8 未发现静态问题"
    except FileNotFoundError:
        return "flake8 未安装，跳过静态分析"
    except subprocess.TimeoutExpired:
        return "flake8 分析超时"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def run_pylint(code: str) -> str:
    """使用 pylint 对代码片段进行分析，返回格式化的结果字符串。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["pylint", "--output-format=text", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout.strip()
        if output:
            output = output.replace(tmp_path, "<code>")
        return output if output else "pylint 未发现静态问题"
    except FileNotFoundError:
        return "pylint 未安装，跳过静态分析"
    except subprocess.TimeoutExpired:
        return "pylint 分析超时"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def run_all_linters(code: str) -> str:
    """运行所有静态分析工具，返回组合结果。"""
    results = []
    results.append("=== flake8 ===")
    results.append(run_flake8(code))
    results.append("")
    results.append("=== pylint ===")
    results.append(run_pylint(code))
    return "\n".join(results)
