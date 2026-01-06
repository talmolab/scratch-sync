"""Command-line interface for scratch-sync."""

import re
import subprocess
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scratch_sync import syncthing, tailscale, discovery, uv

# Rich console for styled output
console = Console()

# Documentation URL
DOCS_URL = "https://scratch.tlab.sh"


def get_install_instructions() -> tuple[str, str]:
    """Get OS-appropriate install command and docs URL.

    Returns:
        Tuple of (install_command, docs_url)
    """
    if sys.platform == "win32":
        install_cmd = f"iwr -useb {DOCS_URL}/install.ps1 | iex"
    else:
        # macOS and Linux
        install_cmd = f"curl -LsSf {DOCS_URL}/install.sh | sh"
    return install_cmd, DOCS_URL


def print_install_instructions() -> None:
    """Print OS-appropriate install instructions with docs link."""
    install_cmd, docs_url = get_install_instructions()
    console.print()
    console.print("[bold]To install scratch-sync dependencies:[/]")
    console.print(f"  [cyan]{install_cmd}[/]")
    console.print()
    console.print(f"[dim]For more information, see: {docs_url}[/]")


def require_syncthing() -> None:
    """Check that Syncthing is installed, exit with helpful message if not."""
    if syncthing.find_syncthing():
        return

    console.print("[red]Error:[/] Syncthing is not installed.")
    console.print()
    console.print("[dim]scratch-sync requires Syncthing to sync folders across machines.[/]")
    print_install_instructions()
    sys.exit(1)


def require_tailscale() -> None:
    """Check that Tailscale is installed and running, exit with helpful message if not."""
    if not tailscale.find_tailscale():
        console.print("[red]Error:[/] Tailscale is not installed.")
        console.print()
        console.print("[dim]scratch-sync uses Tailscale to securely connect your machines.[/]")
        console.print("[dim]Install Tailscale from: https://tailscale.com/download[/]")
        console.print()
        _, docs_url = get_install_instructions()
        console.print(f"[dim]For more information, see: {docs_url}[/]")
        sys.exit(1)

    if not tailscale.is_tailscale_running():
        console.print("[red]Error:[/] Tailscale is not running.")
        console.print()
        console.print("[dim]Start Tailscale and ensure you're connected to your tailnet.[/]")
        sys.exit(1)

# Configure rich-click styling
click.rich_click.THEME = "nord-modern"
click.rich_click.TEXT_MARKUP = "rich"
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.HEADER_TEXT = "[bold cyan]scratch-sync[/] - Sync scratch/ folders across machines"
click.rich_click.STYLE_ERRORS_SUGGESTION = "magenta italic"
click.rich_click.ERRORS_SUGGESTION = "Try running [bold]'scratch-sync --help'[/] for more information."

# Group commands for better organization
click.rich_click.COMMAND_GROUPS = {
    "scratch-sync": [
        {
            "name": "Setup",
            "commands": ["init", "pair"],
        },
        {
            "name": "Monitoring",
            "commands": ["status", "list"],
        },
    ]
}

STIGNORE_TEMPLATE = """\
// Syncthing ignore patterns for scratch folders
// This file is NOT synced between devices

// Python
__pycache__
*.pyc
*.pyo
*.egg-info
.eggs
*.egg
.mypy_cache
.pytest_cache
.ipynb_checkpoints

// Build artifacts
*.so
*.o
*.a
build/
dist/

// Editor/IDE
*.swp
*.swo
*~
.idea/
.vscode/
*.sublime-*

// OS junk
(?d).DS_Store
(?d)Thumbs.db
(?d)desktop.ini
(?d)._*

// Temporary files
*.tmp
*.temp
*.bak
*.log
"""


