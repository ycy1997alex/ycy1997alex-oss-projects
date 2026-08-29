"""分析流程與 UI 之間的細管子：只傳進度、只傳取消訊號。

Model 層不認識 tkinter；它只知道兩個 callback 和一個 Event。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


class AnalysisCancelled(Exception):
    """使用者中止分析時，由 RunContext.check() 丟出，一路往上把流程收掉。"""


@dataclass
class RunContext:
    """分析流程共用的執行環境。"""

    cancel_event: threading.Event = field(default_factory=threading.Event)
    on_log: Callable[[str], None] = lambda msg: None
    on_stage: Callable[[str], None] = lambda text: None

    def check(self) -> None:
        """在每個可中斷的邊界呼叫；已被要求中止就丟例外。"""
        if self.cancel_event.is_set():
            raise AnalysisCancelled()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def log(self, message: str) -> None:
        self.on_log(message)

    def stage(self, text: str) -> None:
        """更新進度條旁邊那行短字（例如「Bolasso 2／3」）。"""
        self.on_stage(text)
