"""Bolasso — Bootstrap-enhanced Lasso 變數篩選。

Bach (2008)：對資料重複做 bootstrap，每次跑一次 Lasso，記錄每個變項被選入
（係數不為 0）的次數；在夠多次抽樣中都存活的變項才視為真的有貢獻。
本實作的 α 用全樣本 LassoCV 選一次後固定，讓 200 次抽樣的懲罰強度一致、
選入頻率之間可以直接比較。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso, LassoCV

from regression_app.model.context import RunContext

# 係數絕對值小於此值視為 0。Lasso 的座標下降不會給出剛好 0.0 的浮點數。
_ZERO_TOL = 1e-8

# 嚴格門檻選不出任何變項時的退讓門檻。
_FALLBACK_THRESHOLD = 0.5


@dataclass
class BolassoResult:
    """單一結果變項的篩選結果。"""

    target: str
    alpha: float
    n_bootstrap: int
    threshold: float
    frequency: pd.Series          # 欄位 -> 選入頻率（0～1），由高到低
    selected: list[str]
    fallback_note: str = ""       # 有退讓時說明退讓方式，供報告揭露

    @property
    def n_selected(self) -> int:
        return len(self.selected)


def run_bolasso(
    design: pd.DataFrame,
    target: pd.Series,
    *,
    n_bootstrap: int = 200,
    threshold: float = 0.9,
    random_state: int = 0,
    ctx: RunContext | None = None,
    label: str = "",
) -> BolassoResult:
    """對單一結果變項跑 Bolasso。"""
    features = list(design.columns)
    X = design.to_numpy(dtype=float)
    y = target.to_numpy(dtype=float)

    # Lasso 的懲罰對尺度敏感，先標準化，選出來的變項才不受單位影響。
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0          # 常數欄不會被選入，但也不能除以 0
    Xz = (X - mean) / std

    alpha = float(LassoCV(cv=5, random_state=random_state).fit(Xz, y).alpha_)
    if ctx:
        ctx.log(f"{label}α = {alpha:.4f}（5-fold LassoCV 於全樣本選定），開始 {n_bootstrap} 次 bootstrap")

    rng = np.random.default_rng(random_state)
    n = len(y)
    counts = np.zeros(len(features), dtype=int)

    for i in range(n_bootstrap):
        if ctx and i % 10 == 0:
            ctx.check()
        idx = rng.integers(0, n, n)
        model = Lasso(alpha=alpha, max_iter=10_000).fit(Xz[idx], y[idx])
        counts += np.abs(model.coef_) > _ZERO_TOL
        if ctx and (i + 1) % 50 == 0:
            ctx.stage(f"{label}bootstrap {i + 1}／{n_bootstrap}")

    frequency = pd.Series(counts / n_bootstrap, index=features).sort_values(ascending=False)

    selected = [f for f in features if frequency[f] >= threshold]
    fallback_note = ""
    if not selected:
        selected = [f for f in features if frequency[f] >= _FALLBACK_THRESHOLD]
        if selected:
            fallback_note = (
                f"沒有變項達到 {threshold:.0%} 門檻，改以 {_FALLBACK_THRESHOLD:.0%} 門檻選入 "
                f"{len(selected)} 個變項。"
            )
        else:
            selected = [frequency.index[0]]
            fallback_note = (
                f"沒有變項達到 {_FALLBACK_THRESHOLD:.0%} 門檻，僅保留頻率最高的 "
                f"{selected[0]}（{frequency.iloc[0]:.0%}）以便仍能建立模型。"
            )

    # 依原始欄位順序輸出，讓報表的欄位排列跟 Excel 一致。
    selected = [f for f in features if f in set(selected)]

    return BolassoResult(
        target=str(target.name),
        alpha=alpha,
        n_bootstrap=n_bootstrap,
        threshold=threshold,
        frequency=frequency,
        selected=selected,
        fallback_note=fallback_note,
    )
