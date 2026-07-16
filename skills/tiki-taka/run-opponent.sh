#!/usr/bin/env bash
# 현재 호스트의 반대쪽 고정 에이전트 세션을 만들거나 정확히 재개한다.
# 상태 폴더에는 세션 식별자와 교환 수만 남기고 토론 내용은 남기지 않는다.
set -u

HOST=""
REPO="$PWD"
STATE_DIR=""
MAX_EXCHANGES=2
MAX_GIVEN=0
SHOW_CONFIG=0
STATUS_MODE=0
FINISH_MODE=0

CODEX_MODEL="gpt-5.6-sol"
CODEX_EFFORT="xhigh"
CLAUDE_MODEL="claude-fable-5"
CLAUDE_FALLBACK="claude-opus-4-8"
CLAUDE_EFFORT="xhigh"

MARKER_FILE=""
HOST_FILE=""
REPO_FILE=""
MAX_FILE=""
COUNT_FILE=""
SESSION_FILE=""
MODEL_FILE=""
UNCERTAIN_FILE=""
LOCK_DIR=""
LOCK_HELD=0
CALL_DIR=""
PROMPT_FILE=""
OUTPUT_FILE=""
EVENTS_FILE=""
LOG_FILE=""
RETRY_FILE=""

usage() {
  cat <<EOF
tiki-taka 반대쪽 전용 세션 실행기

사용법:
  bash run-opponent.sh --host <claude|codex> --state-dir <경로> \
    [--repo <경로>] [--max-exchanges <1-5>] < 프롬프트

상태 확인:
  bash run-opponent.sh --host <claude|codex> --state-dir <경로> --status

상태 정리:
  bash run-opponent.sh --host <claude|codex> --state-dir <경로> --finish

옵션:
  --host <이름>          현재 스킬을 실행 중인 호스트
  --state-dir <경로>     이번 토론에서만 쓸 고유한 상태 폴더
  --repo <경로>          반대쪽 에이전트가 읽을 작업 디렉터리
  --max-exchanges <1-5>  허용할 최대 교환 수, 기본값 2
  --show-config          반대쪽 고정 모델 설정만 출력
  --status               세션 식별자와 현재 교환 수만 출력
  --finish               이번 토론의 로컬 상태를 안전하게 정리
  -h, --help
EOF
}

usage_error() {
  echo "오류: $1" >&2
  usage >&2
  exit 2
}

runtime_error() {
  echo "오류: $1" >&2
  exit 1
}

cleanup() {
  if [ -n "$CALL_DIR" ] && [ -d "$CALL_DIR" ]; then
    rm -f "$PROMPT_FILE" "$OUTPUT_FILE" "$EVENTS_FILE"       "$LOG_FILE" "$RETRY_FILE" 2>/dev/null
    rmdir "$CALL_DIR" 2>/dev/null
  fi

  if [ "$LOCK_HELD" -eq 1 ] && [ -d "$LOCK_DIR" ]; then
    rmdir "$LOCK_DIR" 2>/dev/null
  fi
}

valid_exchange_limit() {
  case "$1" in
    1|2|3|4|5) return 0 ;;
    *) return 1 ;;
  esac
}

valid_nonnegative_integer() {
  case "$1" in
    ""|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

show_failure_log() {
  if [ -s "$LOG_FILE" ]; then
    cat "$LOG_FILE" >&2
  fi
  if [ -s "$EVENTS_FILE" ]; then
    tail -n 20 "$EVENTS_FILE" >&2
  fi
}

mark_uncertain() {
  printf '%s\n' "$1" > "$UNCERTAIN_FILE"
}

extract_codex_session() {
  python3 - "$1" <<'PY'
import json
import sys
import uuid

path = sys.argv[1]
with open(path, encoding="utf-8") as source:
    for line in source:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "thread.started":
            continue
        session_id = str(event.get("thread_id", ""))
        try:
            uuid.UUID(session_id)
        except ValueError:
            continue
        print(session_id)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

quota_message_found() {
  grep -qiE 'reached your .*limit|limit[.].*/model to switch'     "$OUTPUT_FILE" "$LOG_FILE"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host)
      [ $# -ge 2 ] || usage_error "--host 값이 없습니다."
      HOST="$2"
      shift 2
      ;;
    --repo)
      [ $# -ge 2 ] || usage_error "--repo 값이 없습니다."
      REPO="$2"
      shift 2
      ;;
    --state-dir)
      [ $# -ge 2 ] || usage_error "--state-dir 값이 없습니다."
      STATE_DIR="$2"
      shift 2
      ;;
    --max-exchanges)
      [ $# -ge 2 ] || usage_error "--max-exchanges 값이 없습니다."
      MAX_EXCHANGES="$2"
      MAX_GIVEN=1
      shift 2
      ;;
    --show-config)
      SHOW_CONFIG=1
      shift
      ;;
    --status)
      STATUS_MODE=1
      shift
      ;;
    --finish)
      FINISH_MODE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage_error "알 수 없는 옵션: $1"
      ;;
  esac
