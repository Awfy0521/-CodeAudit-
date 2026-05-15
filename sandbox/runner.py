import os
import tempfile
import docker
from docker.errors import DockerException


SANDBOX_IMAGE = "codeaudit-sandbox"


def _get_client():
    return docker.from_env()


def create_container() -> str:
    """创建沙箱容器（create + start），返回 container_id。"""
    client = _get_client()
    # 确保镜像存在
    try:
        client.images.get(SANDBOX_IMAGE)
    except docker.errors.ImageNotFound:
        raise RuntimeError(
            f"沙箱镜像 {SANDBOX_IMAGE} 未找到，请先执行: docker build -t {SANDBOX_IMAGE} -f Dockerfile.sandbox ."
        )
    container = client.containers.create(
        image=SANDBOX_IMAGE,
        command="sleep infinity",
        # 限制资源：最多 512M 内存，30% CPU
        mem_limit="512m",
        nano_cpus=300_000_000,
        network_mode="none",
        read_only=True,
    )
    container.start()
    return container.id


def exec_in_container(container_id: str, cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """在容器内执行命令，返回 (exit_code, stdout, stderr)。"""
    client = _get_client()
    container = client.containers.get(container_id)
    try:
        result = container.exec_run(cmd, stdout=True, stderr=True, demux=False)
        # result.output is bytes
        output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)
        return result.exit_code, output, ""
    except Exception as e:
        return -1, "", str(e)


def copy_to_container(container_id: str, host_path: str, container_path: str):
    """复制文件到容器内。使用 docker cp 的底层 tar 实现。"""
    import io
    import tarfile
    client = _get_client()
    container = client.containers.get(container_id)

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        tar.add(host_path, arcname=os.path.basename(container_path))
    tar_stream.seek(0)
    container.put_archive(os.path.dirname(container_path), tar_stream)


def destroy_container(container_id: str):
    """停止并删除容器。"""
    try:
        client = _get_client()
        container = client.containers.get(container_id)
        container.stop(timeout=5)
        container.remove(force=True)
    except Exception:
        pass


def write_temp_file(code: str, suffix: str) -> str:
    """将代码写入临时文件，返回文件路径。"""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="codeaudit_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    return path
