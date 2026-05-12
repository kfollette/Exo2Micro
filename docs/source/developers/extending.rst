Extending exo2micro
===================

This page covers how to modify exo2micro for uses the shipping
pipeline doesn't cover — custom plots, new workflows, integration
with other tools.

Adding a new diagnostic plot
----------------------------

Every stage-4 diagnostic plot lives as a function in
``exo2micro.plotting`` that takes ``(post_im, pre_im, ..., save_path=None)``
and is called from ``SampleDye._run_stage_4_diagnostics``.

To add a new plot:

1. **Write the plotting function.** Put it in
   ``exo2micro/plotting.py``. Follow the existing signature
   pattern — take ``post_im``, ``pre_im``, any method-specific
   kwargs, and ``sample``, ``dye``, ``save_path``. Return the
   matplotlib figure. Close the figure if ``save_path`` is given;
   call ``plt.show()`` otherwise.

2. **Export it** from ``exo2micro/__init__.py``::

      from .plotting import plot_my_new_diagnostic

3. **Call it from stage 4.** In
   ``_run_stage_4_diagnostics``::

      my_path = self._check_path('my_new_diagnostic')
      if force or not os.path.exists(my_path):
          plotting.plot_my_new_diagnostic(
              post_full, pre_aligned,
              sample=self.sample, dye=self.dye,
              save_path=my_path)

4. **Add it to the inline preview** in ``gui.py`` under
   ``_show_inline_results`` so the GUI displays it after a run::

      plots_to_show.append(
          ('my_new_diagnostic', 'Short caption explaining it.'))

5. **Add it to ``SampleDye.status()``** in ``pipeline.py`` so
   status checks include it.

Adding a new parameter
----------------------

Parameters live in ``exo2micro/defaults.py`` in
``PARAMETER_REGISTRY``. Each entry is::

   ('param_name', (default_value, 'abbrev', stage_number, 'description')),

Steps:

1. **Add to the registry** with a short abbreviation that
   doesn't collide with any existing one. Check
   ``ABBREVIATIONS`` first. The abbreviation appears in
   checkpoint filenames as ``{abbrev}{value}``.

2. **Consume it** in the relevant stage method. Access via
   ``self._params['param_name']``. Parameters are type-checked
   by ``set_params`` against their default value's type.

3. **Choose the type carefully.** Booleans, ints, floats, and
   ``None`` round-trip through filename suffixes via
   ``params_from_suffix``. Strings work but rarely needed.

4. **Update the parameter reference docs** in
   ``docs/source/developers/parameters.rst``.

Boolean parameters serialize as ``0`` / ``1`` in filenames (e.g.
``_iecc0``). None-able parameters serialize as ``none`` (e.g.
``_sp_none``). Floats use ``:g`` format, so ``1.42`` →
``msc1.42``, ``1.0`` → ``msc1``.

Adding a new pipeline stage
---------------------------

This is a deeper change and touches several files.

1. **Update ``STAGE_NAMES`` and ``MAX_STAGE``** in ``defaults.py``.
   Stages are numbered 1-indexed; filenames embed the number
   zero-padded to two digits.

2. **Add a ``_run_stage_N_...`` method** on ``SampleDye``
   following the pattern of the existing ones:

   - Take ``force=False`` as the only argument.
   - Check for existing checkpoints via ``self._has_checkpoint``
     and skip if present (unless ``force``).
   - Auto-run missing upstream stages.
   - Load inputs via ``self._load_image``.
   - Save outputs via ``self._save_image``.

3. **Wire it into ``run()``.** Add the stage guard block to
   ``SampleDye.run``::

      if from_stage <= N and to_stage >= N:
          self._run_stage_N_mystage(force)

4. **Add its files to ``_check_upstream``** so downstream stages
   can detect when it's missing.

5. **Add its files to ``status()``** so users can see its
   checkpoint status.

6. **Update ``gui.py``** — the ``from_stage`` / ``to_stage``
   dropdowns are built from ``STAGE_NAMES`` automatically, so
   they'll pick up the new stage without code changes.