def get_repo_name(path: Path | None = None) -> str | None:
    """Get the repository name from git remote or directory name."""
    if path is None:
        path = Path.cwd()

    # Try to find .git directory
    git_dir = path / ".git"
    if not git_dir.exists():
        # Walk up
        for parent in path.parents:
            git_dir = parent / ".git"
            if git_dir.exists():
                path = parent
                break
        else:
            return None

    # Try to get remote origin
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=path,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Extract repo name from URL
            # git@github.com:user/repo.git -> repo
            # https://github.com/user/repo.git -> repo
            match = re.search(r"/([^/]+?)(?:\.git)?$", url)
            if match:
                return match.group(1)
    except Exception:
        pass

    # Fall back to directory name
    return path.name


def sanitize_folder_id(name: str) -> str:
    """Sanitize a name for use as a Syncthing folder ID."""
    # Replace problematic characters
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", name.lower())
    # Remove consecutive hyphens
    sanitized = re.sub(r"-+", "-", sanitized)
    # Remove leading/trailing hyphens
    return sanitized.strip("-")


@click.group()
@click.version_option(prog_name="scratch-sync")
def main():
    """Sync private [bold cyan]scratch/[/] folders across machines using [bold]Syncthing[/] over [bold]Tailscale[/].

    [dim]scratch-sync helps you keep your local scratch directories synchronized
    across all your development machines on a private Tailscale network.[/]

    [bold]Quick start:[/]
      1. Run [cyan]scratch-sync init[/] in a git repository
      2. Run [cyan]scratch-sync pair[/] to discover other devices
      3. Repeat on your other machines
    """
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False, metavar="[PATH]")
@click.option("--name", "-n", help="Custom name for the sync folder [dim](defaults to repo name)[/]")
def init(path: Path | None, name: str | None):
    """Initialize scratch-sync in a git repository.

    Sets up a [bold cyan]scratch/[/] folder for syncing in the specified directory
    (or current directory if not specified).

    [bold]What this does:[/]
      • Creates [cyan]scratch/[/] directory if it doesn't exist
      • Adds the folder to Syncthing with ID [dim]scratch-<repo-name>[/]
      • Creates a default [dim].stignore[/] file
      • Adds [cyan]scratch/[/] to [dim].gitignore[/]
    """
    # Check syncthing is available
    require_syncthing()

    # Determine path
    if path is None:
        path = Path.cwd()

    # If we're inside a scratch/ directory, use the parent instead
    if path.name == "scratch":
        parent = path.parent
        # Check if parent looks like a repo root (has .git or .gitignore)
        if (parent / ".git").exists() or (parent / ".gitignore").exists():
            console.print(f"[dim]Detected running from inside scratch/, using parent: {parent}[/]")
            path = parent

    # Find scratch directory
    scratch_path = path / "scratch"
    if not scratch_path.exists():
        console.print(f"[cyan]Creating[/] scratch directory: [bold]{scratch_path}[/]")
        scratch_path.mkdir(parents=True)

    # Determine folder name
    if name is None:
        repo_name = get_repo_name(path)
        if repo_name:
            name = repo_name
        else:
            name = path.name

    folder_id = f"scratch-{sanitize_folder_id(name)}"

    # Check if already exists
    if syncthing.folder_exists(folder_id):
        console.print(f"[yellow]Warning:[/] Folder [cyan]{folder_id}[/] already exists in Syncthing config.")
        console.print(f"[dim]To remove: syncthing cli config folders remove --id {folder_id}[/]")
        sys.exit(1)

    # Add folder
    console.print("[bold]Adding folder to Syncthing:[/]")
    console.print(f"  [dim]ID:[/]   [cyan]{folder_id}[/]")
    console.print(f"  [dim]Path:[/] [cyan]{scratch_path.resolve()}[/]")

    if not syncthing.add_folder(folder_id, scratch_path.resolve()):
        console.print("[red]Failed to add folder[/]")
        sys.exit(1)

    # Add all known devices to this folder
    local_device_id = syncthing.get_device_id()
    for device_id in syncthing.list_devices():
        if device_id != local_device_id:
            syncthing.add_device_to_folder(folder_id, device_id)
            console.print(f"  [green]Added device:[/] [dim]{device_id[:7]}...[/]")

    # Create .stignore if it doesn't exist
    stignore_path = scratch_path / ".stignore"
    if not stignore_path.exists():
        console.print("[cyan]Creating[/] default .stignore...")
        stignore_path.write_text(STIGNORE_TEMPLATE)

    # Ensure scratch is in .gitignore
    gitignore_path = path / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if "scratch/" not in content and "/scratch" not in content:
            console.print("[cyan]Adding[/] scratch/ to .gitignore...")
            with open(gitignore_path, "a") as f:
                f.write("\n# Local scratch folder (synced via scratch-sync)\nscratch/\n")
    else:
        console.print("[cyan]Creating[/] .gitignore with scratch/...")
        gitignore_path.write_text("# Local scratch folder (synced via scratch-sync)\nscratch/\n")

    # Configure GUI binding for remote discovery
    if syncthing.is_gui_localhost_only():
        console.print()
        console.print("[cyan]Configuring[/] Syncthing for remote discovery...")
        if syncthing.set_gui_address("0.0.0.0:8384"):
            console.print("  GUI binding changed to [cyan]0.0.0.0:8384[/]")
            console.print("  [yellow]Note:[/] Restart Syncthing for this to take effect")
        else:
            console.print("  [yellow]Warning:[/] Could not configure GUI binding")
            console.print("  [dim]Run manually: syncthing cli config gui raw-address set 0.0.0.0:8384[/]")

    console.print()
    console.print("[bold green]Done![/]")
    console.print()
    console.print("[bold]Next steps:[/]")
    console.print("  1. Run [cyan]scratch-sync pair[/] to discover and pair with other devices")
    console.print("     [dim](only needed once per new machine, not for every repo)[/]")
    console.print("  2. On other devices, run [cyan]scratch-sync init[/] in the same repo")


