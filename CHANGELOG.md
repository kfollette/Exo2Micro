# Changelog

This file summarizes notable changes across exo2micro 2.x. For
upgrading existing code and scripts, see `docs/source/migration.rst`.

## Version 2.3.0 — Current release

### Output folder simplification and visualisation

- **Renamed** ``pipeline_checks/`` → ``pipeline_output/``. All
  diagnostic PNGs (heatmaps, histograms, ratio fit, difference
  image visualisations, saved zoom views) are written here. References
  in code and documentation updated accordingly.
- **Removed** ``difference_plots/`` subdirectory. It was created by
  ``SampleDye.__init__`` but never actually written to — the
  ``compare()`` method had a dead "Save comparison plot" block that
  computed a path and printed "saved" without calling ``savefig``.
  Both the directory and the dead block are gone.
- **Removed** ``SampleDye._diff_path`` method and ``_diff_dir``
  attribute. The output folder structure is now exactly three
  subdirectories: ``tiff/``, ``fits/``, ``pipeline_output/``.
- **New diverging colormap** for difference plots and the excess
  heatmap. Goes blue (negative extreme) → dark blue → black (zero) →
  dark red → red (positive extreme), with white for masked / NaN
  cells. The black centre keeps near-zero values dim so genuine
  signal at the extremes pops; this replaces the old "psychedelic"
  green-purple-yellow custom colormap. Both ``plot_excess_heatmap``
  and ``plot_difference_image`` use the new colormap, giving them a
  consistent visual language across the diagnostic suite.
- ``plot_excess_heatmap`` now also masks empty cells (where both
  ``grid[i,j]`` and ``grid[j,i]`` are zero) to NaN, so empty regions
  render as white instead of as the colormap's black centre. Without
  this, "no data" and "data == 0" would have looked identical under
  the new black-centred colormap.

### Pipeline and API cleanup

- **Removed dead parameters** `interior_levels` and
  `interior_mask_percentile`. Both were kwargs on the (now-renamed)
  interior alignment function that served no purpose after the v2.1
  rewrite — they were retained for API compatibility with the
  removed ECC pyramid implementation. The GUI no longer shows them
  in the advanced parameters tab, and they no longer appear in
  ``PARAMETER_REGISTRY`` or ``DEFAULTS``. The parameter count is
  now 27, down from 29.
- **Renamed** ``refine_interior_ecc`` to ``refine_interior_sift`` in
  ``alignment.py``. The function name was a historical artifact —
  the body uses SIFT feature matching, not ECC, and has done so
  since v2.1. A backward-compatibility alias
  ``refine_interior_ecc = refine_interior_sift`` is retained for
  one version. New code should use the new name.
- **Fine ECC pass grouped as "Stage 2.5"** in the GUI. The opt-in
  ``fine_ecc`` parameter and its two companions (``stopit``,
  ``stopdelta``) now appear in their own tab labeled
  "Stage 2.5 — Fine ECC (optional)" between Stage 2 and Stage 3 in
  the Advanced Parameters accordion. Technically they still affect
  stage 2 (the ECC pass runs after ICP, before stage 3); the 2.5
  grouping is purely cosmetic to keep the optional/rarely-used
  parameters visually separated from the always-on Boundary + ICP
  tuning knobs. Added the ``PARAM_GROUPS`` dict in ``defaults.py``
  as the mechanism for this mapping.

### Persistent run log

- The GUI's output widget is in-memory only — content is lost when
  the kernel restarts or the notebook is closed. New **persistent
  run log file** at ``{output_dir}/.exo2micro_run_log.txt`` is
  appended to on every ``_log`` call, so a full transcript of every
  run survives kernel restarts.
- **Full pipeline output capture.** A new ``TeeStdout`` context
  manager in ``utils.py`` mirrors stdout to the log file during a
  pipeline run, so EVERY printed line is captured — including
  library-internal prints from ``pipeline.py`` and ``alignment.py``
  (stage banners, ICP iterations, scale-response surfaces, SIFT
  matching, etc.) — not just the GUI's own banner messages. The
  ``_log`` method detects when the tee is active and suppresses its
  explicit file append to avoid duplicating each line. Without this
  capture path the persistent log only contained the high-level
  ``_log()`` calls (about a dozen lines per run); now it contains
  the complete transcript.