Custom image loaders
--------------------

If your raw data isn't in the TIFF-with-``PreStain``/``PostStain``
naming convention exo2micro expects, you have two options:

**Option 1: Write files in the expected format before running.**
Simplest — just rename or copy your files into the structure
exo2micro wants.

**Option 2: Replace ``load_image_pair``.** It lives in
``exo2micro.utils`` and returns a 4-tuple of
``(post_im, pre_im, post_path, pre_path)``. Write your own
function with the same signature, then patch it::

   import exo2micro.utils as u
   import exo2micro.pipeline as p

   def my_loader(sample, dye, raw_dir='...'):
       # your logic here
       return post, pre, post_path, pre_path

   u.load_image_pair = my_loader
   p.load_image_pair = my_loader

Ugly but effective. A cleaner alternative is to subclass
``SampleDye`` and override ``_run_stage_1_padding``.

Accessing pipeline internals
----------------------------

The stage methods are prefixed with underscores
(``_run_stage_1_padding``, etc.) to signal that they're internal
implementation details. However, they're stable across minor
releases within a major version, and sometimes you need them.

Common things you might want:

- :meth:`SampleDye._load_image(stage, name)` — load any
  checkpoint as a numpy array. Returns ``None`` if not found.
- :meth:`SampleDye._save_image(image, stage, name, extra_headers=None)`
  — save an array as TIFF + FITS with the usual metadata.
- :meth:`SampleDye._has_checkpoint(stage, name)` — check if a
  specific checkpoint file exists for the current parameters.
- :attr:`SampleDye._tiff_path(stage, name)` /
  :attr:`SampleDye._fits_path(stage, name)` /
  :attr:`SampleDye._check_path(name)` — construct the full
  on-disk paths for checkpoints and check plots.
- :attr:`SampleDye._results` — transient dict of in-memory
  results from the current run. Keys include ``warp_matrix``,
  ``debug_data``, ``scale_estimate``,
  ``scale_percentile_value``. Not persisted across instances.

Integration with downstream analysis
------------------------------------

A typical downstream analysis reads the difference image and
segments the positive signal::

   from astropy.io import fits
   from skimage import morphology, measure

   hdul = fits.open(
       'processed/CD070/SybrGld_microbe/fits/04_difference_difference.fits')
   diff = hdul[0].data
   scale = hdul[0].header['SCALE']

   # Threshold at e.g. 5 sigma above background noise
   bg_std = diff[diff != 0].std()
   mask = diff > 5 * bg_std

   # Clean up small artefacts
   mask = morphology.remove_small_objects(mask, min_size=20)

   # Label connected components
   labels = measure.label(mask)
   props = measure.regionprops(labels, intensity_image=diff)

   for p in props:
       print(f"feature {p.label}: centroid {p.centroid}  "
             f"area {p.area}  mean intensity {p.mean_intensity:.1f}")

The FITS header carries the scale factor and all non-default
parameters, so this downstream script has full provenance
information for every feature it detects. For fully reproducible
pipelines, log ``hdul[0].header`` alongside your segmentation
results.

Where to look in the code
-------------------------

The package is organised around modules with clear
responsibilities:

- ``pipeline.py`` — the :class:`SampleDye` class, parameter
  management, stage orchestration, file I/O routing.
- ``alignment.py`` — image registration. ``register_highorder``
  is the main entry point and does boundary correlation + ICP
  in one call. ``refine_interior_ecc`` is the SIFT refinement.
- ``plotting.py`` — active visualization functions
  (diagnostics, zoom, registration plots).
- ``utils.py`` — file I/O, preprocessing, masking, channel
  detection. Most things in here are used by ``pipeline.py`` but
  also exported for standalone use.
- ``defaults.py`` — parameter registry and filename conventions.
- ``parallel.py`` — batch processing (serial and parallel).
- ``gui.py`` — ipywidgets GUI, layered on top of ``SampleDye``.
- ``legacy.py`` — deprecated functions kept for back-compat.

For autodoc-generated details on every public function, see
:doc:`api/index`.
