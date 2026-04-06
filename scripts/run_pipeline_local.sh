#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PIPELINE_API_DEFAULT="${VITE_PIPELINE_API_BASE_URL:-http://127.0.0.1:8000}"
PRODUCT_API_DEFAULT="${VITE_API_BASE_URL:-https://airlineassistantvoiceagent.up.railway.app}"
RESET_COLOR=$'\033[0m'
GRAY_COLOR=$'\033[90m'
YELLOW_COLOR=$'\033[93m'
BLUE_COLOR=$'\033[1;96m'
GREEN_COLOR=$'\033[1;92m'
PURPLE_COLOR=$'\033[95m'

TASK_SLUG=""
TARGET_SCORE=8
MAX_ITERATIONS=5
REVIEW_MODEL="openai:gpt-5.4"
FIXER_MODEL="openai:gpt-5.4"
AUTO_APPROVE=true
SKIP_FIXTURE_RESET=true
POLL_INTERVAL=2
PIPELINE_API="$PIPELINE_API_DEFAULT"
PRODUCT_API="$PRODUCT_API_DEFAULT"

LAST_EVENT_INDEX=0
LAST_STAGE_KEY=""
LAST_APPROVAL_ITERATION=""
LAST_APPROVAL_MESSAGE=""

usage() {
  cat <<EOF
Usage: ./scripts/run_pipeline_local.sh --task <slug> [options]

Options:
  --task <slug>             Task slug to run. Required.
  --target <score>          Target score. Default: $TARGET_SCORE
  --iterations <count>      Max iterations. Default: $MAX_ITERATIONS
  --review-model <model>    Review model. Default: $REVIEW_MODEL
  --fixer-model <model>     Fixer model. Default: $FIXER_MODEL
  --auto-approve            Auto-approve each waiting iteration.
  --reset-fixtures          Ignored. Fixture reset is permanently disabled.
  --pipeline-api <url>      Local pipeline API base. Default: $PIPELINE_API_DEFAULT
  --product-api <url>       Product backend API base. Default: $PRODUCT_API_DEFAULT
  --poll-interval <sec>     Poll interval in seconds. Default: $POLL_INTERVAL
  --help                    Show this help.
EOF
}

require_arg() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "$flag requires a value." >&2
    usage >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      require_arg "$1" "${2:-}"
      TASK_SLUG="${2:-}"
      shift 2
      ;;
    --target)
      require_arg "$1" "${2:-}"
      TARGET_SCORE="${2:-}"
      shift 2
      ;;
    --iterations)
      require_arg "$1" "${2:-}"
      MAX_ITERATIONS="${2:-}"
      shift 2
      ;;
    --review-model)
      require_arg "$1" "${2:-}"
      REVIEW_MODEL="${2:-}"
      shift 2
      ;;
    --fixer-model)
      require_arg "$1" "${2:-}"
      FIXER_MODEL="${2:-}"
      shift 2
      ;;
    --auto-approve)
      AUTO_APPROVE=true
      shift
      ;;
    --reset-fixtures)
      SKIP_FIXTURE_RESET=true
      shift
      ;;
    --pipeline-api)
      require_arg "$1" "${2:-}"
      PIPELINE_API="${2:-}"
      shift 2
      ;;
    --product-api)
      require_arg "$1" "${2:-}"
      PRODUCT_API="${2:-}"
      shift 2
      ;;
    --poll-interval)
      require_arg "$1" "${2:-}"
      POLL_INTERVAL="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$TASK_SLUG" ]]; then
  echo "--task is required." >&2
  usage >&2
  exit 1
fi

if ! [[ "$TARGET_SCORE" =~ ^[0-9]+$ ]] || ! [[ "$MAX_ITERATIONS" =~ ^[0-9]+$ ]] || ! [[ "$POLL_INTERVAL" =~ ^[0-9]+$ ]]; then
  echo "--target, --iterations, and --poll-interval must be integers." >&2
  exit 1
fi

PIPELINE_API="${PIPELINE_API%/}"
PRODUCT_API="${PRODUCT_API%/}"

