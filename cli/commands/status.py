import httpx

def run(args, client):
    resp = httpx.get(f"{client.hub_url}/health", timeout=10)
    resp.raise_for_status()
    print(f"hub: {resp.json().get('status', 'unknown')}  ({client.hub_url})")

    stats = client.get("/system/stats")
    mem = stats["memory"]
    disk = stats["disk"]
    net = stats["network"]
    gpu = stats.get("gpu")
    print()
    print(f"hostname : {stats['hostname']}")
    print(f"uptime   : {_fmt_duration(stats['uptime_seconds'])}")
    print(f"cpu      : {stats['cpu']['percent']:.1f}%  ({stats['cpu']['cores']} cores)")
    print(f"memory   : {mem['percent']:.1f}%  ({_fmt_bytes(mem['used'])} / {_fmt_bytes(mem['total'])})")
    print(f"disk     : {disk['percent']:.1f}%  ({_fmt_bytes(disk['used'])} / {_fmt_bytes(disk['total'])})")
    print(f"network  : sent {_fmt_bytes(net['bytes_sent'])}  recv {_fmt_bytes(net['bytes_recv'])}")
    if gpu:
        print(f"gpu      : {gpu['percent']:.0f}%  ({gpu['memory_used_mb']:.0f}MB / {gpu['memory_total_mb']:.0f}MB)")
    else:
        print("gpu      : n/a")

    devices = client.get("/devices")["devices"]
    print()
    if not devices:
        print("no devices registered.")
        return

    rows = [("ID", "NAME", "KIND", "ONLINE", "HOST")]
    for d in devices:
        rows.append(
            (
                d["id"],
                d.get("name", ""),
                d["kind"],
                "yes" if d.get("online") else "no",
                d.get("last_ip") or d.get("host", ""),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))

    for d in devices:
        if d["kind"] != "ssh" or not d.get("online"):
            continue
        print(f"\n{d['id']}:")
        try:
            remote = client.get(f"/devices/{d['id']}/stats")
        except httpx.HTTPStatusError as exc:
            print(f"  (could not get stats: {exc.response.status_code} {exc.response.text})")
            continue
        _print_remote_stats(remote)

def _print_remote_stats(remote: dict) -> None:
    mem_total = remote.get("memory_total") or 0
    mem_used = remote.get("memory_used") or 0
    disk_total = remote.get("disk_total") or 0
    disk_used = remote.get("disk_used") or 0
    mem_pct = (mem_used / mem_total * 100) if mem_total else 0
    disk_pct = (disk_used / disk_total * 100) if disk_total else 0

    print(f"  cpu    : {remote.get('cpu_percent') or 0:.1f}%")
    print(f"  memory : {mem_pct:.1f}%  ({_fmt_bytes(mem_used)} / {_fmt_bytes(mem_total)})")
    print(f"  disk   : {disk_pct:.1f}%  ({_fmt_bytes(disk_used)} / {_fmt_bytes(disk_total)})")
    print(
        f"  net    : sent {_fmt_bytes(remote.get('network_sent') or 0)}  "
        f"recv {_fmt_bytes(remote.get('network_recv') or 0)}"
    )
    gpu = remote.get("gpu")
    if gpu:
        print(f"  gpu    : {gpu['percent']:.0f}%  ({gpu['memory_used_mb']:.0f}MB / {gpu['memory_total_mb']:.0f}MB)")
    else:
        print("  gpu    : n/a")

def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024

    return f"{n:.1f}PB"

def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)