#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Fetches Interleaf's web form (web/ of GlassineOS/ui) at the version in app/ui.ref into
# static/vendor/interleaf (not committed). A change to app/ui.ref is how the hub moves to
# another version of the design system.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
ref=$(cat "$here/ui.ref")
case $ref in
    v[0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "fetch-ui: app/ui.ref must name a release tag (vX.Y.Z), not '$ref'" >&2; exit 1 ;;
esac
out=$here/hub/static/vendor/interleaf
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# git waits forever on a stalled transfer by default: give up after 30 s below 1 KB/s, and
# try three times, since GitHub sometimes answers a fetch with a 504.
for try in 1 2 3; do
    git init -q "$tmp/ui"
    GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30 \
        git -C "$tmp/ui" fetch -q --depth 1 https://github.com/GlassineOS/ui "refs/tags/$ref" && break
    [ "$try" = 3 ] && exit 1
    rm -rf "$tmp/ui"
    sleep 10
done
git -C "$tmp/ui" -c advice.detachedHead=false checkout -q FETCH_HEAD
for f in tokens.css bundle.css combinations.json fonts/fonts.css; do
    [ -f "$tmp/ui/web/$f" ] || { echo "fetch-ui: $ref has no web/$f" >&2; exit 1; }
done
rm -rf "$out"
mkdir -p "$(dirname "$out")"
cp -R "$tmp/ui/web" "$out"
