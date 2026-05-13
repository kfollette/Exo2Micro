"""
plotting.py
===========
Active visualization functions for the exo2micro pipeline.

Includes:
  - Registration pipeline check plots (boundary extraction, alignment)
  - Pre/post diagnostic plots (heatmap, histograms, ratio histogram)
  - Excess signal heatmap (diagonal reflection)
  - Difference image visualization
  - Simple image display

Legacy plotting functions (plot_im_sub, plot_diff_comparison,
plot_stretch_comparison, plot_zoom_region, plot_signal_scatter,
plot_ratio_histogram, plot_residual_histogram) have been moved
to exo2micro.legacy.

All plots include sample and dye in the title when provided.
"""

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.ndimage import gaussian_filter

# ==============================================================================
# COLORMAP UTILITIES
# ==============================================================================

def _make_diverging_cmap():
    """
    Diverging colormap with black at the centre.

    Designed for symmetric difference data (e.g. ``post − scale·pre``
    or ``grid − grid.T``) where zero is the meaningful neutral and
    the two signs need to be visually distinguishable. Goes from
    saturated blue (negative extreme) through dark blue → black
    (zero) → dark red → saturated red (positive extreme).

    The black centre keeps near-zero values dim so genuine signal at
    the extremes pops; this is opposite to most matplotlib diverging
    colormaps (RdBu, coolwarm, etc.) which use a light/white centre.
    Light-centre cmaps work well when "the data should look mostly
    blank with bright spots of interest"; black-centre works well
    when "the data should look mostly dark with bright spots of
    interest at either sign". Difference images of stained tissue
    are the latter case — most pixels are near zero (background or
    well-cancelled stain) and we want the microbe signal to stand
    out at the extremes.

    NaN values render as white (set via ``set_bad``), which is how
    background / masked pixels appear distinct from genuine
    near-zero data.
    """
    colors = [
        '#3361ff',   # saturated blue (negative extreme)
        '#1a3380',   # dark blue
        '#000000',   # black (zero)
        '#801a33',   # dark red
        '#ff3361',   # saturated red (positive extreme)
    ]
    cmap = LinearSegmentedColormap.from_list('dark_div', colors, N=512)
    cmap.set_bad('white')
    return cmap

def _make_inferno_cmap():
    """Inferno colormap with NaN values set to white."""
    cmap = plt.get_cmap('inferno').copy()
    cmap.set_bad('white')
    return cmap

def _title_prefix(sample, dye):
    """Build a 'Sample  Dye  —  ' prefix string."""
    _id = f'{sample}  {dye}' if (sample or dye) else ''
    return f'{_id}  —  ' if _id else ''

# ==============================================================================
# REGISTRATION PIPELINE CHECK PLOTS
# ==============================================================================

def plot_registration(stages, title='Registration', save_path=None,
                      sample='', dye=''):
    """
    Four-panel pipeline check figure for registration quality.

    Panel 1a: Post-stain boundary extraction (cyan contour)
    Panel 1b: Pre-stain boundary extraction (magenta contour)
    Panel 2:  Coarse alignment (both boundaries overlaid)
    Panel 3:  Final difference image (post - pre, unscaled)

    Parameters
    ----------
    stages : list of dict
        Stage dicts from register_highorder debug_data['stages'].
    title : str
        Figure title (default 'Registration').
    save_path : str or None
        If set, save to this path.
    sample, dye : str
        For title prefix.

    Returns
    -------
    fig : matplotlib.Figure or None
    """
    if not stages:
        return None

    coarse = stages[0]
    fine = stages[-1]

    prefix = _title_prefix(sample, dye)
    fig, axs = plt.subplots(1, 4, figsize=(28, 7))
    fig.suptitle(f'{prefix}{title}', fontsize=13)

    def _draw_boundary_on_image(ax, raw_im, edge_im, colour, panel_title):
        offset = 1.0
        log_im = np.log10(raw_im.astype(np.float32) + offset)
        px = raw_im[raw_im > 0]
        log_vmax = (np.log10(float(np.percentile(px, 99)) + offset)
                    if len(px) > 0 else 1.0)
        log_vmin = (np.log10(max(float(np.percentile(px, 1)), 1.0) + offset)
                    if len(px) > 0 else 0.0)
        ax.imshow(log_im, cmap='gray', vmin=log_vmin, vmax=log_vmax)
        if edge_im is not None and edge_im.max() > 0:
            h, w = raw_im.shape
            ax.contour(np.arange(w), np.arange(h), edge_im, levels=[0.5],
                       colors=[colour], linewidths=[1.5], linestyles=['solid'])
        ax.set_title(panel_title, fontsize=9)
        ax.axis('off')

    post_e = coarse.get('post_edges')
    _pre_e_pre = coarse.get('pre_edges_pre')
    pre_e_pre = _pre_e_pre if _pre_e_pre is not None else coarse.get('pre_edges')
    post_raw = coarse['post_raw']
    pre_raw = coarse['pre_raw']

    # Panel 1a: post-stain boundary
    _draw_boundary_on_image(axs[0], post_raw, post_e, 'cyan',
                             '1a. Post-Stain + boundary (cyan)')

    # Panel 1b: pre-stain boundary (before alignment)
    _draw_boundary_on_image(axs[1], pre_raw, pre_e_pre, 'magenta',
                             '1b. Pre-Stain + boundary (magenta, before alignment)')

    # Panel 2: coarse alignment overlay
    ax = axs[2]
    ax.set_title('2. Coarse alignment  '
                 '(cyan=post, magenta=pre after coarse)',
                 fontsize=9)

    post_e2 = coarse.get('post_edges')
    pre_e2 = coarse.get('pre_edges')
    pre_pre = coarse.get('pre_edges_pre')

    offset = 1.0
    post_log = np.log10(post_raw.astype(np.float32) + offset)
    px = post_raw[post_raw > 0]
    log_vmax_dark = (np.log10(float(np.percentile(px, 70)) + offset)
                     if len(px) > 0 else 1.0)
    log_vmin = (np.log10(max(float(np.percentile(px, 1)), 1.0) + offset)
                if len(px) > 0 else 0.0)
    ax.imshow(post_log, cmap='gray', vmin=log_vmin, vmax=log_vmax_dark, alpha=0.7)

    h, w = post_raw.shape
    ys, xs = np.arange(h), np.arange(w)

    if post_e2 is not None and post_e2.max() > 0:
        ax.contour(xs, ys, post_e2, levels=[0.5],
                   colors=['cyan'], linewidths=[1.5], linestyles=['solid'])
    if pre_e2 is not None and pre_e2.max() > 0:
        ax.contour(xs, ys, pre_e2, levels=[0.5],
                   colors=['magenta'], linewidths=[1.5], linestyles=['solid'])
    if pre_pre is not None and pre_pre.max() > 0:
        ax.contour(xs, ys, pre_pre, levels=[0.5],
                   colors=['magenta'], linewidths=[1.8], linestyles=['dashed'],
                   alpha=0.9)

    legend_elements2 = [
        Line2D([0], [0], color='cyan', linewidth=1.5,
               label='Post-Stain boundary'),
        Line2D([0], [0], color='magenta', linewidth=1.5, linestyle='solid',
               label='Pre-Stain boundary (after alignment)'),
        Line2D([0], [0], color='magenta', linewidth=1.2, linestyle='dashed',
               label='Pre-Stain boundary (before alignment)'),
    ]
    ax.legend(handles=legend_elements2, loc='lower left', fontsize=7,
              framealpha=0.7, facecolor='black', labelcolor='white')
    ax.axis('off')

    # Panel 3: final difference
    ax = axs[3]
    ax.set_title('3. Post - Pre difference  (post-warp, downsampled)',
                 fontsize=9)

    pre_warped = fine['pre_warped']
    post_raw_f = fine['post_raw']
    diffim = post_raw_f.astype(np.float32) - pre_warped.astype(np.float32)
    diff_px = diffim[np.abs(diffim) > 0]
    dv = np.nanpercentile(np.abs(diff_px), 95) if len(diff_px) > 0 else 1.0
    ax.imshow(diffim, cmap='bwr', vmin=-dv, vmax=dv)

    legend_elements = [
        Patch(facecolor='red', label='Post > Pre  (excess post-stain signal)'),
        Patch(facecolor='blue', label='Pre > Post  (excess pre-stain signal)'),
        Patch(facecolor='white', label='Balanced  (good local alignment)'),
    ]
    ax.legend(handles=legend_elements, loc='lower left', fontsize=7,
              framealpha=0.7, facecolor='black', labelcolor='white')
    ax.axis('off')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig

