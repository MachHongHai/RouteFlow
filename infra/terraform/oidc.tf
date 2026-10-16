resource "google_iam_workload_identity_pool" "github" {
  count                     = var.github_repository == "" ? 0 : 1
  workload_identity_pool_id = "routeflow-github"
  display_name              = "RouteFlow GitHub deployments"
  depends_on                = [google_project_service.api]
}
resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.github_repository == "" ? 0 : 1
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/main'"
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}
resource "google_service_account" "deployer" {
  count      = var.github_repository == "" ? 0 : 1
  account_id = "${local.prefix}-deploy"
}
resource "google_service_account_iam_member" "federation" {
  count              = var.github_repository == "" ? 0 : 1
  service_account_id = google_service_account.deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repository}"
}
resource "google_project_iam_member" "deployment" {
  for_each = var.github_repository == "" ? toset([]) : toset([
    "roles/run.developer", "roles/artifactregistry.writer"
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer[0].email}"
}
resource "google_service_account_iam_member" "deployment_act_as" {
  for_each           = var.github_repository == "" ? toset([]) : toset(["api", "consumer", "produce", "transform", "migrate"])
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.prefix}-${each.value}@${var.project_id}.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer[0].email}"
  depends_on         = [module.runtime]
}
output "github_identity_provider" {
  value = var.github_repository == "" ? "" : google_iam_workload_identity_pool_provider.github[0].name
}
output "github_deployer" {
  value = var.github_repository == "" ? "" : google_service_account.deployer[0].email
}
