Quickstart
==========

This page gets you from zero to a first difference image. It assumes
you've finished :doc:`installation` and have at least one sample's
raw TIFFs in place.

Launching the GUI
-----------------

The easiest way to use exo2micro is the interactive notebook GUI.
Start a Jupyter notebook (``jupyter lab`` or ``jupyter notebook``),
open ``exo2micro_notebook.ipynb``, and run the two setup cells. You
should see the exo2micro interface appear.

You can also launch the GUI from any notebook cell::

   from exo2micro.gui import launch
   gui = launch(
       output_dir='processed',   # where results are saved
       raw_dir='raw',        # where your raw images live
   )

Survey your raw channels (recommended)
--------------------------------------

Before processing, click **Survey raw channels** in the GUI. This
reads a small central crop from each of your raw TIFFs and reports
which RGB channel(s) actually carry fluorescence signal.

This matters because exo2micro's image loader auto-detects which
channel has the dye signal. Running the survey once up front catches
problems like "I thought SybrGold was in the green channel but actually
it's in red" before you waste time on a full run.

Picking your samples and dyes
-----------------------------

Enter one sample name per line in the **Samples** box (e.g.
``CD070``) and one dye name per line in the **Dyes** box (e.g.
``SybrGld_microbe``). Or just click **Auto-detect** — it scans your
raw directory and fills both boxes in.

Every sample × dye combination will be processed.

Picking a scale method
----------------------

The **Scale** dropdown controls how exo2micro estimates the
pre-stain scale factor. For your first run, leave it on
**Auto (Moffat fit)**. Come back to :doc:`scale_methods` later if
you need the percentile or manual options.

Running
-------

Click **▶ Run Pipeline**. For each sample × dye:

1. **Stage 1 — Padding.** Raw images are loaded and placed on a
   common canvas.
2. **Stage 2 — Boundary alignment.** exo2micro finds the best rigid
   alignment using the sample outline.
3. **Stage 3 — Interior alignment.** The alignment is refined using
   SIFT features inside the sample.
4. **Stage 4 — Diagnostics.** The background scale factor is
   estimated and the difference image is computed and saved.

Each stage saves checkpoints to disk, so if you stop and re-run,
exo2micro picks up where it left off.

Watching the diagnostic plots
-----------------------------

With **Show diagnostic plots inline** checked, the GUI displays the
five stage-4 plots for each sample as it finishes, along with short
captions explaining what to look for. If anything looks wrong, see
:doc:`troubleshooting`.

Finding your results
--------------------

Everything ends up under ``processed/``::

   processed/
     CD070/
       SybrGld_microbe/
         tiff/               ← intermediate and final images (float32)
         fits/               ← same images with FITS metadata headers
         pipeline_output/    ← all diagnostic plots as PNGs

The main result is the difference image::

   processed/CD070/SybrGld_microbe/tiff/04_difference_difference.tiff

Positive values in this image = fluorescence that appeared after
staining (candidate microbes). Near-zero values = consistent
autofluorescent background.

The FITS version has the scale factor and full parameter record in
its header for reproducibility::

   processed/CD070/SybrGld_microbe/fits/04_difference_difference.fits

Next: :doc:`gui_tour` walks through every GUI panel in detail,
and :doc:`interpreting_results` explains how to read the diagnostic
plots.
