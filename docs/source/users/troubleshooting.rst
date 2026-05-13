Troubleshooting
===============

This page catalogues common problems and what to do about them.

"No raw files found" / "Raw image directory not found"
------------------------------------------------------

When you click Auto-detect (or call :func:`~exo2micro.survey_raw_channels`
or :func:`~exo2micro.run_batch`) and exo2micro reports a layout problem,
the message will be one of the following. All four come from
:func:`~exo2micro.diagnose_raw_layout` and include the canonical
directory layout in the message itself, so you can copy-paste straight
into your file manager.

**Raw image directory not found.**
The ``raw_dir`` you pointed exo2micro at doesn't exist. Most often this
means the GUI was launched from a different folder than the one
containing your ``raw/`` directory. Either move your raw directory to
the working directory, ``cd`` into the right place before launching
JupyterLab, or pass an absolute path: ``raw_dir='/full/path/to/raw'``.

**Raw image directory is empty.**
The directory exists but contains nothing. Drop your sample folders
into it (one folder per sample, with paired pre/post TIFFs inside).

**Found N TIFF file(s) directly inside <raw_dir>, but no per-sample
subfolders.**
The most common mistake. exo2micro requires each sample to live in
its own subdirectory under ``raw_dir``. Putting all images flat in
``raw/`` is the natural thing to do but exo2micro can't tell which
files belong to which sample. Fix: make a folder for each sample
(``raw/Sample001/``, ``raw/Sample002/``, ...) and move that sample's
pre/post files into its folder.

**Found N sample subdirectory(ies) under <raw_dir>, but none of them
contain any TIFF files.**
The folder structure is right but the folders themselves are empty
(or contain only non-TIFF files). Check that your images are
``.tif`` or ``.tiff`` (case-insensitive) and that they're actually
inside the sample folder, not next to it.

"Some requested (sample, dye) pairs have no raw files"
------------------------------------------------------

When you call :func:`~exo2micro.run_batch` with the default
``strict_dyes=True``, requesting a ``(sample, dye)`` combination
that doesn't exist on disk raises :class:`FileNotFoundError` with
a single message listing every missing pair. The most common
causes:

- **Typo in a sample or dye name.** Check the listed dyes against
  your raw filenames. Dye matching is case-sensitive: ``DAPI`` and
  ``dapi`` are different.
- **Heterogeneous samples.** Not every dye exists for every sample.
  Either trim your sample/dye lists, or pass ``strict_dyes=False``
  to skip missing pairs and process the rest.
- **Files not copied over yet.** The pair really doesn't exist —
  add the missing files, or remove the affected sample/dye from
  your run.

In the GUI, the same situation produces a warning banner above the
Run button with a "Confirm and run anyway" option that automatically
sets ``strict_dyes=False`` for that run. Missing pairs render as
muted gray tiles with a "(no files)" label so you can see what was
filtered out at a glance.

Alignment doesn't look right
----------------------------

**Symptoms.** The boundary contours in ``registration.png`` don't
overlap cleanly, or the difference image shows ghost-like
doubling of features, or the blink comparison shows features
jumping between A and B.

**First, figure out which stage went wrong.** Use the blink
comparison panel with A = post (stage 1) and B = one of the
alignment stages:

- If **B = ICP-aligned pre (stage 2)** looks bad, the boundary
  alignment failed. Move on to "Boundary alignment failing" below.
- If **stage 2 is good but B = interior-aligned pre (stage 3)**
  is worse, the SIFT interior match went wrong. Move on to
  "Interior alignment failing".

Boundary alignment failing
~~~~~~~~~~~~~~~~~~~~~~~~~~

The coarse (stage 2) pass extracts the outer tissue boundary as a
soft ring and finds the best rigid transform to overlap them. It
can fail when the boundary is ill-defined, too thin, or has very
different shapes between pre and post.

Things to try (in order):

1. **Increase ``boundary_width``.** Default 15. Try 20 or 25. A
   thicker ring is more tolerant of small shape differences between
   the two images.
2. **Increase ``boundary_smooth``.** Default 10. Try 15 or 20. More
   smoothing gives the phase-correlation search a gentler gradient
   landscape.
3. **Widen the rotation search.** If your samples might be rotated
   more than 20° between imaging sessions, increase ``angle_range``
   to 45 or 90.
4. **Widen the scale search.** If magnification differs noticeably
   between pre and post, increase ``scale_max`` and decrease
   ``scale_min``.

You can sweep any of these with the **Parameter Comparison** panel
in the GUI to find the best value for your sample.

Interior alignment failing
~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage 3 uses SIFT feature matching on the interior of the tissue
(not the boundary). Common failure modes:

1. **Too few features detected.** Very uniform samples don't give
   SIFT much to match. The console output will say something like
   ``interior alignment: only 50 features``.
2. **Too many false matches.** If the sample has many similar-looking
   repeating structures, RANSAC may reject everything.

Things to try:

1. **Adjust ``interior_blur_base``.** Default 8. Lower it (4-6) if
   your features are fine-grained; raise it (10-15) if the sample
   is noisy at the pixel level.
