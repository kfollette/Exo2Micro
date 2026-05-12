Migration Guide
===============

This page consolidates upgrade notes for moving between exo2micro
versions. Start with your current version and walk forward.

From 2.2 to 2.3
---------------

Pipeline behaviour is unchanged at defaults — if you were running
with all default parameters, nothing about the output files
changes except that the final difference image is now correctly
named ``04_difference_difference.tiff`` instead of the mislabelled
``05_difference_difference.tiff``. The stage-4 diagnostic plots
are unchanged.

Breaking changes
~~~~~~~~~~~~~~~~

**1. Removed parameters.** These eight parameters no longer exist
in :obj:`PARAMETER_REGISTRY` and will raise :class:`ValueError`
if passed to :meth:`SampleDye.set_params`:

- ``signal_threshold``
- ``dilation_iters``
- ``signal_percentile``
- ``robust_percentile``
- ``noise_floor_percentile``
- ``boundary_erosion``
- ``n_hist_bins``
- ``zoom_box``

The first two belonged to the tissue-masking stage that was
deleted in v2.2; the rest belonged to the LS/robust-percentile
scaling code that was superseded by the Moffat fit in v2.2. See
:doc:`developers/scale_methods` for why the old methods were
dropped.

If you have scripts like this:

.. code-block:: python

   run.set_params(robust_percentile=90, boundary_erosion=30)

...rewrite them:

.. code-block:: python

   # v2.3 equivalent: the old "robust_percentile=90" produced a
   # scale estimate at the 90th percentile of the log-ratio
   # distribution. In v2.3 that's scale_percentile=90.0.
   #
   # Note however that the default workflow has changed — the
   # Moffat fit now runs unconditionally, and scale_percentile
   # produces an *additional* difference image rather than
   # replacing the main one. So you can drop the parameter
   # entirely if you just want the Moffat result.
   run.set_params(scale_percentile=90.0)

The dead scaling parameters (``boundary_erosion`` and friends) are
simply dropped — there's nothing for them to do in v2.3.

**2. ``scaling.py`` is gone.** If you have imports like:

.. code-block:: python

   from exo2micro.scaling import optimize_subtraction

...rewrite as:

.. code-block:: python

   from exo2micro.legacy import optimize_subtraction

The function itself is unchanged. It's no longer called by any
stage of the v2.3 pipeline.

**3. ``SampleDye.run`` return dict has new keys.** In v2.2::

   {'sample': ..., 'dye': ..., 'scale_estimate': ..., 'status': ...}

In v2.3::

   {'sample': ..., 'dye': ..., 'scale_estimate': ...,
    'scale_percentile_value': ..., 'manual_scale': ...,
    'status': ...}

The new keys are ``None`` when the corresponding method is not
active, so existing code that only reads ``scale_estimate``
continues to work unchanged.

**4. :func:`plot_excess_heatmap` gained a ``scales=`` kwarg.**
The old single-line ``scale=`` kwarg still works and is
deprecated in behaviour but not removed. For overplotting
multiple scale lines (one per active method), use:

.. code-block:: python

   plot_excess_heatmap(
       post, pre,
       scales=[
           ('Moffat fit',  1.234, '#00cc88'),
           ('ratio p50',   1.198, '#ff9933'),
           ('manual',      1.250, '#ff3366'),
       ],
       save_path='excess.png')

Recommended new features
~~~~~~~~~~~~~~~~~~~~~~~~

- For interactive inspection of difference images, use the new
  **Zoom & Inspect** panel in the GUI, or
  :func:`plot_zoom` / :func:`plot_zoom_multi` from Python.
- For diagnosing alignment quality, use the **Blink Comparison**
  panel in the GUI.
- For manual scale overrides, use the new :obj:`manual_scale`
  parameter.

From 2.1 to 2.2
---------------

.. important::

   Upgrading from 2.1 (or earlier) requires you to re-run the
   pipeline from stage 1. The image loading changed in a way
   that affects the actual pixel values of stage-1 checkpoints:
   v2.2 extracts the fluorescence-bearing RGB channel directly
   rather than converting RGB to grayscale with luminance
   weights. The old v2.1 stage-1 files have ~41% less dynamic
   range than the new ones, and all downstream diagnostics
   depend on precise pixel values.

   To re-run::

      run = e2m.SampleDye('CD070', 'SybrGld_microbe')
      run.run(from_stage=1, force=True)

Pipeline changes
~~~~~~~~~~~~~~~~

- Pipeline shrank from 5 stages to 4. Stage 4 (masking) was
  removed; the old stage 5 (scaling + plots) was replaced by a
  new stage 4 (diagnostics + subtraction using a Moffat-fit
  scale estimate).
- Code that called ``run(from_stage=5)`` should now use
  ``run(from_stage=4)``. The default ``to_stage`` is now 4.

Plotting module changes
~~~~~~~~~~~~~~~~~~~~~~~

Ten legacy plotting functions moved from ``exo2micro.plotting``
to ``exo2micro.legacy``. If you import them directly, update:

.. code-block:: python

   # OLD
   from exo2micro.plotting import plot_signal_scatter, plot_im_sub

   # NEW
   from exo2micro.legacy import plot_signal_scatter, plot_im_sub

The functions still work, but some of the full-resolution
contour-overlay ones crashed on images larger than ~25000×25000
pixels due to matplotlib's cell block limit. The new stage 4
avoids these paths entirely.

Scale estimation
~~~~~~~~~~~~~~~~

In v2.1 and earlier, scale estimation used either least-squares
or a robust-percentile method on the log-ratio distribution.
v2.2 replaced both with a Moffat fit on the left wing of the
same distribution, which fits empirical microscopy noise better.
The old methods are preserved in :mod:`exo2micro.legacy` if you
need to reproduce earlier results.

From 2.0 to 2.1
---------------

- New stage 3: interior SIFT alignment. Runs automatically after
  stage 2 unless ``interior_ecc=False`` is set. No action
  required for most users — the pipeline just gets a better
  alignment for free.
- Stage 2 is no longer just "coarse alignment" — it now includes
  both boundary correlation *and* ICP refinement in a single
  stage. Filenames changed from ``02_coarse_aligned_pre`` to
  ``02_icp_aligned_pre``.
- The old stage 3 ``03_fine_aligned_pre`` checkpoint is now
  ``03_interior_aligned_pre``.
- Old-style checkpoint filenames won't be found by the new
  pipeline. Re-run from stage 1 or rename files manually.

From 1.x to 2.0
---------------

v2.0 was a full package refactor. The monolithic ``exo2micro.py``
was split into eight modules, a class-based :class:`SampleDye`
API was introduced, and the pipeline became
checkpoint-driven. For 1.x users, the migration path is:

1. Replace any calls to the module-level functions with the
   class-based API::

      run = e2m.SampleDye('CD070', 'SybrGld_microbe')
      run.set_params(...)
      run.run()

2. Move any output directory configuration into the ``SampleDye``
   constructor (``output_dir=``, ``raw_dir=``).

3. Let the new parameter-versioning mechanism handle filenames.
   Remove any manual filename construction in your scripts.

Beyond that, the underlying algorithms in v2.0 were largely
unchanged from 1.x. If you have specific 1.x scripts that don't
translate cleanly, the v2.0 changelog in the repository has a
detailed function-by-function migration list.
