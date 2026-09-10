"""Read-only exact-ID AWS role attachment and ingress audit for this deployment."""
import datetime
import json
import urllib.request
from pathlib import Path
import boto3
import yaml

root = Path(__file__).resolve().parent
baseline = json.loads((root / 'resource-baseline.json').read_text())
opts = yaml.safe_load((root.parent / 'colors.yml').read_text())
assert baseline['profile'] == opts['profile'] == 'langfuse-aws'
profile = baseline['profile']
session = boto3.Session(region_name=baseline['region'])
assert session.client('sts').get_caller_identity()['Account'] == baseline['account']
ec2 = session.client('ec2')
instances = [i for r in ec2.describe_instances(InstanceIds=baseline['instance_ids'])['Reservations'] for i in r['Instances']]
assert len(instances) == 6 and all(i['State']['Name'] == 'running' for i in instances)
roles = {}
for i in instances:
    name = next(t['Value'] for t in i['Tags'] if t['Key'] == 'Name')
    assert name.startswith(profile + '-')
    role = name[len(profile) + 1:].rsplit('-', 1)[0]
    assert role in ('app', 'neon', 'redis', 'clickhouse')
    roles.setdefault(role, []).append(i)
assert {r: len(v) for r, v in roles.items()} == {'app': 1, 'neon': 1, 'redis': 1, 'clickhouse': 3}
groups = ec2.describe_security_groups(Filters=[{'Name':'vpc-id','Values':baseline['vpc_ids']}])['SecurityGroups']
groups = {g['GroupName']:g for g in groups}
http_url = 'https://api.cloudflare.com/client/v4/ips'
with urllib.request.urlopen(http_url, timeout=30) as response:
    cloudflare = set(json.load(response)['result']['ipv4_cidrs'])
assert len(cloudflare) >= 10
ssh = opts.get('ssh-sources', opts.get('langfuse-ssh-sources'))
ssh = set(ssh.split(',') if isinstance(ssh,str) else ssh)
app = {roles['app'][0]['PrivateIpAddress'] + '/32'}
clickhouse = {i['PrivateIpAddress'] + '/32' for i in roles['clickhouse']}
port = lambda key, default: int(opts.get(key, default))
expected = {
 'app': {22:ssh,80:cloudflare,443:cloudflare},
 'neon': {22:ssh,55433:app},
 'redis': {22:ssh,port('redis-port',6379):app},
 'clickhouse': {22:ssh,port('clickhouse-http-port',8123):app,port('clickhouse-native-port',9000):app|clickhouse,
                port('clickhouse-interserver-port',9009):clickhouse,port('clickhouse-keeper-port',9181):clickhouse,port('clickhouse-raft-port',9234):clickhouse}}
result = {'profile':profile,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cloudflare_source':http_url,'cloudflare_ipv4_ranges':sorted(cloudflare),'roles':{}}
for role, nodes in roles.items():
    group = groups[profile + '-' + role + '-firewall']
    for node in nodes:
        assert {g['GroupId'] for g in node['SecurityGroups']} == {group['GroupId']}, 'Wrong node role attachment'
        assert all({g['GroupId'] for g in nic['Groups']} == {group['GroupId']} for nic in node['NetworkInterfaces']), 'Unexpected NIC security group'
    actual = {}
    for rule in group['IpPermissions']:
        assert rule['IpProtocol'] == 'tcp' and rule['FromPort'] == rule['ToPort']
        assert not any(rule.get(k) for k in ('Ipv6Ranges','UserIdGroupPairs','PrefixListIds')), 'Unexpected ingress source kind'
        actual.setdefault(rule['FromPort'],set()).update(r['CidrIp'] for r in rule['IpRanges'])
    assert actual == expected[role], 'Ingress differs from exact declared topology for ' + role
    result['roles'][role] = {'security_group_id':group['GroupId'],'nodes':[{'id':n['InstanceId'],'private_ip':n['PrivateIpAddress'],'security_group_ids':[g['GroupId'] for g in n['SecurityGroups']]} for n in nodes], 'ingress':{str(p):sorted(cidrs) for p,cidrs in actual.items()}}
result['assertions'] = {'each_node_has_only_own_role_group':True,'each_nic_has_only_own_role_group':True,'http_only_current_cloudflare_ipv4':True,'database_ingress_only_exact_declared_private_peers':True,'no_unexpected_ingress_or_ipv6':True}
print(json.dumps(result,indent=2))
