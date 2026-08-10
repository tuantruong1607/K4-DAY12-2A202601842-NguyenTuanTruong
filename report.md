# Báo cáo bài lab K3 Day 12 — Cloud Services and Deployment

## 1. Thông tin bài làm

- Học viên: Nguyen Tuan Truong
- Mã học viên: 2A202601842
- Repository: https://github.com/tuantruong1607/DAY12-2A202601842-NguyenTuanTruong
- Public service: https://day12-chat-2249.onrender.com
- Platform: Render
- Ngày kiểm tra: 2026-08-10

Service là một API FastAPI có giao diện web tại `/`. Giao diện gọi các endpoint `/healthz`, `/readyz` và `/chat` cùng origin, nên không cần thêm một frontend server riêng.

## 2. Kiến trúc sau khi hoàn thiện

```text
Client
  |
  +--> /            : web console HTML/CSS/JS
  +--> /healthz  : kiểm tra process còn sống
  +--> /readyz   : kiểm tra Redis đã sẵn sàng
  +--> /chat     : Bearer auth -> token bucket -> cost guard
                                  -> Redis history -> mock LLM
                                  -> lưu history -> ghi chi phí -> trả response
```

Redis được dùng để lưu state dùng chung giữa nhiều instance. Vì vậy nếu request thứ nhất đi vào container A và request thứ hai đi vào container B, cả hai vẫn nhìn thấy cùng lịch sử hội thoại.

## 3. CP1 — Config, logging và liveness

### Cấu hình 12-Factor

`app/config.py` đọc cấu hình từ environment thay vì hardcode trong source:

- `API_TOKEN`: token bắt buộc, không có giá trị mặc định.
- `PORT`: cổng HTTP, mặc định 8000.
- `REDIS_URL`: địa chỉ Redis.
- `BUCKET_CAPACITY`: sức chứa token bucket.
- `REFILL_PER_MINUTE`: tốc độ nạp token.
- `DAILY_BUDGET_USD`: ngân sách mỗi client mỗi ngày.
- `LOG_LEVEL`: mức log.

Việc không đặt mặc định cho `API_TOKEN` giúp service fail fast khi deploy thiếu secret, thay vì chạy công khai với một token mặc định nguy hiểm.

### Structured logging

`app/logging_utils.py` triển khai `emit()`:

- Tạo JSON object gồm `event`, `severity` và `ts`.
- Gộp các field như `client_id`, số token và chi phí.
- In đúng một dòng JSON ra stdout.
- Không ghi API token vào log.

### `/healthz`

`/healthz` không gọi Redis. Khi process bình thường, endpoint trả HTTP 200. Khi service đang draining do nhận SIGTERM, endpoint trả HTTP 503 để load balancer ngừng gửi request mới.

### Frontend console

Frontend nằm trong thư mục `frontend/` và được FastAPI phục vụ như sau:

- `frontend/index.html`: bố cục console chat, cấu hình client, token và endpoint.
- `frontend/styles.css`: giao diện dark-tech responsive, một màu nhấn xanh, có trạng thái loading, lỗi và reduced motion.
- `frontend/app.js`: gọi `/healthz`, `/readyz`, `POST /chat`, hiển thị usage/cost và xử lý lỗi 401, 402, 422, 429, 503.
- Token không được ghi vào `localStorage`; chỉ `client_id` và API base URL được nhớ trên trình duyệt.
- `app/main.py` mount static assets tại `/assets` và trả `index.html` tại `/`.

Khi chạy Docker, `Dockerfile` copy cả thư mục `frontend/` vào image. Vì frontend và API cùng origin, việc deploy không phát sinh CORS cho luồng mặc định.

## 4. CP2 — Docker

Dockerfile sử dụng multi-stage build:

1. Stage `builder` cài dependencies vào `/install`.
2. Stage `runtime` chỉ copy dependencies và source cần thiết.
3. Container chạy bằng user thường `appuser`, không chạy root.
4. Port đọc từ biến `PORT`.
5. Image có `HEALTHCHECK`.

### Compose và Docker healthcheck

Các file Docker đã được đồng bộ với contract của app:

