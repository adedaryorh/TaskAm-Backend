#!/bin/sh
set -eu
while true; do
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  pg_dump -h db -U taskam -d taskam -Fc -f "/backups/taskam-${timestamp}.dump"
  find /backups -name 'taskam-*.dump' -type f -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete
  sleep 86400
done
