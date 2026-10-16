locals {
  prefix = "routeflow-${var.environment}"
  apis = toset(["run.googleapis.com", "pubsub.googleapis.com", "bigquery.googleapis.com",
    "storage.googleapis.com", "secretmanager.googleapis.com", "workflows.googleapis.com",
    "workflowexecutions.googleapis.com", "cloudscheduler.googleapis.com", "monitoring.googleapis.com",
    "logging.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com",
  "sts.googleapis.com", "artifactregistry.googleapis.com", "billingbudgets.googleapis.com"])
}
resource "google_project_service" "api" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}
resource "google_artifact_registry_repository" "images" {
  repository_id = "routeflow"
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
  cleanup_policies {
    id     = "old-images"
    action = "DELETE"
    condition { older_than = "604800s" }
  }
  cleanup_policies {
    id     = "keep-latest"
    action = "KEEP"
    most_recent_versions { keep_count = 2 }
  }
}
module "data" {
  source                 = "./modules/data"
  project_id             = var.project_id
  region                 = var.region
  prefix                 = local.prefix
  archive_retention_days = var.archive_retention_days
  raw_retention_days     = var.raw_retention_days
  depends_on             = [google_project_service.api]
}
module "runtime" {
  source                 = "./modules/runtime"
  project_id             = var.project_id
  region                 = var.region
  prefix                 = local.prefix
  image                  = var.image
  source_database_secret = var.source_database_secret
  bucket                 = module.data.archive_bucket
  dataset_ids            = module.data.dataset_ids
  topic                  = module.data.topic
  max_instances          = var.max_instances
  depends_on             = [google_project_service.api]
}
resource "google_pubsub_subscription" "push" {
  name                       = "${local.prefix}-push"
  topic                      = module.data.topic
  ack_deadline_seconds       = 120
  message_retention_duration = "86400s"
  push_config {
    push_endpoint = "${module.runtime.consumer_url}/pubsub/push"
    oidc_token {
      service_account_email = module.runtime.push_identity
      audience              = module.runtime.consumer_url
    }
  }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
  dead_letter_policy {
    dead_letter_topic     = module.data.dlq_topic
    max_delivery_attempts = 10
  }
  expiration_policy { ttl = "" }
  depends_on = [module.runtime]
}
data "google_project" "current" {}
resource "google_pubsub_topic_iam_member" "dlq_forward" {
  topic  = module.data.dlq_topic
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
resource "google_pubsub_subscription_iam_member" "retry_ack" {
  subscription = google_pubsub_subscription.push.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
resource "google_service_account" "workflow" { account_id = "${local.prefix}-workflow" }
resource "google_service_account" "scheduler" { account_id = "${local.prefix}-scheduler" }
resource "google_cloud_run_v2_job_iam_member" "workflow" {
  for_each = module.runtime.job_names
  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.workflow.email}"
}
resource "google_project_iam_member" "workflow_status" {
  project = var.project_id
  role    = "roles/run.viewer"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}
resource "google_workflows_workflow" "batch" {
  name            = "${local.prefix}-batch"
  region          = var.region
  service_account = google_service_account.workflow.id
  source_contents = templatefile("${path.module}/workflow.yaml.tftpl", {
    project          = var.project_id, region = var.region, prefix = local.prefix,
    spark_runner_url = var.spark_runner_url
  })
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "scheduler_workflow" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}
resource "google_cloud_scheduler_job" "batch" {
  name      = "${local.prefix}-batch"
  region    = var.region
  schedule  = var.schedule
  time_zone = "Etc/UTC"
  paused    = var.scheduler_paused
  http_target {
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.batch.id}/executions"
    http_method = "POST"
    body        = base64encode("{}")
    headers     = { "Content-Type" = "application/json" }
    oauth_token { service_account_email = google_service_account.scheduler.email }
  }
}
resource "google_billing_budget" "portfolio" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "RouteFlow warning; not a spending cap"
  budget_filter { projects = ["projects/${data.google_project.current.number}"] }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 1.0 }
}
resource "google_monitoring_notification_channel" "email" {
  count        = var.notification_email == "" ? 0 : 1
  display_name = "RouteFlow operator"
  type         = "email"
  labels       = { email_address = var.notification_email }
  depends_on   = [google_project_service.api]
}
resource "google_monitoring_alert_policy" "backlog" {
  display_name          = "RouteFlow Pub/Sub processing lag"
  combiner              = "OR"
  notification_channels = google_monitoring_notification_channel.email[*].name
  conditions {
    display_name = "Unacked events older than 10 minutes"
    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND metric.type = \"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.label.subscription_id = \"${google_pubsub_subscription.push.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 600
      duration        = "300s"
    }
  }
  depends_on = [google_project_service.api]
}
