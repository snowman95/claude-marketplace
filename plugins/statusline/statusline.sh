#!/bin/bash
# Statusline for Claude Code
# Displays: model, context %, token usage, 5h/7d rate limits

set -euo pipefail

# --- Colors ---
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
CYAN='\033[36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

# --- Read JSON from stdin ---
input=$(cat)

# --- Parse fields with jq ---
model=$(echo "$input" | jq -r '.model.display_name // "?"')
ctx_pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
input_tokens=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
output_tokens=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
five_h=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
seven_d=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
five_h_reset=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
seven_d_reset=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
cwd_json=$(echo "$input" | jq -r '.cwd // empty')

# --- Git & CWD info ---
work_dir="${cwd_json:-$PWD}"
folder_name=$(basename "$work_dir")
git_branch=$(git -C "$work_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# --- Helper: format token count (e.g., 15234 -> 15.2K) ---
format_tokens() {
  local n=$1
  if [ "$n" -ge 1000000 ]; then
    printf "%.1fM" "$(echo "scale=1; $n / 1000000" | bc)"
  elif [ "$n" -ge 1000 ]; then
    printf "%.1fK" "$(echo "scale=1; $n / 1000" | bc)"
  else
    echo "$n"
  fi
}

# --- Helper: color by percentage (green < 50, yellow 50-80, red > 80) ---
color_pct() {
  local pct=$1
  local rounded
  rounded=$(printf '%.0f' "$pct" 2>/dev/null || echo "0")
  if [ "$rounded" -lt 50 ]; then
    printf "${GREEN}%s%%${RESET}" "$rounded"
  elif [ "$rounded" -lt 80 ]; then
    printf "${YELLOW}%s%%${RESET}" "$rounded"
  else
    printf "${RED}%s%%${RESET}" "$rounded"
  fi
}

# --- Helper: progress bar (8 chars wide) ---
progress_bar() {
  local pct=$1
  local width=8
  local filled=$((pct * width / 100))
  [ "$filled" -gt "$width" ] && filled=$width
  local empty=$((width - filled))
  local bar=""
  for ((i = 0; i < filled; i++)); do bar+="█"; done
  for ((i = 0; i < empty; i++)); do bar+="░"; done

  if [ "$pct" -lt 50 ]; then
    printf "${GREEN}%s${RESET}" "$bar"
  elif [ "$pct" -lt 80 ]; then
    printf "${YELLOW}%s${RESET}" "$bar"
  else
    printf "${RED}%s${RESET}" "$bar"
  fi
}

# --- Helper: format reset time as countdown ---
format_reset() {
  local reset_ts=$1
  if [ -z "$reset_ts" ]; then
    echo ""
    return
  fi
  local now
  now=$(date +%s)
  local diff=$((reset_ts - now))
  if [ "$diff" -le 0 ]; then
    echo "now"
    return
  fi
  local hours=$((diff / 3600))
  local mins=$(((diff % 3600) / 60))
  if [ "$hours" -gt 0 ]; then
    printf "%dh%dm" "$hours" "$mins"
  else
    printf "%dm" "$mins"
  fi
}

# --- Build output ---

# Location segment (folder + branch)
location_segment="${CYAN}${folder_name}${RESET}"
if [ -n "$git_branch" ]; then
  location_segment="${location_segment} ${DIM}on${RESET} ${BOLD}${git_branch}${RESET}"
fi

# Model segment
model_segment="${BOLD}${model}${RESET}"

# Context segment
ctx_bar=$(progress_bar "$ctx_pct")
ctx_segment="Ctx: ${ctx_bar} ${ctx_pct}%"

# Token segment
in_fmt=$(format_tokens "$input_tokens")
out_fmt=$(format_tokens "$output_tokens")
token_segment="${DIM}↓${in_fmt} ↑${out_fmt}${RESET}"

# Rate limit segments
limits=""
if [ -n "$five_h" ]; then
  five_h_color=$(color_pct "$five_h")
  five_h_countdown=$(format_reset "$five_h_reset")
  limits="5h:${five_h_color}"
  [ -n "$five_h_countdown" ] && limits="${limits}${DIM}(${five_h_countdown})${RESET}"
fi
if [ -n "$seven_d" ]; then
  seven_d_color=$(color_pct "$seven_d")
  seven_d_countdown=$(format_reset "$seven_d_reset")
  [ -n "$limits" ] && limits="${limits} "
  limits="${limits}7d:${seven_d_color}"
  [ -n "$seven_d_countdown" ] && limits="${limits}${DIM}(${seven_d_countdown})${RESET}"
fi

# --- Assemble line ---
line="${location_segment} │ ${model_segment} │ ${ctx_segment} │ ${token_segment}"

if [ -n "$limits" ]; then
  line="${line} │ ${limits}"
fi

# --- Output ---
printf "%b\n" "$line"