def _print_discovery_troubleshooting(failed_peers: list) -> None:
    """Print troubleshooting tips based on discovery failures."""
    # Categorize failures
    refused = []
    timeouts = []
    other = []

    for peer, result in failed_peers:
        if result.status == discovery.DiscoveryStatus.CONNECTION_REFUSED:
            refused.append(peer)
        elif result.status == discovery.DiscoveryStatus.TIMEOUT:
            timeouts.append(peer)
        else:
            other.append(peer)

    console.print("[bold]Troubleshooting:[/]")

    if refused:
        console.print()
        console.print(f"  [yellow]Not listening[/] on {len(refused)} peer(s):")
        for peer in refused:
            console.print(f"    • {peer.hostname}")
        console.print()
        console.print("  [dim]This means port 8384 is not open. Possible causes:[/]")
        console.print("    • Syncthing not installed")
        console.print("    • Syncthing not running")
        console.print("    • Syncthing GUI bound to localhost only")
        console.print()
        console.print("  [dim]On those machines, install/start Syncthing and run:[/]")
        console.print("    [cyan]scratch-sync init[/]")

    if timeouts:
        console.print()
        console.print(f"  [dim]Timeout[/] on {len(timeouts)} peer(s):")
        for peer in timeouts:
            console.print(f"    • {peer.hostname}")
        console.print()
        console.print("  [dim]This could mean:[/]")
        console.print("    • Syncthing is not running")
        console.print("    • Firewall blocking port 8384")
        console.print("    • Network connectivity issues")

    if other and not refused and not timeouts:
        console.print()
        console.print("  • Ensure Syncthing is running on other devices")
        console.print("  • Run [cyan]scratch-sync init[/] on other devices to configure GUI binding")


