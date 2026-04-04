#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PIPELINE_API_DEFAULT="${VITE_PIPELINE_API_BASE_URL:-http://127.0.0.1:8000}"
PRODUCT_API_DEFAULT="${VITE_API_BASE_URL:-https://airlineassistantvoiceagent.up.railway.app}"

TASK_SLUG=""
TARGET_SCORE=8
MAX_ITERATIONS=5
REVIEW_MODEL="openai:gpt-5.4-mini"
FIXER_MODEL="openai:gpt-5.4-mini"
AUTO_APPROVE=false
POLL_INTERVAL=2
PIPELINE_API="$PIPELINE_API_DEFAULT"
PRODUCT_API="$PRODUCT_API_DEFAULT"

LAST_EVENT_INDEX=0
LAST_STAGE_KEY=""
LAST_APPROVAL_ITERATION=""

usage() {
  cat <<EOF
Usage: ./run_pipeline_local.sh --task <slug> [options]

Options:
  --task <slug>             Task slug to run. Required.
  --target <score>          Target score. Default: $TARGET_SCORE
  --iterations <count>      Max iterations. Default: $MAX_ITERATIONS
  --review-model <model>    Review model. Default: $REVIEW_MODEL
  --fixer-model <model>     Fixer model. Default: $FIXER_MODEL
  --auto-approve            Auto-approve each waiting iteration.
  --pipeline-api <url>      Local pipeline API base. Default: $PIPELINE_API_DEFAULT
  --product-api <url>       Product backend API base. Default: $PRODUCT_API_DEFAULT
  --poll-interval <sec>     Poll interval in seconds. Default: $POLL_INTERVAL
  --help                    Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK_SLUG="${2:-}"
      shift 2
      ;;
    --target)
      TARGET_SCORE="${2:-}"
      shift 2
      ;;
    --iterations)
      MAX_ITERATIONS="${2:-}"
      shift 2
      ;;
    --review-model)
      REVIEW_MODEL="${2:-}"
      shift 2
      ;;
    --fixer-model)
      FIXER_MODEL="${2:-}"
      shift 2
      ;;
    --auto-approve)
      AUTO_APPROVE=true
      shift
      ;;
    --pipeline-api)
      PIPELINE_API="${2:-}"
      shift 2
      ;;
    --product-api)
      PRODUCT_API="${2:-}"
      shift 2
      ;;
    --poll-interval)
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
  local line index stage iteration event_type message

  while IFS=$'\t' read -r index stage iteration event_type message; do
    [[ -z "$index" ]] && continue
    LAST_EVENT_INDEX="$index"
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
    if [[ -n "$message" ]]; then
      echo "- $message"
    else
      echo "- $event_type"
    fi
  done < <(
    EVENTS_JSON_PAYLOAD="$events_json" python3 - "$LAST_EVENT_INDEX" <<'PY'
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
        "task_finished",
        "testing_complete",
    }:
        return "Testing"
    if event_type in {
        "evaluation_started",
        "evaluation_complete",
        "evaluation_criterion",
        "evaluation_finding",
        "evaluation_error",
        "refinement_started",
        "critique_complete",
        "critic_verdict",
        "critic_criterion",
        "critic_finding",
        "critic_next_step",
        "root_cause_complete",
    }:
        return "Evaluation"
    if event_type in {
        "fix_plan_ready",
        "fixer_summary",
        "fixer_expected_improvement",
        "fixer_edit",
    }:
        return "Fix Planning"
    if event_type == "approval_required":
        return "Approval"
    if event_type in {"code_apply_started", "code_apply_finished"}:
        return "Code Change"
    if event_type in {
        "git_commit_finished",
        "git_push_finished",
        "git_push_skipped",
        "deploy_wait_started",
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
    message = str(event.get("message") or "").replace("\n", "\n  ")
    print(f"{idx}\t{stage}\t{iteration_text}\t{event_type}\t{message}")
PY
  )
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

CREATE_BODY="$(python3 -c 'import json,sys; print(json.dumps({"task_slugs":[sys.argv[1]],"target_score":int(sys.argv[2]),"max_iterations":int(sys.argv[3]),"review_model":sys.argv[4],"fixer_model":sys.argv[5],"require_manual_approval":True}))' "$TASK_SLUG" "$TARGET_SCORE" "$MAX_ITERATIONS" "$REVIEW_MODEL" "$FIXER_MODEL")"
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
      read -r -p "Approve iteration $CURRENT_ITERATION? [y/N]: " answer
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
