#!/usr/bin/env python2

import re
import datetime
import json
import os
import sqlite3
import sys
import random
import zipfile
import tempfile
import shutil
from . import bundleparser

from flask import Flask, render_template, request, send_file, redirect

app = Flask(__name__)
app.config.from_object(__name__)

app.config.update({
    'DATABASE': os.environ.get("DATABASE", None) or
    os.path.join(app.root_path, 'hwtestgrid.db'),
})

def mysort(items, beginning=[], end=[]):
    items = list(sorted(items))

    for item in beginning:
        if item in items:
            yield item

    for item in items:
        if not item in beginning and not item in end:
            yield item

    for item in end:
        if item in items:
            yield item

app.jinja_env.filters['mysort'] = mysort

STYLE = {
    'GOOD' : 'background: #30e030',
    'BAD' : 'background: #ef2929',
    'WARN' : 'background: #fcaf3e',
    'INFO' : '',
}

def state_to_style(state):
    try:
        return STYLE[state]
    except:
        return ''

app.jinja_env.filters['state_to_style'] = state_to_style


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

def get_tmpdir():
    try:
        return request.the_tmpdir
    except AttributeError:
        request.the_tmpdir = tempfile.mkdtemp(prefix='hwtestgrid-')
        return request.the_tmpdir

@app.teardown_request
def clean_tmpdir(error):
    if hasattr(request, 'the_tmpdir'):
        try:
            shutil.rmtree(request.the_tmpdir)
        except OSError:
            pass




def test_get_cache(db, test_id):
    cur = db.execute('select bundle, cache from hwtestdb where ROWID = ?', [test_id])
    row = cur.fetchall()

    bundle = row[0]['bundle']
    cache = json.loads(row[0]['cache'])

    if bundleparser.is_uptodate(cache) and not app.debug:
        return cache

    test = bundleparser.Test(os.path.join(app.root_path, 'data', 'bundles', bundle))
    cache = bundleparser.TestSummary(test).gen_json()

    db.execute('UPDATE hwtestdb SET cache=? WHERE ROWID=?', (cache, test_id))
    db.commit()

    return json.loads(cache)


@app.cli.command('setupdb')
def initdb_command():
    print('[DB] Initializing [%s]' % app.root_path)
    db_setup()


@app.route('/download/<test_id>', methods=['GET'])
def download_bundle(test_id):
    db = db_get()
    cur = db.execute('select bundle from hwtestdb where ROWID = ?', [test_id])
    bundle = cur.fetchall()[0]['bundle']
    fname = os.path.join(app.root_path, 'data', 'bundles', bundle)

    if os.path.exists(fname):
        return send_file(open(fname), attachment_filename=bundle, as_attachment=True)
    else:
        return "File does not exist", 404

@app.route('/download/<test_id>/<path:path>', methods=['GET'])
def extract_file_bundle(test_id, path):
    db = db_get()
    cur = db.execute('select bundle from hwtestdb where ROWID = ?', [test_id])
    bundle = cur.fetchall()[0]['bundle']
    fname = os.path.join(app.root_path, 'data', 'bundles', bundle)

    if os.path.exists(fname):
        z = zipfile.ZipFile(fname, 'r')

        if not path.endswith('/'):
            fname = os.path.basename(path)
            f = z.open(path)

            target_postfix = fname
            target_postfix = request.args.get('fname', target_postfix)
            view = request.args.get('view', None)
            if view is None or view:
                view = True
            target = bundle[:-4] + '_' + target_postfix
            target = request.args.get('target', target)

            return send_file(f, attachment_filename=target, as_attachment=not view, add_etags=False)

        else:
            # Extract the directory and deliver a zip file with the content
            resfile = os.path.join(get_tmpdir(), 'download.zip')
            res = zipfile.ZipFile(resfile, 'w')
            striplen = len(path) - 1
            for f in z.namelist():
                if not f.startswith(path):
                    continue
                res.writestr(f[striplen:], z.read(f))
            res.close()

            target_postfix = path.replace('/', '_')
            target_postfix = request.args.get('fname', target_postfix)
            target = bundle[:-4] + '_' + target_postfix
            target = request.args.get('target', target)

            return send_file(resfile, attachment_filename=target, as_attachment=True, add_etags=False)
    else:
        return "File does not exist", 404


@app.route('/upload', methods=['PUT'])
def upload_bundle():
    # Extract information from the bundle
    tmpdir = get_tmpdir()
    open(os.path.join(tmpdir, 'bundle_upload.zip'), 'w').write(request.data)

    try:
        test = bundleparser.Test(os.path.join(tmpdir, 'bundle_upload.zip'))
        summary = bundleparser.TestSummary(test).gen_json()
    except Exception as e:
        shutil.copy(os.path.join(tmpdir, 'bundle_upload.zip'), '/tmp/broken-bundle-%s.zip' % datetime.datetime.now().isoformat())
        return "Error parsing bundle ({:s})".format(str(e)), 500

    manufacturer = test.sysinfo['Manufacturer']
    if 'Version' in test.sysinfo:
        product = test.sysinfo['Version']
    else:
        product = test.sysinfo['Product Name']

    os_name = test.sysinfo['OS'] if 'OS' in test.sysinfo else 'Unknown OS'
    bundle = datetime.date.today().isoformat() + '_' + manufacturer + '_' + product + '_{:06X}'.format(random.randrange(0, 0xFFFFFF)) + '.zip'
    shutil.move(os.path.join(tmpdir, 'bundle_upload.zip'), os.path.join(app.root_path, 'data', 'bundles', bundle))

    db = db_get()
    try:
        db.execute('insert into hwtestdb (manufacturer, product, os, unique_identifier, bundle, cache, time) values (?, ?, ?, ?, ?, ?, datetime(\'now\'))',
                   [manufacturer, product, os_name, test.get_unique_identifier(), bundle, summary])
        db.commit()
    except sqlite3.IntegrityError:
        os.unlink(os.path.join(app.root_path, 'data', 'bundles', bundle))
        return "Already exists", 409
    return "Created", 201



@app.route('/testrun/<test_id>', methods=['GET'])
def show_single(test_id):
    db = db_get()

    data = test_get_cache(db, test_id)

    data['rowid'] = test_id

    return render_template('test.html',
                           title="Testsummary",
                           data=data)

@app.route('/list')
def lst():
    db = db_get()
    query = ("select rowid,* from hwtestdb ORDER BY manufacturer, product, os, time DESC")
    cur = db.execute(query)
    data = cur.fetchall()

    return render_template('list.html',
                           title="Machine List",
                           entries=data)

@app.route("/robots.txt")
def robots_txt():
    '''Disallow the /download URL as downloads may be large and CPU intensive'''
    disallow = lambda string: 'Disallow: {0}'.format(string)
    return "User-agent: *\n{0}\n".format("\n".join([
        disallow('/download'),
    ])), 200


@app.route('/')
def overview():
    return redirect("/list")

@app.template_filter()
def filter_epochformat(value, format='%d.%m.%Y %H:%M'):
    dt = datetime.datetime.fromtimestamp(value)
    return dt.strftime(format)

app.jinja_env.filters['epochformat'] = filter_epochformat



if __name__ == '__main__':
    app.run()
