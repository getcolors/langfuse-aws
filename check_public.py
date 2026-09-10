#!/usr/bin/env python3
"""Exercise the public HTTPS API; retrieve credentials through SSH, never print them."""
import argparse
import base64
import hashlib
import json
import secrets
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def decoded_io(value):
    """Observations v2 returns raw I/O strings, including serialized JSON."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='langfuse-aws.bigconfig.online')
    parser.add_argument('--ssh-host', default='langfuse-aws-app-0')
    parser.add_argument('--continuity', type=Path, default=Path('.continuity.json'))
    parser.add_argument('--read-only', action='store_true')
    args = parser.parse_args()
    read_keys = "from pathlib import Path; import json; print(json.dumps([Path('/etc/langfuse/secrets/'+n).read_text().strip() for n in ('project_public_key','project_secret_key')]))"
    raw = subprocess.check_output([
        'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', args.ssh_host,
        'sudo -n python3 -c ' + shlex.quote(read_keys),
    ], text=True)
    keys = json.loads(raw)
    if len(keys) != 2:
        raise RuntimeError('SSH credential response did not contain two keys')
    auth = 'Basic ' + base64.b64encode(':'.join(keys).encode()).decode()
    base = 'https://' + args.host
    passed = []

    def request(method, path, data=None, headers=None, authentication=auth):
        h = {'User-Agent': 'colors-langfuse-live-assessment/1.0'}
        if authentication:
            h['Authorization'] = authentication
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        req = urllib.request.Request(
            path if path.startswith('https://') else base + path,
            data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def gate(name, condition):
        if not condition:
            raise RuntimeError(name + ' failed')
        passed.append(name)
        print('PASS ' + name, flush=True)

    st, _, headers = request('GET', '/api/public/health?failIfDatabaseUnavailable=true', authentication=None)
    gate('public HTTPS health with certificate validation', st == 200)
    gate('Cloudflare proxy response', any(k.lower() == 'cf-ray' for k in headers))
    for name, credential in [('anonymous', None), ('wrong secret', 'Basic ' + base64.b64encode((keys[0]+':incorrect-secret').encode()).decode())]:
        st, _, _ = request('GET', '/api/public/v2/observations?limit=1', authentication=credential)
        gate(name + ' API request rejected', st == 401)

    if args.read_only:
        record = json.loads(args.continuity.read_text())
        gate('continuity record is complete for this host',
             record.get('verified') is True and record.get('host') == args.host
             and all(record.get(k) for k in ('trace_id', 'root_id', 'generation_id', 'marker', 'score_id', 'media_id', 'media_sha256')))
    else:
        trace = secrets.token_hex(16)
        root = secrets.token_hex(8)
        generation = secrets.token_hex(8)
        marker = 'aws-public-' + secrets.token_hex(12)
        start = time.time_ns()

        def span(span_id, name, kind, parent=None):
            result = {
                'traceId': trace, 'spanId': span_id, 'name': name, 'kind': 1,
                'startTimeUnixNano': str(start), 'endTimeUnixNano': str(start + 500000000),
                'attributes': [
                    {'key': 'langfuse.observation.type', 'value': {'stringValue': kind}},
                    {'key': 'langfuse.observation.input', 'value': {'stringValue': marker}},
                    {'key': 'langfuse.observation.output', 'value': {'stringValue': marker + '-output'}},
                ],
            }
            if parent:
                result['parentSpanId'] = parent
            return result

        body = {'resourceSpans': [{'resource': {'attributes': []}, 'scopeSpans': [{
            'scope': {'name': 'colors-aws-public'}, 'spans': [
                span(root, marker, 'span'), span(generation, marker + '-generation', 'generation', root),
            ],
        }]}]}
        st, body, _ = request('POST', '/api/public/otel/v1/traces', body, {'x-langfuse-ingestion-version': '4'})
        gate('public OTLP ingestion accepted', st == 200)
        response = json.loads(body or '{}')
        gate('OTLP reports no rejected spans', int(response.get('partialSuccess', {}).get('rejectedSpans', 0)) == 0)
        score_id = secrets.token_hex(16)
        st, score_body, _ = request('POST', '/api/public/scores', {
            'id': score_id, 'dataType': 'NUMERIC',
            'traceId': trace, 'observationId': generation, 'name': marker, 'value': 1,
        })
        gate('public score accepted', st in (200, 201))
        gate('public score identity recorded', json.loads(score_body).get('id') == score_id)
        record = {'host': args.host, 'trace_id': trace, 'root_id': root, 'generation_id': generation, 'marker': marker, 'score_id': score_id, 'verified': False}
        args.continuity.write_text(json.dumps(record, indent=2) + '\n')

    deadline = time.monotonic() + 180
    found = False
    while time.monotonic() < deadline:
        query = urllib.parse.urlencode({'traceId': record['trace_id'], 'fields': 'core,basic,io', 'limit': 50})
        st, body, _ = request('GET', '/api/public/v2/observations?' + query)
        if st == 200:
            rows = json.loads(body).get('data', [])
            matches = {r.get('id'): r for r in rows}
            root = matches.get(record['root_id'], {})
            gen = matches.get(record['generation_id'], {})
            found = (root.get('name') == record['marker'] and root.get('type') == 'SPAN'
                     and gen.get('name') == record['marker'] + '-generation' and gen.get('type') == 'GENERATION'
                     and root.get('traceId') == record['trace_id'] and gen.get('traceId') == record['trace_id']
                     and root.get('isRootObservation') is True and gen.get('parentObservationId') == record['root_id']
                     and all(decoded_io(row.get('input')) == record['marker']
                             and decoded_io(row.get('output')) == record['marker'] + '-output'
                             for row in (root, gen)))
            if found:
                break
        time.sleep(3)
    gate('exact trace and generation content readable through public API', found)

    deadline = time.monotonic() + 180
    score_found = False
    while time.monotonic() < deadline:
        query = urllib.parse.urlencode({'id': record['score_id'], 'traceId': record['trace_id'],
                                        'observationId': record['generation_id'], 'fields': 'subject', 'limit': 10})
        st, body, _ = request('GET', '/api/public/v3/scores?' + query)
        if st == 200:
            score_found = any(row.get('id') == record['score_id'] and row.get('name') == record['marker']
                              and row.get('dataType') == 'NUMERIC' and row.get('value') == 1
                              and row.get('subject', {}).get('kind') == 'observation'
                              and row.get('subject', {}).get('id') == record['generation_id']
                              and row.get('subject', {}).get('traceId') == record['trace_id']
                              for row in json.loads(body).get('data', []))
            if score_found:
                break
        time.sleep(3)
    gate('exact score retained on the generation through public API', score_found)

    if not args.read_only:
        media = ('public AWS media ' + record['marker']).encode()
        digest = hashlib.sha256(media).digest()
        encoded = base64.b64encode(digest).decode()
        st, body, _ = request('POST', '/api/public/media', {
            'traceId': record['trace_id'], 'contentType': 'text/plain', 'contentLength': len(media),
            'sha256Hash': encoded, 'field': 'input',
        })
        gate('public media registration', st in (200, 201))
        entry = json.loads(body)
        if entry.get('uploadUrl'):
            st, _, _ = request('PUT', entry['uploadUrl'], media, {
                'Content-Type': 'text/plain', 'x-amz-checksum-sha256': encoded,
            }, authentication=None)
            gate('S3 presigned media upload', st == 200)
            st, _, _ = request('PATCH', '/api/public/media/' + entry['mediaId'], {
                'uploadedAt': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()), 'uploadHttpStatus': 200,
            })
            gate('media upload completion recorded', st in (200, 201, 204))
        st, body, _ = request('GET', '/api/public/media/' + entry['mediaId'])
        gate('public media download URL', st == 200)
        metadata = json.loads(body)
        gate('media metadata records completed upload', bool(metadata.get('uploadedAt'))
             and metadata.get('mediaId') == entry['mediaId']
             and metadata.get('contentLength') == len(media) and metadata.get('contentType') == 'text/plain')
        url = metadata['url']
        st, downloaded, _ = request('GET', url, authentication=None)
        gate('S3 media exact SHA256 roundtrip', st == 200 and hashlib.sha256(downloaded).digest() == digest)
        record.update({'media_id': entry['mediaId'], 'media_sha256': digest.hex()})
        args.continuity.write_text(json.dumps(record, indent=2) + '\n')
    elif record.get('media_id'):
        st, body, _ = request('GET', '/api/public/media/' + record['media_id'])
        gate('retained media download URL', st == 200)
        metadata = json.loads(body)
        gate('retained media upload remains complete', bool(metadata.get('uploadedAt')) and metadata.get('mediaId') == record['media_id'])
        st, media, _ = request('GET', metadata['url'], authentication=None)
        gate('retained media exact SHA256', st == 200 and hashlib.sha256(media).hexdigest() == record['media_sha256'])

    if not args.read_only:
        record['verified'] = True
        args.continuity.write_text(json.dumps(record, indent=2) + '\n')

    print(json.dumps({'status': 'PASS', 'gates': passed, 'continuity': record}, indent=2))


if __name__ == '__main__':
    main()