def plot_fine_alignment(post_raw, pre_coarse_raw, pre_refined_raw,
                        post_bnd, pre_coarse_bnd, pre_refined_bnd,
                        title='Fine alignment', save_path=None,
                        sample='', dye=''):
    """
    Two-panel comparison of coarse vs ICP-refined alignment.

    Parameters
    ----------
    post_raw : ndarray
        Post-stain image (downsampled, float32).
    pre_coarse_raw : ndarray
        Pre-stain warped by coarse transform.
    pre_refined_raw : ndarray
        Pre-stain warped by ICP-refined transform.
    post_bnd : ndarray
        Post-stain boundary ring.
    pre_coarse_bnd : ndarray
        Pre-stain boundary after coarse alignment.
    pre_refined_bnd : ndarray
        Pre-stain boundary after ICP refinement.
    title : str
        Figure title.
    save_path : str or None
        If set, save to this path.
    sample, dye : str
        For title prefix.

    Returns
    -------
    fig : matplotlib.Figure
    """
    prefix = _title_prefix(sample, dye)
    fig, axs = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle(f'{prefix}{title}', fontsize=13, fontweight='bold', y=1.01)

    def _log_bg(ax, raw_im, alpha=0.8):
        offset = 1.0
        log_im = np.log10(raw_im.astype(np.float32) + offset)
        px = raw_im[raw_im > 0]
        vmax = (np.log10(float(np.percentile(px, 70)) + offset)
                if len(px) > 0 else 1.0)
        vmin = (np.log10(max(float(np.percentile(px, 1)), 1.0) + offset)
                if len(px) > 0 else 0.0)
        ax.imshow(log_im, cmap='gray', vmin=vmin, vmax=vmax, alpha=alpha)

    h, w = post_raw.shape
    xs, ys = np.arange(w), np.arange(h)

    # Panel 1: after coarse alignment
    _log_bg(axs[0], post_raw)
    if post_bnd is not None and post_bnd.max() > 0:
        axs[0].contour(xs, ys, post_bnd, levels=[0.5],
                       colors=['cyan'], linewidths=[1.5])
    if pre_coarse_bnd is not None and pre_coarse_bnd.max() > 0:
        axs[0].contour(xs, ys, pre_coarse_bnd, levels=[0.5],
                       colors=['magenta'], linewidths=[1.5])
    axs[0].set_title('After coarse alignment\n'
                     'cyan = post  |  magenta = pre',
                     fontsize=10, pad=6)
    axs[0].axis('off')

    # Panel 2: after ICP refinement
    _log_bg(axs[1], post_raw)
    if post_bnd is not None and post_bnd.max() > 0:
        axs[1].contour(xs, ys, post_bnd, levels=[0.5],
                       colors=['cyan'], linewidths=[1.5], alpha=0.8)
    if pre_refined_bnd is not None and pre_refined_bnd.max() > 0:
        axs[1].contour(xs, ys, pre_refined_bnd, levels=[0.5],
                       colors=['yellow'], linewidths=[1.8], linestyles=['solid'],
                       alpha=0.85)
    if pre_coarse_bnd is not None and pre_coarse_bnd.max() > 0:
        axs[1].contour(xs, ys, pre_coarse_bnd, levels=[0.5],
                       colors=['magenta'], linewidths=[1.0], linestyles=['solid'],
                       alpha=0.6)
    axs[1].set_title('After ICP refinement\n'
                     'cyan = post  |  yellow = refined  |  magenta = coarse',
                     fontsize=10, pad=6)
    axs[1].axis('off')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig

