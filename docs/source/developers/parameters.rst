Parameter Reference
===================

exo2micro has 29 tunable parameters in v2.3. For most use cases the
defaults work well and you won't need to change anything. This
page documents every parameter, its filename abbreviation, default
value, and the pipeline stage it affects.

How parameters affect filenames
-------------------------------

Only non-default parameters appear in checkpoint filenames. A run
with all defaults produces clean names like
``02_icp_aligned_pre.tiff``. When you change a parameter, its
abbreviation and value are appended:
``02_icp_aligned_pre_bw20.tiff``.

Upstream parameters cascade into downstream filenames. Changing
``pad`` (stage 1) to 3000 affects all stages:

.. code-block:: text

   01_padded_post_pad3000.tiff
   02_icp_aligned_pre_pad3000.tiff
   03_interior_aligned_pre_pad3000.tiff
   04_difference_difference_pad3000.tiff

This means different parameter settings coexist in the same
directory without overwriting each other.

Full parameter table
--------------------

.. list-table::
   :header-rows: 1
   :widths: 24 7 10 5 54

   * - Parameter
     - Abbrev
     - Default
     - Stage
     - Description
   * - ``pad``
     - ``pad``
     - 2000
     - 1
     - Zero-padding pixels added on each side before registration
   * - ``use_edges``
     - ``ue``
     - True
     - 2
     - Focus coarse pass on tissue boundary rings
   * - ``boundary_width``
     - ``bw``
     - 15
     - 2
     - Boundary ring thickness in pixels at coarse resolution
   * - ``boundary_smooth``
     - ``bs``
     - 10
     - 2
     - Gaussian softening sigma on the boundary ring
   * - ``rotation_search``
     - ``rs``
     - True
     - 2
     - Search over rotations in the coarse pass
   * - ``angle_range``
     - ``ar``
     - 20
     - 2
     - Rotation search range: ± degrees
   * - ``angle_step``
     - ``astep``
     - 1
     - 2
     - Rotation search step size in degrees
   * - ``scale_search``
     - ``ss``
     - True
     - 2
     - Search over isotropic scale factors in coarse pass
   * - ``scale_min``
     - ``smin``
     - 0.85
     - 2
     - Minimum scale factor to search
   * - ``scale_max``
     - ``smax``
     - 1.15
     - 2
     - Maximum scale factor to search
   * - ``scale_step``
     - ``sstep``
     - 0.05
     - 2
     - Scale search step size
   * - ``multiscale``
     - ``ms``
     - True
     - 2
     - Run boundary correlation coarse pass before ICP
   * - ``down_scale``
     - ``ds``
     - 0.3
     - 2
     - Downsample factor for alignment visualization
   * - ``fine_ecc``
     - ``fecc``
     - False
     - 2
     - Run a fine homography ECC pass after ICP (rarely useful)
   * - ``max_translation``
     - ``mtr``
     - 200
     - 2
     - Maximum allowed ICP translation in pixels
   * - ``max_rotation``
     - ``mrot``
     - 5.0
     - 2
     - Maximum allowed ICP rotation in degrees
   * - ``max_scale_delta``
     - ``msd``
     - 0.2
     - 2
     - Maximum deviation of scale from 1.0
   * - ``max_scale_diff``
     - ``msdf``
     - 0.15
     - 2
     - Maximum allowed absolute difference between scale_x and scale_y
   * - ``stopit``
     - ``sit``
     - 500
     - 2
     - Maximum ECC iterations for legacy fine pass
   * - ``stopdelta``
     - ``sdl``
     - 1e-6
     - 2
     - ECC convergence threshold for legacy fine pass
   * - ``save_all_intermediates``
     - ``sai``
     - False
     - 2
     - Save coarse-only alignment intermediate for diagnosis
   * - ``interior_ecc``
     - ``iecc``
     - True
     - 3
     - Enable interior SIFT refinement after ICP
   * - ``interior_levels``
     - ``ilvl``
     - 3
     - 3
     - Not used (retained for API compatibility)
   * - ``interior_blur_base``
     - ``iblur``
     - 8.0
     - 3
     - Gaussian blur sigma applied before SIFT feature detection
   * - ``interior_mask_percentile``
     - ``imp``
     - 95
     - 3
     - Not used (retained for API compatibility)
   * - ``interior_max_correction``
     - ``imc``
     - 500
     - 3
     - Max allowed total correction from SIFT (full-res pixels)
   * - ``interior_min_inlier_ratio``
     - ``imir``
     - 0.4
     - 3
     - Minimum RANSAC inlier ratio to accept interior alignment
   * - ``scale_percentile``
     - ``sp``
     - None
     - 4
     - If set (float), produce an additional difference image using
       this percentile of the log₁₀(post/pre) distribution as the scale
   * - ``manual_scale``
     - ``msc``
     - None
     - 4
     - If set (float), produce an additional difference image using
       this exact scale factor

Parameters that matter most
---------------------------

In practice you will almost never touch most parameters. Here are
the ones that come up most often when tuning exo2micro for a new
dataset:

- ``boundary_width`` / ``boundary_smooth`` — when coarse alignment
  is struggling. Bigger values are more tolerant of shape
  differences between pre and post.
- ``angle_range`` — when your samples can rotate significantly
  between imaging sessions.
- ``interior_blur_base`` — when SIFT is struggling in stage 3.
  Higher values suppress microbe-scale features so they don't
  corrupt the feature matching.
- ``interior_ecc=False`` — when the sample interior is too uniform
  for SIFT and you want to fall back to the stage 2 result.
- ``scale_percentile`` — when you want to produce a difference
  image using a percentile of the ratio distribution alongside the
  Moffat fit (see :doc:`scale_methods`).
- ``manual_scale`` — when you want to override the scale estimate
  entirely with a value of your choice.

Setting parameters
------------------

In Python::

   run = e2m.SampleDye('CD070', 'SybrGld_microbe')
   run.set_params(boundary_width=20, scale_percentile=50.0)
   run.run()

In the GUI: open the Advanced Parameters accordion and adjust
values in the appropriate stage tab. For the scale-related options,
use the top-level **Scale** dropdown rather than editing
``scale_percentile`` / ``manual_scale`` in the accordion — the
dropdown provides a cleaner interface and ensures the right
values flow through.

Resetting to defaults::

   run.reset_params()

Filename parsing
----------------

To decode a filename suffix back to parameter values::

   from exo2micro.defaults import params_from_suffix
   params_from_suffix('_bw20_sp50')
   # → {'boundary_width': 20, 'scale_percentile': 50.0}

To build a filename suffix from current parameters::

   from exo2micro.defaults import build_suffix, DEFAULTS

   params = dict(DEFAULTS)
   params['boundary_width'] = 20
   params['manual_scale'] = 1.42
   build_suffix(params, stage=4)
   # → '_bw20_msc1.42'

Legacy parameters
-----------------

The following parameters existed in v2.1 and earlier but have been
removed in v2.3 because the pipeline stages that used them no
longer exist:

- ``signal_threshold``, ``dilation_iters`` — from the deleted
  joint tissue mask stage.
- ``robust_percentile`` — replaced by ``scale_percentile``
  (identical math, clearer name).
- ``signal_percentile``, ``noise_floor_percentile``,
  ``boundary_erosion``, ``n_hist_bins``, ``zoom_box`` — from the
  deleted LS/robust-percentile scaling stage.

If you have scripts that pass any of these via ``set_params``,
they'll raise ``ValueError("Unknown parameter ...")``. See
:doc:`../migration` for how to update them.
