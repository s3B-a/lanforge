import platform
import subprocess
import time
import psutil

_BOOT_TIME = psutil.boot_time()

def _get_local_gpu() -> dict | None:
    """Best-effort NVIDIA GPU snapshot via nvidia-smi; None if absent or on
    any other GPU vendor."""
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if output.returncode != 0 or not output.stdout.strip():
            return None
        percent, used_mb, total_mb = output.stdout.strip().splitlines()[0].split(",")
        return {
            "percent": float(percent),
            "memory_used_mb": float(used_mb),
            "memory_total_mb": float(total_mb),
        }
    except (OSError, ValueError):
        return None

def get_local_stats() -> dict:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/" if platform.system() != "Windows" else "C:\\")
    net = psutil.net_io_counters()

    return {
        "hostname": platform.node(),
        "uptime_seconds": time.time() - _BOOT_TIME,
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "per_core": psutil.cpu_percent(interval=None, percpu=True),
            "cores": psutil.cpu_count(logical=True),
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "percent": mem.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
        },
        "gpu": _get_local_gpu(),
    }