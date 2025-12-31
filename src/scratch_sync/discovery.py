"""Device discovery for auto-pairing."""

import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx

from scratch_sync import syncthing, tailscale

DISCOVERY_PORT = 8385


class DiscoveryHandler(BaseHTTPRequestHandler):
    """HTTP handler for device discovery."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/info":
            self.send_info()
        else:
            self.send_error(404)

    def send_info(self):
        """Send device info for discovery."""
        # Only respond to Tailscale IPs (100.x.y.z)
        client_ip = self.client_address[0]
        if not client_ip.startswith("100."):
            self.send_error(403, "Forbidden: not a Tailscale IP")
            return

        try:
            device_id = syncthing.get_device_id()
            hostname = tailscale.get_hostname() or socket.gethostname()

            info = {
                "hostname": hostname,
                "syncthing_device_id": device_id,
                "syncthing_port": 22000,
                "version": "0.1.0",
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(info).encode())

        except Exception as e:
            self.send_error(500, str(e))


def start_discovery_server(port: int = DISCOVERY_PORT) -> HTTPServer:
    """Start the discovery server in a background thread."""
    server = HTTPServer(("0.0.0.0", port), DiscoveryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def discover_peer(ip: str, port: int = DISCOVERY_PORT, timeout: float = 2.0) -> dict | None:
    """Try to discover a peer at the given IP."""
    try:
        response = httpx.get(
            f"http://{ip}:{port}/info",
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def discover_all_peers(timeout: float = 2.0) -> list[dict]:
    """Discover all online peers running scratch-sync."""
    peers = tailscale.get_online_peers()
    discovered = []

    for peer in peers:
        if peer.tailscale_ip:
            info = discover_peer(peer.tailscale_ip, timeout=timeout)
            if info:
                info["tailscale_ip"] = peer.tailscale_ip
                info["tailscale_hostname"] = peer.hostname
                info["os"] = peer.os
                discovered.append(info)

    return discovered


def auto_pair_with_peer(peer_info: dict) -> bool:
    """Automatically pair with a discovered peer."""
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
