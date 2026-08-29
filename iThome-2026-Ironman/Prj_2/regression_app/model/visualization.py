"""所有圖表輸出。

在背景執行緒裡跑，所以強制 Agg backend —— 任何 GUI backend 在非主執行緒
畫圖都會當掉。每張圖畫完就 plt.close()，否則跑完一輪會累積上百張圖在記憶體裡。
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402
from scipy import stats  # noqa: E402

from regression_app.model.bolasso import BolassoResult  # noqa: E402
from regression_app.model.context import RunContext  # noqa: E402
from regression_app.model.modeling import METRIC_HIGHER_IS_BETTER, METRIC_ORDER, ModelResult  # noqa: E402

HIST_BINS = 50
DPI = 300

VIS_DIR = "Visualization"
VAR_DIR = "Variable Analysis"
CROSS_DIR = "Input×Result Analysis"
MODEL_DIR = "Model Analysis"

_PRIMARY = "#2780e3"
_ACCENT = "#ff7518"
_MUTED = "#7E8081"


def apply_style() -> None:
    """套用全域繪圖樣式。中文標題若沒設字型會變成一排豆腐框。"""
    sns.set_style("white")
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def save_fig(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def pad_ylim(ax, ymin: float, ymax: float, ratio: float = 0.05) -> None:
    """上下各留 5% 空間，資料點不會貼在框線上。"""
    span = ymax - ymin
    pad = span * ratio if span > 0 else max(abs(ymax), 1.0) * ratio
    ax.set_ylim(ymin - pad, ymax + pad)


def _grid_shape(n: int, max_cols: int = 4) -> tuple[int, int]:
    cols = min(max_cols, max(1, n))
    return math.ceil(n / cols), cols


# --------------------------------------------------------------------------
# 3. 統計視覺化
# --------------------------------------------------------------------------

def plot_violin(frame: pd.DataFrame, columns: list[str], out_dir: Path) -> Path:
    """3a. 所有連續型欄位的小提琴圖（內含盒鬚圖），同一張圖多個子圖。"""
    rows, cols = _grid_shape(len(columns))
    fig = plt.figure(figsize=(3.4 * cols, 3.6 * rows))
    gs = GridSpec(rows, cols, figure=fig, hspace=0.42, wspace=0.32)

    for i, name in enumerate(columns):
        ax = fig.add_subplot(gs[i // cols, i % cols])
        values = frame[name].dropna()
        sns.violinplot(y=values, ax=ax, inner="box", color=_PRIMARY, alpha=0.55, linewidth=1.1)
        ax.set_title(name, fontsize=11)
        ax.set_ylabel("")
        ax.set_xlabel("")
        pad_ylim(ax, float(values.min()), float(values.max()))

    fig.suptitle("連續型欄位分布（小提琴圖，內含盒鬚圖）", fontsize=14, y=1.0)
    path = out_dir / VIS_DIR / "01_violin_boxplot.png"
    save_fig(fig, path)
    return path


def plot_histograms(frame: pd.DataFrame, columns: list[str], out_dir: Path, ctx: RunContext | None = None) -> list[Path]:
    """3b. 每個連續型欄位一張直方圖（50 bins），疊上 KDE 與常態擬合線。"""
    paths: list[Path] = []
    target_dir = out_dir / VIS_DIR / VAR_DIR

    for name in columns:
        if ctx:
            ctx.check()
        values = frame[name].dropna()
        fig, ax = plt.subplots(figsize=(7.2, 4.6))

        ax.hist(values, bins=HIST_BINS, density=True, color=_PRIMARY, alpha=0.45, edgecolor="white", linewidth=0.5)

        xs = np.linspace(values.min(), values.max(), 400)
        kde = stats.gaussian_kde(values)
        ax.plot(xs, kde(xs), color=_PRIMARY, linewidth=2.2, label="KDE 擬合")

        mu, sigma = float(values.mean()), float(values.std(ddof=1))
        ax.plot(xs, stats.norm.pdf(xs, mu, sigma), color=_ACCENT, linewidth=1.8, linestyle="--",
                alpha=0.9, label=f"常態擬合 μ={mu:.2f}, σ={sigma:.2f}")

        top = max(kde(xs).max(), stats.norm.pdf(xs, mu, sigma).max())
        pad_ylim(ax, 0.0, float(top))
        ax.set_title(f"{name} 分布（{HIST_BINS} bins）", fontsize=12)
        ax.set_xlabel(name)
        ax.set_ylabel("機率密度")
        ax.legend(frameon=False, fontsize=9)

        path = target_dir / f"hist_{name}.png"
        save_fig(fig, path)
        paths.append(path)

    return paths


def plot_scatter_matrix(
    frame: pd.DataFrame, inputs: list[str], results: list[str], out_dir: Path, ctx: RunContext | None = None
) -> list[Path]:
    """3c. 每個結果變項一張圖，子圖為它對上各個輸入變項的散布圖。"""
    paths: list[Path] = []
    target_dir = out_dir / VIS_DIR / CROSS_DIR

    for result in results:
        if ctx:
            ctx.check()
        rows, cols = _grid_shape(len(inputs))
        fig = plt.figure(figsize=(4.0 * cols, 3.6 * rows))
        gs = GridSpec(rows, cols, figure=fig, hspace=0.40, wspace=0.28)

        for i, feature in enumerate(inputs):
            ax = fig.add_subplot(gs[i // cols, i % cols])
            pair = frame[[feature, result]].dropna()
            x, y = pair[feature].to_numpy(), pair[result].to_numpy()

            ax.scatter(x, y, s=16, color=_PRIMARY, alpha=0.40, edgecolors="none")
            slope, intercept = np.polyfit(x, y, 1)
            xs = np.linspace(x.min(), x.max(), 100)
            ax.plot(xs, slope * xs + intercept, color=_ACCENT, linewidth=2.0)

            r = float(np.corrcoef(x, y)[0, 1])
            ax.set_title(f"{feature}　r = {r:+.3f}", fontsize=10)
            ax.set_xlabel(feature, fontsize=9)
            ax.set_ylabel(result, fontsize=9)
            pad_ylim(ax, float(y.min()), float(y.max()))

        fig.suptitle(f"輸入變項 × {result}", fontsize=14, y=1.0)
        path = target_dir / f"scatter_{result}.png"
        save_fig(fig, path)
        paths.append(path)

    return paths


def plot_correlation(frame: pd.DataFrame, columns: list[str], out_dir: Path) -> Path:
    """3d. Pearson 與 Spearman 相關矩陣並排，固定 -1 ~ +1、coolwarm。"""
    data = frame[columns].dropna()
    pearson = data.corr(method="pearson")
    spearman = data.corr(method="spearman")
    annotate = len(columns) <= 12

    size = max(6.0, 0.62 * len(columns) + 3.2)
    fig = plt.figure(figsize=(size * 2 + 1.2, size))
    gs = GridSpec(1, 3, figure=fig, width_ratios=[1, 1, 0.045], wspace=0.22)

    ax_p = fig.add_subplot(gs[0, 0])
    ax_s = fig.add_subplot(gs[0, 1])
    cax = fig.add_subplot(gs[0, 2])

    for ax, matrix, title in ((ax_p, pearson, "Pearson"), (ax_s, spearman, "Spearman")):
        sns.heatmap(
            matrix, ax=ax, cmap="coolwarm", vmin=-1, vmax=1, center=0,
            annot=annotate, fmt=".2f", annot_kws={"size": 8},
            square=True, linewidths=0.5, linecolor="white",
            cbar=(ax is ax_s), cbar_ax=cax if ax is ax_s else None,
            cbar_kws={"ticks": [-1, -0.5, 0, 0.5, 1]},
        )
        ax.set_title(f"{title} 相關矩陣", fontsize=12)
        ax.tick_params(axis="x", rotation=45, labelsize=9)
        ax.tick_params(axis="y", rotation=0, labelsize=9)
        for label in ax.get_xticklabels():
            label.set_ha("right")

    path = out_dir / VIS_DIR / "02_correlation_matrix.png"
    save_fig(fig, path)
    return path


def plot_pairplot(frame: pd.DataFrame, columns: list[str], out_dir: Path) -> Path:
    """3e. 所有連續型欄位的 pair plot，對角線放 KDE。"""
    data = frame[columns].dropna()
    grid = sns.pairplot(
        data,
        diag_kind="kde",
        plot_kws={"s": 12, "alpha": 0.35, "color": _PRIMARY, "edgecolor": "none"},
        diag_kws={"color": _PRIMARY, "fill": True, "alpha": 0.45},
        height=1.6,
    )
    grid.figure.suptitle("連續型欄位 Pair Plot", fontsize=14, y=1.01)
    path = out_dir / VIS_DIR / "03_pair_plot.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    grid.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(grid.figure)
    return path


# --------------------------------------------------------------------------
# 5. 模型結果圖表
# --------------------------------------------------------------------------

def plot_metrics_overview(models: list[ModelResult], out_dir: Path) -> Path:
    """5b. 六項指標畫在同一張圖上，每項一個子圖、每個結果變項一根長條。

    六項指標的單位與量級完全不同（MSE 可能上百、R² 恆在 0~1），
    硬擠進同一組座標軸只會讓小的那幾根看不見，所以拆成子圖共用一張圖。
    """
    targets = [m.target for m in models]
    fig = plt.figure(figsize=(15, 8.2))
    gs = GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.28)

    x = np.arange(len(targets))
    width = 0.36

    for i, metric in enumerate(METRIC_ORDER):
        ax = fig.add_subplot(gs[i // 3, i % 3])
        in_sample = [m.metrics[metric] for m in models]
        cv = [m.cv_metrics[metric] for m in models]

        ax.bar(x - width / 2, in_sample, width, label="樣本內", color=_PRIMARY)
        ax.bar(x + width / 2, cv, width, label="5-fold 交叉驗證", color=_ACCENT, alpha=0.75)

        for pos, value in zip(x - width / 2, in_sample):
            ax.text(pos, value, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
        for pos, value in zip(x + width / 2, cv):
            if not math.isnan(value):
                ax.text(pos, value, f"{value:.3f}", ha="center", va="bottom", fontsize=8, color="#a04a05")

        arrow = "↑ 越大越好" if METRIC_HIGHER_IS_BETTER.get(metric) else "↓ 越小越好"
        ax.set_title(f"{metric}　（{arrow}）", fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(targets, fontsize=9)
        combined = [v for v in in_sample + cv if not math.isnan(v)]
        pad_ylim(ax, min(0.0, min(combined)), max(combined) * 1.12)
        if i == 0:
            ax.legend(frameon=False, fontsize=9)

    fig.suptitle("迴歸評估指標總覽", fontsize=15, y=0.98)
    path = out_dir / MODEL_DIR / "00_metrics_overview.png"
    save_fig(fig, path)
    return path


def plot_bolasso_frequency(results: list[BolassoResult], out_dir: Path) -> Path:
    """每個結果變項的變項選入頻率；達門檻者著色，未達者淡化。"""
    rows, cols = _grid_shape(len(results), max_cols=3)
    fig = plt.figure(figsize=(6.0 * cols, 4.2 * rows))
    gs = GridSpec(rows, cols, figure=fig, hspace=0.45, wspace=0.30)

    for i, res in enumerate(results):
        ax = fig.add_subplot(gs[i // cols, i % cols])
        freq = res.frequency.sort_values()
        chosen = set(res.selected)
        colors = [_PRIMARY if name in chosen else _MUTED for name in freq.index]
        alphas = [1.0 if name in chosen else 0.35 for name in freq.index]

        bars = ax.barh(range(len(freq)), freq.to_numpy(), color=colors)
        for bar, alpha in zip(bars, alphas):
            bar.set_alpha(alpha)
        for j, value in enumerate(freq.to_numpy()):
            ax.text(value + 0.015, j, f"{value:.0%}", va="center", fontsize=9)

        ax.axvline(res.threshold, color=_ACCENT, linestyle="--", linewidth=1.5,
                   label=f"門檻 {res.threshold:.0%}")
        ax.set_yticks(range(len(freq)))
        ax.set_yticklabels(freq.index, fontsize=9)
        ax.set_xlim(0, 1.14)
        ax.set_xlabel("選入頻率")
        ax.set_title(f"{res.target}　α={res.alpha:.4f}　{res.n_bootstrap} 次 bootstrap", fontsize=11)
        ax.legend(frameon=False, fontsize=9, loc="lower right")

    fig.suptitle("Bolasso 變項選入頻率", fontsize=15, y=1.0)
    path = out_dir / MODEL_DIR / "01_bolasso_selection_frequency.png"
    save_fig(fig, path)
    return path


def plot_coefficient_forest(models: list[ModelResult], out_dir: Path) -> Path:
    """係數森林圖：點估計與 95% 信賴區間，跨過 0 表示該變項不顯著。"""
    rows, cols = _grid_shape(len(models), max_cols=3)
    fig = plt.figure(figsize=(6.0 * cols, 4.2 * rows))
    gs = GridSpec(rows, cols, figure=fig, hspace=0.45, wspace=0.34)

    for i, model in enumerate(models):
        ax = fig.add_subplot(gs[i // cols, i % cols])
        table = model.coefficients[model.coefficients["變項"] != "const"].iloc[::-1]
        y = np.arange(len(table))
        coef = table["係數"].to_numpy()
        low = table["CI 下界 (95%)"].to_numpy()
        high = table["CI 上界 (95%)"].to_numpy()
        significant = table["p 值"].to_numpy() < 0.05

        ax.hlines(y, low, high, color=_MUTED, linewidth=2.0, alpha=0.65)
        ax.scatter(coef, y, s=60, zorder=3,
                   color=[_PRIMARY if s else _MUTED for s in significant])
        ax.axvline(0, color=_ACCENT, linestyle="--", linewidth=1.4)

        ax.set_yticks(y)
        ax.set_yticklabels(table["變項"], fontsize=9)
        ax.set_xlabel("迴歸係數（含 95% 信賴區間）")
        ax.set_title(f"{model.target}", fontsize=11)
        span = float(np.nanmax(high) - np.nanmin(low))
        margin = span * 0.12 if span > 0 else 1.0
        ax.set_xlim(float(np.nanmin(low)) - margin, float(np.nanmax(high)) + margin)

    fig.suptitle("迴歸係數森林圖（實心藍點 = p < 0.05）", fontsize=15, y=1.0)
    path = out_dir / MODEL_DIR / "02_coefficient_forest.png"
    save_fig(fig, path)
    return path


def plot_actual_vs_predicted(model: ModelResult, y_true: pd.Series, out_dir: Path) -> Path:
    """實際值對預測值，附 45 度參考線。點越貼近對角線，模型越準。"""
    fig, ax = plt.subplots(figsize=(6.4, 6.0))
    actual = y_true.to_numpy(float)
    pred = model.predictions.to_numpy(float)

    ax.scatter(actual, pred, s=22, color=_PRIMARY, alpha=0.45, edgecolors="none")
    lo = float(min(actual.min(), pred.min()))
    hi = float(max(actual.max(), pred.max()))
    ax.plot([lo, hi], [lo, hi], color=_ACCENT, linewidth=2.0, linestyle="--", label="完全準確 (y = x)")

    ax.set_xlabel(f"實際值　{model.target}")
    ax.set_ylabel(f"預測值　{model.target}")
    ax.set_title(
        f"{model.target}　實際 vs 預測\n"
        f"R² = {model.metrics['R²']:.4f}　RMSE = {model.metrics['RMSE']:.4f}",
        fontsize=12,
    )
    pad_ylim(ax, lo, hi)
    ax.set_xlim(ax.get_ylim())
    ax.legend(frameon=False, fontsize=9)

    path = out_dir / MODEL_DIR / f"10_actual_vs_predicted_{model.target}.png"
    save_fig(fig, path)
    return path


def plot_residual_diagnostics(model: ModelResult, out_dir: Path) -> Path:
    """殘差三連圖：殘差對配適值、Q-Q 圖、殘差分布。"""
    resid = model.residuals.to_numpy(float)
    fitted = model.predictions.to_numpy(float)

    fig = plt.figure(figsize=(15, 4.6))
    gs = GridSpec(1, 3, figure=fig, wspace=0.28)

    ax1 = fig.add_subplot(gs[0, 0])
    ax1.scatter(fitted, resid, s=20, color=_PRIMARY, alpha=0.42, edgecolors="none")
    ax1.axhline(0, color=_ACCENT, linestyle="--", linewidth=1.6)
    ax1.set_xlabel("配適值")
    # 標籤只用 ASCII 連字號：Microsoft JhengHei 沒有 U+2212 MINUS SIGN，會變成豆腐框。
    ax1.set_ylabel("殘差 (預測值 - 實際值)")
    ax1.set_title("殘差 vs 配適值　（應無明顯形狀）", fontsize=11)
    pad_ylim(ax1, float(resid.min()), float(resid.max()))

    ax2 = fig.add_subplot(gs[0, 1])
    (osm, osr), (slope, intercept, r) = stats.probplot(resid, dist="norm")
    ax2.scatter(osm, osr, s=20, color=_PRIMARY, alpha=0.5, edgecolors="none")
    ax2.plot(osm, slope * osm + intercept, color=_ACCENT, linewidth=1.8)
    ax2.set_xlabel("理論分位數")
    ax2.set_ylabel("樣本分位數")
    ax2.set_title(f"常態 Q-Q 圖　R = {r:.4f}", fontsize=11)
    pad_ylim(ax2, float(osr.min()), float(osr.max()))

    ax3 = fig.add_subplot(gs[0, 2])
    ax3.hist(resid, bins=40, density=True, color=_PRIMARY, alpha=0.45, edgecolor="white", linewidth=0.5)
    xs = np.linspace(resid.min(), resid.max(), 300)
    pdf = stats.norm.pdf(xs, resid.mean(), resid.std(ddof=1))
    ax3.plot(xs, pdf, color=_ACCENT, linewidth=2.0, label="常態擬合")
    ax3.set_xlabel("殘差")
    ax3.set_ylabel("機率密度")
    ax3.set_title("殘差分布", fontsize=11)
    pad_ylim(ax3, 0.0, float(pdf.max()))
    ax3.legend(frameon=False, fontsize=9)

    fig.suptitle(f"{model.target}　殘差診斷", fontsize=14, y=1.04)
    path = out_dir / MODEL_DIR / f"11_residual_diagnostics_{model.target}.png"
    save_fig(fig, path)
    return path