- `Dockerfile` healthcheck `/healthz` và copy frontend vào runtime image.
- `docker-compose.yml` dùng service `chat`.
- Compose truyền `API_TOKEN` qua `${API_TOKEN}`, không hardcode secret.
- Compose dùng `REDIS_URL=redis://redis:6379/0` và chờ Redis healthy.
- Healthcheck của service Compose gọi `/healthz`.

Render vẫn dùng `render.yaml` với `API_TOKEN` và health check `/healthz`.

## 5. CP3 — API security

### Bearer authentication

`app/auth.py` kiểm tra header:

```text
Authorization: Bearer <API_TOKEN>
```

- Thiếu header, sai scheme hoặc sai token đều trả HTTP 401.
- Scheme `Bearer` không phân biệt hoa thường.
- So sánh token bằng `secrets.compare_digest()` để giảm rủi ro timing attack.
- Header `WWW-Authenticate: Bearer` được trả kèm response 401.
- `X-Client-Id` dùng để phân biệt quota; thiếu thì dùng `anonymous`.

### Token bucket

`app/rate_limiter.py` lưu mỗi bucket trong Redis HASH gồm `tokens` và `ts`.

- Client mới bắt đầu với đầy bucket.
- Token được nạp dần theo thời gian.
- Không bao giờ vượt quá `capacity`.
- Mỗi request thành công tiêu thụ một token.
- Bucket hết token trả HTTP 429 và `Retry-After`.
- Key có TTL để Redis không giữ bucket cũ vô hạn.

### Cost guard

`app/cost_guard.py` lưu chi phí theo key:

```text
spend:<client_id>:<YYYY-MM-DD>
```

- Chưa có key thì chi phí là `0.0`.
- `check()` chặn trước khi gọi LLM nếu vượt ngân sách.
- `record()` cộng dồn bằng `incrbyfloat()`.
- Key có TTL vài ngày để phục vụ đối soát.
- Vượt ngân sách trả HTTP 402.

### Luồng `/chat`

Request được xử lý theo thứ tự:

```text
verify_bearer_token
-> bucket.consume
-> guard.check
-> store.history
-> generate_reply
-> store.add_turn x 2
-> guard.record
-> emit
-> response
```

Việc kiểm tra quota trước khi gọi LLM giúp tránh phát sinh chi phí cho request bị từ chối.

## 6. CP4 — Stateless và graceful shutdown

### Chat history trong Redis

`app/store.py` dùng Redis List với key:

```text
chat:<client_id>
```

Mỗi message được JSON hóa rồi `rpush()` vào Redis. Sau đó:

- `ltrim()` giữ tối đa 12 message gần nhất.
- `expire()` đặt thời hạn 3 ngày.
- `history()` đọc bằng `lrange()` và giải mã JSON.
- `ping()` bắt exception và trả `False` khi Redis không phản hồi.

### Readiness

`/readyz` kiểm tra Redis:

- Redis sống: HTTP 200, `{"status":"ready","redis":true}`.
- Redis lỗi: HTTP 503.
- Service đang draining: HTTP 503.

Khác với `/healthz`, `/readyz` được phép kiểm tra dependency vì nó quyết định instance có nhận traffic hay chưa.

### Graceful shutdown

`app/lifecycle.py` đăng ký handler cho `SIGTERM` và `SIGINT`.

Khi nhận signal:

1. Đặt `draining = True`.
2. `/healthz` và `/readyz` chuyển sang 503.
3. Gọi lại handler cũ của Uvicorn để server tiếp tục dừng đúng cách.

## 7. CP5 — Cloud deployment

Service đã deploy trên Render tại:

```text
https://day12-chat-2249.onrender.com
```

Các biến đã cấu hình trên cloud:

- `API_TOKEN`: secret trong Render dashboard.
- `REDIS_URL`: Render Redis service.
- `BUCKET_CAPACITY`: 10.
- `REFILL_PER_MINUTE`: 10.
- `DAILY_BUDGET_USD`: 1.0.
- `LOG_LEVEL`: INFO.
- `PORT`: Render tự cấp.

