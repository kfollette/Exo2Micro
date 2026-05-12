"""
legacy.py
=========
Deprecated functions retained for backward compatibility only.

Do not use these in new code; they may be removed in a future version.
Use the corresponding functions from the main exo2micro modules instead.
"""

import os
import glob
import numpy as np
import cv2
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

from .utils import equalize_pair


# ==============================================================================
# DEPRECATED FILE I/O
# ==============================================================================

def compile_ims_old(target_ch, ref_ch, dirname='./', name_str=''):
    """
    .. deprecated::
        Use load_image_pair() from exo2micro.utils instead.

    Given a directory of .tif image files, read them into arrays.
    Assumes a target channel and variable reference channels.

    Parameters
    ----------
    target_ch : str
        Single 2-digit string for the target channel, e.g. '00'.
    ref_ch : list of str
        List of 2-digit strings for reference channels, e.g. ['01', '02'].
    dirname : str
        Directory containing the images (default './').
    name_str : str
        Partial filename string to select a specific set (default '').

    Returns
    -------
    target_fname, ref_fnames, target_im, ref_ims
    """
    import warnings
    warnings.warn(
        "compile_ims_old is deprecated. Use exo2micro.utils.load_image_pair() "
        "instead.", DeprecationWarning, stacklevel=2)

    target_fname = glob.glob(
        dirname + "*" + name_str + '*ch' + target_ch + '*.tif')
    ref_fnames = []
    for ch in ref_ch:
        ref_file = glob.glob(
            dirname + "*" + name_str + '*ch' + ch + '*.tif')
        ref_fnames.append(ref_file)

    tgim = Image.open(target_fname[0]).convert("L")
    target_im = np.array(tgim)
    imsz = target_im.shape

    ref_ims = np.zeros([imsz[0], imsz[1], len(ref_ch)])
    for i, ch in enumerate(ref_ch):
        rfim = Image.open(ref_fnames[i][0]).convert("L")
        ref_ims[:, :, i] = np.array(rfim)

    return target_fname, ref_fnames, target_im, ref_ims


# ==============================================================================
# DEPRECATED SUBTRACTION
# ==============================================================================

def residuals_collapsed(scale, post_im, pre_im):
    """
    .. deprecated::
        Use optimize_subtraction() from exo2micro.scaling instead.

    Subtract a scaled pre-stain image and return residuals as 1D array.

    Parameters
    ----------
    scale : float
    post_im, pre_im : ndarray

    Returns
    -------
    ndarray
    """
    import warnings
    warnings.warn(
        "residuals_collapsed is deprecated. Use exo2micro.scaling."
        "optimize_subtraction() instead.", DeprecationWarning, stacklevel=2)
    return (post_im - scale * pre_im).ravel()


# ==============================================================================
# DEPRECATED MASKING
# ==============================================================================

def mask_em(red):
    """
    .. deprecated::
        Use exo2micro.utils.build_tissue_mask() instead.

    Create a binary mask: 1.0 where red > 0, NaN elsewhere.

    Parameters
    ----------
    red : ndarray

    Returns
    -------
    ndarray
    """
    import warnings
    warnings.warn(
        "mask_em is deprecated. Use exo2micro.utils.build_tissue_mask() "
        "instead.", DeprecationWarning, stacklevel=2)
    return np.where(red > 0, 1.0, np.nan)


def maskandsave(blue_img, red_img, green_img, sub00, sub02):
    """
    .. deprecated::
        Use the SampleDye pipeline for output management instead.

    Apply mask and save processed images to Analyzed_Images/.

    Parameters
    ----------
    blue_img, red_img, green_img : str
        Filename strings for channel TIFFs.
    sub00, sub02 : ndarray
        Processed channel images.
    """
    import warnings
    warnings.warn(
        "maskandsave is deprecated. Use the SampleDye pipeline instead.",
        DeprecationWarning, stacklevel=2)

    path = os.getcwd()
    out_folder = "Analyzed_Images"
    os.makedirs(os.path.join(path, out_folder), exist_ok=True)

    blue_fname = blue_img.split('/')[1]
    prefix = blue_fname.split('_')[0]

    if sub02 is not None and sub00 is not None:
        mask = np.zeros((512, 512))
        mask[:, :] = sub00[:, :]
        sub02[mask == 0] = 0
        combined = sub00 + sub02
        comp = Image.fromarray(combined.astype(np.uint8))
        comp.save(os.path.join(path, out_folder, f"{prefix}comp.tif"))

    if sub00 is not None:
        pro00 = Image.fromarray(sub00.astype(np.uint8))
        pro00.save(os.path.join(path, out_folder, f"{prefix}pro00.tif"))

    if sub02 is not None:
        pro02 = Image.fromarray(sub02.astype(np.uint8))
        pro02.save(os.path.join(path, out_folder, f"{prefix}pro02.tif"))


# ==============================================================================
# DEPRECATED REGISTRATION
# ==============================================================================

