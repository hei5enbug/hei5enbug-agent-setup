#!/bin/sh
# Starts the agent hook of the public boundary scanner with the interpreter the plugin's hook launcher would pick.
case $0 in
  */*) dir=${0%/*} ;;
  *) dir=. ;;
esac
interpreter=python3
if [ -f "$dir/../scripts/hook_interpreter.sh" ]; then
  . "$dir/../scripts/hook_interpreter.sh"
  hook_select_interpreter
fi
exec "$interpreter" "$dir/public_boundary.py" agent-hook
