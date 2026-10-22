# Opt-in cloud deployment

Status: integrations are implemented; Terraform is validated offline. No GCP resources were
created, no billing APIs were enabled in a real project and no cloud credentials were used.
Use a separate GCP project for each environment: the dbt dataset IDs are intentionally fixed.

First-time setup with the Windows D/E helpers: [Vietnamese GCP guide](GCP_GETTING_STARTED_VI.md).
`scripts/gcloud.ps1` uses the existing pinned Docker image and stores CLI/ADC configuration on D.
`python -m routeflow.cloud_preflight` checks a private `cloud.auto.tfvars.json`; add `--online`
only after ADC exists to read project, billing and enabled APIs. This check never deploys and does
not validate runtime IAM, database reachability, image availability or actual BQ/GCS writes.
Optional `notification_email` creates the Pub/Sub backlog email channel; delivery still needs a
smoke test. Billing budgets are configured separately. See [remaining gaps](PROJECT_GAPS_VI.md).

1. Choose a billing-enabled GCP project and external PostgreSQL source. A TLS connection string
   must use `postgresql+psycopg://...?...sslmode=require`. Create a dedicated database role with
   schema migration privileges for the migrate job; application roles can be narrowed further
   after bootstrap. The reference configuration uses one URL secret for the shared control plane.
2. Authenticate as an infrastructure administrator using ADC. Bootstrap only the APIs, Artifact
   Registry and an existing Secret Manager secret. Supply its value through a local protected
   file or console; do not put credentials into Terraform variables or Git history.
3. Build the **runtime** image and upload it to Artifact Registry, then provide an immutable image
   URI in `infra/terraform/terraform.tfvars` (copy the example). Build `--target runtime` to avoid
   packaging the Spark distribution into Cloud Run.
4. Run the checks below and review the complete Terraform plan. Applying is an explicit owner
   action that can create billable resources. The scheduler is paused by default.

```bash
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -out=review.tfplan
# Only after reviewing resources, IAM, regions and costs:
terraform -chdir=infra/terraform apply review.tfplan
```

For first-time image bootstrap, an owner may use a **reviewed targeted plan** for
`google_project_service.api` and `google_artifact_registry_repository.images`, upload the image,
then review/apply a full plan. This solves the image-before-service dependency without placeholder
public images. Secret Manager provisioning is kept outside state to avoid managing secret payloads.

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
docker build --target runtime -t us-central1-docker.pkg.dev/YOUR_PROJECT/routeflow/app:YOUR_COMMIT .
docker push us-central1-docker.pkg.dev/YOUR_PROJECT/routeflow/app:YOUR_COMMIT
gcloud run jobs execute routeflow-portfolio-migrate --region us-central1 --project YOUR_PROJECT --wait
gcloud run jobs execute routeflow-portfolio-produce --region us-central1 --project YOUR_PROJECT --wait
gcloud run jobs execute routeflow-portfolio-transform --region us-central1 --project YOUR_PROJECT --wait
```

The production consumer is a private Cloud Run service. Pub/Sub push carries an OIDC token with the
consumer URL as audience. Only the push service account is granted `roles/run.invoker` on that
service. There is no public `allUsers` binding. Cloud Run verifies identity before the application
endpoint executes. A 204 acknowledges completed RAW ingestion or durable quarantine; 503 requests
redelivery. Local pull uses ack/nack after the same processing method. Native cloud DLQ forwarding
needs both the Pub/Sub service-agent publisher and subscription subscriber bindings in Terraform.

Separate runtime identities are created for API, consumer, producer, transform, migrations and
push. Dataset IAM is scoped to the datasets; archive writer/readers are scoped to the bucket.
BigQuery job submission and workflow execution-status viewing require project-level roles.
Scheduler's identity has the project's Workflows invoker role. No default compute identity is used.
GCP service-agent materialization and organization IAM restrictions still require cloud smoke tests.

The `produce` job generates ten orders, drains pending outbox events and waits for their actual
RAW IDs. The `transform` job runs dbt build (including tests) then source reconciliation. Workflows
waits on each Cloud Run Job operation, so transformation failures stop the workflow. Resume the
one Scheduler job only after manual smoke tests and cost review.

GitHub deployment is manual `workflow_dispatch`, gated by the `gcp` environment and repository
variables `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`, optional `GCP_REGION`.
Set `github_repository=owner/repo` to generate WIF identities restricted to that repository's main
branch. The deployer can update Cloud Run services/jobs and upload images, but cannot apply
Terraform/IAM. It runs migration, ingestion and transformation smoke jobs after deployment.
Applications remain private. Use a separately authorized user identity / Cloud Run proxy for API
access. Configure environment protection rules in GitHub if a review gate is desired.

Cloud Spark is optional and not represented as an ordinary Cloud Run Job. Use an independently
authorized cluster/runner with the same Spark/Python versions, a pinned Hadoop-3 GCS connector on
the classpath and ADC credentials. Set `ARCHIVE_BUCKET`, `DATA_LAKE_PATH=gs://BUCKET/lake`,
`SOURCE_DATABASE_URL`, `WAREHOUSE_MODE=bigquery`, `GOOGLE_CLOUD_PROJECT`, and `GCP_REGION`. Submit
`scripts/spark_job.py` to that cluster. `gs://` input/output and BigQuery Parquet load integration
are implemented, but require cloud validation. The runner needs bucket read/write, RAW dataset
editor and BigQuery job-user permissions. GCS's connector and ADC configuration are operator
dependencies, not silently downloaded or deployed by RouteFlow.

An optional `spark_runner_url` in Workflows inserts an OIDC-authenticated blocking HTTP call
between `produce` and `transform`. The owner must supply and authorize that endpoint. Its response
must mean the Spark job and warehouse loading completed, not merely that a job was queued.
Leaving it empty skips cloud Spark and leaves the GPS tables empty while streaming marts work.
