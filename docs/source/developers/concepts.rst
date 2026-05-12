Conceptual Overview
===================

This page explains how exo2micro works at the design level — what
each pipeline stage does, why, and the key decisions that shaped
the current implementation. Read this if you're going to modify
the pipeline, write processing code on top of it, or debug
unusual samples.

The problem
-----------

Given two fluorescence microscopy images of the same mineral
sample:

- **Pre-stain**: autofluorescent mineral background only.
- **Post-stain**: same thing, plus whatever microbes took up the
  stain.

We want:

.. code-block:: text

   microbes = post − scale × aligned_pre

Two non-trivial subproblems:

1. **Alignment.** The pre-stain and post-stain images are not
   aligned pixel-for-pixel — the sample can shift, rotate, be
   imaged at slightly different magnifications, and deform
   slightly between the two imaging sessions.
2. **Scale estimation.** The autofluorescent background itself
   has slightly different absolute brightness between pre-stain
   and post-stain (for reasons unrelated to microbes), so a
   simple ``post − pre`` subtraction doesn't work. We need to
   estimate a scale factor.

exo2micro solves alignment with a four-stage multi-resolution
pipeline and scale estimation with a Moffat fit on the log-ratio
distribution, with optional user-specified alternatives.

Pipeline stages
---------------

Stage 1 — Padding
~~~~~~~~~~~~~~~~~

**Input:** raw TIFFs from disk.

**Work:** load each TIFF, auto-detect which RGB channel(s) carry
fluorescence signal, extract at full 8-bit precision, and place
both images on a common zero-padded canvas.

**Channel auto-detection.** The old code used
``PIL.Image.convert("L")`` to grayscale raw TIFFs, applying
luminance weights ``0.299R + 0.587G + 0.114B``. For fluorescence
images where signal lives in one channel (e.g. green for SybrGold,
blue for DAPI, red for Cy5), this discarded ~41% of the dynamic
range. The v2.2 rewrite introduced ``_extract_signal_channel()``,
which compares per-channel means and extracts the signal-bearing
channel(s) directly. Multi-channel dyes (Spy700, etc.) have their
active channels summed.

**Padding.** Each image is centred on a zero canvas with
``pad`` pixels added on all sides (default 2000). This gives the
later alignment search room to translate the pre-stain without
running off the edge.

**Output:** ``01_padded_post.tiff`` and ``01_padded_pre.tiff``.
Post-stain is the reference frame throughout the pipeline and is
never transformed — it's saved exactly once here.

Stage 2 — Boundary alignment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Input:** padded pre and post images.

**Work:** find a rigid (translation + rotation + isotropic scale)
transform that best overlaps the tissue boundary between the two
images, then refine with ICP.

**Why match on the boundary rather than the whole image?** The
pre-stain and post-stain interiors look different — the whole
point of staining is that the post-stain image has new
fluorescence in places the pre-stain doesn't. Feature-based
methods applied naively to the full image will be pulled around
by this difference. The outer tissue boundary, by contrast, is
the same in both images (modulo drift between imaging sessions).
Matching it avoids being confused by fluorescence differences.

**Algorithm.**

1. Downsample both images to a coarse resolution (~0.3×).
2. Extract the sample boundary as a soft ring
   (``_extract_boundary`` in ``alignment.py``) of controllable
   thickness and smoothness.
3. Search over rotations and isotropic scales. For each
   ``(angle, scale)`` candidate, use phase correlation to find
   the best translation and score the overlap.
4. Pick the winning transform.
5. **ICP refinement.** Extract contour points from both boundary
   rings, then iteratively find nearest-neighbour correspondences
   and fit a refined rigid transform. This corrects the small
   residual errors the coarse search misses.
6. Sanity-check the ICP result against bounds
   (``max_translation``, ``max_rotation``, ``max_scale_delta``,
   ``max_scale_diff``) to reject degenerate matches.

**Output:** ``02_icp_aligned_pre.tiff``. Optionally (with
``save_all_intermediates=True``): ``02_icp_aligned_coarse_pre.tiff``,
useful for diagnosing whether the coarse pass or the ICP pass
went wrong.

Stage 3 — Interior alignment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Input:** ICP-aligned pre, original post.

**Work:** refine the boundary-based alignment by matching SIFT
features in the tissue interior.

**Why a second alignment stage?** For large images, small angular
errors left over from stage 2 compound into significant interior
offsets (~20-50 pixels) even when the boundary looks well-aligned.
Stage 3 fixes this.

