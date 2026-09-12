# localserver

A self-hosted hub that runs on a Windows 11 machine on your home network. It
lets you manage and talk to other devices on the LAN, run shell commands
over SSH, browse/transfer files, proxy chat requests to an Ollama instance
running on a dedicated LLM machine, and watch system stats all through one
authenticated API.

Everything here is custom-written (Robyn for the backend, plain SSH/SFTP via
paramiko, a direct Ollama proxy) rather than built on an existing home-lab
tool.

## Status

| Piece | Status |
|---|---|
| `backend/` - hub API (devices, shell, files, llm, monitor) | Built |
| `scripts/` - firewall rule + Windows service install + device heartbeat agent | Built |
| `frontend/` - browser dashboard (chat / devices / terminal) | Not started |
| `cli/` - terminal client (`hub_cli.py`) | Not started |
| `ssh/ssh_manager.py` - key generation/provisioning helper | Built |
| Other Device Control (beyond presence detection) | Not started |

## How it fits together

```
                            your LAN
  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │   [ Hub - this repo ]                 [ LLM rig ]        │
  │   Windows 11 machine     SSH →     Windows 11 machine    │
  │   runs backend/ 24/7     :22      runs Ollama on :11434  │
  │   (as a Windows           ←       heartbeat (reports its │
  │    service)                        current IP every 30s) │
  │                                                          │
  │   [ Your devices ]                 [ Presence-only ]     │
  │   Linux/Windows laptop,           other devices - hub    │
  │   iPhone, Android → HTTP           TCP-probes these.     │
  │   requests to the hub                                    │
  └──────────────────────────────────────────────────────────┘
```

