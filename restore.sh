#!/bin/bash

set -e
. ./colours.sh

CONTAINER_NAME='overseer_db'

cd ../

[ ! -d "database-dump-overseer" ] && { echo "$RED Database dump directory not found $RESET"; exit 1; }

cd database-dump-overseer

echo "$BLUE $BOLD Enter dump file name to restore - $RESET"
read -r FILE_NAME

if [ -f "$FILE_NAME" ]; then
    echo "$BLUE Starting database dump restore $RESET"
    cat "$FILE_NAME" | docker exec -i $CONTAINER_NAME psql -U postgres -d postgres
    echo "$GREEN Restore completed $RESET"

else
  echo "$BOLD Database dump file not found! $RESET"
  exit 1
fi