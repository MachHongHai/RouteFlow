# Thiếu sót và kế hoạch hoàn thiện

Ngày 2026-10-19 đã bổ sung [console quản trị local](LOCAL_CONSOLE_VI.md): tám dịch vụ,
dữ liệu chỉ đọc, nhật ký và lưu trữ. Console chưa có đăng nhập/RBAC để truy cập từ xa;
chỉ dùng trên localhost. Chưa có BI dashboard nghiệp vụ và chưa kết nối GCP.

Đánh giá ngày 2026-10-16. Phân biệt code đã viết, kết quả local đã quan sát và cloud chưa xác minh.
Không dùng số bài test local để khẳng định GCP sẵn sàng production.

| Ưu tiên | Thiếu sót / trạng thái | Tác động | Bước tiếp theo |
|---|---|---|---|
| P0 cloud | Chủ dự án chưa có project GCP; chưa đăng nhập/ADC | Chưa kết nối GCP thật; chưa plan/apply | Làm theo `GCP_GETTING_STARTED_VI.md` |
| P0 cloud | Chưa có PostgreSQL cloud/TLS/secret thật | Cloud Run không thể dùng database localhost trên laptop | Chọn DB reachable, role và Secret Manager; smoke migration |
| P0 cloud | BQ/GCS/PubSub/Run mới kiểm tra code/schema; chưa chạy cloud | Chưa biết IAM, OIDC, quota, vùng và retry có hoạt động thực | Chạy ingestion/archive/dbt/reconcile và negative IAM tests |
| P1 cloud | Cloud load BigQuery theo từng message | Chi phí điều phối/load quota và độ trễ; không phù hợp GPS lưu lượng cao | Thiết kế micro-batch có checkpoint nếu muốn scale; demo cloud giữ nhỏ |
| P1 cloud | BigQuery RAW có thể có duplicate vật lý | Idempotency ở staging logic khác primary key/Postgres; không bảo đảm RAW unique | Kiểm tra retry/collision thực tế; thêm batch collision audit trước production |
| P1 cloud | Relay cloud chạy theo job/schedule | Local streaming có thể liên tục; cloud có độ trễ theo lịch | Đo độ trễ; chọn CDC/relay liên tục nếu SLA cần |
| P1 cloud | Spark cloud chưa có runner/GCS connector | Streaming cloud có thể chạy riêng; GPS cloud chưa có execution path vận hành hoàn chỉnh | Duy trì Spark local; chỉ cấu hình runner cloud khi có nhu cầu/chi phí được duyệt |
| P1 vận hành | Cảnh báo chưa được gửi thử; email mặc định trống | Có alert policy không có nghĩa operator nhận được cảnh báo | Điền `notification_email`, tạo sự cố thử và kiểm tra khôi phục |
| P1 vận hành | Đã diễn tập restore local sau sự cố Docker; chưa có HA hoặc backup ngoài máy | Backup/restore 18 bảng nguồn, 17 bảng warehouse đã khớp; chưa có RPO/RTO production | Bổ sung bản sao ngoài máy và diễn tập mất ổ đĩa/production khi cần |
| P1 release | Chưa có Git remote, CI/GitHub WIF chưa chạy thật | Chỉ kiểm chứng các lệnh local tương ứng | Tạo repository remote, push, cấu hình `gcp`, chạy CI/deploy |
| P2 dữ liệu | Spark quét lịch sử và rebuild suffix để bảo toàn chuỗi GPS | Chưa phải incremental tối ưu ở dữ liệu lớn; partition pruning đầu vào còn hạn chế | Cần checkpoint/index theo driver và phạm vi ảnh hưởng trước khi tối ưu |
| P2 lưu trữ | Parquet generation cũ chưa có GC local tự động | Chạy lại nhiều lần tăng dung lượng Docker trên E | Thiết kế retention bảo vệ run đang dùng/phục hồi, dry-run trước khi xóa |
| P2 đo lường | Workload hiện nhỏ; chưa có benchmark throughput, cloud cost, coverage % | Không có cơ sở công bố SLA, speedup hay chi phí production | Chạy benchmark có baseline, quy mô và giới hạn rõ ràng |
| P2 sản phẩm | Dữ liệu tổng hợp, không thanh toán/road matching/shift thật; chưa có BI dashboard | Phù hợp portfolio DE, chưa phải sản phẩm logistics vận hành | Thêm BI trên marts khi cần; không biến estimate GPS thành road distance |

## Đã hoàn thiện trong lượt rà soát này

- Thêm gcloud wrapper dùng image có sẵn, khóa digest, không pull tự động; cấu hình/ADC ở D,
  dữ liệu Docker và cache container ở E.
- Thêm preflight offline và GET-only online, kiểm tra placeholder/digest/project/ADC,
  đọc project/billing/API có phân trang; không báo deploy thành công từ kiểm tra tĩnh.
- Bổ sung dependency để Cloud Run Jobs được tạo sau grant Secret Manager cho runtime identity.
- Thêm email notification channel tùy chọn và nối với backlog alert policy.
- Chuyển kiểm tra biến deploy vào step sau khi environment `gcp` được chọn; trước đó điều kiện
  ở job có thể bỏ qua workflow khi biến chỉ được cấu hình ở environment.
- Giữ hướng dẫn tài khoản, thiếu sót và bằng chứng test trong repository để không mất ngữ cảnh.

Những thay đổi Terraform/GitHub ở trên chưa được apply/chạy trên GCP/GitHub. Preflight online
được kiểm tra bằng HTTP mock; chưa có credentials để xác nhận project thật. Các thay đổi này
chuẩn bị cho lần triển khai đầu, chưa phải bằng chứng đã loại bỏ mọi rủi ro cloud.

## Tiêu chí gọi là cloud end-to-end đã xác minh

Project/billing/auth pass; Terraform plan đã xem và apply thành công; service account thật
ghi GCS/BQ đúng quyền; Pub/Sub push có OIDC và bị từ chối nếu sai danh tính; tạo đơn → archive →
RAW → dbt → reconciliation pass; retry/replay không làm trùng fact; test DLQ và email alert;
ghi thời gian/chi phí quan sát. Nếu cần GPS cloud, Spark runner phải xử lý thật và nạp được
Parquet vào BQ trước dbt. Scheduler chỉ bật sau các bước này.