Every request to the hub (including a device's own heartbeat) must send
`Authorization: Bearer <HUB_TOKEN>`. There's no per-user login; this is a
single shared token for your own devices, not a multi-user system.

Devices are tracked in `cfg/devices.json` in one of two `kind`s:

- **`ssh`**: a machine you can reach over SSH (e.g. the LLM rig). It runs
  `scripts/heartbeat_agent.py` to keep the hub updated with its current IP,
  so it keeps working even if DHCP changes its address. If it also runs
  Ollama, add `ollama_port` and the hub can proxy chat requests to it.
- **`presence`**: a device that can't run anything (PS4, Fire TV, etc). The
  hub just does a live TCP probe against a known port to report online/offline.

## Prerequisites

- The hub machine: Windows 11, Python 3.12+.
- Each `ssh` device: OpenSSH server enabled and reachable, and a key pair you
  control (the hub connects as a normal SSH client, nothing exotic).
- [NSSM](https://nssm.cc/download) if you want the hub to run as a background
  Windows service (optional; you can also just run it in a terminal).

## Install on the hub machine

```powershell
git clone <this repo> localserver
cd localserver

python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt

copy cfg\.env.example cfg\.env
copy cfg\devices.example.json cfg\devices.json
```

Edit `cfg\.env`:

- `HUB_TOKEN`: generate a real one, don't leave the example value:
  ```powershell
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- `HUB_HOST`: leave as `0.0.0.0` once you're ready for other LAN devices to
  reach it (use `127.0.0.1` only while testing locally on the hub machine
  itself).
- `HUB_PORT`: default `8080`, change if that's taken.

Edit `cfg\devices.json`: start from the example entries and either edit them
in place or delete them and use the API (see "Adding a device" below) once
the hub is running.

### Run it

**Manually, in a terminal (good for first-time testing):**

```powershell
cd backend
$env:PYTHONPATH = (Resolve-Path ".").Path
..\.venv\Scripts\python.exe -m app.main
```

Check it's alive: `http://<hub-host>:8080/health` should return
`{"status": "ok"}` with no auth needed. Every other route needs the
`Authorization: Bearer <HUB_TOKEN>` header.

**As a background Windows service (for actual daily use):**

1. Download NSSM, extract `nssm.exe` into `nssm\nssm.exe` in the repo root
   (that folder is gitignored on purpose).
2. Open the port to your LAN, as Administrator:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\firewall_setup.ps1 -Port 8080
   ```
3. Install and start the service, as Administrator:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1
   Start-Service LocalHub
   ```

Logs land in `logs\hub.out.log` / `logs\hub.err.log`. To reinstall after
changing `install_service.ps1`, remove the old service first
(`nssm\nssm.exe remove LocalHub confirm`) then rerun the script.

## Adding a new device

### An SSH-reachable machine

1. Make sure you can already SSH into it manually once (password auth is
   fine for this step), to confirm the OpenSSH server is running and
   reachable.

2. Generate a keypair for it and install the public half, using
   `ssh/ssh_manager.py` (same venv as the backend):
   ```powershell
   .venv\Scripts\python.exe ssh\ssh_manager.py generate llm-rig
   .venv\Scripts\python.exe ssh\ssh_manager.py deploy llm-rig --host llm-rig.local --user yourusername
   ```
   `deploy` prompts for that account's password once, over the SSH
   connection it just opened, then writes the key into the right
   `authorized_keys` file for you. Pass `--remote-os windows-admin` instead
   of the default `auto` if the account is a member of Administrators on a
   Windows box (those use `administrators_authorized_keys` under
   `%ProgramData%\ssh`, with a locked-down ACL that the command sets for
   you); otherwise `auto` detects Linux vs. a regular Windows account.

3. Register it with the hub:
   ```powershell
   .venv\Scripts\python.exe ssh\ssh_manager.py register llm-rig `
       --hub-url http://<hub-host>:8080 --token <HUB_TOKEN> `
       --host llm-rig.local --ssh-user yourusername --ollama-port 11434
   ```
   (Omit `--ollama-port` for a device that isn't running an LLM.) This is
   just a thin wrapper around `POST /devices`; you can call that endpoint
   directly instead if you'd rather script it yourself.
   
4. On that device, run the heartbeat agent so the hub always has its current
   LAN IP (handles DHCP changes, you don't need a static IP):
   ```powershell
   python scripts\heartbeat_agent.py --hub-url http://<hub-host>:8080 --device-id llm-rig --token <HUB_TOKEN>
   ```
   Keep this running (a scheduled task or another NSSM service works well)
   for anything without a static IP.

Other `ssh_manager.py` commands: `list` (locally managed keypairs) and
`remove <device-id>` (deletes the local keypair; you still need to drop the
matching line from that device's `authorized_keys` yourself).

### A presence-only device (anything that can't run a script)

```powershell
$headers = @{ Authorization = "Bearer <HUB_TOKEN>" }
Invoke-RestMethod -Uri http://<hub-host>:8080/devices -Method Post -Headers $headers -Body (@{
    id = "ps4"
    name = "PlayStation 4"
    kind = "presence"
    host = "192.168.1.50"   # this one needs a real static/DHCP-reserved IP,
                            # there's no agent to report it dynamically
    probe_port = 987
} | ConvertTo-Json) -ContentType "application/json"
```

Reserve these devices' IPs in your router's DHCP settings, since there's no
heartbeat to track address changes for them.

### Checking devices

```powershell
Invoke-RestMethod -Uri http://<hub-host>:8080/devices -Headers @{ Authorization = "Bearer <HUB_TOKEN>" }
```

Returns every device with an `online` field computed live (recent heartbeat,
or a live TCP probe for anything else).

## API surface (all routes except `/health` require the Bearer token)

| Route | Purpose |
|---|---|
| `GET /devices` | List devices + live online status |
| `POST /devices` | Register a device |
| `GET /devices/:id`, `DELETE /devices/:id` | Inspect / remove a device |
| `POST /devices/:id/heartbeat` | Used by `heartbeat_agent.py` to report current IP |
| `POST /shell/:id/exec` | Run a one-shot command over SSH |
| `WS /shell/:id/session?token=` | Interactive terminal session |
| `GET /files/:id/list?path=` | List a directory over SFTP |
| `GET /files/:id/download?path=` | Read a file (base64 in the JSON response) |
| `POST /files/:id/upload` | Write a file (base64 in the JSON body) |
| `GET /llm/:id/models` | List models available on that device's Ollama |
| `POST /llm/:id/chat` | Chat with the model; streams via SSE unless `"stream": false` |
| `GET /system/stats` | CPU/memory/disk/network snapshot of the hub machine |
| `WS /system/stats/stream?token=` | Same stats, pushed once a second |

## Security notes

- `firewall_setup.ps1` only opens the port on Private/Domain network
  profiles, never Public. Don't rely on that alone if the hub ever
  joins an untrusted Wi-Fi network with the service running.
- The shell/file routes give whoever holds `HUB_TOKEN` full command
  execution on every registered SSH device. Don't share the token outside your own devices.