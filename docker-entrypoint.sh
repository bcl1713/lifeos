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
    if [ -n "$supplementary_gids" ]; then
        canonical_gid=${supplementary_gids%%,*}
        python /app/scripts/prepare_wiki_permissions.py --wiki-root /wiki --supplementary-gid "$canonical_gid"
    else
        python /app/scripts/prepare_wiki_permissions.py --wiki-root /wiki
    fi
fi

if [ -n "$supplementary_gids" ]; then
    umask 0002
    exec setpriv --reuid=lifeos --regid=lifeos --groups "$supplementary_gids" -- "$@"
fi

exec setpriv --reuid=lifeos --regid=lifeos --clear-groups -- "$@"
