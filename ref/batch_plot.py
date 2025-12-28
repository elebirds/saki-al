import os
import glob
import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.dates as mdates


# ==========================================
# 1. 物理常数
# ==========================================
CONSTANTS = {
    'RE': 6371.2 * 1000,         # 地球半径 (m)
    'ME': 8.0e15,                # 地球磁矩 (T·m^3)
    'QE': 1.602e-19,             # 电子电荷 (C)
    'E0_KEV': 511.0,             # 电子静止能量 (keV)
    'KEV_TO_J': 1.602e-16,       # keV -> J
    'W_COR_RAD_H': 2 * np.pi / 24.0  # 地球自转角速度 (rad/hour)
}


# ==========================================
# 2. 数据读取
# ==========================================
def parse_energy_bins(lines: list[str]) -> np.ndarray:
    try:
        energy_line = next(l for l in lines if "Energy [keV]" in l)
    except StopIteration:
        raise ValueError("未在文件头中找到 'Energy [keV]' 信息")

    content = energy_line.split("Energy [keV]")[-1]
    tokens = content.replace(',', ' ').split()
    boundaries = []
    for tok in tokens:
        try:
            boundaries.append(float(tok))
        except ValueError:
            continue

    boundaries_np = np.array(boundaries, dtype=float)
    if len(boundaries_np) < 2:
        raise ValueError("能道边界数量不足，无法计算能量中心")
    return 0.5 * (boundaries_np[:-1] + boundaries_np[1:])


def load_fedo_data(file_path: str):
    with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
        lines = f.readlines()

    e_centers = parse_energy_bins(lines)

    try:
        header_line = next(l for l in lines if l.strip().startswith("yyyy"))
    except StopIteration:
        raise ValueError("未找到表头 (yyyy...)")

    header_idx = lines.index(header_line)
    colnames = [c.strip() for c in header_line.split(',') if c.strip()]
    data_str = "".join(lines[header_idx + 1:])

    df = pd.read_csv(
        io.StringIO(data_str),
        header=None,
        names=colnames,
        sep=',',
        on_bad_lines='skip'
    )

    # 能道列
    e_cols = [c for c in df.columns if c.startswith('E_') and c[2:].isdigit()]
    min_len = min(len(e_cols), len(e_centers))
    e_cols = e_cols[:min_len]
    e_centers = e_centers[:min_len]

    # 清洗数值
    for col in e_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    for col in [c for c in df.columns if 'POS' in c or 'L_' in c]:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 时间列（这里假设一定存在 yyyy mn dd hh mm ss）
    df = df.copy()
    df['Datetime'] = pd.to_datetime(
        df[['yyyy', 'mn', 'dd', 'hh', 'mm', 'ss']].astype(str).agg('-'.join, axis=1),
        format='%Y-%m-%d-%H-%M-%S',
        errors='coerce'
    )

    return df, e_centers, e_cols


# ==========================================
# 3. 物理计算
# ==========================================
def calculate_physics_data(df, e_centers, e_cols):
    try:
        x_col = next(c for c in df.columns if 'POS_GSEx' in c)
        y_col = next(c for c in df.columns if 'POS_GSEy' in c)
        z_col = next(c for c in df.columns if 'POS_GSEz' in c)
        l_col = next(c for c in df.columns if 'L_Dipole' in c)
    except StopIteration:
        raise KeyError("关键列缺失：POS_GSEx/POS_GSEy/POS_GSEz/L_Dipole")

    r_vec = df[[x_col, y_col, z_col]].values
    l_vals = df[l_col].values
    flux_matrix = df[e_cols].values
    time_vals = df['Datetime'].values if 'Datetime' in df.columns else np.arange(len(df))

    # 过滤无效点
    mask = (l_vals >= 1.0) & np.isfinite(l_vals) & (np.linalg.norm(r_vec, axis=1) > 0) & np.isfinite(time_vals)
    l_vals = l_vals[mask]
    r_vec = r_vec[mask]
    flux_matrix = flux_matrix[mask]
    time_vals = time_vals[mask]

    # 几何因子 F(y)
    r_norm = np.linalg.norm(r_vec, axis=1)
    cos2 = np.clip(r_norm / (l_vals * CONSTANTS['RE']), 0, 1)  # ~ cos^2(lambda)
    sin2 = 1.0 - cos2
    y = ((cos2 ** 3) / np.sqrt(1 + 3 * sin2)) ** 0.5
    y_pow = y ** 0.75
    F_y = (5.520692 - 2.357194 * y + 1.279385 * y_pow) / (12 * (1.380173 - 0.639693 * y_pow))

    # 能量项
    E_J = e_centers * CONSTANTS['KEV_TO_J']
    E0_J = CONSTANTS['E0_KEV'] * CONSTANTS['KEV_TO_J']
    gamma_term = (E_J * (E_J + 2 * E0_J)) / (E_J + E0_J)

    # wd
    prefactor = (3 * CONSTANTS['RE']) / (CONSTANTS['QE'] * CONSTANTS['ME'])
    wd_matrix_rad_s = prefactor * l_vals[:, None] * gamma_term[None, :] * F_y[:, None]
    wd_matrix = wd_matrix_rad_s * 3600 + CONSTANTS['W_COR_RAD_H']

    return {
        'time': time_vals,        # (N,)
        'L': l_vals,              # (N,)
        'E': e_centers,           # (M,)
        'Flux': flux_matrix,      # (N,M)
        'Wd': wd_matrix           # (N,M)
    }