- New "📄 View Prev Log" button in the Run pane action button row
  loads the last 500 lines of the log into the main output area on
  demand. Useful for recovering run output after closing and
  reopening the notebook.
- New helper functions in ``utils.py``: ``get_run_log_path``,
  ``append_to_run_log``, ``read_run_log_tail``, ``clear_run_log``,
  ``TeeStdout``. All exported from the top-level package.

### GUI layout consolidation

- **Three top-level panes** on first open: Input Selection, Run,
  and Full Output Log. Everything that used to be a separate pane
  (Scale Method, Output Format, Execution Options, Advanced
  Parameters) is now a collapsible sub-accordion inside the Run
  pane, starting collapsed — users see only the Run button and
  basic controls until they explicitly open a sub-accordion to
  tune something.
- **Optional sections collapsed** by default. Parameter Comparison,
  Zoom & Inspect, and Blink Comparison are each wrapped in their
  own collapsed accordion with "(Optional)" appended to the title.
  Users can ignore them entirely without them taking up screen
  space.
- The per-section mini-outputs for Scale Method, Output Format,
  and Execution Options have been removed (they were redundant
  once those sections became sub-accordions inside Run). Only the
  Input Selection and Run mini-outputs remain. The Full Output
  Log at the bottom of the GUI still captures every line from
  every operation.

### Pipeline and API

- New parameter `scale_percentile` (float, default `None`) in stage 4.
  When set, stage 4 additionally computes the requested percentile of
  the `log10(post/pre)` distribution as an alternative scale factor and
  produces a separate difference image using it. Replaces the old
  `robust_percentile` under a clearer name.
- New parameter `manual_scale` (float, default `None`) in stage 4.
  When set, stage 4 additionally produces a difference image using the
  exact user-supplied scale factor.
- All three scale variants (Moffat-fit, percentile, manual) can coexist
  in the same run and produce distinct TIFF, FITS, and PNG outputs. The
  `plot_excess_heatmap` plot overplots all active scale lines in
  different colours for side-by-side comparison.
- `SampleDye.run` now returns a richer result dict: `scale_estimate`,
  `scale_percentile_value`, and `manual_scale` in addition to `sample`,
  `dye`, and `status`.

### File loading and filename validation

- **Strict filename rules** for raw images. The loader now requires
  each filename to contain `pre` or `post` (case-insensitive) and end
  with `_<DyeName>.tif` or `.tiff`, where the dye name contains no
  underscores. See `docs/source/users/installation.rst` for the full
  specification and examples.
- `load_image_pair` is now strict: it **raises** `FileNotFoundError`
  (missing sample directory, missing pair, or only one side found) or
  `ValueError` (duplicate pre/post files for the same dye) with a
  multi-line diagnostic message instead of silently returning `None`
  placeholders. Callers get a clear explanation of what's wrong and
  how to fix it.
- New helper `classify_raw_files(sample_dir)` returns a
  `(pairs, warnings)` tuple describing every dye in the directory
  and any per-file problems. Non-raising — use it for directory
  inspection without committing to a load.
- **Partial-success batch behaviour.** A failed `(sample, dye)` task
  no longer blocks its siblings. Other dyes in the same directory and
  other samples in the batch continue processing; every failure is
  reported mid-stream with a "FILE PROBLEM" block and collected in a
  new "PROBLEMS" section at the bottom of the summary table.
- **GUI auto-detect rewrite.** The auto-detect button now scans all
  samples (previously capped at the first 5), uses `classify_raw_files`
  for robust parsing instead of ad-hoc string splitting, handles
  `.tif`/`.tiff` and case-insensitive `pre`/`post`, and surfaces any
  filename problems in the output panel with an amber status pill.
- **GUI and batch summary tables** now include a "PROBLEMS" section
  after the main table listing each failed task with the full
  multi-line error message, so users running large batches see every
  failure consolidated in one place.

### Checkpoint file format selection

- New ``checkpoint_format`` kwarg on :class:`SampleDye`
  (``'tiff'``, ``'fits'``, or ``'both'``, default ``'tiff'``).
  Controls which file format each intermediate pipeline checkpoint is
  saved as. Default changed from "both" (v2.2 behaviour) to ``'tiff'``
  only, roughly halving disk usage for typical runs.
