variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "environment" {
  type    = string
  default = "portfolio"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,10}$", var.environment))
    error_message = "Use 1-11 lowercase letters/digits/hyphens, starting with a letter, to fit service-account IDs."
  }
}
variable "image" {
  type        = string
  description = "Immutable application image URI, preferably @sha256 digest"
}
variable "source_database_secret" {
  type        = string
  description = "Existing Secret Manager secret containing PostgreSQL SQLAlchemy URL with TLS"
}
variable "schedule" {
  type    = string
  default = "0 3 * * *"
}
variable "scheduler_paused" {
  type    = bool
  default = true
}
variable "archive_retention_days" {
  type    = number
  default = 90
}
variable "raw_retention_days" {
  type    = number
  default = 30
}
variable "max_instances" {
  type    = number
  default = 1
}
variable "billing_account" {
  type    = string
  default = ""
}
variable "monthly_budget_usd" {
  type    = number
  default = 1
}
variable "notification_email" {
  type        = string
  default     = ""
  description = "Optional email channel for the Pub/Sub backlog alert. Delivery still needs a cloud smoke test."
  validation {
    condition     = var.notification_email == "" || can(regex("^[^ @]+@[^ @]+\\.[^ @]+$", var.notification_email))
    error_message = "Use an email address or leave empty to omit the notification channel."
  }
}
variable "github_repository" {
  type        = string
  default     = ""
  description = "Optional exact owner/repo for GitHub OIDC deployment identity"
}
variable "spark_runner_url" {
  type        = string
  default     = ""
  description = "Optional authorized external Spark runner; POST must block until load completes. No cloud Spark cluster is created."
}