RESPONSE_BODY=""

request_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local response_file http_code

  response_file="$(mktemp)"
  if [[ -n "$body" ]]; then
    http_code="$(curl -sS -X "$method" "$url" -H "Content-Type: application/json" -d "$body" -o "$response_file" -w "%{http_code}")"
  else
    http_code="$(curl -sS -X "$method" "$url" -o "$response_file" -w "%{http_code}")"
  fi
  RESPONSE_BODY="$(cat "$response_file")"
  rm -f "$response_file"

  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    echo "Request failed: $method $url (HTTP $http_code)" >&2
    if [[ -n "$RESPONSE_BODY" ]]; then
      echo "$RESPONSE_BODY" >&2
    fi
    return 1
  fi
}

print_stage() {
  local title="$1"
  echo
  echo "== $title =="
}

print_step() {
  echo "- $1"
}

print_colored_step() {
  local color="$1"
  local message="$2"
  printf "%b- %s%b\n" "$color" "$message" "$RESET_COLOR"
}

print_colored_block() {
  local color="$1"
  local prefix="$2"
  local text="$3"
  local first_line=true
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$first_line" == true ]]; then
      printf "%b- %s%s%b\n" "$color" "$prefix" "$line" "$RESET_COLOR"
      first_line=false
    else
      printf "%b  %s%b\n" "$color" "$line" "$RESET_COLOR"
    fi
  done <<< "$text"
}

decode_json_string() {
  local json_string="$1"
  JSON_STRING="$json_string" python3 - <<'PY'
import json
import os
print(json.loads(os.environ["JSON_STRING"]))
PY
}

pipeline_summary_field() {
  local json_payload="$1"
  local field="$2"
  JSON_PAYLOAD="$json_payload" python3 -c 'import json,os,sys; payload=json.loads(os.environ["JSON_PAYLOAD"])["payload"]; value=payload.get(sys.argv[1], ""); print("" if value is None else value)' "$field"
}

pipeline_latest_result_field() {
  local json_payload="$1"
  local field="$2"
  JSON_PAYLOAD="$json_payload" python3 -c 'import json,os,sys; payload=json.loads(os.environ["JSON_PAYLOAD"])["payload"]; iterations=payload.get("iterations") or []; latest=iterations[-1] if iterations else {}; results=latest.get("task_results") or []; result=results[-1] if results else {}; value=result.get(sys.argv[1], ""); print("" if value is None else value)' "$field"
}

validate_task_exists() {
  TASKS_JSON_PAYLOAD="$1" python3 - "$TASK_SLUG" <<'PY'
import json, os, sys
task_slug = sys.argv[1]
tasks = json.loads(os.environ["TASKS_JSON_PAYLOAD"])
slugs = [task.get("slug") for task in tasks]
if task_slug not in slugs:
    print("Available tasks:", ", ".join(filter(None, slugs)), file=sys.stderr)
    raise SystemExit(1)
PY
}

