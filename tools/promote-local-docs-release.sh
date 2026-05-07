#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  tools/promote-local-docs-release.sh [TAG] [options]

Promote publishable changes from local-docs into clean dev/main branch tips.
local-docs remains local-only; dev and main receive only non-local-doc changes,
plus README.md, CHANGELOG.md, and generated *-user-guide.pdf files.

Arguments:
  TAG                         Optional version tag, for example v0.1.1.

Options:
  --tag TAG                   Version tag to create or update.
  --retag                     Force-move an existing local and remote tag.
  --push                      Push dev, main, and TAG when provided.
  --no-fetch                  Do not fetch origin before promotion.
  --dry-run                   Show what would be promoted without changing refs.
  --source REF                Source branch/ref. Default: local-docs.
  --base REF                  Publish base ref. Default: origin/dev.
  --remote NAME               Remote name. Default: origin.
  -m, --message MESSAGE       Promotion commit message.
  -h, --help                  Show this help.

Examples:
  tools/promote-local-docs-release.sh --dry-run --no-fetch
  tools/promote-local-docs-release.sh v0.1.1 --retag --push
  tools/promote-local-docs-release.sh --tag v0.1.2 --push
USAGE
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) ||
    die "run this from inside the TALON git repository"
cd "$repo_root"

# shellcheck source=talon-publish-policy.sh
. "$repo_root/tools/talon-publish-policy.sh"

source_ref=local-docs
base_ref=origin/dev
remote=origin
tag_name=
retag=0
push_refs=0
fetch_first=1
dry_run=0
message="Promote local-docs publishable changes"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --tag)
            [ "$#" -ge 2 ] || die "--tag requires a value"
            tag_name=$2
            shift 2
            ;;
        --retag)
            retag=1
            shift
            ;;
        --push)
            push_refs=1
            shift
            ;;
        --no-fetch)
            fetch_first=0
            shift
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        --source)
            [ "$#" -ge 2 ] || die "--source requires a value"
            source_ref=$2
            shift 2
            ;;
        --base)
            [ "$#" -ge 2 ] || die "--base requires a value"
            base_ref=$2
            shift 2
            ;;
        --remote)
            [ "$#" -ge 2 ] || die "--remote requires a value"
            remote=$2
            shift 2
            ;;
        -m|--message)
            [ "$#" -ge 2 ] || die "$1 requires a value"
            message=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        v[0-9]*.[0-9]*.[0-9]*)
            [ -z "$tag_name" ] || die "tag specified more than once"
            tag_name=$1
            shift
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

current_branch=$(git branch --show-current)
[ "$current_branch" = "$source_ref" ] ||
    die "current branch is '$current_branch'; switch to '$source_ref' before promotion"

status_porcelain=$(git status --porcelain)
if [ -n "$status_porcelain" ]; then
    if [ "$dry_run" -eq 1 ]; then
        printf 'warning: working tree has uncommitted changes; dry run uses committed refs only.\n' >&2
    else
        die "working tree must be clean before promotion"
    fi
fi

if [ -n "$tag_name" ]; then
    case "$tag_name" in
        v[0-9]*.[0-9]*.[0-9]*)
            ;;
        *)
            die "version tag must look like vX.Y.Z"
            ;;
    esac
fi

if [ "$fetch_first" -eq 1 ]; then
    git fetch --prune --tags "$remote"
fi

source_commit=$(git rev-parse --verify "$source_ref^{commit}") ||
    die "cannot resolve source ref: $source_ref"
base_commit=$(git rev-parse --verify "$base_ref^{commit}") ||
    die "cannot resolve base ref: $base_ref"

if ! git merge-base --is-ancestor "$base_commit" "$source_commit"; then
    die "$base_ref is not an ancestor of $source_ref; merge dev into local-docs first"
fi

if git rev-parse --verify "$remote/main^{commit}" >/dev/null 2>&1; then
    remote_main_commit=$(git rev-parse --verify "$remote/main^{commit}")
    if ! git merge-base --is-ancestor "$remote_main_commit" "$source_commit"; then
        die "$remote/main is not included in $source_ref; merge main/dev into local-docs first"
    fi
fi

paths_file=$(mktemp)
skipped_file=$(mktemp)
worktree_dir=
timestamp="$(date -u +%Y%m%d%H%M%S)-$$"

