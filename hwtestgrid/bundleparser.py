# -*- coding: utf-8 -*-

import os
import re
import shutil
import json
import zipfile
import sys

CURRENT_VERSION = 12

class HWInfo:
    def __init__(self, t):
        self.type = t


class GBB:
    def __init__(self, test, fname):
        self.test = test
        self.file = fname

        data = json.loads(self.test.zip.read(self.file).decode('utf-8'))
        self.brightness = data['screen-brightness']
        self.name = data['test-name']
        self.description = data['test-description']
        self.duration = data['duration-seconds']

        self.hardware = data['system-info']['hardware']
        self.software = data['system-info']['software']
        self.kernel = data['system-info']['software']['os']['kernel']
        self.os = data['system-info']['software']['os']['type']
        self.gpus = data['system-info']['hardware']['gpus']

        self.watt = data['power']
        if 'estimated-life-design' in data:
            self.estimated_life = data['estimated-life-design']
        else:
            self.estimated_life = -1

        if 'format-version' not in data['system-info'] or data['system-info']['format-version'] == [1, 0, 0]:
            # The estimation is really bad, primarily because of the first
            # sample not being discarded.
            dt1 = data['log'][1]
            dt2 = data['log'][-1]
            self.watt = (dt1['energy'] - dt2['energy']) / float(dt2['time-ms'] - dt1['time-ms']) * 3.6

            energy_use_per_ms = (dt1['energy'] - dt2['energy']) / float(dt2['time-ms'] - dt1['time-ms'])
            self.estimated_life = data['log'][0]['energy-full-design'] / energy_use_per_ms / 1000

class TestCase:
    def __init__(self, test, data, directory):
        self.test = test
        self.data = data
        self.dir = directory

        self.data['fail_reason'] = \
            self.data['fail_reason'].replace("[WARNING: self.skip() will be deprecated. Use 'self.cancel()' or the skip decorators]", '').strip()

        self._doc = self._get_docstring()

        self.name = self.data['test']
        self.name = re.sub(r'.*:', '', self.name)
        self.name = re.sub(r';.*', '', self.name)

        if self._doc:
            title_match = re.search(r'\.\. title:: (?P<title>.*)$', self._doc, flags=re.MULTILINE)
            if title_match is not None and title_match.group('title'):
                self.name = title_match.group('title')


    @property
    def style(self):
        if self.data['status'] == 'WARN':
            return 'WARN'
        elif self.data['status'] in ['SKIP', 'CANCELLED']:
            return 'INFO'
        if self.data['status'] == 'FAIL':
            return 'BAD'
        if self.data['status'] == 'PASS':
            return 'GOOD'

        return 'WARN'

    def _get_docstring(self):
        import ast
        match = re.match(r'.*/(?P<file>.*):(?P<class>.*)\.(?P<func>.*)', self.data['test'])

        fname = match.group('file')
        tclass = match.group('class')
        tfunc = match.group('func')

        try:
            f = open(os.path.join(os.path.dirname(__file__), 'fedora-laptop-testing', 'tests', fname))
        except IOError:
            return ''

        mod = ast.parse(f.read(), fname)
        for statement in mod.body:
            if not isinstance(statement, ast.ClassDef) or statement.name != tclass:
                continue
            return ast.get_docstring(statement)
        return ''

    @property
    def status(self):
        return self.data['status']

    def mark_categories(self):
        categories = set()
        for match in re.finditer(r'\s*:categories:\s*(?P<cats>\S+)\s*', self._doc):
            cats = match.group('cats').strip().split(',')
            for cat in cats:
                cat = cat.strip()
                if not cat:
                    continue
                categories.add(cat)

        if not categories:
            categories = {'issues'}

        if 'issues' in categories and 'issues' not in self.test.hwtable:
            self.test.hwtable['issues'] = HWInfo('Issues')
            self.test.hwtable['issues'].text = 'Issues were detected during testing!'

        for cat in categories:
            if self.data['status'] == 'WARN':
                self.test.hwtable[cat].warn = True
            elif self.data['status'] == 'FAIL':
                self.test.hwtable[cat].error = True

    def gen_summary_dict(self):
        return {
            'name' : self.name,
            'status' : self.status,
            'style' : self.style,
            'whiteboard' : self.data['whiteboard'] if self.data['whiteboard'] else self.data['fail_reason'],
            'dir' : self.dir + '/test-results/' + self.data['test'].replace('/', '_'),
        }

class HWInfo:
    def __init__(self, t):
        self.text = 'Unresolved'
        self.type = t

        self.resolved = False
        self.error = False
        self.warn = False

    @property
    def status(self):
        if not self.resolved:
            return 'WARN'
        if self.error:
            return 'BAD'
        if self.warn:
            return 'WARN'
        return 'GOOD'

