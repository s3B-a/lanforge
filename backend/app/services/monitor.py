import platform
import time
import psutil

_BOOT_TIME = psutil.boot_time()

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
    }