2. **Lower ``interior_min_inlier_ratio``.** Default 0.4. If RANSAC
   is rejecting otherwise reasonable matches, try 0.3 or 0.25. Too
   low risks accepting bad alignments, so check the result
   visually.
3. **Disable interior refinement entirely.** Set
   ``interior_ecc=False``. Stage 3 will then just copy the stage 2
   result forward. This is a reasonable fallback when the sample
   just doesn't have enough interior structure for SIFT.

Wrong channel detected
----------------------

**Symptoms.** exo2micro loaded a channel that doesn't look right
— the image is black, or it's clearly the wrong colour plane from
what you expected. Or the ``Moffat fit`` produces a weird scale
and the diagnostic plots look nonsensical.

**Diagnose first.** Click **Survey raw channels** in the GUI, or
from Python::

   from exo2micro import survey_raw_channels
   survey_raw_channels('raw')

This prints, for each raw TIFF, which channels have non-zero
values and what their maxima and means are. You can confirm that
the dye you expect really is in the channel you expect.

If the auto-detection is picking the wrong channel, it usually
means the "wrong" channel has a higher mean due to noise or
background contamination. The fix is out-of-scope for this
troubleshooter — see :doc:`../developers/concepts` for how
``_extract_signal_channel`` works, or file an issue.

Scale estimate looks implausible
--------------------------------

**Symptoms.** The Moffat fit produces a scale that doesn't match
what the data visibly demands — e.g. the difference image has a
large negative (cool) region where you expected zeros.

Things to try:

1. **Check the ratio histogram.** If it has multiple peaks or the
   peak is broad, the Moffat fit may have latched onto the wrong
   mode.
2. **Run with ``scale_percentile=50``** as a sanity check. The
   median of the log-ratio distribution is a simple, robust
   background estimator. If it disagrees significantly with the
   Moffat fit, something's off and you should probably use the
   percentile value.
3. **Run with ``manual_scale``** set to a value you think is right
   and compare the three difference images in the
   ``excess_heatmap.png`` plot. Pick whichever visually tracks
   the background ridge best.
4. **Extreme percentiles are dangerous.** Asking for the 99th
   percentile of the ratio distribution when even 1% of pixels
   are microbes will land you in the microbe tail, not the
   background. Prefer moderate percentiles (30-70).

Large negative patches in the difference image
-----------------------------------------------

**Symptoms.** Parts of the difference image are strongly negative
— cool colours dominating where you expected near-zero.

**Most common cause.** The scale factor is too high — you're
oversubtracting. The auto Moffat fit can occasionally overshoot.

**Fix.** Either:

1. Lower the scale manually — set ``manual_scale`` to a value
   slightly below the Moffat estimate and compare. Try stepping
   down in increments of 0.05.
2. Use ``scale_percentile=40`` or ``scale_percentile=50`` — often
   lands closer to the true background.

**Less common cause.** Your alignment is off, so "pre has features
where post doesn't" creates spurious negative residuals. Check the
blink comparison at a few locations. If things are jumping, fix
the alignment first.

Banding or striping in the difference image
-------------------------------------------

**Cause.** Residual rotation or shear misalignment — your
alignment transform is slightly wrong in an angular sense.

**Fix.**

1. Check the blink comparison on a feature near one edge of the
   sample and another near the opposite edge. If the feature
   near the edge jumps more than the feature near the centre,
   it's a rotational error.
2. Try widening ``angle_range`` (default 20 degrees) and lowering
   ``angle_step`` (default 1 degree) for a finer rotation search.
3. Enable ``save_all_intermediates=True`` and use the blink
   panel to compare the stage-2 coarse result against the
   stage-2 ICP result. If ICP is making it worse, something's
   wrong with boundary extraction.

Empty or nearly-empty difference image
--------------------------------------

**Cause.** Either the alignment completely failed (producing an
all-zero aligned pre-stain) or the scale factor is way too low
and the pre-stain signal is swamping the post-stain signal
everywhere.

**Fix.** Check the ``pre_post_heatmap.png`` plot first. If it's
nearly empty or the ridge is weird, the alignment is the problem
— go back to the alignment troubleshooting section above.

If the heatmap looks fine but the difference image is still
empty, double-check your ``scale_percentile`` / ``manual_scale``
values — a scale of 0.1 on a dataset that really wants 1.3 will
produce a difference image that's almost entirely positive and
indistinguishable from the original post-stain image.

Pipeline says a checkpoint is missing
-------------------------------------

**Symptom.** You set ``from_stage=3`` and get a message like
``upstream checkpoints missing: [(1, 'post'), (2, 'pre')]`` with
the pipeline then falling back to running from stage 1.

**Cause.** Either you haven't run the earlier stages yet, or the
parameters you've set change the filename of an upstream
checkpoint and exo2micro can't find the one that exists. Filenames
include non-default parameter values as suffixes, so changing
``boundary_width`` from 15 to 20 means stage 2 is looking for
``02_icp_aligned_pre_bw20.tiff`` instead of ``02_icp_aligned_pre.tiff``.

