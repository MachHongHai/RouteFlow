# Kết nối GCP lần đầu cho RouteFlow

Triển khai GCP thật chưa được xác minh. Hướng dẫn này chuẩn bị project, billing, xác thực và
kiểm tra trước triển khai. Kết quả local streaming, Spark và dbt nằm trong
[validation](VALIDATION.md); chúng không thay thế cloud smoke test.

## 1. Tạo project trên trình duyệt

1. Đăng nhập [Google Cloud Console](https://console.cloud.google.com/).
2. Bấm bộ chọn project ở thanh trên, chọn **New Project** / **Create project**.
3. Project name: `RouteFlow Demo`. Giữ Project ID do Google gợi ý hoặc chọn một ID riêng.
   Ví dụ minh họa: `routeflow-demo-123456`; ID này chưa được tạo hay kiểm tra còn trống.
4. Chọn **No organization** nếu có; nếu tài khoản trường/công ty bắt buộc organization,
   cần quản trị viên cấp quyền tạo project. Bấm **Create**, rồi chọn project vừa tạo.
5. Ghi lại **Project ID**, không nhầm với Project name hay Project number. Project ID không đổi
   được sau khi tạo. Xem [hướng dẫn Google](https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects).

Giữ mật khẩu, thông tin billing và khóa service account ngoài repository.
Dùng Project ID để chuẩn bị cấu hình ở bước tiếp theo.

## 2. Kiểm tra Billing và đặt budget

Trong Console, mở **Billing** và kiểm tra project được liên kết với tài khoản billing phù hợp.
Nếu dùng Free Trial, kiểm tra điều kiện và hạn mức áp dụng trực tiếp tại
[Google Cloud Free Program](https://docs.cloud.google.com/free/docs/free-cloud-features).

Trong **Billing → Budgets & alerts**, tạo budget chỉ áp dụng cho project RouteFlow, chọn mức
nhỏ phù hợp với khả năng chi trả và nhận email ở các ngưỡng như 50%, 90%, 100%. Budget là cảnh báo,
không tự ngắt dịch vụ hoặc chặn tiền phát sinh. Xem
[hướng dẫn budget](https://docs.cloud.google.com/billing/docs/how-to/budgets).

Chưa tạo Cloud SQL, VM hoặc Dataproc ở bước này. Mặc định Terraform giữ Scheduler paused,
Cloud Run scale-to-zero, tối đa một instance; cấu hình đó không bảo đảm hóa đơn bằng 0.

## 3. Đăng nhập với helper Windows D/E

Helper yêu cầu [cấu hình lưu trữ D/E](DISK_STORAGE.md). `scripts/gcloud.ps1` dùng image Google
Cloud CLI khóa digest với `--pull=never`; image cần có sẵn trong Docker. File cấu hình,
log CLI và credentials được bind mount tại `D:\DevCache\gcloud`. Phần ghi tạm trong container
nằm trong Docker trên E. Cách dùng container được Google mô tả tại
[Google Cloud CLI Docker](https://docs.cloud.google.com/sdk/docs/downloads-docker).

Mở PowerShell của bạn và chạy, thay `YOUR_PROJECT_ID` bằng ID thật:

```powershell
.\scripts\gcloud.ps1 --version
.\scripts\gcloud.ps1 auth login
.\scripts\gcloud.ps1 config set project YOUR_PROJECT_ID
.\scripts\gcloud.ps1 auth application-default login
.\scripts\gcloud.ps1 auth application-default set-quota-project YOUR_PROJECT_ID
```

Lệnh login tự thêm `--no-launch-browser`. Mở URL do gcloud đưa ra trong trình duyệt,
chọn đúng tài khoản, đồng ý quyền sau khi đọc, rồi dán authorization code **vào terminal đang
đợi**. Hai lần login có mục đích khác nhau: `auth login` cho gcloud;
`application-default login` cho thư viện Python và Terraform. Google mô tả luồng này tại
[ADC login](https://docs.cloud.google.com/sdk/gcloud/reference/auth/application-default/login).

Nếu quota-project báo thiếu quyền hoặc API chưa bật, giữ nguyên thông báo để xử lý IAM/API;
không tải khóa JSON service account để né lỗi. File ADC dự kiến nằm ở
`D:\DevCache\gcloud\application_default_credentials.json`. `scripts/dev.ps1` đặt
`CLOUDSDK_CONFIG` đúng vị trí này cho Python. Không commit file ADC.

## 4. Kiểm tra kết nối bằng thao tác chỉ đọc

```powershell
.\scripts\gcloud.ps1 projects describe YOUR_PROJECT_ID --format='value(projectId,lifecycleState)'
.\scripts\gcloud.ps1 billing projects describe YOUR_PROJECT_ID --format='value(billingEnabled)'
```

Mong đợi: project đúng ID, trạng thái `ACTIVE`, billing enabled. Lỗi 403/404 cần kiểm tra tài khoản,
project và quyền trước khi triển khai. Đăng nhập thành công chưa chứng minh toàn bộ quyền deploy.

## 5. Chuẩn bị cấu hình và kiểm tra trước triển khai

```powershell
Copy-Item infra\terraform\cloud.auto.tfvars.json.example infra\terraform\cloud.auto.tfvars.json
.\scripts\dev.ps1 uv run python -m routeflow.cloud_preflight
```

Lần đầu **phải báo blocked** vì còn placeholder image/project hoặc thiếu ADC. Không thay digest
bằng chuỗi giả chỉ để kiểm tra pass. Khi đã chọn đúng project, tạo/upload image thực và có digest,
điền `project_id`, `image`, `source_database_secret`, `notification_email`; giữ
`scheduler_paused=true`, `max_instances=1`. Không đồng thời dùng một `terraform.tfvars` có giá trị
mâu thuẫn với JSON. JSON thật được Git ignore. Secret chỉ ghi **tên**, không ghi giá trị kết nối.

Sau khi đã cấu hình và có ADC:

```powershell
.\scripts\dev.ps1 uv run python -m routeflow.cloud_preflight --online
```

Chế độ mặc định không gọi GCP. `--online` chỉ GET project, billing và danh sách API enabled qua
ADC hiện có, có timeout và phân trang. Nó không bật API, đọc secret payload hay tạo tài nguyên.
Mã thoát 1 nghĩa là có blocker; mã 0 chỉ có nghĩa các kiểm tra đã thực hiện không thấy blocker.
`deployment_verified` luôn false vì công cụ này không chạy các cloud smoke test.

## 6. Những điều phải hoàn thành trước khi deploy thật

| Phần | Cần chuẩn bị / bằng chứng |
|---|---|
| Project + Billing + ADC | ID thật, billing, kết nối chỉ đọc và quyền phù hợp |
| PostgreSQL nguồn/control plane | Database cloud mà Cloud Run truy cập được, TLS, role migration/runtime; không thể dùng localhost trên laptop |
| Secret Manager | Secret có URL PostgreSQL; thêm giá trị bằng console/protected file, không qua Git hoặc Terraform state |
| Artifact Registry | Bootstrap repository/API, build target `runtime`, upload và lấy digest thật |
| Terraform | Init/validate đã chạy local; vẫn cần plan thật, kiểm tra IAM/region/cost và apply bản plan đã xem |
| Monitoring | Điền email backlog và thử thông báo; budget ở Billing là cấu hình riêng |
| Cloud smoke tests | Migration, GCS archive, Pub/Sub OIDC/private invocation, BigQuery load, dbt và reconciliation |
| Cloud Spark | Chọn runner/cluster được cấp quyền + GCS connector; hiện không được provision tự động |
| GitHub | Cấu hình environment `gcp` và WIF cho repository triển khai, chạy workflow thực tế |

Lộ trình triển khai chi tiết: [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md). Nếu chưa có PostgreSQL
cloud, có thể tiếp tục demo toàn bộ trên local; chưa thể coi Terraform là một triển khai end-to-end
tự chứa. Dự án hiện không tự provision database cloud để tránh tạo chi phí thường trực.
