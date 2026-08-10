"""CP3 — Xác thực bằng Bearer token.

Public URL = ai cũng gọi được. Không có lớp này, hóa đơn LLM của bạn do
người lạ quyết định.

Chuẩn dùng ở đây là **RFC 6750** — token đi trong header ``Authorization``:

    Authorization: Bearer <token>

Đây là cách mọi API lớn (GitHub, Stripe, OpenAI) nhận token, nên client viết
bằng ngôn ngữ nào cũng có sẵn thư viện hiểu nó.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings

ANONYMOUS_CLIENT = "anonymous"
SCHEME = "Bearer"


def verify_bearer_token(
    authorization: str | None = Header(default=None),
    x_client_id: str | None = Header(default=None),
) -> str:
    """Kiểm tra header ``Authorization``; trả về client_id nếu hợp lệ.

    TODO (CP3):
      1. Thiếu header ``authorization`` → 401.
      2. Tách header thành 2 phần: ``scheme, _, token = authorization.partition(" ")``.
         Sai scheme (không phải ``Bearer``, so sánh không phân biệt hoa thường)
         hoặc token rỗng → 401.
      3. So sánh ``token`` với ``get_settings().api_token`` bằng
         ``secrets.compare_digest(a, b)`` — **không dùng** ``==``.
         Toán tử ``==`` dừng ngay tại ký tự đầu khác nhau, nên thời gian trả
         lời rò rỉ thông tin về token (timing attack). ``compare_digest``
         luôn chạy hết chuỗi.
      4. Mọi trường hợp 401 dùng chung::

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

         Header ``WWW-Authenticate`` là bắt buộc theo chuẩn HTTP cho response
         401 — nó nói cho client biết phải xác thực kiểu gì.

         Dùng **cùng một** thông báo cho mọi trường hợp: nói rõ "sai scheme"
         hay "token không đúng" là tặng thông tin cho người đang dò.
      5. Hợp lệ → trả về ``x_client_id`` nếu client có gửi, ngược lại trả
         ``ANONYMOUS_CLIENT``. client_id này là đơn vị để rate limit và tính
         chi phí.
    """
    def unauthorized() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization:
        unauthorized()

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != SCHEME.lower() or not token:
        unauthorized()

    expected = get_settings().api_token
    if not secrets.compare_digest(token, expected):
        unauthorized()

    return x_client_id or ANONYMOUS_CLIENT
