Scripting API
=============

This page covers how to use exo2micro from Python code, as opposed
to the interactive GUI. It assumes you've read :doc:`concepts`.

The SampleDye class
-------------------

The central object in exo2micro is :class:`~exo2micro.SampleDye`.
One instance represents one ``(sample, dye)`` combination going
through the pipeline::

   import exo2micro as e2m

   run = e2m.SampleDye(
       sample='CD070',
       dye='SybrGld',
       output_dir='processed',
       raw_dir='raw',
       checkpoint_format='tiff',   # 'tiff', 'fits', or 'both'
   )

The ``checkpoint_format`` argument controls which file format(s)
each pipeline checkpoint is saved as. Options:

- ``'tiff'`` (default) — write TIFF only. Roughly half the disk
  footprint of ``'both'``. Recommended for most workflows.
- ``'fits'`` — write FITS only. Adds metadata-rich headers
  (sample, dye, stage, all non-default parameter values) to every
  checkpoint. Use this when provenance tracking matters more than
  disk space.
- ``'both'`` — write both formats for every checkpoint. Highest
  disk usage. Use only when downstream tools need both or when you
  want full redundancy.

Reading checkpoints is format-agnostic regardless of the setting:
if a checkpoint exists in either format, it's loaded (TIFF is
preferred when both are present for faster reads). This means a
``'tiff'`` run can resume from checkpoints left by a previous
``'fits'`` run and vice versa. When the loaded format differs from
the currently-configured save format, a one-time warning is
printed because the output directory will end up with mixed
formats. A pre-flight scan at the start of :meth:`~SampleDye.run`
also warns once if the output directory already contains
checkpoints in the non-configured format.

Running is explicit::

   result = run.run()

Result is a dict::

   {
       'sample': 'CD070',
       'dye': 'SybrGld',
       'scale_estimate': 1.234,
       'scale_percentile_value': None,
       'manual_scale': None,
       'status': 'complete',
   }

On error, ``status`` starts with ``'error: '`` followed by the
exception message.

Setting parameters
------------------

``set_params`` takes keyword arguments for any parameter in
:doc:`parameters`::

   run.set_params(
       boundary_width=20,
       boundary_smooth=15,
       scale_percentile=50.0,
   )
   run.run()

Unknown parameter names raise ``ValueError``.

To reset::

   run.reset_params()

To query::

   run.params                      # dict of all current values
   run.non_default_params()        # only those that differ from defaults
   run.non_default_params(stage=2) # only non-defaults for stages 1-2

Partial runs
------------

You can limit which stages execute::

   run.run(from_stage=2, to_stage=3)   # re-do alignment only
   run.run(from_stage=4)               # just regenerate diagnostics

This is useful when you've changed a parameter that only affects
a later stage. For example, changing ``scale_percentile`` only
affects stage 4, so::

   run.set_params(scale_percentile=50.0)
   run.run(from_stage=4)

...will re-use the alignment checkpoints from a previous run and
only re-do stage 4.

Force rerun::

   run.run(force=True)

Partial + force::

   run.run(from_stage=2, force=True)  # redo from stage 2 onward

Checking status
---------------

::

   run.status()

Prints a checklist of which checkpoints exist on disk for the
current parameter configuration, plus which diagnostic plots have
been generated.

Parameter comparison
--------------------

To sweep one parameter across several values::

   results = run.compare('boundary_width', [10, 15, 20])

This runs the pipeline three times, once for each value, and
returns a list of ``(value, result_dict)`` entries. Only the
stage affected by the parameter onwards is re-run each time.

Batch processing
----------------

For multiple samples × dyes, use :func:`~exo2micro.run_batch`::

   results = e2m.run_batch(
       samples=['CD070', 'CD063', 'CD055'],
       dyes=['SybrGld', 'DAPI'],
       parallel=True,
       n_workers=4,
       output_dir='processed',
       raw_dir='raw',
   )

Parameters common to every task are passed via ``params=``::

   results = e2m.run_batch(
       samples=['CD070', 'CD063'],
       dyes=['SybrGld'],
       params={'boundary_width': 20, 'scale_percentile': 50.0},
       parallel=True,
   )

Run-control kwargs work at batch level too::

   results = e2m.run_batch(
       samples=['CD070', 'CD063'],
       dyes=['SybrGld'],
       from_stage=4,       # only rerun diagnostics
       force=True,
   )