# ==============================================================================
# SCALE ESTIMATION DIAGNOSTICS
# ==============================================================================

def plot_im(im, lims=None):
    """
    Display a single image with auto-scaled or user-specified colorbar.

    Parameters
    ----------
    im : ndarray
    lims : list or None
        [vmin, vmax] display limits.
    """
    plt.figure()
    if not lims:
        vmin = np.nanpercentile(im, 10)
        vmax = np.nanpercentile(im, 90)
    else:
        vmin, vmax = lims[0], lims[1]
    plt.imshow(im, vmin=vmin, vmax=vmax)
    plt.colorbar()

# ==============================================================================
# SIMPLE PRE/POST DIAGNOSTICS (Phase 3)
# ==============================================================================

def _integer_bin_edges(data, percentile_clip=99.9):
    """
    Build bin edges aligned to integer values (-0.5, 0.5, 1.5, …).

    Works correctly whether the data is integer-valued (post-stain)
    or continuous floats (warped pre-stain).

    Returns
    -------
    edges : ndarray
        Bin edges from -0.5 up to ceil(clip_value) + 0.5.
    """
    hi = float(np.percentile(data, percentile_clip))
    max_int = int(np.ceil(hi))
    return np.arange(-0.5, max_int + 1.5, 1.0)

def plot_pre_post_heatmap(post_im, pre_im,
                          sample='', dye='', save_path=None):
    """
    2-D density heatmap of pre-stain vs post-stain pixel brightness.

    Uses ALL pixels.  The y-axis (post-stain) is binned by the actual
    integer values present in the data, collapsing empty quantization
    gaps without smoothing or interpolation.  The x-axis (pre-stain)
    uses standard integer bins.

    Parameters
    ----------
    post_im, pre_im : ndarray (2-D, float-like)
        Post-stain and aligned pre-stain images.
    sample, dye : str
        For title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    """
    post = np.rint(post_im.ravel()).astype(np.int32)
    pre = np.rint(pre_im.ravel()).astype(np.int32)
    n_pixels = len(post)

    post = np.clip(post, 0, 255)
    pre = np.clip(pre, 0, 255)

    # Find the actual values present in post-stain (y-axis)
    post_vals = np.sort(np.unique(post))

    # Build bin edges at midpoints between consecutive real values
    # so each bin is centred on a real value
    y_edges = np.empty(len(post_vals) + 1)
    y_edges[0] = post_vals[0] - 0.5
    for i in range(1, len(post_vals)):
        y_edges[i] = (post_vals[i - 1] + post_vals[i]) / 2.0
    y_edges[-1] = post_vals[-1] + 0.5

    # x-axis: standard integer bins (pre-stain is continuous from warp)
    x_edges = np.arange(-0.5, 256.5, 1.0)

    # 2-D histogram with asymmetric bins
    h2d, x_out, y_out = np.histogram2d(pre, post, bins=[x_edges, y_edges])

    # Log colour scale; mask zeros to white
    with np.errstate(divide='ignore', invalid='ignore'):
        h2d_log = np.log10(h2d.astype(np.float64))
    h2d_log[~np.isfinite(h2d_log)] = np.nan

    # vmax: exclude the (0,0) bin
    valid = h2d_log.copy()
    valid[0, 0] = np.nan  # exclude (pre=0, post=0) corner
    valid_vals = valid[np.isfinite(valid)]
    vmin = float(np.nanmin(valid_vals)) if len(valid_vals) > 0 else 0
    vmax = float(np.nanmax(valid_vals)) if len(valid_vals) > 0 else 1

    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(9, 8))

    cmap = plt.get_cmap('inferno').copy()
    cmap.set_bad('white')

    img = ax.pcolormesh(x_out, y_out, h2d_log.T,
                        cmap=cmap, shading='flat', rasterized=True,
                        vmin=vmin, vmax=vmax)
    # Colorbar pinned to plot height via make_axes_locatable
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='4%', pad=0.08)
    cb = fig.colorbar(img, cax=cax)
    cb.set_label('log₁₀(pixel count)', fontsize=10)

    # Identity line
    ax.plot([0, 255], [0, 255], color='white', linewidth=1.2,
            linestyle='--', alpha=0.8, label='scale = 1 (identity)')

    ax.set_xlim(-0.5, 255.5)
    ax.set_ylim(y_edges[0], y_edges[-1])
    ax.set_aspect('equal')

    ax.set_xlabel('pre-stain brightness', fontsize=11)
    ax.set_ylabel('post-stain brightness', fontsize=11)
    ax.set_title(f'{prefix}pre vs post pixel brightness  '
                 f'(n={n_pixels:,} pixels)', fontsize=10)
    ax.legend(fontsize=9, loc='upper left')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig

def plot_excess_heatmap(post_im, pre_im, scale=None, scales=None,
                        sample='', dye='', save_path=None):
    """
    Excess post-stain signal heatmap (upper triangle only).

    Bins both axes by the actual integer values present in the
    post-stain data, then displays the post-excess asymmetry
    ``grid − grid.T`` only above the diagonal (where post > pre).
    The lower triangle is masked to NaN because, by construction,
    ``grid − grid.T`` is antisymmetric: every cell below the diagonal
    is the negative of its reflection above. There is no additional
    information in the lower half — displaying it would just be
    showing the same numbers with flipped sign on the wrong side
    of the line. Restricting the display to the upper triangle gives
    a single, unambiguous answer to the question "where in the
    brightness space is post brighter than pre, and by how much?".

    Cells with positive excess (post-stain pixels outnumber the
    reflected pre-stain pixels) are coloured by ``log₁₀(excess)``
    using a sequential magma palette. Cells with zero or negative
    excess in the upper triangle are also masked to NaN — these
    correspond to brightness pairs where pre-stain pixels are
    actually MORE common than post (a possible sign of bleaching,
    quenching, or alignment artifact).

    Optionally overplots one or more estimated scale lines.

    Parameters
    ----------
    post_im, pre_im : ndarray (2-D, float-like)
        Post-stain and aligned pre-stain images.
    scale : float or None
        Single scale line to overplot (legacy convenience; equivalent to
        passing ``scales=[('scale', scale, '#00cc88')]``).
    scales : list of tuple or None
        List of ``(label, value, color)`` tuples to overplot as scale lines.
        Takes precedence over ``scale`` when both are given.
        Typical usage::

            scales=[
                ('Moffat fit',  1.123, '#00cc88'),
                ('ratio p99.1', 1.456, '#ff9933'),
                ('manual',      1.500, '#ff3366'),
            ]

    sample, dye : str
        For title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    """
    post = np.rint(post_im.ravel()).astype(np.int32)
    pre = np.rint(pre_im.ravel()).astype(np.int32)
    n_pixels = len(post)

    post = np.clip(post, 0, 255)
    pre = np.clip(pre, 0, 255)

    # Bin both axes by post-stain sensor values
    vals = np.sort(np.unique(post))
    n_vals = len(vals)

    val_to_idx = np.full(256, -1, dtype=np.int32)
    for i, v in enumerate(vals):
        val_to_idx[v] = i

    post_idx = val_to_idx[post]

    # Round pre-stain to nearest post-stain value
    idx_above = np.searchsorted(vals, pre, side='left').clip(0, n_vals - 1)
    idx_below = (idx_above - 1).clip(0, n_vals - 1)
    dist_above = np.abs(pre - vals[idx_above])
    dist_below = np.abs(pre - vals[idx_below])
    pre_idx = np.where(dist_below < dist_above, idx_below, idx_above).astype(np.int32)

    # Build count grid
    grid = np.zeros((n_vals, n_vals), dtype=np.float64)
    np.add.at(grid, (pre_idx, post_idx), 1)

    # Bin edges for pcolormesh
    edges = np.empty(n_vals + 1)
    edges[0] = vals[0] - 0.5
    for i in range(1, n_vals):
        edges[i] = (vals[i - 1] + vals[i]) / 2.0
    edges[-1] = vals[-1] + 0.5

    # Compute the excess and restrict to the upper triangle
    # (post > pre). The lower triangle is masked to NaN because
    # excess is antisymmetric — the lower half is just the negated,
    # mirrored version of the upper half and contains no new
    # information. Negative or zero values in the upper triangle
    # (rare but possible — would mean pre-stain dominates at this
    # brightness pair) are also masked since the magma colormap
    # only conveys positive magnitudes.
    excess = grid - grid.T

    # In data-space:  grid[i, j] = count(pre=vals[i], post=vals[j])
    # So excess[i, j] is positive when there are more (pre=i, post=j)
    # pixels than (pre=j, post=i). When j > i (post > pre, upper
    # triangle in display), positive excess is the post-excess
    # signal we want to show.
    upper_tri_mask = np.triu(np.ones((n_vals, n_vals), dtype=bool), k=1)
    # k=1 so the diagonal itself is NOT included (zero anyway).

    excess_display = np.full_like(excess, np.nan)
    pos_in_upper = upper_tri_mask & (excess > 0)
    excess_display[pos_in_upper] = np.log10(excess[pos_in_upper])

    # Color limits from finite data
    finite_vals = excess_display[np.isfinite(excess_display)]
    if len(finite_vals) > 0:
        vmin = float(np.nanmin(finite_vals))
        vmax = float(np.nanmax(finite_vals))
    else:
        vmin, vmax = 0.0, 1.0

    # Plot — square data axes, sequential magma colormap.
    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(9, 8))

    cmap = plt.get_cmap('magma').copy()
    cmap.set_bad('white')

    img = ax.pcolormesh(edges, edges, excess_display.T,
                        cmap=cmap, shading='flat', rasterized=True,
                        vmin=vmin, vmax=vmax)

    # Colorbar pinned to the same height as the plot via
    # make_axes_locatable. Default fig.colorbar tries to steal
    # axes space and ends up shorter than the parent on square
    # axes; this approach guarantees a height match.
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='4%', pad=0.08)
    cbar = fig.colorbar(img, cax=cax)
    cbar.set_label('log₁₀(post excess count)', fontsize=10)

    # 1:1 identity line — black dashed, visible against magma
    ax.plot([vals[0], vals[-1]], [vals[0], vals[-1]],
            color='black', linewidth=1.0,
            linestyle='--', alpha=0.6, label='scale = 1')

    # Scale lines
    line_specs = []
    if scales:
        line_specs = list(scales)
    elif scale is not None:
        line_specs = [('scale', float(scale), '#00cc88')]

    for label, value, color in line_specs:
        if value is None or not np.isfinite(value) or value <= 0:
            continue
        x_end = min(float(vals[-1]), float(vals[-1]) / value)
        ax.plot([0, x_end], [0, x_end * value],
                color=color, linewidth=1.5,
                linestyle='-', alpha=0.9,
                label=f'{label} = {value:.3f}')

    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylim(edges[0], edges[-1])
    ax.set_aspect('equal')
    ax.set_xlabel('pre-stain brightness', fontsize=11)
    ax.set_ylabel('post-stain brightness', fontsize=11)
    ax.set_title(f'{prefix}post-stain excess  (upper triangle only)  '
                 f'(n={n_pixels:,} pixels)', fontsize=10)
    ax.legend(fontsize=8, loc='upper left')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig

