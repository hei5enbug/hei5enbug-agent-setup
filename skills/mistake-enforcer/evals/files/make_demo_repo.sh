#!/bin/sh
# Create a small Git repository whose history repeats one mistake: a channel added to one list but not to the
# routing table that must match it. Usage: make_demo_repo.sh <empty target directory> [--single]
# With --single, the mistake happens only once.
set -eu

target=$1
mode=${2:-}
mkdir -p "$target"
cd "$target"
git init -q
git config user.name "Demo Author"
git config user.email "demo@example.com"
git config commit.gpgsign false

commit() {
  git add -A
  GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git commit -q -m "$2"
}

mkdir -p notify tests
cat > notify/channels.py <<'EOF'
CHANNELS = ["email"]
EOF
cat > notify/routes.py <<'EOF'
ROUTES = {"email": "smtp_worker"}


def route(channel):
    return ROUTES[channel]
EOF
cat > tests/test_routes.py <<'EOF'
from notify.routes import route


def test_email_routes_to_smtp():
    assert route("email") == "smtp_worker"
EOF
cat > AGENTS.md <<'EOF'
# Repository rules

- When you add a channel to `notify/channels.py`, add its route to `notify/routes.py`.
- Write commit subjects that say why the change is needed, not only what changed.
EOF
commit "2026-10-01T10:00:00" "feat: add email notifications"

cat > notify/channels.py <<'EOF'
CHANNELS = ["email", "sms"]
EOF
commit "2026-10-05T10:00:00" "feat: add sms channel"

cat > notify/routes.py <<'EOF'
ROUTES = {"email": "smtp_worker", "sms": "sms_worker"}


def route(channel):
    return ROUTES[channel]
EOF
commit "2026-10-06T10:00:00" "fix: add the sms route missing from the routing table"

if [ "$mode" != "--single" ]; then
  cat > notify/channels.py <<'EOF'
CHANNELS = ["email", "sms", "push"]
EOF
  commit "2026-10-12T10:00:00" "feat: add push channel"

  cat > notify/routes.py <<'EOF'
ROUTES = {"email": "smtp_worker", "sms": "sms_worker", "push": "push_worker"}


def route(channel):
    return ROUTES[channel]
EOF
  commit "2026-10-13T10:00:00" "fix: add the push route missing from the routing table"
fi

mkdir -p ../demo-notes
if [ "$mode" != "--single" ]; then
  cat > ../demo-notes/corrections.md <<'EOF'
# User corrections

- Session 2026-10-08, after commit subject "update files": "Say why the change is needed in the subject, not just
  which files changed."
- Session 2026-10-15, after commit subject "change config": "Again, the subject has to give the reason for the
  change."
- Session 2026-10-16, after a tab-indented YAML file: "Use spaces in YAML."
EOF
else
  cat > ../demo-notes/corrections.md <<'EOF'
# User corrections

- Session 2026-10-16, after a tab-indented YAML file: "Use spaces in YAML."
EOF
fi
