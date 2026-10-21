#!/bin/zsh
# Turns on the Mac-side schedule (the one that can send iMessage):
#   daily  07:00 Mon-Fri   weekly 08:00 Mon
# Run it once:  ./tools/install-local-schedule.sh
# Turn it off:  ./tools/install-local-schedule.sh off
set -u
HERE="${0:A:h}"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.powerfix.powerdash.daily com.powerfix.powerdash.weekly)

if [[ "${1:-on}" == "off" ]]; then
  for l in $LABELS; do
    launchctl bootout "gui/$UID/$l" 2>/dev/null
    rm -f "$AGENTS/$l.plist"
    echo "removed $l"
  done
  exit 0
fi

mkdir -p "$AGENTS"
for l in $LABELS; do
  cp "$HERE/$l.plist" "$AGENTS/$l.plist"
  launchctl bootout "gui/$UID/$l" 2>/dev/null
  launchctl bootstrap "gui/$UID" "$AGENTS/$l.plist" && echo "scheduled $l"
done
echo
echo "First send will ask macOS for permission to control Messages — say yes."
echo "Test it right now with:  ./tools/run-local.sh daily && tail -20 ~/Library/Logs/powerdash.log"