emit_new_events() {
  local events_json="$1"
  local events_file
  local line index stage iteration event_type role message_json transcript_json details_json
  local field_sep

  field_sep=$'\x1f'
  events_file="$(mktemp)"

  EVENTS_JSON_PAYLOAD="$events_json" python3 - "$LAST_EVENT_INDEX" <<'PY' >"$events_file"
import json, sys
import os

start = int(sys.argv[1])
events = json.loads(os.environ["EVENTS_JSON_PAYLOAD"])

def stage_for(event_type: str) -> str:
    if event_type == "pipeline_started":
        return "Start Pipeline"
    if event_type in {
        "iteration_started",
        "testing_started",
        "fixture_reset_skipped",
        "task_started",
        "run_started",
        "run_finished",
        "user_turn",
        "customer_reply",
        "transcript_turn",
        "conversation_finalizing",
        "task_finished",
        "testing_complete",
    }:
        return "Testing"
    if event_type in {
        "evaluation_started",
        "evaluation_complete",
        "elevenlabs_analysis",
        "evaluation_criterion",
        "evaluation_finding",
        "evaluation_error",
        "refinement_gate",
    }:
        return "Evaluation"
    if event_type in {
        "refinement_started",
        "root_cause_complete",
        "refinement_error",
    }:
        return "Refinement Analysis"
    if event_type in {
        "fix_plan_validation_started",
        "fix_plan_validation_failed",
        "fix_plan_repair_started",
        "fix_plan_repair_finished",
        "fix_plan_ready",
        "fixer_summary",
        "fixer_expected_improvement",
        "fixer_edit",
    }:
        return "Fix Planning"
    if event_type == "approval_required":
        return "Approval"
    if event_type in {"code_apply_started", "code_apply_change", "code_apply_finished", "code_apply_noop"}:
        return "Code Change"
    if event_type in {
        "agent_sync_started",
        "agent_sync_progress",
        "agent_sync_finished",
        "agent_sync_failed",
        "git_commit_finished",
        "git_push_started",
        "git_push_progress",
        "git_push_finished",
        "git_push_skipped",
        "deploy_wait_started",
        "deploy_wait_health_check",
        "deploy_wait_progress",
        "deploy_verified",
        "deploy_skipped",
    }:
        return "Sync / Push / Deploy"
    if event_type == "iteration_complete":
        return "Iteration Result"
    if event_type in {"pipeline_complete", "pipeline_failed", "pipeline_blocked"}:
        return "Final Summary"
    return "Pipeline"

for idx, event in enumerate(events[start:], start=start + 1):
    event_type = str(event.get("type") or "")
    stage = stage_for(event_type)
    iteration = event.get("iteration")
    iteration_text = "" if iteration is None else str(iteration)
    payload = event.get("payload") or {}
    runtime_payload = payload.get("event_payload") or {}
    role = str(event.get("role") or payload.get("role") or runtime_payload.get("role") or "")
    message_json = json.dumps(str(event.get("message") or ""))
    transcript_json = json.dumps(
        event.get("transcript")
        or payload.get("transcript")
        or runtime_payload.get("transcript")
        or []
    )
    details = {}
    for key in (
        "task",
        "category",
        "summary",
        "verification_command",
        "edit_count",
        "invalid_count",
        "repaired_count",
        "edit_index",
        "path",
        "selector_type",
        "selector_value",
        "changed_paths",
        "branch_name",
        "commit_sha",
        "deployed_commit_sha",
        "attempt",
        "elapsed_seconds",
        "timeout_seconds",
        "pid",
        "health_ready",
        "health_status",
        "health_url",
        "phase",
        "planned_changed_paths",
        "requires_agent_sync",
        "requires_remote_deploy",
        "error",
        "stderr",
        "stdout",
        "before_content",
        "after_content",
        "reset_mode",
        "reset_applied",
        "overall_score",
        "goal_achieved",
        "score",
        "criterion",
        "title",
        "detail",
        "stage",
        "blocked_paths",
    ):
        value = event.get(key)
        if value in (None, "", [], {}):
            value = payload.get(key)
        if value in (None, "", [], {}):
            value = runtime_payload.get(key)
        if value not in (None, "", [], {}):
            details[key] = value
    details_json = json.dumps(details)
    print(f"{idx}\x1f{stage}\x1f{iteration_text}\x1f{event_type}\x1f{role}\x1f{message_json}\x1f{transcript_json}\x1f{details_json}")
PY

  while IFS="$field_sep" read -r index stage iteration event_type role message_json transcript_json details_json; do
    [[ -z "$index" ]] && continue
    LAST_EVENT_INDEX="$index"
    if [[ "$event_type" == "approval_required" && -n "$message_json" ]]; then
      LAST_APPROVAL_MESSAGE="$(decode_json_string "$message_json")"
    fi
    local stage_key="${iteration}|${stage}"
    if [[ "$stage_key" != "$LAST_STAGE_KEY" ]]; then
      echo
      if [[ -n "$iteration" ]]; then
        echo "[Iteration $iteration] $stage"
      else
        echo "[$stage]"
      fi
      LAST_STAGE_KEY="$stage_key"
    fi
    if [[ "$event_type" == "transcript_turn" && ( "$role" == "user" || "$role" == "user_transcript" ) ]]; then
      continue
    fi
    if [[ "$event_type" == "deploy_wait_health_check" ]]; then
      continue
    fi

    local message=""
    if [[ -n "$message_json" ]]; then
      message="$(decode_json_string "$message_json")"
    fi

    if [[ "$event_type" == "elevenlabs_analysis" ]]; then
      print_colored_block "$GREEN_COLOR" "" "$message"
      local effective_transcript_json="$transcript_json"
      if [[ -z "$effective_transcript_json" || "$effective_transcript_json" == "[]" ]] && [[ -n "$details_json" && "$details_json" != "{}" ]]; then
        effective_transcript_json="$(DETAILS_JSON="$details_json" python3 - <<'PY'
import json
import os

details = json.loads(os.environ["DETAILS_JSON"])
transcript = details.get("transcript")
print(json.dumps(transcript if isinstance(transcript, list) else []))
PY
)"
      fi
      if [[ -n "$effective_transcript_json" && "$effective_transcript_json" != "[]" ]]; then
        print_colored_step "$GREEN_COLOR" "ElevenLabs transcript:"
        while IFS="$field_sep" read -r item_kind transcript_role transcript_text_json; do
          [[ -z "$item_kind" ]] && continue
          local transcript_text=""
          if [[ -n "$transcript_text_json" ]]; then
            transcript_text="$(decode_json_string "$transcript_text_json")"
          fi
          case "$item_kind" in
            turn)
              case "$transcript_role" in
                agent)
                  print_colored_block "$BLUE_COLOR" "Agent: " "$transcript_text"
                  ;;
                user|user_transcript)
                  print_colored_block "$YELLOW_COLOR" "User: " "$transcript_text"
                  ;;
                *)
                  print_colored_block "$GRAY_COLOR" "Transcript: " "$transcript_text"
                  ;;
              esac
              ;;
            tool_call)
              print_colored_block "$PURPLE_COLOR" "Tool call: " "$transcript_text"
              ;;
            tool_result)
              print_colored_block "$GREEN_COLOR" "Tool result: " "$transcript_text"
              ;;
          esac
        done < <(
          TRANSCRIPT_JSON="$effective_transcript_json" python3 - <<'PY'
import json
import os

field_sep = "\x1f"


def one_line(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def pretty_json_block(value, *, max_lines=40):
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except Exception:
        return one_line(raw)
    formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
    lines = formatted.splitlines()
    if len(lines) > max_lines:
        remaining = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... ({remaining} more line{'s' if remaining != 1 else ''})"]
    return "\n".join(lines)


def emit_record(kind, role, text):
    print(f"{kind}{field_sep}{role}{field_sep}{json.dumps(text)}")


for item in json.loads(os.environ["TRANSCRIPT_JSON"]):
    role = str(item.get("role") or "")
    text = str(item.get("message") or item.get("text") or "").strip()
    if text:
        emit_record("turn", role, text)

    for tool_call in item.get("tool_calls") or []:
        tool_name = one_line(tool_call.get("tool_name")) or "unknown_tool"
        tool_type = one_line(tool_call.get("type"))
        params = pretty_json_block(tool_call.get("params_as_json"))
        tool_details = tool_call.get("tool_details") or {}
        method = one_line(tool_details.get("method"))
        url = one_line(tool_details.get("url"))
        parts = [tool_name]
        if method:
            parts.append(method)
        if url:
            parts.append(url)
        elif tool_type:
            parts.append(tool_type)
        if params:
            emit_record("tool_call", role, f"{' | '.join(parts)}\nparams:\n{params}")
        else:
            emit_record("tool_call", role, " | ".join(parts))

    for tool_result in item.get("tool_results") or []:
        tool_name = one_line(tool_result.get("tool_name")) or "unknown_tool"
        status = "error" if tool_result.get("is_error") else "ok"
        latency = tool_result.get("tool_latency_secs")
        latency_text = ""
        if latency is not None:
            try:
                latency_text = f"{float(latency):.3f}s"
            except (TypeError, ValueError):
                latency_text = one_line(latency)
        result_value = pretty_json_block(tool_result.get("result_value"))
        parts = [tool_name, status]
        if latency_text:
            parts.append(f"latency={latency_text}")
        if result_value:
            emit_record("tool_result", role, f"{' | '.join(parts)}\nresult:\n{result_value}")
        else:
            emit_record("tool_result", role, " | ".join(parts))
PY
        )
      fi
      continue
    fi

    if [[ -n "$message" ]]; then
      if [[ "$event_type" == "user_turn" || "$event_type" == "customer_reply" || "$message" == User:* || "$message" == Customer:* ]]; then
        print_colored_block "$YELLOW_COLOR" "" "$message"
      elif [[ "$event_type" == "transcript_turn" && ( "$role" == "agent" || "$message" == Agent:* ) ]]; then
        print_colored_block "$BLUE_COLOR" "" "$message"
      elif [[ "$event_type" == "agent_sync_progress" || "$event_type" == "git_push_progress" || "$event_type" == "deploy_wait_started" || "$event_type" == "deploy_wait_health_check" || "$event_type" == "deploy_wait_progress" || "$event_type" == "deploy_verified" ]]; then
        print_colored_block "$GREEN_COLOR" "" "$message"
      else
        print_colored_block "$GRAY_COLOR" "" "$message"
      fi
    else
      print_colored_step "$GRAY_COLOR" "$event_type"
    fi

    if [[ "$event_type" == "code_apply_change" && -n "$details_json" && "$details_json" != "{}" ]]; then
      DETAILS_JSON="$details_json" python3 - <<'PY' | while IFS= read -r detail_line; do
import json
import os

details = json.loads(os.environ["DETAILS_JSON"])

def compact_block(text: str | None, limit: int = 12) -> str:
    if not text:
        return ""
    lines = text.strip("\n").splitlines()
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = lines[:limit] + [f"... ({hidden} more line{'s' if hidden != 1 else ''})"]
    return "\n".join(lines)

path = details.get("path", "")
selector_type = details.get("selector_type", "")
selector_value = details.get("selector_value", "")
before_content = compact_block(details.get("before_content"))
after_content = compact_block(details.get("after_content"))

if path:
    print("***********")
    print(f"  file: {path}")
if selector_type or selector_value:
    print(f"  selector: {selector_type}:{selector_value}")
if before_content:
    print("  before:")
    for line in before_content.splitlines():
        print(f"    {line}")
if after_content:
    print("  after:")
    for line in after_content.splitlines():
        print(f"    {line}")
if path or selector_type or selector_value or before_content or after_content:
    print("***********")
PY
        [[ -n "$detail_line" ]] && printf "%b%s%b\n" "$GRAY_COLOR" "$detail_line" "$RESET_COLOR"
      done
      continue
    fi

    if [[ -n "$details_json" && "$details_json" != "{}" ]]; then
      DETAILS_JSON="$details_json" python3 - <<'PY' | while IFS= read -r detail_line; do
import json
import os

details = json.loads(os.environ["DETAILS_JSON"])
label_map = {
    "task": "task",
    "category": "category",
    "summary": "summary",
    "verification_command": "verification",
    "edit_count": "edit count",
    "path": "path",
    "selector_type": "selector type",
    "selector_value": "selector",
    "changed_paths": "changed paths",
    "branch_name": "branch",
    "commit_sha": "commit",
    "deployed_commit_sha": "deployed commit",
    "attempt": "attempt",
    "elapsed_seconds": "elapsed seconds",
    "timeout_seconds": "timeout seconds",
    "pid": "pid",
    "health_ready": "health ready",
    "health_status": "health status",
    "health_url": "health url",
    "phase": "phase",
    "planned_changed_paths": "planned changed paths",
    "requires_agent_sync": "requires agent sync",
    "requires_remote_deploy": "requires deploy",
    "error": "error",
    "stderr": "stderr",
    "stdout": "stdout",
    "before_content": "before",
    "after_content": "after",
    "reset_mode": "reset mode",
    "reset_applied": "reset applied",
    "overall_score": "overall score",
    "goal_achieved": "goal achieved",
    "score": "score",
    "criterion": "criterion",
    "title": "title",
    "detail": "detail",
    "stage": "stage",
    "blocked_paths": "blocked paths",
}
for key, value in details.items():
    label = label_map.get(key, key.replace("_", " "))
    if isinstance(value, list):
        rendered = ", ".join(str(item) for item in value)
    else:
        rendered = str(value).strip().replace("\n", " | ")
    print(f"  {label}: {rendered}")
PY
        [[ -n "$detail_line" ]] && printf "%b%s%b\n" "$GRAY_COLOR" "$detail_line" "$RESET_COLOR"
      done
    fi
  done <"$events_file"

  rm -f "$events_file"
}

