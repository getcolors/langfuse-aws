# AWS live verification

Status: **passed on September 10, 2026**. Live creation, public acceptance,
published-pin convergence, data continuity, recovery rehearsal, full deletion
and repeat deletion succeeded. Independent final audits found **zero remaining
deployment resources**, including all six EBS volumes, all four S3 buckets,
Cloudflare DNS, and local SSH artifacts. The test endpoint is no longer deployed.

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
22 vCPUs. A sibling Cloudflare token was verified with temporary DNS
record creation and deletion, and loaded only into ignored operator secrets. The actual
AWS profile successfully built and completed create dry-run using the copied
launcher and published package/dependency pins, without local overrides. Render inspection confirmed
six role-specific nodes, per-role security groups, encrypted volumes, and
separate S3 state keys for DNS and managed application storage.

## Offline verification completed

- Published Langfuse runtime pin: `d59cca7`; copied launcher commit: `4ce273a`.
- colors-compute: `09ec539`; Neon runtime: `9f8ccc1`.
- colors-compute tests: Python 511, Clojure 107 (1,331 assertions),
  TypeScript 316 plus type checks; 478 parity cases per implementation.
- OpenTofu validates five AWS provider configurations, including role
  security groups with managed and pre-existing SSH keys.
- Pre-live Langfuse integration tests: Python 70, Clojure 51 (179 assertions), TypeScript 51
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

## Completed live results

- Create 1 provisioned all six machines, four buckets, three IAM identities,
  the managed SSH key, and Cloudflare DNS. It failed at Ansible entry because
  Green expected keyword keys inside Terraform's nested credential output.
- Fix `d59cca7` normalizes those keys and tests the actual SDK decoder output.
  Green's full suite passes 52 tests / 184 assertions; focused Red and Blue
  storage tests and Red type checks also pass.
- Create 2 passed all stages: infrastructure 233.8 s, storage 23.0 s,
  DNS 5.4 s, SSH configuration 1.5 s, Ansible 923.3 s, acceptance 17.8 s.
  It used the local package with the tested fix and published dependency pins.
- The external verifier passed all 16 gates, including exact trace/generation
  contents, exact score readback, signed media roundtrip with SHA256 equality,
  default TLS validation, Cloudflare proxying, and incorrect/anonymous
  credential rejection. See `evidence/public-check-1.txt`.
- Create 3 passed using only the copied published launcher and immutable
  dependencies, with no local overrides: infrastructure 237.3 s, storage
  22.8 s, DNS 8.3 s, SSH 1.5 s, Ansible 365.8 s, acceptance 17.7 s.
  See `evidence/live-create-3.txt`.
- All 10 read-only continuity gates passed after Create 3: the original
  trace, generation, score, and media hash were retained. See
  `evidence/continuity-after-converge.txt`.
- Published-pin rehearsal passed: state/credential loading 63.2 s,
  restore-and-drill stage 189.5 s. It took fresh paired ClickHouse/Postgres
  backups, restored both stores, booted the pinned web image against them,
  verified project-key authentication, trace/generation/score contents and
  encrypted LLM connection access, then exercised ClickHouse replica loss
  during ingestion and Redis restart with a queued job. See
  `evidence/live-rehearse-1.txt` and `evidence/recovery-marker.json`.
- All 10 original-record continuity gates passed again after rehearsal.
  `evidence/services-after-rehearsal.json` independently confirms all services
  restored healthy, strict web/worker health 200, and no temporary restore
  containers. The original six instance and volume IDs were unchanged.
- Protected deletion was refused with exit 2 before any destructive stage.
  During authorized deletion, `evidence/writers-stopped.json` independently
  observed all writers stopped while all four buckets still existed.
- Before deletion, all six host monitors reported healthy; see
  `evidence/describe-1.txt`.
- Independent storage and IAM checks pass; see `evidence/storage-isolation.json`
  and `evidence/iam-isolation.json`. Every application identity is limited
  to its own bucket. State is versioned; all buckets are private/encrypted;
  media CORS is configured.
- Independent AWS network checks pass; see `evidence/network-isolation.json`.
  Each machine/NIC has only its own role SG. HTTP(S) accepts current Cloudflare
  IPv4 ranges; database ports accept exact declared private peers. SSH remains
  allowed from `0.0.0.0/0` as configured.
- Exact instance, volume and VPC IDs were captured before deletion. All six
  60 GiB root volumes are encrypted with deletion on termination enabled.

- Full deletion passed: writer cleanup 62.3 s, SSH configuration cleanup
  1.6 s, DNS 4.9 s, application storage 16.2 s, compute 518.3 s, managed
  backend finalization 28.9 s. See `evidence/live-delete-1.txt`.
- Repeated deletion passed with only state discovery and backend finalization;
  it required no remaining SSH key or machines. See `evidence/live-delete-2.txt`.
- Independent final AWS inventory found zero remaining resources and zero
  billable resources, with every recorded root volume absent. See
  `evidence/resources-after-delete.json`. Terminated instance descriptions
  in that inventory are historical records. DNS absence and removal of both
  local key files and all profile SSH aliases are recorded in
  `evidence/dns-after-delete.json` and `evidence/local-cleanup.json`.

## Completed verification sequence

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
