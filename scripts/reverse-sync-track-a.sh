#!/usr/bin/env bash
#
# reverse-sync-track-a.sh — port the "Track A" upstream MCP feature PRs back into
# this provider repo (see CLAUDE.local.md → "Reverse-sync (upstream → this repo)").
#
# Track A = small, clean, non-overlapping feature PRs opened directly against
# music-assistant/server's inlined copy of this provider. This script does the
# MECHANICAL half only:
#   * rewrites upstream paths  (music_assistant/providers/fastmcp_server/ -> provider/,
#                               tests/providers/fastmcp_server/           -> tests/)
#   * rewrites test imports    (music_assistant.providers.fastmcp_server. -> provider.)
#   * attempts to apply each transformed diff, surfacing collisions as *.rej
#
# It deliberately does NOT commit. After it runs, a human lands the result through
# the normal feature flow: spec (specs/inprogress/<NNNN>), TDD green, CHANGELOG +
# VERSION bump, PR to dev, with a `Co-Authored-By:` trailer crediting the author.
#
# Usage:
#   scripts/reverse-sync-track-a.sh            # fetch + transform + apply (--reject)
#   scripts/reverse-sync-track-a.sh --check    # validate only, no working-tree changes
#   PRS="4391 4390" scripts/reverse-sync-track-a.sh   # override the PR set
#
# Requires: gh (authenticated), git, sed.

set -euo pipefail

REPO="music-assistant/server"
# Apply order matters: #4377 and #4392 both touch tools/queue.py. #4377 first
# (adds the ToolError import + set_repeat); #4392's duplicate import hunk then
# rejects on purpose — that .rej is the expected hand-reconciliation point.
PRS="${PRS:-4391 4390 4377 4392}"
BRANCH="${BRANCH:-reverse-sync/track-a}"
MODE="${1:-apply}"

# Reject unknown args so a mistyped flag (e.g. `--chek`) can't silently fall
# through to the mutating apply path.
case "$MODE" in
  apply | --check) ;;
  *)
    echo "ERROR: unknown argument '$MODE' — use '--check' (dry run) or no argument (apply)." >&2
    exit 2
    ;;
esac

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- transform: upstream diff (stdin) -> repo-local diff (stdout) ----------------
transform() {
  sed -E \
    -e 's#( a/| b/|^--- a/|^\+\+\+ b/)music_assistant/providers/fastmcp_server/#\1provider/#g' \
    -e 's#( a/| b/|^--- a/|^\+\+\+ b/)tests/providers/fastmcp_server/#\1tests/#g' \
    -e 's#\bmusic_assistant\.providers\.fastmcp_server\.#provider.#g'
}

# --- guard: surface hunks the transform could not safely handle -----------------
# Warns (does not abort) so a partially-mappable PR — e.g. a Copilot-review
# follow-up that edits strings.json / translations, which live inline in
# provider/config.py here — is loud instead of silently mis-applied.
guard_diff() {  # $1 = transformed diff file ; returns 1 if anything was flagged
  local f="$1" flagged=0 hits
  # 1. residual upstream paths in file headers => hunk targets a path outside the
  #    provider/ + tests/ mapping (strings.json maps to a file we don't have;
  #    music_assistant/translations/* doesn't map at all).
  hits="$(grep -nE '^(diff --git|---|\+\+\+) .*music_assistant/' "$f" || true)"
  if [[ -n "$hits" ]]; then
    echo "  ⚠ UNMAPPED upstream path(s) — reconcile by hand (likely strings.json /"
    echo "    translations → provider/config.py inline descriptions):"
    sed 's/^/      /' <<<"$hits"
    flagged=1
  fi
  # 2. forward-sync-unsafe module import. The fork rewrite only catches the
  #    `from provider.` form; `import provider.X [as Y]` slips through unrewritten
  #    and breaks upstream (no top-level `provider` package there).
  hits="$(grep -nE '^\+[[:space:]]*import[[:space:]]+provider\.' "$f" || true)"
  if [[ -n "$hits" ]]; then
    echo "  ⚠ forward-sync-unsafe import — rewrite to 'from provider.X import …':"
    sed 's/^/      /' <<<"$hits"
    flagged=1
  fi
  return "$flagged"
}

# --- guard: never operate on a dirty tree (forward-sync clobbers provider/ whole) -
if [[ "$MODE" != "--check" ]]; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: working tree not clean — commit or stash first." >&2
    exit 1
  fi
  git switch -c "$BRANCH" 2>/dev/null || git switch "$BRANCH"
  echo "On branch: $(git branch --show-current)"
fi

fail=0
for pr in $PRS; do
  echo "=== PR #$pr ==="
  gh pr diff "$pr" --repo "$REPO" | transform > "$WORK/$pr.diff"

  guard_diff "$WORK/$pr.diff" || fail=1

  if [[ "$MODE" == "--check" ]]; then
    # --check validates each diff against the PRISTINE tree independently, so the
    # known #4377<->#4392 queue.py collision is NOT exercised here (that surfaces
    # only on real sequential apply). A clean --check confirms the transform itself.
    if git apply --check --whitespace=nowarn "$WORK/$pr.diff" 2>"$WORK/$pr.err"; then
      echo "  transform OK — would apply against pristine tree"
    else
      echo "  WOULD NOT APPLY (context drift — likely needs D213 reverse-sync first):"
      sed 's/^/    /' "$WORK/$pr.err"
      fail=1
    fi
  else
    if git apply --reject --whitespace=nowarn "$WORK/$pr.diff"; then
      echo "  applied cleanly"
    else
      echo "  PARTIAL — rejected hunks written as *.rej (reconcile by hand)"
      fail=1
    fi
  fi
done

echo
if [[ "$MODE" == "--check" ]]; then
  echo "Check complete. (Real apply order: ${PRS} — expect one #4392 queue.py import .rej.)"
  exit "$fail"
fi

echo "Rejected hunks to reconcile:"
# find, not `git ls-files --exclude-standard`, so a developer's global
# core.excludesfile ignoring *.rej can't hide rejects from the summary.
find . -path ./.venv -prune -o -name '*.rej' -print | sed 's/^/  /' || true
echo
echo "Working-tree changes:"
git --no-pager diff --stat
cat <<'EOF'

Next (manual):
  1. One expected reject only: provider/tools/queue.py.rej is #4392's duplicate
     `from fastmcp.exceptions import ToolError` — #4377 already added that import,
     so just delete the .rej (no code change). Verified: the two get_active_queue
     edits (#4377 set_repeat doc mention + #4392 queue_id alias) land in separate
     hunks and coexist cleanly; ruff + the 26 affected tests pass as-is.
  2. rm -f provider/tools/*.rej tests/*.rej
  3. uv run ruff format provider/ tests/ && uv run ruff check provider/ tests/
  4. uv run pytest tests/test_players_tool.py tests/test_playback_tool.py \
       tests/test_set_repeat.py tests/test_prompts.py
  5. Add spec, bump VERSION, update CHANGELOG, commit with Co-Authored-By.
EOF
exit "$fail"
