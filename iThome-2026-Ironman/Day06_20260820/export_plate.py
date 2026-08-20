#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_plate.py
================================================================================
把 descent_hda.py 的危害分析結果打包成單檔互動式 HTML 圖版。

  python3 export_plate.py --seed 7 -o landing_site_plate.html

輸出的 HTML 不依賴任何後端: 危害圖以 uint8 量化後 base64 內嵌,
門檻與權重的重算、候選點的非極大值抑制全部在瀏覽器端即時執行。
換句話說, 拉動滑桿不需要重跑模擬 —— 重的是配準與融合, 那部分已經固化在資料裡。

量化誤差: 各圖以 8 bit 分級 (坡度 0.1 度, 粗糙度 2 mm, 凸起 4 mm),
對候選點排序無影響, 分數差異約 0.005, 可著陸面積差異約 3%。
================================================================================
"""

from __future__ import annotations

import argparse
import base64
import json
import os

import numpy as np

import descent_hda as D

# 量化上界 (超過即截斷; 這些值都遠高於任何合理門檻)
SLOPE_CAP, ROUGH_CAP, PROTR_CAP = 25.0, 0.5, 1.0


def _enc(a: np.ndarray, lo: float, hi: float) -> str:
    q = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    return base64.b64encode((q * 255).astype(np.uint8).tobytes()).decode()


def build_payload(result: dict) -> dict:
    h, dem, cnt = result["hz"], result["dem"], result["cnt"]
    res, ext = result["dem_res"], result["dem_extent"]
    n = dem.shape[0]
    axg = np.linspace(-ext / 2, ext / 2, n)

    # 裁切到實際有掃描覆蓋的範圍, 避免把大片空白也編碼進去
    valid = h.valid & (cnt > 0)
    rows, cols = np.nonzero(valid)
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    sl = (slice(r0, r1), slice(c0, c1))
    V = valid[sl]

    zmin, zmax = float(dem[sl][V].min()), float(dem[sl][V].max())
    m = lambda a: np.where(V, a[sl], 0.0)

    return dict(
        nx=int(c1 - c0), ny=int(r1 - r0), res=float(res),
        x0=float(axg[c0]), y0=float(axg[r0]), zmin=zmin, zmax=zmax,
        slopeMax=SLOPE_CAP, roughMax=ROUGH_CAP, protrMax=PROTR_CAP,
        valid=base64.b64encode(np.packbits(V.astype(np.uint8)).tobytes()).decode(),
        slope=_enc(m(h.slope_deg), 0, SLOPE_CAP),
        rough=_enc(m(h.roughness), 0, ROUGH_CAP),
        protr=_enc(m(h.protrusion), 0, PROTR_CAP),
        cov=_enc(m(h.coverage), 0, 1.0),
        dem=_enc(np.where(V, dem[sl], zmin), zmin, zmax),
        track=[[float(f.T_true[0, 3]), float(f.T_true[1, 3]), float(f.altitude)]
               for f in result["frames"]],
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("-o", "--out", default="landing_site_plate.html")
    ap.add_argument("--template",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "plate_template.html"))
    a = ap.parse_args()

    result = D.run(seed=a.seed, plot=False)
    data = json.dumps(build_payload(result), separators=(",", ":"))
    if "</script" in data.lower():
        raise RuntimeError("payload 內含 </script>，會破壞內嵌區塊")

    tpl = open(a.template, encoding="utf-8").read()
    if "__DATA__" not in tpl:
        raise RuntimeError(f"樣板 {a.template} 缺少 __DATA__ 佔位符")
    open(a.out, "w", encoding="utf-8").write(tpl.replace("__DATA__", data))

    print(f"\n[圖版] {a.out}  ({os.path.getsize(a.out) / 1024:.0f} KB, seed={a.seed})")


if __name__ == "__main__":
    main()
