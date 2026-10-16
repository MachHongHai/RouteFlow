variable "project_id" { type = string }
variable "region" { type = string }
variable "prefix" { type = string }
variable "image" { type = string }
variable "source_database_secret" { type = string }
variable "bucket" { type = string }
variable "dataset_ids" { type = map(string) }
variable "topic" { type = string }
variable "max_instances" { type = number }
locals {
  identities = toset(["api", "consumer", "produce", "transform", "migrate", "push"])
  analytics  = toset(["consumer", "transform", "produce"])
  env = {
    ENVIRONMENT          = "cloud", WAREHOUSE_MODE = "bigquery", PUBSUB_EMULATOR_HOST = "",
    GOOGLE_CLOUD_PROJECT = var.project_id, ARCHIVE_BUCKET = var.bucket,
    BIGQUERY_DATASET     = var.dataset_ids["raw"], GCP_REGION = var.region,
    TOPIC                = reverse(split("/", var.topic))[0]
  }
}
resource "google_service_account" "identity" {
  for_each   = local.identities
  account_id = "${var.prefix}-${each.value}"
}
resource "google_secret_manager_secret_iam_member" "database" {
  for_each  = setsubtract(local.identities, toset(["push"]))
  secret_id = var.source_database_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.identity[each.value].email}"
}
resource "google_pubsub_topic_iam_member" "producer" {
  topic  = var.topic
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.identity["produce"].email}"
}
resource "google_storage_bucket_iam_member" "archive_write" {
  bucket = var.bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.identity["consumer"].email}"
}
resource "google_storage_bucket_iam_member" "archive_read" {
  bucket = var.bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.identity["transform"].email}"
}
resource "google_project_iam_member" "query" {
  for_each = local.analytics
  project  = var.project_id
  role     = "roles/bigquery.jobUser"
  member   = "serviceAccount:${google_service_account.identity[each.value].email}"
}
resource "google_bigquery_dataset_iam_member" "consumer" {
  dataset_id = var.dataset_ids["raw"]
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.identity["consumer"].email}"
}
resource "google_bigquery_dataset_iam_member" "produce_wait" {
  dataset_id = var.dataset_ids["raw"]
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.identity["produce"].email}"
}
resource "google_bigquery_dataset_iam_member" "transform" {
  for_each   = var.dataset_ids
  dataset_id = each.value
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.identity["transform"].email}"
}
resource "google_cloud_run_v2_service" "service" {
  for_each            = toset(["api", "consumer"])
  name                = "${var.prefix}-${each.value}"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                  = google_service_account.identity[each.value].email
    max_instance_request_concurrency = 8
    timeout                          = "120s"
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }
    containers {
      image = var.image
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = false
      }
      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "SOURCE_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = var.source_database_secret
            version = "latest"
          }
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.database]
}
resource "google_cloud_run_v2_service_iam_member" "push" {
  location = var.region
  name     = google_cloud_run_v2_service.service["consumer"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.identity["push"].email}"
}
data "google_project" "current" {}
resource "google_service_account_iam_member" "token" {
  service_account_id = google_service_account.identity["push"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
resource "google_cloud_run_v2_job" "job" {
  for_each            = toset(["produce", "transform", "migrate"])
  name                = "${var.prefix}-${each.value}"
  location            = var.region
  deletion_protection = false
  template {
    task_count = 1
    template {
      service_account = google_service_account.identity[each.value].email
      max_retries     = 0
      timeout         = "900s"
      containers {
        image   = var.image
        command = ["python", "-m", "routeflow.cloud_job"]
        args    = [each.value]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        dynamic "env" {
          for_each = local.env
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name = "SOURCE_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.source_database_secret
              version = "latest"
            }
          }
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.database]
}
output "consumer_url" { value = google_cloud_run_v2_service.service["consumer"].uri }
output "api_url" { value = google_cloud_run_v2_service.service["api"].uri }
output "push_identity" { value = google_service_account.identity["push"].email }
output "job_names" { value = toset([for v in google_cloud_run_v2_job.job : v.name]) }
