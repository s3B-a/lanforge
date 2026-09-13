"""Key generation + provisioning helper for devices this hub SSHes into.

Uses the same venv as backend/ (paramiko + cryptography are already pulled
in by backend/requirements.txt). Run it from the project root:

    ..\\.venv\\Scripts\\python.exe ssh\\ssh_manager.py <command> ...
      (or, from the project root: .venv\\Scripts\\python.exe ssh\\ssh_manager.py ...)

Commands:
    generate <device-id> [--force]
        Create a new ed25519 keypair at ssh/keys/<device-id>(.pub).

    deploy <device-id> --host H --user U [--port 22] [--remote-os auto|linux|windows-user|windows-admin]
        Copy the generated public key into the remote account's
        authorized_keys over SSH (password auth, prompted once).

    register <device-id> --hub-url URL --token TOKEN --host H --ssh-user U
              [--name NAME] [--ssh-port 22] [--ollama-port PORT]
        Register the device with the hub's API using this key.

    list
        List locally managed keypairs.

    remove <device-id> [--force]
        Delete the local keypair. Does not touch the remote authorized_keys
        file; remove the line there yourself if you're retiring the device.
"""

import argparse
import getpass
import json
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEYS_DIR = PROJECT_ROOT / "ssh" / "keys"


def _lock_down_private_key(path: Path) -> None:
    """POSIX chmod is a no-op on Windows access control; OpenSSH on Windows
    checks ACLs instead and refuses a key that's readable by other accounts."""
    path.chmod(0o600)
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r"],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["icacls", str(path), "/grant:r", f"{getpass.getuser()}:(R)"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"warning: could not lock down ACLs on {path}: {exc.stderr}", file=sys.stderr)


def cmd_generate(args: argparse.Namespace) -> None:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv_path = KEYS_DIR / args.device_id
    pub_path = KEYS_DIR / f"{args.device_id}.pub"

    if priv_path.exists() and not args.force:
        print(f"error: {priv_path} already exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)

    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )

    priv_path.write_bytes(private_bytes)
    pub_path.write_text(f"{public_bytes.decode()} {args.device_id}@localhub\n")
    _lock_down_private_key(priv_path)

    print(f"Generated {priv_path} and {pub_path}")
    print(f"Public key: {public_bytes.decode()} {args.device_id}@localhub")


def _load_public_key(device_id: str) -> str:
    pub_path = KEYS_DIR / f"{device_id}.pub"
    if not pub_path.exists():
        print(f"error: no keypair for '{device_id}', run 'generate {device_id}' first", file=sys.stderr)
        sys.exit(1)
    return pub_path.read_text().strip()


def _probe_remote_os(client: paramiko.SSHClient) -> str:
    _, stdout, _ = client.exec_command("uname -s")
    if stdout.channel.recv_exit_status() == 0:
        return "linux"
    return "windows-user"


_LINUX_DEPLOY_SCRIPT = """
set -e
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
if ! grep -qF "{key}" ~/.ssh/authorized_keys; then
    echo "{key}" >> ~/.ssh/authorized_keys
fi
chmod 600 ~/.ssh/authorized_keys
"""

_WINDOWS_USER_DEPLOY_SCRIPT = """
$ErrorActionPreference = "Stop"
$dir = Join-Path $env:USERPROFILE ".ssh"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$authFile = Join-Path $dir "authorized_keys"
if (-not (Test-Path $authFile)) {{ New-Item -ItemType File -Path $authFile | Out-Null }}
$key = @'
{key}
'@
if (-not (Select-String -Path $authFile -SimpleMatch $key -Quiet)) {{
    Add-Content -Path $authFile -Value $key -Encoding ascii
}}
"""

_WINDOWS_ADMIN_DEPLOY_SCRIPT = """
$ErrorActionPreference = "Stop"
$path = Join-Path $env:ProgramData "ssh\\administrators_authorized_keys"
if (-not (Test-Path $path)) {{ New-Item -ItemType File -Path $path -Force | Out-Null }}
$key = @'
{key}
'@
if (-not (Select-String -Path $path -SimpleMatch $key -Quiet)) {{
    Add-Content -Path $path -Value $key -Encoding ascii
}}
icacls $path /inheritance:r | Out-Null
icacls $path /grant "SYSTEM:(F)" | Out-Null
icacls $path /grant "Administrators:(F)" | Out-Null
"""


