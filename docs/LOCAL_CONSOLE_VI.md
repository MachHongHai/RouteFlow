# Giao diện quản lý local

Chạy từ PowerShell:

```powershell
cd D:\Du-an\RouteFlow
.\scripts\start-console.ps1
```

Mở [RouteFlow Console](http://127.0.0.1:58090). Console chạy trên máy host,
độc lập với container Delivery API. Ctrl+C chỉ dừng console; container giữ nguyên trạng thái.
Không cần npm hoặc tài khoản GCP. Nếu môi trường Python chưa có, chạy
`.\scripts\dev.ps1 uv sync --frozen` trước.

- **Dịch vụ:** trạng thái tám dịch vụ, tìm kiếm, lọc, bật/dừng/khởi động lại,
  mở API docs và Spark UI. Container ngoài RouteFlow chỉ xem trong mục thu gọn.
- **Dữ liệu:** bảy bảng cho phép, chỉ đọc, 20 dòng mỗi trang; không có SQL tùy ý.
- **Nhật ký:** 150 dòng gần nhất, lọc nội dung và sao chép. Một số dạng mật khẩu/token
  được che; vẫn kiểm tra nội dung trước khi chia sẻ log ra ngoài máy.
- **Lưu trữ:** dung lượng ổ C/D/E, đường dẫn VHD Docker và bản ghi kiểm tra phục hồi.
  Kết quả restore là bằng chứng lịch sử, không xác nhận lại file backup hiện tại.
  Có lệnh tạo/verify backup để chạy chủ động trong PowerShell.

Nút bật dùng image đã có (`--no-build --pull never`). Nếu thiếu image, làm theo
[hướng dẫn local](LOCAL_DEVELOPMENT.md) để build qua `scripts/dev.ps1`.
Các nút dừng dùng `compose stop`, không xóa volume. Console không cung cấp prune,
xóa container/image/volume, sửa dữ liệu hoặc tự dọn backup. Một thao tác được xử lý
tại một thời điểm; kết quả nằm trong bộ nhớ và mất khi console khởi động lại.

Console tự làm mới trạng thái mỗi 15 giây khi tab đang hiển thị. Database chưa kết nối
sẽ hiện dấu `—`, không giả định số lượng bằng không. Khi thao tác hết thời gian chờ,
làm mới để kiểm tra trạng thái thực tế trước khi thử lại.

Chỉ bind `127.0.0.1`; kiểm tra địa chỉ client/Host và token phiên cho thao tác thay đổi.
Không publish console lên Internet, đổi host thành `0.0.0.0` hoặc gắn Docker socket
vào container web. Đây là công cụ quản trị máy local, chưa có đăng nhập/RBAC cho nhiều người.
Các lệnh Docker đi qua wrapper kiểm tra vị trí dữ liệu trên E; cache và temp ở D.
GCP hiện chưa kết nối; console không triển khai hay quản lý tài nguyên cloud.
