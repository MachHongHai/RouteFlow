# Trạng thái và giới hạn

Cập nhật ngày 2026-10-22. Pipeline streaming, Spark, dbt và console đã được kiểm thử local;
CI kiểm tra ứng dụng, Spark và Terraform. [Validation](VALIDATION.md) ghi rõ bằng chứng từng môi trường.
Triển khai lên GCP thật chưa được xác minh.

Console hỗ trợ điều khiển dịch vụ, tạo dữ liệu, theo dõi batch, duyệt schema, SQL chỉ đọc và
nhật ký. Console chỉ dùng trên localhost, chưa có đăng nhập/RBAC từ xa. Compose mặc định
portable; [policy Windows D/E](DISK_STORAGE.md) nằm trong override tùy chọn.

| Ưu tiên | Giới hạn | Tác động | Bước tiếp theo |
|---|---|---|---|
| P0 cloud | Chưa xác minh project, billing, ADC và Terraform plan/apply thật | Chưa có bằng chứng triển khai GCP hoạt động | Làm theo [hướng dẫn GCP](GCP_GETTING_STARTED_VI.md) và preflight |
| P0 cloud | Chưa kiểm thử PostgreSQL cloud/TLS/secret | Cloud Run không thể dùng database localhost | Cấu hình DB reachable, role và Secret Manager; smoke migration |
| P0 cloud | BQ/GCS/Pub/Sub/Run chưa chạy cloud smoke | IAM, OIDC, quota, vùng và retry còn chưa xác minh | Chạy ingestion/archive/dbt/reconcile và negative IAM tests |
| P1 cloud | BigQuery load từng message; RAW có thể duplicate vật lý | Quota/chi phí tăng ở lưu lượng cao; staging dedup khác Postgres primary key | Micro-batch có checkpoint và collision audit trước khi scale |
| P1 cloud | Relay chạy theo job/schedule | Có độ trễ theo lịch | Đo độ trễ; chọn relay liên tục/CDC nếu SLA yêu cầu |
| P1 cloud | Chưa provision Spark runner/GCS connector | GPS cloud chưa có execution path hoàn chỉnh | Cung cấp runner được cấp quyền và kiểm thử Parquet → BQ |
| P1 vận hành | Alert delivery và GCP WIF chưa được kiểm thử thật | Cấu hình chưa chứng minh cảnh báo/deploy nhận đủ quyền | Kiểm tra notification channel và deploy environment `gcp` |
| P1 vận hành | Restore đã thử local; chưa có HA, backup ngoài máy và RPO/RTO production | Chưa bảo vệ được tình huống mất máy/ổ đĩa | Bản sao ngoài máy và diễn tập phục hồi định kỳ |
| P2 dữ liệu | Spark quét lịch sử và rebuild suffix để bảo toàn chuỗi GPS | Chi phí tăng khi dữ liệu lớn | Checkpoint/index theo driver và phạm vi ảnh hưởng |
| P2 lưu trữ | Parquet generation cũ chưa có GC local tự động | Chạy lặp tăng dung lượng Docker | Retention bảo vệ run đang dùng/phục hồi, dry-run trước khi xóa |
| P2 đo lường | Workload nhỏ; chưa đo throughput, cloud cost, coverage % | Chưa có cơ sở công bố SLA, speedup hoặc chi phí production | Benchmark có baseline, quy mô và giới hạn rõ ràng |
| P2 sản phẩm | Dữ liệu tổng hợp; không có thanh toán thật, road matching, shift hoặc BI dashboard | Chỉ mô phỏng nghiệp vụ logistics | Bổ sung tích hợp thực khi cần; giữ GPS estimate tách khỏi road distance |

## Điều kiện xác minh cloud end-to-end

Project/billing/auth hợp lệ; Terraform plan đã xem và apply thành công; service account ghi
GCS/BQ đúng quyền; Pub/Sub push dùng OIDC và từ chối danh tính sai; đơn mới đi qua archive,
RAW, dbt và reconciliation; retry/replay không làm trùng fact; DLQ và email alert được thử.
Ghi lại thời gian/chi phí quan sát. Nếu dùng GPS cloud, Spark phải xử lý thật và nạp Parquet
vào BQ trước dbt. Chỉ bật Scheduler sau khi các kiểm tra này hoàn tất.
