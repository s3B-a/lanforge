import base64
import json
import threading
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

_connections_lock = threading.Lock()
_connections: dict[str, paramiko.SSHClient] = {}

def _is_alive(client: paramiko.SSHClient) -> bool:
    transport = client.get_transport()
    return transport is not None and transport.is_active()

def _get_persistent_client(device: dict) -> paramiko.SSHClient:
    device_id = device["id"]
    with _connections_lock:
        client = _connections.get(device_id)
        if client is not None and _is_alive(client):
            return client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        client = _connect(device)
        _connections[device_id] = client
        return client

@contextmanager
def ssh_client(device: dict):
    """Yields this device's shared persistent connection. Do not close it,
    other callers reuse the same cached connection"""
    yield _get_persistent_client(device)

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
    once done with the channel (used for the websocket terminal session).

    invoke_shell() just requests whatever the SSH server's configured
    default shell is, on Windows OpenSSH that's cmd.exe unless the
    server's own registry DefaultShell is changed. Rather than requiring
    that remote config change, launch PowerShell as the first command
    over the fresh cmd.exe shell instead."""
    client = _connect(device)
    channel = client.invoke_shell(term="xterm")
    channel.send(b"powershell.exe -NoLogo\r\n")
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

def run_powershell(device: dict, script: str, timeout: int = 30) -> str:
    """Runs a (possibly multi-line) PowerShell script via -EncodedCommand:
    one exec_command call, no stdin writes. Piping a script over stdin to
    `powershell -Command -` (the technique ssh_manager.py's deploy uses) can
    silently produce no output at all while still reporting exit code 0,
    -EncodedCommand sidesteps that failure mode entirely, plus all
    escaping/quoting concerns, by passing the whole script as one base64
    blob on the command line."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    command = f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"
    with ssh_client(device) as client:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode(errors="replace")
        if exit_code != 0:
            raise RuntimeError(stderr.read().decode(errors="replace") or f"exit code {exit_code}")

        return output

_REMOTE_STATS_SCRIPT = r"""
$cpu = $null
try {
    $cpu = (Get-CimInstance Win32_Processor -ErrorAction Stop | Measure-Object -Property LoadPercentage -Average).Average
} catch {}

$memTotal = $null
$memUsed = $null
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $memTotal = [int64]$os.TotalVisibleMemorySize * 1024
    $memUsed = $memTotal - ([int64]$os.FreePhysicalMemory * 1024)
} catch {}

$diskTotal = $null
$diskUsed = $null
try {
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" -ErrorAction Stop
    $diskTotal = $disk.Size
    $diskUsed = $disk.Size - $disk.FreeSpace
} catch {}

$netRecv = $null
$netSent = $null
try {
    $net = Get-NetAdapterStatistics -ErrorAction Stop
    $netRecv = ($net | Measure-Object -Property ReceivedBytes -Sum).Sum
    $netSent = ($net | Measure-Object -Property SentBytes -Sum).Sum
} catch {}

$gpu = $null
try {
    $raw = & nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null
    if ($raw) {
        $parts = ($raw | Select-Object -First 1) -split ',\s*'
        $gpu = @{ percent = [double]$parts[0]; memory_used_mb = [double]$parts[1]; memory_total_mb = [double]$parts[2] }
    }
} catch {}

$result = @{
    hostname = $env:COMPUTERNAME
    cpu_percent = $cpu
    memory_total = $memTotal
    memory_used = $memUsed
    disk_total = $diskTotal
    disk_used = $diskUsed
    network_recv = $netRecv
    network_sent = $netSent
    gpu = $gpu
}
$result | ConvertTo-Json -Compress
"""

def get_remote_stats(device: dict) -> dict:
    """Live CPU/RAM/disk/network/GPU snapshot of a remote SSH device,
    gathered over the existing SSH connection"""
    output = run_powershell(device, _REMOTE_STATS_SCRIPT)
    try:
        return json.loads(output.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON output from stats script: {output!r}") from exc