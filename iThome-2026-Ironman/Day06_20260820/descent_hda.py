#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descent_hda.py
================================================================================
太空登陸艇「下降段光學掃描 → 地形相對導航 (TRN) → 危害偵測與避讓 (HDA)」模擬

流程 (Pipeline)
--------------------------------------------------------------------------------
  [0] 合成固體行星表面真值地形 (碎形基底 + 撞擊坑 + 岩塊 + 區域傾斜)
  [1] 感測模擬
        - 軌道器先驗地圖: 稀疏、低雜訊點雲 (視為已知的 reference map)
        - 下降段光學/雷射掃描: 多幀稠密、含雜訊點雲，且導航姿態有誤差
  [2] 點雲配準 (本程式核心)
        - ICP  : point-to-plane，Gauss-Newton + Huber 強健權重
        - NDT  : 體素化高斯混合，解析梯度 + 近似 Hessian + backtracking line search
        - Hybrid: NDT 粗對位 → ICP 精對位 (實務上最穩)
  [3] 以修正後的姿態把多幀掃描融合成高解析 DEM
  [4] 危害分析: 著陸足跡內的 坡度 / 粗糙度 / 最大凸起 / 資料覆蓋率
  [5] 綜合安全評分 → 硬性約束篩選 → 選出最佳降落點 (含轉向燃料代價)
  [6] 視覺化與量化報告

執行:  python3 descent_hda.py --seed 7
       python3 descent_hda.py --no-plot        (只輸出文字報告)
       python3 descent_hda.py --sweep          (額外做初始誤差強健性掃描)

僅依賴 numpy / scipy / matplotlib。

模擬的假設與已知限制 (誠實聲明)
--------------------------------------------------------------------------------
  * 光學感測抽象化為「已還原之 3D 點雲」: 未模擬影像形成、立體匹配失敗、
    低太陽角下的長陰影與飽和、行星塵埃反光等真實光學退化。
  * 軌道器先驗地圖由同一份真值地形取樣而來, 故只含隨機雜訊、無系統性
    地圖偏差。真實 TRN 的先驗地圖本身即有數公尺級的絕對定位誤差,
    配準精度會被該誤差限制住。
  * 水平位置的可觀測性完全來自地形起伏。若降落區極度平坦 (如平滑月海),
    ICP 與 NDT 的水平方向皆會退化為病態問題, 需改用影像特徵匹配或
    都卜勒/慣性輔助。
  * 未納入下降段的即時性約束 (每幀運算需在 GNC 週期內完成)、燃料最佳化
    軌跡重規劃、光照/通訊/科學價值等任務層級的選點準則。
  * NDT 使用近似 Hessian (丟棄負定項) 並在線搜尋中重複評估分數,
    因此比 ICP 慢約一個數量級; 正式飛控實作應改用完整解析 Hessian
    與快取查表。
================================================================================
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree
from scipy import ndimage


# ==============================================================================
# 0. 幾何工具 —— SE(3) 基本運算
# ==============================================================================

def skew(v: np.ndarray) -> np.ndarray:
    """3 向量 -> 3x3 反對稱矩陣。"""
    return np.array([[0.0, -v[2], v[1]],
                     [v[2], 0.0, -v[0]],
                     [-v[1], v[0], 0.0]])


def skew_batch(V: np.ndarray) -> np.ndarray:
    """(N,3) -> (N,3,3) 反對稱矩陣。"""
    M = np.zeros((V.shape[0], 3, 3))
    M[:, 0, 1] = -V[:, 2]; M[:, 0, 2] = V[:, 1]
    M[:, 1, 0] = V[:, 2];  M[:, 1, 2] = -V[:, 0]
    M[:, 2, 0] = -V[:, 1]; M[:, 2, 1] = V[:, 0]
    return M


def so3_exp(w: np.ndarray) -> np.ndarray:
    """旋轉向量 (axis-angle) -> 旋轉矩陣 (Rodrigues)。"""
    th = float(np.linalg.norm(w))
    if th < 1e-12:
        return np.eye(3) + skew(w)
    K = skew(w / th)
    return np.eye(3) + np.sin(th) * K + (1.0 - np.cos(th)) * (K @ K)


def so3_log_angle(R: np.ndarray) -> float:
    """旋轉矩陣 -> 旋轉角 (rad)。"""
    c = (np.trace(R) - 1.0) / 2.0
    return float(np.arccos(np.clip(c, -1.0, 1.0)))


