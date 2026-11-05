#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Fetches the pinned browser libraries into static/vendor (not committed).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=$here/hub/static/vendor
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
npm install --silent --no-fund --no-audit --ignore-scripts \
    htm@3.1.1 preact@10.26.9 @xterm/xterm@6.0.0 @xterm/addon-fit@0.11.0 >/dev/null
mkdir -p "$out"
cp node_modules/htm/preact/standalone.module.js "$out/preact-htm.js"
cp node_modules/@xterm/xterm/lib/xterm.mjs "$out/xterm.mjs"
cp node_modules/@xterm/xterm/css/xterm.css "$out/xterm.css"
cp node_modules/@xterm/addon-fit/lib/addon-fit.mjs "$out/addon-fit.mjs"
