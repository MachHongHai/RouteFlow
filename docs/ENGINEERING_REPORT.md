# Báo cáo kỹ thuật RouteFlow

## A. Tổng quan

Đã xây dựng repository có thể chạy thực tế cho nền tảng dữ liệu giao hàng: API nghiệp vụ,
PostgreSQL, transactional outbox, Pub/Sub Emulator, consumer, archive, warehouse, dbt và nhánh
PySpark xử lý GPS. Đây là mô phỏng có dữ liệu sinh tổng hợp; không tích hợp thanh toán thật.

## B. Kiến trúc

API/generator ghi nghiệp vụ và outbox trong cùng transaction. Relay claim bằng lease/SKIP LOCKED,
publish có xác nhận. Consumer lưu nguyên bản, kiểm tra contract/identity rồi ghi RAW trước ack.
dbt khôi phục vòng đời theo phiên bản và xây marts/SCD2. Spark đọc GPS từ archive, sắp xếp lịch sử,
tính Haversine, phát hiện bất thường, ghi Parquet và thay thế tổng hợp trong warehouse để dbt sử dụng.

## C. Tính năng và trạng thái

Đã triển khai và kiểm thử local: vòng đời đơn hàng/thanh toán/hủy/refund, GPS, seed/generator,
outbox/concurrency/retry, Pub/Sub, loại trùng, late/out-of-order, DLQ/replay, archive/backfill,
reconciliation, metadata/logs, dbt incremental/SCD2 và Spark Master/Worker với Parquet/warehouse.

Đã chuẩn bị nhưng chưa kiểm thử cloud: adapter BigQuery/GCS, private Cloud Run push, Terraform,
IAM, Workflows/Scheduler, WIF, monitoring/budget và workflow deploy. Spark cloud cần cluster/runner
và GCS connector do người vận hành cung cấp. Không tự tạo Dataproc hoặc dịch vụ tính phí.

## D. Xác thực

Ruff và mypy pass. Bộ ứng dụng/contract/integration/E2E pass 25 bài; Spark pass 10 bài. dbt build
pass 55 bước, gồm 22 mô hình và 33 kiểm tra; dbt test riêng pass 33. Terraform init/fmt/validate
pass qua Docker. Compose và pipeline đầy đủ có Spark đã chạy thành công. Xem `VALIDATION.md`
cho lệnh, dữ liệu đầu ra và giới hạn bằng chứng; không suy diễn kết quả cloud từ kiểm thử local.

Ảnh chụp dữ liệu đã đối soát: 34 đơn nguồn = 34 fact orders = 34 payments; 562 logical RAW events;
264 điểm GPS và chín dòng tổng hợp driver/date. Cả sáu nhóm reconciliation pass. Không công bố
coverage hoặc benchmark hiệu năng chưa đo.

Lượt chuẩn bị GCP sau đó chạy 29 unit/contract tests, gồm 12 trường hợp preflight mới; Ruff,
mypy và Terraform validate pass. Test online dùng HTTP mock; không có đăng nhập hay request GCP
thật. Không chạy lại Spark/integration E2E trong lượt chỉ sửa công cụ/infra này. Chi tiết ghi
riêng ở cuối `VALIDATION.md` để tách kết quả mới khỏi snapshot pipeline ban đầu.

## E. Cloud

Chưa sử dụng GCP, chưa enable API, chưa apply Terraform và chưa tạo tài nguyên billable. Cloud
deployment là opt-in. Đã tra tài liệu giá chính thức và ghi nguồn/ngày kiểm tra trong `CLOUD_COSTS.md`.
Budget chỉ cảnh báo; image lớn có thể vượt dung lượng miễn phí của Artifact Registry.

## F. Tệp quan trọng

