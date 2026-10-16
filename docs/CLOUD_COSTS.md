# Cloud costs and shutdown controls

Pricing pages were checked on 2026-10-16. These are published allowances, not measured RouteFlow
bills or a promise of zero cost. Local execution is the fully free demonstration path. GCP billing
must be explicitly enabled by the owner; Terraform is never applied by project scripts or CI.

| Resource | Published assumption | RouteFlow control |
|---|---|---|
| Cloud Run request billing | 2M requests, 180k vCPU-seconds, 360k GB-seconds monthly | Private services, min 0 / max 1 instance |
| Pub/Sub | First 10 GiB monthly | Daily ten-order workload, one-day main retention |
| BigQuery | 10 GiB storage, 1 TiB querying monthly | 100 MB query limit, 30-day RAW expiration |
| Regional GCS | 5 GB-month, 5k Class A / 50k Class B operations monthly in eligible US regions | `us-central1`, 90-day archive lifecycle |
| Artifact Registry | 0.5 GB storage monthly | Automatic old-image cleanup, keep two versions |
| Secret Manager | Six active versions, 10k accesses monthly | One database URL secret |

These account-shared allowances and regional conditions are from
[Google Cloud Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features).
Cloud Run **Jobs** use instance-based pricing and have separate allowances; do not apply the request
billing row to jobs. See [Cloud Run pricing](https://cloud.google.com/run/pricing).

One daily Scheduler job is created paused; up to three jobs per billing account are free, and paused
jobs still count. See [Scheduler pricing](https://cloud.google.com/scheduler/pricing).
Workflows has a limited free step allowance; connector polling counts toward execution usage.
See [Workflows pricing](https://cloud.google.com/workflows/pricing).

The source database is intentionally external PostgreSQL, supplied through Secret Manager. Cloud
SQL is not required because its ongoing cost is unsuitable for this goal. Neon is one possible
free source: the current [Neon pricing page](https://neon.com/pricing) lists 100 CU-hours and 1 GB
storage per free project, with idle scale-to-zero and a separate network-transfer allowance.
No provider account has been created or verified for this repository. Keep TLS enabled, restrict
database privileges, choose a nearby available region and inspect the provider console before use.

Expected demonstration usage is ten orders/day, roughly a few hundred events/day including GPS,
two short jobs/day, and no continuously polling relay in GCP. This is a planning assumption only.
API-created cloud orders remain in the outbox until the bounded producer/relay job runs. Continuous
low-latency relay deployment is deliberately outside this low-cost cloud configuration.

The BigQuery adapter uses free batch load APIs rather than legacy streaming inserts. Loading one
message per job is appropriate only for this tiny demo and consumes table load-job quotas. Do not
send the 1000-point GPS benchmark to cloud; use local Spark. A larger deployment must batch cloud
loads from GCS before enabling high-volume GPS. See
[BigQuery pricing](https://cloud.google.com/bigquery/pricing) and
[BigQuery load quotas](https://cloud.google.com/bigquery/quotas#load_jobs).

Remaining billing risks include container images exceeding the small registry allowance, outbound
traffic to external PostgreSQL, archive operations/replays, BigQuery scans and ingestion quota
retries, retained logs, and optional Spark infrastructure. Images include both dbt adapters and may
exceed the registry allowance even with cleanup; build locally and deploy briefly if minimizing cost.
Cloud Run limits, budgets and alerts are **not hard spending caps**. The optional budget defaults
to USD 1 and requires a billing account ID. Alert notification channels must be configured by the
operator; the default Monitoring policy is visible in the console without sending email.

Pause workload generation first:

```bash
gcloud scheduler jobs pause routeflow-portfolio-batch --location us-central1 --project YOUR_PROJECT
```

Private services scale to zero when idle. Pausing the scheduler does not revoke callers, purge
message backlogs or stop an already running job. Inspect executions and cancel any active jobs in
the Cloud Run console, revoke unwanted invokers and check usage dashboards.

To remove infrastructure deliberately, first export important RAW/archive data. Disable table
deletion protection in Terraform, review/apply that protection-only change, empty only the intended
archive bucket if its data is no longer needed, then review a destroy plan:

```bash
terraform -chdir=infra/terraform plan -destroy -out=destroy.tfplan
terraform -chdir=infra/terraform apply destroy.tfplan
```

The bucket has `force_destroy=false` and datasets refuse deleting remaining tables, so destruction
fails safely until the owner handles retained data. Secret versions and the external PostgreSQL
account are not owned by this Terraform state and require separate cleanup. Never destroy resources
from another project's state. No destroy or cloud apply command was executed during development.
