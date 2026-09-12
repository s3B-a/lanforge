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

1. Enable an SSH server on it if it doesn't have one yet, then make sure you
   can already SSH into it manually once to confirm it's running and reachable:
   - Windows 11: `Settings > Apps > Optional Features > Add a feature >
     OpenSSH Server`, then
     `Start-Service sshd; Set-Service -Name sshd -StartupType Automatic`.
   - Linux: `sudo systemctl enable --now sshd` (package name varies by
     distro, e.g. `openssh-server` on Debian/Ubuntu).

   Nothing else needs to run for shell/file access; SSH itself is enough.

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

   If this device is running the LLM: Ollama binds to `127.0.0.1` only by
   default, so the hub (a different machine) can't reach it until you point
   it at the LAN interface instead, then restart Ollama:
   ```powershell
   setx OLLAMA_HOST "0.0.0.0:11434"
   ```

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

### Installing with the LLM rig

This repo doesn't ship a model, it proxies to whatever Ollama instance
the LLM rig is running. To put a model on that machine (for our example:
[qwen38-uncensored](https://github.com/Wassimyounes01/qwen38-uncensored)):

1. Prerequisites on the rig: an NVIDIA GPU (24GB VRAM for the default
   `Q4_K_M` quant, 12GB works with `--quant=Q3_K_M`), [Node.js](https://nodejs.org/),
   and [Ollama](https://ollama.com/download) 0.17.1+.
2. Install it:
   ```powershell
   git clone https://github.com/Wassimyounes01/qwen38-uncensored.git
   cd qwen38-uncensored
   node bin/install.cjs
   ```
   Add `--quant=Q3_K_M` or `--quant=IQ4_XS` to use a smaller quant on a
   lower-VRAM GPU. This downloads 15-20GB of weights, so make sure there's
   disk space free.
3. Test it locally on the rig before involving the hub at all:
   ```powershell
   ollama run --think=false qwen3.8:27b-uncensored
   ```
   Run `ollama list` if you need the exact tag it installed under.
4. Point Ollama at the LAN interface instead of just `127.0.0.1`, then
   restart it so the change takes effect:
   ```powershell
   setx OLLAMA_HOST "0.0.0.0:11434"
   ```
   Open the port on the rig's firewall the same way you did for the hub
   itself:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\firewall_setup.ps1 -Port 11434
   ```
   Then tell the hub about the Ollama port, one of two ways depending on
   whether this device is already registered:
   - **Not registered yet:** run the full SSH walkthrough above, including
     `--ollama-port 11434` on the `register` step from the start.
   - **Already registered** (you set up SSH access before installing the
     LLM): patch the existing entry instead, no need to delete/re-add it:
     ```powershell
     .venv\Scripts\python.exe ssh\ssh_manager.py update llm-rig `
         --hub-url http://<hub-host>:8080 --token <HUB_TOKEN> --ollama-port 11434
     ```
     `update` PATCHes `/devices/:id`, merging in whatever fields you pass
     (`--host`, `--ssh-user`, `--ssh-port`, `--name`, `--ollama-port`)
     without touching the rest of the device's entry. `register` can't be
     reused here, the hub rejects registering an ID that already exists.
5. From the hub: `POST /llm/<device-id>/chat` with
   `{"model": "qwen3.8:27b-uncensored", "messages": [...]}` (see the API
   table below).

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
| `PATCH /devices/:id` | Merge fields into an existing device (used by `ssh_manager.py update`) |
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