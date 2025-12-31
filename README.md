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

```bash
curl -LsSf https://raw.githubusercontent.com/talmolab/scratch-sync/main/install.sh | sh
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

## Development

See the [docs](./docs/) folder for detailed documentation.

## License

MIT