| Tệp/thư mục | Vai trò |
|---|---|
| `routeflow/domain.py`, `api.py`, `models.py` | Nghiệp vụ, API và bất biến dữ liệu |
| `routeflow/relay.py`, `messaging.py`, `consumer.py` | Outbox, broker và ingestion/recovery |
| `routeflow/storage.py`, `operations.py`, `cli.py` | Archive/warehouse, replay/backfill/đối soát |
| `routeflow/spark/` | Đọc GPS, kiểm tra, window/Haversine, tổng hợp, Parquet và loading |
| `dbt/` | Staging, intermediate, dimensions/facts, incremental và kiểm tra |
| `migrations/` | Alembic revisions đóng băng |
| `docker-compose.yml`, `Dockerfile` | Môi trường local và Spark profile |
| `infra/terraform/`, `.github/workflows/` | Cloud opt-in, CI và deploy thủ công |
| `tests/`, `docs/adr/` | Kiểm thử và quyết định kiến trúc |
| `routeflow/cloud_preflight.py`, `scripts/gcloud.ps1` | Kiểm tra trước deploy và CLI dùng cấu hình ở D |

## G. Giới hạn còn lại

Sau cập nhật Docker 4.95 đã phục hồi inventory và dữ liệu cũ, sửa khóa WSL storage và diễn tập
restore logic trên môi trường tách biệt. 18 bảng nguồn và 17 bảng warehouse khớp fingerprint;
archive/lake giải nén thành công. Xem [DOCKER_RECOVERY_VI.md](DOCKER_RECOVERY_VI.md).
Đây là backup local; HA, bản sao ngoài máy và RPO/RTO production vẫn chưa có.

Danh sách thiếu sót có ưu tiên, tác động và bước tiếp theo được duy trì tại
[PROJECT_GAPS_VI.md](PROJECT_GAPS_VI.md). Chủ dự án chưa có project GCP; đã thêm hướng dẫn
[GCP_GETTING_STARTED_VI.md](GCP_GETTING_STARTED_VI.md), gcloud wrapper dùng image có sẵn và
preflight chỉ đọc. Chưa chạy preflight online với tài khoản thật. Việc kết nối GCP vẫn bị chặn
ở project/billing/auth và PostgreSQL cloud; không thể giải quyết chỉ bằng code local.

Cloud IAM/API/GCS connector cần kiểm thử với tài khoản được cấp quyền. BigQuery load từng message
chỉ phù hợp demo nhỏ; workload GPS lớn phải chạy local hoặc bổ sung batch cloud trước khi scale.
Relay cloud chạy theo lịch nên có độ trễ. Spark backfill ưu tiên đúng dữ liệu, quét lịch sử và có
thể rebuild cả suffix sau ngày kết thúc. Parquet run cũ chưa có garbage collector local tự động.
Retention giới hạn khả năng replay. Không có road matching hoặc lịch ca làm việc thực tế.

Một warning từ thư viện Starlette còn tồn tại. DLQ main có một poison message cố ý tạo để kiểm tra;
metadata giữ lịch sử một lần chạy thất bại đã được sửa. Những dấu vết này không bị xóa để làm đẹp số liệu.

## H. Cách chạy

```bash
uv sync --frozen
docker compose up -d --build
docker compose --profile spark up -d --build spark-master spark-worker
uv run python scripts/local_pipeline.py --orders 20 --spark
```

API docs: http://127.0.0.1:58000/docs; Spark UI: http://127.0.0.1:58080.
Lệnh kiểm thử, replay/backfill và dừng dịch vụ có trong README và các runbook tương ứng.

## I. Git

Repository được khởi tạo local trên nhánh `main`. Không có remote nên không push. Các commit triển khai `41d66f2` và hạ tầng/CI `fa1446f` đã được tạo sau kiểm tra.
Commit tài liệu/chuẩn hóa LF được tạo sau cùng; dùng `git log --oneline` để xem hash chính xác.
Không force-push hay thay thế công việc có sẵn; thư mục ban đầu trống.

## J. Đánh giá portfolio

Dự án thể hiện thực tế event-driven ingestion, outbox, at-least-once, idempotency, hợp đồng dữ liệu,
replay/backfill, SCD2, data quality/reconciliation, Spark phân tán và Infrastructure as Code.
README có CV bullets dựa trên chức năng đã kiểm chứng local. Không nên ghi đã deploy GCP hoặc
đạt thông lượng/tiết kiệm chi phí cụ thể khi chưa có phép đo tương ứng.
