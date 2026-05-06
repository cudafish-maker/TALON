#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  build/generate-release-notes.sh TAG REPOSITORY OUTPUT

Generate grouped GitHub release notes for TALON desktop release assets.

Arguments:
  TAG                         Release tag, for example v0.1.1.
  REPOSITORY                  GitHub repository in owner/name form.
  OUTPUT                      Markdown file to write.
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

[ "$#" -eq 3 ] || {
    usage >&2
    exit 2
}

tag=$1
repository=$2
output=$3

[ -n "$tag" ] || die "tag is required"
[ -n "$repository" ] || die "repository is required"
[ -n "$output" ] || die "output is required"

download_base="https://github.com/${repository}/releases/download/${tag}"

mkdir -p "$(dirname "$output")"
cat > "$output" <<EOF
# TALON ${tag}

## Desktop Downloads

### Linux

- [Client package](<${download_base}/talon-desktop-client-linux.tar.gz>)
- [Server package](<${download_base}/talon-desktop-server-linux.tar.gz>)

### Windows

- [Client setup installer](<${download_base}/talon-desktop-client-windows-setup.exe>)
- [Server setup installer](<${download_base}/talon-desktop-server-windows-setup.exe>)

## Update Manifest

- [Signed update manifest](<${download_base}/talon-update.json>)
- [Manifest signature](<${download_base}/talon-update.json.sig>)

## Integrity

- [SHA256SUMS](<${download_base}/SHA256SUMS>) contains checksums for all release artifacts above.

The source archives below are generated automatically by GitHub.
EOF
