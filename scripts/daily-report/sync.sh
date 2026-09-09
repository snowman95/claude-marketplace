#!/usr/bin/env bash
# 마켓플레이스 클론(정본) → 로컬 실행본(~/.local/share/daily-report) 동기화.
#
# 왜 두 곳인가:
#   마켓플레이스는 autoUpdate 대상이라 재클론 시 로컬 변경이 날아간다.
#   실행본을 자동갱신 밖에 두고, 코드는 리포에서 버전 관리한다.
#
# config.toml 과 로그는 동기화 대상이 아니다 (개인 값·런타임).
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.local/share/daily-report"
mkdir -p "$DEST"
rsync -a --delete \
  --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'config.toml' --exclude 'sync.sh' \
  "$SRC/" "$DEST/"
echo "동기화 완료: $SRC → $DEST"
cd "$DEST" && python3 -m pytest tests/ -q 2>&1 | tail -2
