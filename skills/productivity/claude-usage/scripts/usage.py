#!/usr/bin/env python3
"""Claude Code subscription usage checker.

Reads the OAuth token from macOS Keychain and queries
https://api.anthropic.com/api/oauth/usage to show 5-hour and 7-day
window utilisation.

Exit codes
----------
0  success
2  auth / keychain problem  (user must re-login: run `claude`)
3  endpoint / format problem (treat usage as unknown, do not guess)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── constants ────────────────────────────────────────────────────────────────

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
_BETA_HEADER = "oauth-2025-04-20"
_TIMEOUT = 15
_KST = timezone(timedelta(hours=9))

# Allow test override of the keychain service name
_KEYCHAIN_SERVICE = os.environ.get(
    "CLAUDE_USAGE_KEYCHAIN_SERVICE", "Claude Code-credentials"
)


# ── keychain ─────────────────────────────────────────────────────────────────

def _read_token() -> str:
    """Read the Claude Code OAuth token from macOS Keychain.

    Raises SystemExit(2) on any failure.  Never prints the token.
    """
    user = os.environ.get("USER", "")
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", _KEYCHAIN_SERVICE, "-a", user, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        _die(2, "security(1) not found — this tool requires macOS")
    except subprocess.TimeoutExpired:
        _die(2, "Keychain lookup timed out")

    if result.returncode != 0:
        _die(
            2,
            f"Keychain entry not found (service={_KEYCHAIN_SERVICE!r}, account={user!r}).\n"
            "  → Run `claude` in the terminal and log in, then retry.",
        )

    raw = result.stdout.strip()
    try:
        data = json.loads(raw)
        token: str = data["claudeAiOauth"]["accessToken"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        _die(2, f"Keychain JSON parse failed: {exc}\n  → Re-login with `claude`.")

    if not token:
        _die(2, "accessToken is empty in Keychain entry.\n  → Re-login with `claude`.")

    return token


# ── http ─────────────────────────────────────────────────────────────────────

def _get(url: str, token: str) -> dict:
    """GET url with Bearer token.  Returns parsed JSON or dies."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": _BETA_HEADER,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            _die(
                3,
                f"HTTP 401 — token rejected.\n"
                "  → Claude Code auto-refreshes tokens; wait a moment and retry.\n"
                "  → If repeated, re-login with `claude`.",
            )
        _die(3, f"HTTP {exc.code} from {url}\n  → Check Anthropic status; do not guess usage.")
    except urllib.error.URLError as exc:
        _die(3, f"Network error: {exc.reason}")
    except json.JSONDecodeError as exc:
        _die(3, f"Response is not valid JSON: {exc}\n  → Endpoint may have changed.")


# ── formatting ────────────────────────────────────────────────────────────────

