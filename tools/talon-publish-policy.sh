#!/usr/bin/env sh

# Shared publish-path policy for TALON's local-docs workflow.
#
# Return codes:
# - talon_is_blocked_remote_path PATH returns 0 when PATH must stay local-only.
# - It returns 1 when PATH may be promoted or pushed.

talon_is_blocked_remote_path() {
    talon_policy_path_lc=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')

    case "$talon_policy_path_lc" in
        changelog.md|readme.md|*-user-guide.pdf)
            return 1
            ;;
    esac

    case "$talon_policy_path_lc" in
        agents.md|claude.md|memory.md|readme*.md|features*.md)
            return 0
            ;;
        talon_architecture.md|wiki/*|docs/user-guides/*)
            return 0
            ;;
        *.md|*.html|*.pdf)
            return 0
            ;;
    esac

    return 1
}

talon_print_publish_policy() {
    cat <<'POLICY'
TALON publish policy:
  - local-docs stays local-only.
  - Push only dev and main branch refs.
  - Allowed published docs: README.md, CHANGELOG.md, and generated
    *-user-guide.pdf files.
  - Keep AGENTS.md, CLAUDE.md, other README files, HTML guides, wiki files,
    guide assets, and other local docs local-only unless explicitly overridden.
POLICY
}
