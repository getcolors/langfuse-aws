#!/usr/bin/env python3
"""Read-only Cloudflare verification for this deployment's exact hostname."""
import argparse
import json
import os
import urllib.parse
import urllib.request

ZONE = 'bigconfig.online'
HOST = 'langfuse-aws.' + ZONE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expected', choices=['present', 'absent'])
    parser.add_argument('--origin-ip')
    args = parser.parse_args()
    token = os.environ['COLORS_PAR_CLOUDFLARE_API_TOKEN']

    def get(path):
        request = urllib.request.Request('https://api.cloudflare.com/client/v4/' + path,
                                         headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        assert result['success'], 'Cloudflare read failed'
        return result['result']

    zones = get('zones?' + urllib.parse.urlencode({'name': ZONE}))
    assert len(zones) == 1, 'Expected exactly one accessible zone'
    records = get('zones/' + zones[0]['id'] + '/dns_records?' + urllib.parse.urlencode({'name': HOST}))
    if args.expected == 'absent':
        assert not records, 'Deployment DNS record remains present'
    else:
        assert args.origin_ip, '--origin-ip is required for exact verification'
        assert len(records) == 1, 'Expected one deployment DNS record'
        record = records[0]
        assert record['type'] == 'A' and record['proxied'] is True
        assert record['content'] == args.origin_ip, 'DNS origin differs from deployed app host'
    print(json.dumps({'status': 'PASS', 'zone': ZONE, 'hostname': HOST, 'expected': args.expected,
                      'records': [{k: r[k] for k in ('id', 'name', 'type', 'content', 'proxied')} for r in records]}, indent=2))


if __name__ == '__main__':
    main()
