# Phục hồi Docker Desktop và kiểm tra backup

Danh sách container trống sau cập nhật có thể do context hoặc kho WSL được chọn thay đổi.
Cần xác định ổ dữ liệu đang dùng trước khi tạo lại stack. Hướng dẫn D/E bên dưới áp dụng cho
[cấu hình Windows tùy chọn](DISK_STORAGE.md); Compose mặc định không yêu cầu các ổ này.

## Xác định kho dữ liệu

1. Kiểm tra `docker context ls` và context Linux cần dùng, thường là `desktop-linux`.
2. Kiểm tra **Disk image location** trong Docker Desktop và vị trí VHD cũ. Danh sách trống
   không đủ để kết luận dữ liệu đã bị xóa.
3. Thoát hoàn toàn Docker Desktop và dừng WSL trước khi sao chép hay thay thế VHD.
   Việc dừng WSL ảnh hưởng các distribution đang chạy.
4. Sao lưu `settings-store.json`, thông tin đăng ký WSL và các VHD vào thư mục mới.
   So sánh kích thước và SHA256 của bản sao trước khi thay đổi cấu hình.
5. Với helper D/E, kiểm tra `CustomWslDistroDir` trong
   `$env:APPDATA\Docker\settings-store.json` trỏ tới `E:\DockerDesktop\data\wsl`.
   Giữ các thiết lập khác. `DataFolder` không thay thế kiểm tra vị trí WSL này.

Docker có thảo luận về thiết lập WSL và việc giữ bản sao trước khi đổi đường dẫn tại
[issue #14129](https://github.com/docker/for-win/issues/14129).
Không factory reset, prune hay ghi đè VHD để xử lý một kho chưa xác định.
Phân biệt runtime `main\ext4.vhdx` với bulk data `disk\docker_data.vhdx`;
không unregister distribution khi chưa có bản sao và chưa biết nó chứa dữ liệu gì.

## Khởi động và đối chiếu

Khi đã xác nhận đúng kho trên E, chạy từ thư mục repository:

```powershell
.\scripts\start-docker.ps1
.\scripts\dev.ps1 docker ps -a
.\scripts\dev.ps1 docker volume ls
```

Đối chiếu inventory với bản ghi trước đó. Khi container/volume đúng đã xuất hiện, có thể
khởi động stack hiện có, không rebuild hay pull:

```powershell
.\scripts\dev.ps1 docker compose --profile console --profile spark up -d --no-build --pull never
```

Kiểm tra API readiness, số bản ghi nguồn/RAW/mart và reconciliation. Không chạy generator
để thay thế bằng chứng dữ liệu cũ. Nếu ổ cũ hỏng hoặc mất, giữ nguyên bản hiện tại và phục hồi
từ snapshot đã xác minh khi Desktop/WSL đã dừng.

## Backup logic và diễn tập restore

Tạo một thư mục đích mới trên D cho mỗi snapshot:

```powershell
$snapshotPath = 'D:\RouteFlow-backups\YOUR_NEW_SNAPSHOT'
.\scripts\dev.ps1 uv run python scripts/backup_local.py backup --destination $snapshotPath
.\scripts\dev.ps1 uv run python scripts/backup_local.py verify --destination $snapshotPath
```

Backup yêu cầu core stack đang chạy và không có Spark job. Công cụ tạm dừng API, chờ ingestion
barrier, dừng relay/consumer, tạo hai `pg_dump -Fc` cùng archive/lake tar, rồi khởi động lại
các dịch vụ đã dừng trong `finally`. Fingerprint nội dung các base table trước/sau phải khớp.
Không chạy generator, dbt, Spark hoặc ghi database từ bên ngoài trong thời gian backup.

`manifest.json` ghi SHA256 và nội dung bảng tại thời điểm backup; nó chưa chứng minh restore
thành công. Lệnh `verify` kiểm tra SHA256, tạo PostgreSQL 16 tạm với `--network none`, không
publish port, PGDATA trên tmpfs và dùng `pg_restore --exit-on-error`. Sau đó công cụ so sánh
số dòng/fingerprint của mọi base table và giải nén archive/lake vào thư mục mới bằng bộ lọc an toàn.
Container kiểm tra được xóa khi dừng; database đang chạy không bị thay thế.
Chỉ khi các bước đều pass mới ghi `restore-verification.json` với `restore_verified=true`.

Đây là diễn tập xác minh backup, không phải lệnh ghi đè database đang chạy.
Kết quả đã ghi nhận nằm trong [validation](VALIDATION.md). Backup cùng máy không bảo vệ khỏi
mất máy hoặc hỏng toàn bộ ổ đĩa; cần thêm bản sao ngoài máy và chính sách RPO/RTO cho production.