Không ghi giá trị thật của `API_TOKEN` vào `DEPLOYMENT.md`, `report.md`, Git hoặc ảnh chụp màn hình.

### Kết quả kiểm tra public

```text
GET /healthz  -> 200
{"status":"ok","service":"day12-chat-service","version":"1.0.0"}

GET /readyz   -> 200
{"status":"ready","redis":true}

POST /chat không có Authorization -> 401

POST /chat có Bearer token -> 200
Trả về reply, client_id, turns_before, usd_cost và usage.
```

Phiên bản Render được kiểm tra trước khi thêm frontend có thể vẫn trả 404 tại `/` cho đến khi push code và redeploy. Sau khi redeploy commit mới, `/` sẽ mở web console; `/docs` vẫn là tài liệu API tương tác.

## 8. CI/CD với GitHub Actions và Railway

Workflow nằm tại `.github/workflows/ci.yml` và có ba job:

1. `test`: cài `requirements.txt`, chạy CP1 đến CP4 và bỏ qua test Docker bằng `-m "not docker"`.
2. `build-image`: chạy `docker build` để phát hiện lỗi Dockerfile trước khi deploy.
3. `deploy`: chỉ chạy khi push vào `main`, đồng thời có `needs: [test, build-image]` nên test hoặc build lỗi thì không deploy.

Job deploy dùng `RAILWAY_TOKEN` từ GitHub Secrets và ba repository variables:

- `RAILWAY_PROJECT_ID`: ID project Railway.
- `RAILWAY_ENVIRONMENT`: thường là `production`.
- `RAILWAY_SERVICE`: tên service web trên Railway.

Không nên bật đồng thời Railway GitHub Autodeploy và job `railway up` trong workflow này, vì một commit có thể tạo hai lần deploy. Chọn một cơ chế CD; workflow hiện tại là cơ chế được chọn vì nó tạo cổng chất lượng sau CI.

README đã có badge workflow. Badge chỉ chuyển sang `passing` sau khi workflow được push lên GitHub và chạy thành công ít nhất một lần.

## 9. Kết quả test

| Checkpoint | Kết quả |
|------------|---------|
| CP1 | 13 passed |
| CP2 cấu hình không Docker | 14 passed, 2 deselected |
| CP3 | 29 passed |
| CP4 | 19 passed |
| CP5 | 9 passed, 4 skipped |
| Bonus CI/CD cấu trúc workflow | 12 passed, 1 test badge chờ workflow chạy trên GitHub |

Bốn test CP5 bị skip là nhóm `TestLocalFallback`. Chúng chỉ chạy khi `LOCAL_FALLBACK=true`. Vì bài đã deploy cloud nên để `LOCAL_FALLBACK=false` là đúng; các test public deployment đã chạy và pass.

## 10. Các lỗi gặp phải và cách xử lý

### Mở URL root vẫn nhận 404

Nếu Render chưa build commit mới, public service vẫn đang chạy image cũ chưa có frontend. Push code rồi chờ Render redeploy; kiểm tra local bằng `http://localhost:8000/`. Trong thời gian chờ, `/healthz`, `/readyz` và `/docs` vẫn là các endpoint kiểm tra được.

### JSON 400/422 khi gọi bằng PowerShell

PowerShell đôi khi làm mất dấu ngoặc kép khi truyền JSON trực tiếp cho `curl.exe`. Cách ổn định là ghi JSON UTF-8 vào file tạm rồi dùng `--data-binary`.

### Redis báo port 6379 đã được sử dụng

Nguyên nhân là một Redis container khác đã chạy. Kiểm tra bằng:

```powershell
docker ps --filter "publish=6379"
```

Không chạy thêm Redis thứ hai trên cùng port.

## 11. Lệnh kiểm tra cuối

```powershell
Set-Location C:\Users\banka\Documents\DAY12-2A202601842-NguyenTuanTruong

.\.venv\Scripts\python.exe -m pytest tests/test_cp1.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_cp3.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_cp4.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_cp5.py -v
```

Trước khi commit, kiểm tra:

```powershell
git status --short
```

Không commit `.env`, token thật hoặc file test tạm `request.json`.
