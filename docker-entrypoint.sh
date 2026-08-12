#!/bin/sh
set -eu

chown -R lifeos:lifeos /data
if [ -d /wiki ]; then
    canonical_root=/wiki/01-Projects/LifeOS/lifeos
    mkdir -p "$canonical_root"
    chown -R lifeos:lifeos "$canonical_root"
fi
exec runuser -u lifeos -- "$@"