- **Lenient resume across formats.** ``_has_checkpoint`` now returns
  True if either a TIFF or a FITS file exists at the checkpoint path,
  regardless of the configured save format. This means a ``'tiff'``
  run can pick up where a previous ``'fits'`` run left off (and vice
  versa).
- **Format-agnostic loading.** ``_load_image`` reads whichever format
  is present on disk (preferring TIFF when both exist for faster
  reads). The format the user asked to save is not required to match
  the format on disk.
- **Mixed-format warnings.** When a run loads a checkpoint in the
  non-configured format, a one-time warning prints explaining that
  the output directory will end up with mixed formats. A pre-flight
  scan at the start of ``SampleDye.run()`` also fires once if the
  output directory already contains checkpoints in the non-configured
  format, so users see the warning at the top of the run output.
- **GUI support.** New "📝 Output Format" top-level section with a
  radio button for tiff / fits / both, defaulting to tiff. Observer
  wired to the disk-space estimate so switching format updates the
  estimate immediately.
- **Batch API passthrough.** ``run_batch``, ``build_task_list``, and
  ``process_one`` in ``parallel.py`` all thread ``checkpoint_format``
  through to the workers.
- **Disk-space estimate aware.** ``estimate_pipeline_output_size``
  takes a ``checkpoint_format`` kwarg and halves the non-PNG byte
  estimate for ``'tiff'`` or ``'fits'`` runs.

### New functions

- `exo2micro.plot_zoom` — crop an image region, optionally smooth with a
  Gaussian blur, and display. Handles edge clamping and supports both
  standard and diverging colormaps.
- `exo2micro.plot_zoom_multi` — the same but tiles multiple images at
  the same coordinates side-by-side (for e.g. comparing post + aligned
  pre + difference at a single region of interest).

### GUI rewrite

- New top-level **Scale** dropdown exposing the Moffat / percentile /
  manual options with a decimal percentile input and a decimal
  manual-value input.
- New **Zoom & Inspect** panel with downsampled-preview sliders for
  interactive region selection, Gaussian blur, "show full-res"
  checkbox, side-by-side multi-image mode, and save-to-disk button.
- New **Blink Comparison** panel with A/B checkpoint selection and a
  toggle button for flipping between alignment stages at any region of
  interest. Designed for visually diagnosing alignment quality.
- New **Survey raw channels** button that runs `survey_raw_channels` as
  a pre-flight check without leaving the GUI.
- Stage dropdowns updated to 1-4 with the current stage names.
- `to_stage` control added alongside the existing `from_stage`.
- Inline post-run previews updated to display the five v2.2 diagnostic
  plots (`pre_post_heatmap`, `excess_heatmap`, `pre_post_histograms`,
  `difference_histogram`, `ratio_histogram`) plus the final difference
  image, each with a short caption explaining what to look for.

### Bug fixes

- Fixed a latent `AttributeError` in stage 2: the old code called
  `self._generate_alignment_plots(...)` from `_run_stage_2_coarse`, but
  no such method was defined. Stage 2 would have crashed on any fresh
  run without a cached stage-2 checkpoint. Now wired up to call
  `plot_registration` and `plot_fine_alignment` from the
  `debug_data['stages']` list returned by `register_highorder`.
- `SampleDye.status` now reports stage 4 instead of a phantom stage 5,
  so the status checklist actually reflects what the pipeline produces.
- `parallel.print_summary` now reads `scale_estimate` (the new result
  key) instead of the dead `opt_scale` / `opt_scale_robust` keys from
  v2.1. Summary tables work again after batch runs.
- `_check_path` and `_diff_path` in `SampleDye` no longer hard-code
  `stage=5` — they now use the `MAX_STAGE` constant, so stage names in
  check-plot filenames match the current pipeline.
- The stage-4 difference TIFF is now saved as
  `04_difference_difference.tiff` rather than the mislabelled
  `05_difference_difference.tiff` from v2.2.

### Removals

- `scaling.py` is deleted. Its contents (`optimize_subtraction` and
  `_build_histogram_data`) have been moved to `exo2micro.legacy` with
  deprecation notes pointing at `scale_percentile` as the equivalent
  v2.3 workflow. Imports from `exo2micro.scaling` no longer resolve;
  use `exo2micro.legacy` if you still need the old LS/robust code.
