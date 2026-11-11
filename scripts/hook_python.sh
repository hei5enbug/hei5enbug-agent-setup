#!/bin/sh
case $0 in
  */*) dir=${0%/*} ;;
  *) dir=. ;;
esac
if [ ! -f "$dir/hook_interpreter.sh" ]; then
  echo "hei5enbug-agent-setup hook launcher (hook_python.sh) did not run the hook because hook_interpreter.sh is missing next to it. Reinstall the plugin, then retry." >&2
  exit 1
fi
. "$dir/hook_interpreter.sh"
script=$1
case $script in
  '' | */* | -* | .* | *[!A-Za-z0-9_.-]*) script= ;;
  *.py) ;;
  *) script= ;;
esac
if [ -z "$script" ] || [ ! -f "$dir/$script" ]; then
  echo "hei5enbug-agent-setup hook launcher (hook_python.sh) did not run a hook because its first argument is not a .py file next to the launcher. Fix the hook command so it names a script in the plugin's scripts folder." >&2
  exit 1
fi
shift
hook_select_interpreter
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
