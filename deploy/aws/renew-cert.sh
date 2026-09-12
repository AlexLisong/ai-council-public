#!/bin/sh
# Install under /etc/letsencrypt/renewal-hooks/deploy/ with mode 0755.
if [ "$RENEWED_LINEAGE" = /etc/letsencrypt/live/council.example.com ]; then
    nginx -t && systemctl reload nginx
fi
