#!/usr/bin/env bash
set -euo pipefail

case "$1" in
    Username*) exec echo "$GIT_USER" ;;
    Password*) exec echo "$GIT_PASSWORD" ;;
esac
