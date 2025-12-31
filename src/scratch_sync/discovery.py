"""Device discovery using Syncthing's REST API.

Uses Syncthing's noauth endpoint to discover device IDs without requiring
SSH access, API keys, or a custom discovery server.
"""

import httpx

from scratch_sync import syncthing


def discover_syncthing_peer(ip: str, port: int = 8384, timeout: float = 3.0) -> dict | None:
    """
    Discover Syncthing device ID from a peer using the noauth endpoint.

    The X-Syncthing-Id header is returned on all HTTP responses from Syncthing,
    including unauthenticated endpoints like /rest/noauth/health.

    Args:
        ip: The IP address of the peer (e.g., Tailscale IP)
        port: Syncthing GUI port (default 8384)
        timeout: Request timeout in seconds

    Returns:
        Dictionary with peer info or None if not reachable
    """
    url = f"http://{ip}:{port}/rest/noauth/health"

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)

            if response.status_code == 200:
                device_id = response.headers.get("X-Syncthing-Id")
                version = response.headers.get("X-Syncthing-Version", "unknown")

                if device_id:
                    return {
                        "hostname": None,  # Will be filled from Tailscale
                        "tailscale_ip": ip,
                        "syncthing_device_id": device_id,
                        "syncthing_version": version,
                        "syncthing_port": 22000,  # Data sync port
                    }
    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    except Exception:
        pass

    return None


def auto_pair_with_peer(peer_info: dict) -> bool:
    """
    Automatically pair with a discovered peer.

    Adds the peer's device to local Syncthing config and sets
    the Tailscale IP as the connection address.

    Args:
        peer_info: Dictionary with peer information from discover_syncthing_peer()

    Returns:
        True if pairing succeeded
    """
    device_id = peer_info.get("syncthing_device_id")
    ip = peer_info.get("tailscale_ip")
    hostname = peer_info.get("hostname") or peer_info.get("tailscale_hostname")
    port = peer_info.get("syncthing_port", 22000)

    if not device_id or not ip:
        return False

    # Check if already added
    existing_devices = syncthing.list_devices()
    if device_id in existing_devices:
        # Just update address
        syncthing.set_device_address(device_id, f"tcp://{ip}:{port}")
        return True

    # Add new device
    if not syncthing.add_device(device_id, hostname):
        return False

    # Set Tailscale address
    syncthing.set_device_address(device_id, f"tcp://{ip}:{port}")

    return True