approve_iteration() {
  local pipeline_id="$1"
  request_json "POST" "$PIPELINE_API/api/testing/pipelines/$pipeline_id/approve"
}

cancel_pipeline() {
  local pipeline_id="$1"
  request_json "POST" "$PIPELINE_API/api/testing/pipelines/$pipeline_id/cancel"
}

print_stage "Preflight"

for tool_name in curl python3 git; do
  if ! command -v "$tool_name" >/dev/null 2>&1; then
    echo "Missing required tool: $tool_name" >&2
    exit 1
  fi
  print_step "$tool_name: found"
done

GIT_STATUS="$(cd "$ROOT_DIR" && git status --short)"
if [[ -n "$GIT_STATUS" ]]; then
  echo "Git working tree is dirty:" >&2
  echo "$GIT_STATUS" >&2
  exit 1
fi
print_step "git working tree: clean"

request_json "GET" "$PIPELINE_API/api/testing/tasks"
validate_task_exists "$RESPONSE_BODY"
print_step "pipeline backend: reachable at $PIPELINE_API"
print_step "task '$TASK_SLUG': available"

request_json "GET" "$PRODUCT_API/api/meta"
print_step "product backend: reachable at $PRODUCT_API"

print_stage "Start Pipeline"

CREATE_BODY="$(python3 -c 'import json,sys; print(json.dumps({"task_slugs":[sys.argv[1]],"target_score":int(sys.argv[2]),"max_iterations":int(sys.argv[3]),"review_model":sys.argv[4],"fixer_model":sys.argv[5],"require_manual_approval":False,"skip_fixture_reset":sys.argv[6].lower()=="true"}))' "$TASK_SLUG" "$TARGET_SCORE" "$MAX_ITERATIONS" "$REVIEW_MODEL" "$FIXER_MODEL" "$SKIP_FIXTURE_RESET")"
request_json "POST" "$PIPELINE_API/api/testing/pipelines" "$CREATE_BODY"
PIPELINE_JSON="$RESPONSE_BODY"
PIPELINE_ID="$(pipeline_summary_field "$PIPELINE_JSON" "pipeline_id")"
BRANCH_NAME="$(pipeline_summary_field "$PIPELINE_JSON" "branch_name")"