- The following parameters have been removed from `PARAMETER_REGISTRY`
  because no stage in the current pipeline uses them:
  `signal_threshold`, `dilation_iters`, `signal_percentile`,
  `robust_percentile`, `noise_floor_percentile`, `boundary_erosion`,
  `n_hist_bins`, `zoom_box`. Scripts that pass any of these via
  `SampleDye.set_params` will raise `ValueError`.
- The dead `_run_stage_4_masking` and `_run_stage_5_scaling_legacy`
  methods on `SampleDye` have been deleted.

---

## Version 2.2.0 — Moffat-fit scale and diagnostic rewrite

### Pipeline

- Pipeline reduced from 5 stages to 4. The old stages 4 (masking) and
  5 (LS/robust scaling + 8 plots) were replaced by a single stage 4:
  diagnostic plots plus scaled subtraction.
- New five-plot diagnostic set: `pre_post_heatmap`, `excess_heatmap`,
  `pre_post_histograms`, `difference_histogram`, `ratio_histogram`. All
  are saved to `pipeline_checks/`.
- New scale estimation: a Moffat profile is fit to the left wing of the
  `log10(post/pre)` distribution mirrored across the peak. Handles the
  sharp-peak-plus-long-tail shape of real microscopy noise better than
  the old Gaussian/Voigt approach.

### Image loading fix

- `load_image_pair` now extracts the fluorescence-bearing RGB channel
  at full 8-bit precision instead of using `PIL.Image.convert`, which
  applied luminance weights and discarded ~41% of the dynamic range.
  Multi-channel dyes (e.g. Spy700) sum their active channels
  automatically. **Users upgrading from 2.1 should re-run from stage 1**
  to get full-precision data.
- New helper `survey_raw_channels` to scan raw TIFFs and report which
  RGB channels carry signal.

### Plotting reorganization

- Ten legacy plotting functions moved from `plotting.py` to
  `legacy.py`: `plot_signal_scatter`, the dict-based
  `plot_ratio_histogram`, `plot_residual_histogram`, `plot_im_sub`,
  `plot_diff_comparison`, `plot_stretch_comparison`, `plot_zoom_region`,
  `_tissue_boundary_contour`, `_diff_colorbars`, and
  `_image_stretch_params`. These were removed from the main plotting
  module primarily because several of them crashed matplotlib with
  `OverflowError: Exceeded cell block limit` on full-resolution images.

### Batch processing

- `run_batch` accepts `from_stage`, `to_stage`, and `force` parameters,
  passed through to each `SampleDye.run` call. The summary table adapts
  its columns depending on which scale methods are in use.

---

## Version 2.1.0 — SIFT interior alignment

- New stage 3: interior SIFT feature matching. Corrects the residual
  interior misalignment (~20-50 pixels) left by the boundary-only
  registration in stage 2. Uses FLANN matching with Lowe's ratio test
  and RANSAC, with sanity checks on the correction magnitude and
  inlier ratio.
- Design note: SIFT was chosen over ECC after extensive testing. ECC
  converged to a local optimum unrelated to true alignment
  (`cc ≈ 0.6` regardless of quality) due to the ~3× staining intensity
  difference between pre and post. SIFT sidesteps this by operating on
  local gradient structure. See `docs/source/developers/concepts.rst`
  for the full rationale.
- Post-stain is saved exactly once at stage 1 as `01_padded_post.fits`.
  All downstream stages and diagnostic messages reference this single
  file, which makes blink comparison between stages trivial.
- New FITS header keywords on stage-3 outputs: `IACC` (interior
  alignment accuracy estimate in pixels, or `-1.0` if the fit failed)
  and `ILVLOK` (number of alignment levels completed).

---

## Version 2.0.0 — Package refactor

- Monolithic `exo2micro.py` (3,276 lines) split into a proper Python
  package with eight modules.
- New class-based API: `SampleDye` manages per-sample pipeline state,
  parameter versioning, and checkpoint-based resume.
- Every intermediate image saved as both TIFF (full float32) and FITS
  (with metadata headers).
- Parameter versioning: non-default parameter values are embedded in
  checkpoint filenames, so variants coexist without overwriting each
  other.
- First version of the ipywidgets interactive GUI.
- First version of `run_batch` with serial and parallel modes.