def register_loworder(post_im, pre_im, stopit=500, stopdelta=1e-6,
                      down_scale=0.5, save_prefix=None):
    """
    .. deprecated::
        Use register_highorder() from exo2micro.alignment instead,
        which handles both low-order and high-order registration.

    Register using Euclidean (rotation + translation) motion model via ECC.

    Parameters
    ----------
    post_im, pre_im : ndarray
    stopit : int
    stopdelta : float
    down_scale : float
    save_prefix : str or None

    Returns
    -------
    post_full, pre_aligned : ndarray
    """
    import warnings
    warnings.warn(
        "register_loworder is deprecated. Use exo2micro.alignment."
        "register_highorder() instead.", DeprecationWarning, stacklevel=2)

    warp_mode = cv2.MOTION_EUCLIDEAN
    warp_matrix = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                stopit, stopdelta)

    post_full = post_im.astype(np.float32)
    pre_full = pre_im.astype(np.float32)

    scale = down_scale
    post_small = cv2.resize(post_full, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA)
    pre_small = cv2.resize(pre_full, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_AREA)

    post_eq, pre_eq = equalize_pair(post_small, pre_small)

    cc, warp_matrix = cv2.findTransformECC(
        post_eq, pre_eq, warp_matrix, warp_mode, criteria)

    warp_matrix[0, 2] /= scale
    warp_matrix[1, 2] /= scale

    h, w = post_full.shape
    pre_aligned = cv2.warpAffine(
        pre_full, warp_matrix, (w, h),
        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

    cos_theta = warp_matrix[0, 0]
    sin_theta = warp_matrix[1, 0]
    angle_deg = np.degrees(np.arctan2(sin_theta, cos_theta))
    tx = warp_matrix[0, 2]
    ty = warp_matrix[1, 2]

    print("\n=== Euclidean Alignment Results ===")
    print(f"Rotation angle : {angle_deg:8.4f} degrees")
    print(f"X shift (dx)   : {tx:8.2f} pixels")
    print(f"Y shift (dy)   : {ty:8.2f} pixels")
    print("===================================\n")

    return post_full, pre_aligned


# ==============================================================================
# DEPRECATED PLOTTING FUNCTIONS (moved from plotting.py in v2.2)
# ==============================================================================

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter


def _tissue_boundary_contour(ax, post_im):
    """Overplot the tissue boundary (post_im > 0 edge) as yellow contour."""
    tissue = (post_im > 0).astype(np.float32)
    if tissue.max() == 0:
        return
    h, w = tissue.shape
    ax.contour(np.arange(w), np.arange(h), tissue,
               levels=[0.5], colors=['#ffee00'],
               linewidths=[0.8], alpha=0.7)


def _diff_colorbars(diffim, diffim_rob, post):
    """
    Compute colorbar limits for LS and robust difference panels.

    Returns
    -------
    sv : float
        Symmetric half-range for LS diverging colorbar.
    rob_vmax : float or None
    rob_vmin : float or None
    """
    diff_px = diffim[post > 0]
    sv = float(np.percentile(np.abs(diff_px), 90)) if len(diff_px) > 0 else 1.0

    rob_vmax = rob_vmin = None
    if diffim_rob is not None:
        rob_px = diffim_rob[post > 0]
        rob_vmax = (float(np.percentile(np.abs(rob_px), 90))
                    if len(rob_px) > 0 else 1.0)
        rob_vmin = -rob_vmax * 0.05

    return sv, rob_vmax, rob_vmin


def _image_stretch_params(post):
    """
    Compute shared log-asinh stretch parameters from post-stain pixels.

    Returns
    -------
    knee, im_vmin, im_vmax : float
    """
    post_px = post[post > 0]
    if len(post_px) > 0:
        knee = max(float(np.percentile(post_px, 10)), 0.5)
        post_s = np.arcsinh(np.clip(post, 0, None) / knee)
        post_px_s = post_s[post > 0]
        im_vmin = float(np.percentile(post_px_s, 10))
        im_vmax = float(np.percentile(post_px_s, 99))
    else:
        knee, im_vmin, im_vmax = 1.0, 0.0, 1.0
    return knee, im_vmin, im_vmax


def plot_ratio_histogram(plot_data, save_path=None):
    """
    Diagnostic histogram of post/pre ratio distribution.

    Parameters
    ----------
    plot_data : dict
        Data from optimize_subtraction (plot_data output).
    save_path : str or None
        If set, save to this path.

    Returns
    -------
    fig : matplotlib.Figure
    """
    from scipy.optimize import curve_fit as _curve_fit

    log_r = plot_data['ratio_log']
    opt_scale = plot_data['opt_scale']
    ls_scale = plot_data['ls_scale']
    scale_sig = plot_data['scale_sig']
    n_hist_bins = plot_data['n_hist_bins']
    sample = plot_data['sample']
    dye = plot_data['dye']

    r_lo = float(log_r.min())
    r_hi = float(log_r.max())
    prefix = _title_prefix(sample, dye)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(log_r, bins=n_hist_bins, range=(r_lo, r_hi),
            color='#7b4fa6', edgecolor='none', alpha=0.85)

    # Scale lines
    ax.axvline(np.log10(opt_scale), color='red', linewidth=2,
               label=f'chosen scale = {opt_scale:.3f}')
    ax.axvline(np.log10(ls_scale), color='orange', linewidth=2,
               linestyle='--', label=f'LS scale = {ls_scale:.3f}')
    if scale_sig is not None:
        ax.axvline(np.log10(scale_sig), color='#00cc88', linewidth=2,
                   linestyle=':', label=f'sig-LS scale = {scale_sig:.3f}')

    # Diagnostic percentile markers
    r_plot = 10 ** log_r
    diag_percentiles = [10, 25, 50, 75, 90]
    diag_colors = ['#c6dbef', '#6baed6', '#2171b5', '#08519c', '#08306b']
    for pct, col in zip(diag_percentiles, diag_colors):
        val = float(np.percentile(r_plot, pct))
        ax.axvline(np.log10(val), color=col, linewidth=1.2,
                   linestyle=':', label=f'pctile{pct} = {val:.3f}')

    # Gaussian noise estimate via peak mirroring
    counts_c, edges_c = np.histogram(log_r, bins=20, range=(r_lo, r_hi))
    bin_c = (edges_c[:-1] + edges_c[1:]) / 2.0
    pb_c = int(np.argmax(counts_c))
    lo_bc = max(pb_c - 3, 0)
    hi_bc = min(pb_c + 4, len(bin_c))
    try:
        cf2 = np.polyfit(bin_c[lo_bc:hi_bc],
                         counts_c[lo_bc:hi_bc].astype(float), 2)
        peak_x = (float(-cf2[1] / (2.0 * cf2[0]))
                  if cf2[0] < 0 else float(bin_c[pb_c]))
        peak_x = float(np.clip(peak_x, bin_c[lo_bc], bin_c[hi_bc - 1]))
    except Exception:
        peak_x = float(bin_c[pb_c])

    counts_f, edges_f = np.histogram(log_r, bins=n_hist_bins,
                                      range=(r_lo, r_hi))
    bin_f = (edges_f[:-1] + edges_f[1:]) / 2.0
    left_mask = bin_f <= peak_x
    xf_left = bin_f[left_mask]
    yf_left = counts_f[left_mask].astype(float)
    xf_mirror = 2.0 * peak_x - xf_left
    yf_mirror = yf_left.copy()
    xf = np.concatenate([xf_left, xf_mirror])
    yf = np.concatenate([yf_left, yf_mirror])

    if len(xf) > 5 and yf.max() > 0:
        def _gauss(x, amp, mu, sig):
            return amp * np.exp(-0.5 * ((x - mu) / sig) ** 2)
        p0 = [float(yf.max()), peak_x, float((peak_x - r_lo) / 2.0)]
        try:
            popt, _ = _curve_fit(_gauss, xf, yf, p0=p0, maxfev=5000)
            amp_fit, mu_fit, sig_fit = popt
            sig_fit = abs(sig_fit)
            x_curve = np.linspace(r_lo, r_hi, 500)
            y_curve = _gauss(x_curve, amp_fit, mu_fit, sig_fit)
            ax.plot(x_curve, y_curve, color='#888888', linewidth=2,
                    linestyle='-', zorder=3)
            ax.fill_between(x_curve, y_curve, alpha=0.55,
                            color='#666666', zorder=2,
                            label='noise estimate')
            ax.scatter(xf_left, yf_left, color='#ff9500', s=10,
                       alpha=0.9, zorder=5,
                       label='fit bins (left of peak)')
            ax.scatter(xf_mirror, yf_mirror, color='#ffcc00', s=10,
                       alpha=0.7, zorder=5, marker='^',
                       label='mirrored bins')
        except Exception:
            pass

    tick_vals = np.linspace(r_lo, r_hi, 9)
    ax.set_xticks(tick_vals)
    ax.set_xticklabels([f'{10**v:.2f}' for v in tick_vals], fontsize=8)
    ax.set_xlabel('post / pre pixel ratio  (log\u2081\u2080 scale)', fontsize=10)
    ax.set_ylabel('pixel count', fontsize=10)
    ax.set_title(
        f'{prefix}post/pre ratio distribution  (n={len(log_r):,} pixels)',
        fontsize=10)
    ax.legend(fontsize=9)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig



def plot_residual_histogram(plot_data, save_path=None):
    """
    Post-subtraction residual histogram comparing LS and robust methods.

    Parameters
    ----------
    plot_data : dict
        Data from optimize_subtraction.
    save_path : str or None
        If set, save to this path.

    Returns
    -------
    fig : matplotlib.Figure or None
    """
    prefix = _title_prefix(plot_data['sample'], plot_data['dye'])

    diff_ls_all = plot_data['diff_ls_all']
    diff_rob_all = plot_data['diff_rob_all']
    diff_ls_opt = plot_data['diff_ls_opt']
    diff_rob_opt = plot_data['diff_rob_opt']
    ls_scale = plot_data['ls_scale']
    opt_scale = plot_data['opt_scale']
    n_hist_bins = plot_data['n_hist_bins']

    if len(diff_ls_all) == 0:
        print("  residual histogram: no tissue pixels — skipping")
        return None

    combined = np.concatenate([diff_ls_all, diff_rob_all])
    d_lo = float(np.percentile(combined, 0.5))
    d_hi = float(np.percentile(combined, 99.5))

    fig, ax = plt.subplots(figsize=(9, 4))
    fig.suptitle(f'{prefix}post-subtraction residual distribution', fontsize=12)

    col_ls = '#2196a0'
    col_rob = '#e05c2a'

    ax.hist(diff_ls_all, bins=n_hist_bins, range=(d_lo, d_hi),
            histtype='step', color=col_ls, linewidth=1.5, alpha=0.9,
            label=f'LS all tissue  (n={plot_data["n_ls_all"]:,}, '
                  f'scale={ls_scale:.3f})')
    ax.hist(diff_ls_opt, bins=n_hist_bins, range=(d_lo, d_hi),
            color=col_ls, edgecolor='none', alpha=0.35,
            label=f'LS opt pixels  (n={plot_data["n_ls_opt"]:,})')

    ax.hist(diff_rob_all, bins=n_hist_bins, range=(d_lo, d_hi),
            histtype='step', color=col_rob, linewidth=1.5, alpha=0.9,
            label=f'Robust all tissue  (n={plot_data["n_rob_all"]:,}, '
                  f'scale={opt_scale:.3f})')
    ax.hist(diff_rob_opt, bins=n_hist_bins, range=(d_lo, d_hi),
            color=col_rob, edgecolor='none', alpha=0.35,
            label=f'Robust opt pixels  (n={plot_data["n_rob_opt"]:,})')

    ax.axvline(0, color='black', linewidth=1.2, linestyle='--', label='zero')
    ax.set_yscale('log')
    ax.set_xlabel('post \u2212 scale \u00d7 pre  (intensity)', fontsize=10)
    ax.set_ylabel('pixel count (log scale)', fontsize=10)
    ax.legend(fontsize=8)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig



def plot_signal_scatter(post_im, pre_im, scale_ls, scale_sig, scale_robust,
                        tissue_mask, signal_percentile=50,
                        n_points=100_000, sample='', dye='',
                        save_path=None):
    """
    Diagnostic scatter plot of post vs pre brightness.

    Shows scale lines for LS, signal-only LS, and robust methods
    on a log-log density plot.

    Parameters
    ----------
    post_im, pre_im : ndarray
        Post-stain and aligned pre-stain images.
    scale_ls : float
        LS scale over all tissue pixels.
    scale_sig : float or None
        LS scale over signal-only pixels.
    scale_robust : float
        Robust scale.
    tissue_mask : ndarray of bool
        Tissue mask.
    signal_percentile : float
        Percentile threshold shown as dashed lines (default 50).
    n_points : int
        Number of points to display (default 100000).
    sample, dye : str
        For title.
    save_path : str or None
        If set, save to this path.

    Returns
    -------
    fig : matplotlib.Figure or None
    """
    post = post_im.astype(np.float64)
    pre = pre_im.astype(np.float64)

    flat_post = post[tissue_mask]
    flat_pre = pre[tissue_mask]

    valid = (flat_post > 0) & (flat_pre > 0)
    flat_post = flat_post[valid]
    flat_pre = flat_pre[valid]

    if len(flat_post) > n_points:
        idx = np.argpartition(flat_post, -n_points)[-n_points:]
        flat_post = flat_post[idx]
        flat_pre = flat_pre[idx]

    if len(flat_post) < 10:
        print("  plot_signal_scatter: too few valid pixels — skipping")
        return None

    log_post = np.log10(flat_post)
    log_pre = np.log10(flat_pre)

    # 2-D density colouring
    h2d, xedges, yedges = np.histogram2d(log_pre, log_post, bins=200)
    xi = np.clip(np.searchsorted(xedges[1:], log_pre), 0, h2d.shape[0] - 1)
    yi = np.clip(np.searchsorted(yedges[1:], log_post), 0, h2d.shape[1] - 1)
    density = h2d[xi, yi]
    order = np.argsort(density)
    log_pre_s = log_pre[order]
    log_post_s = log_post[order]
    density_s = density[order]
    norm_d = density_s / (density_s.max() + 1e-8)

    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(7, 6))

    sc = ax.scatter(log_pre_s, log_post_s, c=norm_d,
                    cmap='viridis', s=1, alpha=0.6, linewidths=0,
                    rasterized=True)
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label('relative local density', fontsize=9)

    x_min = float(log_pre_s.min())
    x_max = float(log_pre_s.max())
    xline = np.array([x_min, x_max])

    col_ls = '#2196a0'
    col_sig = '#00cc88'
    col_rob = '#e05c2a'

    ax.plot(xline, xline + np.log10(scale_ls), color=col_ls,
            linewidth=1.8, linestyle='-',
            label=f'LS all-tissue  (scale={scale_ls:.3f})')
    if scale_sig is not None:
        ax.plot(xline, xline + np.log10(scale_sig), color=col_sig,
                linewidth=1.8, linestyle='--',
                label=f'LS signal-only  (scale={scale_sig:.3f})')
    ax.plot(xline, xline + np.log10(scale_robust), color=col_rob,
            linewidth=1.8, linestyle=':',
            label=f'Robust p{signal_percentile}  (scale={scale_robust:.3f})')

    # Signal threshold lines
    all_post_tissue = post[tissue_mask & (post > 0)]
    all_pre_tissue = pre[tissue_mask & (pre > 0)]
    if len(all_post_tissue) > 0:
        post_thr = float(np.percentile(all_post_tissue, signal_percentile))
        ax.axhline(np.log10(post_thr), color='white', linewidth=1.0,
                   linestyle='--', alpha=0.7,
                   label=f'post p{signal_percentile} threshold')
    if len(all_pre_tissue) > 0:
        pre_thr = float(np.percentile(all_pre_tissue, signal_percentile))
        ax.axvline(np.log10(pre_thr), color='lightgrey', linewidth=1.0,
                   linestyle='--', alpha=0.7,
                   label=f'pre p{signal_percentile} threshold')

    ax.plot(xline, xline, color='grey', linewidth=0.8, linestyle='-',
            alpha=0.4, label='scale = 1  (identity)')

    def _log_formatter(val, pos):
        return f'{10**val:.3g}'
    ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(_log_formatter))
    ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(_log_formatter))

    ax.set_xlabel('pre-stain brightness  (log scale)', fontsize=11)
    ax.set_ylabel('post-stain brightness  (log scale)', fontsize=11)
    ax.set_title(
        f'{prefix}pre vs post brightness  '
        f'(top {len(flat_post):,} post-stain pixels)',
        fontsize=10)
    ax.legend(fontsize=8, loc='upper left')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig


# ==============================================================================
# DIFFERENCE IMAGE PLOTS
# ==============================================================================


def plot_im_sub(post_im, pre_im, scale, comp=None, scale_robust=None,
                sample='', dye=''):
    """
    Subtract a scaled pre-stain image and display panels.

    Parameters
    ----------
    post_im, pre_im : ndarray
        Post-stain and aligned pre-stain images.
    scale : float
        Least-squares scale factor.
    comp : ndarray or None
        Comparison image.
    scale_robust : float or None
        If set, add robust subtraction panels.
    sample, dye : str
        For title.

    Returns
    -------
    fig : matplotlib.Figure
    diff_im : ndarray
        LS difference image.
    """
    post = post_im.astype(np.float32)
    pre = pre_im.astype(np.float32)

    pre_scaled = pre * scale
    diffim = post - pre_scaled

    diffim_rob = None
    if scale_robust is not None:
        pre_scaled_rob = pre * scale_robust
        diffim_rob = post - pre_scaled_rob

    bg_mask = (post == 0)

    # Shared stretch
    post_px = post[post > 0]
    knee = max(float(np.percentile(post_px, 10)), 0.5) if len(post_px) > 0 else 1.0

    def _stretch(im):
        s = np.arcsinh(np.clip(im, 0, None) / knee)
        s = s.copy()
        s[bg_mask] = np.nan
        return s

    post_s = _stretch(post)
    pre_ls_s = _stretch(pre_scaled)
    if scale_robust is not None:
        pre_rob_s = _stretch(pre_scaled_rob)
        pool = np.concatenate([post_s[np.isfinite(post_s)],
                               pre_ls_s[np.isfinite(pre_ls_s)],
                               pre_rob_s[np.isfinite(pre_rob_s)]])
    else:
        pre_rob_s = None
        pool = np.concatenate([post_s[np.isfinite(post_s)],
                               pre_ls_s[np.isfinite(pre_ls_s)]])

    im_vmin = float(np.percentile(pool, 10)) if len(pool) > 0 else 0.0
    im_vmax = float(np.percentile(pool, 90)) if len(pool) > 0 else 1.0

    im_cmap = _make_inferno_cmap()
    div_cmap = _make_diverging_cmap()
    im_label = f'asinh(intensity / {knee:.1f})'

    sv, rob_vmax, rob_vmin = _diff_colorbars(diffim, diffim_rob, post)

    diff_ls_masked = diffim.copy().astype(np.float32)
    diff_ls_masked[bg_mask] = np.nan

    if diffim_rob is not None:
        diffim_rob_masked = diffim_rob.copy().astype(np.float32)
        diffim_rob_masked[bg_mask] = np.nan

    n_panels = 3
    if scale_robust is not None:
        n_panels += 2
    if comp is not None:
        n_panels += 1
    fig, axs = plt.subplots(1, n_panels, figsize=(7 * n_panels, 7))

    def _add_panel(ax, im, vmin, vmax, cmap, title, label, ann=None):
        img = ax.imshow(im, vmin=vmin, vmax=vmax, cmap=cmap,
                        interpolation='nearest')
        div = make_axes_locatable(ax)
        cb_ax = div.append_axes('right', size='5%', pad=0.05)
        cb = fig.colorbar(img, cax=cb_ax)
        cb.set_label(label, fontsize=9)
        ax.set_title(title, fontsize=11, pad=8)
        _tissue_boundary_contour(ax, post_im)
        if ann is not None:
            ax.text(0.02, 0.97, ann, color='white', fontsize=11,
                    ha='left', va='top', transform=ax.transAxes,
                    bbox=dict(boxstyle='round,pad=0.3', fc='#333333', alpha=0.7))
        ax.axis('off')

    ax_idx = 0
    _add_panel(axs[ax_idx], post_s, im_vmin, im_vmax,
               im_cmap, 'Post-Stain (log-asinh)', im_label)
    ax_idx += 1

    _add_panel(axs[ax_idx], pre_ls_s, im_vmin, im_vmax,
               im_cmap, 'Pre-Stain LS-scaled (log-asinh)', im_label,
               ann=f'scale={scale:.2f}')
    ax_idx += 1

    _add_panel(axs[ax_idx], diff_ls_masked, -sv, sv,
               div_cmap, 'Post \u2212 LS\u00d7Pre', 'intensity')
    ax_idx += 1

    if scale_robust is not None:
        _add_panel(axs[ax_idx], pre_rob_s, im_vmin, im_vmax,
                   im_cmap, 'Pre-Stain Robust-scaled (log-asinh)', im_label,
                   ann=f'scale={scale_robust:.2f}')
        ax_idx += 1

        _add_panel(axs[ax_idx], diffim_rob_masked, rob_vmin, rob_vmax,
                   im_cmap, 'Post \u2212 Robust\u00d7Pre', 'intensity')
        ax_idx += 1

    if comp is not None:
        comp_masked = comp.copy().astype(np.float32)
        comp_masked[bg_mask] = np.nan
        _add_panel(axs[ax_idx], comp_masked, -sv, sv,
                   div_cmap, 'Comparison Image', 'intensity')

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    prefix = _title_prefix(sample, dye)
    if prefix:
        fig.suptitle(prefix.rstrip('  —  '), fontsize=12, y=0.98)
    return fig, diffim



