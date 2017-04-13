#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import random
import sys
import tempfile
import time
import unittest

from dugrid import dugrid

data_template = '''
{
   "timestamp" : 1492019194,
   "id" : "%(machine_id)d",
   "diskusage" : {
    "/" : {
      "size" : 41398292480,
      "used" : 32969252864,
      "avail" : 6416629760
    },
    "/boot" : {
      "size" : 3103539200,
      "used" : 254468096,
      "avail" : 2671235072
    },
    "/home" : {
      "size" : 422621650944,
      "used" : 341935136768,
      "avail" : 62394970112
    },
    "total" : {
      "size" : %(total_size)d,
      "used" : %(total_used)d,
      "avail" : %(total_avail)d
    }
  }
}
'''

class TestDuGrid(unittest.TestCase):

    def setUp(self):
        self.db_fd, dugrid.app.config['DATABASE'] = tempfile.mkstemp(suffix="-dugrid.db")
        dugrid.app.config['TESTING'] = True
        self.app = dugrid.app.test_client()
        with dugrid.app.app_context():
            dugrid.db_setup()

    def tearDown(self):
        os.close(self.db_fd)
        #os.unlink(dugrid.app.config['DATABASE'])
        print("export DATABASE=%s" % dugrid.app.config['DATABASE'])

    def test_insert(self):
        tic = time.time()
        howmany = 5000
        for x in range(howmany):

            base = random.choice([128, 256, 512, 1024])
            unit = 1024**3
            used = random.randrange(30, base)
            this_machine = {
                'machine_id': 10000 + x,
                'total_size': base * unit,
                'total_used': used * unit,
                'total_avail': (base - used) * unit
            }

            data = data_template % this_machine

            resp = self.app.post('/upload',
                                 data=data,
                                 content_type='application/json')
            self.assertEqual(resp.status_code, 201)
        toc = time.time()
        print("Inserted %d items in %2.2f seconds" % (howmany, toc - tic))


if __name__ == '__main__':
    unittest.main()
