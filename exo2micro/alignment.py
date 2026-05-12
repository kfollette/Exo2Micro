"""
alignment.py
============
Image registration for pre/post-stain microscopy image pairs.

The multiscale registration pipeline:
  1. Coarse boundary correlation (translation + rotation + isotropic scale)
  2. ICP affine refinement of boundary contour correspondences
  3. Optional fine homography ECC pass (disabled by default)

All functions assume images are 2D float32 arrays.
"""

import numpy as np
import cv2
from .utils import equalize_pair


# ==============================================================================
# INTERNAL HELPERS
# ==============================================================================

def _extract_boundary(im_eq, boundary_width, boundary_smooth):
    """
    Extract the outer tissue boundary ring from an equalised image.

    Pipeline:
        1. Density-adaptive Gaussian blur to suppress interior texture
        2. Binary threshold to get tissue footprint
        3. Morphological closing to fill gaps
        4. Keep largest connected component; fill interior holes
        5. Large convex-envelope closing (dense images only)
        6. Erode then subtract to isolate the outer boundary ring
        7. Gaussian-soften the ring for ECC gradient tracking

    Parameters
    ----------
    im_eq : ndarray
        Equalised float32 image normalised to [0, 1].
    boundary_width : int
        Boundary ring thickness in pixels (erosion radius).
    boundary_smooth : float
        Gaussian softening sigma applied to the ring.

    Returns
    -------
    boundary_ecc : ndarray
        Softened boundary ring (float32, [0, 1]).
    boundary_raw : ndarray
        Hard binary boundary ring (float32, 0/255).
    """
    from scipy.ndimage import binary_fill_holes as _bfh

    nonzero_frac = float(np.mean(im_eq > 0.05))

    # Density-adaptive blur
    if nonzero_frac > 0.1:
        blur_sigma = min(max(im_eq.shape[0] // 50, 3), 20)
    else:
        blur_sigma = min(max(im_eq.shape[0] // 100, 2), 10)
    print(f"    _extract_boundary: blur_sigma={blur_sigma:.1f}  "
          f"(nonzero_frac={nonzero_frac:.3f})")

    im_blurred = cv2.GaussianBlur(im_eq, (0, 0), float(blur_sigma))
    im_blurred = im_blurred / (im_blurred.max() + 1e-8)

    # Adaptive threshold
    blurred_nz = im_blurred[im_blurred > 0]
    if nonzero_frac < 0.1 and len(blurred_nz) > 0:
        threshold = max(float(np.percentile(blurred_nz, 30)), 0.02)
        print(f"    _extract_boundary: sparse — adaptive threshold={threshold:.3f}")
    else:
        threshold = 0.1
    tissue_mask = (im_blurred > threshold).astype(np.uint8)

    # Morphological closing
    close_r = boundary_width * 3 if nonzero_frac > 0.3 else boundary_width
    close_k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (close_r * 2 + 1, close_r * 2 + 1))
    tissue_mask = cv2.morphologyEx(tissue_mask, cv2.MORPH_CLOSE, close_k,
                                   iterations=2)

    # Keep largest connected component
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        tissue_mask, connectivity=8)
    if n_labels > 1:
        largest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        tissue_mask = (labels == largest).astype(np.uint8)
    tissue_mask = _bfh(tissue_mask.astype(bool)).astype(np.uint8)

    # Large convex-envelope closing (dense images only)
    if nonzero_frac > 0.1:
        hull_r = max(im_eq.shape[0] // 20, boundary_width * 2)
        hull_k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (hull_r * 2 + 1, hull_r * 2 + 1))
        tissue_mask = cv2.morphologyEx(
            tissue_mask, cv2.MORPH_CLOSE, hull_k, iterations=1)
        tissue_mask = _bfh(tissue_mask.astype(bool)).astype(np.uint8)

    # Erode then subtract to get boundary ring
    erode_k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (boundary_width * 2 + 1, boundary_width * 2 + 1))
    eroded = cv2.erode(tissue_mask, erode_k, iterations=1)
    boundary = (tissue_mask - eroded).astype(np.float32)

    boundary_raw = boundary * 255.0

    # Gaussian soften for ECC
    boundary_ecc = cv2.GaussianBlur(
        boundary, (0, 0), max(float(boundary_smooth), 1.0))
    boundary_ecc = boundary_ecc / (boundary_ecc.max() + 1e-8)

    return boundary_ecc, boundary_raw


def _prepare_pair_for_ecc(post_small, pre_small, gauss_sigma, usharp,
                           use_edges, boundary_width, boundary_smooth):
    """
    Jointly preprocess a pair of downsampled images for ECC registration.

    Parameters
    ----------
    post_small : ndarray
        Downsampled post-stain image (float32).
    pre_small : ndarray
        Downsampled pre-stain image (float32).
    gauss_sigma : float
        Gaussian pre-smoothing sigma (0 = disabled).
    usharp : float or False
        Unsharp mask sigma (False = disabled).
    use_edges : bool
        If True, extract boundary ring instead of raw image.
    boundary_width : int
        Boundary ring thickness in pixels.
    boundary_smooth : float
        Gaussian softening sigma on the boundary ring.

    Returns
    -------
    post_ecc, pre_ecc : ndarray
        Preprocessed images ready for ECC.
    post_edges, pre_edges : ndarray or None
        Raw boundary rings for display.
    """
    post_edges = None
    pre_edges = None

    post_eq, pre_eq = equalize_pair(post_small, pre_small)

    if gauss_sigma > 0:
        post_eq = cv2.GaussianBlur(post_eq, (0, 0), float(gauss_sigma))
        pre_eq = cv2.GaussianBlur(pre_eq, (0, 0), float(gauss_sigma))

    if use_edges:
        post_ecc, post_edges = _extract_boundary(post_eq, boundary_width,
                                                  boundary_smooth)
        pre_ecc, pre_edges = _extract_boundary(pre_eq, boundary_width,
                                                boundary_smooth)
    elif usharp:
        post_blur = cv2.GaussianBlur(post_eq, (0, 0), float(usharp))
        pre_blur = cv2.GaussianBlur(pre_eq, (0, 0), float(usharp))
        post_ecc = np.clip(post_eq - post_blur, 0, None)
        pre_ecc = np.clip(pre_eq - pre_blur, 0, None)
        post_ecc = post_ecc / (post_ecc.max() + 1e-8)
        pre_ecc = pre_ecc / (pre_ecc.max() + 1e-8)
    else:
        post_ecc = post_eq
        pre_ecc = pre_eq

    return post_ecc, pre_ecc, post_edges, pre_edges


# ==============================================================================
# COARSE ALIGNMENT — BOUNDARY CORRELATION
# ==============================================================================

def boundary_correlation_coarse(post_full, pre_full, coarse_scale,
                                boundary_width, boundary_smooth,
                                rotation_search=True,
                                angle_range=20, angle_step=1,
                                scale_search=True,
                                scale_min=0.85, scale_max=1.15,
                                scale_step=0.05):
    """
    Find coarse rigid alignment by maximising boundary ring overlap.

    Uses phase correlation and brute-force rotation/scale search over
    extracted tissue boundary rings.

    Parameters
    ----------
    post_full : ndarray
        Full-resolution post-stain image (float32).
    pre_full : ndarray
        Full-resolution pre-stain image (float32).
    coarse_scale : float
        Downsample factor for boundary extraction.
    boundary_width : int
        Boundary ring thickness in pixels at coarse resolution.
    boundary_smooth : float
        Gaussian softening sigma on the boundary ring.
    rotation_search : bool
        Search over rotations (default True).
    angle_range : float
        Rotation search range ±degrees (default 20).
    angle_step : float
        Rotation search step in degrees (default 1).
    scale_search : bool
        Search over isotropic scale factors (default True).
    scale_min, scale_max, scale_step : float
        Scale search range and step.

    Returns
    -------
    warp_coarse_full : ndarray
        3x3 similarity homography at full resolution.
    best_angle : float
        Best rotation angle found (degrees).
    best_dx, best_dy : float
        Best translation in coarse-scale pixels.
    post_boundary_raw, pre_boundary_raw : ndarray
        Boundary rings at coarse scale (for diagnostics).
    """
    # Downsample
    post_small = cv2.resize(post_full, None, fx=coarse_scale, fy=coarse_scale,
                             interpolation=cv2.INTER_AREA)
    pre_small = cv2.resize(pre_full, None, fx=coarse_scale, fy=coarse_scale,
                            interpolation=cv2.INTER_AREA)

    # Joint equalisation and boundary extraction
    post_eq, pre_eq = equalize_pair(post_small, pre_small)
    post_boundary, post_boundary_raw = _extract_boundary(
        post_eq, boundary_width, boundary_smooth)
    pre_boundary, pre_boundary_raw = _extract_boundary(
        pre_eq, boundary_width, boundary_smooth)

    h, w = post_boundary.shape

    # Centroid for rotation pivot
    pre_moments = cv2.moments((pre_boundary_raw > 0).astype(np.uint8))
    if pre_moments['m00'] > 0:
        cx = pre_moments['m10'] / pre_moments['m00']
        cy = pre_moments['m01'] / pre_moments['m00']
    else:
        cx, cy = w / 2.0, h / 2.0

    best_response = -np.inf
    best_angle = 0.0
    best_scale = 1.0
    best_dx = 0.0
    best_dy = 0.0

    angles = ([0.0] if not rotation_search
              else np.arange(-angle_range, angle_range + angle_step, angle_step))
    scales = (np.arange(scale_min, scale_max + scale_step * 0.5, scale_step)
              if scale_search else [1.0])

    def _l2norm(im):
        n = np.linalg.norm(im)
        return im / n if n > 1e-8 else im

    post_boundary_norm = _l2norm(post_boundary.astype(np.float32))

    scale_responses = {}
    for scale in scales:
        scale_best_response = -np.inf
        for angle in angles:
            if angle == 0.0 and scale == 1.0:
                pre_transformed = pre_boundary.astype(np.float32)
            else:
                M_rs = cv2.getRotationMatrix2D((cx, cy), angle, scale)
                pre_transformed = cv2.warpAffine(
                    pre_boundary.astype(np.float32), M_rs, (w, h),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)

            pre_norm = _l2norm(pre_transformed)
            shift, response = cv2.phaseCorrelate(post_boundary_norm, pre_norm)

            if response > best_response:
                best_response = response
                best_angle = float(angle)
                best_scale = float(scale)
                best_dx = float(shift[0])
                best_dy = float(shift[1])

            if response > scale_best_response:
                scale_best_response = response

        scale_responses[float(scale)] = scale_best_response

    # Print scale response surface
    print("  Scale response surface (best response at each scale):")
    for sc, resp in sorted(scale_responses.items()):
        marker = ' <-- BEST' if abs(sc - best_scale) < 1e-6 else ''
        print(f"    scale={sc:.3f}  response={resp:.4f}{marker}")
    print(f"  Boundary correlation: dx={best_dx:.1f}, dy={best_dy:.1f} px, "
          f"angle={best_angle:.1f} deg  scale={best_scale:.3f}  "
          f"(response={best_response:.4f})")

    # Build full-resolution similarity transform
    cx_full = cx / coarse_scale
    cy_full = cy / coarse_scale
    dx_full = best_dx / coarse_scale
    dy_full = best_dy / coarse_scale
    theta = np.radians(best_angle)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    s = best_scale
    warp_coarse_full = np.array([
        [s * cos_t, -s * sin_t,
         (1 - s * cos_t) * cx_full + s * sin_t * cy_full + dx_full],
        [s * sin_t, s * cos_t,
         (1 - s * cos_t) * cy_full - s * sin_t * cx_full + dy_full],
        [0, 0, 1],
    ], dtype=np.float32)

    return (warp_coarse_full, best_angle, best_dx, best_dy,
            post_boundary_raw, pre_boundary_raw)


# ==============================================================================
# ICP REFINEMENT
# ==============================================================================

def refine_icp(post_full, warp_coarse,
               post_bnd_pts=None, pre_bnd_pts=None,
               bnd_scale=None,
               max_translation=200, max_rotation=5.0,
               max_scale_delta=0.1, max_scale_diff=0.05,
               close_threshold_px=30,
               close_threshold_floor=5,
               max_icp_iter=20):
    """
    Refine coarse alignment using ICP on tissue boundary points.

    Only well-matched boundary points (those already close after the coarse
    pass) are used, avoiding regions where tissue shapes genuinely differ.

    Parameters
    ----------
    post_full : ndarray
        Full-resolution post-stain image (float32).
    warp_coarse : ndarray
        3x3 coarse homography at full resolution.
    post_bnd_pts : ndarray or None
        Nx2 boundary points for post-stain in coarse-scale coords.
    pre_bnd_pts : ndarray or None
        Nx2 boundary points for pre-stain in post-coarse frame.
    bnd_scale : float or None
        Conversion factor from boundary-point coords to full-res pixels.
    max_translation : float
        Maximum allowed translation correction (default 200 px).
    max_rotation : float
        Maximum allowed rotation correction (default 5 degrees).
    max_scale_delta : float
        Maximum deviation of scale from 1.0 (default 0.1).
    max_scale_diff : float
        Maximum allowed ``|scale_x - scale_y|`` (default 0.05).
    close_threshold_px : float
        Initial max NN distance for well-matched pairs (default 30).
    close_threshold_floor : float
        Tightest threshold allowed (default 5).
    max_icp_iter : int
        Maximum ICP iterations (default 20).

    Returns
    -------
    warp_refined : ndarray
        3x3 refined homography.
    accepted : bool
        True if ICP correction was accepted.
    """
    from scipy.spatial import cKDTree

    if post_bnd_pts is None or pre_bnd_pts is None:
        print("  ICP: no boundary points provided — skipping")
        return warp_coarse.copy(), False

    if bnd_scale is None:
        bnd_scale = 1.0

    def _subsample_pts(pts, n_max=800):
        if pts is None or len(pts) == 0:
            return pts
        if len(pts) <= n_max:
            return pts
        idx = np.round(np.linspace(0, len(pts) - 1, n_max)).astype(int)
        return pts[idx]

    post_pts = _subsample_pts(post_bnd_pts).astype(np.float64)
    pre_pts_current = _subsample_pts(pre_bnd_pts).astype(np.float64)

    # Auto-set initial threshold from actual NN distances
    tree_init = cKDTree(pre_pts_current)
    dists_init, _ = tree_init.query(post_pts, k=1)
    median_dist = float(np.median(dists_init))
    adaptive_start = float(np.clip(2.0 * median_dist,
                                   close_threshold_floor,
                                   close_threshold_px))
    print(f"  ICP: post={len(post_pts)} pts, pre={len(pre_pts_current)} pts, "
          f"median_dist={median_dist:.1f} px  "
          f"threshold={adaptive_start:.1f}→{close_threshold_floor} px")

    # Global affine pre-correction for large misalignment
    M_accum = np.eye(3, dtype=np.float64)
    M_pre_corr = None
    freeze_scale = False

    if median_dist > 15.0:
        print(f"  ICP: median_dist={median_dist:.1f} px > 15 px — "
              f"running global affine pre-correction")
        tree_pre = cKDTree(post_pts)
        _, idx_pre = tree_pre.query(pre_pts_current, k=1)
        src_pre = pre_pts_current
        dst_pre = post_pts[idx_pre]

        src_mean_pre = src_pre.mean(axis=0)
        dst_mean_pre = dst_pre.mean(axis=0)
        src_c_pre = src_pre - src_mean_pre
        dst_c_pre = dst_pre - dst_mean_pre

        n_pre = len(src_c_pre)
        A_pre = np.zeros((2 * n_pre, 4), dtype=np.float64)
        A_pre[0::2, 0] = src_c_pre[:, 0]
        A_pre[0::2, 1] = src_c_pre[:, 1]
        A_pre[1::2, 2] = src_c_pre[:, 0]
        A_pre[1::2, 3] = src_c_pre[:, 1]
        b_pre = np.empty(2 * n_pre, dtype=np.float64)
        b_pre[0::2] = dst_c_pre[:, 0]
        b_pre[1::2] = dst_c_pre[:, 1]

        res_pre, _, _, _ = np.linalg.lstsq(A_pre, b_pre, rcond=None)
        a_p, b_p, c_p, d_p = res_pre
        tx_p = dst_mean_pre[0] - (a_p * src_mean_pre[0] + b_p * src_mean_pre[1])
        ty_p = dst_mean_pre[1] - (c_p * src_mean_pre[0] + d_p * src_mean_pre[1])
        sx_p = np.sqrt(a_p**2 + c_p**2)
        sy_p = np.sqrt(b_p**2 + d_p**2)
        ang_p = np.degrees(np.arctan2(c_p, a_p))
        print(f"    pre-correction: tx={tx_p:.1f} ty={ty_p:.1f} "
              f"sx={sx_p:.4f} sy={sy_p:.4f} angle={ang_p:.2f} deg")

        pre_ok = (abs(tx_p) < close_threshold_px * 5 and
                  abs(ty_p) < close_threshold_px * 5 and
                  abs(sx_p - 1.0) < 0.3 and
                  abs(sy_p - 1.0) < 0.3 and
                  abs(ang_p) < 10.0)
        if pre_ok:
            M_pre_corr = np.array([[a_p, b_p, tx_p],
                                   [c_p, d_p, ty_p],
                                   [0, 0, 1]], dtype=np.float64)
            ones = np.ones((len(pre_pts_current), 1))
            pre_pts_current = (M_pre_corr[:2] @
                               np.hstack([pre_pts_current, ones]).T).T
            M_accum = np.eye(3, dtype=np.float64)
            tree_post = cKDTree(pre_pts_current)
            dists_post, _ = tree_post.query(post_pts, k=1)
            median_dist_post = float(np.median(dists_post))
            print(f"    pre-correction accepted — "
                  f"median_dist: {median_dist:.1f} → {median_dist_post:.1f} px")
            adaptive_start = float(np.clip(2.0 * median_dist_post,
                                           close_threshold_floor,
                                           close_threshold_px))
            freeze_scale = True
        else:
            M_pre_corr = None
            print("    pre-correction REJECTED (implausible) — proceeding without it")

    # ICP main loop
    best_mean_dist = np.inf
    stagnation_count = 0

    for iteration in range(max_icp_iter):
        frac = iteration / max(max_icp_iter - 1, 1)
        threshold_iter = (adaptive_start * (1 - frac)
                          + close_threshold_floor * frac)

        tree = cKDTree(pre_pts_current)
        dists, idx = tree.query(post_pts, k=1)

        keep = dists < threshold_iter
        n_close = keep.sum()

        if n_close < 10:
            print(f"    ICP iter {iteration}: only {n_close} close pairs "
                  f"(threshold={threshold_iter:.1f} px) — stopping")
            break

        src = pre_pts_current[idx[keep]]
        dst = post_pts[keep]

        src_mean = src.mean(axis=0)
        dst_mean = dst.mean(axis=0)
        src_c = src - src_mean
        dst_c = dst - dst_mean

        n = len(src_c)
        A = np.zeros((2 * n, 4), dtype=np.float64)
        A[0::2, 0] = src_c[:, 0]
        A[0::2, 1] = src_c[:, 1]
        A[1::2, 2] = src_c[:, 0]
        A[1::2, 3] = src_c[:, 1]
        b_vec = np.empty(2 * n, dtype=np.float64)
        b_vec[0::2] = dst_c[:, 0]
        b_vec[1::2] = dst_c[:, 1]

        result, _, _, _ = np.linalg.lstsq(A, b_vec, rcond=None)
        a, b, c, d = result

        if freeze_scale:
            col0_norm = np.sqrt(a * a + c * c)
            col1_norm = np.sqrt(b * b + d * d)
            if col0_norm > 1e-8:
                a /= col0_norm
                c /= col0_norm
            if col1_norm > 1e-8:
                b /= col1_norm
                d /= col1_norm

        tx = dst_mean[0] - (a * src_mean[0] + b * src_mean[1])
        ty = dst_mean[1] - (c * src_mean[0] + d * src_mean[1])
        M_iter = np.array([[a, b, tx], [c, d, ty], [0, 0, 1]])

        iter_sx = np.sqrt(a * a + c * c)
        iter_sy = np.sqrt(b * b + d * d)
        step_too_large = (abs(tx) > threshold_iter * 3 or
                          abs(ty) > threshold_iter * 3 or
                          abs(iter_sx - 1.0) > 0.15 or
                          abs(iter_sy - 1.0) > 0.15)
        if step_too_large:
            print(f"    ICP iter {iteration}: step rejected "
                  f"(tx={tx:.1f} ty={ty:.1f} "
                  f"sx={iter_sx:.3f} sy={iter_sy:.3f})")
            continue

        M_accum = M_iter @ M_accum

        ones = np.ones((len(pre_pts_current), 1))
        pre_pts_current = (M_iter[:2] @ np.hstack([pre_pts_current, ones]).T).T

        mean_close = float(dists[keep].mean())
        sx = np.sqrt(a * a + c * c)
        sy = np.sqrt(b * b + d * d)
        print(f"    ICP iter {iteration}: n_close={n_close}  "
              f"threshold={threshold_iter:.1f} px  mean_dist={mean_close:.2f} px  "
              f"tx={tx:.2f}  ty={ty:.2f}  scale_x={sx:.4f}  scale_y={sy:.4f}")

        if mean_close < 0.5:
            print(f"    converged at iteration {iteration}")
            break

        if mean_close < best_mean_dist * 0.98:
            best_mean_dist = mean_close
            stagnation_count = 0
        else:
            stagnation_count += 1
            if stagnation_count >= 5:
                print(f"    ICP stagnated at iteration {iteration} "
                      f"(mean_dist={mean_close:.2f} px) — stopping")
                break

    # Decompose and sanity-check
    a = M_accum[0, 0]
    b = M_accum[0, 1]
    c = M_accum[1, 0]
    d = M_accum[1, 1]
    tx_bnd = M_accum[0, 2]
    ty_bnd = M_accum[1, 2]
    angle_deg = np.degrees(np.arctan2(c, a))
    scale_x = np.sqrt(a * a + c * c)
    scale_y = np.sqrt(b * b + d * d)
    tx_full = tx_bnd * bnd_scale
    ty_full = ty_bnd * bnd_scale

    print(f"  ICP accumulated: tx={tx_full:.1f} px  ty={ty_full:.1f} px  "
          f"angle={angle_deg:.3f} deg  scale_x={scale_x:.4f}  "
          f"scale_y={scale_y:.4f}")

    reasons = []
    if abs(tx_full) > max_translation:
        reasons.append(f"tx={tx_full:.1f} px > {max_translation}")
    if abs(ty_full) > max_translation:
        reasons.append(f"ty={ty_full:.1f} px > {max_translation}")
    if abs(angle_deg) > max_rotation:
        reasons.append(f"angle={angle_deg:.2f} deg > {max_rotation}")
    if abs(scale_x - 1.0) > max_scale_delta:
        reasons.append(f"scale_x={scale_x:.4f} outside [1±{max_scale_delta}]")
    if abs(scale_y - 1.0) > max_scale_delta:
        reasons.append(f"scale_y={scale_y:.4f} outside [1±{max_scale_delta}]")
    if abs(scale_x - scale_y) > max_scale_diff:
        reasons.append(f"|scale_x-scale_y|={abs(scale_x - scale_y):.4f} "
                       f"> {max_scale_diff}")

    if reasons:
        print(f"  ICP REJECTED ({'; '.join(reasons)}) — keeping coarse")
        return warp_coarse.copy(), False

    # Lift to full resolution and compose
    S_up = np.diag([bnd_scale, bnd_scale, 1.0])
    S_down = np.diag([1.0 / bnd_scale, 1.0 / bnd_scale, 1.0])

    M_icp_full = S_up @ M_accum @ S_down
    M_icp_full_inv = np.linalg.inv(M_icp_full)

    if M_pre_corr is not None:
        M_pre_full = S_up @ M_pre_corr @ S_down
        M_pre_full_inv = np.linalg.inv(M_pre_full)
        warp_refined = (M_icp_full_inv @ M_pre_full_inv @
                        warp_coarse.astype(np.float64)).astype(np.float32)
    else:
        warp_refined = (M_icp_full_inv @
                        warp_coarse.astype(np.float64)).astype(np.float32)

    print("  ICP accepted")
    return warp_refined, True


# ==============================================================================
# PHASE CORRELATION PRE-ALIGNMENT
# ==============================================================================

def prealign_phase_correlation(post_im, pre_im):
    """
    Compute a coarse translational pre-alignment using phase correlation.

    Parameters
    ----------
    post_im : ndarray
        Post-stain (fixed) image (2D).
    pre_im : ndarray
        Pre-stain image to be shifted (2D).

    Returns
    -------
    post_full : ndarray (float32)
    pre_shift : ndarray (float32)
        Pre-stain image shifted to coarsely align.
    shift : tuple
        (dx, dy) shift applied.
    """
    post = post_im.astype(np.float32)
    pre = pre_im.astype(np.float32)

    shift, response = cv2.phaseCorrelate(post, pre)
    dx, dy = shift
    print(f"prealign_phase_correlation: dx={dx:.1f}, dy={dy:.1f} px  "
          f"(response={response:.4f})")

    h, w = post.shape
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    pre_shift = cv2.warpAffine(pre, M, (w, h), flags=cv2.INTER_LINEAR)

    return post, pre_shift, (dx, dy)


# ==============================================================================
# INTERIOR FEATURE-MATCHING REFINEMENT
# ==============================================================================

def refine_interior_sift(post_full, pre_full, warp_init,
                         interior_blur_base=8.0,
                         interior_max_correction=500,
                         interior_min_inlier_ratio=0.4):
    """
    Refine alignment using SIFT feature matching on interior image content.

    Detects SIFT features in both post-stain and (ICP-warped) pre-stain
    images, matches them, and computes a refined homography via RANSAC.
    This is robust to the intensity differences between pre and post
    because SIFT features are based on local gradient structure.

    Microbe-only features (present in post but not pre) are naturally
    rejected by the matching + RANSAC pipeline as outliers.

    This function was previously called ``refine_interior_ecc`` when
    the body used an ECC pyramid (pre-v2.1). The implementation now
    uses SIFT exclusively; the old name has been retained as an alias
    for one version for backward compatibility.

    Parameters
    ----------
    post_full : ndarray
        Full-resolution post-stain image (float32).
    pre_full : ndarray
        Full-resolution pre-stain image (float32, un-warped).
    warp_init : ndarray
        3×3 homography from upstream alignment (boundary corr + ICP).
    interior_blur_base : float
        Gaussian blur sigma applied before feature detection (default 8.0).
        Suppresses microbe-scale features to focus on mineral grain structure.
    interior_max_correction : float
        Maximum allowed total correction in full-resolution pixels
        (default 500).  If exceeded, the refinement is rejected.
    interior_min_inlier_ratio : float
        Minimum RANSAC inlier ratio to accept the refinement (default 0.4).
        Below this, the match quality is too poor to trust.

    Returns
    -------
    warp_refined : ndarray
        3×3 refined homography at full resolution.
    result : dict
        Diagnostic information:
        - 'success' : bool
        - 'levels_completed' : int (1 if success, 0 if not)
        - 'total_levels' : int (always 1)
        - 'estimated_accuracy_px' : float
        - 'level_details' : list of dict
        - 'failure_reason' : str or None
    """
    h, w = post_full.shape

    # Work at a moderate scale for feature detection — full resolution
    # is too slow and has too many microbe-scale features.
    # 0.5× gives good feature density while keeping computation reasonable.
    work_scale = 0.5
    if max(h, w) * work_scale > 15000:
        work_scale = 10000.0 / max(h, w)
    if max(h, w) * work_scale < 2000:
        work_scale = min(1.0, 2000.0 / max(h, w))

    print(f"\n  Interior feature matching (work_scale={work_scale:.3f})...")

    # Downsample
    post_small = cv2.resize(post_full, None, fx=work_scale, fy=work_scale,
                            interpolation=cv2.INTER_AREA)
    pre_small = cv2.resize(pre_full, None, fx=work_scale, fy=work_scale,
                           interpolation=cv2.INTER_AREA)
    h_s, w_s = post_small.shape

    # Rescale warp to work scale
    S = np.diag([work_scale, work_scale, 1.0]).astype(np.float32)
    S_inv = np.diag([1.0 / work_scale, 1.0 / work_scale, 1.0]).astype(np.float32)
    warp_work = S @ warp_init.astype(np.float32) @ S_inv

    # Warp pre into post frame
    pre_warped = cv2.warpPerspective(
        pre_small, warp_work, (w_s, h_s),
        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

    # Light blur to suppress noise / microbe spots before feature detection
    blur_sigma = max(interior_blur_base * 0.5, 1.0)
    post_blur = cv2.GaussianBlur(post_small, (0, 0), float(blur_sigma))
    pre_blur = cv2.GaussianBlur(pre_warped, (0, 0), float(blur_sigma))

    # Convert to uint8 for SIFT (needs 8-bit input)
    def _to_uint8(im):
        px = im[im > 0]
        if len(px) == 0:
            return np.zeros_like(im, dtype=np.uint8)
        vmin = float(np.percentile(px, 1))
        vmax = float(np.percentile(px, 99))
        if vmax <= vmin:
            vmax = vmin + 1.0
        scaled = np.clip((im - vmin) / (vmax - vmin) * 255, 0, 255)
        return scaled.astype(np.uint8)

    post_u8 = _to_uint8(post_blur)
    pre_u8 = _to_uint8(pre_blur)

    # Detect SIFT features
    sift = cv2.SIFT_create(nfeatures=5000)
    kp_post, desc_post = sift.detectAndCompute(post_u8, None)
    kp_pre, desc_pre = sift.detectAndCompute(pre_u8, None)

    print(f"    Features detected: post={len(kp_post)}, pre={len(kp_pre)}")

    detail = {
        'level': 1,
        'scale': work_scale,
        'n_features_post': len(kp_post),
        'n_features_pre': len(kp_pre),
    }

    if len(kp_post) < 10 or len(kp_pre) < 10:
        detail['status'] = 'failed'
        detail['reason'] = 'Too few features detected'
        print(f"    Too few features — keeping ICP result")
        print(f"    → To assess ICP alignment, blink:")
        print(f"        fits/01_padded_post.fits")
        print(f"        fits/02_icp_aligned_pre.fits")
        return warp_init.copy(), {
            'success': False, 'levels_completed': 0, 'total_levels': 1,
            'estimated_accuracy_px': float('inf'),
            'level_details': [detail], 'failure_reason': detail['reason'],
        }

    # Match features using FLANN
    index_params = dict(algorithm=1, trees=5)  # FLANN_INDEX_KDTREE
    search_params = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(desc_post, desc_pre, k=2)

    # Lowe's ratio test
    good_matches = []
    for m_pair in matches:
        if len(m_pair) == 2:
            m, n = m_pair
            if m.distance < 0.7 * n.distance:
                good_matches.append(m)

    print(f"    Good matches (Lowe ratio<0.7): {len(good_matches)}")
    detail['n_matches'] = len(good_matches)

    if len(good_matches) < 10:
        detail['status'] = 'failed'
        detail['reason'] = f'Only {len(good_matches)} good matches (need ≥10)'
        print(f"    Too few matches — keeping ICP result")
        print(f"    → To assess ICP alignment, blink:")
        print(f"        fits/01_padded_post.fits")
        print(f"        fits/02_icp_aligned_pre.fits")
        return warp_init.copy(), {
            'success': False, 'levels_completed': 0, 'total_levels': 1,
            'estimated_accuracy_px': float('inf'),
            'level_details': [detail], 'failure_reason': detail['reason'],
        }

    # Extract matched point coordinates
    pts_post = np.float32([kp_post[m.queryIdx].pt for m in good_matches])
    pts_pre = np.float32([kp_pre[m.trainIdx].pt for m in good_matches])

    # Find homography with RANSAC
    # This maps pre_warped coords → post coords
    H_delta, inlier_mask = cv2.findHomography(
        pts_pre, pts_post, cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=5000,
        confidence=0.999)

    if H_delta is None:
        detail['status'] = 'failed'
        detail['reason'] = 'RANSAC failed to find homography'
        print(f"    RANSAC failed — keeping ICP result")
        return warp_init.copy(), {
            'success': False, 'levels_completed': 0, 'total_levels': 1,
            'estimated_accuracy_px': float('inf'),
            'level_details': [detail], 'failure_reason': detail['reason'],
        }

    n_inliers = int(inlier_mask.sum())
    inlier_ratio = n_inliers / len(good_matches)
    print(f"    RANSAC inliers: {n_inliers}/{len(good_matches)} "
          f"({inlier_ratio*100:.1f}%)")

    detail['n_inliers'] = n_inliers
    detail['inlier_ratio'] = inlier_ratio

    # Sanity check: inlier ratio
    if inlier_ratio < interior_min_inlier_ratio:
        detail['status'] = 'rejected'
        detail['reason'] = (f'inlier ratio {inlier_ratio:.1%} below minimum '
                            f'{interior_min_inlier_ratio:.0%}')
        print(f"    Inlier ratio {inlier_ratio:.1%} below minimum "
              f"({interior_min_inlier_ratio:.0%}) — REJECTED")
        print(f"    → Match quality too low to trust. This may indicate:")
        print(f"        - Too few shared features between pre and post")
        print(f"        - Try increasing interior_blur_base to suppress microbe detail")
        print(f"    → To assess ICP alignment, blink:")
        print(f"        fits/01_padded_post.fits")
        print(f"        fits/02_icp_aligned_pre.fits")
        return warp_init.copy(), {
            'success': False, 'levels_completed': 0, 'total_levels': 1,
            'estimated_accuracy_px': float('inf'),
            'level_details': [detail], 'failure_reason': detail['reason'],
        }

    # Measure correction magnitude (translation component in full-res pixels)
    dx_work = H_delta[0, 2]
    dy_work = H_delta[1, 2]
    dx_fullres = dx_work / work_scale
    dy_fullres = dy_work / work_scale
    correction_fullres = np.sqrt(dx_fullres**2 + dy_fullres**2)

    detail['dx_correction'] = float(dx_fullres)
    detail['dy_correction'] = float(dy_fullres)
    detail['correction_fullres_px'] = float(correction_fullres)

    # Sanity check
    if correction_fullres > interior_max_correction:
        detail['status'] = 'rejected'
        detail['reason'] = (f'correction {correction_fullres:.1f}px '
                            f'exceeds limit {interior_max_correction:.1f}px')
        print(f"    Correction {correction_fullres:.1f}px exceeds limit "
              f"({interior_max_correction:.1f}px) — REJECTED")
        print(f"    → To assess ICP alignment, blink:")
        print(f"        fits/01_padded_post.fits")
        print(f"        fits/02_icp_aligned_pre.fits")
        return warp_init.copy(), {
            'success': False, 'levels_completed': 0, 'total_levels': 1,
            'estimated_accuracy_px': float('inf'),
            'level_details': [detail], 'failure_reason': detail['reason'],
        }

    # Compose: H_delta maps pre_warped→post in work coords.
    # With WARP_INVERSE_MAP, we need dst→src map.
    # Current warp maps post→pre (dst→src).
    # H_delta maps pre_warped→post, so inv(H_delta) maps post→pre_warped.
    # Combined: inv(H_delta) ∘ warp_work maps post→pre (through pre_warped).
    # But warp_work already maps post→pre, and H_delta is a correction
    # in the warped space. So: new_warp = warp_work @ inv(H_delta)
    H_delta_inv = np.linalg.inv(H_delta.astype(np.float64))
    warp_work_refined = (warp_work.astype(np.float64) @ H_delta_inv)

    # Lift back to full resolution
    warp_refined = (S_inv @ warp_work_refined @ S).astype(np.float32)

    # Compute reprojection error on inliers for accuracy estimate
    inlier_pts_post = pts_post[inlier_mask.ravel() == 1]
    inlier_pts_pre = pts_pre[inlier_mask.ravel() == 1]
    # Transform pre points by H_delta and measure distance to post points
    pre_transformed = cv2.perspectiveTransform(
        inlier_pts_pre.reshape(-1, 1, 2), H_delta).reshape(-1, 2)
    reproj_errors = np.sqrt(np.sum((inlier_pts_post - pre_transformed)**2, axis=1))
    median_reproj = float(np.median(reproj_errors))
    estimated_accuracy = median_reproj / work_scale  # in full-res pixels

    detail['status'] = 'accepted'
    detail['median_reproj_error'] = median_reproj
    detail['estimated_accuracy_px'] = estimated_accuracy

    print(f"    dx={dx_fullres:.1f}px dy={dy_fullres:.1f}px "
          f"(total={correction_fullres:.1f}px)")
    print(f"    Median reprojection error: {median_reproj:.2f}px "
          f"(at work scale) → ±{estimated_accuracy:.1f}px (full res)")

    print(f"  Interior feature matching: accepted "
          f"(estimated accuracy: ±{estimated_accuracy:.1f}px)")
    print(f"    → To verify, blink:")
    print(f"        fits/01_padded_post.fits")
    print(f"        fits/03_interior_aligned_pre.fits")

    return warp_refined, {
        'success': True,
        'levels_completed': 1,
        'total_levels': 1,
        'estimated_accuracy_px': estimated_accuracy,
        'level_details': [detail],
        'failure_reason': None,
    }




# ==============================================================================
# MAIN REGISTRATION API
# ==============================================================================

def register_highorder(post_im, pre_im, stopit=500, stopdelta=1e-6,
                       down_scale=0.3, usharp=False, gauss_sigma=0,
                       use_edges=True, boundary_width=15, boundary_smooth=10,
                       coarse_stopit=1000, coarse_stopdelta=1e-4,
                       rotation_search=True, angle_range=20, angle_step=1,
                       scale_search=True, scale_min=0.85, scale_max=1.15,
                       scale_step=0.05, multiscale=True, fine_ecc=False,
                       max_translation=200, max_rotation=5.0,
                       max_scale_delta=0.2, max_scale_diff=0.15,
                       save_prefix=None):
    """
    Register pre-stain to post-stain using a multiscale strategy.

    Pipeline:
        1. Boundary correlation coarse pass (translation + rotation + scale)
        2. ICP affine refinement of boundary contour correspondences
        3. Optional fine homography ECC pass (fine_ecc=True)

    Parameters
    ----------
    post_im, pre_im : ndarray
        Post-stain (fixed) and pre-stain (moving) images (2D).
    stopit : int
        Max ECC iterations for fine pass (default 500).
    stopdelta : float
        ECC convergence threshold (default 1e-6).
    down_scale : float
        Downsample factor for fine ECC pass (default 0.3).
    usharp : float or False
        Unsharp mask sigma (default False).
    gauss_sigma : float
        Gaussian pre-smoothing sigma (default 0).
    use_edges : bool
        Extract boundary rings for ECC (default True).
    boundary_width : int
        Boundary ring thickness (default 15).
    boundary_smooth : float
        Boundary softening sigma (default 10).
    rotation_search : bool
        Search over rotations (default True).
    angle_range : float
        Rotation search ±degrees (default 20).
    angle_step : float
        Rotation search step (default 1).
    scale_search : bool
        Search over scale factors (default True).
    scale_min, scale_max, scale_step : float
        Scale search parameters.
    multiscale : bool
        Run coarse+ICP pipeline (default True).
    fine_ecc : bool
        Run fine ECC after ICP (default False).
    max_translation, max_rotation : float
        ICP sanity limits.
    max_scale_delta, max_scale_diff : float
        ICP scale sanity limits.
    save_prefix : str or None
        If set, save pipeline check plots to disk.

    Returns
    -------
    post_full : ndarray (float32)
    pre_aligned : ndarray (float32)
        Pre-stain warped by full pipeline.
    pre_coarse_aligned : ndarray or None
        Pre-stain warped by coarse pass only (None if multiscale=False).
    warp_matrix : ndarray
        Final 3x3 homography.
    debug_data : dict
        Intermediate data for pipeline check plots.
    """
    warp_mode = cv2.MOTION_HOMOGRAPHY
    warp_matrix = np.eye(3, 3, dtype=np.float32)
    warp_coarse = None
    criteria_fine = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                     stopit, stopdelta)

    post_full = post_im.astype(np.float32)
    pre_full = pre_im.astype(np.float32)

    debug_data = {
        'stages': [],
        'post_bnd_raw': None,
        'pre_bnd_raw': None,
        'pre_bnd_warped': None,
        'post_bnd_display': None,
    }

    if multiscale:
        coarse_scale = max(down_scale * 0.25, 0.02)
        print(f"Multiscale: boundary correlation (coarse_scale={coarse_scale:.3f}) "
              f"→ ICP → fine ECC (down_scale={down_scale:.3f})")

        # Step 1: Coarse boundary correlation
        (warp_coarse, best_angle, best_dx, best_dy,
         post_bnd_raw, pre_bnd_raw) = boundary_correlation_coarse(
            post_full, pre_full,
            coarse_scale=coarse_scale,
            boundary_width=boundary_width,
            boundary_smooth=boundary_smooth,
            rotation_search=rotation_search,
            angle_range=angle_range,
            angle_step=angle_step,
            scale_search=scale_search,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
        )

        warp_matrix = warp_coarse.copy()

        # Warp pre-stain boundary into post-coarse frame
        post_coarse = cv2.resize(post_full, None, fx=coarse_scale, fy=coarse_scale,
                                  interpolation=cv2.INTER_AREA)
        pre_coarse = cv2.resize(pre_full, None, fx=coarse_scale, fy=coarse_scale,
                                 interpolation=cv2.INTER_AREA)
        h_c, w_c = post_coarse.shape
        S_c = np.diag([coarse_scale, coarse_scale, 1.0]).astype(np.float32)
        S_c_inv = np.diag([1.0 / coarse_scale, 1.0 / coarse_scale, 1.0]).astype(np.float32)
        H_c = S_c @ warp_coarse @ S_c_inv
        pre_bnd_warped = cv2.warpPerspective(
            pre_bnd_raw.astype(np.float32), H_c, (w_c, h_c),
            flags=cv2.INTER_NEAREST + cv2.WARP_INVERSE_MAP)
        post_bnd_display = cv2.resize(post_bnd_raw, (w_c, h_c),
                                       interpolation=cv2.INTER_NEAREST)

        # Store debug data
        pre_warped_coarse = cv2.warpPerspective(
            pre_coarse, H_c, (w_c, h_c),
            flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        pre_bnd_pre = cv2.resize(pre_bnd_raw, (w_c, h_c),
                                  interpolation=cv2.INTER_NEAREST)
        debug_data['stages'].append({
            'label': f'Boundary corr (scale={coarse_scale:.3f})',
            'post_raw': post_coarse, 'pre_raw': pre_coarse,
            'post_ecc': post_bnd_display, 'pre_ecc': pre_bnd_warped,
            'pre_warped': pre_warped_coarse,
            'post_edges': post_bnd_display,
            'pre_edges': pre_bnd_warped,
            'pre_edges_pre': pre_bnd_pre,
        })
        debug_data['post_bnd_raw'] = post_bnd_raw
        debug_data['pre_bnd_raw'] = pre_bnd_raw
        debug_data['pre_bnd_warped'] = pre_bnd_warped
        debug_data['post_bnd_display'] = post_bnd_display

        # Step 2: ICP refinement
        if warp_coarse is not None:
            h_full, w_full = post_full.shape

            def _bnd_to_pts(bnd_raw):
                mask = (bnd_raw > 10).astype(np.uint8)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                                cv2.CHAIN_APPROX_NONE)
                if not contours:
                    return None
                c = max(contours, key=cv2.contourArea)
                return c.reshape(-1, 2).astype(np.float32)

            post_icp_pts = _bnd_to_pts(post_bnd_raw)
            pre_icp_pts = _bnd_to_pts(pre_bnd_warped)

            warp_matrix, accepted = refine_icp(
                post_full, warp_coarse,
                post_bnd_pts=post_icp_pts,
                pre_bnd_pts=pre_icp_pts,
                bnd_scale=1.0 / coarse_scale,
                max_translation=max_translation,
                max_rotation=max_rotation,
                max_scale_delta=max_scale_delta,
                max_scale_diff=max_scale_diff,
            )

        # Step 3: Optional fine ECC
        if fine_ecc:
            post_small = cv2.resize(post_full, None, fx=down_scale, fy=down_scale,
                                     interpolation=cv2.INTER_AREA)
            pre_small = cv2.resize(pre_full, None, fx=down_scale, fy=down_scale,
                                    interpolation=cv2.INTER_AREA)

            post_ecc, pre_ecc, post_fine_edges, pre_fine_edges = \
                _prepare_pair_for_ecc(post_small, pre_small, gauss_sigma, usharp,
                                      use_edges, boundary_width, boundary_smooth)
            try:
                cc, warp_matrix = cv2.findTransformECC(
                    post_ecc, pre_ecc, warp_matrix, warp_mode, criteria_fine)
                print(f"  Fine ECC converged  (cc={cc:.4f})")
            except cv2.error:
                print(f"  Fine ECC failed — keeping coarse/ICP result")
                warp_matrix = (warp_coarse.copy() if warp_coarse is not None
                               else warp_matrix)

            # Rescale from down_scale coords to full resolution
            S = np.diag([down_scale, down_scale, 1.0]).astype(np.float32)
            S_inv = np.diag([1.0 / down_scale, 1.0 / down_scale, 1.0]).astype(np.float32)
            warp_matrix = S_inv @ warp_matrix @ S
        else:
            print("  Fine ECC skipped (fine_ecc=False) — using coarse/ICP result")

    # Apply final homography
    h, w = post_full.shape
    pre_aligned = cv2.warpPerspective(
        pre_full, warp_matrix, (w, h),
        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

    # Coarse-only warp for comparison
    if warp_coarse is not None:
        pre_coarse_aligned = cv2.warpPerspective(
            pre_full, warp_coarse, (w, h),
            flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
    else:
        pre_coarse_aligned = None

    # Report final homography decomposition
    H = warp_matrix / warp_matrix[2, 2]
    a, b_val = H[0, 0], H[0, 1]
    c, d = H[1, 0], H[1, 1]
    tx, ty = H[0, 2], H[1, 2]
    p, q = H[2, 0], H[2, 1]

    angle_deg = np.degrees(np.arctan2(c, a))
    scale_x = np.sqrt(a * a + c * c)
    scale_y = np.sqrt(b_val * b_val + d * d)
    shear = (a * b_val + c * d) / (scale_x * scale_y)
    perspective_mag = np.sqrt(p * p + q * q)

    print("\n=========== Homography Alignment Results ===========")
    print(f"Rotation angle        : {angle_deg:10.4f} degrees")
    print(f"Translation X (dx)    : {tx:10.2f} pixels")
    print(f"Translation Y (dy)    : {ty:10.2f} pixels")
    print(f"Scale X (magnify)     : {scale_x:10.6f}")
    print(f"Scale Y (magnify)     : {scale_y:10.6f}")
    print(f"Shear factor          : {shear:10.6f}")
    print(f"Perspective distortion: {perspective_mag:10.8f}")
    print("====================================================\n")

    return post_full, pre_aligned, pre_coarse_aligned, warp_matrix, debug_data


# ── Backward compatibility alias (removed in a future version) ────────
refine_interior_ecc = refine_interior_sift
"""Deprecated alias for :func:`refine_interior_sift`. The function was
renamed because its body uses SIFT, not ECC, after the v2.1 rewrite.
Prefer the new name for new code."""