def _to_kst(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone(_KST)
    except ValueError:
        return None


def _fmt_delta(dt: Optional[datetime]) -> str:
    if dt is None:
        return "?"
    now = datetime.now(_KST)
    delta = dt - now
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "already reset"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"in {days}d {hours}h"
    if hours > 0:
        return f"in {hours}h {minutes}m"
    return f"in {minutes}m"


def _fmt_kst(dt: Optional[datetime]) -> str:
    if dt is None:
        return "?"
    return dt.strftime("%Y-%m-%d %H:%M KST")


def _pct_bar(pct: Optional[float], width: int = 20) -> str:
    if pct is None:
        return "-" * width
    filled = int(pct / 100 * width)
    return "#" * filled + "." * (width - filled)


def _warn(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    if pct >= 80:
        return "  *** HIGH — do not start long jobs ***"
    if pct >= 60:
        return "  * caution"
    return ""


# ── display ──────────────────────────────────────────────────────────────────

def _print_table(body: dict, profile: Optional[dict]) -> None:
    windows = [
        ("5-hour",       body.get("five_hour")),
        ("7-day",        body.get("seven_day")),
        ("7-day opus",   body.get("seven_day_opus")),
        ("7-day sonnet", body.get("seven_day_sonnet")),
    ]

    now_kst = datetime.now(_KST).strftime("%Y-%m-%d %H:%M KST")
    print(f"Claude Code Usage  (fetched {now_kst})")
    print()

    header = f"{'Window':<14}  {'Used %':>6}  {'Resets (KST)':<22}  {'Resets in':<14}"
    print(header)
    print("-" * len(header))

    for label, w in windows:
        if w is None:
            continue
        try:
            pct: Optional[float] = float(w["utilization"])
        except (TypeError, KeyError, ValueError):
            pct = None
        resets_dt = _to_kst(w.get("resets_at") if isinstance(w, dict) else None)
        pct_str = f"{pct:.1f}%" if pct is not None else "?"
        print(
            f"{label:<14}  {pct_str:>6}  {_fmt_kst(resets_dt):<22}  "
            f"{_fmt_delta(resets_dt):<14}{_warn(pct)}"
        )

    extra = body.get("extra_usage", {})
    extra_enabled = extra.get("is_enabled", False) if isinstance(extra, dict) else False
    print()
    print(f"Extra usage: {'enabled' if extra_enabled else 'disabled'}")

    if profile:
        org = profile.get("organization", {})
        tier = org.get("rate_limit_tier", "?")
        org_type = org.get("organization_type", "?")
        print(f"Org tier: {tier}  |  type: {org_type}")


def _build_json_output(body: dict, profile: Optional[dict]) -> dict:
    def _extract(w) -> Optional[dict]:
        if w is None:
            return None
        if not isinstance(w, dict):
            return None
        return {
            "utilization": w.get("utilization"),
            "resets_at": w.get("resets_at"),
        }

    extra = body.get("extra_usage", {})
    out: dict = {
        "five_hour":       _extract(body.get("five_hour")),
        "seven_day":       _extract(body.get("seven_day")),
        "seven_day_opus":  _extract(body.get("seven_day_opus")),
        "seven_day_sonnet": _extract(body.get("seven_day_sonnet")),
        "extra_usage_enabled": extra.get("is_enabled", False) if isinstance(extra, dict) else False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if profile:
        org = profile.get("organization", {})
        out["profile"] = {
            "rate_limit_tier": org.get("rate_limit_tier"),
            "organization_type": org.get("organization_type"),
            "has_extra_usage_enabled": org.get("has_extra_usage_enabled"),
        }
    return out


# ── util ─────────────────────────────────────────────────────────────────────

def _die(code: int, msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show Claude Code subscription usage for 5-hour and 7-day windows.",
        epilog=(
            "Exit codes: 0=ok, 2=auth/keychain problem, 3=endpoint/format problem.\n"
            "Token is NEVER printed.  Set CLAUDE_USAGE_KEYCHAIN_SERVICE to override "
            "the keychain service name (useful for testing the auth-failure path)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON instead of a human table.",
    )
    parser.add_argument(
        "--profile", action="store_true",
        help="Also fetch /api/oauth/profile to include org tier and type.",
    )
    args = parser.parse_args()

    token = _read_token()

    try:
        body = _get(_USAGE_URL, token)
    finally:
        # Ensure token doesn't linger in local scope on error paths
        del token
        token = None  # type: ignore[assignment]

    profile: Optional[dict] = None
    if args.profile:
        # Re-read token (already deleted above; need a fresh read)
        token2 = _read_token()
        try:
            profile = _get(_PROFILE_URL, token2)
        finally:
            del token2

    # Basic shape validation
    if not isinstance(body, dict) or ("five_hour" not in body and "seven_day" not in body):
        _die(
            3,
            "Unexpected response shape from usage endpoint.\n"
            "  → The endpoint may have changed; treat usage as unknown.",
        )

    if args.json:
        print(json.dumps(_build_json_output(body, profile), indent=2))
    else:
        _print_table(body, profile)


if __name__ == "__main__":
    main()