A summary table is printed at the end.

Strict vs lenient dye resolution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before queueing tasks, :func:`~exo2micro.run_batch` resolves the
requested ``samples × dyes`` product against the actual contents
of ``raw_dir`` via :func:`~exo2micro.discover_tasks`. A pair is
"present" when both a pre-stain and a post-stain file exist for
that dye in that sample's directory.

The ``strict_dyes`` parameter controls what happens when some
requested pairs are missing on disk:

- ``strict_dyes=True`` (default): raise
  :class:`FileNotFoundError` with one message listing every
  missing pair. Catches typos before a long batch starts.
- ``strict_dyes=False``: skip missing pairs silently, log a
  short summary, and run only the present ones. Use this when
  your samples are heterogeneous (not every dye exists for every
  sample).

::

   # Strict — fails if any of CD070, CD063, CD055 are missing any dye:
   results = e2m.run_batch(
       samples=['CD070', 'CD063', 'CD055'],
       dyes=['SybrGld', 'DAPI', 'Cy5'],
   )

   # Lenient — runs every pair that exists, skips the rest:
   results = e2m.run_batch(
       samples=['CD070', 'CD063', 'CD055'],
       dyes=['SybrGld', 'DAPI', 'Cy5'],
       strict_dyes=False,
   )

Either way, fatal layout problems with the raw directory itself
(missing, empty, no per-sample subfolders) raise
:class:`FileNotFoundError` regardless of ``strict_dyes`` — there
are no pairs to run at all in those cases.

Parallel mode gotchas
~~~~~~~~~~~~~~~~~~~~~

Parallel mode uses :class:`multiprocessing.Pool` with the ``spawn``
start method (required on macOS). Each worker starts a fresh Python
interpreter, so:

- Any code that relies on module-level side effects must be
  re-importable.
- Each worker holds its own copy of any loaded images — the rule
  of thumb is ``workers × peak RAM per sample < total RAM``.
- For small batches (1-3 samples) the spawn overhead often makes
  serial faster than parallel.
- On low-RAM machines, prefer ``parallel=False`` over
  ``parallel=True, n_workers=1``. Serial mode runs explicit
  garbage-collection between tasks; single-worker parallel mode
  does not. See :doc:`../users/memory_and_performance` for full
  guidance.

Discovery helpers
-----------------

If you want to do your own filtering before calling
:func:`~exo2micro.run_batch`, two utility functions in
:mod:`exo2micro.utils` are useful:

:func:`~exo2micro.diagnose_raw_layout` returns a structured report
about the layout of a raw directory — whether it exists, whether
it has per-sample subfolders, whether those subfolders contain
TIFFs. Use it for a fast pre-flight check before any real work::

   from exo2micro import diagnose_raw_layout
   report = diagnose_raw_layout('raw')
   if not report['ok']:
       print(report['message'])
   else:
       print(f"Found {len(report['subdirs'])} sample folder(s)")

:func:`~exo2micro.discover_tasks` resolves a ``samples × dyes``
request against the filesystem and returns three lists::

   from exo2micro import discover_tasks
   result = discover_tasks(
       samples=['CD070', 'CD063'],
       dyes=['SybrGld', 'DAPI', 'Cy5'],
       raw_dir='raw',
   )
   print('Will run:', result['present'])
   for sample, dye, reason in result['skipped']:
       print(f'  skip {sample}/{dye}: {reason}')
   for sample, warning in result['warnings']:
       print(f'  warning in {sample}: {warning}')

This is the same helper :func:`~exo2micro.run_batch` and the GUI
use internally; calling it yourself lets you inspect the resolution
before any tasks run.

Working with output files
-------------------------

Everything lives under
``{output_dir}/{sample}/{dye}/`` in four subdirectories:

- ``tiff/`` — full-precision float32 TIFFs. The main deliverable
  is ``04_difference_difference.tiff``.
- ``fits/`` — same data with metadata-rich headers
  (``SAMPLE``, ``DYE``, ``STAGE``, ``SCALE``, ``SCALEK``,
  ``CREATED``, plus all non-default parameter values). Use these
  when you need full provenance.
- ``pipeline_output/`` — PNG diagnostic plots (heatmaps,
  histograms, ratio fit, difference image visualizations,
  saved zoom views).