# ==========================================
# 4. pcolormesh: 中心点 -> 角点(corners) 网格
# ==========================================
def centers_to_edges_2d(Xc: np.ndarray) -> np.ndarray:
    """
    Xc: (M,N) 视为 cell centers
    return: (M+1,N+1) cell corners，用于 pcolormesh(..., shading='flat')
    """
    if Xc.ndim != 2:
        raise ValueError("centers_to_edges_2d 需要 2D 数组")

    # 列方向： (M,N) -> (M,N+1)
    mid = 0.5 * (Xc[:, :-1] + Xc[:, 1:])
    left = Xc[:, [0]] - (mid[:, [0]] - Xc[:, [0]])
    right = Xc[:, [-1]] + (Xc[:, [-1]] - mid[:, [-1]])
    Xe_col = np.hstack([left, mid, right])

    # 行方向： (M,N+1) -> (M+1,N+1)
    mid2 = 0.5 * (Xe_col[:-1, :] + Xe_col[1:, :])
    top = Xe_col[[0], :] - (mid2[[0], :] - Xe_col[[0], :])
    bottom = Xe_col[[-1], :] + (Xe_col[[-1], :] - mid2[[-1], :])
    Xe = np.vstack([top, mid2, bottom])

    return Xe


# ==========================================
# 5. 单张图绘制（可选子图、可选纯图）
# ==========================================
def plot_one_file(
    data: dict,
    which: str = "ax3",              # "ax1" | "ax2" | "ax3"
    out_path: str | None = None,
    dpi: int = 200,
    pure_image: bool = False,        # True: 无标题/坐标轴/图例/colorbar
    add_colorbar: bool = True,       # pure_image=True 时会自动忽略
    l_xlim: tuple[float, float] | None = (1.2, 1.9),
    wd_ylim: tuple[float, float] | None = (0.0, 4.0),
    cmap = "jet"
):
    which = which.lower().strip()
    if which not in {"ax1", "ax2", "ax3"}:
        raise ValueError("which 必须是 'ax1'/'ax2'/'ax3'")

    Time = data['time']
    L = data['L']
    E = data['E']
    Flux = data['Flux']
    Wd = data['Wd']

    # 颜色范围（跨能道统计）
    flux_valid = Flux[np.isfinite(Flux) & (Flux > 0)]
    if flux_valid.size < 10:
        raise ValueError("有效 Flux 太少，无法可靠设定 LogNorm 范围")
    vmin = np.nanpercentile(flux_valid, 5)
    vmax = np.nanpercentile(flux_valid, 99)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin <= 0 or vmax <= 0:
        raise ValueError("LogNorm 的 vmin/vmax 非法")
    norm = colors.LogNorm(vmin=vmin, vmax=vmax)

    # 画布：只画一个子图
    fig, ax = plt.subplots(1, 1, figsize=(6, 4), dpi=dpi)

    pcm = None

    if which == "ax1":
        pcm = ax.pcolormesh(Time, E, Flux.T, norm=norm, cmap=cmap, shading='auto')
        ax.set_yscale('log')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        if not pure_image:
            ax.set_title('Time vs Energy')
            ax.set_ylabel('Energy (keV)')
            ax.set_xlabel('Time')

    elif which == "ax2":
        pcm = ax.pcolormesh(L, E, Flux.T, norm=norm, cmap=cmap, shading='auto')
        ax.set_yscale('log')
        if l_xlim is not None:
            ax.set_xlim(*l_xlim)
        if not pure_image:
            ax.set_title('L vs Energy')
            ax.set_ylabel('Energy (keV)')
            ax.set_xlabel('L-shell')

    else:  # which == "ax3"
        # 弯曲网格：显式 corners，避免不单调导致的边界推断问题
        L_grid = np.tile(L, (len(E), 1))  # (M,N)
        Wd_grid = Wd.T                    # (M,N)
        Z_data = Flux.T                   # (M,N)

        L_edge = centers_to_edges_2d(L_grid)
        Wd_edge = centers_to_edges_2d(Wd_grid)

        pcm = ax.pcolormesh(
            L_edge, Wd_edge, Z_data,
            norm=norm, cmap=cmap,
            shading='flat',
            edgecolors='none',
            linewidth=0,
            rasterized=True
        )

        if wd_ylim is not None:
            ax.set_ylim(*wd_ylim)
        if l_xlim is not None:
            ax.set_xlim(*l_xlim)

        if not pure_image:
            ax.set_title(r'L vs $\omega_d$')
            ax.set_ylabel(r'$\omega_d$ (rad/h)')
            ax.set_xlabel('L-shell')
            ax.axhline(CONSTANTS['W_COR_RAD_H'], color='white', linestyle='--', label='Earth Corotation')
            ax.legend(loc='upper right')

    # 纯图模式：去掉一切装饰
    if pure_image:
        ax.set_axis_off()
        add_colorbar = False

    if add_colorbar and pcm is not None:
        plt.colorbar(pcm, ax=ax, label=None if pure_image else 'Flux')

    plt.tight_layout(pad=0.0 if pure_image else 1.0)

    if out_path is not None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        fig.savefig(
            out_path,
            bbox_inches='tight',
            pad_inches=0.0 if pure_image else 0.1,
            transparent=False,
            facecolor='white',
        )
        plt.close(fig)
    else:
        plt.show()


