#!/bin/sh
case $0 in
  */*) dir=${0%/*} ;;
  *) dir=. ;;
esac
script=$1
case $script in
  '' | */* | -* | .* | *[!A-Za-z0-9_.-]*) script= ;;
  *.py) ;;
  *) script= ;;
esac
if [ -z "$script" ] || [ ! -f "$dir/$script" ]; then
  echo "hook_python.sh: the first argument must be a .py file next to this launcher" >&2
  exit 1
fi
shift
interpreter=
for python in "$CLAUDE_PLUGIN_OPTION_PYTHON" "$HEI5ENBUG_PYTHON"; do
  case $python in
    /*)
      if [ -f "$python" ] && [ -x "$python" ]; then
        interpreter=$python
        break
      fi
      ;;
  esac
done
[ -n "$interpreter" ] || interpreter=python3
state=${XDG_STATE_HOME:-${HOME:+$HOME/.local/state}}
case $state in
  /*)
    exec "$interpreter" -X "pycache_prefix=$state/hei5enbug-agent-setup/pycache" -c 'import os, sys
if sys.path and sys.path[0] == "":
    del sys.path[0]
sys.path.insert(0, os.path.abspath(sys.argv[1]))
import runpy
module = sys.argv[2][:-3]
del sys.argv[1:3]
runpy.run_module(module, run_name="__main__", alter_sys=True)' "$dir" "$script" "$@"
    ;;
esac
exec "$interpreter" "$dir/$script" "$@"