@main.command()
@click.option("--timeout", "-t", default=3.0, show_default=True, help="Discovery timeout in seconds")
@click.option("--yes", "-y", is_flag=True, help="Auto-accept all discovered devices without prompting")
def pair(timeout: float, yes: bool):
    """Discover and pair with other devices on the Tailscale network.

    Scans your [bold]Tailscale[/] network for other machines running [bold]Syncthing[/]
    and automatically pairs them for folder synchronization.

    [bold]Requirements:[/]
      • Tailscale must be running and connected
      • Syncthing must be running on other devices
      • Syncthing GUI must be bound to 0.0.0.0:8384 (run [cyan]scratch-sync init[/] first)
    """
    require_tailscale()
    require_syncthing()

    console.print("[bold]Discovering Syncthing peers on Tailscale network...[/]")
    console.print()

    # Find peers
    peers = tailscale.get_online_peers()
    if not peers:
        console.print("[dim]No online peers found on Tailscale network[/]")
        return

    console.print(f"Found [bold]{len(peers)}[/] online peer(s)")
    console.print()

    # Try to discover Syncthing on each peer using the noauth endpoint
    discovered = []
    failed_peers = []  # Track failures for troubleshooting
    for peer in peers:
        console.print(f"  Checking [cyan]{peer.hostname}[/] ({peer.tailscale_ip})...", end="")
        result = discovery.discover_syncthing_peer_detailed(peer.tailscale_ip, timeout=timeout)

        if result.status == discovery.DiscoveryStatus.SUCCESS:
            console.print(" [green]found![/]")
            result.peer_info["tailscale_hostname"] = peer.hostname
            discovered.append(result.peer_info)
        elif result.status == discovery.DiscoveryStatus.CONNECTION_REFUSED:
            console.print(" [yellow]not listening[/]")
            failed_peers.append((peer, result))
        elif result.status == discovery.DiscoveryStatus.TIMEOUT:
            console.print(" [dim]timeout[/]")
            failed_peers.append((peer, result))
        else:
            console.print(" [dim]no Syncthing[/]")
            failed_peers.append((peer, result))

    if not discovered:
        console.print()
        console.print("[dim]No Syncthing peers discovered.[/]")
        console.print()
        _print_discovery_troubleshooting(failed_peers)
        return

    console.print()
    console.print(f"[bold]Discovered {len(discovered)} Syncthing peer(s):[/]")

    for info in discovered:
        hostname = info.get("hostname") or info.get("tailscale_hostname")
        console.print(f"  [cyan]•[/] {hostname} [dim]({info.get('tailscale_ip')})[/]")
        device_id = info.get("syncthing_device_id", "unknown")
        console.print(f"    [dim]Device ID: {device_id[:20]}...[/]")

    # Select which devices to pair with
    if yes:
        # Auto-accept all discovered devices
        selected = discovered
    else:
        # Interactive checkbox selection
        import questionary
        from questionary import Choice

        choices = [
            Choice(
                title=f"{info.get('hostname') or info.get('tailscale_hostname')} ({info.get('tailscale_ip')}) - {info.get('syncthing_device_id', '')[:15]}...",
                value=info,
                checked=True,  # Pre-select all by default
            )
            for info in discovered
        ]

        console.print()
        selected = questionary.checkbox(
            "Select devices to pair with:",
            choices=choices,
            instruction="(↑↓ navigate, Space toggle, a toggle all, Enter confirm)",
        ).ask()

        if selected is None:
            # User cancelled (Ctrl+C or Escape)
            console.print("[yellow]Cancelled[/]")
            return

        if not selected:
            console.print("[yellow]No devices selected[/]")
            return

    # Pair with selected devices
    paired_device_ids = []
    for info in selected:
        hostname = info.get("hostname") or info.get("tailscale_hostname")
        if discovery.auto_pair_with_peer(info):
            console.print(f"  [green]Paired with {hostname}[/]")
            paired_device_ids.append(info.get("syncthing_device_id"))
        else:
            console.print(f"  [red]Failed to pair with {hostname}[/]")

    # Add newly paired devices to all existing scratch folders
    if paired_device_ids:
        folders = syncthing.list_folders()
        scratch_folders = [f for f in folders if f.startswith("scratch-")]

        if scratch_folders:
            console.print()
            console.print("[bold]Adding devices to scratch folders...[/]")
            for folder_id in scratch_folders:
                for device_id in paired_device_ids:
                    if device_id:
                        syncthing.add_device_to_folder(folder_id, device_id)
                console.print(f"  [green]Updated {folder_id}[/]")

    console.print()
    console.print("[bold green]Done![/] Devices are now paired.")
    console.print("[dim]Folders will sync automatically when both devices have the same folder ID.[/]")


