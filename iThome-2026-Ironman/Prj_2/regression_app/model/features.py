"""建立設計矩陣。Bolasso 與最終 OLS 必須用同一套欄位，所以集中在這裡。"""

from __future__ import annotations

import pandas as pd

from regression_app.model.schema import ColumnSpec


def build_design_matrix(
    frame: pd.DataFrame, inputs: list[ColumnSpec]
) -> tuple[pd.DataFrame, dict[str, str]]:
    """把輸入欄位攤成數值矩陣。

    連續型原樣保留；類別型做 One-Hot（丟掉第一個水準當作參考組）。
    回傳 (設計矩陣, {展開後欄名: 原始欄名})，後者讓報表能把 One-Hot 欄位追回原欄位。
    """
    pieces: list[pd.DataFrame] = []
    origin: dict[str, str] = {}

    for spec in inputs:
        series = frame[spec.name]
        if spec.is_categorical:
            dummies = pd.get_dummies(series.astype("string"), prefix=spec.name, drop_first=True, dtype=float)
            for col in dummies.columns:
                origin[col] = spec.name
            pieces.append(dummies)
        else:
            pieces.append(series.astype(float).to_frame(spec.name))
            origin[spec.name] = spec.name

    matrix = pd.concat(pieces, axis=1) if pieces else pd.DataFrame(index=frame.index)
    return matrix, origin


def drop_incomplete(design: pd.DataFrame, target: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """整列刪除缺失值（listwise deletion），並保留原本的 index 以便回填預測值。"""
    mask = design.notna().all(axis=1) & target.notna()
    return design.loc[mask], target.loc[mask]
