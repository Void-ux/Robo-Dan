#!/bin/bash

set -e

CONTAINER_NAME='overseer_db'
DIRECTORY_NAME='Overseer'
DUMP_FILE="dump_$(date +%d-%m-%Y"_"%H_%M_%S).sql"
B2_BUCKET_NAME='overseer-db'
B2_FOLDER_NAME='backups'
USER='dan'

cd /home/$USER/$DIRECTORY_NAME

[ -t 1 ] && . ./colours.sh

cd /home/$USER

if [ "$( docker container inspect -f '{{.State.Running}}' $CONTAINER_NAME )" == "true" ]; then
  echo "$BLUE Starting database dump $RESET"

  if [ -d 'database-dump-overseer' ]; then
    cd database-dump-overseer
  else
    mkdir database-dump-overseer && cd database-dump-overseer
  fi

  docker exec $CONTAINER_NAME pg_dump --data-only -U postgres postgres > "$DUMP_FILE"
  DUMP_SIZE=$(ls -lh $DUMP_FILE | awk '{print  $5}')
  echo "$YELLOW Dump size - $DUMP_SIZE $RESET"
  echo "$RED Uploading to Backblaze... $RESET"
  /usr/local/bin/python3.10 -m b2 upload-file "$B2_BUCKET_NAME" "$DUMP_FILE" "$B2_FOLDER_NAME/$DUMP_FILE"
  echo "$GREEN Database dump completed $RESET"

else
  echo "$RED $CONTAINER_NAME isn't running $RESET"
  exit 1
fi