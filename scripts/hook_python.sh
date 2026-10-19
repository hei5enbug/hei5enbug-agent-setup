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
for python in "$CLAUDE_PLUGIN_OPTION_PYTHON" "$HEI5ENBUG_PYTHON"; do
  case $python in
    /*)
      if [ -f "$python" ] && [ -x "$python" ]; then
        exec "$python" "$dir/$script" "$@"
      fi
      ;;
  esac
done
exec python3 "$dir/$script" "$@"
