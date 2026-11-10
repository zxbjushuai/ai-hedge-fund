#!/usr/bin/env bash
set -euo pipefail

REPO="/home/zxbjushuai/codespace/ai-hedge-fund"
BRANCH="agent/daily"
ENV_FILE="/home/zxbjushuai/.config/ai-hedge-fund/agent.env"
BACKUP_ROOT="/home/zxbjushuai/.local/state/aihf-backups"
LOG_ROOT="$REPO/logs/agent"
DATE="$(date +%F)"
TS="$(date +%Y%m%d-%H%M%S)"
LOCK_FILE="/tmp/aihf-agent.lock"
PYTHON="$REPO/.venv/bin/python"
POETRY="/home/zxbjushuai/.local/bin/poetry"
CODEX="/usr/local/bin/codex"
HOST_HEALTH="http://127.0.0.1:8000/health"

mkdir -p "$LOG_ROOT" "$BACKUP_ROOT/$TS" "$REPO/docs/agent-daily"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "another agent run is active"
    exit 0
fi
DAILY_STATE="$(systemctl is-active aihf-daily.service || true)"
case "$DAILY_STATE" in
    active|activating|reloading)
        echo "daily pipeline is still running; skipping agent run"
        exit 0
        ;;
esac

RUN_LOG="$LOG_ROOT/run-$TS.log"
exec > >(tee -a "$RUN_LOG") 2>&1

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export PATH="/home/zxbjushuai/.local/bin:/usr/local/bin:/usr/bin:/bin"
PUSH_ENABLED="${PUSH_ENABLED:-0}"
DRY_RUN="${AIHF_AGENT_DRY_RUN:-0}"
CODEX_PROFILE="${AIHF_CODEX_PROFILE:-opencode-go-sub2api}"

REPORT="$REPO/docs/agent-daily/$DATE.md"
write_failure_report() {
    local reason="$1"
    if [ ! -f "$REPORT" ]; then
        printf '# %s 日报\n\n' "$DATE" >"$REPORT"
    fi
    {
        echo
        echo "---"
        echo "## 自动化运行摘要（$TS）"
        echo "- 结果: 失败（$reason）"
        echo "- Codex exit: ${CODEX_RC:-n/a}"
        echo "- 基线: ${BASE_TAG:-n/a}"
        echo "- 审计: ${AUDIT_LOG:-n/a}"
        echo "- 测试门禁: ${GATE_LOG:-n/a}"
        echo "- Codex 日志: ${CODEX_LOG:-n/a}"
        echo "- 最后消息: ${LAST_MSG:-n/a}"
    } >>"$REPORT"
}

cd "$REPO"
git switch "$BRANCH" >/dev/null

if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty before the run; refusing to continue"
    git status --short
    exit 1
fi

HOOK="$REPO/.git/hooks/pre-push"
cat >"$HOOK" <<'HOOK_EOF'
#!/usr/bin/env bash
if [ "${AIHF_ALLOW_PUSH:-0}" != "1" ]; then
    echo "push blocked: the agent wrapper pushes at most once per day" >&2
    exit 1
fi
exit 0
HOOK_EOF
chmod +x "$HOOK"

git fetch fork >/dev/null 2>&1 || true
if git ls-remote --exit-code --heads fork "$BRANCH" >/dev/null 2>&1; then
    git pull --ff-only fork "$BRANCH" || true
fi

BASE_TAG="backup-$TS"
git tag -f "$BASE_TAG" >/dev/null

"$PYTHON" "$REPO/scripts/agent_backup.py" "$BACKUP_ROOT/$TS" || true

AUDIT_LOG="$LOG_ROOT/audit-$TS.log"
{
    echo "== date =="
    date
    echo "== git =="
    git status --short
    git log --oneline -8
    echo "== health =="
    curl -sSf --max-time 5 "$HOST_HEALTH" || echo "HEALTH FAILED"
    echo
    echo "== services =="
    systemctl --no-pager --lines=0 is-active aihf-backend aihf-frontend || true
    echo "== latest sims =="
    curl -s --max-time 5 "http://127.0.0.1:8000/dashboard/sim/runs" | head -c 1500 || true
    echo
    echo "== todos =="
    grep -rn "TODO\|FIXME" hedge_fund research_app --include='*.py' --include='*.ts' --include='*.tsx' | head -40 || true
    echo "== disk =="
    df -h / | tail -1
    echo "== memory =="
    free -h | head -2
} >"$AUDIT_LOG" 2>&1

PROMPT="$LOG_ROOT/prompt-$TS.md"
cp "$REPO/docs/agent/daily-prompt.md" "$PROMPT"
{
    echo
    echo "## Run context"
    echo "- Date: $DATE"
    echo "- Timestamp: $TS"
    echo "- Branch: $BRANCH"
    echo "- Base tag: $BASE_TAG"
    echo "- Audit log: $AUDIT_LOG"
    echo "- Backlog: docs/agent/backlog.md"
    echo "- Universe: docs/agent/universe.txt"
    echo "- Full access is enabled. The wrapper will re-run tests after you finish."
    echo "- If tests fail, your work may be preserved in a WIP tag and reverted."
} >>"$PROMPT"

CODEX_LOG="$LOG_ROOT/codex-$TS.jsonl"
LAST_MSG="$LOG_ROOT/last-message-$TS.md"
if [ "$DRY_RUN" = "1" ]; then
    echo "dry run: skipping codex"
    CODEX_RC=0
