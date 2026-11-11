# Sourced by hook_python.sh and by the project hook commands; it is not run on its own.
# It records when the launcher started in HEI5ENBUG_HOOK_STARTED_AT (seconds since the epoch) when the shell can
# read the clock without a child process, and it sets `interpreter` and `state` for the caller. A configured
# interpreter wins. Otherwise a cached absolute interpreter runs while the first python3 on PATH is still the one
# the cache was resolved from; on a cold or stale cache python3 from PATH runs as before, and one detached
# resolver refreshes the cache, so resolving never delays a hook. Nothing here starts a child process on a warm cache.
# The resolver writes the cache and then a `verified` file after it; the launcher trusts the cache only while both are
# owned by the current user, are not symlinks, and the cache is not newer than `verified`.
unset HEI5ENBUG_HOOK_STARTED_AT
case ${EPOCHREALTIME-} in
  '') ;;
  *,*)
    HEI5ENBUG_HOOK_STARTED_AT=${EPOCHREALTIME%,*}.${EPOCHREALTIME#*,}
    export HEI5ENBUG_HOOK_STARTED_AT
    ;;
  *)
    HEI5ENBUG_HOOK_STARTED_AT=$EPOCHREALTIME
    export HEI5ENBUG_HOOK_STARTED_AT
    ;;
esac

hook_recent_failure() {
  [ -f "$hook_folder/failed" ] && [ -n "$(find "$hook_folder/failed" -mmin -1 2>/dev/null)" ]
}

hook_unlock() {
  hook_holder=
  [ ! -f "$hook_folder/lock" ] || read -r hook_holder < "$hook_folder/lock" 2>/dev/null
  [ "$hook_holder" != "$hook_self" ] || rm -f "$hook_folder/lock"
  rm -f "$hook_folder/lock.$hook_self" "$hook_folder/cache.$hook_self"
}

hook_resolve() {
  umask 077
  hook_folder=$1/hei5enbug-agent-setup/interpreter
  mkdir -p "$hook_folder" 2>/dev/null || exit 0
  hook_recent_failure && exit 0
  hook_self=$(exec sh -c 'echo $PPID')
  case $hook_self in
    '' | *[!0-9]*) exit 0 ;;
  esac
  trap hook_unlock EXIT
  printf '%s\n' "$hook_self" > "$hook_folder/lock.$hook_self" 2>/dev/null || exit 0
  if ! ln "$hook_folder/lock.$hook_self" "$hook_folder/lock" 2>/dev/null; then
    hook_holder=
    read -r hook_holder < "$hook_folder/lock" 2>/dev/null
    case $hook_holder in
      '' | *[!0-9]*) ;;
      *) ! kill -0 "$hook_holder" 2>/dev/null || exit 0 ;;
    esac
    rm -f "$hook_folder/lock"
    ln "$hook_folder/lock.$hook_self" "$hook_folder/lock" 2>/dev/null || exit 0
  fi
  hook_recent_failure && exit 0
  hook_real=$(cd / && "$2" -E -S -c 'import sys
if sys.version_info >= (3, 12):
    print(sys.executable)' 2>/dev/null </dev/null)
  case $hook_real in
    /* | '') ;;
    *) hook_real= ;;
  esac
  case $hook_real in
    *'
'*) hook_real= ;;
  esac
  if [ -n "$hook_real" ] && [ -f "$hook_real" ] && [ -x "$hook_real" ]; then
    rm -f "$hook_folder/verified"
    printf '%s\n%s\n' "$2" "$hook_real" > "$hook_folder/cache.$hook_self" &&
      mv -f "$hook_folder/cache.$hook_self" "$hook_folder/cache" &&
      : > "$hook_folder/verified"
    rm -f "$hook_folder/failed"
  else
    : > "$hook_folder/failed"
  fi
  exit 0
}

hook_cached_interpreter() {
  hook_first=
  hook_old_ifs=$IFS
  set -f
  IFS=:
  for hook_entry in $PATH; do
    case $hook_entry in
      /*) ;;
      *) hook_first=; break ;;
    esac
    if [ -f "$hook_entry/python3" ] && [ -x "$hook_entry/python3" ]; then
      hook_first=$hook_entry/python3
      break
    fi
  done
  IFS=$hook_old_ifs
  set +f
  [ -n "$hook_first" ] || return 0
  hook_key=
  hook_real=
  hook_cache=$state/hei5enbug-agent-setup/interpreter/cache
  hook_mark=$state/hei5enbug-agent-setup/interpreter/verified
  if [ -O "$hook_cache" ] && [ -f "$hook_cache" ] && [ ! -h "$hook_cache" ] &&
    [ -O "$hook_mark" ] && [ -f "$hook_mark" ] && [ ! -h "$hook_mark" ] && ! [ "$hook_cache" -nt "$hook_mark" ]; then
    { IFS= read -r hook_key; IFS= read -r hook_real; } < "$hook_cache"
  fi
  if [ "$hook_key" = "$hook_first" ]; then
    case $hook_real in
      /*)
        if [ -f "$hook_real" ] && [ -x "$hook_real" ]; then
          interpreter=$hook_real
          return 0
        fi
        ;;
    esac
  fi
  (hook_resolve "$state" "$hook_first") </dev/null >/dev/null 2>&1 &
}

hook_select_interpreter() {
  interpreter=
  for hook_python in "$CLAUDE_PLUGIN_OPTION_PYTHON" "$HEI5ENBUG_PYTHON"; do
    case $hook_python in
      /*)
        if [ -f "$hook_python" ] && [ -x "$hook_python" ]; then
          interpreter=$hook_python
          break
        fi
        ;;
    esac
  done
  state=${XDG_STATE_HOME:-${HOME:+$HOME/.local/state}}
  case $state in
    /*) ;;
    *) state= ;;
  esac
  if [ -z "$interpreter" ]; then
    interpreter=python3
    [ -z "$state" ] || hook_cached_interpreter
  fi
}