done

case "$HOST" in
  claude|codex) ;;
  *) usage_error "--host에는 claude 또는 codex가 필요합니다." ;;
esac

MODE_COUNT=$((SHOW_CONFIG + STATUS_MODE + FINISH_MODE))
[ "$MODE_COUNT" -le 1 ] || usage_error "실행 모드 옵션은 하나만 선택해야 합니다."

if [ "$SHOW_CONFIG" -eq 1 ]; then
  if [ "$HOST" = "claude" ]; then
    echo "opponent=codex model=$CODEX_MODEL effort=$CODEX_EFFORT"
  else
    echo "opponent=claude model=$CLAUDE_MODEL fallback=$CLAUDE_FALLBACK effort=$CLAUDE_EFFORT"
  fi
  exit 0
fi

[ -n "$STATE_DIR" ] || usage_error "--state-dir가 필요합니다."
valid_exchange_limit "$MAX_EXCHANGES" ||
  usage_error "--max-exchanges는 1부터 5까지의 정수여야 합니다."

if [ -L "$STATE_DIR" ]; then
  usage_error "--state-dir에는 심볼릭 링크를 사용할 수 없습니다."
fi

if [ ! -e "$STATE_DIR" ]; then
  if [ "$STATUS_MODE" -eq 1 ] || [ "$FINISH_MODE" -eq 1 ]; then
    runtime_error "상태 폴더가 없습니다: $STATE_DIR"
  fi
  mkdir -m 700 "$STATE_DIR" ||
    runtime_error "상태 폴더를 만들 수 없습니다: $STATE_DIR"
fi

[ -d "$STATE_DIR" ] || usage_error "--state-dir는 폴더여야 합니다."
chmod 700 "$STATE_DIR" ||
  runtime_error "상태 폴더 권한을 제한할 수 없습니다."

STATE_DIR="$(cd "$STATE_DIR" 2>/dev/null && pwd -P)"
[ -n "$STATE_DIR" ] || runtime_error "상태 폴더 경로를 확인할 수 없습니다."