**Fix.** Either reset the parameters to match an existing run, or
just let the pipeline re-run from stage 1 — it's only slow if you
have many samples.

The GUI is slow or unresponsive
-------------------------------

**Cause.** Usually means Jupyter is busy rendering many inline
figures. With **Show diagnostic plots inline** enabled and many
samples in the batch, the output cell can balloon.

**Fix.** Uncheck **Show diagnostic plots inline** for large
batches. The plots are still saved to ``pipeline_output/`` — you
can inspect them afterward from disk, or use the Zoom & Inspect
panel to reload any particular one.

Filename problems
-----------------

exo2micro is strict about raw filename conventions (see
:doc:`installation`). When something is wrong with a filename, you
get a clear "FILE PROBLEM" message during the run, the affected
``(sample, dye)`` task fails, and the pipeline continues with the
next task. All failed tasks are listed in a "PROBLEMS" section in
the summary at the end of the batch.

This section catalogues each error message you might see and what
to do about it.

**AMBIGUOUS: <filename> contains both 'pre' and 'post' in the
filename**

The filename contains both substrings somewhere in it (e.g.
``Sample_pre_post_DAPI.tif``). The loader can't tell whether you
meant pre-stain or post-stain.

*Fix:* rename the file so only one of ``pre`` or ``post`` appears
anywhere in the name. Most often this means dropping a confusing
date or run identifier — ``Sample_2024-03-pre_DAPI.tif`` is fine,
``Sample_pre_post_DAPI.tif`` is not.

**NO STAIN MARKER: <filename> contains neither 'pre' nor 'post'**

The filename has no recognizable stain-type indicator. The loader
can't classify it as pre-stain or post-stain.

*Fix:* rename the file to include ``pre`` or ``post`` (or
``PreStain``/``PostStain``) somewhere in the basename. Where in the
name doesn't matter — the loader does a substring search.

**NO UNDERSCORE: <filename> has no underscore before the extension**

The filename has no ``_`` before ``.tif``/``.tiff``, so there's no
way to extract a dye name. For example: ``DAPI.tif``.

*Fix:* prepend an underscore-separated prefix:
``Sample001_PreStain_DAPI.tif``.

**EMPTY DYE: <filename> has nothing between the last underscore and
the extension**

There's an underscore right before the extension (e.g.
``Sample_PreStain_.tif``), so the dye name is empty.

*Fix:* add the dye name between the trailing underscore and the
extension.

**Incomplete pair for <sample> / <dye>: no file containing 'pre'
ends with ``_<dye>.tif``**

The loader found a post-stain file for that dye but no matching
pre-stain file (or vice versa). Each ``(sample, dye)`` combination
needs both halves to process.

*Fix:* either add the missing file, or remove the orphan side and
drop that dye from your run. Note that the missing-side message
mentions the *exact* filename pattern the loader is looking for,
which is usually enough to spot the typo.

**Duplicate pair for <sample> / <dye>: expected exactly one
pre-stain and one post-stain file but found N**

There are multiple files in the same sample directory that all
match ``_<dye>.tif`` and all contain ``pre`` (or all contain
``post``). The loader can't decide which one to use.

*Fix:* rename or remove the extras. The error message lists every
candidate filename so you can see exactly which files are
colliding. A common cause is leaving an old run's output in the
raw directory — move it to an archive folder.

**No raw files matching dye '<dye>' in <directory>**

You requested a dye name that doesn't appear in any of the raw
filenames in that sample directory. The error message lists every
dye exo2micro *did* find in that directory.

*Fix:* either remove that dye from your run for that sample, or
check for typos against the listed dyes. Note that dye matching is
case-sensitive — ``DAPI`` and ``dapi`` are different.

If the requested dye name contains an underscore, the error message
also explicitly flags that as a likely problem and suggests the
correct dye name. The most common mistake is asking for
``'SybrGld_microbe'`` when the dye is actually ``'SybrGld'`` and
``'microbe'`` was just a descriptor in the filename. Dye names must
not contain underscores; the dye is whatever comes between the
last underscore and the extension.

**Sample directory not found: <path>**

The sample subdirectory doesn't exist under your ``raw_dir``.

*Fix:* check the spelling of the sample name in your input list,
and confirm the directory actually exists at the expected path. If
your samples live somewhere else, pass a custom ``raw_dir`` to the
GUI or to :class:`SampleDye`.

A note on partial success
~~~~~~~~~~~~~~~~~~~~~~~~~

exo2micro processes each ``(sample, dye)`` task independently. If
one task in your batch fails — say, ``CD070`` is missing its DAPI
pre-stain image — every other task in the batch still runs. You'll
see a clear error message for the failed task in real time, and at
the end of the batch the summary table shows a "PROBLEMS" section
listing every failed task with its full error message. There's no
need to scroll back through the mid-stream output to see what
broke.

This applies even within a single sample folder: if ``CD070``
contains clean ``SybrGld`` images and broken ``DAPI`` images,
``SybrGld`` will process successfully and ``DAPI`` will fail with a
clear message about exactly what's wrong.