def _get_state_style(state: str) -> str:
    """Get rich style for a sync state."""
    state_styles = {
        "idle": "green",
        "scanning": "yellow",
        "syncing": "cyan",
        "error": "red",
        "unknown": "dim",
    }
    return state_styles.get(state, "dim")


def _format_bytes(b: int) -> str:
    """Format bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def _format_time(iso_time: str) -> str:
    """Format ISO time to relative."""
    from datetime import datetime

    if not iso_time or iso_time.startswith("1969") or iso_time.startswith("0001"):
        return "never"
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        diff = now - dt
        if diff.days > 0:
            return f"{diff.days}d ago"
        elif diff.seconds > 3600:
            return f"{diff.seconds // 3600}h ago"
        elif diff.seconds > 60:
            return f"{diff.seconds // 60}m ago"
        else:
            return "just now"
    except Exception:
        return iso_time[:19] if len(iso_time) > 19 else iso_time


def _format_uptime(seconds: int) -> str:
    """Format uptime in seconds to human readable."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h" if hours else f"{days}d"


@main.command()
def status():
    """Show current sync status.

    Displays information about:
      • Dependency status (uv, Tailscale, Syncthing)
      • Your device ID and Syncthing version
      • Paired devices and their connection status
      • All [cyan]scratch-*[/] folders and their sync state
    """
    # === Dependencies Section ===
    console.print("[bold]Dependencies[/]")
    console.print()

    dep_table = Table(box=None, padding=(0, 2), show_header=False)
    dep_table.add_column("Tool", style="cyan")
    dep_table.add_column("Status")
    dep_table.add_column("Details", style="dim")

    # --- uv ---
    uv_path = uv.find_uv()
    if uv_path:
        uv_version = uv.get_uv_version()
        dep_table.add_row(
            "uv",
            f"[green]installed[/] {uv_version or ''}",
            uv_path,
        )
    else:
        dep_table.add_row("uv", "[red]not found[/]", "")

    # --- Tailscale ---
    ts_path = tailscale.find_tailscale()
    if ts_path:
        ts_version = tailscale.get_tailscale_version()
        ts_running = tailscale.is_tailscale_running()
        ts_info = tailscale.get_tailnet_info()

        if ts_running and ts_info:
            status_parts = [f"[green]running[/] {ts_version or ''}"]
            details_parts = []
            if ts_info.tailnet_name:
                details_parts.append(ts_info.tailnet_name)
            if ts_info.user_login:
                details_parts.append(ts_info.user_login)
            dep_table.add_row("tailscale", " ".join(status_parts), " / ".join(details_parts) if details_parts else "")
        elif ts_running:
            dep_table.add_row("tailscale", f"[green]running[/] {ts_version or ''}", "")
        else:
            dep_table.add_row("tailscale", f"[yellow]not running[/] {ts_version or ''}", ts_path)
    else:
        dep_table.add_row("tailscale", "[red]not found[/]", "")

    # --- Syncthing ---
    st_path = syncthing.find_syncthing()
    if st_path:
        st_running = syncthing.is_syncthing_running()
        st_version = syncthing.get_syncthing_version()
        st_service = syncthing.get_service_status()

        if st_running:
            status_str = f"[green]running[/] {st_version or ''}"
        else:
            status_str = f"[yellow]not running[/] {st_version or ''}"

        details_parts = [st_path]
        if st_service.get("method"):
            method = st_service["method"]
            enabled = st_service.get("enabled")
            if enabled:
                details_parts.append(f"autostart: {method}")
            else:
                details_parts.append(f"autostart: {method} (disabled)")

        dep_table.add_row("syncthing", status_str, " / ".join(details_parts))
    else:
        dep_table.add_row("syncthing", "[red]not found[/]", "")

    console.print(dep_table)

    # Exit early if Syncthing is not available
    if not st_path:
        console.print()
        console.print("[red]Error:[/] Syncthing is not installed.")
        console.print()
        console.print("[dim]scratch-sync requires Syncthing to sync folders across machines.[/]")
        print_install_instructions()
        sys.exit(1)

    if not syncthing.is_syncthing_running():
        console.print()
        console.print("[yellow]Warning:[/] Syncthing is not running. Start it to see sync status.")
        console.print()

        # Provide helpful restart instructions based on service configuration
        service_status = syncthing.get_service_status()
        method = service_status.get("method")

        if sys.platform == "darwin":
            if method == "launchd":
                plist_path = "~/Library/LaunchAgents/syncthing.plist"
                if service_status.get("enabled"):
                    console.print("[dim]To restart Syncthing:[/]")
                    console.print(f"  [cyan]launchctl kickstart -k gui/$(id -u)/syncthing[/]")
                else:
                    console.print("[dim]To load and start Syncthing:[/]")
                    console.print(f"  [cyan]launchctl load {plist_path}[/]")
            elif method == "homebrew":
                console.print("[dim]To start Syncthing:[/]")
                console.print("  [cyan]brew services start syncthing[/]")
            else:
                console.print("[dim]To start Syncthing manually:[/]")
                console.print("  [cyan]syncthing serve --no-browser &[/]")
                console.print()
                console.print("[dim]To enable autostart, run:[/]")
                console.print("  [cyan]scratch-sync init[/]")

        elif sys.platform == "linux":
            if method == "systemd":
                console.print("[dim]To start Syncthing:[/]")
                console.print("  [cyan]systemctl --user start syncthing[/]")
            else:
                console.print("[dim]To start Syncthing manually:[/]")
                console.print("  [cyan]syncthing serve --no-browser &[/]")
                console.print()
                console.print("[dim]To enable autostart, run:[/]")
                console.print("  [cyan]scratch-sync init[/]")

        elif sys.platform == "win32":
            if method == "task_scheduler":
                console.print("[dim]To start Syncthing:[/]")
                console.print("  [cyan]schtasks /Run /TN Syncthing[/]")
            else:
                console.print("[dim]To start Syncthing manually:[/]")
                console.print("  [cyan]syncthing serve --no-browser[/]")
                console.print()
                console.print("[dim]To enable autostart, run:[/]")
                console.print("  [cyan]scratch-sync init[/]")

        else:
            # Fallback for other platforms
            console.print("[dim]To start Syncthing manually:[/]")
            console.print("  [cyan]syncthing serve --no-browser &[/]")

        return

    # === This Device Section ===
    console.print()
    system_status = syncthing.get_system_status()

    if system_status:
        device_id = system_status.get("myID", "unknown")
        uptime_secs = system_status.get("uptime", 0)

        # Get dashboard URL
        gui_address = syncthing.get_gui_address() or "127.0.0.1:8384"
        # Normalize to localhost for display
        if gui_address.startswith("0.0.0.0:"):
            gui_address = "127.0.0.1:" + gui_address.split(":")[1]
        dashboard_url = f"http://{gui_address}/"

        console.print(Panel(
            f"[cyan]Device ID:[/]  {device_id}\n"
            f"[cyan]Uptime:[/]     {_format_uptime(uptime_secs)}\n"
            f"[cyan]Dashboard:[/]  [link={dashboard_url}]{dashboard_url}[/link]",
            title="This Device",
            border_style="blue",
        ))
    else:
        # Fall back to CLI-based device ID
        try:
            device_id = syncthing.get_device_id()
            console.print(f"[bold]Device ID:[/] [dim]{device_id}[/]")
        except Exception as e:
            console.print(f"[red]Error getting device ID:[/] {e}")
            device_id = None

    # Get devices with full info from REST API
    config_devices = syncthing.get_config_devices()
    connections = syncthing.get_connections()
    device_stats = syncthing.get_device_stats()

    # Filter out self
    my_id = system_status.get("myID", "") if system_status else (device_id or "")
    other_devices = [d for d in config_devices if d.get("deviceID") != my_id]

    console.print()
    console.print(f"[bold]Paired Devices ({len(other_devices)})[/]")

    if other_devices:
        device_table = Table(box=None, padding=(0, 2))
        device_table.add_column("Name")
        device_table.add_column("Device ID", style="dim")
        device_table.add_column("Status")
        device_table.add_column("Last Seen")
        device_table.add_column("Transfer")

        conn_info = connections.get("connections", {})

        for device in other_devices:
            dev_id = device.get("deviceID", "")
            name = device.get("name") or "unknown"

            # Connection status
            conn = conn_info.get(dev_id, {})
            if conn.get("connected"):
                status_str = "[green]connected[/]"
            elif conn.get("paused"):
                status_str = "[yellow]paused[/]"
            else:
                status_str = "[red]disconnected[/]"

            # Stats
            stats = device_stats.get(dev_id, {})
            last_seen = _format_time(stats.get("lastSeen", ""))

            # Transfer totals
            in_bytes = conn.get("inBytesTotal", 0)
            out_bytes = conn.get("outBytesTotal", 0)
            if in_bytes or out_bytes:
                transfer = f"[dim]{_format_bytes(in_bytes)}[/] / [dim]{_format_bytes(out_bytes)}[/]"
            else:
                transfer = "[dim]-[/]"

            device_table.add_row(
                name,
                f"{dev_id[:15]}...",
                status_str,
                last_seen,
                transfer,
            )

        console.print(device_table)
    else:
        console.print("[dim]No devices paired yet. Run: scratch-sync pair[/]")

    # Get folders with full info
    config_folders = syncthing.get_config_folders()
    scratch_folders = [f for f in config_folders if f.get("id", "").startswith("scratch-")]

    console.print()
    console.print(f"[bold]Scratch Folders ({len(scratch_folders)})[/]")

    if scratch_folders:
        folder_table = Table(box=None, padding=(0, 2))
        folder_table.add_column("Folder ID", style="cyan")
        folder_table.add_column("Path")
        folder_table.add_column("Status")
        folder_table.add_column("Shared With")

        for folder in scratch_folders:
            folder_id = folder.get("id", "unknown")
            path = folder.get("path", "")

            # Get folder status
            folder_status = syncthing.get_folder_status(folder_id)
            if folder_status:
                state = folder_status.get("state", "unknown")
                style = _get_state_style(state)
                status_str = f"[{style}]{state}[/]"
            else:
                status_str = "[dim]unknown[/]"

            # Get devices this folder is shared with
            shared_devices = folder.get("devices", [])
            shared_names = []
            for sd in shared_devices:
                sd_id = sd.get("deviceID", "")
                if sd_id == my_id:
                    continue
                # Find device name
                for d in config_devices:
                    if d.get("deviceID") == sd_id:
                        shared_names.append(d.get("name") or sd_id[:8])
                        break

            # Truncate path if too long
            display_path = path if len(path) <= 35 else "..." + path[-32:]

            folder_table.add_row(
                folder_id,
                f"[dim]{display_path}[/]",
                status_str,
                ", ".join(shared_names) if shared_names else "[dim]none[/]",
            )

        console.print(folder_table)
    else:
        console.print("[dim]No scratch folders configured. Run: scratch-sync init[/]")

    # Check for pending device requests
    pending = syncthing.get_pending_devices()
    if pending:
        console.print()
        console.print(f"[bold yellow]Pending Pair Requests ({len(pending)})[/]")
        for dev_id, info in pending.items():
            name = info.get("name", "unknown")
            console.print(f"  [yellow]•[/] {name} ({dev_id[:20]}...)")


@main.command("list")
def list_folders():
    """List all scratch-sync managed folders.

    Shows all Syncthing folders with IDs starting with [cyan]scratch-[/].
    """
    require_syncthing()

    folders = syncthing.list_folders()
    scratch_folders = [f for f in folders if f.startswith("scratch-")]

    if not scratch_folders:
        console.print("[dim]No scratch-sync folders configured[/]")
        return

    console.print("[bold]Scratch folders:[/]")
    for folder_id in scratch_folders:
        console.print(f"  [cyan]•[/] {folder_id}")



if __name__ == "__main__":
    main()