# ==========================================
# 6. 批处理：扫描文件夹、按规则、保存
# ==========================================
def default_file_filter(file_path: str) -> bool:
    """
    你可以按文件名规则筛选，比如只要包含 FEDO，或按日期段等。
    """
    name = os.path.basename(file_path)
    return ("202405" in name) and name.lower().endswith(".txt")


def batch_process(
    in_dir: str,
    out_dir: str,
    pattern: str = "*.txt",
    which: str = "ax3",
    pure_image: bool = False,
    add_colorbar: bool = True,
    dpi: int = 200,
    file_filter=default_file_filter,
    cmap: str = "jet"
):
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(in_dir, pattern)))

    if not files:
        print(f"[WARN] 没有找到文件: {os.path.join(in_dir, pattern)}")
        return

    ok, fail = 0, 0
    for fp in files:
        if file_filter is not None and (not file_filter(fp)):
            continue

        base = os.path.splitext(os.path.basename(fp))[0]
        out_name = f"{base}_{which}.png"
        out_path = os.path.join(out_dir, out_name)

        try:
            df, e_cen, e_cols = load_fedo_data(fp)
            data = calculate_physics_data(df, e_cen, e_cols)

            plot_one_file(
                data,
                which=which,
                out_path=out_path,
                dpi=dpi,
                pure_image=pure_image,
                add_colorbar=add_colorbar,
                l_xlim=(1.2, 1.9),
                wd_ylim=(0.0, 4.0),
                cmap=cmap
            )

            ok += 1
            print(f"[OK] {os.path.basename(fp)} -> {out_name}")

        except Exception as e:
            fail += 1
            print(f"[FAIL] {os.path.basename(fp)}: {e}")

    print(f"Done. ok={ok}, fail={fail}")


# ==========================================
# 7. 主程序（按需改参数）
# ==========================================
if __name__ == "__main__":
    INPUT_DIR = r"C:\Research\MSS1A_v1"
    OUTPUT_DIR = r"C:\Research\MSS1A_CON\T-E\jet"

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 只画 ax1/ax2/ax3 之一
    WHICH = "ax1"

    # 纯图（无标题/坐标/图例/colorbar）
    PURE = True

    # 如果 PURE=True，这个会自动被忽略
    ADD_COLORBAR = False

    batch_process(
        in_dir=INPUT_DIR,
        out_dir=OUTPUT_DIR,
        pattern="*.txt",
        which=WHICH,
        pure_image=PURE,
        add_colorbar=ADD_COLORBAR,
        dpi=350,
        file_filter=default_file_filter,   # 你可替换成自己的规则
        cmap="jet"
    )
