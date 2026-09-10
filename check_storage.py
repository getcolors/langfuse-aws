#!/usr/bin/env python3
"""Verify managed S3 settings and credential scope without displaying keys."""
import json
import subprocess
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

PROFILE = 'langfuse-aws'
ACCOUNT = '251213589273'
REGION = 'us-east-1'
HOST = 'langfuse-aws.bigconfig.online'
BUCKETS = {role: f'{PROFILE}-{role}-{ACCOUNT}-{REGION}' for role in ('state', 'neon', 'data', 'backup')}


def main():
    session = boto3.Session(region_name=REGION)
    assert session.client('sts').get_caller_identity()['Account'] == ACCOUNT
    storage = session.client('s3')
    results = []
    for role, bucket in BUCKETS.items():
        block = storage.get_public_access_block(Bucket=bucket)['PublicAccessBlockConfiguration']
        assert all(block.values()), f'{role}: incomplete public-access block'
        rules = storage.get_bucket_encryption(Bucket=bucket)['ServerSideEncryptionConfiguration']['Rules']
        assert rules[0]['ApplyServerSideEncryptionByDefault']['SSEAlgorithm'] in ('AES256', 'aws:kms')
        if role == 'neon':
            try:
                lifecycle = storage.get_bucket_lifecycle_configuration(Bucket=bucket)
                assert not lifecycle.get('Rules'), 'Neon bucket must not expire live layers or WAL'
            except ClientError as error:
                assert error.response['Error']['Code'] == 'NoSuchLifecycleConfiguration'
        results.append({'bucket': bucket, 'public_access_block': 'PASS', 'encryption': 'PASS'})
    cors = storage.get_bucket_cors(Bucket=BUCKETS['data'])['CORSRules']
    assert any('https://' + HOST in rule['AllowedOrigins'] and {'GET', 'PUT', 'HEAD'} <= set(rule['AllowedMethods']) for rule in cors)
    assert storage.get_bucket_versioning(Bucket=BUCKETS['state']).get('Status') == 'Enabled'

    stage = Path(__file__).resolve().parent / '.colors' / PROFILE / 'langfuse-storage'
    raw = subprocess.check_output(['tofu', 'output', '-json', 'credentials'], cwd=stage, stderr=subprocess.DEVNULL)
    credentials = json.loads(raw)
    scope = []
    for role in ('neon', 'data', 'backup'):
        pair = credentials[role]
        client = boto3.client('s3', region_name=REGION,
                              aws_access_key_id=pair['access_key_id'],
                              aws_secret_access_key=pair['secret_access_key'])
        client.list_objects_v2(Bucket=BUCKETS[role], MaxKeys=1)
        for other, bucket in BUCKETS.items():
            if other == role:
                continue
            try:
                client.list_objects_v2(Bucket=bucket, MaxKeys=1)
            except ClientError as error:
                assert error.response['Error']['Code'] == 'AccessDenied', f'{role} to {other}: unexpected error'
            else:
                raise AssertionError(f'{role} credential unexpectedly reads {other}')
        scope.append({'identity': role, 'own_bucket_list': 'PASS', 'all_other_bucket_lists_denied': 'PASS'})
    print(json.dumps({'status': 'PASS', 'buckets': results, 'media_cors': 'PASS',
                      'state_versioning': 'PASS', 'credential_isolation': scope}, indent=2))


if __name__ == '__main__':
    main()