class Test:

    def __init__(self, fname):
        self.zipfile = fname
        self.zip = zipfile.ZipFile(self.zipfile, mode='r')
        self.zip.testzip()

        toplevel_dirs = set()
        for filename in self.zip.namelist():
            if '/' in filename:
                toplevel_dirs.add(filename.split('/')[0])

        self.testruns = list(sorted(toplevel_dirs))
        self.maindir = self.testruns[-1]

        self.sysinfo = {}
        self.power_info = {}
        self.gbb = []
        self.hwtable = {}
        self.testcases = []

        self.hwtable['graphics'] = HWInfo('Graphics')
        self.hwtable['screen'] = HWInfo('Screen')
        self.hwtable['bluetooth'] = HWInfo('Bluetooth')
        self.hwtable['cpu'] = HWInfo('CPU')
        self.hwtable['ethernet'] = HWInfo('Ethernet')
        self.hwtable['wifi'] = HWInfo('Wireless LAN')
        self.hwtable['usb'] = HWInfo('USB')
        self.hwtable['pointer'] = HWInfo('Pointer Devices')
        self.hwtable['battery'] = HWInfo('Battery')
        self.hwtable['firmware'] = HWInfo('Firmware')
        self.hwtable['fingerprint'] = HWInfo('Fingerprint Reader')

        self.get_sysinfo()
        if 'CPU' in self.sysinfo:
            self.hwtable['cpu'].text = self.sysinfo['CPU']
            self.hwtable['cpu'].resolved = True
        self.find_gbb_tests()

        self.resolve_hwtable()
        self.parse_tests()

    def get_sysinfo(self):
        include = {'Manufacturer', 'Product Name', 'Version', 'Family', 'SKU Number'}
        dmidecode = self.read_sysinfo('dmidecode')
        hwinfo = 0

        for line in dmidecode.split('\n'):
            if line.startswith('Handle'):
                hwinfo = 0
            if line == 'System Information':
                hwinfo = 1
            if not hwinfo:
                continue
            t = line.split(':', 1)
            if len(t) != 2:
                continue
            key, value = t
            key = key.strip()
            value = value.strip()
            if key in include:
                self.sysinfo[key] = value

        cpuinfo = self.read_sysinfo('lscpu')
        match = re.search(r'^Model name:\s+(?P<model>.*)$', cpuinfo, re.MULTILINE)
        if match:
            self.sysinfo['CPU'] = match.group('model')

        # Try grabbing information from gbb
        try:
            gbbinfo = self.read_sysinfo('gbb_info_--json')
            # There might be junk before everything, remove anything before the first opening braces
            gbbinfo = gbbinfo[gbbinfo.find('{\n'):]
            data = json.loads(gbbinfo)


            self.sysinfo['Kernel'] = data['software']['os']['kernel']
            self.sysinfo['OS'] = data['software']['os']['type']
        except:
            pass

        if not 'Kernel' in self.sysinfo:
            self.sysinfo['Kernel'] = self.read_sysinfo('uname_-a').split()[2]

    def get_inputdevices(self):
        inputdevices = self.read_sysinfo('libinput-list-devices')
        device = {}
        self.input_devices = []
        for line in inputdevices.split('\n'):
            if not line:
                if 'device' in device:
                    self.input_devices.append(device)
                    device = {}
                continue

            tmp = line.split(':', 1)
            # Handle error cases
            if len(tmp) != 2:
                return
            k, v = tmp
            device[k.lower()] = v.strip()

        if 'device' in device:
            self.input_devices.append(device)


    def read_sysinfo(self, f, time='pre'):
        return self.zip.read(os.path.join(self.maindir, 'sysinfo', time, f)).decode('utf-8')


    def resolve_wifi(self):
        # Just PHY capabilities for now?
        iw_phy = self.read_sysinfo('iw_phy')
        phys = re.split('Wiphy (?P<phy>[^\s]*)\n', iw_phy)
        phys = phys[1:]
        self.wifi_phys = {}
        while phys:
            phy = phys[0]
            values = phys[1]
            phys = phys[2:]

            self.wifi_phys[phy] = phy + ' Bands:'

            bands = re.split('\tBand [0-9]+:\n', values, re.MULTILINE)[1:]
            self.wifi_phys[phy] += '<ul>'

            for band in bands:
                self.wifi_phys[phy] += '<li>'
                infos = []
                if '\tHT20/HT40\n' in band:
                    infos.append('802.11n (40MHz)')
                elif '\tHT20\n' in band:
                    infos.append('802.11n (20MHz)')
                else:
                    infos.append('802.11g only')

                streams = -1
                streams_mcs = 'unresolved'
                for match in re.finditer('(?P<streams>[1-8]) streams: (?P<mcs>MCS [0-9]+-[0-9]+)', band):
                    if int(match.group('streams')) > streams:
                        streams = int(match.group('streams'))
                        streams_mcs = match.group('mcs')

                vht_capabilities = re.search('\tVHT Capabilities \((?P<vht_cap>0x[a-f0-9A-F]*)\)', band)
                if vht_capabilities:
                    vht_capabilities = int(vht_capabilities.group('vht_cap'), 0)
                    bands = (vht_capabilities >> 2) & 3
                    if bands == 0:
                        infos.append('802.11ac (80MHz, {:d} streams {})'.format(streams, streams_mcs))
                    elif bands == 1:
                        infos.append('802.11ac (160MHz, {:d} streams {})'.format(streams, streams_mcs))
                    elif bands == 2:
                        infos.append('802.11ac (160/80+80 MHz, {:d} streams {})'.format(streams, streams_mcs))
                    else:
                        infos.append('802.11ac, {:d} streams {})'.format(streams, streams_mcs))
                if infos:
                    self.wifi_phys[phy] += ', '.join(infos)
                else:
                    self.wifi_phys[phy] += 'Unavailable'
                self.wifi_phys[phy] += '</li>\n'
            self.wifi_phys[phy] += '</ul>'


    def resolve_hwtable(self):
        # Pointer
        self.get_inputdevices()
        ptrs = []
        for dev in self.input_devices:
            if 'pointer' in dev['capabilities']:
                ptrs.append(dev['device'])
        if ptrs:
            self.hwtable['pointer'].text = ', '.join(ptrs)
            self.hwtable['pointer'].resolved = ', '.join(ptrs)

        # TODO: Doesn't seem to detect USB-C (3.1)
        lsusb = self.read_sysinfo('lsusb_-v')
        hubs = set()
        for match in re.finditer('Bus[^:]*: ID 1d6b:.* Linux Foundation (?P<version>.*) root hub', lsusb):
            hubs.add(match.group('version'))
        if hubs:
            self.hwtable['usb'].text = ', '.join(sorted(hubs))
            self.hwtable['usb'].resolved = ', '.join(sorted(hubs))
        else:
            # TODO: Warn here?
            pass

        lspci = self.read_sysinfo('lspci_-vvnn')
        wifi = ''
        pci_wifis = []
        for match in re.finditer(r'(?!\s)[^:]*\[0280\]:\s+(?P<device>.*)', lspci, re.MULTILINE):
            pci_wifis.append(match.group('device'))
        if pci_wifis:
            wifi = '<br/>\n'.join(pci_wifis)
            wifi += '<br/>'
        self.resolve_wifi()

        for phy in sorted(self.wifi_phys.keys()):
            wifi += self.wifi_phys[phy]

        self.hwtable['wifi'].text = wifi
        self.hwtable['wifi'].resolved = True


        # Ethernet
        lan = ''
        pci_lans = []
        for match in re.finditer(r'(?!\s)[^:]*\[0200\]:\s+(?P<device>.*)', lspci, re.MULTILINE):
            pci_lans.append(match.group('device'))
        if pci_lans:
            self.hwtable['ethernet'].text = '\n'.join(pci_lans)
            self.hwtable['ethernet'].resolved = True
        else:
            self.hwtable['ethernet'].text = 'No PCI Adapter found'



        # Resolve some stuff from GBB
        if self.gbb:
            gbb = self.gbb[0]

            if 'screen' in gbb.hardware:
                scale = gbb.hardware['screen']['scale']
                x = int(gbb.hardware['screen']['x'] * scale)
                y = int(gbb.hardware['screen']['y'] * scale)
                width = gbb.hardware['screen']['width']
                height = gbb.hardware['screen']['height']
                self.hwtable['screen'].text = '{:d}x{:d}px ({:d}x{:d}mm, {:.2g} Hz)'.format(x, y, width, height, gbb.hardware['screen']['refresh'])
                self.hwtable['screen'].resolved = True

            self.hwtable['graphics'].text = '<ul>\n'

            for gpu in gbb.gpus:
                vendor = gpu['vendor-name'] if 'vendor-name' in gpu else "0x{:X}".format(gpu['vendor'])
                device = gpu['device-name'] if 'device-name' in gpu else "0x{:X}".format(gpu['device'])
                if not gpu['enabled']:
                    note = ' (disabled)'
                else:
                    note = ''
                self.hwtable['graphics'].text += '<li>%s &mdash; %s%s</li>' % (vendor, device, note)

            self.hwtable['graphics'].text += '</ul>'
            self.hwtable['graphics'].resolved = True

            self.hwtable['battery'].resolved = True
            self.hwtable['battery'].text = 'Battery Design Power:\n<ul>'
            for battery in gbb.hardware['batteries']:
                self.hwtable['battery'].text += '<li>{:2.2f} Wh</li>\n'.format(battery['energy-full-design'])
            self.hwtable['battery'].text += '</ul>Estimated Life:\n<ul>'
            for gbb in sorted(self.gbb, key=lambda v : v.name):
                self.hwtable['battery'].text += "<li><strong>{test:s}</strong>: {hours:02d}:{min:02d}h ({watt:.2f}W) <br/>(screen brightness: {brightness:.0f}%, test duration: {duration:.0f}min)</li>\n".format(
                            test=gbb.name,
                            hours=int(gbb.estimated_life / 60 / 60),
                            min=int(gbb.estimated_life / 60 % 60),
                            watt=gbb.watt,
                            brightness=gbb.brightness,
                            duration=gbb.duration / 60,
                        )
            self.hwtable['battery'].text += "</li>"

            # Firmware stuff
            if 'bios' in gbb.hardware:
                bios = gbb.hardware['bios']
                self.hwtable['firmware'].text = 'BIOS: {:s}, date: {:s}, vendor: {:s}'.format(bios['version'], bios['date'], bios['vendor'])
                self.hwtable['firmware'].resolved = True

            # Fingerprint
            readers = self.find_dbus_objects('/net/reactivated/Fprint/Device/')
            if readers:
                self.hwtable['fingerprint'].text = 'Available fingerprint readers:<ul>'
                self.hwtable['fingerprint'].resolved = True
                for reader in readers.itervalues():
                    device = reader['interfaces']['net.reactivated.Fprint.Device']
                    self.hwtable['fingerprint'].text += '<li>{:s} (scan type: {:s})</li>'.format(device['props']['name'], device['props']['scan-type'])
                self.hwtable['fingerprint'].text += '</ul>'
            else:
                self.hwtable['fingerprint'].text = 'No fingerprint reader was detected'

    def ensure_dbus(self):
        if hasattr(self, '_dbus'):
            return

        self._dbus = None

        for filename in self.zip.namelist():
            if 'pre/fed-dbus-dump.py' in filename:
                dbus_dump = filename
                break
        else:
            # Not found
            return

        self._dbus = json.loads(self.zip.read(os.path.join(dbus_dump)).decode('utf-8'))

    def find_dbus_objects(self, prefix):
        self.ensure_dbus()

        if not self._dbus:
            return []

        res = {}
        for s in self._dbus.values():
            for obj_path, obj in s.iteritems():
                if obj_path.startswith(prefix):
                    res[obj_path] = obj
        return res

    def parse_tests(self):
        for run in self.testruns:
            results = json.loads(self.zip.read(os.path.join(run, 'results.json')).decode('utf-8'))

            # Assumes that all except the first run are replays
            for test in results['tests'][len(self.testcases):]:
                t = TestCase(self, test, run)
                t.mark_categories()
                self.testcases.append(t)


    def find_gbb_tests(self):
        for filename in self.zip.namelist():
            if filename.endswith('/gbb.json'):
                # Found a GBB file
                try:
                    self.gbb.append(GBB(self, filename))
                except:
                    details = sys.exc_info()[1]
                    print('Error parsing GBB information, ignoring {:s} ({:s})'.format(filename, details))

    def get_unique_identifier(self):
        return self.maindir

class TestSummary:

    def __init__(self, test):
        self.test = test

    def gen_json(self):
        data = {}
        data['version'] = CURRENT_VERSION
        data['sysinfo'] = self.test.sysinfo
        data['hwtable'] = {}

        data['testruns'] = self.test.testruns

        for field, value in self.test.hwtable.iteritems():
            data['hwtable'][field] = {
                'type' : value.type,
                'status' : value.status,
                'text' : value.text,
            }

        data['lspci'] = re.sub(r'^(\t.*|)\n', '', self.test.read_sysinfo('lspci_-vvnn'), flags=re.MULTILINE)
        data['lsusb'] = re.sub(r'^(?!Bus).*\n', '', self.test.read_sysinfo('lsusb_-v'), flags=re.MULTILINE)

        data['tests'] = []
        for testcase in self.test.testcases:
            data['tests'].append(testcase.gen_summary_dict())

        return json.dumps(data)


def is_uptodate(cache):
    if cache is None or not 'version' in cache:
        return False

    return cache['version'] == CURRENT_VERSION

if __name__ == '__main__':
    import sys
    test = Test(sys.argv[1])
    print(TestSummary(test).gen_json())


