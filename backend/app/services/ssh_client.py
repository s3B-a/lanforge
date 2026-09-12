from contextlib import contextmanager

import paramiko

from app.core.config import PROJECT_ROOT
from app.core.devices_store import target_host

def _connect(device: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key_path = PROJECT_ROOT / device["ssh_key_path"]
    client.connect(
        hostname=target_host(device),
        port=device.get("ssh_port", 22),
        username=device["ssh_user"],
        key_filename=str(key_path),
        timeout=10,
    )

    return client

@contextmanager
def ssh_client(device: dict):
    client = _connect(device)
    try:
        yield client
    finally:
        client.close()

def run_command(device: dict, command: str, timeout: int = 30) -> dict:
    with ssh_client(device) as client:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return {
            "exit_code": exit_code,
            "stdout": stdout.read().decode(errors="replace"),
            "stderr": stderr.read().decode(errors="replace"),
        }

def open_interactive_shell(device: dict):
    """Returns (client, channel). Caller is responsible for closing `client`
    once done with the channel (used for the websocket terminal session)."""
    client = _connect(device)
    channel = client.invoke_shell(term="xterm")
    return client, channel

def sftp_list(device: dict, path: str) -> list[dict]:
    with ssh_client(device) as client:
        sftp = client.open_sftp()
        try:
            entries = []
            for attr in sftp.listdir_attr(path):
                entries.append(
                    {
                        "name": attr.filename,
                        "size": attr.st_size,
                        "is_dir": bool(attr.st_mode and (attr.st_mode & 0o040000)),
                        "modified": attr.st_mtime,
                    }
                )
            return entries
        finally:
            sftp.close()

def sftp_read(device: dict, path: str) -> bytes:
    with ssh_client(device) as client:
        sftp = client.open_sftp()
        try:
            with sftp.open(path, "rb") as f:
                return f.read()
        finally:
            sftp.close()

def sftp_write(device: dict, path: str, data: bytes) -> None:
    with ssh_client(device) as client:
        sftp = client.open_sftp()
        try:
            with sftp.open(path, "wb") as f:
                f.write(data)
        finally:
            sftp.close()