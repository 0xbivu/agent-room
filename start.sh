#!/bin/sh
# Starts a new room session, then chats in this terminal. /resume ID restores an old one; Ctrl-C stops everything.
# See / drive each agent from another terminal: tmux attach -t room     Browser: http://localhost:9090
cd "$(dirname "$0")" || exit 1
# room up creates the session when the stack is stopped; an already-running stack needs /new.
room_running=no
if tmux has-session -t room 2>/dev/null; then
  room_running=yes
fi
./room up || exit 1
if [ "$room_running" = yes ]; then ./room new || exit 1; fi
ROOM_MAIN=1 exec ./room chat
