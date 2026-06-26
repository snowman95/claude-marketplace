---
name: show-schedulers
description: Use when the user wants to see all scheduled tasks, cron jobs, or launchd agents on macOS — lists targets, intervals, and next-run times in a unified table.
disable-model-invocation: true
---

# Show Schedulers

모든 커스텀 스케줄러를 통합 마크다운 표로 출력한다.

## 실행

아래 Python 스크립트를 그대로 실행한다:

```bash
python3 << 'PYEOF'
import plistlib, os, glob, subprocess

SKIP_PREFIXES = ("com.google.", "com.apple.")
SHELL_ARGS = ("/bin/zsh", "/bin/bash", "/bin/sh")
INTERVAL_LABELS = {
    60:"1분", 300:"5분", 360:"6분", 600:"10분", 1800:"30분",
    3600:"1시간", 7200:"2시간", 10800:"3시간", 18000:"5시간",
    21600:"6시간", 43200:"12시간", 86400:"매일"
}
WEEKDAY_KR = {0:"일",1:"월",2:"화",3:"수",4:"목",5:"금",6:"토"}

def parse_schedule(d):
    interval = d.get("StartInterval")
    sci = d.get("StartCalendarInterval")
    if interval:
        label = INTERVAL_LABELS.get(interval, f"{interval}초")
        return f"매 {label}"
    if not sci:
        return ""
    entries = sci if isinstance(sci, list) else [sci]
    slots = [f"{e.get('Hour','*')}:{e.get('Minute',0):02d}" for e in entries]
    time_str = ", ".join(slots)
    weekday = entries[0].get("Weekday") if entries else None
    if weekday is not None:
        return f"매주 {WEEKDAY_KR.get(weekday, weekday)}요일 {time_str}"
    return f"매일 {time_str}"

rows = []
for path in sorted(glob.glob(os.path.expanduser("~/Library/LaunchAgents/*.plist"))):
    with open(path, "rb") as f:
        try:
            d = plistlib.load(f)
        except Exception:
            continue
    label = d.get("Label", "")
    if not label or any(label.startswith(p) for p in SKIP_PREFIXES):
        continue

    args = d.get("ProgramArguments", [])
    prog = d.get("Program", "")
    keepalive = d.get("KeepAlive", False)
    if args:
        if args[0] in SHELL_ARGS and len(args) >= 3:
            target = args[-1][:55] + ("…" if len(args[-1]) > 55 else "")
        else:
            exts = (".py", ".ts", ".js", ".sh")
            script = next((a for a in args if any(a.endswith(e) for e in exts)), None)
            target = os.path.basename(script) if script else os.path.basename(args[1] if len(args) > 1 else args[0])
    else:
        target = os.path.basename(prog)

    schedule = parse_schedule(d)
    if keepalive and not schedule:
        schedule = "상시 실행 (KeepAlive)"

    rows.append((label, target, schedule))

print("## LaunchAgents\n")
print("| Label | 스크립트 | 주기/시각 |")
print("|---|---|---|")
for label, target, schedule in rows:
    print(f"| {label} | {target} | {schedule} |")

print()
print("## crontab\n")
result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
lines = [l for l in result.stdout.splitlines() if l.strip() and not l.startswith("#")]
if lines:
    print("| 분 | 시 | 일 | 월 | 요일 | 명령 |")
    print("|---|---|---|---|---|---|")
    for line in lines:
        parts = line.split(None, 5)
        if len(parts) >= 6:
            print(f"| {' | '.join(parts[:5])} | {parts[5]} |")
else:
    print("crontab 항목 없음")
PYEOF
```

## 완료 기준

- `~/Library/LaunchAgents/` 내 모든 비시스템 plist가 표에 포함됨
- crontab 확인 완료 (비어 있어도 명시)
- 각 항목에 주기 또는 시각이 표시됨
