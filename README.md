# scratch-sync

Sync private `scratch/` folders across multiple machines using Syncthing over Tailscale.

## The Problem

Working across multiple machines (Linux workstation, Mac laptop, Windows desktop) with code repositories in different locations:

| Machine | Example Repo Paths |
|---------|-------------------|
| Linux   | `~/code/sleap-io`, `~/repo1` |
| Mac     | `~/sleap-io`, `~/code/my-repo` |
| Windows | `D:\sleap-io`, `C:\Users\me\code\repo1` |

Each repo has a `scratch/` subfolder that's `.gitignore`d — notes, experiments, temp files, WIP that shouldn't be in version control but should sync privately across machines.

## Solution

- Sync `scratch/` folders without git
- Single CLI command to add folders to sync
- Works across Linux, macOS, and Windows
- Uses Tailscale for secure direct connections (no cloud relay)
- Minimal ongoing maintenance

## Quick Start

### Prerequisites

- [Tailscale](https://tailscale.com/) installed and connected on all machines
- All machines on the same Tailnet

### Install

**macOS / Linux:**
```bash
curl -LsSf https://scratch.tlab.sh/install.sh | sh
```

**Windows (PowerShell):**
```powershell
iwr -useb https://scratch.tlab.sh/install.ps1 | iex
```

The installer will download Syncthing, set up auto-start, and show you the status of all dependencies:

```
Dependencies

  uv           installed 0.9.18     ~/.local/bin/uv
  tailscale    running   1.92.3     your-tailnet.org / you@example.com
  syncthing    running   v2.0.12    ~/.local/bin/syncthing / autostart: launchd
```

After installation, remember to **set up a password** for the Syncthing dashboard at `http://127.0.0.1:8384/`.

**Uninstall (macOS / Linux):**
```bash
curl -LsSf https://scratch.tlab.sh/install.sh | sh -s -- --uninstall
```

**Uninstall (Windows):**
```powershell
$env:UNINSTALL=1; iwr -useb https://scratch.tlab.sh/install.ps1 | iex
```

**Check dependency status:**
```bash
curl -LsSf https://scratch.tlab.sh/install.sh | sh -s -- --status
```

### Install the CLI

The `scratch-sync` CLI helps you manage synced folders. Choose your preferred installation method:

**Permanent install (recommended):**
```bash
uv tool install scratch-sync
```
This installs `scratch-sync` globally so you can run it from anywhere.

**Run without installing:**
```bash
uvx scratch-sync --help
```
If you prefer not to install permanently, use `uvx` to run the latest version on-demand.

**Update to latest version:**
```bash
uv tool upgrade scratch-sync
```

**Uninstall:**
```bash
uv tool uninstall scratch-sync
```

### Usage

```bash
# Inside a git repo with a scratch/ folder
scratch-sync init

# Add a specific scratch folder
scratch-sync add ~/code/myrepo/scratch
```

## How It Works

Syncthing folder IDs just need to match across devices. The actual filesystem paths can be different:
- `scratch-sleap-io` on Linux at `~/code/sleap-io/scratch`
- Same folder ID on Windows at `D:\sleap-io\scratch`

```
┌─────────────────┐     Tailscale      ┌─────────────────┐
│  Linux Box      │◄──────────────────►│  Mac Laptop     │
│ ~/code/sleap-io │                    │ ~/sleap-io      │
│   └── scratch/  │   folder-id:       │   └── scratch/  │
│                 │  "scratch-sleap-io"│                 │
└────────┬────────┘                    └────────┬────────┘
         │            Tailscale                 │
         └──────────────┬───────────────────────┘
                        ▼
              ┌─────────────────┐
              │  Windows PC     │
              │ D:\sleap-io     │
              │   └── scratch/  │
              └─────────────────┘
```

## Documentation

Full documentation at [scratch.tlab.sh](https://scratch.tlab.sh).

## Development

### Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/talmolab/scratch-sync.git
cd scratch-sync
uv sync
```

This creates a virtual environment and installs all dependencies.

### Running in development

Run the CLI directly from source:

```bash
uv run scratch-sync --help
```

### Install from GitHub

Install the latest development version from the `main` branch:

```bash
uv tool install git+https://github.com/talmolab/scratch-sync.git
```

Or run without installing:

```bash
uvx --from git+https://github.com/talmolab/scratch-sync.git scratch-sync --help
```

### Local editable install

For development, install as an editable tool from your local checkout:

```bash
uv tool install --editable .
```

This installs `scratch-sync` globally but uses your local source files, so changes take effect immediately.

To uninstall and reinstall after making changes to entry points:

```bash
uv tool uninstall scratch-sync
uv tool install --editable .
```

## License

MIT
