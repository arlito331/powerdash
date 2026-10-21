#!/bin/zsh
# Runs on the Mac, where iMessage is possible. launchd calls this; see
# install-local-schedule.sh. Usage: run-local.sh daily|weekly
set -u
HERE="${0:A:h}"
LOG="$HOME/Library/Logs/powerdash.log"
cd "${HERE:h}" || exit 1

# Use the live file from GitHub when the repo is online, otherwise the local one.
REMOTE=""
if /usr/bin/curl -sf -o /dev/null --max-time 10 \
   "https://raw.githubusercontent.com/arlito331/powerdash/main/data/leads.json"; then
  REMOTE="--remote"
fi

case "${1:-daily}" in
  daily)  ARGS=(due --send --via auto $REMOTE) ;;
  weekly) ARGS=(standing --send --via auto --always $REMOTE) ;;
  *) echo "usage: run-local.sh daily|weekly" >&2; exit 2 ;;
esac

{
  echo "--- $(date '+%Y-%m-%d %H:%M') $1"
  /usr/bin/python3 tools/followups.py "${ARGS[@]}" 2>&1
} >> "$LOG"
