"""Excel 報表輸出。

兩份檔案：
  Model_Report.xlsx   模型摘要、指標、係數、Bolasso 頻率、殘差診斷
  Predictions.xlsx    每個結果變項一張工作表，含原始欄位、預測值、誤差與誤差率
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from regression_app.model.bolasso import BolassoResult
from regression_app.model.modeling import METRIC_ORDER, ModelResult
from regression_app.model.schema import Dataset

MODEL_REPORT_NAME = "Model_Report.xlsx"
PREDICTIONS_NAME = "Predictions.xlsx"

# 真值太接近 0 時，百分比誤差率會爆成天文數字，這種值沒有意義，一律留白。
_RELATIVE_ERROR_FLOOR = 1e-9

_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(name: str) -> str:
    """Excel 工作表名稱有長度與字元限制，超過會直接寫檔失敗。"""
    return _INVALID_SHEET_CHARS.sub("_", name)[:31]


def _write(writer: pd.ExcelWriter, frame: pd.DataFrame, sheet: str) -> None:
    """寫入一張工作表，並套用共用的標題列樣式與欄寬。"""
    sheet = _sheet_name(sheet)
    frame.to_excel(writer, sheet_name=sheet, index=False, startrow=1, header=False)

    book, worksheet = writer.book, writer.sheets[sheet]
    header_fmt = book.add_format(
        {"bold": True, "bg_color": "#DCE6F1", "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True}
    )
    number_fmt = book.add_format({"num_format": "0.0000"})

    for col, name in enumerate(frame.columns):
        worksheet.write(0, col, str(name), header_fmt)
        width = max(len(str(name)) * 1.9, 10)
        if frame[name].dtype == object:
            longest = frame[name].astype(str).str.len().max()
            width = max(width, min(float(longest) * 1.3 + 2, 60))
        is_float = pd.api.types.is_float_dtype(frame[name])
        worksheet.set_column(col, col, width, number_fmt if is_float else None)

    worksheet.freeze_panes(1, 0)


def write_model_report(
    dataset: Dataset,
    models: list[ModelResult],
    bolassos: dict[str, BolassoResult],
    out_dir: Path,
) -> Path:
    """把所有模型結果整理成一份多工作表的 Excel 報表。"""
    path = out_dir / MODEL_REPORT_NAME

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        _write(writer, _summary_table(models, bolassos), "Summary")
        _write(writer, _metrics_table(models), "Metrics")
        _write(writer, _coefficient_table(models), "Coefficients")
        _write(writer, _bolasso_table(bolassos), "Bolasso_Frequency")
        _write(writer, _diagnostics_table(models), "Diagnostics")
        _write(writer, _column_table(dataset), "Column_Definition")

    return path


def _summary_table(models: list[ModelResult], bolassos: dict[str, BolassoResult]) -> pd.DataFrame:
    rows = []
    for model in models:
        bol = bolassos[model.target]
        rows.append(
            {
                "結果變項": model.target,
                "樣本數 n": model.n_obs,
                "候選變項數": len(bol.frequency),
                "選入變項數": model.features and len(model.features) or 0,
                "選入變項": "、".join(model.features),
                "Bolasso α": bol.alpha,
                "選入門檻": bol.threshold,
                "R²": model.metrics["R²"],
                "Adjusted R²": model.metrics["Adjusted R²"],
                "RMSE (樣本內)": model.metrics["RMSE"],
                "RMSE (交叉驗證)": model.cv_metrics["RMSE"],
                "R² (交叉驗證)": model.cv_metrics["R²"],
                "F 統計量": model.diagnostics["F 統計量"],
                "F 檢定 p 值": model.diagnostics["F 檢定 p 值"],
                "AIC": model.diagnostics["AIC"],
                "BIC": model.diagnostics["BIC"],
                "門檻退讓說明": bol.fallback_note or "—",
            }
        )
    return pd.DataFrame(rows)


def _metrics_table(models: list[ModelResult]) -> pd.DataFrame:
    rows = []
    for model in models:
        for source, values in (("樣本內", model.metrics), ("5-fold 交叉驗證", model.cv_metrics)):
            row = {"結果變項": model.target, "評估方式": source}
            row.update({metric: values[metric] for metric in METRIC_ORDER})
            rows.append(row)
    return pd.DataFrame(rows)


def _coefficient_table(models: list[ModelResult]) -> pd.DataFrame:
    frames = []
    for model in models:
        table = model.coefficients.copy()
        table.insert(0, "結果變項", model.target)
        table["顯著性"] = table["p 值"].map(_stars)
        frames.append(table)
    return pd.concat(frames, ignore_index=True)


def _stars(p: float) -> str:
    if pd.isna(p):
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "n.s."


def _bolasso_table(bolassos: dict[str, BolassoResult]) -> pd.DataFrame:
    rows = []
    for target, bol in bolassos.items():
        chosen = set(bol.selected)
        for feature, freq in bol.frequency.items():
            rows.append(
                {
                    "結果變項": target,
                    "候選變項": feature,
                    "選入頻率": float(freq),
                    "是否選入": "是" if feature in chosen else "否",
                    "門檻": bol.threshold,
                    "bootstrap 次數": bol.n_bootstrap,
                    "α": bol.alpha,
                }
            )
    return pd.DataFrame(rows)


def _diagnostics_table(models: list[ModelResult]) -> pd.DataFrame:
    rows = []
    for model in models:
        row = {"結果變項": model.target}
        row.update(model.diagnostics)
        rows.append(row)
    return pd.DataFrame(rows)


def _column_table(dataset: Dataset) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "欄位": c.name,
                "角色": c.role_raw,
                "資料類型": c.data_type,
                "優先級": c.priority,
                "合理範圍": c.continuity,
                "合法類別": c.category,
                "備註": c.note,
            }
            for c in dataset.columns
        ]
    )


def write_predictions(dataset: Dataset, models: list[ModelResult], out_dir: Path) -> Path:
    """每個結果變項一張工作表：原始欄位 + 預測值 + 誤差 + 誤差率。"""
    path = out_dir / PREDICTIONS_NAME

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        for model in models:
            frame = _prediction_frame(dataset, model)
            _write(writer, frame, model.target)

    return path


def _prediction_frame(dataset: Dataset, model: ModelResult) -> pd.DataFrame:
    """組出單一結果變項的預測表。

    未參與建模的列（含缺失值而被整列刪除的）保留在表中，預測相關欄位留白，
    這樣列數與原始 Data 對得上，回頭比對比較不會錯行。
    """
    target = model.target
    frame = dataset.frame.copy()

    pred = model.predictions.reindex(frame.index)
    truth = frame[target]
    error = pred - truth

    frame[f"{target}_預測值"] = pred
    frame["誤差 (預測 − 實際)"] = error
    frame["絕對誤差"] = error.abs()

    # 真值接近 0 時百分比會爆掉，這些格子留白而不是印出 999999%。
    safe = truth.abs() >= _RELATIVE_ERROR_FLOOR
    frame["誤差率 (%)"] = np.where(safe, error / truth.where(safe) * 100.0, np.nan)

    # 本樣板的欄位都是平均 0 的量尺，上面那欄大多沒有意義，
    # 因此另外給一個以全距為分母的版本，跨變項也能比較。
    spread = float(truth.max() - truth.min())
    frame["誤差率 (佔全距 %)"] = error / spread * 100.0 if spread > 0 else np.nan

    frame["是否納入建模"] = np.where(pred.notna(), "是", "否")
    return frame.reset_index(drop=True)
