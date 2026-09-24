#!/bin/sh
set -eu

umask 077
export GARMIN_MCP_PORT="${PORT:-8080}"
exec "$@"
