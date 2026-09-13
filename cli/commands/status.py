import httpx

def run(args, client):
    resp = httpx.get(f"{client.hub_url}/health", timeout=10)
    resp.raise_for_status()
    print(f"hub: {resp.json().get('status', 'unknown')}  ({client.hub_url})")

    stats = client.get("/system/stats")
    mem = stats["memory"]
    disk = stats["disk"]
    print()
    print(f"hostname : {stats['hostname']}")
    print(f"uptime   : {_fmt_duration(stats['uptime_seconds'])}")
    print(f"cpu      : {stats['cpu']['percent']:.1f}%  ({stats['cpu']['cores']} cores)")
    print(f"memory   : {mem['percent']:.1f}%  ({_fmt_bytes(mem['used'])} / {_fmt_bytes(mem['total'])})")
    print(f"disk     : {disk['percent']:.1f}%  ({_fmt_bytes(disk['used'])} / {_fmt_bytes(disk['total'])})")

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