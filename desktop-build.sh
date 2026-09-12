#!/usr/bin/env bash
# Rebuild HandScript.app from the current source.
#
# What this wraps: src-tauri/ is a thin native shell (Tauri, Rust + the
# system WebView) around the existing frontend/ static site - no separate
# frontend build step, no Node required. `frontendDist` in
# src-tauri/tauri.conf.json points straight at ../frontend, so editing
# anything under frontend/ and re-running this script is all a rebuild
# needs. The Flask backend (app/) is unrelated to this build and keeps
# running exactly as documented in README.md - the desktop app is a client
# of it, the same way the browser-based frontend already is.
#
# Usage: ./desktop-build.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null 2>&1; then
  echo "error: Rust is not installed. Run: brew install rust" >&2
  exit 1
fi
if ! cargo tauri --version >/dev/null 2>&1; then
  echo "error: tauri-cli is not installed. Run: cargo install tauri-cli --version \"^2.0.0\" --locked" >&2
  exit 1
fi

cargo tauri build

APP="src-tauri/target/release/bundle/macos/HandScript.app"
echo
echo "Built: $(pwd)/$APP"
echo "Move it to /Applications with:"
echo "  cp -R \"$APP\" /Applications/"
