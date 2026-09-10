# Langfuse on AWS

Deployment profile `langfuse-aws`, using the `getcolors/langfuse` package and
`getcolors/colors-compute`. Live verification passed on September 10, 2026,
including public API/media checks, repeat convergence, and backup recovery.
The test deployment was deleted; independent audits found zero remaining
resources. See [the verification report](verification.md) and its evidence.
The configured hostname is `langfuse-aws.bigconfig.online`.

Six Ubuntu machines host Neon Postgres, Redis, three ClickHouse replicas, and
Langfuse web/worker with Caddy. Cloudflare manages DNS and proxies HTTPS.
Four lifecycle-managed S3 buckets hold Terraform state, Neon layers/WAL,
Langfuse events/media, and backups. Application credentials are scoped to
their own buckets; infrastructure credentials stay on the operator machine.

## Run

Install Babashka, OpenTofu, Ansible, AWS CLI, Python 3 with boto3, and OpenSSH. The copied
`green` launcher resolves the package's immutable dependencies.

The `.envrc` loads AWS credentials from `../.envrc` and then the ignored
`.deployment-secrets` file. Store the Cloudflare token and three durable
application secrets in `.deployment-secrets`.
Provide `COLORS_PAR_AWS_ACCESS_KEY_ID`, `COLORS_PAR_AWS_SECRET_ACCESS_KEY`, and
`COLORS_PAR_CLOUDFLARE_API_TOKEN` (Zone:Read and DNS:Edit on bigconfig.online).
The application secrets are `COLORS_PAR_LANGFUSE_ENCRYPTION_KEY` (64 hex),
`COLORS_PAR_LANGFUSE_SALT` (at least 32 characters), and
`COLORS_PAR_LANGFUSE_INIT_USER_PASSWORD` (at least 12 characters). Preserve
them outside the machines: restoring encrypted database contents requires
the same encryption key and salt.

```sh
direnv allow
./green build
./green create
./green describe
./green rehearse
```

Committed desired state prevents destruction. To explicitly remove this
deployment, including its managed storage and all stored data:

```sh
COLORS_PAR_COMPUTE_PREVENT_DESTROY=false ./green delete
```

The live test used the Green implementation and published immutable pins.
Red and Blue passed offline builds and parity checks. This assessment uses
one availability zone and is not a production availability or performance
certification.