print_step "pipeline id: $PIPELINE_ID"
print_step "branch: $BRANCH_NAME"
print_step "review model: $REVIEW_MODEL"
print_step "fixer model: $FIXER_MODEL"
if [[ "$AUTO_APPROVE" == true ]]; then
  print_step "approval mode: automatic"
else
  print_step "approval mode: manual"
fi
print_step "fixture reset: disabled"

while true; do
  request_json "GET" "$PIPELINE_API/api/testing/pipelines/$PIPELINE_ID"
  PIPELINE_JSON="$RESPONSE_BODY"
  request_json "GET" "$PIPELINE_API/api/testing/pipelines/$PIPELINE_ID/events"
  EVENTS_JSON="$RESPONSE_BODY"

  emit_new_events "$EVENTS_JSON"

  PIPELINE_STATUS="$(pipeline_summary_field "$PIPELINE_JSON" "status")"
  PIPELINE_STAGE="$(pipeline_summary_field "$PIPELINE_JSON" "stage")"
  CURRENT_ITERATION="$(pipeline_summary_field "$PIPELINE_JSON" "current_iteration")"

  if [[ "$PIPELINE_STATUS" == "waiting_approval" && "$CURRENT_ITERATION" != "$LAST_APPROVAL_ITERATION" ]]; then
    LAST_APPROVAL_ITERATION="$CURRENT_ITERATION"
    echo
    echo "[Iteration $CURRENT_ITERATION] Approval"
    if [[ "$AUTO_APPROVE" == true ]]; then
      print_step "auto-approving iteration $CURRENT_ITERATION"
      approve_iteration "$PIPELINE_ID"
    else
      if [[ -n "$LAST_APPROVAL_MESSAGE" ]]; then
        print_step "$LAST_APPROVAL_MESSAGE"
      fi
      read -r -p "Approve iteration $CURRENT_ITERATION and continue? [y/N]: " answer
      if [[ "$answer" =~ ^[Yy]$ ]]; then
        approve_iteration "$PIPELINE_ID"
        print_step "approved"
      else
        cancel_pipeline "$PIPELINE_ID"
        print_step "pipeline canceled"
        exit 1
      fi
    fi
  fi

  case "$PIPELINE_STATUS" in
    completed|failed|blocked_manual_fix|canceled)
      break
      ;;
  esac

  sleep "$POLL_INTERVAL"
