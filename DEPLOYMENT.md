# Thông Tin Deploy — Checkpoint 5

## Thông Tin Học Viên

| Mục | Nội dung |
|-----|----------|
| Họ và tên | Nguyen Tuan Truong |
| Mã học viên | 2A202601842 |
| Repo | https://github.com/tuantruong1607/DAY12-2A202601842-NguyenTuanTruong |

## Service

| Mục | Nội dung |
|-----|----------|
| Public URL | https://day12-chat-2249.onrender.com |
| Platform | Render |
| Ngày deploy | 2026-08-10 |

## Biến Môi Trường Đã Set Trên Cloud

Chỉ ghi tên biến và nguồn giá trị, không ghi giá trị token.

| Biến | Đã set | Ghi chú |
|------|--------|---------|
| `PORT` | ✅ | Render tự gán |
| `API_TOKEN` | ✅ | Secret trong Render dashboard |
| `REDIS_URL` | ✅ | Render Redis service |
| `BUCKET_CAPACITY` | ✅ | Render environment variables |
| `REFILL_PER_MINUTE` | ✅ | Render environment variables |
| `DAILY_BUDGET_USD` | ✅ | Render environment variables |
| `LOG_LEVEL` | ✅ | Render environment variables |

## Kết Quả Chạy Thật

```text
GET /healthz  -> 200
{"status":"ok","service":"day12-chat-service","version":"1.0.0"}

GET /readyz   -> 200
{"status":"ready","redis":true}

POST /chat không có Authorization -> 401

POST /chat có Bearer token -> 200
Service trả về reply, client_id, turns_before, usd_cost và usage.

GET /  -> web console sau khi Render redeploy commit có thư mục frontend/
GET /docs -> Swagger UI của FastAPI
```

Frontend được phục vụ cùng origin với API. Sau khi push commit frontend lên GitHub,
chờ Render build lại rồi mở Public URL ở trên để sử dụng giao diện.

## Ảnh Chụp Màn Hình

Đã kiểm tra service trên Render và endpoint `/healthz`. Có thể đặt ảnh tại:

- `screenshots/dashboard.png` — dashboard Render.
- `screenshots/healthz.png` — kết quả gọi `/healthz`.

Không ghi giá trị `API_TOKEN` vào file này hoặc commit vào repository.
