#!/bin/sh
# Read-only guest collector. Python 2.7-compatible; never emit raw log records.
__GUEST_PYTHON__ - <<'PY'
from __future__ import print_function
import base64, collections, hashlib, heapq, json, os, re, socket, stat, struct, subprocess, sys, time

MINUTES = __WINDOW_MINUTES__
CONFIG = json.loads(base64.b64decode('__GUEST_CONFIG_BASE64__').decode('utf-8'))
LOG_DIRECTORIES = CONFIG['logDirectories']
MAX_FILES, MAX_BYTES, MAX_LINE = 2048, 32 * 1024 * 1024, 65536
SERVICES = CONFIG['services']
CAUSES = [('reset', 'connection reset'), ('rejected', 'rejected'), ('idle', 'no recent network activity'),
          ('timeout', 'timeout'), ('deadline', 'deadline exceeded'), ('refused', 'connection refused'),
          ('unreachable', 'unreachable'), ('no_route', 'no route to host'), ('broken_pipe', 'broken pipe'),
          ('auth', 'authentication'), ('cancelled', 'cancel'), ('eof', 'eof')]


def utc(seconds):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(seconds))


def run(arguments):
    proc = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, unused = proc.communicate()
    if proc.returncode:
        raise ValueError('read_command_failed')
    return out.decode('utf-8', 'replace')


def destination(value):
    match = re.match(r'^(?:\[([^\]]+)\]|([^:]+)):(\d{1,5})$', value)
    if not match:
        return 'unknown', 0, None
    host, port = match.group(1) or match.group(2), int(match.group(3))
    if not 1 <= port <= 65535:
        return 'unknown', 0, None
    try:
        packed = socket.inet_pton(socket.AF_INET6 if ':' in host else socket.AF_INET, host)
    except (socket.error, ValueError):
        return 'hostname', port, None
    if len(packed) == 16:
        if packed[:12] == b'\x00' * 10 + b'\xff\xff':
            packed = packed[12:]
        elif packed == b'\x00' * 15 + b'\x01':
            return 'loopback', port, None
        elif packed == b'\x00' * 16:
            return 'unspecified', port, None
        elif (bytearray(packed)[0] & 254) == 252:
            return 'private', port, None
        elif bytearray(packed)[0] == 254 and (bytearray(packed)[1] & 192) == 128:
            return 'link_local', port, None
        elif bytearray(packed)[0] == 255:
            return 'multicast', port, None
        elif (bytearray(packed)[0] & 224) == 32 and packed[:4] != b'\x20\x01\x0d\xb8':
            return 'public_ipv6', port, packed
        else:
            return 'reserved', port, None
    number = struct.unpack('!I', packed)[0]
    for network, bits, label in [('127.0.0.0', 8, 'loopback'), ('10.0.0.0', 8, 'private'),
            ('172.16.0.0', 12, 'private'), ('192.168.0.0', 16, 'private'), ('169.254.0.0', 16, 'link_local'),
            ('100.64.0.0', 10, 'shared'), ('198.18.0.0', 15, 'fake_ip'), ('0.0.0.0', 8, 'unspecified'),
            ('224.0.0.0', 4, 'multicast'), ('240.0.0.0', 4, 'reserved'), ('192.0.0.0', 24, 'reserved'),
            ('192.0.2.0', 24, 'reserved'), ('198.51.100.0', 24, 'reserved'), ('203.0.113.0', 24, 'reserved'),
            ('168.63.129.16', 32, 'azure_platform')]:
        mask = (0xffffffff << (32 - bits)) & 0xffffffff
        if number & mask == struct.unpack('!I', socket.inet_aton(network))[0] & mask:
            return label, port, None
    return 'public_ipv4', port, packed


