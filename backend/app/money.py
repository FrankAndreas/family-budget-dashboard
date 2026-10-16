"""Money columns: stored as integer cents, handed to the code (and the API) as francs."""

from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.types import TypeDecorator


class Money(TypeDecorator):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Optional[float], dialect) -> Optional[int]:
        return None if value is None else round(value * 100)

    def process_result_value(self, value: Optional[int], dialect) -> Optional[float]:
        return None if value is None else value / 100
