---
name: statusline-setup
description: Install and configure the Claude Code statusline script (model, context %, tokens, rate limits)
trigger: When the user asks to set up, install, or configure the statusline
---

# Statusline Setup

This skill installs the statusline script and updates `~/.claude/settings.json`.

## Steps

1. **Copy the script** to `~/.claude/statusline.sh`:

```bash
cp "$(dirname "$0")/../../statusline.sh" ~/.claude/statusline.sh
chmod +x ~/.claude/statusline.sh
```

2. **Add to settings.json** (`~/.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "/Users/YOUR_USERNAME/.claude/statusline.sh",
    "padding": 1
  }
}
```

Replace `YOUR_USERNAME` with your actual username (`whoami`).

## Requirements

- `jq` — JSON parsing (`brew install jq` on macOS)
- `bc` — math (`brew install bc` on macOS, pre-installed on most Linux)

## What It Shows

```
my-project on main │ claude-sonnet-4-6 │ Ctx: ████░░░░ 42% │ ↓15.2K ↑3.4K │ 5h:23%(1h30m) 7d:8%
```

- **Location** — folder name + git branch
- **Model** — current model display name
- **Context** — progress bar + percentage (green/yellow/red)
- **Tokens** — input ↓ / output ↑ formatted (K/M)
- **Rate limits** — 5-hour and 7-day usage % with countdown to reset
