#!/bin/sh
set -eu

chown -R lifeos:lifeos /data
exec runuser -u lifeos -- "$@"