def plot_pre_post_histograms(post_im, pre_im,
                             raw_pre_im=None,
                             sample='', dye='', save_path=None):
    """
    Overlapping histograms of pre-stain and post-stain pixel values.

    Apples-to-apples comparison: when ``raw_pre_im`` is provided, the
    foreground pre histogram uses the **raw padded pre-stain image**
    (discrete 8-bit values, no warp interpolation), making it directly
    comparable to the post histogram which is also discrete 8-bit.
    The warped/interpolated pre is drawn underneath in faint grey
    for reference so the effect of the alignment warp on the
    distribution is still visible.

    Padding-region zeros (where both pre and post are 0) are excluded
    via a sample-region mask defined as ``(post > 0) | (pre > 0)``.
    Interior dark pixels (zero in the sample region) are retained.

    Bin edges are integer-aligned (-0.5, 0.5, …) and adapt to the
    actual range and density of observed values to avoid empty bins
    when the data are sparse.

    The y-axis is linear by default; if the zero-value bin is more
    than 5× taller than the next-tallest bin (a common situation
    when the sample has lots of interior dark pixels), the y-axis
    switches to log so the rest of the distribution remains visible.

    Parameters
    ----------
    post_im : ndarray (2-D, float-like)
        Post-stain image (the reference frame, always
        ``01_padded_post``).
    pre_im : ndarray (2-D, float-like)
        Aligned (warped, interpolated) pre-stain image
        (``03_interior_aligned_pre`` or ``02_icp_aligned_pre``).
        Plotted in faint grey as a background reference.
    raw_pre_im : ndarray (2-D, float-like) or None
        Raw padded pre-stain image (``01_padded_pre``) — discrete
        8-bit values, no warp interpolation. When provided this is
        the apples-to-apples comparison to the post histogram and
        is plotted in the foreground. When ``None`` (legacy
        callers), the function falls back to the previous two-curve
        behaviour: warped pre and post only.
    sample, dye : str
        For title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    """
    # Sample-region mask: anywhere any of the three images has signal
    # is "in the sample". Anywhere all are zero is padding. This
    # excludes padding from all distributions without throwing away
    # interior dark pixels. ORing in the raw pre matters because it
    # lives in a slightly different (unwarped) frame than post and
    # warped pre — for large warps its sample footprint can extend
    # beyond the post/warped sample mask, and we want to keep those
    # pixels.
    if raw_pre_im is not None:
        sample_mask = (post_im > 0) | (pre_im > 0) | (raw_pre_im > 0)
    else:
        sample_mask = (post_im > 0) | (pre_im > 0)
    post = post_im[sample_mask].astype(np.float64).ravel()
    pre_warped = pre_im[sample_mask].astype(np.float64).ravel()
    if raw_pre_im is not None:
        raw_pre = raw_pre_im[sample_mask].astype(np.float64).ravel()
    else:
        raw_pre = None

    # ── Adaptive bin edges ────────────────────────────────────────
    # Use integer-aligned bins (each integer at the centre of its
    # bin). Range is determined by the foreground data (post + raw
    # pre if available, else post + warped pre). 99.9th percentile
    # caps the upper edge so a few bright outliers don't waste 90%
    # of the plot width.
    if raw_pre is not None and len(raw_pre):
        hi_data = np.concatenate([post, raw_pre])
    else:
        hi_data = np.concatenate([post, pre_warped])
    if len(hi_data) == 0:
        # Degenerate case: nothing to plot. Bail out with an empty
        # figure rather than crashing.
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.set_title(f'{_title_prefix(sample, dye)}'
                     'pre vs post: no in-sample pixels')
        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close(fig)
        return fig

    lo = 0  # always start at 0 so interior dark pixels are visible
    hi = max(1, int(np.ceil(np.percentile(hi_data, 99.9))))

    # Sparsity check: count distinct integer values present in the
    # foreground data over [lo, hi]. If they fill more than ~30% of
    # the integer range, use one bin per integer. Otherwise use one
    # bin per *observed* value — avoids long combs of empty bins
    # when only a handful of brightnesses appear (e.g. heavily
    # quantised raw data).
    foreground_ints = np.unique(np.rint(hi_data[hi_data <= hi]).astype(np.int64))
    foreground_ints = foreground_ints[foreground_ints >= lo]
    span = hi - lo + 1
    if len(foreground_ints) >= 0.30 * span:
        # Dense — one bin per integer.
        edges = np.arange(lo - 0.5, hi + 1.5, 1.0)
        x_positions = np.arange(lo, hi + 1)
    else:
        # Sparse — one bin per observed value. Edges sit halfway
        # between consecutive observed values so each bin centres
        # on its value.
        if len(foreground_ints) == 1:
            v = foreground_ints[0]
            edges = np.array([v - 0.5, v + 0.5])
        else:
            mids = (foreground_ints[:-1] + foreground_ints[1:]) / 2.0
            edges = np.concatenate([
                [foreground_ints[0] - 0.5],
                mids,
                [foreground_ints[-1] + 0.5],
            ])
        x_positions = foreground_ints

    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(9, 4))

    # ── Background layer: warped (interpolated) pre, faint grey ──
    # Drawn first so it sits beneath the foreground. We keep this
    # so users can see how much the alignment warp smeared the
    # distribution compared to the raw pre.
    if raw_pre is not None:
        ax.hist(pre_warped, bins=edges,
                histtype='stepfilled', color='#888888', alpha=0.18,
                edgecolor='#888888', linewidth=0.8,
                label=f'pre-stain, warped  (n={len(pre_warped):,})',
                zorder=1)

    # ── Foreground: raw pre (or warped pre as fallback) and post ──
    fg_pre = raw_pre if raw_pre is not None else pre_warped
    fg_pre_label = ('pre-stain, raw' if raw_pre is not None
                    else 'pre-stain')

    pre_counts, _, _ = ax.hist(
        fg_pre, bins=edges,
        histtype='stepfilled', color='#2196a0', alpha=0.45,
        edgecolor='#2196a0', linewidth=1.2,
        label=f'{fg_pre_label}  (n={len(fg_pre):,})',
        zorder=2)
    post_counts, _, _ = ax.hist(
        post, bins=edges,
        histtype='stepfilled', color='#e05c2a', alpha=0.45,
        edgecolor='#e05c2a', linewidth=1.2,
        label=f'post-stain  (n={len(post):,})',
        zorder=3)

    # ── Decide y-scale ────────────────────────────────────────────
    # If the zero bin is more than 10× taller than the second-tallest
    # bin in either foreground distribution, switch to log y so the
    # rest of the histogram doesn't get crushed to the baseline.
    use_log = False
    for counts in (pre_counts, post_counts):
        if len(counts) < 2:
            continue
        # The zero bin is whichever bin contains value 0. With our
        # integer-aligned edges that's the first bin if lo == 0.
        zero_bin_idx = 0 if x_positions[0] == 0 else None
        if zero_bin_idx is None:
            continue
        zero_count = counts[zero_bin_idx]
        # Second-tallest = max over all non-zero bins.
        others = np.concatenate([counts[:zero_bin_idx],
                                 counts[zero_bin_idx + 1:]])
        if len(others) == 0:
            continue
        second = others.max()
        if second > 0 and zero_count > 5 * second:
            use_log = True
            break

    if use_log:
        ax.set_yscale('log')
        y_label = 'pixel count (log)'
    else:
        y_label = 'pixel count'

    ax.set_xlim(lo - 0.5, hi + 0.5)
    ax.set_xlabel('pixel brightness', fontsize=11)
    ax.set_ylabel(y_label, fontsize=10)
    ax.set_title(f'{prefix}pre vs post pixel value distributions',
                 fontsize=10)
    ax.legend(fontsize=9, loc='best')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig

def plot_difference_histogram(post_im, pre_im,
                              sample='', dye='', save_path=None):
    """
    Histogram of raw pixel-wise difference (post - pre).

    Three overlaid distributions:
    - All pixels (outline only)
    - Pixels where post > 0 and pre == 0 (post-only signal)
    - Pixels where both post > 0 and pre > 0 (shared signal)

    Linear x-axis, log y-axis.

    Parameters
    ----------
    post_im, pre_im : ndarray (2-D, float-like)
        Post-stain and aligned pre-stain images.
    sample, dye : str
        For title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    """
    post = post_im.ravel().astype(np.float64)
    pre = pre_im.ravel().astype(np.float64)
    diff_all = np.rint(post - pre).astype(np.int32)

    # Subsets
    post_only = (post > 0) & (pre == 0)
    both = (post > 0) & (pre > 0)

    diff_post_only = diff_all[post_only]
    diff_both = diff_all[both]

    # Integer-aligned bin edges
    lo = int(diff_all.min())
    hi = int(diff_all.max())
    edges = np.arange(lo - 0.5, hi + 1.5, 1.0)

    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(12, 4))

    # All pixels: outline only
    ax.hist(diff_all, bins=edges,
            histtype='step', color='#7b4fa6', linewidth=1.2,
            alpha=0.7,
            label=f'all pixels  (n={len(diff_all):,})')

    # Both > 0: filled
    ax.hist(diff_both, bins=edges,
            histtype='stepfilled', color='#2196a0', alpha=0.45,
            edgecolor='#2196a0', linewidth=0.8,
            label=f'both > 0  (n={len(diff_both):,})')

    # Post > 0, pre == 0: filled
    ax.hist(diff_post_only, bins=edges,
            histtype='stepfilled', color='#e05c2a', alpha=0.45,
            edgecolor='#e05c2a', linewidth=0.8,
            label=f'post > 0, pre = 0  (n={len(diff_post_only):,})')

    ax.axvline(0, color='black', linewidth=1.2, linestyle='--',
               alpha=0.7, label='zero')

    ax.set_yscale('log')
    ax.set_xlabel('post − pre  (pixel brightness difference)',
                  fontsize=11)
    ax.set_ylabel('pixel count', fontsize=10)
    ax.set_title(f'{prefix}post − pre difference distribution', fontsize=10)
    ax.legend(fontsize=9)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig

def plot_ratio_histogram_simple(post_im, pre_im, n_bins=200,
                                smooth_sigma=3,
                                sample='', dye='', save_path=None):
    """
    Histogram of per-pixel post/pre ratio with scale estimation.

    Plotted in log₁₀ space.  Estimates the background scale factor
    from the smoothed histogram peak, then mirrors the left wing
    across the peak and fits a Moffat profile to model the noise.

    Parameters
    ----------
    post_im, pre_im : ndarray (2-D, float-like)
        Post-stain and aligned pre-stain images.
    n_bins : int
        Number of histogram bins (default 200).
    smooth_sigma : float
        Gaussian smoothing sigma (in bins) for peak finding (default 3).
    sample, dye : str
        For title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    scale_estimate : float
        Estimated background scale factor (in linear units).
    """
    from scipy.ndimage import uniform_filter1d
    from scipy.optimize import curve_fit as _curve_fit

    post = post_im.ravel().astype(np.float64)
    pre = pre_im.ravel().astype(np.float64)

    # Only pixels where both have signal
    both = (post > 0) & (pre > 0)
    post_b = post[both]
    pre_b = pre[both]

    ratio = post_b / pre_b
    log_ratio = np.log10(ratio)

    lo = float(log_ratio.min())
    hi = float(log_ratio.max())

    # Histogram
    counts, edges_h = np.histogram(log_ratio, bins=n_bins, range=(lo, hi))
    centres = (edges_h[:-1] + edges_h[1:]) / 2.0
    counts_f = counts.astype(np.float64)
    bin_width = float(edges_h[1] - edges_h[0])

    # Smooth for initial peak finding
    counts_smooth = uniform_filter1d(counts_f, size=max(int(smooth_sigma * 2 + 1), 3))

    # Find peak of smoothed histogram, EXCLUDING bins near ratio=1
    log_one = 0.0
    exclude_radius = 3 * bin_width
    peak_candidates = counts_smooth.copy()
    near_one = np.abs(centres - log_one) <= exclude_radius
    peak_candidates[near_one] = 0  # zero out ratio=1 neighborhood
    peak_bin = int(np.argmax(peak_candidates))
    log_scale_init = float(centres[peak_bin])

    # --- Moffat noise fit from left wing mirrored across peak ---
    # Exclude bins near ratio=1 from fitting
    not_near_one = ~near_one

    left_mask = (centres <= log_scale_init) & not_near_one
    x_left = centres[left_mask]
    y_left = counts_f[left_mask]

    # Mirror left wing across initial peak
    x_mirror = 2.0 * log_scale_init - x_left
    y_mirror = y_left.copy()

    # Exclude mirrored points near ratio=1
    mirror_ok = np.abs(x_mirror - log_one) > exclude_radius
    x_mirror = x_mirror[mirror_ok]
    y_mirror = y_mirror[mirror_ok]

    # Combine for fitting
    x_fit = np.concatenate([x_left, x_mirror])
    y_fit = np.concatenate([y_left, y_mirror])

    # Moffat profile: amp * (1 + ((x - mu) / alpha)^2)^(-beta)
    # beta controls peakedness: beta=1 is Lorentzian, large beta -> Gaussian
    def _moffat(x, amp, mu, alpha, beta):
        return amp * (1.0 + ((x - mu) / alpha) ** 2) ** (-beta)

    fit_x = np.linspace(lo, hi, 500)
    fit_y = None
    log_scale = log_scale_init  # will be refined by fit

    if len(x_fit) > 5 and y_fit.max() > 0:
        # Initial guesses
        alpha0 = float(max(log_scale_init - lo, 0.1) / 3.0)
        amp0 = float(y_fit.max())
        p0 = [amp0, log_scale_init, alpha0, 2.5]
        try:
            popt, _ = _curve_fit(_moffat, x_fit, y_fit, p0=p0,
                                 maxfev=10000,
                                 bounds=([0, lo, 1e-6, 1.0],
                                         [np.inf, hi, hi - lo, 20.0]))
            amp_fit, mu_fit, alpha_fit, beta_fit = popt
            fit_y = _moffat(fit_x, amp_fit, mu_fit, alpha_fit, beta_fit)
            # Refine scale from the fit centre
            log_scale = mu_fit
            print(f"  Moffat fit: mu={mu_fit:.4f} alpha={alpha_fit:.4f} "
                  f"beta={beta_fit:.2f}")
        except Exception as e:
            print(f"  Moffat fit failed: {e} — using smoothed peak")

    scale_estimate = float(10 ** log_scale)

    # --- Plot ---
    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(10, 4))

    # Main histogram
    ax.hist(log_ratio, bins=n_bins, range=(lo, hi),
            histtype='stepfilled', color='#2196a0', alpha=0.5,
            edgecolor='#2196a0', linewidth=0.8,
            label=f'both > 0  (n={len(log_ratio):,})')

    # Voigt noise estimate
    if fit_y is not None:
        ax.fill_between(fit_x, fit_y, alpha=0.35,
                        color='#888888', zorder=2,
                        label='noise estimate (Moffat)')
        ax.plot(fit_x, fit_y, color='#888888', linewidth=1.5,
                linestyle='-', zorder=3)

    # Fitted points (left wing + mirror), excluding near ratio=1
    if len(x_fit) > 0:
        ax.scatter(x_left, y_left, color='#999999', s=8,
                   alpha=0.6, zorder=4, marker='o',
                   label='fit bins (left of peak)')
        ax.scatter(x_mirror, y_mirror, color='#bbbbbb', s=8,
                   alpha=0.5, zorder=4, marker='^',
                   label='mirrored bins')

    # Reference lines
    ax.axvline(0, color='black', linewidth=1.0, linestyle='--',
               alpha=0.5, label='ratio = 1')
    ax.axvline(log_scale, color='#e05c2a', linewidth=2, linestyle='-',
               alpha=0.9,
               label=f'scale estimate = {scale_estimate:.3f}')

    # Tick labels in ratio units
    def _log_fmt(val, pos):
        return f'{10**val:.2g}'
    ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(_log_fmt))

    ax.set_xlabel('post / pre ratio  (log scale)', fontsize=11)
    ax.set_ylabel('pixel count', fontsize=10)
    ax.set_title(f'{prefix}post/pre ratio distribution  '
                 f'(n={len(log_ratio):,} pixels where both > 0)',
                 fontsize=10)
    ax.legend(fontsize=8)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()

    print(f"  Scale estimate (ratio peak): {scale_estimate:.4f}")
    return fig, scale_estimate

def plot_difference_image(post_im, pre_im, scale,
                          sample='', dye='', save_path=None):
    """
    Plot the scaled difference image: post − scale × pre.

    Shows the image with an asinh stretch and a diverging colormap
    so positive (microbe) signal is visually distinct from negative
    (over-subtraction) regions.

    Parameters
    ----------
    post_im, pre_im : ndarray (2-D, float-like)
        Post-stain and aligned pre-stain images.
    scale : float
        Scale factor to apply to pre-stain before subtraction.
    sample, dye : str
        For title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    diff : ndarray
        The difference image (float32).
    """
    post = post_im.astype(np.float32)
    pre = pre_im.astype(np.float32)
    diff = post - scale * pre

    # Asinh stretch for display
    tissue = (post > 0) | (pre > 0)
    tissue_px = diff[tissue]
    if len(tissue_px) > 0:
        knee = max(float(np.percentile(np.abs(tissue_px), 50)), 1.0)
    else:
        knee = 1.0
    stretched = np.arcsinh(diff / knee)

    # Symmetric color limits from tissue pixels
    stretched_tissue = stretched[tissue]
    if len(stretched_tissue) > 0:
        sv = float(np.percentile(np.abs(stretched_tissue), 95))
    else:
        sv = 1.0

    # Mask background
    display = stretched.copy()
    display[~tissue] = np.nan

    prefix = _title_prefix(sample, dye)
    fig, ax = plt.subplots(figsize=(12, 10))

    cmap = _make_diverging_cmap()
    img = ax.imshow(display, vmin=-sv, vmax=sv, cmap=cmap,
                    interpolation='nearest')
    # Colorbar pinned to plot height via make_axes_locatable
    divider = make_axes_locatable(ax)
    cax = divider.append_axes('right', size='4%', pad=0.08)
    cb = fig.colorbar(img, cax=cax)
    cb.set_label(f'asinh((post − {scale:.3f}×pre) / {knee:.0f})',
                 fontsize=9)

    ax.set_title(f'{prefix}post − {scale:.3f} × pre', fontsize=11)
    ax.axis('off')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig, diff


# ==============================================================================
# ZOOM / INSPECTION
# ==============================================================================