MARKER_FILE="$STATE_DIR/.tiki-taka-state"
HOST_FILE="$STATE_DIR/host"
REPO_FILE="$STATE_DIR/repo"
MAX_FILE="$STATE_DIR/max-exchanges"
COUNT_FILE="$STATE_DIR/exchange-count"
SESSION_FILE="$STATE_DIR/session-id"
MODEL_FILE="$STATE_DIR/active-model"
UNCERTAIN_FILE="$STATE_DIR/uncertain"
LOCK_DIR="$STATE_DIR/.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  runtime_error "같은 상태 폴더를 다른 호출이 사용 중입니다."
fi
LOCK_HELD=1
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -f "$MARKER_FILE" ]; then
  MARKER_VALUE="$(cat "$MARKER_FILE" 2>/dev/null)"
  [ "$MARKER_VALUE" = "tiki-taka-state-v1" ] ||
    runtime_error "알 수 없는 상태 폴더 형식입니다."

  STORED_HOST="$(cat "$HOST_FILE" 2>/dev/null)" ||
    runtime_error "저장된 호스트 정보를 읽을 수 없습니다."
  [ "$STORED_HOST" = "$HOST" ] ||
    runtime_error "처음 지정한 호스트와 현재 호스트가 다릅니다."

  STORED_MAX="$(cat "$MAX_FILE" 2>/dev/null)" ||
    runtime_error "저장된 교환 한도를 읽을 수 없습니다."
  valid_exchange_limit "$STORED_MAX" ||
    runtime_error "저장된 교환 한도가 올바르지 않습니다."

  EXCHANGE_COUNT="$(cat "$COUNT_FILE" 2>/dev/null)" ||
    runtime_error "저장된 교환 수를 읽을 수 없습니다."
  valid_nonnegative_integer "$EXCHANGE_COUNT" ||
    runtime_error "저장된 교환 수가 올바르지 않습니다."

  if [ "$STATUS_MODE" -eq 0 ] && [ "$FINISH_MODE" -eq 0 ]; then
    CANONICAL_REPO="$(cd "$REPO" 2>/dev/null && pwd -P)"
    [ -n "$CANONICAL_REPO" ] ||
      runtime_error "작업 디렉터리를 확인할 수 없습니다: $REPO"

    STORED_REPO="$(cat "$REPO_FILE" 2>/dev/null)" ||
      runtime_error "저장된 작업 디렉터리를 읽을 수 없습니다."
    [ "$STORED_REPO" = "$CANONICAL_REPO" ] ||
      runtime_error "처음 지정한 작업 디렉터리와 현재 경로가 다릅니다."
    REPO="$CANONICAL_REPO"

    if [ "$MAX_GIVEN" -eq 1 ] && [ "$MAX_EXCHANGES" != "$STORED_MAX" ]; then
      runtime_error "처음 지정한 교환 한도와 현재 값이 다릅니다."
    fi
    MAX_EXCHANGES="$STORED_MAX"
  fi
else
  if [ "$STATUS_MODE" -eq 1 ] || [ "$FINISH_MODE" -eq 1 ]; then
    runtime_error "tiki-taka 상태 폴더가 아닙니다."
  fi

  EXTRA_ENTRY="$(find "$STATE_DIR" -mindepth 1 -maxdepth 1 \
    ! -name .lock -print -quit)"
  [ -z "$EXTRA_ENTRY" ] ||
    runtime_error "새 상태 폴더는 비어 있어야 합니다."

  CANONICAL_REPO="$(cd "$REPO" 2>/dev/null && pwd -P)"
  [ -n "$CANONICAL_REPO" ] ||
    runtime_error "작업 디렉터리를 확인할 수 없습니다: $REPO"
  REPO="$CANONICAL_REPO"
  EXCHANGE_COUNT=0

  umask 077
  printf '%s\n' "tiki-taka-state-v1" > "$MARKER_FILE"
  printf '%s\n' "$HOST" > "$HOST_FILE"
  printf '%s\n' "$REPO" > "$REPO_FILE"
  printf '%s\n' "$MAX_EXCHANGES" > "$MAX_FILE"
  printf '%s\n' "$EXCHANGE_COUNT" > "$COUNT_FILE"
fi

if [ "$STATUS_MODE" -eq 1 ]; then
  SESSION_ID="없음"
  ACTIVE_MODEL="없음"
  STATE_STATUS="준비"

  if [ -s "$SESSION_FILE" ]; then
    SESSION_ID="$(cat "$SESSION_FILE")"
  fi
  if [ -s "$MODEL_FILE" ]; then
    ACTIVE_MODEL="$(cat "$MODEL_FILE")"
  fi
  if [ -s "$UNCERTAIN_FILE" ]; then
    STATE_STATUS="불확실"
  fi

  echo "host=$HOST session_id=$SESSION_ID model=$ACTIVE_MODEL"
  echo "exchanges=$EXCHANGE_COUNT/$STORED_MAX state=$STATE_STATUS"
  exit 0
fi

