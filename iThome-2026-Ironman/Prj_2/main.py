"""迴歸統計分析工具 — 程式進入點。

    python main.py                              開啟圖形介面
    python main.py --selftest <xlsx> <輸出目錄>   不開介面，直接跑完整條分析

--selftest 是給打包後驗收用的：光是「視窗開得起來」不代表 matplotlib 的資料檔、
python-docx 的樣板、sklearn 與 scipy 的二進位檔都有被打包進去，那些只有真的跑完
一次分析才會暴露出來。
"""

from __future__ import annotations

import sys


def _set_taskbar_identity() -> None:
    """讓 Windows 工作列顯示本程式的圖示，而不是 Python 直譯器的。

    必須在建立 root window 之前呼叫。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        from regression_app.version import APP_ID

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass  # 設不起來只是圖示不對，不該擋住程式啟動


def _selftest(xlsx: str, out_dir: str) -> int:
    """無介面跑完整條分析，回傳 0 表示成功。

    打包成 console=False 之後 sys.stdout 是 None、print 會靜靜地不做事，
    所以過程一律寫進 <輸出目錄>\\_selftest.log，成敗則靠 exit code 回報。
    """
    import traceback
    from pathlib import Path

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    log_path = target / "_selftest.log"
    log_file = log_path.open("w", encoding="utf-8")

    def say(message: str) -> None:
        print(message, flush=True)
        log_file.write(message + "\n")
        log_file.flush()

    try:
        from regression_app.model.context import RunContext
        from regression_app.model.excel_reader import load_dataset
        from regression_app.model.pipeline import run_analysis
        from regression_app.model.schema import AnalysisRequest

        dataset, issues = load_dataset(xlsx)
        for issue in issues:
            say(f"[{issue.level}] {issue.message}")
        if dataset is None:
            say("SELFTEST FAILED: 格式檢查未通過")
            return 1

        outcome = run_analysis(
            AnalysisRequest(
                dataset=dataset,
                input_names=[c.name for c in dataset.inputs],
                result_names=[c.name for c in dataset.results],
                output_dir=target,
            ),
            RunContext(on_log=lambda m: say(f"LOG   {m}"), on_stage=lambda s: say(f"STAGE {s}")),
        )

        produced = [p for p in outcome.output_dir.rglob("*") if p.is_file()]
        say(f"SELFTEST: {len(outcome.models)} 個模型、{len(produced)} 個檔案")
        missing = [
            name for name in ("Analysis_Report.docx", "Model_Report.xlsx", "Predictions.xlsx")
            if not any(p.name == name for p in produced)
        ]
        if missing:
            say(f"SELFTEST FAILED: 缺少 {'、'.join(missing)}")
            return 1
        say("SELFTEST PASSED")
        return 0
    except Exception:
        say("SELFTEST FAILED: 未預期的例外")
        say(traceback.format_exc())
        return 1
    finally:
        log_file.close()


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        if len(sys.argv) != 4:
            print("用法：--selftest <xlsx> <輸出目錄>")
            return 2
        return _selftest(sys.argv[2], sys.argv[3])

    _set_taskbar_identity()

    from regression_app.presenter.main_presenter import build_app

    build_app().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
