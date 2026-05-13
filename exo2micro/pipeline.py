"""
pipeline.py
===========
The SampleDye class — the central object for processing one sample+dye
combination through the full exo2micro pipeline.

Each instance manages:
  - Current parameter state
  - Checkpoint file discovery and resume logic
  - Stage execution with automatic save/load
  - Directory structure creation
  - Plot generation and caching

Usage
-----
::

    import exo2micro as e2m

    run = e2m.SampleDye('CD070', 'SybrGld_microbe', output_dir='processed')
    run.set_params(boundary_width=20)
    run.run()                                    # resumes from latest checkpoint
    run.compare('boundary_width', [10, 15, 20])  # grid comparison
"""

import os
import numpy as np
import cv2

from .defaults import (DEFAULTS, ABBREVIATIONS, PARAM_STAGES, STAGE_NAMES,
                        STAGE_PARAMS, MAX_STAGE, build_suffix)
from .utils import (load_image_pair, save_checkpoint, load_checkpoint,
                    checkpoint_exists, pad_images, build_tissue_mask,
                    equalize_pair)
from .alignment import register_highorder, refine_interior_sift
from . import plotting


class SampleDye:
    """
    Pipeline controller for a single sample + dye combination.

    Manages parameter state, checkpoint files, and stage execution.
    Images are loaded from disk on demand and released after processing
    to preserve RAM.

    Parameters
    ----------
    sample : str
        Sample name, e.g. 'CD070'.
    dye : str
        Dye/channel name, e.g. 'SybrGld_microbe'.
    output_dir : str
        Root output directory (default 'processed').
    raw_dir : str
        Root directory containing raw images (default 'raw').
    checkpoint_format : {'tiff', 'fits', 'both'}
        Which file formats to write for each pipeline checkpoint
        (default ``'tiff'``). TIFF is the most widely-supported format
        for downstream inspection; FITS adds an ~equal-size copy with
        metadata in the header for provenance. ``'both'`` writes both.

        For loading (resume), this setting only governs what gets
        *written*. Reads are format-agnostic and will use whichever
        file exists — if both exist, TIFF is preferred for speed. A
        warning is printed when the loaded format differs from the
        configured save format, because the output directory will end
        up with mixed formats.
    """

    def __init__(self, sample, dye, output_dir='processed', raw_dir='raw',
                 checkpoint_format='tiff'):
        if checkpoint_format not in ('tiff', 'fits', 'both'):
            raise ValueError(
                f"checkpoint_format must be 'tiff', 'fits', or 'both', "
                f"got {checkpoint_format!r}")

        self.sample = sample
        self.dye = dye
        self.output_dir = output_dir
        self.raw_dir = raw_dir
        self.checkpoint_format = checkpoint_format

        # Current parameter state — start with all defaults
        self._params = dict(DEFAULTS)

        # Results from the most recent run (transient, not saved)
        self._results = {}

        # Track whether we've already emitted the "mixed formats"
        # warning for this run, so it only fires once per SampleDye
        # instance even if many checkpoints are in the non-preferred
        # format.
        self._mixed_format_warned = False

        # Create directory structure
        self._base_dir = os.path.join(output_dir, sample, dye)
        self._tiff_dir = os.path.join(self._base_dir, 'tiff')
        self._fits_dir = os.path.join(self._base_dir, 'fits')
        self._checks_dir = os.path.join(self._base_dir, 'pipeline_output')
        for d in [self._tiff_dir, self._fits_dir, self._checks_dir]:
            os.makedirs(d, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────
    # PARAMETER MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────

    @property
    def params(self):
        """Current parameter state as a dict."""
        return dict(self._params)

    def set_params(self, **kwargs):
        """
        Set one or more pipeline parameters.

        Only known parameter names are accepted. Unknown names raise ValueError.

        Parameters
        ----------
        **kwargs
            Parameter name=value pairs, e.g. boundary_width=20.
        """
        for key, value in kwargs.items():
            if key not in DEFAULTS:
                raise ValueError(
                    f"Unknown parameter '{key}'. "
                    f"Valid parameters: {list(DEFAULTS.keys())}")
            self._params[key] = value

    def reset_params(self):
        """Reset all parameters to their default values."""
        self._params = dict(DEFAULTS)

    def non_default_params(self, stage=None):
        """
        Return a dict of parameters that differ from their defaults.

        Parameters
        ----------
        stage : int or None
            If set, only return non-defaults for this stage and upstream.

        Returns
        -------
        dict
        """
        result = {}
        for key, default in DEFAULTS.items():
            if self._params[key] != default:
                if stage is not None and PARAM_STAGES[key] > stage:
                    continue
                result[key] = self._params[key]
        return result

    # ──────────────────────────────────────────────────────────────────────
    # FILENAME CONSTRUCTION
    # ──────────────────────────────────────────────────────────────────────

    def _suffix(self, stage):
        """Build the non-default parameter suffix for a given stage."""
        return build_suffix(self._params, stage)

    def _checkpoint_path(self, stage, name):
        """
        Build the base filepath for a checkpoint (no extension).

        Parameters
        ----------
        stage : int
            Pipeline stage number.
        name : str
            Descriptive name, e.g. 'post', 'pre', 'joint_mask'.

        Returns
        -------
        str
            Full path like 'processed/CD070/SybrGld/tiff/01_padded_post_bw20'
        """
        stage_name = STAGE_NAMES[stage]
        suffix = self._suffix(stage)
        filename = f'{stage_name}_{name}{suffix}'
        return os.path.join(self._tiff_dir, filename)

    def _checkpoint_base(self, stage, name):
        """
        Build the base filepath for save_checkpoint (routes to tiff/ and fits/).

        This returns a path under a virtual 'images/' subdirectory so that
        save_checkpoint can route to tiff/ and fits/ siblings.
        """
        stage_name = STAGE_NAMES[stage]
        suffix = self._suffix(stage)
        filename = f'{stage_name}_{name}{suffix}'
        # save_checkpoint expects parent to be 'images/' to route correctly
        # We'll pass directly to tiff/fits dirs instead
        return filename

    def _tiff_path(self, stage, name):
        """Full path to a TIFF checkpoint file."""
        base = self._checkpoint_base(stage, name)
        return os.path.join(self._tiff_dir, base + '.tiff')

    def _fits_path(self, stage, name):
        """Full path to a FITS checkpoint file."""
        base = self._checkpoint_base(stage, name)
        return os.path.join(self._fits_dir, base + '.fits')

    def _check_path(self, name):
        """Full path for a pipeline check plot."""
        suffix = self._suffix(MAX_STAGE)  # include all params
        return os.path.join(self._checks_dir, f'{name}{suffix}.png')

    def _has_checkpoint(self, stage, name):
        """Check if a checkpoint exists for the current parameters.

        Lenient: returns True if EITHER a TIFF or a FITS file exists
        at this checkpoint, regardless of the configured
        ``checkpoint_format``. This is what makes "tiff-only" runs
        able to resume from "both" runs and vice versa.
        """
        return (os.path.exists(self._tiff_path(stage, name)) or
                os.path.exists(self._fits_path(stage, name)))

    def _save_image(self, image, stage, name, extra_headers=None):
        """Save an image as a pipeline checkpoint.

        Writes TIFF, FITS, or both according to
        ``self.checkpoint_format``. FITS files always carry full
        metadata (sample, dye, stage, non-default parameters);
        TIFF files carry only the pixel data.
        """
        import tifffile
        from astropy.io import fits
        from datetime import datetime

        tiff_path = self._tiff_path(stage, name)
        fits_path = self._fits_path(stage, name)

        save_tiff = self.checkpoint_format in ('tiff', 'both')
        save_fits = self.checkpoint_format in ('fits', 'both')

        if save_tiff:
            tifffile.imwrite(tiff_path, image.astype(np.float32))
            print(f"  Saved: {tiff_path}")

        if save_fits:
            hdu = fits.PrimaryHDU(image.astype(np.float32))
            header = hdu.header
            header['SAMPLE'] = (self.sample, 'Sample name')
            header['DYE'] = (self.dye, 'Dye/channel name')
            header['STAGE'] = (STAGE_NAMES[stage], 'Pipeline stage')
            header['CREATED'] = (datetime.now().isoformat(),
                                 'File creation timestamp')

            # Record non-default parameters
            nd = self.non_default_params(stage)
            for key, value in nd.items():
                fits_key = ABBREVIATIONS.get(key, key[:8]).upper()
                if value is None:
                    header[fits_key] = ('None', key)
                elif isinstance(value, bool):
                    header[fits_key] = (value, key)
                else:
                    header[fits_key] = (value, key)

            if extra_headers:
                for key, value in extra_headers.items():
                    header[key[:8].upper()] = value

            hdu.writeto(fits_path, overwrite=True)
            print(f"  Saved: {fits_path}")

    def _load_image(self, stage, name):
        """Load a checkpoint file, or return None if neither format exists.

        Loads whichever format is present. When both exist, prefers
        TIFF for speed (FITS loading has parser overhead).

        If the loaded format differs from the configured
        ``checkpoint_format``, prints a one-time warning about mixed
        formats in the output directory.
        """
        import tifffile
        from astropy.io import fits

        tiff_path = self._tiff_path(stage, name)
        fits_path = self._fits_path(stage, name)

        tiff_exists = os.path.exists(tiff_path)
        fits_exists = os.path.exists(fits_path)

        if tiff_exists:
            image = tifffile.imread(tiff_path)
            print(f"  Loaded: {tiff_path}  shape={image.shape}")
            # If we loaded TIFF but the run is configured to save
            # FITS only, we're about to create mixed formats in this
            # directory.
            if (self.checkpoint_format == 'fits'
                    and not self._mixed_format_warned):
                print(f"  ⚠ Mixed-format warning: this directory already "
                      f"contains TIFF checkpoints from a previous run, "
                      f"but the current run is configured to save FITS "
                      f"only. New outputs will be FITS; existing TIFFs "
                      f"will remain. Delete old files or use "
                      f"checkpoint_format='both' to avoid a mix.")
                self._mixed_format_warned = True
            return image

        if fits_exists:
            with fits.open(fits_path) as hdul:
                image = np.asarray(hdul[0].data)
            print(f"  Loaded: {fits_path}  shape={image.shape}  "
                  f"(fell back to FITS — no TIFF at {tiff_path})")
            if (self.checkpoint_format == 'tiff'
                    and not self._mixed_format_warned):
                print(f"  ⚠ Mixed-format warning: this directory contains "
                      f"FITS checkpoints from a previous run, but the "
                      f"current run is configured to save TIFF only. "
                      f"New outputs will be TIFF; existing FITS files "
                      f"will remain. Delete old files or use "
                      f"checkpoint_format='both' to avoid a mix.")
                self._mixed_format_warned = True
            return image

        return None

    # ──────────────────────────────────────────────────────────────────────
    # STAGE EXECUTION
    # ──────────────────────────────────────────────────────────────────────

    def _preflight_format_check(self):
        """Scan checkpoint directories for mixed-format content.

        Emits a one-time pre-flight warning if the output directory
        already contains checkpoints in a format different from the
        one currently configured for writing. This runs once per
        :meth:`run` call, before any stage executes, so users see the
        warning at the top of the run output.
        """
        if self._mixed_format_warned:
            return

        wants_tiff = self.checkpoint_format in ('tiff', 'both')
        wants_fits = self.checkpoint_format in ('fits', 'both')

        has_tiff = False
        has_fits = False
        if os.path.isdir(self._tiff_dir):
            has_tiff = any(f.endswith('.tiff') or f.endswith('.tif')
                           for f in os.listdir(self._tiff_dir))
        if os.path.isdir(self._fits_dir):
            has_fits = any(f.endswith('.fits')
                           for f in os.listdir(self._fits_dir))

        problem = None
        if has_tiff and not wants_tiff:
            problem = ("this directory already contains TIFF checkpoints "
                       "from a previous run, but the current run is "
                       "configured to save FITS only")
        elif has_fits and not wants_fits:
            problem = ("this directory already contains FITS checkpoints "
                       "from a previous run, but the current run is "
                       "configured to save TIFF only")

        if problem:
            print(f"  ⚠ Mixed-format warning: {problem}.")
            print(f"     New outputs will be in the configured format; "
                  f"existing files will remain.")
            print(f"     Delete old files or use "
                  f"checkpoint_format='both' to avoid a mix.")
            self._mixed_format_warned = True

    def _check_upstream(self, target_stage):
        """
        Check that all upstream stages have checkpoints for current params.

        Returns a list of (stage, name) tuples that are missing.
        """
        missing = []
        stage_files = {
            1: ['post', 'pre'],
            2: ['pre'],
            3: ['pre'],
        }
        for stage in range(1, target_stage):
            if stage in stage_files:
                for name in stage_files[stage]:
                    if not self._has_checkpoint(stage, name):
                        missing.append((stage, name))
        return missing

    def run(self, from_stage=None, to_stage=None, force=False):
        """
        Run the pipeline, resuming from the latest available checkpoint.

        Stages
        ------
        1. Padding — load raw images onto a common padded canvas
        2. Coarse alignment — boundary correlation + ICP
        3. Interior alignment — SIFT feature matching refinement
        4. Diagnostics & subtraction — scale estimation, plots, difference image

        Parameters
        ----------
        from_stage : int or None
            Force re-run from this stage onward. If None, auto-detect.
        to_stage : int or None
            Stop after this stage. If None, run to completion.
        force : bool
            If True, re-run all stages even if checkpoints exist.

        Returns
        -------
        dict
            Results dict with status.
        """
        if from_stage is None:
            from_stage = 1
        if to_stage is None:
            to_stage = 4

        print(f"\n{'='*60}")
        print(f"  Sample: {self.sample}   Dye: {self.dye}")
        print(f"{'='*60}")

        nd = self.non_default_params()
        if nd:
            print(f"  Non-default parameters: {nd}")

        # Pre-flight mixed-format check. Scan the tiff/ and fits/
        # subdirectories for any existing checkpoint files in the
        # "wrong" format (i.e. a format different from what this run
        # is configured to save), and warn once up front so the user
        # knows the output directory will end up mixed. This
        # complements the per-file warning in _load_image, which
        # fires when a specific checkpoint is loaded from the
        # non-preferred format.
        self._preflight_format_check()

        try:
            # Stage 1: Padding
            if from_stage <= 1 and to_stage >= 1:
                self._run_stage_1_padding(force)

            # Stage 2: Coarse alignment (boundary correlation + ICP)
            if from_stage <= 2 and to_stage >= 2:
                self._run_stage_2_coarse(force)

            # Stage 3: Interior alignment (SIFT feature matching)
            if from_stage <= 3 and to_stage >= 3:
                self._run_stage_3_fine(force)

            # Stage 4: Diagnostics & subtraction
            if from_stage <= 4 and to_stage >= 4:
                self._run_stage_4_diagnostics(force)

            return {
                'sample': self.sample,
                'dye': self.dye,
                'scale_estimate': self._results.get('scale_estimate'),
                'scale_percentile_value':
                    self._results.get('scale_percentile_value'),
                'manual_scale': self._params.get('manual_scale'),
                'status': 'complete',
            }

        except Exception as e:
            print(f"  !! ERROR: {e}")
            import traceback
            traceback.print_exc()
            return {
                'sample': self.sample,
                'dye': self.dye,
                'status': f'error: {e}',
            }

    def _run_stage_1_padding(self, force=False):
        """Stage 1: Load raw images and pad them.

        Loads the pre-stain and post-stain raw TIFFs via
        :func:`load_image_pair`, which is strict about filename
        conventions and raises :class:`FileNotFoundError` or
        :class:`ValueError` with a multi-line diagnostic message when
        anything is wrong. Those exceptions propagate to
        :meth:`run`, which records them in the result dict so batch
        processing can continue with other (sample, dye) tasks.
        """
        if not force and self._has_checkpoint(1, 'post') and self._has_checkpoint(1, 'pre'):
            print("  Stage 1 (padding): checkpoints exist — skipping")
            return

        print("  Stage 1: Loading and padding images...")
        try:
            post_im, pre_im, post_path, pre_path = load_image_pair(
                self.sample, self.dye, self.raw_dir)
        except (FileNotFoundError, ValueError) as e:
            # Print a visible block before re-raising so the user
            # sees the full diagnostic message in context, not just
            # the one-line summary from the run() catch-all.
            print(f"\n  !! FILE PROBLEM for {self.sample} / {self.dye}:")
            for line in str(e).splitlines():
                print(f"     {line}")
            print()
            raise

        post_pad, pre_pad = pad_images(post_im, pre_im, pad=self._params['pad'])

        self._save_image(post_pad, 1, 'post')
        self._save_image(pre_pad, 1, 'pre')

        # Release raw images
        del post_im, pre_im, post_pad, pre_pad

    def _run_stage_2_coarse(self, force=False):
        """Stage 2: Boundary correlation + ICP alignment."""
        if not force and self._has_checkpoint(2, 'pre'):
            print("  Stage 2 (ICP alignment): checkpoint exists — skipping")
            return

        # Check upstream
        missing = self._check_upstream(2)
        if missing:
            print(f"  Stage 2: upstream checkpoints missing: {missing}")
            print("  Running Stage 1 first...")
            self._run_stage_1_padding(force=False)

        print("  Stage 2: Boundary correlation + ICP alignment...")
        post_pad = self._load_image(1, 'post')
        pre_pad = self._load_image(1, 'pre')

        post_full, pre_aligned, pre_coarse, warp_matrix, debug_data = \
            register_highorder(
                post_pad, pre_pad,
                use_edges=self._params['use_edges'],
                boundary_width=self._params['boundary_width'],
                boundary_smooth=self._params['boundary_smooth'],
                rotation_search=self._params['rotation_search'],
                angle_range=self._params['angle_range'],
                angle_step=self._params['angle_step'],
                scale_search=self._params['scale_search'],
                scale_min=self._params['scale_min'],
                scale_max=self._params['scale_max'],
                scale_step=self._params['scale_step'],
                multiscale=self._params['multiscale'],
                down_scale=self._params['down_scale'],
                fine_ecc=self._params['fine_ecc'],
                max_translation=self._params['max_translation'],
                max_rotation=self._params['max_rotation'],
                max_scale_delta=self._params['max_scale_delta'],
                max_scale_diff=self._params['max_scale_diff'],
                stopit=self._params['stopit'],
                stopdelta=self._params['stopdelta'],
            )

        # Save ICP-aligned pre at stage 2
        # (post-stain is the reference frame — saved once at stage 1)
        self._save_image(pre_aligned, 2, 'pre')

        # Optionally save coarse-only intermediate for diagnosis
        if self._params['save_all_intermediates'] and pre_coarse is not None:
            self._save_image(pre_coarse, 2, 'coarse_pre')

        # Store warp matrix and un-warped pre for stage 3
        self._results['warp_matrix'] = warp_matrix
        self._results['debug_data'] = debug_data
        self._results['pre_pad'] = pre_pad  # needed by stage 3 to re-warp

        # Generate pipeline check plots
        self._generate_alignment_plots(
            post_full, pre_aligned, pre_coarse, debug_data)

        # debug_data carries several downsampled image arrays used only
        # by _generate_alignment_plots above. Drop them now so they don't
        # sit in self._results for the rest of the run.
        self._results.pop('debug_data', None)

        # Release images (but keep pre_pad if stage 3 needs it)
        del post_pad, post_full, pre_aligned, pre_coarse, debug_data

    def _run_stage_3_fine(self, force=False):
        """Stage 3: Interior ECC refinement."""
        if not force and self._has_checkpoint(3, 'pre'):
            print("  Stage 3 (interior alignment): checkpoint exists — skipping")
            return

        if not self._params['interior_ecc']:
            print("  Stage 3 (interior alignment): interior_ecc=False — skipping")
            # Copy ICP pre as stage 3 output so downstream stages find it
            if not self._has_checkpoint(3, 'pre'):
                pre_icp = self._load_image(2, 'pre')
                if pre_icp is not None:
                    self._save_image(pre_icp, 3, 'pre')
                    del pre_icp
            return

        # Check upstream
        if not self._has_checkpoint(2, 'pre'):
            print("  Stage 3: upstream ICP alignment missing — running stage 2...")
            self._run_stage_2_coarse(force=False)

        print("  Stage 3: Interior ECC refinement...")
        post_full = self._load_image(1, 'post')

        # We need the un-warped pre to re-warp with the refined homography.
        # Try to get it from stage 2 results (in-memory), else load stage 1.
        pre_pad = self._results.get('pre_pad')
        if pre_pad is None:
            pre_pad = self._load_image(1, 'pre')
        if pre_pad is None:
            print("  !! Cannot find un-warped pre-stain — "
                  "falling back to ICP result")
            pre_icp = self._load_image(2, 'pre')
            self._save_image(pre_icp, 3, 'pre')
            del post_full, pre_icp
            return

        # Get the ICP warp matrix
        warp_icp = self._results.get('warp_matrix')
        if warp_icp is None:
            # Can't recover the warp matrix without re-running stage 2
            print("  !! Warp matrix not in memory — cannot run interior ECC")
            print("    → Re-run from stage 2 to enable interior ECC: "
                  "run.run(from_stage=2, force=True)")
            pre_icp = self._load_image(2, 'pre')
            self._save_image(pre_icp, 3, 'pre')
            del post_full, pre_icp, pre_pad
            return

        # Run interior SIFT refinement
        warp_refined, ecc_result = refine_interior_sift(
            post_full, pre_pad.astype(np.float32),
            warp_init=warp_icp,
            interior_blur_base=self._params['interior_blur_base'],
            interior_max_correction=self._params['interior_max_correction'],
            interior_min_inlier_ratio=self._params['interior_min_inlier_ratio'],
        )

        # Warp pre with refined homography
        h, w = post_full.shape
        pre_refined = cv2.warpPerspective(
            pre_pad.astype(np.float32), warp_refined, (w, h),
            flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

        # Save stage 3 pre (post-stain is the reference — use 01_padded_post)
        accuracy = ecc_result['estimated_accuracy_px']
        if not np.isfinite(accuracy):
            accuracy = -1.0  # sentinel: no valid estimate
        self._save_image(pre_refined, 3, 'pre',
                         extra_headers={
                             'IACC': (accuracy,
                                      'Interior alignment accuracy estimate (px)'),
                             'ILVLOK': (ecc_result['levels_completed'],
                                        'Interior ECC levels completed'),
                         })

        # If interior ECC had a failure, ensure ICP pre is saved for diagnosis
        if not ecc_result['success'] or \
                ecc_result['levels_completed'] < ecc_result['total_levels']:
            if not self._has_checkpoint(2, 'pre'):
                pre_icp = cv2.warpPerspective(
                    pre_pad.astype(np.float32), warp_icp, (w, h),
                    flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
                self._save_image(pre_icp, 2, 'pre')
                del pre_icp

        # Store results
        self._results['warp_matrix_interior'] = warp_refined
        self._results['interior_ecc_result'] = ecc_result

        # Release memory
        del post_full, pre_pad, pre_refined
        self._results.pop('pre_pad', None)  # no longer needed

    def _run_stage_4_diagnostics(self, force=False):
        """Stage 4: Diagnostic plots and scaled difference image(s).

        Always generates the five standard diagnostic plots
        (pre/post heatmap, excess heatmap, pre/post histograms, difference
        histogram, ratio histogram with Moffat fit) and a difference image
        using the Moffat-fit scale estimate.

        When ``scale_percentile`` is set, additionally computes that
        percentile of the log10(post/pre) distribution as an alternative
        scale and produces a corresponding difference image.

        When ``manual_scale`` is set, additionally produces a difference
        image using that exact value.

        The excess heatmap shows all active scale lines overplotted.
        """
        # Load aligned images once
        print("  Stage 4: Diagnostics and difference image(s)...")
        post_full = self._load_image(1, 'post')
        pre_aligned = self._load_image(3, 'pre')
        if pre_aligned is None:
            pre_aligned = self._load_image(2, 'pre')
        if post_full is None or pre_aligned is None:
            raise RuntimeError(
                "Stage 4: missing upstream checkpoint(s). "
                "Run from_stage=1 to regenerate.")

        print(f"  Image size: {post_full.shape[0]:,} x {post_full.shape[1]:,} "
              f"({post_full.size:,} pixels)")

        import matplotlib
        matplotlib.use('Agg')

        # ── Standard diagnostic plots ────────────────────────────────────
        heatmap_path = self._check_path('pre_post_heatmap')
        hist_path = self._check_path('pre_post_histograms')
        diff_hist_path = self._check_path('difference_histogram')
        ratio_hist_path = self._check_path('ratio_histogram')
        excess_path = self._check_path('excess_heatmap')
        diff_img_path = self._check_path('difference_image')

        # 2-D heatmap: pre vs post brightness
        if force or not os.path.exists(heatmap_path):
            plotting.plot_pre_post_heatmap(
                post_full, pre_aligned,
                sample=self.sample, dye=self.dye,
                save_path=heatmap_path)

        # Overlapping histograms: pre and post distributions
        if force or not os.path.exists(hist_path):
            plotting.plot_pre_post_histograms(
                post_full, pre_aligned,
                sample=self.sample, dye=self.dye,
                save_path=hist_path)

        # Difference histogram: post - pre (unscaled)
        if force or not os.path.exists(diff_hist_path):
            plotting.plot_difference_histogram(
                post_full, pre_aligned,
                sample=self.sample, dye=self.dye,
                save_path=diff_hist_path)

        # Ratio histogram with Moffat fit → canonical scale estimate
        scale_moffat = self._results.get('scale_estimate')
        if force or not os.path.exists(ratio_hist_path) or scale_moffat is None:
            _, scale_moffat = plotting.plot_ratio_histogram_simple(
                post_full, pre_aligned,
                sample=self.sample, dye=self.dye,
                save_path=ratio_hist_path)
            self._results['scale_estimate'] = scale_moffat

        if scale_moffat is None or not np.isfinite(scale_moffat):
            raise RuntimeError(
                "Stage 4: could not estimate a scale factor from the "
                "post/pre ratio distribution.")

        # ── Alternative scales from user parameters ─────────────────────
        scale_percentile_param = self._params.get('scale_percentile')
        manual_scale_param = self._params.get('manual_scale')

        scale_entries = [('Moffat fit', float(scale_moffat), '#00cc88')]

        if scale_percentile_param is not None:
            sp_value = self._compute_scale_percentile(
                post_full, pre_aligned, float(scale_percentile_param))
            if sp_value is not None:
                label = f'ratio p{scale_percentile_param:g}'
                scale_entries.append((label, sp_value, '#ff9933'))
                self._results['scale_percentile_value'] = sp_value
                print(f"  Scale (ratio p{scale_percentile_param:g}): "
                      f"{sp_value:.4f}")

        if manual_scale_param is not None:
            scale_entries.append(
                ('manual', float(manual_scale_param), '#ff3366'))
            print(f"  Scale (manual): {float(manual_scale_param):.4f}")

        # ── Excess heatmap with all active scale lines ──────────────────
        # Always regenerate when alternative scales are active, so the
        # overlay reflects the current parameter state.
        need_excess = (force
                       or not os.path.exists(excess_path)
                       or len(scale_entries) > 1)
        if need_excess:
            plotting.plot_excess_heatmap(
                post_full, pre_aligned,
                scales=scale_entries,
                sample=self.sample, dye=self.dye,
                save_path=excess_path)

        # ── Difference image for each active scale ─────────────────────
        # Canonical (Moffat) difference image
        self._save_difference(
            post_full, pre_aligned, scale_moffat,
            label='moffat',
            force=force)

        # scale_percentile variant
        if (scale_percentile_param is not None
                and self._results.get('scale_percentile_value') is not None):
            sp_value = self._results['scale_percentile_value']
            self._save_difference(
                post_full, pre_aligned, sp_value,
                label=f'percentile_p{scale_percentile_param:g}',
                force=force)

        # manual_scale variant
        if manual_scale_param is not None:
            self._save_difference(
                post_full, pre_aligned, float(manual_scale_param),
                label='manual',
                force=force)

        # Drop transient cross-stage state. By the time stage 4 finishes,
        # the warp matrices and ECC bookkeeping from stages 2 and 3 are
        # no longer needed; only the small scalar scale estimates need
        # to survive into the return dict from run().
        for key in ('warp_matrix', 'warp_matrix_interior',
                    'interior_ecc_result', 'pre_pad', 'debug_data'):
            self._results.pop(key, None)

        del post_full, pre_aligned

    def _compute_scale_percentile(self, post_im, pre_im, percentile):
        """
        Compute the requested percentile of the log10(post/pre) distribution.

        Parameters
        ----------
        post_im, pre_im : ndarray (2-D)
        percentile : float
            Percentile in 0-100, e.g. 99.1.

        Returns
        -------
        float or None
            Scale factor (linear units), or None if no valid pixels.
        """
        post = post_im.ravel().astype(np.float64)
        pre = pre_im.ravel().astype(np.float64)
        both = (post > 0) & (pre > 0)
        if not np.any(both):
            print("  _compute_scale_percentile: no overlap — skipping")
            return None
        ratio = post[both] / pre[both]
        log_ratio = np.log10(ratio)
        p_log = float(np.percentile(log_ratio, percentile))
        return float(10 ** p_log)

    def _save_difference(self, post_full, pre_aligned, scale,
                         label, force):
        """
        Compute and save a difference image for one scale value.

        Writes TIFF, FITS (with SCALE header), and a PNG visualization.

        When ``label == 'moffat'`` the canonical filenames are used:
            {tiff_dir}/04_difference_difference{suffix}.tiff
            {fits_dir}/04_difference_difference{suffix}.fits
            {checks_dir}/difference_image{suffix}.png

        For alternative scales (``label`` = ``'manual'``,
        ``'percentile_p99.1'``, etc.), the label is inserted into the
        filename so that all variants coexist:
            04_difference_difference_{label}{suffix}.tiff
            difference_image_{label}{suffix}.png

        Parameters
        ----------
        post_full, pre_aligned : ndarray (2-D)
        scale : float
        label : str
            Short label identifying the scale kind. 'moffat' uses the
            canonical filenames; anything else is inserted into the name.
        force : bool
            If True, regenerate even if files exist.
        """
        import tifffile
        from astropy.io import fits
        from datetime import datetime

        suffix = self._suffix(MAX_STAGE)
        stage_name = STAGE_NAMES[MAX_STAGE]

        if label == 'moffat':
            tiff_path = self._tiff_path(MAX_STAGE, 'difference')
            fits_path = self._fits_path(MAX_STAGE, 'difference')
            png_path = self._check_path('difference_image')
        else:
            base = f'{stage_name}_difference_{label}{suffix}'
            tiff_path = os.path.join(self._tiff_dir, base + '.tiff')
            fits_path = os.path.join(self._fits_dir, base + '.fits')
            png_path = os.path.join(
                self._checks_dir,
                f'difference_image_{label}{suffix}.png')

        already_exists = (os.path.exists(tiff_path)
                          and os.path.exists(fits_path)
                          and os.path.exists(png_path))
        if already_exists and not force:
            print(f"  Difference ({label}): files exist — skipping")
            return

        print(f"  Computing difference ({label}): "
              f"post − {scale:.4f} × pre")
        diff_im = (post_full.astype(np.float32)
                   - float(scale) * pre_aligned.astype(np.float32))

        # TIFF
        tifffile.imwrite(tiff_path, diff_im.astype(np.float32))
        print(f"  Saved: {tiff_path}")

        # FITS with metadata
        hdu = fits.PrimaryHDU(diff_im.astype(np.float32))
        header = hdu.header
        header['SAMPLE'] = (self.sample, 'Sample name')
        header['DYE'] = (self.dye, 'Dye/channel name')
        header['STAGE'] = (STAGE_NAMES[MAX_STAGE], 'Pipeline stage')
        header['CREATED'] = (datetime.now().isoformat(),
                             'File creation timestamp')
        header['SCALE'] = (float(scale),
                           f'Scale factor ({label})')
        header['SCALEK'] = (label[:68], 'Scale kind')

        # Record non-default parameters
        nd = self.non_default_params(MAX_STAGE)
        for key, value in nd.items():
            fits_key = ABBREVIATIONS.get(key, key[:8]).upper()
            if value is None:
                header[fits_key] = ('None', key)
            elif isinstance(value, bool):
                header[fits_key] = (value, key)
            else:
                header[fits_key] = (value, key)

        hdu.writeto(fits_path, overwrite=True)
        print(f"  Saved: {fits_path}")

        # PNG visualization
        plotting.plot_difference_image(
            post_full, pre_aligned, float(scale),
            sample=self.sample, dye=self.dye,
            save_path=png_path)

    def _generate_alignment_plots(self, post_full, pre_aligned, pre_coarse,
                                  debug_data):
        """
        Generate stage 2 alignment diagnostic plots.

        Writes ``registration.png`` (four-panel overview from debug_data)
        and, if ``pre_coarse`` is available, ``fine_alignment.png``
        (coarse vs ICP comparison).
        """
        import matplotlib
        matplotlib.use('Agg')

        # Registration overview from debug_data stages
        stages = debug_data.get('stages') if debug_data else None
        if stages:
            try:
                plotting.plot_registration(
                    stages,
                    sample=self.sample, dye=self.dye,
                    save_path=self._check_path('registration'))
            except Exception as e:
                print(f"  plot_registration failed (non-fatal): {e}")

        # Coarse vs ICP comparison (only when coarse intermediate is kept)
        if pre_coarse is not None and stages:
            try:
                coarse = stages[0]
                post_raw = coarse.get('post_raw')
                post_bnd = coarse.get('post_edges')
                pre_bnd_pre = coarse.get('pre_edges_pre')
                pre_bnd_after = coarse.get('pre_edges')
                if post_raw is not None:
                    plotting.plot_fine_alignment(
                        post_raw,
                        coarse.get('pre_warped', post_raw),
                        coarse.get('pre_warped', post_raw),
                        post_bnd, pre_bnd_pre, pre_bnd_after,
                        sample=self.sample, dye=self.dye,
                        save_path=self._check_path('fine_alignment'))
            except Exception as e:
                print(f"  plot_fine_alignment failed (non-fatal): {e}")

    # ──────────────────────────────────────────────────────────────────────
    # COMPARISON
    # ──────────────────────────────────────────────────────────────────────

    def compare(self, param_name, values, save=False):
        """
        Compare the effect of varying a single parameter.

        Generates a grid of plots showing the effect of each value on
        either the alignment or the final difference image.

        Parameters
        ----------
        param_name : str
            Parameter to vary.
        values : list
            Values to try.
        save : bool
            If True, save each variant's checkpoints. If False, display
            only (default False).

        Returns
        -------
        list of dict
            Results for each parameter value.
        """
        if param_name not in DEFAULTS:
            raise ValueError(f"Unknown parameter '{param_name}'")

        original_value = self._params[param_name]
        results = []

        for value in values:
            print(f"\n--- Comparing {param_name}={value} ---")
            self._params[param_name] = value
            stage = PARAM_STAGES[param_name]

            if save:
                result = self.run(from_stage=stage, force=True)
            else:
                result = self.run(from_stage=stage, force=True)

            results.append({
                'value': value,
                'result': result,
            })

        # Restore original value
        self._params[param_name] = original_value

        return results

    # ──────────────────────────────────────────────────────────────────────
    # STATUS / INFO
    # ──────────────────────────────────────────────────────────────────────

    def status(self):
        """
        Print a summary of which checkpoints exist for current parameters.
        """
        print(f"\nPipeline status: {self.sample} / {self.dye}")
        print(f"  Output directory: {self._base_dir}")
        nd = self.non_default_params()
        if nd:
            print(f"  Non-default params: {nd}")
        else:
            print(f"  All parameters at defaults")

        stage_files = {
            1: ['post', 'pre'],
            2: ['pre'],
            3: ['pre'],
            4: ['difference'],
        }
        for stage, names in stage_files.items():
            stage_name = STAGE_NAMES[stage]
            for name in names:
                exists = self._has_checkpoint(stage, name)
                marker = '\u2713' if exists else '\u2717'
                path = self._tiff_path(stage, name)
                print(f"  [{marker}] {stage_name}_{name}: "
                      f"{os.path.basename(path)}")

        # Check for diagnostic plots
        diag_plots = ['pre_post_heatmap', 'pre_post_histograms',
                      'difference_histogram', 'ratio_histogram',
                      'excess_heatmap', 'difference_image']
        for name in diag_plots:
            path = self._check_path(name)
            exists = os.path.exists(path)
            marker = '\u2713' if exists else '\u2717'
            print(f"  [{marker}] {name}.png")

    def __repr__(self):
        nd = self.non_default_params()
        nd_str = f', params={nd}' if nd else ''
        return f"SampleDye('{self.sample}', '{self.dye}'{nd_str})"