def make_T(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def transform(T: np.ndarray, P: np.ndarray) -> np.ndarray:
    """對 (N,3) 點雲套用 4x4 剛體變換。"""
    return P @ T[:3, :3].T + T[:3, 3]


def compose_increment(T: np.ndarray, delta: np.ndarray, center: np.ndarray) -> np.ndarray:
    """
    以「繞當前點雲質心 center 的局部小量」更新位姿:
        x' -> dR (x' - c) + c + dt
    這種局部參數化讓 ICP 與 NDT 共用同一組 Jacobian，且數值條件遠優於
    直接對全域 axis-angle 微分。
    delta = [dw(3), dt(3)]
    """
    dR = so3_exp(delta[:3])
    dt = delta[3:]
    A = np.eye(4)
    A[:3, :3] = dR
    A[:3, 3] = center + dt - dR @ center
    return A @ T


def pose_error(T_est: np.ndarray, T_true: np.ndarray) -> tuple[float, float]:
    """回傳 (平移誤差 m, 旋轉誤差 deg)。"""
    dT = np.linalg.inv(T_true) @ T_est
    return float(np.linalg.norm(dT[:3, 3])), float(np.degrees(so3_log_angle(dT[:3, :3])))


# ==============================================================================
# 1. 合成行星表面地形 (真值)
# ==============================================================================

@dataclass
class Terrain:
    """規則網格 DEM，座標原點在網格中心，Z 為高程 (m)。"""
    z: np.ndarray            # (n, n)
    res: float               # 網格解析度 (m/cell)
    extent: float            # 邊長 (m)

    @property
    def half(self) -> float:
        return self.extent / 2.0

    def height(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """雙線性內插取樣高程 (超出範圍以邊界值外推)。"""
        col = (x + self.half) / self.res
        row = (y + self.half) / self.res
        return ndimage.map_coordinates(self.z, [row, col], order=1, mode="nearest")


def _fractal_field(n: int, res: float, beta: float, rng: np.random.Generator) -> np.ndarray:
    """以 1/f^beta 濾波白噪聲產生碎形地形基底 (自相似的行星表面統計特性)。"""
    w = rng.normal(size=(n, n))
    F = np.fft.fft2(w)
    kx = np.fft.fftfreq(n, d=res)
    K = np.hypot(kx[:, None], kx[None, :])
    K[0, 0] = 1e-9
    F *= K ** (-beta / 2.0)
    h = np.real(np.fft.ifft2(F))
    return (h - h.mean()) / (h.std() + 1e-12)


def build_terrain(extent: float = 140.0, res: float = 0.25,
                  seed: int = 0) -> tuple[Terrain, dict]:
    """
    生成「固體行星表面」真值地形:
      - 碎形基底 (長波起伏)
      - 區域傾斜 (регional slope)
      - 撞擊坑: 碗狀凹陷 + 隆起坑緣 (對降落而言是高坡度危害)
      - 岩塊 boulders: 小半徑高突起 (對著陸腳架是致命的凸起危害)
      - 一塊人為放置的相對平坦區 (確保問題有解)
    """
    rng = np.random.default_rng(seed)
    n = int(round(extent / res)) + 1
    ax = np.linspace(-extent / 2, extent / 2, n)
    X, Y = np.meshgrid(ax, ax)

    z = 1.3 * _fractal_field(n, res, beta=3.4, rng=rng)          # 長波起伏
    z += 0.10 * _fractal_field(n, res, beta=2.4, rng=rng)        # 中頻粗糙
    z += 0.03 * X + 0.02 * Y                                     # 區域傾斜 ~2 度

    # ---- 撞擊坑 ----
    craters = []
    for _ in range(12):
        cx, cy = rng.uniform(-60, 60, 2)
        R = rng.uniform(3.0, 16.0)
        d = R * rng.uniform(0.14, 0.22)                           # 深徑比
        r = np.hypot(X - cx, Y - cy)
        bowl = -d * (1.0 - (r / R) ** 2)
        z += np.where(r < R, bowl, 0.0)
        rim = 0.28 * d * np.exp(-((r - R) / (0.35 * R)) ** 2)     # 坑緣隆起
        z += np.where(r >= 0.8 * R, rim, 0.0)
        craters.append((cx, cy, R))

    # ---- 岩塊 ----
    rocks = []
    for _ in range(130):
        cx, cy = rng.uniform(-65, 65, 2)
        rad = rng.uniform(0.25, 1.3)
        hgt = rad * rng.uniform(0.5, 1.1)
        r2 = (X - cx) ** 2 + (Y - cy) ** 2
        z += hgt * np.exp(-r2 / (0.55 * rad ** 2))
        rocks.append((cx, cy, rad, hgt))

    # ---- 保證存在一處可用的平坦著陸區 ----
    safe_c = np.array([12.0, -9.0])
    r = np.hypot(X - safe_c[0], Y - safe_c[1])
    wgt = np.clip(1.0 - (r / 9.0) ** 2, 0.0, 1.0) ** 1.5
    z = z * (1 - wgt) + ndimage.uniform_filter(z, int(9.0 / res)) * wgt

    meta = {"craters": craters, "rocks": rocks, "safe_hint": safe_c}
    return Terrain(z=z, res=res, extent=extent), meta


# ==============================================================================
# 2. 感測模擬
# ==============================================================================

def orbital_reference_cloud(terr: Terrain, spacing: float = 0.5,
                            noise: float = 0.10, half: float = 60.0,
                            rng: np.random.Generator | None = None) -> np.ndarray:
    """
    軌道器先驗地圖 (例如 LRO NAC DTM 等級):
    大範圍、規則取樣、解析度較粗、高程雜訊中等 —— 這是配準的 target。
    """
    rng = rng or np.random.default_rng(1)
    ax = np.arange(-half, half + 1e-9, spacing)
    X, Y = np.meshgrid(ax, ax)
    x, y = X.ravel(), Y.ravel()
    x = x + rng.normal(0, 0.08, x.size)      # 取樣抖動，避免完美網格造成 ICP 假鎖定
    y = y + rng.normal(0, 0.08, y.size)
    z = terr.height(x, y) + rng.normal(0, noise, x.size)
    return np.column_stack([x, y, z])


@dataclass
class ScanFrame:
    """單一幀下降段掃描結果。"""
    pts_sensor: np.ndarray      # 感測器座標系下的點雲 (N,3)
    T_true: np.ndarray          # 真值 感測器->行星固定座標 位姿
    T_nav: np.ndarray           # 導航系統的估計位姿 (含誤差，作為配準初值)
    altitude: float
    footprint_r: float


def simulate_descent(terr: Terrain, n_frames: int = 6, seed: int = 2,
                     pts_per_frame: int = 15000,
                     nav_sigma_xy: float = 3.0, nav_sigma_z: float = 1.5,
                     nav_sigma_att_deg: float = 0.25,
                     range_noise: float = 0.025) -> list[ScanFrame]:
    """
    模擬登陸艇沿下降軌跡的多幀光學/雷射掃描。

    假設: 光學感測 (flash LiDAR / 立體視覺) 的輸出已還原成感測器座標系下的 3D 點雲。
    高度越低 -> 足跡越小、點密度越高、測距雜訊越小 (符合實際 ToF 感測器行為)。
    導航 (IMU + 都卜勒雷達) 位姿隨時間累積漂移，需要靠 TRN 配準修正。
    """
    rng = np.random.default_rng(seed)
    frames: list[ScanFrame] = []

    alts = np.linspace(900.0, 250.0, n_frames)
    # 下降軌跡在水平面上斜向逼近標稱目標 (0,0)
    traj_xy = np.column_stack([np.linspace(-38, 2, n_frames),
                               np.linspace(26, -1, n_frames)])

    for k in range(n_frames):
        alt = float(alts[k])
        fp_r = 0.052 * alt                      # 半視場角 ~3 度 的地面足跡半徑
        cx, cy = traj_xy[k]

        # --- 真值位姿: 位置在標稱點正上方偏移處，姿態近乎垂直向下並帶小傾角 ---
        att = np.radians(rng.normal(0, 1.5, 3)) * np.array([1, 1, 0.6])
        R_true = so3_exp(att)
        t_true = np.array([cx, cy, terr.height(np.array([cx]), np.array([cy]))[0] + alt])
        T_true = make_T(R_true, t_true)

        # --- 地面取樣: 在足跡圓盤內以 blue-noise 近似的均勻取樣 ---
        rr = fp_r * np.sqrt(rng.uniform(0, 1, pts_per_frame))
        th = rng.uniform(0, 2 * np.pi, pts_per_frame)
        gx = cx + rr * np.cos(th)
        gy = cy + rr * np.sin(th)
        keep = (np.abs(gx) < terr.half - 1) & (np.abs(gy) < terr.half - 1)
        gx, gy = gx[keep], gy[keep]
        gz = terr.height(gx, gy)

        # 測距雜訊沿視線方向 (此處近似垂直向下)，並隨距離平方根成長
        sigma = range_noise * np.sqrt(alt / 250.0)
        gz = gz + rng.normal(0, sigma, gz.size)
        pts_world = np.column_stack([gx, gy, gz])

        # 轉回感測器座標系
        pts_sensor = (pts_world - T_true[:3, 3]) @ T_true[:3, :3]

        # --- 導航估計位姿 (帶誤差，作為 ICP/NDT 的初值) ---
        drift = 1.0 + 0.25 * k                  # 誤差隨時間累積
        dt_err = np.array([rng.normal(0, nav_sigma_xy) * drift,
                           rng.normal(0, nav_sigma_xy) * drift,
                           rng.normal(0, nav_sigma_z) * drift])
        dw_err = np.radians(rng.normal(0, nav_sigma_att_deg, 3)) * drift
        T_nav = make_T(so3_exp(dw_err) @ R_true, t_true + dt_err)

        frames.append(ScanFrame(pts_sensor, T_true, T_nav, alt, fp_r))

    return frames


# ==============================================================================
# 3-A. ICP —— Point-to-Plane，Gauss-Newton + Huber 強健權重
# ==============================================================================

def estimate_normals(P: np.ndarray, k: int = 14) -> np.ndarray:
    """以 k 近鄰局部 PCA 估計法向量，並統一朝 +Z (行星表面外法向)。"""
    tree = cKDTree(P)
    _, idx = tree.query(P, k=k, workers=-1)
    nb = P[idx]                                        # (N,k,3)
    nb = nb - nb.mean(axis=1, keepdims=True)
    C = np.einsum("nki,nkj->nij", nb, nb) / k
    _, vec = np.linalg.eigh(C)
    n = vec[:, :, 0]                                   # 最小特徵值對應的方向
    n[n[:, 2] < 0] *= -1.0
    return n


@dataclass
class RegResult:
    T: np.ndarray
    iters: int
    cost_hist: list = field(default_factory=list)
    seconds: float = 0.0
    inlier_ratio: float = 0.0
    method: str = ""


def icp_point_to_plane(src: np.ndarray, tgt: np.ndarray, tgt_normals: np.ndarray,
                       T_init: np.ndarray, max_iter: int = 60,
                       corr_dist_start: float = 8.0, corr_dist_end: float = 0.8,
                       anneal: float = 0.88, tol: float = 1e-5,
                       tgt_tree: cKDTree | None = None) -> RegResult:
    """
    Point-to-Plane ICP (含由粗到細的對應距離退火)。

    殘差:   r_i = (R p_i + t - q_i) . n_i
    以繞質心的小量 delta=[dw, dt] 線性化:
            r_i ~= r_i^0 + [ (p_i-c) x n_i , n_i ] . delta
    Gauss-Newton 正規方程:  (A^T W A) delta = -A^T W r

    對「行星表面」這種近似平面的資料, point-to-plane 比 point-to-point 收斂快
    一個數量級: 它只懲罰法線方向的偏差, 允許點沿切平面滑動, 不會被錯誤對應鎖死。

    對應距離退火 (corr_dist_start -> corr_dist_end) 等效於多解析度策略:
    初期容忍大位移以擴大收斂盆地, 後期收緊以排除錯誤對應、逼出次公尺精度。
    """
    t0 = time.perf_counter()
    tree = tgt_tree or cKDTree(tgt)
    T = T_init.copy()
    hist: list[float] = []
    it = 0
    inlier_ratio = 0.0
    cd = corr_dist_start

    for it in range(1, max_iter + 1):
        P = transform(T, src)
        dist, j = tree.query(P, k=1, workers=-1)

        m = dist < cd
        inlier_ratio = float(m.mean())
        if m.sum() < 30:
            break

        p = P[m]; q = tgt[j[m]]; n = tgt_normals[j[m]]
        r = np.einsum("ij,ij->i", p - q, n)

        # Huber 強健權重 (以 MAD 估計尺度) —— 壓制岩塊、離群點與掃描邊緣
        mad = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-6
        kh = 1.345 * mad
        ar = np.maximum(np.abs(r), 1e-9)
        w = np.where(ar <= kh, 1.0, kh / ar)

        c = p.mean(axis=0)
        A = np.hstack([np.cross(p - c, n), n])          # (M,6)
        H = A.T @ (w[:, None] * A) + 1e-9 * np.eye(6)
        g = -A.T @ (w * r)
        try:
            delta = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break

        T = compose_increment(T, delta, c)
        hist.append(float(np.sqrt(np.mean(r ** 2))))
        cd = max(corr_dist_end, cd * anneal)

        if (cd <= corr_dist_end * 1.001
                and np.linalg.norm(delta[:3]) < tol
                and np.linalg.norm(delta[3:]) < tol):
            break

    return RegResult(T=T, iters=it, cost_hist=hist,
                     seconds=time.perf_counter() - t0,
                     inlier_ratio=inlier_ratio, method="ICP (point-to-plane)")


# ==============================================================================
# 3-B. NDT —— Normal Distributions Transform
# ==============================================================================

class NDTMap:
    """
    把 target 點雲體素化，每個體素以一個 3D 高斯 N(mu, Sigma) 描述局部表面分佈。
    好處: 目標端變成連續可微的機率場，不需要每次迭代重新找最近鄰對應點，
          且對雜訊與點密度差異比 ICP 更不敏感、收斂盆地更寬。
    """

    def __init__(self, pts: np.ndarray, voxel: float = 2.0, min_pts: int = 8,
                 inflate: float = 0.0):
        """
        inflate: 各向同性共變異數膨脹量 sigma0 (m)。Sigma_eff = Sigma + sigma0^2 I

        這是本實作能讓 NDT 真正發揮「大收斂盆地」優勢的關鍵。
        近平面地形的體素高斯在法線方向極薄 (Sigma_zz ~ 0.01 m^2), 使得
        exp(-0.5 d^T Sigma^-1 d) 在數公尺初始誤差下直接下溢為 0, 梯度消失。
        膨脹等同對目標機率場做高斯平滑, 由粗到細逐級縮小 sigma0 即為退火,
        概念上與 CPD / GMMReg 的 annealing 一致。
        """
        self.voxel = voxel
        self.inflate = inflate
        origin = pts.min(axis=0) - voxel
        idx = np.floor((pts - origin) / voxel).astype(np.int64)
        key, inv = np.unique(idx, axis=0, return_inverse=True)
        cnt = np.bincount(inv, minlength=len(key))

        # 逐體素統計量
        s1 = np.zeros((len(key), 3))
        np.add.at(s1, inv, pts)
        mu = s1 / cnt[:, None]
        d = pts - mu[inv]
        s2 = np.zeros((len(key), 3, 3))
        np.add.at(s2, inv, d[:, :, None] * d[:, None, :])
        cov = s2 / np.maximum(cnt - 1, 1)[:, None, None]

        good = cnt >= min_pts
        mu, cov = mu[good], cov[good]

        # 共變異數正則化: 夾住過小的特徵值，避免近乎共平面的體素導致 Sigma 病態
        w, V = np.linalg.eigh(cov)
        wmax = w[:, -1:]
        w = np.maximum(w, 0.001 * wmax + 1e-4)
        cov = np.einsum("nij,nj,nkj->nik", V, w, V)
        if inflate > 0:
            cov = cov + (inflate ** 2) * np.eye(3)

        self.mu = mu
        self.Sinv = np.linalg.inv(cov)
        self.n = len(mu)
        self.tree = cKDTree(mu)

    def score_terms(self, P: np.ndarray, k: int = 6):
        """回傳每個 (點, 高斯) 配對的 e、Sigma^-1 d、以及點索引。"""
        _, idx = self.tree.query(P, k=k, distance_upper_bound=1.6 * self.voxel,
                                 workers=-1)
        valid = idx < self.n
        pi = np.repeat(np.arange(len(P)), k)[valid.ravel()]
        gi = idx.ravel()[valid.ravel()]
        if pi.size == 0:
            return pi, gi, np.zeros(0), np.zeros((0, 3))
        d = P[pi] - self.mu[gi]
        Sd = np.einsum("mij,mj->mi", self.Sinv[gi], d)
        e = np.exp(-0.5 * np.einsum("mi,mi->m", d, Sd))
        return pi, gi, e, Sd


def ndt_register(src: np.ndarray, ndt: NDTMap, T_init: np.ndarray,
                 max_iter: int = 16, k: int = 6, tol: float = 1e-4) -> RegResult:
    """
    最大化 score(theta) = sum_i sum_j exp(-0.5 d^T Sigma^-1 d)

    梯度:      g = sum e * (Sigma^-1 d)^T J
    近似 Hessian: H ≈ sum e * J^T Sigma^-1 J   (丟棄不定的負項，保證正定)
    J = [ -[x-c]x , I ]  (與 ICP 相同的局部參數化)
    再加上 Levenberg 阻尼與 backtracking line search 保證單調上升。
    """
    t0 = time.perf_counter()
    T = T_init.copy()
    hist: list[float] = []
    lam = 1e-3
    it = 0

    def score_of(Tx: np.ndarray) -> float:
        _, _, e, _ = ndt.score_terms(transform(Tx, src), k=k)
        return float(e.sum())

    cur = score_of(T)

    for it in range(1, max_iter + 1):
        P = transform(T, src)
        c = P.mean(axis=0)
        pi, gi, e, Sd = ndt.score_terms(P, k=k)
        if pi.size < 30:
            break

        x = P[pi] - c
        J = np.zeros((pi.size, 3, 6))
        J[:, :, :3] = -skew_batch(x)
        J[:, 0, 3] = J[:, 1, 4] = J[:, 2, 5] = 1.0

        g = np.einsum("m,ma,maj->j", e, Sd, J)                       # d(-score)/dtheta
        H = np.einsum("m,mai,mab,mbj->ij", e, J, ndt.Sinv[gi], J)
        H += lam * np.trace(H) / 6.0 * np.eye(6) + 1e-9 * np.eye(6)

        try:
            delta = -np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break

        # line search: 先回溯找到可接受步長, 再嘗試擴張。
        # 近似 Hessian 丟棄了負定項 -e*u*u^T, 會系統性高估曲率、低估步長,
        # 因此允許 step > 1 的擴張可顯著減少迭代次數。
        step, accepted = 1.0, False
        for _ in range(6):
            T_try = compose_increment(T, step * delta, c)
            s_try = score_of(T_try)
            if s_try > cur:
                T, cur, accepted = T_try, s_try, True
                lam = max(lam * 0.5, 1e-6)
                break
            step *= 0.5
        if accepted:
            for _ in range(3):
                T_try = compose_increment(T, 2.0 * step * delta, c)
                s_try = score_of(T_try)
                if s_try <= cur:
                    break
                T, cur, step = T_try, s_try, 2.0 * step
        if not accepted:
            lam *= 4.0
            if lam > 1e3:
                break
            continue

        hist.append(cur)
        d_used = step * delta
        if np.linalg.norm(d_used[:3]) < tol and np.linalg.norm(d_used[3:]) < tol:
            break

    return RegResult(T=T, iters=it, cost_hist=hist,
                     seconds=time.perf_counter() - t0,
                     inlier_ratio=1.0, method="NDT (P2D, Newton)")


def build_ndt_pyramid(ref: np.ndarray) -> list[NDTMap]:
    """由粗到細的 NDT 金字塔 (voxel, sigma0, min_pts)。"""
    cfg = [(6.0, 0.80, 30), (3.0, 0.30, 12), (1.5, 0.08, 6)]
    return [NDTMap(ref, voxel=v, min_pts=m, inflate=s) for v, s, m in cfg]


def ndt_register_multires(src: np.ndarray, maps: list[NDTMap],
                          T_init: np.ndarray) -> RegResult:
    """
    由粗到細的 NDT: 先用大體素 (寬收斂盆地、平滑的分數場) 抓住大致位移,
    再用小體素逼出精度。這是 NDT 相對 ICP 的主要優勢來源。
    """
    t0 = time.perf_counter()
    T = T_init.copy()
    hist, iters = [], 0
    for m in maps:
        r = ndt_register(src, m, T)
        T, iters = r.T, iters + r.iters
        hist.extend(r.cost_hist)
    return RegResult(T=T, iters=iters, cost_hist=hist,
                     seconds=time.perf_counter() - t0, inlier_ratio=1.0,
                     method="NDT (multi-resolution)")


# ==============================================================================
# 4. 多幀融合 -> 高解析 DEM
# ==============================================================================

def fuse_to_dem(clouds: list[np.ndarray], extent: float, res: float
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    以格點分箱把配準後的多幀點雲融合成 DEM。
    回傳 (z_mean, z_sq_mean, count)，後續危害分析全部在柵格上做，速度遠優於
    對每個候選點做 KD-tree 半徑查詢。
    """
    n = int(round(extent / res)) + 1
    half = extent / 2.0
    P = np.vstack(clouds)
    col = np.round((P[:, 0] + half) / res).astype(int)
    row = np.round((P[:, 1] + half) / res).astype(int)
    ok = (col >= 0) & (col < n) & (row >= 0) & (row < n)
    col, row, z = col[ok], row[ok], P[ok, 2]
    lin = row * n + col

    cnt = np.bincount(lin, minlength=n * n).astype(float)
    s1 = np.bincount(lin, weights=z, minlength=n * n)
    s2 = np.bincount(lin, weights=z ** 2, minlength=n * n)

    with np.errstate(invalid="ignore", divide="ignore"):
        zm = np.where(cnt > 0, s1 / np.maximum(cnt, 1), 0.0)
        zs = np.where(cnt > 0, s2 / np.maximum(cnt, 1), 0.0)
    return zm.reshape(n, n), zs.reshape(n, n), cnt.reshape(n, n)


# ==============================================================================
# 5. 危害分析 (Hazard Detection) 與安全評分
# ==============================================================================

@dataclass
class HazardMaps:
    slope_deg: np.ndarray
    roughness: np.ndarray
    protrusion: np.ndarray
    coverage: np.ndarray
    score: np.ndarray
    valid: np.ndarray


def _disk_kernels(radius_cells: int, res: float):
    """建立圓形視窗，以及帶偏移量權重的核 (供加權最小平方平面擬合用)。"""
    r = radius_cells
    o = np.arange(-r, r + 1) * res
    OX, OY = np.meshgrid(o, o)
    W = ((OX ** 2 + OY ** 2) <= (r * res) ** 2 + 1e-9).astype(float)
    return W, W * OX, W * OY, W * OX * OX, W * OX * OY, W * OY * OY


def analyze_hazards(dem: np.ndarray, dem_sq: np.ndarray, cnt: np.ndarray,
                    res: float, lander_radius: float = 2.5) -> HazardMaps:
    """
    對每個候選著陸點，取半徑 = 著陸足跡半徑的圓形視窗，做加權最小平方平面擬合:
        z ≈ a*dx + b*dy + c
    - 坡度 slope      = atan(sqrt(a^2+b^2))      -> 決定翻覆風險與推力向量
    - 粗糙度 roughness = 殘差 RMS                 -> 決定著陸腳架接觸品質
    - 最大凸起 protrusion                        -> 岩塊，會頂穿或架空登陸艇
    - 覆蓋率 coverage  = 有效格點比例             -> 感測資料是否足夠可信

    全部用 correlate 一次算完 9 個統計量，O(N * kernel)，避免逐點迴圈。
    """
    m = (cnt > 0).astype(float)
    z = np.where(cnt > 0, dem, 0.0)
    zz = np.where(cnt > 0, dem_sq, 0.0)

    rc = max(1, int(round(lander_radius / res)))
    K1, Kx, Ky, Kxx, Kxy, Kyy = _disk_kernels(rc, res)
    corr = lambda a, k: ndimage.correlate(a, k, mode="constant", cval=0.0)

    S   = corr(m, K1)
    Sx  = corr(m, Kx);   Sy  = corr(m, Ky)
    Sxx = corr(m, Kxx);  Sxy = corr(m, Kxy);  Syy = corr(m, Kyy)
    Sz  = corr(z, K1);   Sxz = corr(z, Kx);   Syz = corr(z, Ky)
    Szz = corr(zz, K1)

    ncell = K1.sum()
    valid = S >= 0.55 * ncell                      # 覆蓋率門檻

    A = np.stack([np.stack([Sxx, Sxy, Sx], -1),
                  np.stack([Sxy, Syy, Sy], -1),
                  np.stack([Sx,  Sy,  S],  -1)], -2)
    b = np.stack([Sxz, Syz, Sz], -1)
    A = A + np.eye(3) * 1e-6
    coef = np.linalg.solve(A, b[..., None])[..., 0]
    a_, b_, c_ = coef[..., 0], coef[..., 1], coef[..., 2]

    slope = np.degrees(np.arctan(np.hypot(a_, b_)))

    # 殘差平方和展開 (避免第二次卷積迴圈)
    ssr = (Szz - 2 * (a_ * Sxz + b_ * Syz + c_ * Sz)
           + a_ ** 2 * Sxx + b_ ** 2 * Syy + c_ ** 2 * S
           + 2 * (a_ * b_ * Sxy + a_ * c_ * Sx + b_ * c_ * Sy))
    rough = np.sqrt(np.maximum(ssr, 0.0) / np.maximum(S, 1e-9))

    # 最大凸起: 以「該格自身的局部擬合平面」為基準去趨勢, 再取視窗內最大值。
    # 若改用視窗均值當基準, 斜坡本身就會被誤判成 0.5 m 級的凸起 -> 全域無解。
    detr = np.where(cnt > 0, dem - c_, -1e3)
    protr = ndimage.maximum_filter(detr, footprint=K1 > 0, mode="constant", cval=-1e3)
    protr = np.maximum(protr, 0.0)

    coverage = S / ncell
    return HazardMaps(slope, rough, protr, coverage,
                      np.zeros_like(slope), valid)


def score_sites(h: HazardMaps, res: float, extent: float,
                target_xy=(0.0, 0.0),
                slope_max: float = 10.0, rough_max: float = 0.14,
                protr_max: float = 0.30, cov_min: float = 0.75,
                divert_max: float = 30.0,
                weights=(0.34, 0.26, 0.24, 0.06, 0.10)) -> HazardMaps:
    """
    綜合安全評分:
      1) 硬性約束 (任一違反 -> 分數 0): 坡度 / 粗糙度 / 凸起 / 覆蓋率
      2) 軟性評分: 各項以其上限做線性歸一，再加權；另計入轉向水平距離的燃料代價
    權重順序 = (坡度, 粗糙度, 凸起, 覆蓋率, 轉向代價)
    """
    n = h.slope_deg.shape[0]
    ax = np.linspace(-extent / 2, extent / 2, n)
    X, Y = np.meshgrid(ax, ax)
    divert = np.hypot(X - target_xy[0], Y - target_xy[1])

    feasible = (h.valid & (h.slope_deg <= slope_max) & (h.roughness <= rough_max)
                & (h.protrusion <= protr_max) & (h.coverage >= cov_min)
                & (divert <= divert_max))

    f_slope = np.clip(1 - h.slope_deg / slope_max, 0, 1)
    f_rough = np.clip(1 - h.roughness / rough_max, 0, 1)
    f_protr = np.clip(1 - h.protrusion / protr_max, 0, 1)
    f_cov = np.clip((h.coverage - cov_min) / (1 - cov_min + 1e-9), 0, 1)
    f_div = np.clip(1 - divert / divert_max, 0, 1)

    w = np.asarray(weights, float); w = w / w.sum()
    s = (w[0] * f_slope + w[1] * f_rough + w[2] * f_protr
         + w[3] * f_cov + w[4] * f_div)
    h.score = np.where(feasible, s, 0.0)
    return h


def top_sites(h: HazardMaps, extent: float, k: int = 5,
              min_sep: float = 5.0) -> list[dict]:
    """非極大值抑制式挑選: 取分數最高者，抑制其鄰域後再取次高，避免結果擠在一起。"""
    n = h.score.shape[0]
    res = extent / (n - 1)
    ax = np.linspace(-extent / 2, extent / 2, n)
    sc = h.score.copy()
    out = []
    sep = int(round(min_sep / res))
    for _ in range(k):
        i = int(np.argmax(sc))
        r, c = divmod(i, n)
        if sc[r, c] <= 0:
            break
        out.append(dict(x=float(ax[c]), y=float(ax[r]),
                        score=float(sc[r, c]),
                        slope=float(h.slope_deg[r, c]),
                        rough=float(h.roughness[r, c]),
                        protr=float(h.protrusion[r, c]),
                        cov=float(h.coverage[r, c]),
                        divert=float(np.hypot(ax[c], ax[r]))))
        r0, r1 = max(0, r - sep), min(n, r + sep + 1)
        c0, c1 = max(0, c - sep), min(n, c + sep + 1)
        sc[r0:r1, c0:c1] = 0.0
    return out


# ==============================================================================
# 6. 主流程
# ==============================================================================

def run(seed: int = 7, plot: bool = True, sweep: bool = False,
        outdir: str = ".") -> dict:
    rng = np.random.default_rng(seed)
    print("=" * 78)
    print("  登陸艇下降段 光學掃描 -> ICP/NDT 地形相對導航 -> 最佳降落點選擇")
    print("=" * 78)

    # ---- [0][1] 地形與感測 ----
    terr, meta = build_terrain(seed=seed)
    ref = orbital_reference_cloud(terr, rng=rng)
    ref_n = estimate_normals(ref)
    ref_tree = cKDTree(ref)
    ndt_maps = build_ndt_pyramid(ref)
    frames = simulate_descent(terr, seed=seed + 1)

    print(f"\n[1] 感測資料")
    print(f"    軌道器先驗地圖 : {len(ref):>7,} 點  (格距 0.5 m, sigma_z 0.10 m)")
    print("    NDT 金字塔     : " + " -> ".join(
        f"{m.n:,}體素(v={m.voxel:.0f}m, s0={m.inflate:.2f}m)" for m in ndt_maps))
    print(f"    下降掃描       : {len(frames)} 幀, 高度 "
          f"{frames[0].altitude:.0f} -> {frames[-1].altitude:.0f} m")

    # ---- [2] 逐幀配準 ----
    print(f"\n[2] 配準結果 (以 導航估計位姿 為初值, 對齊至軌道器先驗地圖)")
    print("    逐幀 地圖空間 RMSE (配準後地面點相對真值的 RMS 位移, m)")
    print(f"    {'幀':<4}{'高度m':>8}{'足跡半徑m':>11}{'導航初值':>11}"
          f"{'ICP':>10}{'NDT':>10}{'Hybrid':>10}")
    print("    " + "-" * 64)

    stats = {"ICP": [], "NDT": [], "Hybrid": []}
    map_err = {"ICP": [], "NDT": [], "Hybrid": [], "nav": []}
    fused_clouds, best_poses = [], []

    for k, f in enumerate(frames):
        # 為了配準速度，對稠密掃描做隨機降採樣 (實務上 flash LiDAR 也會做 decimation)
        sub = rng.choice(len(f.pts_sensor), size=min(4000, len(f.pts_sensor)),
                         replace=False)
        src = f.pts_sensor[sub]

        e0 = pose_error(f.T_nav, f.T_true)

        r_icp = icp_point_to_plane(src, ref, ref_n, f.T_nav, tgt_tree=ref_tree)
        src_ndt = src[rng.choice(len(src), min(1800, len(src)), replace=False)]
        r_ndt = ndt_register_multires(src_ndt, ndt_maps, f.T_nav)
        # Hybrid: NDT 收斂盆地寬 -> 先粗對位; ICP 精度高 -> 再細修
        r_hyb = icp_point_to_plane(src, ref, ref_n, r_ndt.T, tgt_tree=ref_tree,
                                   corr_dist_start=4.0, corr_dist_end=0.5)

        def map_rmse(Tx):
            """地圖空間誤差: 配準後地面點相對真值位置的 RMS 位移。
            這才是直接決定融合 DEM 是否被塗糊的量。"""
            a = transform(Tx, src); b = transform(f.T_true, src)
            return float(np.sqrt(np.mean(np.sum((a - b) ** 2, axis=1))))

        e_icp = pose_error(r_icp.T, f.T_true)
        e_ndt = pose_error(r_ndt.T, f.T_true)
        e_hyb = pose_error(r_hyb.T, f.T_true)
        m_icp, m_ndt, m_hyb = map_rmse(r_icp.T), map_rmse(r_ndt.T), map_rmse(r_hyb.T)
        map_err["ICP"].append(m_icp); map_err["NDT"].append(m_ndt)
        map_err["Hybrid"].append(m_hyb); map_err["nav"].append(map_rmse(f.T_nav))

        stats["ICP"].append((e_icp, r_icp))
        stats["NDT"].append((e_ndt, r_ndt))
        stats["Hybrid"].append((e_hyb, r_hyb))

        print(f"    {k:<4}{f.altitude:>8.0f}{f.footprint_r:>11.1f}"
              f"{map_err['nav'][-1]:>11.3f}{m_icp:>10.3f}{m_ndt:>10.3f}{m_hyb:>10.3f}")

        best_poses.append(r_hyb.T)
        fused_clouds.append(transform(r_hyb.T, f.pts_sensor))

    print("    " + "-" * 64)
    print(f"\n    {'方法':<10}{'地圖 RMSE':>11}{'位姿誤差 (@感測器)':>20}{'迭代':>7}{'耗時':>10}")
    print(f"    {'(未配準)':<10}{np.mean(map_err['nav']):>9.3f} m{'-':>20}{'-':>7}{'-':>10}")
    for name in ("ICP", "NDT", "Hybrid"):
        et = np.mean([s[0][0] for s in stats[name]])
        er = np.mean([s[0][1] for s in stats[name]])
        tt = np.mean([s[1].seconds for s in stats[name]]) * 1000
        ni = np.mean([s[1].iters for s in stats[name]])
        print(f"    {name:<10}{np.mean(map_err[name]):>9.3f} m"
              f"{et:>13.3f} m /{er:>5.2f}d{ni:>7.0f}{tt:>7.0f} ms")

    # ---- [3] 融合 ----
    dem_res, dem_ext = 0.5, 140.0
    zm, zs, cnt = fuse_to_dem(fused_clouds, dem_ext, dem_res)
    print(f"\n[3] 多幀融合 DEM: 解析度 {dem_res} m, 有效格點 "
          f"{int((cnt>0).sum()):,} ({(cnt>0).mean()*100:.1f}% of grid), "
          f"平均 {cnt[cnt>0].mean():.1f} 點/格")

    # ---- [4][5] 危害分析與選點 ----
    hz = analyze_hazards(zm, zs, cnt, dem_res, lander_radius=2.5)
    hz = score_sites(hz, dem_res, dem_ext)
    sites = top_sites(hz, dem_ext, k=5)

    print(f"\n[4] 危害判定門檻: 坡度<=10.0 deg, 粗糙度<=0.14 m, "
          f"最大凸起<=0.30 m, 覆蓋率>=75%")
    feas = (hz.score > 0)
    print(f"    可行區域面積: {feas.sum()*dem_res**2:,.0f} m^2 "
          f"({feas.sum()/max((cnt>0).sum(),1)*100:.1f}% of 掃描區)")

    print(f"\n[5] 候選降落點 (依綜合安全分數排序)")
    print(f"    {'#':<3}{'X(m)':>8}{'Y(m)':>8}{'分數':>8}{'坡度°':>8}"
          f"{'粗糙m':>8}{'凸起m':>8}{'覆蓋':>7}{'轉向m':>8}")
    print("    " + "-" * 66)
    for i, s in enumerate(sites, 1):
        print(f"    {i:<3}{s['x']:>8.2f}{s['y']:>8.2f}{s['score']:>8.3f}"
              f"{s['slope']:>8.2f}{s['rough']:>8.3f}{s['protr']:>8.3f}"
              f"{s['cov']*100:>6.0f}%{s['divert']:>8.2f}")

    if sites:
        b = sites[0]
        # 用真值地形驗證選點是否真的安全
        ax = np.linspace(-70, 70, 561)
        X, Y = np.meshgrid(ax, ax)
        r = np.hypot(X - b["x"], Y - b["y"])
        msk = r <= 2.5
        zt = terr.height(X[msk], Y[msk])
        Ad = np.column_stack([X[msk] - b["x"], Y[msk] - b["y"], np.ones(msk.sum())])
        cf, *_ = np.linalg.lstsq(Ad, zt, rcond=None)
        true_slope = np.degrees(np.arctan(np.hypot(cf[0], cf[1])))
        true_rough = float(np.std(zt - Ad @ cf))
        print(f"\n    >>> 選定降落點: ({b['x']:.2f}, {b['y']:.2f}) m")
        print(f"        真值地形驗證 -> 坡度 {true_slope:.2f} deg, "
              f"粗糙度 {true_rough:.3f} m  "
              f"(估測值 {b['slope']:.2f} deg / {b['rough']:.3f} m)")

    # ---- 強健性掃描 ----
    sweep_res = None
    if sweep:
        sweep_res = robustness_sweep(frames[2], ref, ref_n, ref_tree, ndt_maps, seed)

    if plot:
        make_figure(terr, frames, zm, cnt, hz, sites, stats, map_err, dem_ext, dem_res,
                    f"{outdir}/landing_site_selection.png")
        print(f"\n[6] 圖檔已輸出: {outdir}/landing_site_selection.png")

    return dict(terr=terr, hz=hz, sites=sites, stats=stats, sweep=sweep_res,
                dem=zm, cnt=cnt, dem_res=dem_res, dem_extent=dem_ext,
                frames=frames, map_err=map_err)


def robustness_sweep(frame: ScanFrame, ref, ref_n, ref_tree, ndt_maps, seed):
    """比較 ICP 與 NDT 對初始位姿誤差的容忍度 (收斂盆地寬度)。"""
    rng = np.random.default_rng(seed + 99)
    sub = rng.choice(len(frame.pts_sensor), 2000, replace=False)
    src = frame.pts_sensor[sub]
    levels = [2.0, 5.0, 10.0, 20.0, 35.0]
    trials = 8
    def maprmse(Tx):
        a = transform(Tx, src); b = transform(frame.T_true, src)
        return float(np.sqrt(np.mean(np.sum((a - b) ** 2, axis=1))))

    print(f"\n[*] 收斂盆地掃描 (成功判定: 地圖 RMSE < 0.3 m, 每級 {trials} 次)")
    print(f"    {'初始水平誤差(m)':>16}{'ICP 成功率':>14}{'NDT 成功率':>14}")
    out = []
    for L in levels:
        ok_i = ok_n = 0
        for _ in range(trials):
            # 固定水平誤差量值、方向隨機 -> 收斂盆地曲線乾淨且單調
            phi = rng.uniform(0, 2 * np.pi)
            dt = np.array([L * np.cos(phi), L * np.sin(phi),
                           rng.normal(0, 0.3 * L)])
            dw = np.radians(rng.normal(0, 0.25, 3))
            T0 = make_T(so3_exp(dw) @ frame.T_true[:3, :3], frame.T_true[:3, 3] + dt)
            ri = icp_point_to_plane(src, ref, ref_n, T0, tgt_tree=ref_tree,
                                    corr_dist_start=max(8.0, 2.0 * L))
            rn = ndt_register_multires(src, ndt_maps, T0)
            ok_i += maprmse(ri.T) < 0.3
            ok_n += maprmse(rn.T) < 0.3
        print(f"    {L:>16.1f}{ok_i/trials*100:>13.0f}%{ok_n/trials*100:>13.0f}%")
        out.append((L, ok_i / trials, ok_n / trials))
    return out


# ==============================================================================
# 7. 視覺化
# ==============================================================================

def make_figure(terr, frames, zm, cnt, hz, sites, stats, map_err, extent, res, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    ext = [-extent / 2, extent / 2] * 2
    ext = [-extent / 2, extent / 2, -extent / 2, extent / 2]
    mask = cnt > 0

    def hillshade(z, res, az=315, alt=45):
        gy, gx = np.gradient(z, res)
        slope = np.arctan(np.hypot(gx, gy))
        asp = np.arctan2(-gx, gy)
        a, A = np.radians(alt), np.radians(az)
        return (np.sin(a) * np.cos(slope)
                + np.cos(a) * np.sin(slope) * np.cos(A - asp))

    fig, axes = plt.subplots(2, 3, figsize=(19, 12))

    # (1) 真值地形
    ax = axes[0, 0]
    e_t = [-terr.half, terr.half, -terr.half, terr.half]
    ax.imshow(hillshade(terr.z, terr.res), extent=e_t, origin="lower",
              cmap="gray", vmin=0, vmax=1)
    ax.imshow(terr.z, extent=e_t, origin="lower", cmap="terrain", alpha=0.45)
    for f in frames:
        c = f.T_true[:3, 3]
        ax.add_patch(Circle((c[0], c[1]), f.footprint_r, fill=False,
                            ec="cyan", lw=1.0, alpha=0.8))
    tr = np.array([f.T_true[:3, 3] for f in frames])
    ax.plot(tr[:, 0], tr[:, 1], "o-", c="red", ms=4, lw=1.2, label="descent track")
    ax.set_title("(1) Ground-truth terrain + scan footprints")
    ax.legend(loc="lower left", fontsize=8)

    # (2) 融合 DEM
    ax = axes[0, 1]
    d = np.where(mask, zm, np.nan)
    im = ax.imshow(d, extent=ext, origin="lower", cmap="terrain")
    plt.colorbar(im, ax=ax, fraction=0.046, label="elevation [m]")
    ax.set_title("(2) Fused DEM from registered scans (0.5 m)")

    # (3) 坡度
    ax = axes[0, 2]
    s = np.where(hz.valid, hz.slope_deg, np.nan)
    im = ax.imshow(s, extent=ext, origin="lower", cmap="inferno", vmin=0, vmax=20)
    plt.colorbar(im, ax=ax, fraction=0.046, label="slope [deg]")
    ax.contour(np.where(hz.valid, hz.slope_deg, 99), levels=[10],
               extent=ext, colors="cyan", linewidths=1.0)
    ax.set_title("(3) Slope over 2.5 m footprint (limit 10 deg)")

    # (4) 粗糙度
    ax = axes[1, 0]
    r = np.where(hz.valid, hz.roughness, np.nan)
    im = ax.imshow(r, extent=ext, origin="lower", cmap="magma", vmin=0, vmax=0.4)
    plt.colorbar(im, ax=ax, fraction=0.046, label="RMS residual [m]")
    ax.set_title("(4) Roughness (limit 0.14 m)")

    # (5) 安全分數 + 候選點
    ax = axes[1, 1]
    sc = np.where(hz.score > 0, hz.score, np.nan)
    hs = np.where(mask, hillshade(np.where(mask, zm, 0), res), np.nan)
    ax.imshow(hs, extent=ext, origin="lower", cmap="gray", vmin=0, vmax=1)
    im = ax.imshow(sc, extent=ext, origin="lower", cmap="viridis", vmin=0.2, vmax=0.8)
    plt.colorbar(im, ax=ax, fraction=0.046, label="safety score")
    for i, s_ in enumerate(sites, 1):
        ax.add_patch(Circle((s_["x"], s_["y"]), 2.5, fill=False,
                            ec="red" if i == 1 else "orange", lw=2.0))
        ax.annotate(str(i), (s_["x"], s_["y"]), color="w", fontsize=11,
                    ha="center", va="center", weight="bold")
    ax.plot(0, 0, "w+", ms=14, mew=2)
    ax.set_title("(5) Safety score + top-5 candidate sites")

    # (6) 收斂曲線 / 誤差比較
    ax = axes[1, 2]
    idx = np.arange(len(map_err["ICP"]))
    w = 0.21
    series = [("nav", "nav (raw)", "#999999"), ("ICP", "ICP", "#4C72B0"),
              ("NDT", "NDT", "#DD8452"), ("Hybrid", "Hybrid", "#55A868")]
    for j, (key, name, col) in enumerate(series):
        ax.bar(idx + (j - 1.5) * w, map_err[key], w, label=name, color=col)
    ax.set_yscale("log")
    ax.set_xlabel("descent frame")
    ax.set_ylabel("map-space RMSE [m] (log)")
    ax.axhline(0.25, ls="--", c="k", lw=1, label="0.25 m target")
    ax.legend(fontsize=8, ncol=2)
    ax.set_title("(6) Registration accuracy in map space")

    # 把 (2)~(5) 裁切到實際掃描覆蓋範圍，避免大片空白
    rows, cols = np.nonzero(mask)
    axg = np.linspace(-extent / 2, extent / 2, mask.shape[0])
    xlim = (axg[cols.min()] - 4, axg[cols.max()] + 4)
    ylim = (axg[rows.min()] - 4, axg[rows.max()] + 4)
    for a in (axes[0, 1], axes[0, 2], axes[1, 0], axes[1, 1]):
        a.set_xlim(*xlim); a.set_ylim(*ylim); a.set_aspect("equal")
    axes[0, 0].set_aspect("equal")
    for a in axes.ravel()[:5]:
        a.set_xlabel("X [m]"); a.set_ylabel("Y [m]")

    fig.suptitle("Spacecraft Descent: Optical Scan -> ICP/NDT Terrain-Relative "
                 "Navigation -> Hazard Detection & Landing Site Selection",
                 fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=115)
    plt.close(fig)


# ==============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--sweep", action="store_true", help="做初始誤差強健性掃描")
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()
    run(seed=a.seed, plot=not a.no_plot, sweep=a.sweep, outdir=a.outdir)


if __name__ == "__main__":
    main()
