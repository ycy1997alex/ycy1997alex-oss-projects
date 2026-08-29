"""主 Presenter。

執行緒模型：分析跑在一條 daemon 工作執行緒上，所有要顯示的東西都丟進
queue.Queue，由主執行緒每 100ms 用 after() 撈出來更新畫面。
工作執行緒完全不碰任何 widget —— tkinter 不是執行緒安全的，跨執行緒動 widget
會在關閉時炸出 "main thread is not in main loop"。
"""

from __future__ import annotations

import queue
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path

from regression_app.model.context import AnalysisCancelled, RunContext
from regression_app.model.excel_reader import load_dataset
from regression_app.model.pipeline import AnalysisOutcome, run_analysis
from regression_app.model.schema import AnalysisRequest, Dataset
from regression_app.view.main_view import MainView

POLL_INTERVAL_MS = 100

# 工作執行緒收到中止訊號後，最多等這麼久讓它自己收乾淨；逾時就靠 daemon 屬性讓行程退出。
JOIN_TIMEOUT_SEC = 5.0

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


class MainPresenter:
    def __init__(self, view: MainView) -> None:
        self.view = view
        self.dataset: Dataset | None = None
        self.worker: threading.Thread | None = None
        self.ctx: RunContext | None = None
        self.queue: queue.Queue = queue.Queue()
        self._after_id: str | None = None
        self._folder_name_edited = False
        self._closing = False

        view.on_browse_input = self.handle_browse_input
        view.on_browse_output = self.handle_browse_output
        view.on_start = self.handle_start
        view.on_stop = self.handle_stop
        view.on_close_request = self.handle_close
        view.on_selection_changed = self._refresh_start_enabled
        view.reset_folder_name = self.reset_folder_name

        # 使用者親手改過資料夾名稱後，就不再自動覆寫它。
        view.entry_folder.bind("<KeyRelease>", lambda _e: self._mark_folder_edited())

        view.append_log(f"{view.root.title()} 已啟動")
        view.append_log("等待選擇輸入 Excel")
        self._schedule_poll()

    def run(self) -> None:
        try:
            self.view.root.mainloop()
        finally:
            # mainloop 因未攔截的例外或主控台強制關閉而結束時，也要把工作執行緒收掉。
            if self.ctx:
                self.ctx.cancel_event.set()

    # ------------------------------------------------------------------
    # 選檔與設定
    # ------------------------------------------------------------------

    def handle_browse_input(self, path: str) -> None:
        self.view.set_input_path(path)
        self.view.append_log(f"讀取 {Path(path).name}")

        dataset, issues = load_dataset(path)
        for issue in issues:
            self.view.append_log(f"{'⚠ ' if issue.level == 'warning' else '✕ '}{issue.message}")

        errors = [i for i in issues if i.level == "error"]
        if dataset is None:
            self.dataset = None
            self.view.clear_columns()
            self.view.set_banner(
                "error",
                f"格式不符，發現 {len(errors)} 項問題（未載入）\n"
                + "\n".join(f"· {i.message}" for i in errors),
            )
            self.view.set_stage("格式檢查未通過")
            self._refresh_start_enabled()
            return

        self.dataset = dataset
        self.view.populate_columns(dataset.inputs, dataset.results)

        n_missing = int(dataset.frame.isna().sum().sum())
        info_names = "、".join(c.name for c in dataset.infos) or "無"
        self.view.set_banner(
            "ok",
            f"格式檢查通過　·　{dataset.n_rows:,} 筆樣本　·　"
            f"{len(dataset.infos)} Info ／ {len(dataset.inputs)} Input ／ {len(dataset.results)} Result　·　"
            f"缺失值 {n_missing}　·　不參與分析：{info_names}",
        )
        self.view.append_log(
            f"角色判定：Info {len(dataset.infos)}、Input {len(dataset.inputs)}、Result {len(dataset.results)}"
        )

        self.view.set_output_dir(str(dataset.path.parent))
        self._folder_name_edited = False
        self.view.set_folder_name(self._default_folder_name())
        self.view.set_stage("就緒")
        self._refresh_start_enabled()

    def handle_browse_output(self, path: str) -> None:
        self.view.set_output_dir(path)
        self.view.append_log(f"輸出目錄設為 {path}")

    def reset_folder_name(self) -> None:
        self._folder_name_edited = False
        self.view.set_folder_name(self._default_folder_name())

    def _mark_folder_edited(self) -> None:
        self._folder_name_edited = True

    def _default_folder_name(self) -> str:
        stem = self.dataset.path.stem if self.dataset else "Data"
        return f"Output [{stem}] @{datetime.now():%Y-%m-%d %H%M%S}"

    def _refresh_start_enabled(self) -> None:
        ready = (
            self.dataset is not None
            and bool(self.view.selected_columns("input"))
            and bool(self.view.selected_columns("result"))
        )
        self.view.set_start_enabled(ready)

    # ------------------------------------------------------------------
    # 執行
    # ------------------------------------------------------------------

    def handle_start(self) -> None:
        if self.dataset is None or self._is_running():
            return

        inputs = self.view.selected_columns("input")
        results = self.view.selected_columns("result")
        if not inputs or not results:
            self.view.show_error("無法開始", "輸入變項與結果變項都至少要勾選一個。")
            return

        output_dir = self.view.get_output_dir()
        if not output_dir:
            self.view.show_error("無法開始", "請先指定輸出目錄。")
            return

        # 名稱若還是預設值，就在按下開始的當下重新產生時間戳，
        # 免得資料夾時間寫的是選檔時間而不是實際分析時間。
        if not self._folder_name_edited:
            self.view.set_folder_name(self._default_folder_name())

        folder_name = self.view.get_folder_name()
        if not folder_name:
            self.view.show_error("無法開始", "請輸入輸出資料夾名稱。")
            return
        if _INVALID_NAME_CHARS.search(folder_name):
            self.view.show_error("資料夾名稱不合法", '名稱不能包含這些字元： < > : " / \\ | ? *')
            return

        target = Path(output_dir) / folder_name
        if target.exists() and any(target.iterdir()):
            if not self.view.ask_yes_no(
                "資料夾已存在",
                f"「{folder_name}」已經存在而且裡面有東西。\n\n繼續執行會覆蓋同名檔案。要繼續嗎？",
            ):
                return

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.view.show_error("無法建立輸出資料夾", str(exc))
            return

        request = AnalysisRequest(
            dataset=self.dataset,
            input_names=inputs,
            result_names=results,
            output_dir=target,
        )

        self.ctx = RunContext(
            cancel_event=threading.Event(),
            on_log=lambda msg: self.queue.put(("log", msg)),
            on_stage=lambda text: self.queue.put(("stage", text)),
        )

        self.view.set_running(True)
        self.view.set_stage("開始分析")
        self.view.append_log("─" * 40)
        self.view.append_log(f"開始分析：輸入 {len(inputs)} 欄、結果 {len(results)} 欄")

        self.worker = threading.Thread(
            target=self._run_worker, args=(request, self.ctx), name="analysis-worker", daemon=True
        )
        self.worker.start()

    def _run_worker(self, request: AnalysisRequest, ctx: RunContext) -> None:
        """工作執行緒本體。只能把結果丟進 queue，不能碰任何 widget。"""
        try:
            outcome = run_analysis(request, ctx)
            self.queue.put(("done", outcome))
        except AnalysisCancelled:
            self.queue.put(("cancelled", None))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def handle_stop(self) -> None:
        if not self._is_running() or self.ctx is None:
            return
        self.ctx.cancel_event.set()
        self.view.set_stop_enabled(False)   # 防連按
        self.view.set_stage("停止中…")
        self.view.append_log("已送出停止訊號，等待目前這一步跑完後收尾…")

    def _is_running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    # ------------------------------------------------------------------
    # 佇列輪詢
    # ------------------------------------------------------------------

    def _schedule_poll(self) -> None:
        self._after_id = self.view.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _poll_queue(self) -> None:
        if self._closing:
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.view.append_log(payload)
                elif kind == "stage":
                    self.view.set_stage(payload)
                elif kind == "done":
                    self._on_finished(payload)
                elif kind == "cancelled":
                    self._on_cancelled()
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self._schedule_poll()

    def _on_finished(self, outcome: AnalysisOutcome) -> None:
        self.view.set_running(False, can_start=True)
        self.view.set_stage("完成")
        self._refresh_start_enabled()
        self.view.show_info(
            "分析完成",
            f"共建立 {len(outcome.models)} 個迴歸模型。\n\n產出位於：\n{outcome.output_dir}",
        )

    def _on_cancelled(self) -> None:
        self.view.set_running(False, can_start=True)
        self.view.set_stage("已停止")
        self.view.append_log("分析已由使用者中止。已產生的檔案保留在輸出資料夾中，但內容不完整。")
        self._refresh_start_enabled()

    def _on_error(self, detail: str) -> None:
        self.view.set_running(False, can_start=True)
        self.view.set_stage("發生錯誤")
        for line in detail.strip().splitlines():
            self.view.append_log(line)
        self._refresh_start_enabled()
        self.view.show_error("分析失敗", f"分析過程發生未預期的錯誤，詳細內容已寫入分析紀錄。\n\n{detail.strip().splitlines()[-1]}")

    # ------------------------------------------------------------------
    # 關閉
    # ------------------------------------------------------------------

    def handle_close(self) -> None:
        if self._is_running():
            stage = self.view.label_stage.cget("text")
            if not self.view.ask_yes_no(
                "分析尚未結束",
                "分析正在執行中，確定要關閉嗎？\n\n"
                "關閉後會立刻中止分析，已產生的圖表與報表會留在輸出資料夾中，但內容不完整。\n\n"
                f"目前進度：{stage}",
            ):
                return
            self._closing = True
            if self.ctx:
                self.ctx.cancel_event.set()
            self.view.set_stage("中止中…")
            self.view.append_log("正在中止分析並關閉程式…")
        self._destroy()

    def _destroy(self) -> None:
        """關閉順序：先停掉 after 迴圈，再收工作執行緒，最後才 destroy 視窗。"""
        self._closing = True

        if self._after_id is not None:
            try:
                self.view.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

        if self.ctx:
            self.ctx.cancel_event.set()

        if self.worker is not None and self.worker.is_alive():
            # 卡在某個長運算裡就等不到；worker 是 daemon，行程仍能正常退出。
            self.worker.join(timeout=JOIN_TIMEOUT_SEC)

        try:
            self.view.root.destroy()
        except Exception:
            pass


def build_app() -> MainPresenter:
    """組裝 MVP 三層。main.py 只需要呼叫這個。"""
    return MainPresenter(MainView())