Loading results::

   import tifffile
   from astropy.io import fits

   # Float32 difference image
   diff = tifffile.imread(
       'processed/CD070/SybrGld_microbe/tiff/04_difference_difference.tiff')

   # Same data with metadata
   hdul = fits.open(
       'processed/CD070/SybrGld_microbe/fits/04_difference_difference.fits')
   diff_fits = hdul[0].data
   scale = hdul[0].header['SCALE']
   scale_kind = hdul[0].header['SCALEK']  # 'moffat', 'manual', or 'percentile_p50'
   print(f"Scale: {scale} ({scale_kind})")

Filename conventions
--------------------

Every checkpoint filename has a parameter suffix reflecting the
non-default parameters in effect when it was written. A run with
defaults produces::

   01_padded_post.tiff
   01_padded_pre.tiff
   02_icp_aligned_pre.tiff
   03_interior_aligned_pre.tiff
   04_difference_difference.tiff

A run with ``boundary_width=20, scale_percentile=99.1``::

   01_padded_post.tiff
   01_padded_pre.tiff
   02_icp_aligned_pre_bw20.tiff
   03_interior_aligned_pre_bw20.tiff
   04_difference_difference_bw20_sp99.1.tiff
   04_difference_difference_percentile_p99.1_bw20_sp99.1.tiff

Upstream parameters cascade into downstream filenames — changing
``pad`` (stage 1) affects all subsequent stage filenames.

To decode a filename suffix::

   from exo2micro.defaults import params_from_suffix
   params_from_suffix('_bw20_sp99.1')
   # → {'boundary_width': 20, 'scale_percentile': 99.1}

Bypass vs. checkpoint mode
--------------------------

:class:`~exo2micro.SampleDye` is designed for the file-based
checkpoint-and-resume workflow. For one-off experiments where you
don't want files on disk, you can call the lower-level functions
directly::

   from exo2micro import (load_image_pair, pad_images,
                          register_highorder, plot_ratio_histogram_simple)

   post_raw, pre_raw, post_path, pre_path = load_image_pair(
       'CD070', 'SybrGld', raw_dir='raw')
   post_pad, pre_pad = pad_images(post_raw, pre_raw, pad=2000)
   post_full, pre_aligned, pre_coarse, warp, _debug = \
       register_highorder(post_pad, pre_pad)

   _, scale = plot_ratio_histogram_simple(post_full, pre_aligned)
   diff = post_full - scale * pre_aligned

Note that as of v2.3, :func:`load_image_pair` is **strict** about
filename conventions and raises :class:`FileNotFoundError` (missing
sample directory or missing pair) or :class:`ValueError` (duplicate
or malformed filenames) when it can't cleanly resolve the requested
``(sample, dye)``. The exception message is multi-line and tells
the user exactly what's wrong. Wrap calls in ``try`` / ``except``
if you want to handle these failures programmatically::

   try:
       post, pre, post_path, pre_path = load_image_pair(
           'CD070', 'DAPI', raw_dir='raw')
   except (FileNotFoundError, ValueError) as e:
       print(f"Couldn't load CD070/DAPI: {e}")

When :class:`SampleDye` is used (the standard workflow), these
exceptions are caught by :meth:`SampleDye.run` and recorded in the
result dict's ``status`` field, so batch runs continue with other
``(sample, dye)`` tasks even when individual ones have file
problems.

The companion helper :func:`classify_raw_files` is non-raising and
returns a ``(pairs, warnings)`` tuple — useful for inspecting a
directory's contents without committing to a load::

   from exo2micro import classify_raw_files
   pairs, warnings = classify_raw_files('raw/CD070')
   for dye, files in pairs.items():
       print(f"{dye}: {len(files['pre'])} pre, {len(files['post'])} post")
   for w in warnings:
       print(f"warning: {w}")

See :doc:`api/index` for the full list of re-exported functions.

Error handling
--------------

:meth:`~exo2micro.SampleDye.run` catches any exception raised by
its stage methods and returns a result dict with
``status='error: {message}'``, plus a full traceback printed to
stdout. If you'd rather exceptions propagate, call the stage
methods directly::

   run._run_stage_1_padding()
   run._run_stage_2_coarse()
   run._run_stage_3_fine()
   run._run_stage_4_diagnostics()

These are technically private methods (leading underscore), but
they're stable across minor releases within a major version.
