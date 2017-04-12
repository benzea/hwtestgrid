#!/bin/sh

echo "Running in $PWD"
echo "DB is at: $DATABASE"
if [ ! -f "$DATABASE" ]; then
  echo "Initializing $DATABASE"
  flask setupdb
fi

exec flask run --host 0.0.0.0

