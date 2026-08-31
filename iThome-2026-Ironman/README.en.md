# iThome-2026-Ironman

[繁體中文](README.md) | English

## Overview

This folder holds the **artifacts** for my iThome 2026 Ironman Contest series, *"Three interfaces, one workflow? 30 days of cross-domain work with Claude: from claude.ai to Claude Desktop to Claude Code"*. The articles themselves are published on ithelp.ithome.com.tw (in Traditional Chinese); what lives here is everything the articles reference but cannot usefully embed: source code, Office documents, packaged `.exe` files, and screenshots.

Each day's article links to the matching folder here, and the relationship is one-way — these files are **evidence for an article**, not a product. There is no shared architecture and no unified build process; every folder stands on its own. If you want to know why a file looks the way it does, or what went wrong on the way there, the answer is in the article, not in the code.

The series runs 30 days, but only the days that need downloadable files get a folder, so the numbering has gaps. Desktop applications that span several days live under `Prj_N/` instead of being tied to one day.

If a folder ships its own `README.md`, that one is authoritative and goes into far more detail than this page. The rest are plain file drops, explained in the articles.

## Setup & run

There is no repo-wide install or build. Each folder is independent.

**Packaged executables** (Windows, no Python required):

```
.exe
```

Download and double-click. The onefile builds unpack themselves on first launch, so a few seconds of delay before the window appears is expected.

**Running the Python projects from source**:

```bash
# Prj_2 as an example; the other folders follow the same pattern
cd Prj_2
pip install -r requirements.txt
python main.py

# Run the whole pipeline headless to verify the environment
python main.py --selftest
```

The Day06 simulation has no `requirements.txt` — it only needs `numpy` / `scipy` / `matplotlib`:

```bash
cd Day06_20260820
pip install numpy scipy matplotlib
python descent_hda.py --no-plot
```

**The PowerShell scripts** (Day07) only read system information; they write nothing:

```powershell
powershell -ExecutionPolicy Bypass -File .\perf-check.ps1
powershell -ExecutionPolicy Bypass -File .\crash-check.ps1
```

Office documents, `.png` files and `.html` files just open directly; `landing_site_plate.html` works offline.

## Dependencies

They vary by folder — the authoritative lists are the `requirements.txt` files (`Prj_1/*/requirements.txt`, `Prj_2/requirements.txt`). The Python projects have been run on Windows with Python 3.12/3.13, and draw on roughly these:

- **Numerics and statistics**: numpy, scipy, pandas, scikit-learn, statsmodels
- **Plotting**: matplotlib, seaborn
- **Office read/write**: openpyxl, XlsxWriter, python-docx, python-pptx
- **Desktop UI and packaging**: ttkbootstrap, Pillow, PyInstaller

## Configuration

There is no config file, and no environment variables to set.

## License

Governed by the [MIT License](../LICENSE) at the repo root. The articles themselves remain the author's copyrighted work; the code and files here are MIT-licensed.

> Note: the stock weekly review files under `Day16_20260830/` demonstrate a "turn what was read into a deck" workflow. They summarize publicly available finance programs and are not investment advice.
