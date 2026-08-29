"""讀取樣板格式的 Excel 並做格式檢查。

檢查一次跑完所有規則、把問題全部收集起來再回傳，不會遇到第一個錯就中斷 ——
使用者可以一次改完，不必改一個跑一次。
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from regression_app.model.schema import (
    OPTIONAL_DEF_ROWS,
    REQUIRED_DEF_ROWS,
    ROLE_INFO,
    ROLE_INPUT,
    ROLE_RESULT,
    SHEET_DATA,
    SHEET_DEFINITION,
    TYPE_CATEGORICAL,
    TYPE_CONTINUOUS,
    TYPE_NONE,
    ColumnSpec,
    Dataset,
    ValidationIssue,
)

_ROLE_PATTERN = re.compile(r"^(Info|Input|Result)(?:_\d+)?$", re.IGNORECASE)
_ROLE_CANON = {"info": ROLE_INFO, "input": ROLE_INPUT, "result": ROLE_RESULT}
_TYPE_CANON = {
    "continuous": TYPE_CONTINUOUS,
    "categorical": TYPE_CATEGORICAL,
    "none": TYPE_NONE,
}

# 低於這個樣本數仍可分析，但迴歸結果不穩定，提示使用者。
MIN_RECOMMENDED_ROWS = 50


def _cell(value: object) -> str:
    """儲存格轉成去掉前後空白的字串；空值一律回空字串。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def load_dataset(path: str | Path) -> tuple[Dataset | None, list[ValidationIssue]]:
    """讀取並檢查 Excel。

    回傳 (dataset, issues)。只要 issues 內含 level=="error"，dataset 就是 None。
    """
    path = Path(path)
    issues: list[ValidationIssue] = []

    def err(msg: str) -> None:
        issues.append(ValidationIssue("error", msg))

    def warn(msg: str) -> None:
        issues.append(ValidationIssue("warning", msg))

    if not path.is_file():
        err(f"找不到檔案：{path}")
        return None, issues

    try:
        with pd.ExcelFile(path, engine="openpyxl") as book:
            sheet_names = list(book.sheet_names)
            missing = [s for s in (SHEET_DEFINITION, SHEET_DATA) if s not in sheet_names]
            if missing:
                err(f"缺少必要的工作表：{'、'.join(missing)}（現有工作表：{'、'.join(sheet_names)}）")
                return None, issues
            def_raw = book.parse(SHEET_DEFINITION, header=None)
            data_raw = book.parse(SHEET_DATA, header=0, na_values=["NA"], keep_default_na=True)
    except Exception as exc:  # 檔案損毀、被 Excel 鎖住、根本不是 xlsx…
        err(f"無法開啟檔案：{exc}")
        return None, issues

    extra_sheets = [s for s in sheet_names if s not in (SHEET_DEFINITION, SHEET_DATA)]
    if extra_sheets:
        warn(f"忽略不參與分析的工作表：{'、'.join(extra_sheets)}")

    columns, def_issues = _parse_definition(def_raw)
    issues.extend(def_issues)
    if any(i.level == "error" for i in def_issues):
        return None, issues

    issues.extend(_check_data_alignment(columns, data_raw))
    issues.extend(_check_roles(columns))

    frame, type_issues = _coerce_types(columns, data_raw)
    issues.extend(type_issues)

    if len(frame) == 0:
        err("Data 工作表沒有任何資料列。")
    elif len(frame) < MIN_RECOMMENDED_ROWS:
        warn(f"樣本數只有 {len(frame)} 筆，低於建議的 {MIN_RECOMMENDED_ROWS} 筆，迴歸結果會不穩定。")

    if any(i.level == "error" for i in issues):
        return None, issues

    dataset = Dataset(
        path=path,
        frame=frame,
        columns=columns,
        warnings=[i for i in issues if i.level == "warning"],
    )
    return dataset, issues


