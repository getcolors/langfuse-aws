"""Read-only inventory for this exact deployment; never print credentials/state."""
import argparse
import json
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

PROFILE = 'langfuse-aws'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expect-absent', action='store_true', help='Fail unless every recorded deployment resource is absent')
args = parser.parse_args()
REGION = 'us-east-1'
ACCOUNT = '251213589273'
BUCKETS = [f'{PROFILE}-{purpose}-{ACCOUNT}-{REGION}' for purpose in ('state', 'data', 'neon', 'backup')]
session = boto3.Session(region_name=REGION)
assert session.client('sts').get_caller_identity()['Account'] == ACCOUNT
compute = session.client('ec2')
filters = [{'Name': 'tag:Name', 'Values': [PROFILE, PROFILE + '-*']}]

def pages(operation, field, **kwargs):
    paginator = compute.get_paginator(operation)
    return [value for page in paginator.paginate(**kwargs) for value in page.get(field, [])]

def name(resource):
    return next((t['Value'] for t in resource.get('Tags', []) if t['Key'] == 'Name'), None)

inventory = {'profile': PROFILE, 'region': REGION}
reservations = pages('describe_instances', 'Reservations', Filters=filters)
inventory['instances'] = [{'id': i['InstanceId'], 'name': name(i), 'state': i['State']['Name'], 'public_ip': i.get('PublicIpAddress'), 'private_ip': i.get('PrivateIpAddress'),
                          'root_device': i.get('RootDeviceName'), 'ebs_volumes': [{'id': d['Ebs']['VolumeId'], 'device': d['DeviceName'], 'root': d['DeviceName'] == i.get('RootDeviceName'), 'delete_on_termination': d['Ebs']['DeleteOnTermination']} for d in i.get('BlockDeviceMappings', []) if 'Ebs' in d]}
                          for r in reservations for i in r['Instances']]
for operation, field, id_key in [('describe_vpcs', 'Vpcs', 'VpcId'), ('describe_subnets', 'Subnets', 'SubnetId'),
        ('describe_route_tables', 'RouteTables', 'RouteTableId'), ('describe_internet_gateways', 'InternetGateways', 'InternetGatewayId'),
        ('describe_security_groups', 'SecurityGroups', 'GroupId')]:
    resources = pages(operation, field, Filters=filters)
    inventory[field] = [{'id': r[id_key], 'name': name(r), **({'ingress': r['IpPermissions'], 'egress': r['IpPermissionsEgress']} if field == 'SecurityGroups' else {})} for r in resources]
inventory['KeyPairs'] = [{'id': k['KeyPairId'], 'name': k['KeyName']} for k in compute.describe_key_pairs(Filters=[{'Name': 'key-name', 'Values': [PROFILE]}])['KeyPairs']]
# Preserve exact resource IDs before deletion: root EBS volumes have no Name tag.
baseline_path = Path(__file__).with_name('resource-baseline.json')
if baseline_path.exists():
    baseline = json.loads(baseline_path.read_text())
    assert (baseline['profile'], baseline['region'], baseline['account']) == (PROFILE, REGION, ACCOUNT)
else:
    live_instances = [i for i in inventory['instances'] if i['state'] == 'running']
    assert len(live_instances) == 6, 'Refuse incomplete initial resource baseline'
    baseline = {'profile': PROFILE, 'region': REGION, 'account': ACCOUNT,
                'instance_ids': [i['id'] for i in live_instances],
                'volumes': [v for i in live_instances for v in i['ebs_volumes']],
                'vpc_ids': [v['id'] for v in inventory['Vpcs']]}
    assert len(baseline['volumes']) == 6 and len(baseline['vpc_ids']) == 1
    baseline_path.write_text(json.dumps(baseline, indent=2))
    baseline_path.chmod(0o600)
inventory['recorded_ebs_volumes'] = baseline['volumes']
volume_ids = [v['id'] for v in baseline['volumes']]
inventory['Volumes'] = [{'id': v['VolumeId'], 'state': v['State'], 'size_gib': v['Size'], 'encrypted': v['Encrypted']}
                        for v in pages('describe_volumes', 'Volumes', Filters=[{'Name': 'volume-id', 'Values': volume_ids}])]
# Include implicit default groups/routes/NACLs and ENIs by the recorded VPC ID.
inventory['VpcDependencies'] = {}
for operation, field, id_key, filter_key in [
        ('describe_vpcs', 'Vpcs', 'VpcId', 'vpc-id'),
        ('describe_subnets', 'Subnets', 'SubnetId', 'vpc-id'),
        ('describe_route_tables', 'RouteTables', 'RouteTableId', 'vpc-id'),
        ('describe_internet_gateways', 'InternetGateways', 'InternetGatewayId', 'attachment.vpc-id'),
        ('describe_security_groups', 'SecurityGroups', 'GroupId', 'vpc-id'),
        ('describe_network_interfaces', 'NetworkInterfaces', 'NetworkInterfaceId', 'vpc-id'),
        ('describe_network_acls', 'NetworkAcls', 'NetworkAclId', 'vpc-id')]:
    resources = pages(operation, field, Filters=[{'Name': filter_key, 'Values': baseline['vpc_ids']}])
    inventory['VpcDependencies'][field] = [{'id': r[id_key], 'name': name(r)} for r in resources]
storage = session.client('s3')
inventory['buckets'] = []
for bucket in BUCKETS:
    try:
        storage.head_bucket(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
        tags = storage.get_bucket_tagging(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)['TagSet']
        inventory['buckets'].append({'name': bucket, 'status': 'present', 'ownership_tags': {t['Key']: t['Value'] for t in tags if t['Key'].startswith('colors:')}})
    except ClientError as error:
        code = error.response['Error']['Code']
        inventory['buckets'].append({'name': bucket, 'status': 'absent' if code in ('404', 'NoSuchBucket', 'NotFound') else 'unverified', 'code': code})
inventory['iam_users'] = []
# List only names belonging to this deployment; never access or print access keys.
for page in session.client('iam').get_paginator('list_users').paginate():
    inventory['iam_users'].extend({'name': u['UserName'], 'status': 'present'}
                                  for u in page['Users'] if u['UserName'].startswith(PROFILE + '-'))
remaining_ids = {i['id'] for i in inventory['instances'] if i['state'] != 'terminated'}
for kind in ('Vpcs', 'Subnets', 'RouteTables', 'InternetGateways', 'SecurityGroups', 'KeyPairs', 'Volumes'):
    remaining_ids.update(item['id'] for item in inventory[kind])
for items in inventory['VpcDependencies'].values():
    remaining_ids.update(item['id'] for item in items)
inventory['remaining_resource_count'] = len(remaining_ids) + sum(b['status'] != 'absent' for b in inventory['buckets']) + len(inventory['iam_users'])
inventory['all_recorded_volumes_absent'] = len(inventory['Volumes']) == 0
inventory['remaining_billable_resource_count'] = sum(i['state'] != 'terminated' for i in inventory['instances']) + len(inventory['Volumes']) + sum(b['status'] != 'absent' for b in inventory['buckets'])
print(json.dumps(inventory, indent=2))
if args.expect_absent:
    assert inventory['remaining_resource_count'] == 0, 'Deployment resources remain or absence is unverified'