else
    set +e
    timeout 10800 "$CODEX" exec \
        -p "$CODEX_PROFILE" \
        -C "$REPO" \
        --dangerously-bypass-approvals-and-sandbox \
        --ignore-rules \
        --json \
        -o "$LAST_MSG" \
        - <"$PROMPT" >"$CODEX_LOG" 2>&1
    CODEX_RC=$?
    set -e
fi
echo "codex exit=$CODEX_RC"

SALVAGED=0
if [ "$CODEX_RC" != "0" ]; then
    if [ -n "$(git status --porcelain)" ]; then
        git add -A
        git commit -m "wip(agent): $DATE automated work (codex exit $CODEX_RC)" >/dev/null || true
        git tag -f "wip-$TS" HEAD >/dev/null || true
    elif [ "$(git rev-list --count "$BASE_TAG"..HEAD)" != "0" ]; then
        git tag -f "wip-$TS" HEAD >/dev/null || true
    fi
    SALVAGED=1
    echo "codex failed with exit $CODEX_RC; keeping WIP and checking the gate"
fi

if git diff --name-only "$BASE_TAG" -- pyproject.toml poetry.lock | grep -q .; then
    "$POETRY" install --no-interaction >>"$RUN_LOG" 2>&1 || true
fi
if git diff --name-only "$BASE_TAG" -- research_app/frontend/package.json research_app/frontend/package-lock.json | grep -q .; then
    npm --prefix research_app/frontend ci >>"$RUN_LOG" 2>&1 || true
fi

GATE_LOG="$LOG_ROOT/gate-$TS.log"
GATE_OK=0
if {
    "$PYTHON" -m pytest research_app/backend hedge_fund -q &&
    npm --prefix research_app/frontend run test &&
    npm --prefix research_app/frontend run lint &&
    npm --prefix research_app/frontend run build
} >"$GATE_LOG" 2>&1; then
    GATE_OK=1
fi
echo "gate_ok=$GATE_OK"

if [ "$GATE_OK" != "1" ]; then
    if [ -n "$(git status --porcelain)" ]; then
        git add -A
        git commit -m "wip(agent): $DATE automated work (tests failing)" >/dev/null || true
        git tag -f "wip-$TS" HEAD >/dev/null || true
    elif [ "$(git rev-list --count "$BASE_TAG"..HEAD)" != "0" ]; then
        git tag -f "wip-$TS" HEAD >/dev/null || true
    fi
    git reset --hard "$BASE_TAG" >/dev/null 2>&1 || true
    write_failure_report "测试门禁未通过"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -m "chore(agent): daily update $DATE" >/dev/null || true
fi

if [ "$SALVAGED" = "1" ]; then
    LAST_SUBJECT="$(git log -1 --format=%s)"
    case "$LAST_SUBJECT" in
        wip\(agent\)*)
            git commit --amend -m "chore(agent): salvage tested work for $DATE after codex exit $CODEX_RC" >/dev/null || true
            ;;
    esac
    echo "salvaged tested work after codex exit $CODEX_RC"
fi

COMMITS="$(git rev-list --count "$BASE_TAG"..HEAD)"
if [ "$COMMITS" = "0" ]; then
    write_failure_report "没有产生提交"
    echo "no commits produced"
    exit 0
fi

PUSH_MARKER="$HOME/.local/state/aihf-last-push-date"
mkdir -p "$(dirname "$PUSH_MARKER")"
LAST_PUSH="$(cat "$PUSH_MARKER" 2>/dev/null || true)"
if [ "$PUSH_ENABLED" = "1" ]; then
    if [ "$LAST_PUSH" = "$DATE" ]; then
        echo "already pushed today ($DATE); skipping push"
    elif AIHF_ALLOW_PUSH=1 git push fork "$BRANCH"; then
        echo "$DATE" >"$PUSH_MARKER"
        echo "pushed to fork/$BRANCH"
    else
        echo "push failed (check the deploy key)"
    fi
else
    echo "push disabled (PUSH_ENABLED=0)"
fi

CHANGED="$(git diff --name-only "$BASE_TAG" HEAD)"
ROLLBACK=0
if echo "$CHANGED" | grep -qE '(^|/)pyproject\.toml$|(^|/)poetry\.lock$|(^|/)research_app/backend/.*\.py$'; then
    sudo systemctl restart aihf-backend || ROLLBACK=1
    sleep 3
    curl -sSf --max-time 5 "$HOST_HEALTH" >/dev/null || ROLLBACK=1
fi
if echo "$CHANGED" | grep -qE '(^|/)research_app/frontend/(src/|package(-lock)?\.json)'; then
    sudo systemctl restart aihf-frontend || true
fi
if [ "$ROLLBACK" = "1" ]; then
    git tag -f "failed-$TS" HEAD >/dev/null || true
    git reset --hard "$BASE_TAG" >/dev/null 2>&1 || true
    sudo systemctl restart aihf-backend || true
    sleep 3
    write_failure_report "提交后健康检查失败，已回滚"
    exit 1
fi

{
    echo
    echo "---"
    echo "## 自动化运行摘要（$TS）"
    echo "- 分支: $BRANCH"
    echo "- 基线: $BASE_TAG"
    echo "- 提交: $(git log -1 --oneline)"
    echo "- Codex exit: $CODEX_RC（非 0 时若门禁通过则 salvage）"
    echo "- 测试门禁: 通过（$GATE_LOG）"
    echo "- 审计: $AUDIT_LOG"
    echo "- Codex 日志: $CODEX_LOG"
    echo "- 最后消息: $LAST_MSG"
    echo "- 推送: $([ "$PUSH_ENABLED" = "1" ] && echo enabled || echo disabled)"
} >>"$REPORT"

echo "agent run complete: $(git log -1 --oneline)"
