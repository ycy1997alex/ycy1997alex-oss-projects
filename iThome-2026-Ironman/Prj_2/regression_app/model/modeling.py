"""以 Bolasso 選出的變項建立 OLS 迴歸模型，並算出評估指標與診斷統計量。

用 statsmodels 而不是 sklearn，是因為報告需要 p 值、標準誤與信賴區間 ——
sklearn 的線性模型不提供這些。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, jarque_bera

# 指標在報表與圖上的顯示順序，以及「越大越好」還是「越小越好」。
METRIC_ORDER = ["MAE", "MSE", "RMSE", "Max Error", "R²", "Adjusted R²"]
METRIC_HIGHER_IS_BETTER = {"R²": True, "Adjusted R²": True}

CV_FOLDS = 5


@dataclass
class ModelResult:
    """單一結果變項的完整建模結果。"""

    target: str
    features: list[str]
    n_obs: int
    fitted: object                      # statsmodels RegressionResultsWrapper
    predictions: pd.Series              # index 對齊原始資料列
    residuals: pd.Series
    metrics: dict[str, float]           # 樣本內
    cv_metrics: dict[str, float]        # 5-fold 交叉驗證（樣本外）
    coefficients: pd.DataFrame
    diagnostics: dict[str, float] = field(default_factory=dict)

    @property
    def formula(self) -> str:
        params = self.fitted.params
        terms = [f"{params[f]:+.4f}·{f}" for f in self.features]
        return f"{self.target} = {params['const']:.4f} " + " ".join(terms)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray, n_predictors: int) -> dict[str, float]:
    """六項迴歸指標。Adjusted R² 用 n 與預測變項個數（不含截距）校正。"""
    error = y_pred - y_true
    n = len(y_true)
    ss_res = float(np.sum(error**2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    denom = n - n_predictors - 1
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / denom if denom > 0 else float("nan")

    return {
        "MAE": float(np.mean(np.abs(error))),
        "MSE": float(np.mean(error**2)),
        "RMSE": float(np.sqrt(np.mean(error**2))),
        "Max Error": float(np.max(np.abs(error))),
        "R²": r2,
        "Adjusted R²": adj_r2,
    }


def fit_model(design: pd.DataFrame, target: pd.Series, features: list[str], random_state: int = 0) -> ModelResult:
    """對選定的變項配適 OLS，並補上交叉驗證與殘差診斷。"""
    X = design[features]
    y = target
    X_const = sm.add_constant(X, has_constant="add")

    fitted = sm.OLS(y, X_const).fit()
    y_pred = pd.Series(fitted.predict(X_const), index=y.index, name=f"{target.name}_pred")
    residuals = pd.Series(y_pred.to_numpy() - y.to_numpy(), index=y.index, name="residual")

    metrics = regression_metrics(y.to_numpy(), y_pred.to_numpy(), len(features))
    cv_metrics = _cross_validated_metrics(X.to_numpy(float), y.to_numpy(float), len(features), random_state)

    return ModelResult(
        target=str(target.name),
        features=features,
        n_obs=int(fitted.nobs),
        fitted=fitted,
        predictions=y_pred,
        residuals=residuals,
        metrics=metrics,
        cv_metrics=cv_metrics,
        coefficients=_coefficient_table(fitted, X_const, features),
        diagnostics=_diagnostics(fitted, X_const),
    )


def _cross_validated_metrics(
    X: np.ndarray, y: np.ndarray, n_predictors: int, random_state: int
) -> dict[str, float]:
    """5-fold 交叉驗證。彙總各折的樣本外預測後一次算指標。

    樣本內 R² 一定偏樂觀；沒有這組數字，報告會高估模型的實際預測能力。
    """
    n = len(y)
    if n < CV_FOLDS * 2:
        return {k: float("nan") for k in METRIC_ORDER}

    oof = np.empty(n, dtype=float)
    for train_idx, test_idx in KFold(n_splits=CV_FOLDS, shuffle=True, random_state=random_state).split(X):
        model = LinearRegression().fit(X[train_idx], y[train_idx])
        oof[test_idx] = model.predict(X[test_idx])
    return regression_metrics(y, oof, n_predictors)


def _coefficient_table(fitted, X_const: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """係數、標準誤、t、p、95% CI、標準化係數與 VIF。"""
    conf = fitted.conf_int(alpha=0.05)
    conf.columns = ["CI 下界 (95%)", "CI 上界 (95%)"]

    table = pd.DataFrame(
        {
            "係數": fitted.params,
            "標準誤": fitted.bse,
            "t 值": fitted.tvalues,
            "p 值": fitted.pvalues,
        }
    ).join(conf)

    # 標準化係數（beta）讓不同單位的變項可以互相比較影響力大小。
    y_std = float(np.std(fitted.model.endog, ddof=1))
    betas = {"const": float("nan")}
    for f in features:
        x_std = float(X_const[f].std(ddof=1))
        betas[f] = fitted.params[f] * x_std / y_std if y_std > 0 else float("nan")
    table["標準化係數 β"] = pd.Series(betas)

    table["VIF"] = pd.Series(_vif(X_const, features))
    table.index.name = "變項"
    return table.reset_index()


def _vif(X_const: pd.DataFrame, features: list[str]) -> dict[str, float]:
    """變異數膨脹因子。只有一個預測變項時共線性不存在，直接給 1。"""
    values: dict[str, float] = {"const": float("nan")}
    if len(features) < 2:
        return values | {f: 1.0 for f in features}

    matrix = X_const.to_numpy(dtype=float)
    for pos, name in enumerate(X_const.columns):
        if name == "const":
            continue
        try:
            values[name] = float(variance_inflation_factor(matrix, pos))
        except Exception:
            values[name] = float("nan")
    return values


def _diagnostics(fitted, X_const: pd.DataFrame) -> dict[str, float]:
    """殘差診斷：自我相關、異質變異、常態性、共線性。"""
    resid = np.asarray(fitted.resid, dtype=float)
    out: dict[str, float] = {
        "Durbin-Watson": float(durbin_watson(resid)),
        "條件數 (Condition No.)": float(np.linalg.cond(X_const.to_numpy(dtype=float))),
        "F 統計量": float(fitted.fvalue),
        "F 檢定 p 值": float(fitted.f_pvalue),
        "AIC": float(fitted.aic),
        "BIC": float(fitted.bic),
    }
    try:
        out["Breusch-Pagan p 值"] = float(het_breuschpagan(resid, X_const.to_numpy(dtype=float))[1])
    except Exception:
        out["Breusch-Pagan p 值"] = float("nan")
    try:
        out["Jarque-Bera p 值"] = float(jarque_bera(resid)[1])
    except Exception:
        out["Jarque-Bera p 值"] = float("nan")
    return out
