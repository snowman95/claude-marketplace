---
name: cursor-statusline-setup
description: Install and configure the Cursor CLI statusline script (model, context %, tokens, git branch)
trigger: When the user asks to set up, install, or configure the Cursor statusline or CLI status bar
---

# Cursor Statusline Setup

Installs the shared statusline script and registers it in `~/.cursor/cli-config.json`.
Uses the same `statusline.sh` as Claude Code; rate-limit fields are omitted automatically when absent from the payload.

## Steps

1. **Copy the script** to `~/.cursor/statusline.sh`:

```bash
cp "$(dirname "$0")/../../../scripts/statusline.sh" ~/.cursor/statusline.sh
chmod +x ~/.cursor/statusline.sh
```

2. **Merge into cli-config.json** (`~/.cursor/cli-config.json`).

Replace `YOUR_USERNAME` with `whoami` output, or use `$HOME`:

```bash
USERNAME=$(whoami)
jq --arg cmd "/Users/${USERNAME}/.cursor/statusline.sh" \
  '.statusLine = {"type": "command", "command": $cmd, "padding": 1}' \
  ~/.cursor/cli-config.json > ~/.cursor/cli-config.json.tmp \
  && mv ~/.cursor/cli-config.json.tmp ~/.cursor/cli-config.json
```

Or add manually (preserve existing keys):

```json
{
  "statusLine": {
    "type": "command",
    "command": "/Users/YOUR_USERNAME/.cursor/statusline.sh",
    "padding": 1
  }
}
```

3. **Restart the Cursor CLI** (or start a new agent session) for changes to take effect.

Alternatively, run `/statusline` inside the Cursor CLI to configure interactively.

## Requirements

- `jq` — JSON parsing (`brew install jq` on macOS)
- `bc` — math (`brew install bc` on macOS, pre-installed on most Linux)

## What It Shows

```
my-project on main │ Auto │ Ctx: ████░░░░ 42% │ ↓15.2K ↑3.4K
```

- **Location** — folder name + git branch
- **Model** — current model display name
- **Context** — progress bar + percentage (green/yellow/red)
- **Tokens** — input ↓ / output ↑ formatted (K/M)

Rate limits (`5h` / `7d`) appear only when the payload includes `rate_limits` (Claude Code). Cursor CLI does not provide these fields.

## Verify

```bash
echo '{"model":{"display_name":"Auto"},"context_window":{"used_percentage":42,"total_input_tokens":15234,"total_output_tokens":3400},"cwd":"'"$PWD"'"}' \
  | ~/.cursor/statusline.sh
```

## Related

- Claude Code variant: `statusline-setup` skill (`~/.claude/settings.json`)
- Shared script: `scripts/statusline.sh`
