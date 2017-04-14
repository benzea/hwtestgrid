#!/usr/bin/env python3

import json
import os
import sqlite3
import sys

from flask import Flask, render_template, request

app = Flask(__name__)
app.config.from_object(__name__)

app.config.update({
    'DATABASE': os.environ.get("DATABASE", None) or
    os.path.join(app.root_path, 'dugrid.db'),
})

edges = [0, 110, 220, 480, 1000]

def db_connect():
    db_path = app.config['DATABASE']
    rv = sqlite3.connect(db_path)
    rv.row_factory = sqlite3.Row
    return rv


def db_get():
    from flask import g
    if not hasattr(g, 'the_database'):
        g.the_database = db_connect()
    return g.the_database


@app.teardown_appcontext
def db_close(error):
    from flask import g
    if hasattr(g, 'the_database'):
        g.the_database.close()


def db_setup():
    db = db_get()
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()


@app.cli.command('setupdb')
def initdb_command():
    print('[DB] Initializing [%s]' % app.root_path)
    db_setup()


@app.route('/upload', methods=['POST'])
def upload_data():
    db = db_get()
    data = request.get_json()
    machine_id = data['id']
    try:
        db.execute('insert or replace into hwdb (id, data) values (?, ?)',
                   [machine_id, json.dumps(data)])
        db.commit()
    except sqlite3.IntegrityError:
        return "Already exists", 409
    return "Created", 201


def extract_info(e):
    machine_id = e['id']
    d = json.loads(e['data'])
    return {
        'id': machine_id,
        'used': "%3.2f" % (d['used'] / 1e9),
        'size': "%3.2f" % (d['size'] / 1e9),
        'avail': "%3.2f" % (d['avail'] / 1e9),
    }

@app.route('/machine/<machine_id>', methods=['GET'])
def show_single(machine_id):
    db = db_get()
    cur = db.execute('select data from hwdb where id = ?', [machine_id])
    row = cur.fetchall()
    return render_template('machine.html',
                           title="Machine %s" % machine_id,
                           data=json.loads(row[0]['data']))

@app.route('/list')
def lst():
    db = db_get()
    query = ("select id, json_extract(hwdb.data, '$.diskusage.total') as data from hwdb")
    cur = db.execute(query)
    data = cur.fetchall()
    info = [extract_info(e) for e in data]
    return render_template('list.html',
                           title="Machine List",
                           entries=info)

@app.route('/')
def overview():
    db = db_get()
    query = "select json_extract(hwdb.data, '$.diskusage.total.used') as data from hwdb"
    cur = db.execute(query)
    res = cur.fetchall()
    data = [r["data"] / 1e9 for r in res]
    total_machines = len(data)
    bounds = list(zip(edges[:-1], edges[1:]))
    counts = [len(list(filter(lambda x: b[0] < x < b[1], data))) for b in bounds]
    counts += [len(list(filter(lambda x: x > edges[-1], data)))]
    percent = [cnt / total_machines * 100 for cnt in counts]

    return render_template('overview.html',
                           title="Overview",
                           data_raw=list(filter(lambda x: x < edges[-1], data)),
                           bounds=bounds,
                           machines=total_machines,
                           counts=counts,
                           percents=percent)


if __name__ == '__main__':
    app.run()