def plot_diff_comparison(post_im, pre_im, scale_ls, scale_robust,
                         title='', sig_mask=None, sample='', dye=''):
    """
    Two-panel comparison of LS and robust difference images.

    Parameters
    ----------
    post_im, pre_im : ndarray
    scale_ls, scale_robust : float
    title : str
    sig_mask : ndarray or None (retained for API compatibility)
    sample, dye : str

    Returns
    -------
    fig, diff_ls, diff_rob
    """
    post = post_im.astype(np.float32)
    pre = pre_im.astype(np.float32)

    diff_ls = post - pre * scale_ls
    diff_rob = post - pre * scale_robust

    bg_mask = (post == 0)
    sv, rob_vmax, rob_vmin = _diff_colorbars(diff_ls, diff_rob, post)

    diff_ls_masked = diff_ls.copy()
    diff_ls_masked[bg_mask] = np.nan
    diff_rob_masked = diff_rob.copy()
    diff_rob_masked[bg_mask] = np.nan

    div_cmap = _make_diverging_cmap()
    inf_cmap = _make_inferno_cmap()

    prefix = _title_prefix(sample, dye)
    full_title = f'{prefix}{title}' if title else prefix.rstrip('  —  ')

    fig, axs = plt.subplots(1, 2, figsize=(20, 10))

    def _diff_panel(ax, im, vmin, vmax, cmap, panel_title, cb_label, ann):
        img = ax.imshow(im, vmin=vmin, vmax=vmax, cmap=cmap,
                        interpolation='nearest')
        div = make_axes_locatable(ax)
        cb = fig.colorbar(img, cax=div.append_axes('right', size='3%', pad=0.05))
        cb.set_label(cb_label, fontsize=11)
        ax.set_title(panel_title, fontsize=13, pad=8)
        _tissue_boundary_contour(ax, post_im)
        ax.text(0.02, 0.98, ann, color='white', fontsize=12,
                ha='left', va='top', transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=0.3', fc='black', alpha=0.5))
        ax.axis('off')

    _diff_panel(axs[0], diff_ls_masked, -sv, sv, div_cmap,
                'Post \u2212 LS\u00d7Pre', 'intensity', f'scale={scale_ls:.3f}')
    _diff_panel(axs[1], diff_rob_masked, rob_vmin, rob_vmax, inf_cmap,
                'Post \u2212 Robust\u00d7Pre', 'intensity', f'scale={scale_robust:.3f}')

    if full_title:
        fig.suptitle(full_title, fontsize=14, y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    return fig, diff_ls, diff_rob



def plot_stretch_comparison(post_im, pre_im, scale_ls, scale_robust,
                            title='', sample='', dye=''):
    """
    4-row x 2-column grid comparing stretch methods on LS and robust diffs.

    Rows: asinh, signed log, global z-score, local z-score.
    Columns: LS (diverging cmap), Robust (inferno cmap).

    Parameters
    ----------
    post_im, pre_im : ndarray
    scale_ls, scale_robust : float
    title : str
    sample, dye : str

    Returns
    -------
    fig : matplotlib.Figure
    """
    post = post_im.astype(np.float32)
    pre = pre_im.astype(np.float32)

    diff_ls = post - pre * scale_ls
    diff_rob = post - pre * scale_robust

    bg_mask = (post == 0)
    tissue_px = post > 0

    div_cmap = _make_diverging_cmap()
    inf_cmap = _make_inferno_cmap()

    def _nan_mask(im):
        out = im.copy()
        out[bg_mask] = np.nan
        return out

    def _asinh_stretch(diff):
        px = diff[tissue_px]
        knee = max(float(np.percentile(np.abs(px), 10)), 0.5) if len(px) > 0 else 1.0
        return np.arcsinh(diff / knee), f'asinh(diff / {knee:.1f})'

    def _log_stretch(diff):
        return np.sign(diff) * np.log10(np.abs(diff) + 1), 'sign \u00d7 log\u2081\u2080(|diff|+1)'

    def _global_zscore(diff):
        px = diff[tissue_px]
        mu = float(np.mean(px)) if len(px) > 0 else 0.0
        std = float(np.std(px)) if len(px) > 0 else 1.0
        std = max(std, 1e-8)
        return (diff - mu) / std, 'global z-score'

    def _local_zscore(diff, sigma=20):
        d = diff.copy()
        d[bg_mask] = 0.0
        w = tissue_px.astype(np.float32)
        local_mean = gaussian_filter(d * w, sigma=sigma) / (
            gaussian_filter(w, sigma=sigma) + 1e-8)
        local_sq = gaussian_filter(d**2 * w, sigma=sigma) / (
            gaussian_filter(w, sigma=sigma) + 1e-8)
        local_std = np.sqrt(np.clip(local_sq - local_mean**2, 0, None)) + 1e-8
        return (diff - local_mean) / local_std, f'local z-score (\u03c3={sigma}px)'

    stretches = [_asinh_stretch, _log_stretch, _global_zscore, _local_zscore]
    row_labels = ['asinh', 'signed log\u2081\u2080', 'global z-score', 'local z-score']

    prefix = _title_prefix(sample, dye)
    full_title = f'{prefix}{title}' if title else prefix.rstrip('  —  ')
    fig, axs = plt.subplots(4, 2, figsize=(16, 28))
    if full_title:
        fig.suptitle(full_title, fontsize=13, y=1.005)

    for row, (stretch_fn, row_label) in enumerate(zip(stretches, row_labels)):
        for col, (diff, scale_val, cmap, col_label) in enumerate([
            (diff_ls, scale_ls, div_cmap, 'LS'),
            (diff_rob, scale_robust, inf_cmap, 'Robust'),
        ]):
            ax = axs[row, col]
            stretched, cb_label = stretch_fn(diff)
            stretched_m = _nan_mask(stretched)

            px_s = stretched_m[tissue_px & np.isfinite(stretched_m)]
            if col == 0:
                abs_s = np.abs(px_s)
                sv_s = (max(float(np.median(abs_s) + 2 * np.median(
                             np.abs(abs_s - np.median(abs_s)))),
                             float(np.percentile(abs_s, 50)))
                         if len(abs_s) > 0 else 1.0)
                vmin_s, vmax_s = -sv_s, sv_s
            else:
                stretched_m = np.where(stretched_m < 0, 0.0, stretched_m)
                pos_s = px_s[px_s > 0]
                vmax_s = float(np.percentile(pos_s, 99)) if len(pos_s) > 0 else 1.0
                vmin_s = -vmax_s * 0.05

            img = ax.imshow(stretched_m, vmin=vmin_s, vmax=vmax_s,
                            cmap=cmap, interpolation='nearest')
            div_ax = make_axes_locatable(ax)
            cb = fig.colorbar(img,
                              cax=div_ax.append_axes('right', size='5%', pad=0.05))
            cb.set_label(cb_label, fontsize=8)
            _tissue_boundary_contour(ax, post_im)
            ax.set_title(f'{col_label}  (scale={scale_val:.3f})  —  {row_label}',
                         fontsize=10, pad=6)
            ax.axis('off')

    plt.tight_layout()
    return fig



def plot_zoom_region(post_im, pre_im, scale_ls, scale_robust,
                     sig_mask=None, box_size=300, title='',
                     sample='', dye=''):
    """
    Zoom into the densest signal region and compare LS vs robust subtraction.

    Parameters
    ----------
    post_im, pre_im : ndarray
    scale_ls, scale_robust : float
    sig_mask : ndarray or None
    box_size : int
    title : str
    sample, dye : str

    Returns
    -------
    fig, r0, c0
    """
    from scipy.ndimage import uniform_filter

    post = post_im.astype(np.float32)
    pre = pre_im.astype(np.float32)

    density_src = (sig_mask.astype(np.float32) if sig_mask is not None
                   else (post > 0).astype(np.float32))

    h, w = post.shape
    if h < box_size or w < box_size:
        print(f"  plot_zoom_region: image ({h}\u00d7{w}) smaller than "
              f"box_size={box_size} — skipping")
        return None, 0, 0

    density = uniform_filter(density_src, size=box_size, mode='constant')
    peak = np.unravel_index(np.argmax(density), density.shape)
    r0 = int(np.clip(peak[0] - box_size // 2, 0, h - box_size))
    c0 = int(np.clip(peak[1] - box_size // 2, 0, w - box_size))
    r1, c1 = r0 + box_size, c0 + box_size

    crop_post = post[r0:r1, c0:c1]
    crop_pre = pre[r0:r1, c0:c1]
    diff_ls = crop_post - crop_pre * scale_ls
    diff_rob = crop_post - crop_pre * scale_robust

    bg_mask_crop = (crop_post == 0)
    sv, rob_vmax_val, rob_vmin_val = _diff_colorbars(diff_ls, diff_rob, crop_post)

    diff_ls_m = diff_ls.copy()
    diff_ls_m[bg_mask_crop] = np.nan
    diff_rob_m = diff_rob.copy()
    diff_rob_m[bg_mask_crop] = np.nan

    div_cmap = _make_diverging_cmap()
    inf_cmap = _make_inferno_cmap()

    prefix = _title_prefix(sample, dye)
    zoom_title = f'{prefix}Zoom  rows {r0}:{r1}, cols {c0}:{c1}'
    if title:
        zoom_title = f'{prefix}{title}  —  Zoom  rows {r0}:{r1}, cols {c0}:{c1}'

    fig, axs = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle(zoom_title, fontsize=12)

    def _zpanel(ax, im, vmin, vmax, cmap, panel_title, ann):
        img = ax.imshow(im, vmin=vmin, vmax=vmax, cmap=cmap,
                        interpolation='nearest')
        div_ax = make_axes_locatable(ax)
        cb = fig.colorbar(img,
                          cax=div_ax.append_axes('right', size='5%', pad=0.05))
        cb.set_label('intensity', fontsize=9)
        ax.set_title(panel_title, fontsize=11, pad=6)
        _tissue_boundary_contour(ax, crop_post)
        ax.text(0.02, 0.97, ann, color='white', fontsize=10,
                ha='left', va='top', transform=ax.transAxes,
                bbox=dict(boxstyle='round,pad=0.3', fc='black', alpha=0.5))
        ax.axis('off')

    _zpanel(axs[0], diff_ls_m, -sv, sv,
            div_cmap, 'Post \u2212 LS\u00d7Pre', f'scale={scale_ls:.3f}')
    _zpanel(axs[1], diff_rob_m, rob_vmin_val, rob_vmax_val,
            inf_cmap, 'Post \u2212 Robust\u00d7Pre', f'scale={scale_robust:.3f}')

    plt.tight_layout()
    return fig, r0, c0




# ==============================================================================
# LEGACY SCALING  (moved from scaling.py in v2.3.0)
# ==============================================================================
#
# These functions implement the old LS / robust-percentile scale estimation
# approach. They are no longer called by the v2.3 pipeline (which uses a
# Moffat fit on the ratio distribution, plus optional user-specified
# scale_percentile and manual_scale overrides), but are retained here for
# anyone who wants the old behaviour or is reproducing older results.
#
# Use `exo2micro.SampleDye` with `scale_percentile=<float>` for the
# percentile-based workflow in the new pipeline.

import numpy as _np_scaling
from scipy.ndimage import binary_fill_holes as _bfh_scaling
from scipy.ndimage import binary_erosion as _berode_scaling


def optimize_subtraction(post_im, pre_im,
                         method='least_squares',
                         percentile=None,
                         n_hist_bins=100,
                         noise_floor_percentile=5,
                         boundary_erosion=50,
                         mask=None,
                         signal_percentile=50,
                         plot_ratio_hist=False,
                         sample='',
                         dye='',
                         save_prefix=None):
    """
    .. deprecated:: 2.3
        Moved from ``exo2micro.scaling`` into ``exo2micro.legacy`` and no
        longer used by the main pipeline. Use
        ``SampleDye(scale_percentile=...)`` for the equivalent
        percentile-based workflow in the current pipeline.

    Compute a pre-stain scale factor for subtraction.

    Parameters
    ----------
    post_im, pre_im : ndarray
        Post-stain and registered pre-stain images (2-D).
    method : str
        ``'least_squares'`` or ``'robust_percentile'`` (default
        ``'least_squares'``).
    percentile : int or None
        For ``robust_percentile``: ``None`` = histogram mode, int =
        use that percentile of the log-ratio distribution.
    n_hist_bins : int
        Histogram bins for the log-ratio distribution (default 100).
    noise_floor_percentile : float
        Pixels below this percentile of post_im are excluded (default 5).
    boundary_erosion : int
        Erode the signal mask by this many pixels (default 50).
    mask : ndarray or None
        Optional boolean base mask.
    signal_percentile : float
        Bright-in-both percentile (default 50).
    plot_ratio_hist : bool
        If True, also return a data dict for plotting (default False).
    sample, dye : str
        Labels for plots.
    save_prefix : str or None
        If set, save diagnostic figures to disk.

    Returns
    -------
    opt_scale : float
    scale_sig : float or None
    tissue_mask_out : ndarray of bool
    plot_data : dict or None
    """
    post = post_im.astype(_np_scaling.float64)
    pre = pre_im.astype(_np_scaling.float64)

    tissue_mask_out = _bfh_scaling(post > 0) & _bfh_scaling(pre > 0)

    if mask is not None:
        sig_mask = mask.astype(bool) & (post > 0) & (pre > 0)
    else:
        sig_mask = tissue_mask_out.copy()

    if boundary_erosion > 0:
        k = boundary_erosion * 2 + 1
        struct = _np_scaling.ones((k, k), dtype=bool)
        sig_mask = _berode_scaling(sig_mask, structure=struct, iterations=1)

    post_sig = post[sig_mask]
    pre_sig = pre[sig_mask]

    if len(post_sig) < 100:
        post_sig = post[post > 0].ravel()
        pre_sig = pre[post > 0].ravel()
        print("  optimize_subtraction: mask too aggressive — "
              "using all signal pixels")

    plot_data = None

    if method == 'robust_percentile':
        with _np_scaling.errstate(divide='ignore', invalid='ignore'):
            ratio = _np_scaling.where(pre_sig > 0, post_sig / pre_sig,
                                      _np_scaling.nan)
        ratio = ratio[_np_scaling.isfinite(ratio) & (ratio > 0)]

        if len(ratio) == 0:
            print("  optimize_subtraction: no valid ratios — "
                  "falling back to least_squares")
            opt_scale = float(_np_scaling.dot(post_sig, pre_sig) /
                              _np_scaling.dot(pre_sig, pre_sig))
        elif percentile is not None:
            opt_scale = float(_np_scaling.percentile(ratio, percentile))
            print(f"  opt_scale (robust p{percentile}): {opt_scale:.4f}  "
                  f"(n_pixels={len(ratio):,})")
        else:
            r_fit = (ratio if len(ratio) <= 2_000_000 else
                     ratio[_np_scaling.random.choice(len(ratio),
                                                     2_000_000,
                                                     replace=False)])
            log_r = _np_scaling.log10(r_fit)
            r_lo = float(log_r.min())
            r_hi = float(log_r.max())
            counts, edges = _np_scaling.histogram(log_r, bins=n_hist_bins,
                                                  range=(r_lo, r_hi))
            from scipy.ndimage import uniform_filter1d
            counts_smooth = uniform_filter1d(counts.astype(float), size=5)
            bin_centres = (edges[:-1] + edges[1:]) / 2.0

            ls_log = _np_scaling.log10(
                float(_np_scaling.dot(post_sig, pre_sig) /
                      _np_scaling.dot(pre_sig, pre_sig)))
            peak_bin = int(_np_scaling.argmax(counts_smooth))
            if bin_centres[peak_bin] < ls_log - 1.0:
                window = _np_scaling.abs(bin_centres - ls_log) <= 1.0
                if window.any():
                    peak_bin = int(_np_scaling.argmax(
                        counts_smooth * window.astype(float)))

            lo_b = max(peak_bin - 5, 0)
            hi_b = min(peak_bin + 6, len(bin_centres))
            xp = bin_centres[lo_b:hi_b]
            yp = counts_smooth[lo_b:hi_b]
            try:
                coeffs = _np_scaling.polyfit(xp, yp, 2)
                if coeffs[0] < 0:
                    log_mode = float(-coeffs[1] / (2.0 * coeffs[0]))
                    log_mode = float(_np_scaling.clip(
                        log_mode, bin_centres[lo_b], bin_centres[hi_b - 1]))
                else:
                    log_mode = float(bin_centres[peak_bin])
            except Exception:
                log_mode = float(bin_centres[peak_bin])
            opt_scale = float(10 ** log_mode)
            print(f"  opt_scale (robust mode): {opt_scale:.4f}  "
                  f"(n_pixels={len(ratio):,})")

        ls_scale = float(_np_scaling.dot(post_sig, pre_sig) /
                         _np_scaling.dot(pre_sig, pre_sig))

        post_thresh = (float(_np_scaling.percentile(post[tissue_mask_out],
                                                    signal_percentile))
                       if tissue_mask_out.any() else 0.0)
        pre_thresh = (float(_np_scaling.percentile(pre[tissue_mask_out],
                                                   signal_percentile))
                      if tissue_mask_out.any() else 0.0)
        sig_both_mask = (tissue_mask_out
                         & (post > post_thresh)
                         & (pre > pre_thresh))
        if sig_both_mask.sum() >= 100:
            post_sig2 = post[sig_both_mask]
            pre_sig2 = pre[sig_both_mask]
            scale_sig = float(_np_scaling.dot(post_sig2, pre_sig2) /
                              _np_scaling.dot(pre_sig2, pre_sig2))
            print(f"  scale_sig (LS signal-only p{signal_percentile}): "
                  f"{scale_sig:.4f}  (n={sig_both_mask.sum():,})")
        else:
            scale_sig = ls_scale
            print("  scale_sig: signal mask too small — using ls_scale")

        if plot_ratio_hist and len(ratio) > 0:
            plot_data = _build_histogram_data(
                post, pre, ratio, opt_scale, ls_scale, scale_sig,
                tissue_mask_out, sig_mask, n_hist_bins, signal_percentile,
                sample, dye)

    else:
        opt_scale = float(_np_scaling.dot(post_sig, pre_sig) /
                          _np_scaling.dot(pre_sig, pre_sig))
        print(f"  opt_scale (least_squares): {opt_scale:.4f}  "
              f"(n_pixels={len(post_sig):,})")
        scale_sig = None

    return opt_scale, scale_sig, tissue_mask_out, plot_data


def _build_histogram_data(post, pre, ratio, opt_scale, ls_scale, scale_sig,
                          tissue_mask_out, sig_mask, n_hist_bins,
                          signal_percentile, sample, dye):
    """
    .. deprecated:: 2.3
        Companion to the legacy ``optimize_subtraction``. Builds the data
        dict consumed by the old histogram/residual plotting functions.
    """
    r_plot = (ratio if len(ratio) <= 500_000 else
              ratio[_np_scaling.random.choice(len(ratio), 500_000,
                                              replace=False)])

    tm_flat = tissue_mask_out.ravel()
    post_tm = post.ravel()[tm_flat]
    pre_tm = pre.ravel()[tm_flat]
    diff_ls_all = post_tm - pre_tm * ls_scale
    diff_rob_all = post_tm - pre_tm * opt_scale

    if sig_mask.any():
        diff_ls_opt = post[sig_mask] - pre[sig_mask] * ls_scale
    else:
        diff_ls_opt = diff_ls_all

    with _np_scaling.errstate(divide='ignore', invalid='ignore'):
        ratio_tm = _np_scaling.where(pre_tm > 0, post_tm / pre_tm,
                                     _np_scaling.nan)
    opt_px = _np_scaling.isfinite(ratio_tm) & (ratio_tm <= opt_scale)
    diff_rob_opt = (diff_rob_all[opt_px] if opt_px.any() else diff_rob_all)

    def _subsample(arr, n=500_000):
        if len(arr) <= n:
            return arr
        return arr[_np_scaling.random.choice(len(arr), n, replace=False)]

    zoom_data = None
    if sig_mask.any():
        from scipy.ndimage import uniform_filter
        _BOX = 300
        h_im, w_im = sig_mask.shape
        if h_im >= _BOX and w_im >= _BOX:
            density = uniform_filter(sig_mask.astype(_np_scaling.float32),
                                     size=_BOX, mode='constant')
            peak = _np_scaling.unravel_index(_np_scaling.argmax(density),
                                             density.shape)
            r0 = int(_np_scaling.clip(peak[0] - _BOX // 2, 0, h_im - _BOX))
            c0 = int(_np_scaling.clip(peak[1] - _BOX // 2, 0, w_im - _BOX))
            r1, c1 = r0 + _BOX, c0 + _BOX
            zoom_data = {
                'r0': r0, 'c0': c0, 'r1': r1, 'c1': c1,
                'crop_post': post[r0:r1, c0:c1],
                'crop_pre': pre[r0:r1, c0:c1],
            }

    return {
        'ratio_log': _np_scaling.log10(r_plot),
        'opt_scale': opt_scale,
        'ls_scale': ls_scale,
        'scale_sig': scale_sig,
        'n_hist_bins': n_hist_bins,
        'signal_percentile': signal_percentile,
        'sample': sample,
        'dye': dye,
        'diff_ls_all': _subsample(diff_ls_all),
        'diff_rob_all': _subsample(diff_rob_all),
        'diff_ls_opt': _subsample(diff_ls_opt),
        'diff_rob_opt': _subsample(diff_rob_opt),
        'n_ls_all': len(diff_ls_all),
        'n_ls_opt': len(diff_ls_opt) if sig_mask.any() else len(diff_ls_all),
        'n_rob_all': len(diff_rob_all),
        'n_rob_opt': len(diff_rob_opt),
        'zoom_data': zoom_data,
    }