def _parse_definition(def_raw: pd.DataFrame) -> tuple[list[ColumnSpec], list[ValidationIssue]]:
    """把轉置格式的 Definition 解析成一串 ColumnSpec。"""
    issues: list[ValidationIssue] = []

    if def_raw.empty or def_raw.shape[1] < 2:
        issues.append(ValidationIssue("error", "Definition 工作表是空的，或只有列標籤沒有任何欄位定義。"))
        return [], issues

    # 第一欄是列標籤（Feature、Feature_Type…），其餘每一欄是一個特徵。
    rows: dict[str, list[str]] = {}
    for _, row in def_raw.iterrows():
        label = _cell(row.iloc[0])
        if label:
            rows[label] = [_cell(v) for v in row.iloc[1:]]

    missing_rows = [r for r in REQUIRED_DEF_ROWS if r not in rows]
    if missing_rows:
        issues.append(
            ValidationIssue(
                "error",
                f"Definition 缺少必要的列：{'、'.join(missing_rows)}"
                f"（第一欄找到的列標籤：{'、'.join(rows) or '無'}）",
            )
        )
        return [], issues

    features = rows["Feature"]
    # 尾端的空白欄位不算欄位定義。
    while features and not features[-1]:
        features.pop()
    if not features:
        issues.append(ValidationIssue("error", "Definition 的 Feature 列沒有填任何欄位名稱。"))
        return [], issues

    def value_at(label: str, idx: int) -> str:
        values = rows.get(label, [])
        return values[idx] if idx < len(values) else ""

    seen: dict[str, int] = {}
    columns: list[ColumnSpec] = []
    for idx, name in enumerate(features):
        col_letter = _excel_column_letter(idx + 2)  # 特徵從 B 欄開始
        if not name:
            issues.append(ValidationIssue("error", f"Definition {col_letter} 欄的 Feature 是空的，欄位名稱不可留白。"))
            continue
        if name in seen:
            issues.append(
                ValidationIssue(
                    "error",
                    f"Definition 出現重複欄位名稱「{name}」"
                    f"（{_excel_column_letter(seen[name] + 2)} 欄與 {col_letter} 欄）。",
                )
            )
            continue
        seen[name] = idx

        role_raw = value_at("Feature_Type", idx)
        match = _ROLE_PATTERN.match(role_raw)
        if not match:
            issues.append(
                ValidationIssue(
                    "error",
                    f"Definition {col_letter} 欄 {name}：Feature_Type「{role_raw or '（空白）'}」不是合法值，"
                    f"須為 Info_XX ／ Input_XX ／ Result_XX。",
                )
            )
            continue
        role = _ROLE_CANON[match.group(1).lower()]

        type_raw = value_at("Data_Type", idx)
        if not type_raw and role == ROLE_INFO:
            data_type = TYPE_NONE  # Info 欄留白視同 None
        else:
            data_type = _TYPE_CANON.get(type_raw.lower(), "")
            if not data_type:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"Definition {col_letter} 欄 {name}：Data_Type「{type_raw or '（空白）'}」不是合法值，"
                        f"須為 Continuous ／ Categorical ／ None。",
                    )
                )
                continue

        if role in (ROLE_INPUT, ROLE_RESULT) and data_type == TYPE_NONE:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"{name} 角色是 {role_raw} 但 Data_Type 為 None，將不參與分析。",
                )
            )

        columns.append(
            ColumnSpec(
                name=name,
                role=role,
                role_raw=role_raw,
                data_type=data_type,
                priority=value_at("Priority", idx),
                continuity=value_at("Continuity", idx),
                category=value_at("Category", idx),
                note=value_at("Note", idx),
            )
        )

    unknown_rows = [r for r in rows if r not in REQUIRED_DEF_ROWS and r not in OPTIONAL_DEF_ROWS]
    if unknown_rows:
        issues.append(ValidationIssue("warning", f"Definition 有不認得的列，已忽略：{'、'.join(unknown_rows)}"))

    return columns, issues


def _check_data_alignment(columns: list[ColumnSpec], data: pd.DataFrame) -> list[ValidationIssue]:
    """Definition 的欄位名稱與 Data 的標題列必須完全對得上。"""
    issues: list[ValidationIssue] = []
    declared = [c.name for c in columns]
    actual = [str(c).strip() for c in data.columns]

    missing = [n for n in declared if n not in actual]
    if missing:
        issues.append(ValidationIssue("error", f"Data 缺少 Definition 宣告的欄位：{'、'.join(missing)}"))

    extra = [n for n in actual if n not in declared and not n.startswith("Unnamed:")]
    if extra:
        issues.append(ValidationIssue("warning", f"Data 有 Definition 未宣告的欄位，已忽略：{'、'.join(extra)}"))

    return issues


def _check_roles(columns: list[ColumnSpec]) -> list[ValidationIssue]:
    """角色組合要足以建立迴歸模型。"""
    issues: list[ValidationIssue] = []
    inputs = [c for c in columns if c.role == ROLE_INPUT and c.data_type != TYPE_NONE]
    results = [c for c in columns if c.role == ROLE_RESULT and c.data_type != TYPE_NONE]

    if not inputs:
        issues.append(ValidationIssue("error", "Definition 沒有任何可分析的 Input_XX 欄位，無法建立模型。"))
    if not results:
        issues.append(ValidationIssue("error", "Definition 沒有任何可分析的 Result_XX 欄位，無法建立迴歸模型。"))

    for col in results:
        if col.is_categorical:
            issues.append(
                ValidationIssue(
                    "error",
                    f"結果變項 {col.name} 的 Data_Type 是 Categorical。本工具只做迴歸，"
                    f"類別型結果變項屬於分類任務，不在支援範圍。",
                )
            )
    return issues


def _coerce_types(
    columns: list[ColumnSpec], data: pd.DataFrame
) -> tuple[pd.DataFrame, list[ValidationIssue]]:
    """把連續型欄位轉成數值，並回報轉不過去的內容。"""
    issues: list[ValidationIssue] = []
    keep = [c.name for c in columns if c.name in data.columns]
    frame = data[keep].copy()

    for col in columns:
        if col.name not in frame.columns or not col.is_continuous:
            continue
        original = frame[col.name]
        converted = pd.to_numeric(original, errors="coerce")
        broke = original.notna() & converted.isna()
        if broke.any():
            samples = original[broke].astype(str).unique()[:3]
            issues.append(
                ValidationIssue(
                    "error",
                    f"連續型欄位 {col.name} 有 {int(broke.sum())} 個無法轉成數值的內容"
                    f"（例如：{'、'.join(samples)}）。",
                )
            )
        frame[col.name] = converted

    analysable = [c.name for c in columns if c.analysable and c.name in frame.columns]
    if analysable:
        n_missing = int(frame[analysable].isna().sum().sum())
        if n_missing:
            issues.append(
                ValidationIssue(
                    "warning",
                    f"分析欄位共有 {n_missing} 個缺失值，建模時會整列刪除（listwise deletion）。",
                )
            )
    return frame, issues


def _excel_column_letter(index_1based: int) -> str:
    """1 -> A、2 -> B、27 -> AA，用來把問題指回 Excel 上看得到的位置。"""
    letters = ""
    n = index_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
