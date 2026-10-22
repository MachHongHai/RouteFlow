# Giao diện quản lý local

Trong Docker Desktop, bấm **Start** cho nhóm **routeflow**, mở rộng nhóm rồi bấm cổng
**58090:8080** của **console**. Hoặc mở [RouteFlow Console](http://127.0.0.1:58090).
UI đã là container cùng nhóm; không cần chạy PowerShell riêng mỗi lần.

Chỉ mở Docker Desktop sẽ không tự bật RouteFlow (`restart: no`). Bấm Start nhóm để chạy
cả UI và workload. Có thể chỉ Start riêng console, rồi dùng **Bật toàn bộ** trong UI.
**Dừng toàn bộ** trong UI giữ console hoạt động; Stop nhóm trong Docker dừng cả console.
Tám dịch vụ dữ liệu và console là chín container chạy lâu dài; init chỉ chạy thiết lập rồi thoát 0.

Thiết lập lần đầu hoặc cập nhật code trên máy Windows này:

```powershell
cd D:\Du-an\RouteFlow
.\scripts\start-console.ps1 -Build
.\scripts\dev.ps1 docker compose --profile spark up -d --no-build --pull never
```

Script kiểm tra Docker/WSL trên E, cập nhật metadata lưu trữ ở D, build image khi cần và
khởi động console. Khi đã tạo các container, những lần sau chỉ cần nút Start của Docker.
Nếu chỉ muốn mở lại console qua terminal: `.\scripts\start-console.ps1`.

- **Dịch vụ:** trạng thái tám dịch vụ, tìm kiếm, lọc, bật/dừng/khởi động lại, API docs và
  Spark UI. Các nút dùng container đã có, không pull,
  build, tạo hay xóa container/volume. Nếu đã xóa container, dùng Compose để tạo lại.
- **Dữ liệu:** bảy bảng cho phép, truy vấn chỉ đọc, 20 dòng mỗi trang; không có SQL tùy ý.
- **Tạo dữ liệu:** chọn 1–500 đơn, ngày nghiệp vụ UTC và seed; tùy chọn chạy dbt khi
  toàn bộ sự kiện đã vào RAW. Mỗi lần tạo thêm đơn mới, giữ dữ liệu hiện có.
- **Nhật ký:** 150 dòng gần nhất, lọc và sao chép. Kiểm tra nội dung trước khi chia sẻ.


Ứng dụng chờ database, migration và subscription sẵn sàng khi Docker Desktop bật các
container cùng lúc. Broker trong console khởi động dependency và chạy init khi broker
Pub/Sub cần provision lại. Không tự sinh đơn hàng, chạy dbt hay Spark batch khi Start.

UI chạy UID 10001, không có quyền mở Docker socket. Một broker riêng trong cùng container
lắng nghe loopback nội bộ, giữ quyền socket và chỉ cho start/stop/restart tám container
RouteFlow đã kiểm tra nhãn project/service; init chỉ được gọi trong trình tự khởi động.
Broker không chuyển tiếp Engine API tùy ý, không create/delete/prune và không có cổng
publish. Chỉ có một lệnh exec cố định: `python -m routeflow.cli dbt`, chạy UID 10001
trong API của RouteFlow; giao diện không truyền được lệnh, tham số hay môi trường tùy ý.
Không có Docker TCP API không xác thực.

Cổng web chỉ publish 127.0.0.1:58090. Host/CSRF/token được kiểm tra; không mở cổng ra LAN
hoặc Internet. Đây là công cụ quản trị local, chưa có đăng nhập/RBAC nhiều người. Container
UI có filesystem chỉ đọc và tmpfs giới hạn trên E. Cache/temp host của wrapper ở D.
Nút thay đổi trạng thái kiểm tra cấu hình Docker đang ghim E từ mount settings chỉ đọc.
GCP chưa kết nối; console không triển khai hay quản lý cloud.

Trang Tạo dữ liệu cập nhật mỗi 2 giây khi hiển thị. Chọn một đợt để theo dõi số liệu
thực theo `correlation_id`: **Generate → Source/Outbox → Pub/Sub → Consumer/RAW →
dbt/Mart**. Bấm từng bước để xem giải thích; bảng bên dưới hiện 20 sự kiện mới nhất
của đợt, trạng thái publish và nhận RAW. Generator gọi nghiệp vụ trực tiếp, không tạo
HTTP traffic qua Delivery API. `published_at` là xác nhận publish, không phải độ dài queue.

Nhánh GPS hiển thị số điểm RAW của đợt, lần chạy Spark gần nhất và tổng điểm đã tổng hợp
trong hệ thống. **Spark vẫn chạy bằng job riêng**, không tự chạy khi generate hoặc Start;
trạng thái Spark gần nhất không chứng minh GPS vừa tạo đã được xử lý.

Lịch sử tạo dữ liệu nằm trong volume `routeflow_console-state` trên đĩa Docker E.
Console hiện 25 đợt gần nhất, giữ metadata cũ để chống gửi lại yêu cầu trùng. Cùng mã yêu
cầu trả lại đợt cũ; bấm tạo đợt mới sẽ thêm đơn mới kể cả khi dùng cùng seed. Khi console
khởi động lại, đợt đang chạy được đánh dấu gián đoạn, không tự sinh lại; dữ liệu đã commit
vẫn được giữ nguyên và dbt có thể vẫn đang chạy trong API.

Các trang khác tự cập nhật mỗi 15 giây khi tab hiển thị. Database chưa kết nối hiện dấu —.
Một thao tác chạy tại một thời điểm; các nút dịch vụ bị khóa khi đợt dữ liệu đang chạy.
Lịch sử thao tác bật/dừng dịch vụ trong RAM mất khi console khởi động lại. Nếu thao tác
hết thời gian, làm mới trạng thái trước khi thử lại.