done

print_stage "Final Summary"
FINAL_STATUS="$(pipeline_summary_field "$PIPELINE_JSON" "status")"
FINAL_STAGE="$(pipeline_summary_field "$PIPELINE_JSON" "stage")"
STOP_REASON="$(pipeline_summary_field "$PIPELINE_JSON" "stop_reason")"
LATEST_COMMIT_SHA="$(pipeline_summary_field "$PIPELINE_JSON" "latest_commit_sha")"
LATEST_DEPLOY_SHA="$(pipeline_summary_field "$PIPELINE_JSON" "latest_deploy_sha")"
LATEST_TASK_SLUG="$(pipeline_latest_result_field "$PIPELINE_JSON" "task_slug")"
LATEST_SCORE="$(pipeline_latest_result_field "$PIPELINE_JSON" "overall_score")"
LATEST_GOAL="$(pipeline_latest_result_field "$PIPELINE_JSON" "goal_achieved")"
LATEST_ROOT_CAUSE="$(pipeline_latest_result_field "$PIPELINE_JSON" "root_cause_category")"

print_step "pipeline id: $PIPELINE_ID"
print_step "status: $FINAL_STATUS"
print_step "stage: $FINAL_STAGE"
print_step "current iteration: $CURRENT_ITERATION"
print_step "task: ${LATEST_TASK_SLUG:-$TASK_SLUG}"
if [[ -n "$LATEST_SCORE" ]]; then
  print_step "latest score: $LATEST_SCORE/10"
fi
if [[ -n "$LATEST_GOAL" ]]; then
  print_step "goal achieved: $LATEST_GOAL"
fi
if [[ -n "$LATEST_ROOT_CAUSE" ]]; then
  print_step "root cause: $LATEST_ROOT_CAUSE"
fi
if [[ -n "$STOP_REASON" ]]; then
  print_step "stop reason: $STOP_REASON"
fi
if [[ -n "$BRANCH_NAME" ]]; then
  print_step "branch: $BRANCH_NAME"
fi
if [[ -n "$LATEST_COMMIT_SHA" ]]; then
  print_step "latest commit: $LATEST_COMMIT_SHA"
fi
if [[ -n "$LATEST_DEPLOY_SHA" ]]; then
  print_step "latest deploy: $LATEST_DEPLOY_SHA"
fi

if [[ "$FINAL_STATUS" != "completed" ]]; then
  exit 1
fi
