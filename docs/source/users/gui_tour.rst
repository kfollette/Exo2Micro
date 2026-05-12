GUI Tour
========

This page walks through every panel of the exo2micro GUI, top to
bottom. It's the reference you come back to when you're not sure what
a particular control does.

.. todo::

   Add an annotated screenshot of the full GUI here, with callouts
   labelling each panel. Place it at
   ``docs/source/users/_images/gui_overview.png``.

.. Overview image placeholder
.. .. image:: _images/gui_overview.png
..    :alt: exo2micro GUI overview
..    :width: 100%

Input Selection
---------------

This is where you pick which samples and dyes to process.

**Samples** and **Dyes** are simple text areas — one entry per line.
Processing runs every sample × dye combination.

**Auto-detect** scans your raw directory for sample subfolders and
extracts likely dye names from the filenames. Saves typing when you
have many samples.

**Survey raw channels** reads a small central crop from every raw
TIFF and reports which RGB channels carry signal. This is a
pre-flight sanity check — run it once at the start of a new dataset
to confirm exo2micro's automatic channel detection will pick the
right channel for each dye.

Scale
-----

The **Scale** dropdown controls how exo2micro estimates the scale
factor used to subtract the pre-stain background:

- **Auto (Moffat fit)** — the default. A Moffat profile is fit to
  the log-ratio distribution and the peak is used as the scale.
  Works well for most samples.
- **Auto + ratio percentile** — the Moffat fit still runs, and *in
  addition* a second difference image is computed using a chosen
  percentile of the log-ratio distribution as the scale. A text box
  appears for you to enter the percentile (accepts decimals, e.g.
  ``99.1``).
- **Auto + manual override** — the Moffat fit still runs, and *in
  addition* a second difference image is computed using an exact
  scale value you type in.
- **Auto + percentile + manual** — produces all three.

See :doc:`scale_methods` for guidance on when to reach for each.

Execution Options
-----------------

**Parallel (multiprocessing)** — check this to run multiple samples
concurrently. For small batches (1-3 samples) the overhead of
starting workers often makes serial faster; for larger batches
parallel is usually a big win.

**Workers** — how many parallel worker processes to run. Rule of
thumb: ``workers × peak RAM per sample < your total RAM``. Start
with 4 and adjust based on what your machine can handle.

**Force rerun (ignore checkpoints)** — normally exo2micro skips any
stage whose checkpoint already exists on disk. Checking this box
re-runs everything from scratch.

**From stage** — where to start. ``Auto (resume)`` picks up from the
latest checkpoint. Pick a specific stage when you've changed a
parameter that only affects that stage onward. For example, if you
want to try a different ``scale_percentile`` value, pick stage 4.

**To stage** — where to stop. Useful if you only want to regenerate
the diagnostic plots (stop at 4) without touching alignment.

**Show diagnostic plots inline** — displays the stage-4 diagnostic
plots in the notebook as each sample finishes, with short captions
explaining each. Turn it off if you're batch-processing dozens of
samples and don't want the output cell to balloon.

Advanced Parameters
-------------------

Collapsed by default. When expanded, shows every tunable parameter
organized into four tabs (one per pipeline stage). Each widget
shows the parameter's short abbreviation (used in filenames) and a
one-line description.

Most users never need to touch these. If you do, see
:doc:`../developers/parameters` for a full reference.

The three action buttons
------------------------

**▶ Run Pipeline** — kicks off processing on the current sample/dye
selection.

**📋 Check Status** — prints a checklist showing which checkpoint
files exist on disk for each sample × dye combination (under the
current parameter settings). Useful for seeing where you left off.

**↺ Reset Params** — clears any advanced parameter changes and
restores defaults.

Parameter Comparison
--------------------

A convenience for sweeping one parameter across several values.
Pick a parameter from the dropdown, enter comma-separated values
(e.g. ``10, 15, 20``), and click **Compare**. exo2micro re-runs the
affected stage for each value on the first sample × dye combination
and shows the results side by side.

If **Save variants to disk** is checked, each run's checkpoints are
written with the non-default value embedded in the filename (e.g.
``02_icp_aligned_pre_bw10.tiff``), so variants coexist without
overwriting each other.

🔍 Zoom & Inspect
-----------------

See :doc:`zoom_and_inspect`.

👁️ Blink Comparison
-------------------

A visual tool for checking alignment quality. Load two alignment
checkpoints — typically the stage-1 post-stain and either the stage-2
ICP-aligned pre-stain or the stage-3 interior-aligned pre-stain —
then click the **Blink: A ⇄ B** toggle to flip between them at any
region of interest.

Good alignment means structures barely shift when you flip. Bad
alignment means things jump around.

Workflow:

1. Enter your sample and dye.
2. Pick image A (usually **Post, reference, stage 1**) and image B
   (usually **Interior-aligned pre, stage 3**).
3. Click **Load**. Both images are loaded as downsampled previews.
4. Use the Row / Col / Size sliders to frame a region of interest
   (a conspicuous feature in the sample is ideal).
5. Click the **Blink: A ⇄ B** toggle button repeatedly to flip
   between the two images. Features that stay in place are
   well-aligned; features that shift indicate residual error.

To diagnose where in the pipeline an alignment problem came from,
compare stage 2 (ICP) against stage 3 (interior). If stage 2 is
already bad, the boundary alignment failed and you want to look at
``boundary_width`` / ``boundary_smooth``. If stage 2 is good but
stage 3 is bad, SIFT matching in the interior went wrong; check
``interior_blur_base`` or ``interior_min_inlier_ratio``.

Progress bar and output
-----------------------

As the pipeline runs, the progress bar tracks total tasks completed.
The output area below shows real-time text from each pipeline stage
plus the inline diagnostic plots (when enabled) and the final
summary table.

The summary table shows the Moffat scale for every completed run,
plus — when you used ``scale_percentile`` or ``manual_scale`` —
extra columns for those alternative scales.
