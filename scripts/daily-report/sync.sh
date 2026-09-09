#!/usr/bin/env bash
# 마켓플레이스 클론(정본) → 로컬 실행본(~/.local/share/daily-report) 동기화.
#
# 왜 두 곳인가:
#   마켓플레이스는 autoUpdate 대상이라 재클론 시 로컬 변경이 날아간다.
#   실행본을 자동갱신 밖에 두고, 코드는 리포에서 버전 관리한다.
#
# ⚠️ 2026-09-09 사고: 리포가 실행본보다 낡은 상태에서 이 스크립트를 돌려
#    `rsync --delete` 가 실행본의 신규 파일(github.py 등)을 지웠다.
#    그래서 아래 가드를 넣었다. --force 로만 우회한다.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.local/share/daily-report"
FORCE="${1:-}"

mkdir -p "$DEST"

# 가드 1 — 실행본에만 있는 .py 가 있으면 멈춘다. 지우면 소실이다.
ORPHANS=$(comm -13 \
  <(cd "$SRC" && find . -name '*.py' -not -path './__pycache__/*' -not -path './.pytest_cache/*' | sort) \
  <(cd "$DEST" && find . -name '*.py' -not -path './__pycache__/*' -not -path './.pytest_cache/*' | sort) || true)
if [ -n "$ORPHANS" ] && [ "$FORCE" != "--force" ]; then
  echo "❌ 중단: 실행본에만 있는 파일이 있다. 정본(리포)이 낡았다는 뜻이다." >&2
  echo "$ORPHANS" | sed 's/^/   /' >&2
  echo >&2
  echo "   실행본 → 리포 로 먼저 반영해라:" >&2
  echo "     rsync -a --delete --exclude __pycache__ --exclude .pytest_cache \\" >&2
  echo "       --exclude config.toml --exclude sync.sh \"$DEST/\" \"$SRC/\"" >&2
  echo >&2
  echo "   정말 지우려면: $0 --force" >&2
  exit 1
fi

# 가드 2 — 실행본 테스트 수가 줄어들면 멈춘다.
count_tests() { (cd "$1" && python3 -m pytest tests/ -q --collect-only 2>/dev/null | tail -1 | grep -oE '^[0-9]+' || echo 0); }
BEFORE=$(count_tests "$DEST")

BACKUP="/tmp/daily-report-presync-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$BACKUP" -C "$(dirname "$DEST")" --exclude '__pycache__' --exclude '.pytest_cache' "$(basename "$DEST")"

rsync -a --delete \
  --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'config.toml' --exclude 'sync.sh' \
  "$SRC/" "$DEST/"

AFTER=$(count_tests "$DEST")
echo "동기화: $SRC → $DEST  (테스트 $BEFORE → $AFTER)"
echo "직전 백업: $BACKUP"
if [ "$AFTER" -lt "$BEFORE" ] && [ "$FORCE" != "--force" ]; then
  echo "❌ 테스트가 $((BEFORE-AFTER))개 줄었다. 되돌린다." >&2
  tar -xzf "$BACKUP" -C "$(dirname "$DEST")"
  echo "   복원 완료. 리포가 낡았는지 확인해라." >&2
  exit 1
fi
(cd "$DEST" && python3 -m pytest tests/ -q 2>&1 | tail -2)