if [ "$FINISH_MODE" -eq 1 ]; then
  UNEXPECTED="$(find "$STATE_DIR" -mindepth 1 -maxdepth 1 \
    ! -name .lock \
    ! -name .tiki-taka-state \
    ! -name host \
    ! -name repo \
    ! -name max-exchanges \
    ! -name exchange-count \
    ! -name session-id \
    ! -name active-model \
    ! -name uncertain \
    -print -quit)"
  [ -z "$UNEXPECTED" ] ||
    runtime_error "알 수 없는 파일이 있어 상태 폴더를 지우지 않았습니다."

  rm -f "$MARKER_FILE" "$HOST_FILE" "$REPO_FILE" "$MAX_FILE" \
    "$COUNT_FILE" "$SESSION_FILE" "$MODEL_FILE" "$UNCERTAIN_FILE" ||
    runtime_error "상태 파일을 지울 수 없습니다."
  rmdir "$LOCK_DIR" ||
    runtime_error "상태 잠금을 지울 수 없습니다."
  LOCK_HELD=0
  rmdir "$STATE_DIR" ||
    runtime_error "상태 폴더를 지울 수 없습니다."
  echo "토론 상태를 정리했습니다."
  exit 0
fi

if [ -s "$UNCERTAIN_FILE" ]; then
  runtime_error "이 상태는 응답 수신 여부가 불확실합니다. 새 복구 상태를 사용하세요."
fi

if [ "$EXCHANGE_COUNT" -ge "$MAX_EXCHANGES" ]; then
  runtime_error "최대 $MAX_EXCHANGES교환에 도달했습니다."
fi

CALL_DIR="$(mktemp -d "$STATE_DIR/.call.XXXXXX")" ||
  runtime_error "호출용 임시 폴더를 만들 수 없습니다."
PROMPT_FILE="$CALL_DIR/prompt.txt"
OUTPUT_FILE="$CALL_DIR/output.txt"
EVENTS_FILE="$CALL_DIR/events.jsonl"
LOG_FILE="$CALL_DIR/participant.log"
RETRY_FILE="$CALL_DIR/retry.txt"

cat > "$PROMPT_FILE"
if [ ! -s "$PROMPT_FILE" ]; then
  usage_error "표준 입력으로 프롬프트를 전달해야 합니다."
fi

SESSION_ID=""
ACTIVE_MODEL=""

if [ -s "$SESSION_FILE" ]; then
  SESSION_ID="$(cat "$SESSION_FILE")"
fi

if [ "$HOST" = "claude" ]; then
  if [ -z "$SESSION_ID" ]; then
    if ! (
      cd "$REPO" &&
      codex exec \
        -m "$CODEX_MODEL" \
        -c model_reasoning_effort="$CODEX_EFFORT" \
        -s read-only \
        -C "$REPO" \
        --json \
        -o "$OUTPUT_FILE" \
        - < "$PROMPT_FILE" > "$EVENTS_FILE" 2> "$LOG_FILE"
    ); then
      mark_uncertain "Codex 첫 호출의 처리 여부를 확인할 수 없습니다."
      echo "Codex 첫 호출 실패" >&2
      show_failure_log
      exit 1
    fi

    SESSION_ID="$(extract_codex_session "$EVENTS_FILE")"
    if [ $? -ne 0 ] || [ -z "$SESSION_ID" ]; then
      mark_uncertain "Codex 대화 식별자를 확인할 수 없습니다."
      runtime_error "Codex 대화 식별자를 읽지 못했습니다."
    fi
  else
    if ! (
      cd "$REPO" &&
      codex exec resume \
        -m "$CODEX_MODEL" \
        -c model_reasoning_effort="$CODEX_EFFORT" \
        -c 'sandbox_mode="read-only"' \
        --json \
        -o "$OUTPUT_FILE" \
        "$SESSION_ID" \
        - < "$PROMPT_FILE" > "$EVENTS_FILE" 2> "$LOG_FILE"
    ); then
      mark_uncertain "Codex 재개 호출의 처리 여부를 확인할 수 없습니다."
      echo "Codex 세션 재개 실패" >&2
      show_failure_log
      exit 1
    fi
  fi
  ACTIVE_MODEL="$CODEX_MODEL"