def summarize(profile, now, root=None):
    directory = os.path.join(root, profile) if root is not None else LOG_DIRECTORIES[profile]
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode) or os.path.realpath(directory) != directory:
        raise ValueError('unsafe_log_directory')
    cutoff = now - MINUTES * 60
    entries, aged, missing = [], 0, False
    for name in os.listdir(directory):
        match = re.match(r'^(\d{1,12})-(\d{1,12})\.log$', name)
        if not match:
            continue
        bucket = int(match.group(1))
        if bucket + 10 <= cutoff or bucket > now:
            aged += 1
            continue
        path = os.path.join(directory, name)
        try:
            meta = os.lstat(path)
        except OSError:
            missing = True
            continue
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
            raise ValueError('unsafe_log_file')
        entries.append((bucket, int(match.group(2)), path, meta))
    selected = sorted(heapq.nlargest(MAX_FILES, entries))
    result = {'files': len(selected), 'eligibleFiles': len(entries), 'agedOutSkipped': aged,
              'bytesOnDisk': sum(e[3].st_size for e in entries), 'sampledBytes': 0,
              'oldestBucketUtc': utc(selected[0][0]) if selected else None,
              'newestWriteUtc': utc(max(e[3].st_mtime for e in selected)) if selected else None,
              'privateModes': stat.S_IMODE(info.st_mode) == 0o700 and all(stat.S_IMODE(e[3].st_mode) == 0o600 for e in entries),
              'scanComplete': not missing and len(entries) <= MAX_FILES and bool(selected),
              'windowStartCovered': bool(selected) and selected[0][0] <= cutoff,
              'unparsed': 0}
    severity, causes, operations, rejected = [collections.Counter() for unused in range(4)]
    public, public_capped, overflow = set(), False, 0
    # Retained segments can begin/end midway through a core line; flag fragments.
    partial, discard = b'', False
    for bucket, counter, path, meta in selected:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except OSError:
            result['scanComplete'] = False
            continue
        with os.fdopen(fd, 'rb') as source:
            current = os.fstat(source.fileno())
            if (current.st_ino, current.st_dev) != (meta.st_ino, meta.st_dev):
                result['scanComplete'] = False
                continue
            remaining = min(meta.st_size, MAX_BYTES - result['sampledBytes'])
            if remaining < meta.st_size:
                result['scanComplete'] = False
            while remaining > 0:
                block = source.read(min(MAX_LINE, remaining))
                if not block:
                    result['scanComplete'] = False
                    break
                remaining -= len(block)
                result['sampledBytes'] += len(block)
                pieces = (partial + block).split(b'\n')
                partial = pieces.pop()
                for raw in pieces:
                    if discard:
                        discard = False
                        continue
                    if len(raw) > MAX_LINE:
                        result['unparsed'] += 1
                        continue
                    line = raw.decode('utf-8', 'replace')
                    level, request = 'unknown', u''
                    if profile == 'hy2':
                        try:
                            row = json.loads(line)
                            level = row.get('level', u'unknown').lower()
                            line = (row.get('msg', u'') + u' ' + row.get('error', u'')).lower()
                            request = row.get('reqAddr', u'')
                            if not isinstance(line, type(u'')) or not isinstance(request, type(u'')):
                                raise ValueError('bad_record')
                        except (ValueError, TypeError, AttributeError):
                            result['unparsed'] += 1
                            continue
                    else:
                        line = line.lower()
                        match = re.search(r'\[(debug|info|warning|warn|error|fatal)\]', line)
                        if not match:
                            result['unparsed'] += 1
                            continue
                        level = match.group(1)
                    if level not in ('debug', 'info', 'warning', 'warn', 'error', 'fatal', 'unknown'):
                        level = 'other'
                    severity[level] += 1
                    if level not in ('warn', 'warning', 'error', 'fatal'):
                        continue
                    cause = next((key for key, word in CAUSES if word in line), 'other')
                    causes[cause] += 1
                    kind, port, address = destination(request)
                    if cause == 'reset':
                        operation = next((op for op in ('write', 'read', 'dial') if re.search(r'\b' + op + r'(?:to|from)?\b', line)), 'unknown')
                        operations[operation] += 1
                        if address is None:
                            remote = re.search(r'(?:->|dial tcp\s+)(\[[0-9a-f:]+\]|(?:\d{1,3}\.){3}\d{1,3}):(\d{1,5})\b', line)
                            if remote:
                                unused_kind, unused_port, address = destination(remote.group(1) + ':' + remote.group(2))
                        if address is not None:
                            digest = hashlib.sha256(address).digest()
                            if digest in public or len(public) < 4096:
                                public.add(digest)
                            else:
                                public_capped = True
                    if cause == 'rejected':
                        key = (kind, port)
                        if key in rejected or len(rejected) < 32:
                            rejected[key] += 1
                        else:
                            overflow += 1
                if len(partial) > MAX_LINE:
                    partial, discard = b'', True
                    result['unparsed'] += 1
    if partial or discard:
        result['unparsed'] += 1
    result.update(severity=dict(severity), warningCauses=dict(causes), resetOperations=dict(operations),
                  resetPublicDestinations=len(public), resetPublicCountCapped=public_capped,
                  rejected=[{'class': k[0], 'port': k[1], 'count': n} for k, n in rejected.most_common(6)],
                  rejectedOmitted=overflow + sum(n for k, n in rejected.most_common()[6:]))
    if result['unparsed'] or not result['privateModes']:
        result['scanComplete'] = False
    return result


