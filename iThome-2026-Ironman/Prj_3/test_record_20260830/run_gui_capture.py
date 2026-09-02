"""Day 19 實測腳本（第三階段）：跑真正的圖形介面並截圖。

不是另做一個假畫面，而是照 mi_band_explorer_gui.main() 的流程建出同一組
Window / View / Presenter，差別只在按鈕由腳本代按（掃描 → 選裝置 → 連線
→ 列舉 GATT → 摘要），以便在無人操作的情況下截到有內容的畫面。

亮色一張、暗色一張，另外把 GATT 結構分頁單獨截一張。
"""

from __future__ import annotations

import argparse
import ctypes
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

import mi_band_explorer_gui as g  # noqa: E402

STEPS: list[str] = []


def note(text: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    STEPS.append(f"{stamp}  {text}")
    print(f"[gui] {stamp} {text}", flush=True)


def window_rect(root) -> tuple[int, int, int, int]:
    """整個視窗（含標題列與外框）的螢幕座標。"""
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
SERIAL_RE = re.compile(r"(序號: )(\S+)")


def _mask_mac(match: re.Match[str]) -> str:
    parts = match.group(0).split(":")
    return f"{parts[0]}:{parts[1]}:**:**:**:{parts[5]}"


def _mask_serial(match: re.Match[str]) -> str:
    """遮蔽序號，長度照原值算，不把真實值寫進這支腳本裡。"""
    prefix, value = match.group(1), match.group(2)
    if "*" in value:  # 已經遮過，直接回傳原樣讓替換迴圈收手
        return match.group(0)
    if len(value) <= 4:
        return prefix + "*" * len(value)
    return prefix + value[:2] + "*" * (len(value) - 4) + value[-2:]


def redact_text_widget(widget, pattern: re.Pattern[str], repl) -> None:
    """就地遮蔽 Text 內容，逐段替換以保留原本的顏色 tag。"""
    widget.config(state="normal")
    while True:
        content = widget.get("1.0", "end-1c")
        match = pattern.search(content)
        if match is None:
            break
        before = content[: match.start()]
        line = before.count("\n") + 1
        col = len(before) - (before.rfind("\n") + 1)
        start = f"{line}.{col}"
        end = f"{start}+{len(match.group(0))}c"
        tags = widget.tag_names(start)
        new = repl(match) if callable(repl) else repl
        if new == match.group(0):
            break
        widget.delete(start, end)
        widget.insert(start, new, tags)
    widget.config(state="disabled")


def redact(view) -> None:
    """截圖前遮蔽序號與 MAC 位址；資料本身沒有改，只有畫面上的呈現。"""
    redact_text_widget(view.comm_log, MAC_RE, _mask_mac)
    redact_text_widget(view.comm_log, SERIAL_RE, _mask_serial)
    for item in view.device_tree.get_children(""):
        name, address, rssi = view.device_tree.item(item, "values")
        view.device_tree.item(item, values=(name, MAC_RE.sub(_mask_mac, address), rssi))
    current = view.target_var.get().replace("Target: ", "", 1)
    view.set_target(MAC_RE.sub(_mask_mac, current))


def shoot(root, path: Path) -> None:
    # 截圖抓的是螢幕區域，被別的視窗蓋住就會拍到別人，所以先強制置頂
    root.attributes("-topmost", True)
    root.lift()
    root.update()
    root.update_idletasks()
    ImageGrab.grab(bbox=window_rect(root), all_screens=True).save(path)
    root.attributes("-topmost", False)
    note(f"截圖 {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--scan-timeout", default="20")
    args = parser.parse_args()
    outdir = Path(args.outdir)

    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(g.APP_ID)

    root = g.bs.Window(themename=g.THEME_LIGHT)
    view = g.ExplorerView(root)
    presenter = g.ExplorerPresenter(view)
    view.timeout_var.set(args.scan_timeout)

    state = {"step": 0}

    def band_item() -> str | None:
        """在裝置 Treeview 裡找出手環那一列，回傳 item id。"""
        for item in view.device_tree.get_children(""):
            values = view.device_tree.item(item, "values")
            text = " ".join(str(v) for v in values).lower()
            if any(h in text for h in ("mi band", "mi smart band", "xiaomi", "amazfit")):
                return item
        return None

    def step() -> None:
        """每 500 ms 推進一步；等待中的步驟直接重排，不阻塞 Tk 主迴圈。"""
        n = state["step"]
        try:
            if n == 0:
                note("按下 Scan")
                view.on_scan()
                state["step"] = 1
            elif n == 1:
                item = band_item()
                if presenter._busy:
                    pass
                elif item is None:
                    note("掃描完成但沒看到手環，中止")
                    state["step"] = 90
                else:
                    name = view.device_tree.item(item, "values")[0]
                    note(f"選擇裝置：{name}")
                    view.device_tree.selection_set(item)
                    view.device_tree.focus(item)
                    view._on_device_selected(None)
                    state["step"] = 2
            elif n == 2:
                note("按下 Connect")
                view.on_connect()
                state["step"] = 3
            elif n == 3:
                if not presenter._busy:
                    note("按下 Dump GATT")
                    view.on_dump_gatt()
                    state["step"] = 4
            elif n == 4:
                if not presenter._busy:
                    note("按下 Summary")
                    view.on_summary()
                    state["step"] = 5
            elif n == 5:
                if not presenter._busy:
                    redact(view)
                    shoot(root, outdir / "03_gui_light.png")
                    state["step"] = 6
            elif n == 6:
                note("切到 GATT Structure 分頁並展開")
                notebook = view.gatt_tree.master.master  # gatt_tab 的 master 就是 Notebook
                notebook.select(1)
                tree = view.gatt_tree
                for item in tree.get_children(""):
                    tree.item(item, open=True)
                    for child in tree.get_children(item)[:4]:
                        tree.item(child, open=True)
                state["step"] = 7
            elif n == 7:
                redact(view)
                shoot(root, outdir / "04_gui_gatt_tree.png")
                state["step"] = 8
            elif n == 8:
                note("切回通訊紀錄分頁，打開 Dark 開關")
                view.gatt_tree.master.master.select(0)
                view.theme_var.set(True)
                view._toggle_theme()
                state["step"] = 9
            elif n == 9:
                redact(view)
                shoot(root, outdir / "05_gui_dark.png")
                state["step"] = 10
            elif n == 10:
                note("按下 Disconnect")
                view.on_disconnect()
                state["step"] = 11
            elif n == 11:
                if not presenter._busy:
                    state["step"] = 90
            elif n == 90:
                note("關閉視窗（走 presenter.close 的五步流程）")
                log_text = MAC_RE.sub(_mask_mac, view.get_log_content())
                log_text = SERIAL_RE.sub(_mask_serial, log_text)
                (outdir / "06_gui_log.txt").write_text(log_text, encoding="utf-8")
                (outdir / "07_gui_steps.txt").write_text(
                    "\n".join(STEPS) + "\n", encoding="utf-8"
                )
                presenter.close()
                return
        except Exception as exc:  # noqa: BLE001
            note(f"步驟 {n} 例外：{exc!r}")
            state["step"] = 90
        root.after(500, step)

    root.after(800, step)
    root.mainloop()
    print("[gui] done", flush=True)


if __name__ == "__main__":
    main()
