"""分析流程的總指揮。

每個階段之間都呼叫 ctx.check()，使用者按下「停止計算」後最多再跑完當下這一步就會收掉。
Bolasso 內部另外每 10 次抽樣檢查一次，因為那是整條流程裡最久的一段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from regression_app.model import report_excel, report_word, visualization as viz
from regression_app.model.bolasso import BolassoResult, run_bolasso
from regression_app.model.context import RunContext
from regression_app.model.features import build_design_matrix, drop_incomplete
from regression_app.model.modeling import ModelResult, fit_model
from regression_app.model.schema import AnalysisRequest
from regression_app.version import APP_VERSION


@dataclass
class AnalysisOutcome:
    """跑完之後回給 Presenter 的東西，主要是路徑，讓 UI 能提示產出位置。"""

    output_dir: Path
    models: list[ModelResult] = field(default_factory=list)
    bolassos: dict[str, BolassoResult] = field(default_factory=dict)
    figures: dict[str, Path] = field(default_factory=dict)
    model_report: Path | None = None
    predictions: Path | None = None
    word_report: Path | None = None


def run_analysis(request: AnalysisRequest, ctx: RunContext) -> AnalysisOutcome:
    """執行完整分析流程，回傳產出的路徑集合。"""
    viz.apply_style()

    dataset = request.dataset
    out_dir = request.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.log(f"建立輸出資料夾 {out_dir.name}")
    outcome = AnalysisOutcome(output_dir=out_dir)

    input_specs = [s for s in dataset.inputs if s.name in request.input_names]
    result_specs = [s for s in dataset.results if s.name in request.result_names]
    frame = dataset.frame

    continuous_inputs = [s.name for s in input_specs if s.is_continuous]
    continuous_results = [s.name for s in result_specs if s.is_continuous]
    continuous_all = continuous_inputs + continuous_results

    ctx.log(
        f"載入資料 {len(frame):,} 列，輸入變項 {len(input_specs)} 欄、結果變項 {len(result_specs)} 欄"
        f"（其中連續型共 {len(continuous_all)} 欄）"
    )

    _run_visualisations(frame, continuous_inputs, continuous_results, continuous_all, out_dir, ctx, outcome)

    design, _ = build_design_matrix(frame, input_specs)
    ctx.log(f"設計矩陣 {design.shape[0]:,} × {design.shape[1]} 欄（類別型已展開為 One-Hot）")

    _run_selection_and_modelling(design, frame, result_specs, request, ctx, outcome)
    _run_model_figures(frame, out_dir, ctx, outcome)
    _run_reports(dataset, request, out_dir, ctx, outcome)

    ctx.stage("完成")
    ctx.log(f"全部完成，產出位於 {out_dir}")
    return outcome


def _run_visualisations(frame, continuous_inputs, continuous_results, continuous_all, out_dir, ctx, outcome) -> None:
    total = 5

    ctx.check()
    ctx.stage(f"視覺化 1／{total}")
    outcome.figures["violin"] = viz.plot_violin(frame, continuous_all, out_dir)
    ctx.log(f"[視覺化 1/{total}] violin + box 完成（{len(continuous_all)} 子圖）")

    ctx.check()
    ctx.stage(f"視覺化 2／{total}")
    paths = viz.plot_histograms(frame, continuous_all, out_dir, ctx)
    ctx.log(f"[視覺化 2/{total}] histogram 完成（{len(paths)} 張，{viz.HIST_BINS} bins ＋ KDE 與常態擬合線）")

    ctx.check()
    ctx.stage(f"視覺化 3／{total}")
    if continuous_inputs and continuous_results:
        paths = viz.plot_scatter_matrix(frame, continuous_inputs, continuous_results, out_dir, ctx)
        ctx.log(f"[視覺化 3/{total}] scatter 完成（{len(paths)} 張，各 {len(continuous_inputs)} 子圖）")
    else:
        ctx.log(f"[視覺化 3/{total}] 略過：沒有可配對的連續型輸入或結果變項")

    ctx.check()
    ctx.stage(f"視覺化 4／{total}")
    if len(continuous_all) >= 2:
        outcome.figures["correlation"] = viz.plot_correlation(frame, continuous_all, out_dir)
        ctx.log(f"[視覺化 4/{total}] Pearson ／ Spearman 相關矩陣完成")
    else:
        ctx.log(f"[視覺化 4/{total}] 略過：連續型欄位不足 2 個")

    ctx.check()
    ctx.stage(f"視覺化 5／{total}")
    if len(continuous_all) >= 2:
        if len(continuous_all) > 12:
            ctx.log(f"[視覺化 5/{total}] 欄位有 {len(continuous_all)} 個，pair plot 會較久，請稍候")
        outcome.figures["pairplot"] = viz.plot_pairplot(frame, continuous_all, out_dir)
        ctx.log(f"[視覺化 5/{total}] pair plot 完成")
    else:
        ctx.log(f"[視覺化 5/{total}] 略過：連續型欄位不足 2 個")


def _run_selection_and_modelling(design, frame, result_specs, request, ctx, outcome) -> None:
    total = len(result_specs)

    for i, spec in enumerate(result_specs, start=1):
        ctx.check()
        label = f"[Bolasso {i}/{total}] {spec.name}　"
        ctx.stage(f"Bolasso {i}／{total}")

        X, y = drop_incomplete(design, frame[spec.name])
        if len(y) <= design.shape[1] + 2:
            ctx.log(f"{label}可用樣本僅 {len(y)} 筆，不足以配適 {design.shape[1]} 個變項，略過。")
            continue

        result = run_bolasso(
            X, y,
            n_bootstrap=request.n_bootstrap,
            threshold=request.selection_threshold,
            random_state=request.random_state,
            ctx=ctx,
            label=label,
        )
        outcome.bolassos[spec.name] = result
        ctx.log(f"{label}選入 {result.n_selected} 欄：" + "、".join(result.selected))
        if result.fallback_note:
            ctx.log(f"{label}{result.fallback_note}")

        ctx.check()
        ctx.stage(f"建模 {i}／{total}")
        model = fit_model(X, y, result.selected, random_state=request.random_state)
        outcome.models.append(model)
        ctx.log(
            f"[建模 {i}/{total}] {spec.name}　n={model.n_obs:,}　"
            f"R²={model.metrics['R²']:.4f}　Adjusted R²={model.metrics['Adjusted R²']:.4f}　"
            f"交叉驗證 R²={model.cv_metrics['R²']:.4f}"
        )


def _run_model_figures(frame, out_dir, ctx, outcome) -> None:
    if not outcome.models:
        ctx.log("沒有任何模型建立成功，略過模型圖表。")
        return

    ctx.check()
    ctx.stage("模型圖表")
    outcome.figures["metrics"] = viz.plot_metrics_overview(outcome.models, out_dir)
    ctx.log("[模型圖表] 六項指標總覽完成")

    ctx.check()
    outcome.figures["bolasso"] = viz.plot_bolasso_frequency(list(outcome.bolassos.values()), out_dir)
    ctx.log("[模型圖表] Bolasso 選入頻率完成")

    ctx.check()
    outcome.figures["forest"] = viz.plot_coefficient_forest(outcome.models, out_dir)
    ctx.log("[模型圖表] 係數森林圖完成")

    for model in outcome.models:
        ctx.check()
        truth = frame[model.target].reindex(model.predictions.index)
        outcome.figures[f"actual_{model.target}"] = viz.plot_actual_vs_predicted(model, truth, out_dir)
        outcome.figures[f"residual_{model.target}"] = viz.plot_residual_diagnostics(model, out_dir)
        ctx.log(f"[模型圖表] {model.target} 實際vs預測 與 殘差診斷完成")


def _run_reports(dataset, request, out_dir, ctx, outcome) -> None:
    if not outcome.models:
        ctx.log("沒有任何模型建立成功，不產生報表。")
        return

    ctx.check()
    ctx.stage("輸出報表")
    outcome.model_report = report_excel.write_model_report(dataset, outcome.models, outcome.bolassos, out_dir)
    ctx.log(f"[報表] {outcome.model_report.name} 完成")

    ctx.check()
    outcome.predictions = report_excel.write_predictions(dataset, outcome.models, out_dir)
    ctx.log(f"[報表] {outcome.predictions.name} 完成（每個結果變項一張工作表）")

    ctx.check()
    ctx.stage("撰寫報告")
    outcome.word_report = report_word.write_report(
        dataset, outcome.models, outcome.bolassos, outcome.figures, out_dir,
        input_names=request.input_names, app_version=APP_VERSION,
    )
    ctx.log(f"[報表] {outcome.word_report.name} 完成")
