variable "project_id" { type = string }
variable "region" { type = string }
variable "prefix" { type = string }
variable "archive_retention_days" { type = number }
variable "raw_retention_days" { type = number }
resource "google_pubsub_topic" "events" { name = "${var.prefix}-events" }
resource "google_pubsub_topic" "dlq" { name = "${var.prefix}-dlq" }
resource "google_pubsub_subscription" "dlq" {
  name                       = "${var.prefix}-dlq-audit"
  topic                      = google_pubsub_topic.dlq.id
  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }
}
resource "google_bigquery_dataset" "layer" {
  for_each                    = toset(["raw", "staging", "intermediate", "analytics"])
  dataset_id                  = "routeflow_${each.value}"
  location                    = var.region
  default_table_expiration_ms = var.raw_retention_days * 86400000
  delete_contents_on_destroy  = false
}
resource "google_bigquery_table" "raw" {
  dataset_id          = google_bigquery_dataset.layer["raw"].dataset_id
  table_id            = "raw_events"
  deletion_protection = true
  time_partitioning {
    type          = "DAY"
    field         = "event_time"
    expiration_ms = var.raw_retention_days * 86400000
  }
  clustering = ["event_type", "aggregate_id"]
  schema     = file("${path.module}/raw_schema.json")
}
resource "google_storage_bucket" "archive" {
  name                        = "${var.project_id}-${var.prefix}-archive"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  lifecycle_rule {
    condition { age = var.archive_retention_days }
    action { type = "Delete" }
  }
}
resource "google_bigquery_table" "spark" {
  for_each            = jsondecode(file("${path.module}/spark_schemas.json"))
  dataset_id          = google_bigquery_dataset.layer["raw"].dataset_id
  table_id            = "spark_${each.key}"
  deletion_protection = true
  schema              = jsonencode(each.value)
  time_partitioning {
    type          = "DAY"
    field         = "business_date"
    expiration_ms = var.raw_retention_days * 86400000
  }
}
output "archive_bucket" { value = google_storage_bucket.archive.name }
output "dataset_ids" { value = { for k, v in google_bigquery_dataset.layer : k => v.dataset_id } }
output "topic" { value = google_pubsub_topic.events.id }
output "dlq_topic" { value = google_pubsub_topic.dlq.id }
