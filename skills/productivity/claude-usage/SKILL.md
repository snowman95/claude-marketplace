---
name: claude-usage
description: Use when checking Claude Code subscription quota before starting long or expensive jobs; when user asks about 토큰 사용량, 쿼터, 사용량 확인, 한도, remaining quota, usage limit, or rate limit 얼마 남았; when any agent needs to decide if it has budget to run a multi-step or parallel task.
---

# claude-usage

## Overview

Reads the Claude Code OAuth token from macOS Keychain and queries Anthropic's usage API to show 5-hour and 7-day window utilisation.

## When to Use

- User asks about quota, usage, 사용량, 한도, rate limit
- Before launching expensive parallel agents or long pipelines
- Any time you are unsure whether there is budget to proceed

**Threshold rule:** ≥ 80% on either window → do not start long jobs. Suggest waiting for reset.

## Command

```bash
python3 ~/.claude/skills/claude-usage/scripts/usage.py
```

Flags: `--json` (machine-readable), `--profile` (add org tier). Run `--help` for all options.

## Reading the Output

```
Window     Used %   Resets (KST)           Resets in
5-hour      7.0%   2026-09-07 13:39 KST   in 1h 23m
7-day      12.0%   2026-09-14 09:00 KST   in 6d 21h
```

- `Used %` is the utilisation percent (0–100). Lower is safer.
- Resets at is shown in **KST (UTC+9)**. API returns UTC; script adds +9 h.
- `7-day_opus` / `7-day_sonnet` rows appear only when the account has per-model limits.

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Exit 2 — "Keychain entry not found" | No token cached | Run `claude` in the terminal and log in |
| Exit 2 — "JSON parse failed" | Token entry corrupted | Re-login via `claude` |
| Exit 3 — "HTTP 401" | Token expired | Claude Code auto-refreshes; re-run after a few seconds |
| Exit 3 — "unexpected response shape" | Endpoint changed | Report unknown usage; do not guess; check Anthropic status |
