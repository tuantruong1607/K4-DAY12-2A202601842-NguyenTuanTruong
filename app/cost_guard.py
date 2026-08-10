"""CP3 — Cost guard: chặn chi phí trước khi hóa đơn chặn bạn.

Rate limit giới hạn *số lượng* request. Cost guard giới hạn *số tiền*: một
client gửi đúng hạn mức request nhưng mỗi request 50k token vẫn đốt sạch
ngân sách.

Lab này chốt ngân sách theo **ngày**, không phải theo tháng. Lý do: hạn mức
tháng chỉ báo động sau khi bạn đã mất phần lớn số tiền; hạn mức ngày giới hạn
thiệt hại tối đa của một sự cố xuống 1/30, và sáng hôm sau service tự hồi
phục mà không cần ai can thiệp.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

# Giữ dữ liệu chi tiêu vài ngày để còn đối soát
KEY_TTL_SECONDS = 3 * 24 * 3600


class CostGuard:
    def __init__(self, client, daily_budget_usd: float) -> None:
        self.client = client
        self.budget = daily_budget_usd

    @staticmethod
    def today() -> str:
        """CHO SẴN — nhãn ngày hiện tại dạng '2026-08-01' (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @classmethod
    def _key(cls, client_id: str, day: str | None = None) -> str:
        """CHO SẴN — khóa Redis theo từng client, từng ngày."""
        return f"spend:{client_id}:{day or cls.today()}"

    def spent(self, client_id: str, day: str | None = None) -> float:
        """Số tiền client đã tiêu trong ngày.

        TODO (CP3): đọc ``self.client.get(self._key(client_id, day))``.
        Key chưa tồn tại → Redis trả None → hàm này phải trả ``0.0``.
        Nhớ ép kiểu ``float(...)`` vì Redis trả về chuỗi.
        """
        value = self.client.get(self._key(client_id, day))
        return 0.0 if value is None else float(value)

    def check(
        self,
        client_id: str,
        estimated_cost: float = 0.0,
        day: str | None = None,
    ) -> None:
        """Cho qua nếu còn ngân sách, ngược lại raise 402.

        TODO (CP3): nếu ``spent(client_id) + estimated_cost > self.budget``
        → raise ``HTTPException(status_code=402, detail="daily budget exceeded")``.
        402 = Payment Required, đúng ngữ nghĩa cho tình huống hết ngân sách.
        """
        if self.spent(client_id, day) + estimated_cost > self.budget:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="daily budget exceeded",
            )

    def record(self, client_id: str, cost: float, day: str | None = None) -> float:
        """Cộng dồn chi phí vừa phát sinh, trả về tổng mới.

        TODO (CP3):
          1. ``total = self.client.incrbyfloat(key, cost)``
          2. ``self.client.expire(key, KEY_TTL_SECONDS)``
          3. ``return float(total)``
        """
        key = self._key(client_id, day)
        total = self.client.incrbyfloat(key, cost)
        self.client.expire(key, KEY_TTL_SECONDS)
        return float(total)

    def remaining(self, client_id: str, day: str | None = None) -> float:
        """CHO SẴN — còn bao nhiêu tiền trong ngân sách hôm nay."""
        return max(0.0, self.budget - self.spent(client_id, day))
