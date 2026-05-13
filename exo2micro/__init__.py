"""
exo2micro
=========
Image registration and fluorescence subtraction pipeline for pre/post-stain
microscopy images.

Workflow
--------
1. **Padding** — load paired TIFF images onto a common zero-padded canvas
2. **Boundary alignment** — phase correlation + ICP on the tissue outline
3. **Interior alignment** — SIFT feature matching on tissue interior
4. **Diagnostics & subtraction** — Moffat-fit scale estimation, diagnostic
   plots, and a scaled difference image

When the optional ``scale_percentile`` or ``manual_scale`` parameters are
set, stage 4 additionally produces difference images using those
alternative scales, with every active scale line overplotted on the
excess heatmap for side-by-side comparison.

Quick start
-----------
::

    import exo2micro as e2m

    # Process a single sample+dye combination
    run = e2m.SampleDye('CD070', 'SybrGld')
    run.run()

    # With an additional manual scale override
    run.set_params(manual_scale=1.42)
    run.run(from_stage=4)

    # Batch processing (strict_dyes=True by default — raises if any
    # requested (sample, dye) pair is missing on disk)
    results = e2m.run_batch(
        samples=['CD070', 'CD063'],
        dyes=['SybrGld', 'DAPI'],
        parallel=True,
        n_workers=4,
    )

    # For heterogeneous datasets where not every dye exists for every
    # sample, pass strict_dyes=False to skip missing pairs:
    results = e2m.run_batch(
        samples=['CD070', 'CD063'],
        dyes=['SybrGld', 'DAPI', 'Cy5'],
        strict_dyes=False,
    )

Interactive GUI
---------------
::

    from exo2micro.gui import launch
    launch()

Sub-modules
-----------
alignment  : Image registration (boundary correlation, ICP, SIFT)
plotting   : Active visualization functions (diagnostics, zoom)
pipeline   : SampleDye class with checkpointing and resume logic
parallel   : Batch processing (serial and parallel)
gui        : Interactive Jupyter notebook interface (ipywidgets)
utils      : Shared utilities (I/O, preprocessing, masking, channel detection)
defaults   : Parameter registry and filename conventions
legacy     : Deprecated / superseded functions retained for back-compat.
             Includes the old least-squares / robust-percentile scaling
             helpers formerly in ``scaling.py``.
"""

__version__ = '2.3.1'

# Primary API: the SampleDye pipeline class
from .pipeline import SampleDye

# Batch processing
from .parallel import run_batch, run_serial, run_parallel

# Commonly used functions re-exported for convenience
from .alignment import register_highorder, prealign_phase_correlation
from .utils import (
    load_image_pair,
    classify_raw_files,
    diagnose_raw_layout,
    discover_tasks,
    estimate_pipeline_output_size,
    get_free_disk_space,
    format_bytes,
    get_run_log_path,
    append_to_run_log,
    read_run_log_tail,
    clear_run_log,
    TeeStdout,
    survey_raw_channels,
    pad_images,
    trim_to_signal,
    subtract_median,
    normalize_image,
    build_tissue_mask,
    tiff_to_fits,
    filter_nan_gaussian_conserving,
    estimate_gauss_sigma,
)
from .plotting import (
    plot_registration,
    plot_fine_alignment,
    plot_pre_post_heatmap,
    plot_excess_heatmap,
    plot_pre_post_histograms,
    plot_difference_histogram,
    plot_ratio_histogram_simple,
    plot_difference_image,
    plot_zoom,
    plot_zoom_multi,
    plot_im,
)
from .defaults import DEFAULTS, PARAMETER_REGISTRY, MAX_STAGE
