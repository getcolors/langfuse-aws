# AWS live verification

Status: offline preparation verified; live deployment awaits Cloudflare credentials.
No live success is claimed, and no AWS resources have been created.

## Deployment

- AWS account `251213589273`, region `us-east-1`, availability zone `us-east-1a`.
- Profile `langfuse-aws`; public hostname `langfuse-aws.bigconfig.online`.
- Ubuntu 24.04 amd64, AMI `ami-025d99823a4caad37` verified available.
- Five `t3.xlarge` machines (Neon, app, three ClickHouse replicas), one
  `t3.small` Redis machine; 60 GiB encrypted root volumes.
- Four managed S3 buckets: state, Neon layers/WAL, events/media, backups.
- Cloudflare DNS and proxied HTTPS; app HTTP(S) ingress restricted to
  Cloudflare ranges. Database ingress restricted to required peer addresses.

AWS identity and the 32-vCPU quota were verified. No running EC2 instances
were present in this region at preflight. The requested topology needs
22 vCPUs. Cloudflare credentials are still required for the first live run. The actual
AWS profile successfully built and completed create dry-run using the copied
launcher and published package/dependency pins, without local overrides. Render inspection confirmed
six role-specific nodes, per-role security groups, encrypted volumes, and
separate S3 state keys for DNS and managed application storage.

## Offline verification completed

- Published Langfuse runtime pin: `0562cb3`; copied launcher commit: `e65b922`.
- colors-compute: `09ec539`; Neon runtime: `9f8ccc1`.
- colors-compute tests: Python 511, Clojure 107 (1,331 assertions),
  TypeScript 316 plus type checks; 478 parity cases per implementation.
- OpenTofu validates five AWS provider configurations, including role
  security groups with managed and pre-existing SSH keys.
- Langfuse tests: Python 70, Clojure 51 (179 assertions), TypeScript 51
  (214 assertions) plus type checks.
- All three implementations produce identical output for five fixtures,
  including managed AWS roles and S3 storage.
- Nine runtime checks cover S3 provider selection and fail-closed writer
  shutdown. Rendered AWS cleanup passes Ansible syntax validation.
- Copied launcher checks pass, including dependency-pin agreement.
- Published Red and Blue payloads build the actual AWS profile with fresh
  dependency caches, no credentials and no local-library overrides. Their
  62 generated artifacts are byte-identical and pass AWS contract checks.
- Actual published Green launcher build, create dry-run, and delete dry-run
  pass; command output is in `evidence/offline-*.txt`.

## Live verification to complete

1. Live creation through colors-compute, including managed state bootstrap.
2. Built-in acceptance across the six hosts.
3. `check_public.py`: public HTTPS and Cloudflare, exact OTLP trace and
   generation content, exact score readback, signed S3 media roundtrip,
   and rejection of anonymous and incorrect API credentials.
4. `check_storage.py`: private encrypted buckets, state versioning, media
   CORS, each application identity confined to its own bucket.
5. Repeat converge and read-only continuity verification.
6. Backup restore rehearsal and service failure drills.
7. Guarded deletion, full deletion, repeated deletion, and independent
   inventory of recorded EC2, EBS, network, keypair, IAM, S3 and DNS resources.

## Limits

This is a functional deployment and lifecycle assessment in one availability
zone. It does not establish multi-zone availability, production capacity,
or a workload-specific latency target. The built-in smoke script calls
loopback; external HTTPS evidence comes from the separate public verifier.

## Reference contract

Langfuse separates web and worker containers and recommends at least two
CPUs and 4 GB RAM per container for production. This assessment puts both
on a 4-vCPU, 16-GiB app host.
[Container guidance](https://langfuse.com/self-hosting/deployment/infrastructure/containers).

Native Amazon S3 is officially supported for events and media.
[Blob storage configuration](https://langfuse.com/self-hosting/deployment/infrastructure/blobstorage).

The public verifier uses the Observations API v2 and the score API available
in the pinned 4.27.0 release.
[Observations API](https://langfuse.com/docs/api-and-data-platform/features/observations-api),
[score API definition](https://github.com/langfuse/langfuse/blob/v4.27.0/fern/apis/server/definition/scores-v3.yml).
