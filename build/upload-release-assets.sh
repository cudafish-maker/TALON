#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  build/upload-release-assets.sh TAG FILE [FILE ...]

Create the GitHub release for TAG if needed, then upload FILE assets with
--clobber. The command retries release lookup/upload to ride out transient
GitHub API errors during tag-triggered release builds.
USAGE
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

[ "$#" -ge 2 ] || {
    usage >&2
    exit 2
}

tag=$1
shift

if [ -z "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]; then
    die "GH_TOKEN or GITHUB_TOKEN must be set"
fi

repo_args=()
if [ -n "${GITHUB_REPOSITORY:-}" ]; then
    repo_args=(--repo "$GITHUB_REPOSITORY")
fi

for asset in "$@"; do
    [ -f "$asset" ] || die "missing release asset: $asset"
done

retry() {
    description=$1
    shift

    for attempt in 1 2 3 4 5; do
        if "$@"; then
            return 0
        fi
        if [ "$attempt" -eq 5 ]; then
            break
        fi
        sleep_seconds=$((attempt * 10))
        printf '%s failed on attempt %s; retrying in %ss.\n' \
            "$description" "$attempt" "$sleep_seconds" >&2
        sleep "$sleep_seconds"
    done

    printf '%s failed after 5 attempts.\n' "$description" >&2
    return 1
}

ensure_release() {
    if gh "${repo_args[@]}" release view "$tag" >/dev/null 2>&1; then
        return 0
    fi

    if gh "${repo_args[@]}" release create "$tag" \
        --title "$tag" \
        --notes "TALON $tag" \
        --verify-tag >/dev/null 2>&1; then
        return 0
    fi

    # Another tag workflow may have won the creation race.
    gh "${repo_args[@]}" release view "$tag" >/dev/null
}

upload_assets() {
    gh "${repo_args[@]}" release upload "$tag" "$@" --clobber
}

retry "Ensure release $tag exists" ensure_release
retry "Upload release assets for $tag" upload_assets "$@"
