#!/usr/bin/env bash
# launchd 잡 2개를 설치한다. 실행 전 poll.py 가 --dry-run 으로 검증된 뒤에만 돌려라.
set -euo pipefail
PLUGIN_ROOT="$HOME/.claude/plugins/marketplaces/snowman95-marketplace"
SRC="$PLUGIN_ROOT/scripts/daily-report/launchd"
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST" "$HOME/.local/log/daily-report"

for label in com.daily-report.daily-poll com.daily-report.daily-brief; do
  sed -e "s|PLUGIN_ROOT|$PLUGIN_ROOT|g" -e "s|HOME_DIR|$HOME|g" \
      "$SRC/$label.plist" > "$DEST/$label.plist"
  launchctl unload "$DEST/$label.plist" 2>/dev/null || true
  launchctl load "$DEST/$label.plist"
  echo "loaded: $label"
done
echo
echo "확인: launchctl list | grep daily-report"
echo "로그: ~/.local/log/daily-report/"
echo
echo "⚠️  vault가 iCloud 경로라 launchd가 읽지 못하면 시스템 설정 >"
echo "    개인정보 보호 및 보안 > 전체 디스크 접근 권한에 /bin/bash 또는 python3 추가 필요"
