"""Tailscale CLI interactions."""

import json
import subprocess
from dataclasses import dataclass


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