def cmd_deploy(args: argparse.Namespace) -> None:
    public_key = _load_public_key(args.device_id)
    password = args.password or getpass.getpass(f"Password for {args.user}@{args.host}: ")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=args.host, port=args.port, username=args.user, password=password, timeout=10
    )

    try:
        remote_os = args.remote_os
        if remote_os == "auto":
            remote_os = _probe_remote_os(client)
            print(f"Detected remote OS: {remote_os}")

        script = {
            "linux": _LINUX_DEPLOY_SCRIPT,
            "windows-user": _WINDOWS_USER_DEPLOY_SCRIPT,
            "windows-admin": _WINDOWS_ADMIN_DEPLOY_SCRIPT,
        }[remote_os].format(key=public_key)

        if remote_os == "linux":
            stdin, stdout, stderr = client.exec_command(f"bash -s <<'SCRIPT'\n{script}\nSCRIPT")
        else:
            stdin, stdout, stderr = client.exec_command("powershell -NoProfile -NonInteractive -Command -")
            stdin.write(script)
            stdin.close()

        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            print(f"error: remote deploy script failed (exit {exit_code})", file=sys.stderr)
            print(stderr.read().decode(errors="replace"), file=sys.stderr)
            sys.exit(1)
    finally:
        client.close()

    print(f"Public key for '{args.device_id}' installed on {args.user}@{args.host}.")


def cmd_register(args: argparse.Namespace) -> None:
    if not (KEYS_DIR / f"{args.device_id}.pub").exists():
        print(f"error: no keypair for '{args.device_id}', run 'generate {args.device_id}' first", file=sys.stderr)
        sys.exit(1)

    payload = {
        "id": args.device_id,
        "name": args.name or args.device_id,
        "kind": "ssh",
        "host": args.host,
        "ssh_port": args.ssh_port,
        "ssh_user": args.ssh_user,
        "ssh_key_path": f"ssh/keys/{args.device_id}",
    }
    if args.ollama_port:
        payload["ollama_port"] = args.ollama_port

    _hub_request(args.hub_url, "/devices", "POST", args.token, payload)

def _hub_request(hub_url: str, path: str, method: str, token: str, payload: dict) -> None:
    request = urllib.request.Request(
        f"{hub_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            print(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"error: hub returned {exc.code}: {exc.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

def cmd_update(args: argparse.Namespace) -> None:
    fields = {
        "name": args.name,
        "host": args.host,
        "ssh_port": args.ssh_port,
        "ssh_user": args.ssh_user,
        "ollama_port": args.ollama_port,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        print("error: give at least one field to update (--name/--host/--ssh-port/--ssh-user/--ollama-port)", file=sys.stderr)
        sys.exit(1)

    _hub_request(args.hub_url, f"/devices/{args.device_id}", "PATCH", args.token, fields)

def cmd_list(args: argparse.Namespace) -> None:
    if not KEYS_DIR.exists():
        print("No keys generated yet.")
        return
    for pub_path in sorted(KEYS_DIR.glob("*.pub")):
        device_id = pub_path.stem
        priv_ok = (KEYS_DIR / device_id).exists()
        print(f"{device_id}{'' if priv_ok else '  (missing private key!)'}")


def cmd_remove(args: argparse.Namespace) -> None:
    priv_path = KEYS_DIR / args.device_id
    pub_path = KEYS_DIR / f"{args.device_id}.pub"

    if not priv_path.exists() and not pub_path.exists():
        print(f"error: no keypair for '{args.device_id}'", file=sys.stderr)
        sys.exit(1)

    if not args.force:
        confirm = input(f"Delete local keypair for '{args.device_id}'? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Cancelled.")
            return

    priv_path.unlink(missing_ok=True)
    pub_path.unlink(missing_ok=True)
    print(f"Removed local keypair for '{args.device_id}'.")
    print("Remember to remove the matching line from that device's authorized_keys file too.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="create a new ed25519 keypair")
    p.add_argument("device_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("deploy", help="install the public key on a remote device")
    p.add_argument("device_id")
    p.add_argument("--host", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--password", help="omit to be prompted (safer than passing it on the command line)")
    p.add_argument(
        "--remote-os",
        choices=["auto", "linux", "windows-user", "windows-admin"],
        default="auto",
        help="'windows-admin' is for an account in the Administrators group (uses administrators_authorized_keys)",
    )
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("register", help="register the device with the hub API")
    p.add_argument("device_id")
    p.add_argument("--hub-url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--host", required=True, help="hostname/IP the hub falls back to before any heartbeat arrives")
    p.add_argument("--ssh-user", required=True)
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--name")
    p.add_argument("--ollama-port", type=int)
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("update", help="patch fields on an already-registered device")
    p.add_argument("device_id")
    p.add_argument("--hub-url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--host", help="e.g. to correct the fallback hostname")
    p.add_argument("--ssh-user")
    p.add_argument("--ssh-port", type=int)
    p.add_argument("--name")
    p.add_argument("--ollama-port", type=int, help="add this once you've installed an LLM on an already-registered device")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("list", help="list locally managed keypairs")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("remove", help="delete a local keypair")
    p.add_argument("device_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
