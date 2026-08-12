#!/bin/sh
set -eu

chown -R lifeos:lifeos /data
supplementary_gids=${LIFEOS_SUPPLEMENTARY_GIDS:-}
if [ -n "$supplementary_gids" ]; then
    case "$supplementary_gids" in
        *[!0-9,]* | ,* | *, | *,,* | 0* | *,0*)
            echo "invalid LIFEOS_SUPPLEMENTARY_GIDS: expected comma-separated positive numeric GIDs" >&2
            exit 64
            ;;
    esac
    remaining_gids=$supplementary_gids
    while [ -n "$remaining_gids" ]; do
        supplementary_gid=${remaining_gids%%,*}
        case "$remaining_gids" in
            *,*) remaining_gids=${remaining_gids#*,} ;;
            *) remaining_gids= ;;
        esac
        if [ "${#supplementary_gid}" -gt 10 ] || [ "$supplementary_gid" -gt 4294967294 ]; then
            echo "invalid LIFEOS_SUPPLEMENTARY_GIDS: GID outside 1..4294967294" >&2
            exit 64
        fi
    done
fi

if [ -d /wiki ]; then
    canonical_root=/wiki/01-Projects/LifeOS/lifeos
    mkdir -p "$canonical_root"
    if [ -n "$supplementary_gids" ]; then
        canonical_gid=${supplementary_gids%%,*}
        chgrp "$canonical_gid" "$canonical_root"
        chmod 2775 "$canonical_root"
    else
        chown lifeos:lifeos "$canonical_root"
        chmod 0755 "$canonical_root"
    fi
fi

if [ -n "$supplementary_gids" ]; then
    umask 0002
    exec setpriv --reuid=lifeos --regid=lifeos --groups "$supplementary_gids" -- "$@"
fi

exec setpriv --reuid=lifeos --regid=lifeos --clear-groups -- "$@"