cleanup() {
    rm -f "$paths_file" "$skipped_file"
    if [ -n "${worktree_dir:-}" ] && [ -d "$worktree_dir" ]; then
        git worktree remove --force "$worktree_dir" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT HUP INT TERM

publish_count=0
skipped_count=0
while IFS= read -r -d '' path; do
    if talon_is_blocked_remote_path "$path"; then
        printf '%s\n' "$path" >> "$skipped_file"
        skipped_count=$((skipped_count + 1))
    else
        printf '%s\0' "$path" >> "$paths_file"
        publish_count=$((publish_count + 1))
    fi
done < <(git diff --name-only --no-renames -z "$base_commit" "$source_commit")

printf 'Source: %s (%s)\n' "$source_ref" "$source_commit"
printf 'Base:   %s (%s)\n' "$base_ref" "$base_commit"
printf 'Publishable path changes: %s\n' "$publish_count"
printf 'Skipped local-doc path changes: %s\n' "$skipped_count"

if [ -s "$skipped_file" ]; then
    printf '\nSkipped local-only paths:\n'
    sort -u "$skipped_file" | sed 's/^/  - /'
fi

if [ "$dry_run" -eq 1 ]; then
    printf '\nDry run only; no refs changed.\n'
    exit 0
fi

worktree_dir=$(mktemp -d "${TMPDIR:-/tmp}/talon-promote.XXXXXX")
rmdir "$worktree_dir"
git worktree add --detach "$worktree_dir" "$base_commit" >/dev/null

if [ -s "$paths_file" ]; then
    while IFS= read -r -d '' path; do
        if git cat-file -e "$source_commit:$path" 2>/dev/null; then
            git -C "$worktree_dir" checkout "$source_commit" -- "$path"
        else
            git -C "$worktree_dir" rm -q --ignore-unmatch -- "$path"
        fi
    done < "$paths_file"
fi

if git -C "$worktree_dir" diff --quiet &&
    git -C "$worktree_dir" diff --cached --quiet; then
    publish_commit=$base_commit
    printf '\nNo publishable file changes; using base commit %s.\n' "$publish_commit"
else
    git -C "$worktree_dir" commit -m "$message"
    publish_commit=$(git -C "$worktree_dir" rev-parse HEAD)
    printf '\nCreated publish commit %s.\n' "$publish_commit"
fi

if git rev-parse --verify "$remote/dev^{commit}" >/dev/null 2>&1; then
    remote_dev_commit=$(git rev-parse --verify "$remote/dev^{commit}")
    if ! git merge-base --is-ancestor "$remote_dev_commit" "$publish_commit"; then
        die "$publish_commit is not a fast-forward of $remote/dev"
    fi
fi

if git rev-parse --verify "$remote/main^{commit}" >/dev/null 2>&1; then
    remote_main_commit=$(git rev-parse --verify "$remote/main^{commit}")
    if ! git merge-base --is-ancestor "$remote_main_commit" "$publish_commit"; then
        die "$publish_commit is not a fast-forward of $remote/main"
    fi
fi

backup_branch_if_needed() {
    branch_name=$1
    existing_commit=$(git rev-parse --verify "$branch_name^{commit}" 2>/dev/null || true)
    if [ -n "$existing_commit" ] && [ "$existing_commit" != "$publish_commit" ]; then
        backup_branch="backup/${branch_name}-before-promote-${timestamp}"
        git branch "$backup_branch" "$branch_name"
        printf 'Backed up %s as %s.\n' "$branch_name" "$backup_branch"
    fi
}

backup_branch_if_needed dev
backup_branch_if_needed main
git branch -f dev "$publish_commit"
git branch -f main "$publish_commit"
printf 'Moved dev and main to %s.\n' "$publish_commit"

if [ -n "$tag_name" ]; then
    version=${tag_name#v}
    if ! git show "$publish_commit:CHANGELOG.md" | grep -Fq "## [$version] - "; then
        die "$tag_name requires CHANGELOG.md section: ## [$version] - YYYY-MM-DD"
    fi

    existing_tag_commit=$(git rev-parse --verify "$tag_name^{commit}" 2>/dev/null || true)
    if [ -n "$existing_tag_commit" ] && [ "$existing_tag_commit" != "$publish_commit" ] &&
        [ "$retag" -ne 1 ]; then
        die "$tag_name already points to $existing_tag_commit; pass --retag to move it"
    fi

    if [ -n "$existing_tag_commit" ] && [ "$retag" -ne 1 ] &&
        [ "$existing_tag_commit" = "$publish_commit" ]; then
        printf 'Tag %s already points to %s.\n' "$tag_name" "$publish_commit"
    else
        if [ "$retag" -eq 1 ]; then
            git tag -f -a "$tag_name" -m "$tag_name" "$publish_commit"
        else
            git tag -a "$tag_name" -m "$tag_name" "$publish_commit"
        fi
        printf 'Tagged %s at %s.\n' "$tag_name" "$publish_commit"
    fi
fi

if [ "$push_refs" -eq 1 ]; then
    git push "$remote" dev main
    if [ -n "$tag_name" ]; then
        if [ "$retag" -eq 1 ]; then
            git push "$remote" "$tag_name" --force
        else
            git push "$remote" "$tag_name"
        fi
    fi
    printf 'Pushed dev, main%s.\n' "${tag_name:+, and $tag_name}"
else
    printf 'Push skipped. Re-run with --push to publish dev/main%s.\n' "${tag_name:+ and $tag_name}"
fi