def services():
    results = []
    for expected in SERVICES:
        unit, port, udp = expected['unit'], expected['port'], expected['transport'] == 'udp'
        props = dict(line.split('=', 1) for line in run(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID']).splitlines() if '=' in line)
        pid = int(props.get('MainPID', '0'))
        child_pids = []
        if pid:
            with open('/proc/%d/task/%d/children' % (pid, pid)) as source:
                child_pids = [int(value) for value in source.read(4096).split() if value.isdigit()]
        sockets = run(['ss', '-H', '-lnup' if udp else '-lntp', 'sport = :%d' % port])
        owners = set(int(value) for value in re.findall(r'pid=(\d+)', sockets))
        results.append({'unit': unit, 'active': props.get('ActiveState') == 'active', 'mainPid': pid,
                        'children': child_pids[:8], 'port': port, 'transport': 'udp' if udp else 'tcp',
                        'listener': bool(sockets.strip()), 'owned': bool(owners) and owners.issubset(set([pid] + child_pids))})
    return results


def resources():
    memory = {}
    with open('/proc/meminfo') as source:
        for line in source:
            key, value = line.split(':', 1)
            if key in ('MemTotal', 'MemAvailable', 'MemFree'):
                memory[key + 'KiB'] = int(value.split()[0])
    disk = os.statvfs('/var/log')
    udp = {}
    with open('/proc/net/snmp') as source:
        rows = [line.split()[1:] for line in source if line.startswith('Udp:')]
    if len(rows) == 2:
        udp = dict((key, int(value)) for key, value in zip(*rows) if key in ('InErrors', 'RcvbufErrors', 'SndbufErrors', 'NoPorts'))
    return {'memory': memory, 'logDiskFreeMiB': disk.f_bavail * disk.f_frsize // (1024 * 1024),
            'udpCountersSinceBootNotWindow': udp}


def collect():
    now = time.time()
    result = {'schema': 1, 'status': 'observations_only', 'utc': utc(now), 'requestedSinceUtc': utc(now - MINUTES * 60),
              'bucketSeconds': 10, 'logs': {}}
    for profile in ('vless', 'hy2'):
        if profile not in LOG_DIRECTORIES:
            result['logs'][profile] = {'error': 'log_support_not_configured'}
            result['status'] = 'incomplete'
            continue
        try:
            result['logs'][profile] = summarize(profile, now)
            if not result['logs'][profile]['scanComplete']:
                result['status'] = 'incomplete'
        except Exception:
            result['logs'][profile] = {'error': 'logs_unavailable_or_unsafe'}
            result['status'] = 'incomplete'
    for key, reader in [('services', services), ('resources', resources)]:
        try:
            result[key] = reader()
        except Exception:
            result[key] = {'error': 'read_failed'}
            result['status'] = 'incomplete'
    if isinstance(result.get('services'), list) and not all(s['active'] and s['owned'] and s['listener'] for s in result['services']):
        result['status'] = 'incomplete'
    # Historical private log: metadata only; never mix its older events into the rolling window.
    try:
        if CONFIG['historicalLog'] is None:
            raise OSError('not_configured')
        meta = os.lstat(CONFIG['historicalLog'])
        result['historicalLog'] = {'bytes': meta.st_size, 'mtimeUtc': utc(meta.st_mtime),
                                   'privateRegularFile': stat.S_ISREG(meta.st_mode) and stat.S_IMODE(meta.st_mode) == 0o600, 'scanned': False}
    except OSError:
        result['historicalLog'] = {'present': False, 'scanned': False}
    return result


def emit(result):
    encode = lambda: json.dumps(result, separators=(',', ':'), sort_keys=True)
    if len(encode().encode('utf-8')) > 3000:
        result.update(status='incomplete', summaryTruncated=True)
        for summary in result.get('logs', {}).values():
            for key in ('warningCauses', 'rejected', 'severity'):
                summary.pop(key, None)
    if len(encode().encode('utf-8')) > 3000:
        result = {'schema': 1, 'status': 'error', 'error': 'summary_too_large'}
    print('VPN_DIAGNOSTICS=' + json.dumps(result, separators=(',', ':'), sort_keys=True))


if __name__ == '__main__':
    try:
        emit(collect())
    except Exception:
        emit({'schema': 1, 'status': 'error', 'error': 'guest_collection_failed'})
        sys.exit(1)
PY