else
  if [ -z "$SESSION_ID" ]; then
    SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')" ||
      runtime_error "Claude 대화 식별자를 만들 수 없습니다."
    ACTIVE_MODEL="$CLAUDE_MODEL"

    if ! (
      cd "$REPO" &&
      claude -p \
        --session-id "$SESSION_ID" \
        --model "$CLAUDE_MODEL" \
        --fallback-model "$CLAUDE_FALLBACK" \
        --effort "$CLAUDE_EFFORT" \
        --permission-mode plan \
        < "$PROMPT_FILE" > "$OUTPUT_FILE" 2> "$LOG_FILE"
    ); then
      mark_uncertain "Claude 첫 호출의 처리 여부를 확인할 수 없습니다."
      echo "Claude 첫 호출 실패" >&2
      show_failure_log
      exit 1
    fi
  else
    ACTIVE_MODEL="$CLAUDE_MODEL"
    if [ -s "$MODEL_FILE" ]; then
      ACTIVE_MODEL="$(cat "$MODEL_FILE")"
    fi

    case "$ACTIVE_MODEL" in
      "$CLAUDE_MODEL")
        if ! (
          cd "$REPO" &&
          claude -p \
            --resume "$SESSION_ID" \
            --model "$CLAUDE_MODEL" \
            --fallback-model "$CLAUDE_FALLBACK" \
            --effort "$CLAUDE_EFFORT" \
            --permission-mode plan \
            < "$PROMPT_FILE" > "$OUTPUT_FILE" 2> "$LOG_FILE"
        ); then
          mark_uncertain "Claude 재개 호출의 처리 여부를 확인할 수 없습니다."
          echo "Claude 세션 재개 실패" >&2
          show_failure_log
          exit 1
        fi
        ;;
      "$CLAUDE_FALLBACK")
        if ! (
          cd "$REPO" &&
          claude -p \
            --resume "$SESSION_ID" \
            --model "$CLAUDE_FALLBACK" \
            --effort "$CLAUDE_EFFORT" \
            --permission-mode plan \
            < "$PROMPT_FILE" > "$OUTPUT_FILE" 2> "$LOG_FILE"
        ); then
          mark_uncertain "Claude 대체 모델 재개의 처리 여부를 확인할 수 없습니다."
          echo "Claude 대체 모델 세션 재개 실패" >&2
          show_failure_log
          exit 1
        fi
        ;;
      *)
        runtime_error "저장된 Claude 모델이 허용된 값과 다릅니다."
        ;;
    esac
  fi

  if [ "$ACTIVE_MODEL" = "$CLAUDE_MODEL" ] && quota_message_found; then
    echo "Claude Fable 한도 감지, 같은 세션을 Opus로 재개" >&2
    printf '%s\n' \
      "앞선 요청은 모델 한도 안내 때문에 처리되지 않았습니다." \
      "같은 세션의 바로 앞 사용자 요청에 답하세요. 요청 전체를 되풀이하지 마세요." \
      > "$RETRY_FILE"

    if ! (
      cd "$REPO" &&
      claude -p \
        --resume "$SESSION_ID" \
        --model "$CLAUDE_FALLBACK" \
        --effort "$CLAUDE_EFFORT" \
        --permission-mode plan \
        < "$RETRY_FILE" > "$OUTPUT_FILE" 2>> "$LOG_FILE"
    ); then
      mark_uncertain "Claude 대체 모델 재개의 처리 여부를 확인할 수 없습니다."
      echo "Claude 대체 모델 실행 실패" >&2
      show_failure_log
      exit 1
    fi
    ACTIVE_MODEL="$CLAUDE_FALLBACK"
  fi
fi

if [ ! -s "$OUTPUT_FILE" ]; then
  mark_uncertain "반대쪽 응답이 비어 있어 처리 여부를 확인할 수 없습니다."
  runtime_error "반대쪽 에이전트가 빈 응답을 반환했습니다."
fi

printf '%s\n' "$SESSION_ID" > "$SESSION_FILE"
printf '%s\n' "$ACTIVE_MODEL" > "$MODEL_FILE"
EXCHANGE_COUNT=$((EXCHANGE_COUNT + 1))
printf '%s\n' "$EXCHANGE_COUNT" > "$COUNT_FILE"

cat "$OUTPUT_FILE"