def plot_zoom(image, row, col, size, sigma=0.0,
              cmap='gray', stretch_percentile=99.0,
              diverging=False, title='', save_path=None):
    """
    Crop a square region from an image, optionally smooth it, and display.

    Useful for inspecting fine structure in large microscopy images or
    difference images. The crop is bounds-checked so near-edge coordinates
    work without raising.

    Parameters
    ----------
    image : ndarray (2-D)
        Source image to crop from. Can be any float or integer dtype.
    row, col : int
        Top-left corner of the crop region in pixel coordinates.
    size : int
        Side length of the square crop in pixels.
    sigma : float
        Gaussian blur sigma applied to the crop (default 0 = no blur).
    cmap : str
        Matplotlib colormap name (default 'gray'). Ignored if
        ``diverging=True``.
    stretch_percentile : float
        For non-diverging display, clip values above this percentile of
        the crop for display (default 99.0). Lower values push faint
        features harder.
    diverging : bool
        If True, use a symmetric diverging colormap centred at zero
        (appropriate for difference images). Overrides ``cmap``.
    title : str
        Figure title.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    crop : ndarray (2-D)
        The cropped (and smoothed, if sigma > 0) region.
    """
    h, w = image.shape[:2]

    # Clamp to image bounds
    r0 = int(max(0, min(row, h - 1)))
    c0 = int(max(0, min(col, w - 1)))
    r1 = int(max(r0 + 1, min(r0 + size, h)))
    c1 = int(max(c0 + 1, min(c0 + size, w)))

    crop = image[r0:r1, c0:c1].astype(np.float32)

    if sigma and sigma > 0:
        crop = gaussian_filter(crop, sigma=float(sigma))

    fig, ax = plt.subplots(figsize=(8, 8))

    if diverging:
        # Symmetric colour limits
        finite = crop[np.isfinite(crop)]
        if len(finite) > 0:
            sv = float(np.percentile(np.abs(finite), stretch_percentile))
            if sv <= 0:
                sv = 1.0
        else:
            sv = 1.0
        dcmap = _make_diverging_cmap()
        img = ax.imshow(crop, vmin=-sv, vmax=sv, cmap=dcmap,
                        interpolation='nearest')
    else:
        finite = crop[np.isfinite(crop)]
        if len(finite) > 0:
            vmin = float(np.percentile(finite, 100 - stretch_percentile))
            vmax = float(np.percentile(finite, stretch_percentile))
            if vmax <= vmin:
                vmax = vmin + 1.0
        else:
            vmin, vmax = 0.0, 1.0
        img = ax.imshow(crop, vmin=vmin, vmax=vmax, cmap=cmap,
                        interpolation='nearest')

    fig.colorbar(img, ax=ax, pad=0.02, shrink=0.8)

    sigma_str = f'  σ={sigma:g}' if sigma else ''
    full_title = title if title else 'zoom'
    ax.set_title(f'{full_title}  [{r0}:{r1}, {c0}:{c1}]{sigma_str}',
                 fontsize=10)
    ax.axis('off')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig, crop


def plot_zoom_multi(images, labels, row, col, size, sigma=0.0,
                    cmaps=None, diverging_flags=None,
                    stretch_percentile=99.0,
                    sample='', dye='', save_path=None):
    """
    Side-by-side zoomed crops from multiple images at the same coordinates.

    Useful for comparing post-stain, aligned pre-stain, and difference
    image at a common region of interest.

    Parameters
    ----------
    images : list of ndarray
        2-D images to crop from. All must have the same shape.
    labels : list of str
        Panel titles, one per image.
    row, col, size, sigma : int / int / int / float
        Crop geometry and blur, as in :func:`plot_zoom`.
    cmaps : list of str or None
        Per-image colormap names. Default: 'gray' for each.
    diverging_flags : list of bool or None
        If set, per-image flag to use a diverging symmetric colormap
        (typically True for the difference image).
    stretch_percentile : float
        Display stretch percentile.
    sample, dye : str
        For title prefix.
    save_path : str or None
        If set, save figure to this path.

    Returns
    -------
    fig : matplotlib.Figure
    crops : list of ndarray
    """
    n = len(images)
    if n == 0:
        return None, []
    if cmaps is None:
        cmaps = ['gray'] * n
    if diverging_flags is None:
        diverging_flags = [False] * n

    fig, axs = plt.subplots(1, n, figsize=(6 * n, 6))
    if n == 1:
        axs = [axs]

    crops = []
    for ax, im, lab, cmap, is_div in zip(axs, images, labels,
                                         cmaps, diverging_flags):
        h, w = im.shape[:2]
        r0 = int(max(0, min(row, h - 1)))
        c0 = int(max(0, min(col, w - 1)))
        r1 = int(max(r0 + 1, min(r0 + size, h)))
        c1 = int(max(c0 + 1, min(c0 + size, w)))
        crop = im[r0:r1, c0:c1].astype(np.float32)
        if sigma and sigma > 0:
            crop = gaussian_filter(crop, sigma=float(sigma))
        crops.append(crop)

        if is_div:
            finite = crop[np.isfinite(crop)]
            sv = (float(np.percentile(np.abs(finite), stretch_percentile))
                  if len(finite) > 0 else 1.0)
            if sv <= 0:
                sv = 1.0
            dcmap = _make_diverging_cmap()
            img = ax.imshow(crop, vmin=-sv, vmax=sv, cmap=dcmap,
                            interpolation='nearest')
        else:
            finite = crop[np.isfinite(crop)]
            if len(finite) > 0:
                vmin = float(np.percentile(finite, 100 - stretch_percentile))
                vmax = float(np.percentile(finite, stretch_percentile))
                if vmax <= vmin:
                    vmax = vmin + 1.0
            else:
                vmin, vmax = 0.0, 1.0
            img = ax.imshow(crop, vmin=vmin, vmax=vmax, cmap=cmap,
                            interpolation='nearest')
        fig.colorbar(img, ax=ax, pad=0.02, shrink=0.8)
        ax.set_title(lab, fontsize=10)
        ax.axis('off')

    sigma_str = f'  σ={sigma:g}' if sigma else ''
    prefix = _title_prefix(sample, dye)
    fig.suptitle(f'{prefix}zoom  [{row}:{row+size}, {col}:{col+size}]{sigma_str}',
                 fontsize=11, y=1.02)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  saved: {save_path}")
        plt.close(fig)
    else:
        plt.show()
    return fig, crops
