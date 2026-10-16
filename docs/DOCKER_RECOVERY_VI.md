# Phục hồi sau cập nhật Docker Desktop

## Sự cố và nguyên nhân đã quan sát

Ngày 2026-10-16, Docker Desktop cập nhật từ 4.91 sang 4.95 (Engine 29.8.2). Engine mới hiển thị
0 container/image/volume vì dùng kho WSL mới mặc định trên C. Ổ cũ 36.170.629.120 byte trên E
vẫn còn nguyên. Cấu hình trước đó chỉ đặt `DataFolder` và junction ở Desktop root; chưa đặt
đúng khóa chọn ổ WSL là **`CustomWslDistroDir`**. Vì vậy cấu hình chuyển ổ trước đó chưa đủ bền
qua cập nhật. Không dùng việc thấy danh sách trống để kết luận dữ liệu đã bị xóa.

Docker maintainer mô tả khóa này và việc giữ bản sao VHD trước khi đổi đường dẫn tại
[issue #14129](https://github.com/docker/for-win/issues/14129). Trên máy này, kết quả được xác minh
trực tiếp bằng log backend, WSL registration, inventory và dữ liệu database sau phục hồi.

Đã sửa `CustomWslDistroDir=E:\DockerDesktop\data\wsl`, giữ `DataFolder` riêng, phục hồi runtime
WSL dùng E, và thay Desktop root junction bằng thư mục Windows thông thường cho log/socket nhỏ.
Junction cũ và các socket cũ chỉ được đổi tên để giữ lại. Các ổ trống mới tạo trên C được chuyển
sang thư mục recovery trên E; không ghi đè ổ dữ liệu cũ. Các dự án ecommerce vẫn giữ trạng thái
dừng như trước; không chạy migration hoặc generator vào dữ liệu của những dự án đó.

## Các bản sao hiện có

| Bản sao | Vị trí / bằng chứng |
|---|---|
| Ổ Docker mới nhất trước khi sửa | `E:\DockerDesktop\recovery-20261016-update\pre-recovery-docker_data.vhdx` |
| SHA256/byte proof của snapshot | `E:\DockerDesktop\recovery-20261016-update\snapshot-proof.json` |
| Cấu hình/WSL trước khi sửa | Cùng thư mục recovery trên E |
| Các bản sao từ lần chuyển ổ đầu | `E:\DockerDesktop\migration-backups-20261016` |
| Backup logic RouteFlow độc lập với Docker VHD | `D:\RouteFlow-backups\recovered-after-docker-update-20261016` |

Snapshot VHD mới nhất được copy khi Desktop/WSL đã dừng và SHA256 toàn bộ khớp với ổ nguồn
trước khi đổi cấu hình. Các bản cũ không được xóa hoặc ghi đè trong quá trình phục hồi.
Backup cùng máy không bảo vệ khỏi việc cả máy hoặc cả ổ D/E bị hỏng.

## Kiểm tra trước khi cập nhật hoặc khi danh sách bỗng trống

1. Kiểm tra `docker context ls` và dùng đúng `desktop-linux`.
2. Dừng Desktop hoàn toàn trước khi đụng vào file VHD. Không factory reset, prune hoặc tạo lại
   volume khi chưa xác định được ổ dữ liệu đang dùng.
3. Giữ bản sao `settings-store.json`, WSL registration và VHD. Kiểm tra ổ gốc E còn tồn tại.
4. Trong `%APPDATA%\Docker\settings-store.json`, giữ các thiết lập khác và xác nhận:

```json
"CustomWslDistroDir": "E:\\DockerDesktop\\data\\wsl"
```

5. Dùng helper để khởi động; helper giữ socket cũ và kiểm tra registration sau khởi động:

```powershell
Set-Location D:\Du-an\RouteFlow
.\scripts\start-docker.ps1
.\scripts\dev.ps1 docker ps -a
.\scripts\dev.ps1 docker volume ls
.\scripts\dev.ps1 docker compose --profile spark up -d --no-build
```

Nếu ổ E không còn nguyên, không tiếp tục các lệnh tạo volume. Giữ lại VHD hiện tại dưới tên khác,
phục hồi từ snapshot đã kiểm tra khi Desktop/WSL dừng, rồi kiểm tra lại inventory và database.
Không unregister một distribution chứa dữ liệu nghiệp vụ nếu chưa có bản sao và chưa phân biệt
runtime `ext4.vhdx` với bulk data `docker_data.vhdx`.

## Backup logic và diễn tập restore

Tạo một thư mục đích mới trên D mỗi lần backup:

```powershell
.\scripts\dev.ps1 uv run python scripts/backup_local.py backup --destination D:\RouteFlow-backups\YOUR_NEW_SNAPSHOT
.\scripts\dev.ps1 uv run python scripts/backup_local.py verify --destination D:\RouteFlow-backups\YOUR_NEW_SNAPSHOT
```

Backup yêu cầu core stack chạy và không có Spark job đang thực thi. Nó tạm dừng API, chờ ingestion
barrier, dừng relay/consumer, tạo hai `pg_dump -Fc`, backup archive/lake, rồi khởi động lại đúng
các dịch vụ đã dừng trong `finally`. Hash nội dung tất cả base table trước/sau phải khớp để
backup được chấp nhận. Không chạy generator/dbt/Spark hay ghi database từ bên ngoài trong lúc này.

`manifest.json` ghi SHA256 và nội dung bảng ở thời điểm backup; không có nghĩa đã restore thử.
`verify` kiểm tra SHA256, tạo PostgreSQL 16 tạm với `--network none`, không host port và PGDATA
trên tmpfs, `pg_restore --exit-on-error`, rồi so sánh số dòng và fingerprint nội dung mọi base table.
Nó giải nén hai tar vào thư mục mới trên D bằng bộ lọc an toàn. Container kiểm tra được tự xóa
khi dừng; volume database đang chạy không bị thay thế. Chỉ khi mọi bước pass mới ghi
`restore-verification.json` với `restore_verified=true`.

Kết quả thực thi trên backup đã phục hồi:

- 18 bảng nguồn và 17 bảng warehouse restore thành công, tất cả row fingerprints khớp.
- Archive giải nén 563 file; data lake giải nén 89 file.
- 34 đơn nguồn = 34 fact orders; 562 RAW events; 9 dòng GPS daily, 264 điểm,
  60.639007624322296 km ước tính; khớp mốc trước cập nhật.
- 17 container cũ, 9 volume và toàn bộ image/tag khớp inventory; các container ecommerce còn dừng.

Diễn tập này xác minh backup RouteFlow; chưa chạy smoke nghiệp vụ hoặc restore logic cho các
database ecommerce. Chúng được giữ trong VHD đầy đủ và volume cũ đã xuất hiện trở lại.
