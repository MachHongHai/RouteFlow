output "api_url" { value = module.runtime.api_url }
output "consumer_url" { value = module.runtime.consumer_url }
output "archive_bucket" { value = module.data.archive_bucket }
output "workflow_name" { value = google_workflows_workflow.batch.id }
output "image_repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}" }