**Why SIFT instead of ECC?** Stage 3 was originally implemented
as an ECC (Enhanced Correlation Coefficient) pyramid on the
downsampled image. ECC performed poorly for this application:
the ~3× staining intensity difference between pre and post
creates a correlation landscape where ECC converges to ``cc ≈ 0.6``
regardless of alignment quality, making it useless as a quality
metric. Intensity equalization, multiscale pyramids, masking, and
phase correlation were all tried without success. SIFT sidesteps
the problem entirely by operating on local gradient structure —
features like tissue edges and texture transitions are
well-defined in both images even though the absolute brightnesses
differ, and microbe-only features (present in post but not in pre)
are naturally rejected as outlier matches by RANSAC.

**Algorithm.**

1. Downsample to the working scale and warp pre-stain by the
   stage-2 ICP homography so the images are already roughly
   aligned.
2. Apply a Gaussian blur (default sigma 8.0, controlled by
   ``interior_blur_base``) to suppress microbe-scale features
   that would otherwise corrupt the feature matching.
3. Convert to uint8 with percentile stretching for SIFT
   compatibility.
4. Detect up to 5000 SIFT features in each image.
5. Match with FLANN + Lowe's ratio test (threshold 0.7).
6. Compute a refined homography via RANSAC (reprojection
   threshold 3.0 px, confidence 0.999).
7. Sanity-check: total correction below ``interior_max_correction``
   (default 500 full-res pixels), inlier ratio above
   ``interior_min_inlier_ratio`` (default 0.4).
8. On failure, fall back to the stage 2 ICP result.

**Output:** ``03_interior_aligned_pre.tiff`` with an estimated
accuracy stored in the FITS ``IACC`` header (median inlier
reprojection error in pixels, or ``-1.0`` if the fit failed).

Stage 4 — Diagnostics and subtraction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Input:** post (stage 1) and best-available aligned pre (stage 3
preferred, stage 2 as fallback).

**Work:**

1. Generate the five standard diagnostic plots:
   ``pre_post_heatmap``, ``pre_post_histograms``,
   ``difference_histogram``, ``ratio_histogram``, and
   ``excess_heatmap``. These are functions of the pre/post data
   alone and are always produced.
2. Fit a Moffat profile to the log-ratio distribution to estimate
   the background scale factor (see :doc:`scale_methods`).
3. Compute the Moffat-scale difference image and save it as TIFF,
   FITS (with ``SCALE`` header), and PNG.
4. If ``scale_percentile`` is set, additionally compute that
   percentile of the log-ratio distribution as an alternative
   scale, produce a second difference image for it, and overplot
   its scale line on the excess heatmap.
5. If ``manual_scale`` is set, produce a third difference image
   using that exact value and overplot it on the excess heatmap.

**Why no masking stage?** exo2micro 2.1 and earlier had a stage 4
"joint tissue mask" that built a binary mask of pixels with
signal in both images and used that mask to restrict scale
estimation. The new pipeline doesn't need it: the Moffat fit
operates on pixels where both images have signal directly, and
the diagnostic heatmap already excludes zero-valued pixels. The
masking stage was deleted in v2.2.

Design principles
-----------------

**Post-stain is the reference frame.** It is never transformed.
Only the pre-stain is warped, so every alignment stage writes a
new pre-stain TIFF and leaves ``01_padded_post.tiff`` as the
single canonical post-stain file. This makes blink comparison
trivial — you always flip between ``01_padded_post`` and a
stage-N pre.

**Checkpoint-driven, resume-by-default.** Every stage saves both
TIFF (full precision) and FITS (with metadata headers) at the
end, and every stage skips itself if its output already exists
for the current parameter configuration. Re-running a completed
pipeline does nothing. This enables parameter sweeps, iterative
debugging, and recovery from crashes mid-batch.

**Parameters flow into filenames.** Non-default parameter values
are embedded in checkpoint filenames as a suffix
(``02_icp_aligned_pre_bw20_bs15.tiff``). Default values are
omitted, so a fresh run with defaults produces clean short
filenames, while parameter variants coexist in the same
directory without overwriting each other. See
:doc:`parameters` for the full abbreviation table.

**Decoupled compute and plotting.** Stage functions produce data;
plotting functions render data. No stage function creates
matplotlib figures directly — they call out to plotting functions
in ``exo2micro.plotting``. This means you can reuse the compute
side in a Jupyter notebook for custom analysis without the
pipeline trying to save PNGs you don't want.

**Legacy code lives in legacy.py.** Anything deprecated is moved
to ``exo2micro.legacy`` rather than deleted outright, with
``.. deprecated::`` notes pointing at the current equivalent.
This includes the old LS/robust-percentile scaling code
(formerly ``scaling.py``), the old masking helpers, and the old
plotting functions that used full-resolution contour overlays
(which crashed matplotlib on 30000×25000 images).
