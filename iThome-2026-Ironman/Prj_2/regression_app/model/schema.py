"""資料集的結構描述，對應 Data_Template_Stats_Format_Definition.md。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROLE_INFO = "Info"
ROLE_INPUT = "Input"
ROLE_RESULT = "Result"

TYPE_CONTINUOUS = "Continuous"
TYPE_CATEGORICAL = "Categorical"
TYPE_NONE = "None"

# Definition 工作表第一欄的列標籤。前三個缺一不可，其餘可省略。
REQUIRED_DEF_ROWS = ("Feature", "Feature_Type", "Data_Type")
OPTIONAL_DEF_ROWS = ("Priority", "Continuity", "Category", "Note")

SHEET_DEFINITION = "Definition"
SHEET_DATA = "Data"


@dataclass(frozen=True)
class ColumnSpec:
    """Definition 工作表中的一個欄位（一整欄的屬性）。"""

    name: str
    role: str          # Info / Input / Result
    role_raw: str      # 原始寫法，例如 Input_01
    data_type: str     # Continuous / Categorical / None
    priority: str = ""
    continuity: str = ""
    category: str = ""
    note: str = ""

    @property
    def is_continuous(self) -> bool:
        return self.data_type == TYPE_CONTINUOUS

    @property
    def is_categorical(self) -> bool:
        return self.data_type == TYPE_CATEGORICAL

    @property
    def analysable(self) -> bool:
        """是否可能參與分析：角色是 Input/Result，且型別不是 None。"""
        return self.role in (ROLE_INPUT, ROLE_RESULT) and self.data_type != TYPE_NONE


@dataclass
class ValidationIssue:
    """一項格式問題。level 為 error 時不予載入，warning 只提示。"""

    level: str   # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class Dataset:
    """通過格式檢查後的資料集。"""

    path: Path
    frame: pd.DataFrame
    columns: list[ColumnSpec]
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.frame)

    def by_role(self, role: str) -> list[ColumnSpec]:
        return [c for c in self.columns if c.role == role]

    @property
    def inputs(self) -> list[ColumnSpec]:
        return [c for c in self.by_role(ROLE_INPUT) if c.data_type != TYPE_NONE]

    @property
    def results(self) -> list[ColumnSpec]:
        return [c for c in self.by_role(ROLE_RESULT) if c.data_type != TYPE_NONE]

    @property
    def infos(self) -> list[ColumnSpec]:
        return self.by_role(ROLE_INFO)

    def spec_of(self, name: str) -> ColumnSpec | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None


@dataclass
class AnalysisRequest:
    """使用者在 UI 上勾選完之後，交給分析流程的參數。"""

    dataset: Dataset
    input_names: list[str]
    result_names: list[str]
    output_dir: Path
    n_bootstrap: int = 200
    selection_threshold: float = 0.9
    random_state: int = 0
