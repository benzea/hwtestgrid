#!/bin/sh

export FLASK_APP=hwtestgrid
export PYTHONPATH=`pwd`
export DATABASE=hwtestgrid/hwtestgrid.db

# Ensure data directory exists
mkdir -p $FLASK_APP/data/bundles

echo "Running in $PWD"
echo "DB is at: $DATABASE"
if [ ! -f "$DATABASE" ]; then
  echo "Initializing $DATABASE"
  flask setupdb
fi

exec flask run --host 0.0.0.0

