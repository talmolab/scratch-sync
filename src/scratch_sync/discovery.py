"""Device discovery using Syncthing's REST API.

Uses Syncthing's noauth endpoint to discover device IDs without requiring
SSH access, API keys, or a custom discovery server.
"""

from dataclasses import dataclass
from enum import Enum

import httpx

from scratch_sync import syncthing


class DiscoveryStatus(Enum):
    """Status of a Syncthing discovery attempt."""

    SUCCESS = "success"
    CONNECTION_REFUSED = "connection_refused"  # Port not listening
    TIMEOUT = "timeout"  # Host unreachable or too slow
    NO_SYNCTHING_HEADER = "no_syncthing_header"  # HTTP response but no Syncthing
    HTTP_ERROR = "http_error"  # Non-200 response
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class DiscoveryResult:
    """Result of a Syncthing discovery attempt."""

    status: DiscoveryStatus
    peer_info: dict | None = None
    error_message: str | None = None


def discover_syncthing_peer_detailed(
    ip: str, port: int = 8384, timeout: float = 3.0
) -> DiscoveryResult:
    """
    Discover Syncthing device ID from a peer with detailed error reporting.

    Args:
        ip: The IP address of the peer (e.g., Tailscale IP)
        port: Syncthing GUI port (default 8384)
        timeout: Request timeout in seconds

    Returns:
        DiscoveryResult with status and peer info or error details
    """
    url = f"http://{ip}:{port}/rest/noauth/health"

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)

            if response.status_code == 200:
                device_id = response.headers.get("X-Syncthing-Id")
                version = response.headers.get("X-Syncthing-Version", "unknown")

                if device_id:
                    return DiscoveryResult(
                        status=DiscoveryStatus.SUCCESS,
                        peer_info={
                            "hostname": None,
                            "tailscale_ip": ip,
                            "syncthing_device_id": device_id,
                            "syncthing_version": version,
                            "syncthing_port": 22000,
                        },
                    )
                else:
                    return DiscoveryResult(
                        status=DiscoveryStatus.NO_SYNCTHING_HEADER,
                        error_message="HTTP response received but no X-Syncthing-Id header",
                    )
            else:
                return DiscoveryResult(
                    status=DiscoveryStatus.HTTP_ERROR,
                    error_message=f"HTTP {response.status_code}",
                )

    except httpx.ConnectError as e:
        error_str = str(e).lower()
        if "refused" in error_str or "connection refused" in error_str:
            return DiscoveryResult(
                status=DiscoveryStatus.CONNECTION_REFUSED,
                error_message="Connection refused - Syncthing GUI not listening on this address",
            )
        else:
            return DiscoveryResult(
                status=DiscoveryStatus.UNKNOWN_ERROR,
                error_message=f"Connection error: {e}",
            )
    except httpx.TimeoutException:
        return DiscoveryResult(
            status=DiscoveryStatus.TIMEOUT,
            error_message="Connection timed out",
        )
    except Exception as e:
        return DiscoveryResult(
            status=DiscoveryStatus.UNKNOWN_ERROR,
            error_message=str(e),
        )


def discover_syncthing_peer(ip: str, port: int = 8384, timeout: float = 3.0) -> dict | None:
    """
    Discover Syncthing device ID from a peer using the noauth endpoint.

    This is a simplified wrapper around discover_syncthing_peer_detailed()
    that returns just the peer info or None.

    Args:
        ip: The IP address of the peer (e.g., Tailscale IP)
        port: Syncthing GUI port (default 8384)
        timeout: Request timeout in seconds

    Returns:
        Dictionary with peer info or None if not reachable
    """
    result = discover_syncthing_peer_detailed(ip, port, timeout)
    return result.peer_info


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
