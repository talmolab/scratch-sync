"""Tailscale CLI interactions."""

import json
import shutil
import subprocess
from dataclasses import dataclass


def find_tailscale() -> str | None:
    """Find tailscale binary in PATH."""
    return shutil.which("tailscale")


def get_tailscale_version() -> str | None:
    """Get the Tailscale version string."""
    try:
        result = subprocess.run(
            ["tailscale", "version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Output is like "1.76.6\n  tailscale commit: ..."
            version_line = result.stdout.strip().split("\n")[0]
            return version_line.strip()
    except FileNotFoundError:
        pass
    return None


@dataclass
class TailnetInfo:
    """Information about the current Tailscale connection."""

    tailnet_name: str | None
    user_login: str | None
    user_name: str | None
    dns_name: str | None
    hostname: str | None
    backend_state: str | None


def get_tailnet_info() -> TailnetInfo | None:
    """Get information about the current Tailscale tailnet and user."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        self_info = data.get("Self", {})
        user_info = data.get("User", {})
        current_tailnet = data.get("CurrentTailnet", {})

        # Get user info from the User dict using Self's UserID
        user_id = str(self_info.get("UserID", ""))
        user_data = user_info.get(user_id, {})

        return TailnetInfo(
            tailnet_name=current_tailnet.get("Name"),
            user_login=user_data.get("LoginName"),
            user_name=user_data.get("DisplayName"),
            dns_name=self_info.get("DNSName", "").rstrip("."),
            hostname=self_info.get("HostName"),
            backend_state=data.get("BackendState"),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@dataclass
class TailscalePeer:
    """A peer on the Tailscale network."""

    hostname: str
    tailscale_ip: str
    os: str
    online: bool
    node_id: int | None = None


def is_tailscale_running() -> bool:
    """Check if Tailscale is running."""
    try:
        result = subprocess.run(
            ["tailscale", "status"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_tailscale_ip() -> str | None:
    """Get the local Tailscale IP address."""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def get_hostname() -> str | None:
    """Get the local Tailscale hostname."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("Self", {}).get("HostName")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def get_online_peers() -> list[TailscalePeer]:
    """Get all online peers on the Tailscale network."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        peers = []

        for peer in data.get("Peer", {}).values():
            if peer.get("Online"):
                peers.append(
                    TailscalePeer(
                        hostname=peer.get("HostName", "unknown"),
                        tailscale_ip=peer.get("TailscaleIPs", [None])[0],
                        os=peer.get("OS", "unknown"),
                        online=True,
                        node_id=peer.get("ID"),
                    )
                )

        return peers

    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_all_peers() -> list[TailscalePeer]:
    """Get all peers on the Tailscale network (including offline)."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        peers = []

        for peer in data.get("Peer", {}).values():
            peers.append(
                TailscalePeer(
                    hostname=peer.get("HostName", "unknown"),
                    tailscale_ip=peer.get("TailscaleIPs", [None])[0],
                    os=peer.get("OS", "unknown"),
                    online=peer.get("Online", False),
                    node_id=peer.get("ID"),
                )
            )

        return peers

    except (FileNotFoundError, json.JSONDecodeError):
        return []
