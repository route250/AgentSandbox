#!/bin/bash

DefaultDir=$HOME/projects/default
mkdir -p $DefaultDir
cd $DefaultDir
if [ ! -e $HOME/.local/share/opencode/opencode.db ]; then
    "$HOME/.opencode/bin/opencode" run "こんにちは" --dir $DefaultDir >/dev/null 2>&1 &
    xpid=$!
    sleep 3
    kill -9 $xpid
fi
exec "$HOME/.opencode/bin/opencode" web --hostname 127.0.0.1 --port "$SBOX_PORT" --cors '*'
