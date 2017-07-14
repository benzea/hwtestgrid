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
  python2 -m flask setupdb
fi

exec python2 -m flask run --host 0.0.0.0

