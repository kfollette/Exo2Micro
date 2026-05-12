Scale Methods
=============

This page explains the three ways exo2micro can estimate the
pre-stain scale factor, when to use each, and what the output
files look like for each.

The problem
-----------

After alignment, exo2micro needs to subtract a scaled version of
the pre-stain image from the post-stain image:

.. code-block:: text

   difference = post − scale × pre

Choosing the right ``scale`` matters. Too low and you undersubtract
(the background bleeds through and masks microbe signal). Too high
and you oversubtract (the background "becomes negative" and real
microbe features appear suppressed). The exact right value depends
on how the autofluorescent background scaled between pre-stain and
post-stain imaging.

Auto (Moffat fit) — the default
-------------------------------

What it does
~~~~~~~~~~~~

exo2micro computes the log-ratio ``log₁₀(post/pre)`` at every pixel
where both images have signal, bins this into a histogram, and fits
a Moffat profile — that's:

.. code-block:: text

   amp × (1 + ((x − μ) / α)²)^(−β)

— to the left wing of the distribution mirrored across the peak.
The fitted peak centre ``μ`` is the background scale estimate, and
``scale = 10^μ``.

Why a Moffat fit? The log-ratio distribution has a sharp central
peak from autofluorescent background pixels (which have a consistent
ratio) and a long right tail from microbe pixels (which have a
higher ratio because they gained fluorescence). We want the peak
centre, not the tail. A Gaussian fits the peak poorly because
microscopy noise has longer tails than a normal distribution; a
Moffat profile matches the empirical peak shape much better.

When to use it
~~~~~~~~~~~~~~

This is the right choice almost always. Use it as your default.

Output
~~~~~~

- ``processed/{sample}/{dye}/tiff/04_difference_difference.tiff`` —
  the scaled difference image
- ``...fits/04_difference_difference.fits`` — same, with the scale
  factor in the ``SCALE`` header keyword and ``SCALEK = 'moffat'``
- ``...pipeline_output/difference_image.png`` — visualization
- ``...pipeline_output/ratio_histogram.png`` — the fit itself,
  which you should check

Ratio percentile
----------------

What it does
~~~~~~~~~~~~

Computes the per-pixel ratio ``post/pre`` at every pixel where
both images have signal, takes the chosen percentile of that
distribution, and uses it as the scale factor.

You enable this by setting the ``scale_percentile`` parameter to a
float value between 0 and 100 (decimals like ``99.1`` are accepted).
This is also exposed in the GUI via the **Scale** dropdown.

Importantly, setting ``scale_percentile`` does *not* replace the
Moffat fit — the Moffat-fit difference image is still produced.
Instead, an **additional** difference image is produced using the
percentile-derived scale. This lets you compare the two side by
side in the ``excess_heatmap.png`` plot (which overlays both scale
lines) and in the two difference TIFFs.

When to use it
~~~~~~~~~~~~~~

The percentile method is most useful when:

- You have a clear intuition about what fraction of your tissue
  should be "background only" vs. "microbe signal". If you expect
  roughly half the tissue to have microbes, the 50th percentile of
  the ratio distribution is a reasonable estimate of the
  background-only scale.
- You want a quick sanity check against the Moffat fit by picking
  a percentile you think should land in the background cluster
  (typically between 20 and 70 for most samples).
- You're building a processing procedure for a new sample type
  where you don't yet trust the Moffat fit and want a
  percentile-based control you understand exactly.

**Watch the percentile value you pick.** If you ask for the 99th
percentile of a ratio distribution where even 1% of pixels are
microbes, you'll land in the microbe tail and get an implausibly
large scale. Moderate percentiles (30-70) are usually the right
range for this method.

Output
~~~~~~

With ``scale_percentile=50`` set, in addition to the standard
Moffat outputs, you get:

- ``04_difference_difference_percentile_p50{suffix}.tiff``
- ``04_difference_difference_percentile_p50{suffix}.fits`` (with
  ``SCALE`` header recording the computed value and
  ``SCALEK = 'percentile_p50'``)
- ``difference_image_percentile_p50{suffix}.png``

Where ``{suffix}`` reflects all non-default parameters in the run,
including the percentile value itself.

Manual override
---------------

What it does
~~~~~~~~~~~~~

You type in an exact scale value and exo2micro uses it verbatim.
Set with the ``manual_scale`` parameter (a float). Also exposed in
the GUI via the **Scale** dropdown.

Like ``scale_percentile``, setting ``manual_scale`` doesn't replace
the Moffat fit — it adds a third difference image that uses your
value.

When to use it
~~~~~~~~~~~~~~

- You're reproducing a published result that specified a particular
  scale factor.
- You've already processed the dataset once with auto scale, saw
  the Moffat fit land somewhere slightly off, and want to try a
  nearby value by hand.
- You're doing sensitivity analysis — running the same sample with
  several nearby scale values to see how stable the subtraction is.
- The Moffat fit failed (e.g. your sample has an unusually
  distributed ratio distribution) and you need to bypass it.

Output
~~~~~~

With ``manual_scale=1.42`` set, in addition to the standard Moffat
outputs, you get:

- ``04_difference_difference_manual{suffix}.tiff``
- ``04_difference_difference_manual{suffix}.fits`` (with ``SCALE =
  1.42`` and ``SCALEK = 'manual'``)
- ``difference_image_manual{suffix}.png``

All three at once
-----------------

You can set ``scale_percentile`` and ``manual_scale`` simultaneously.
Stage 4 will compute all three: Moffat, percentile, and manual. The
``excess_heatmap.png`` plot overlays all three scale lines in
different colours, making it easy to see which one best tracks the
peak of the pre vs. post density ridge.

This is the recommended workflow when you're deciding what scale to
use for a new dataset: run all three, compare the difference image
PNGs, pick the one that looks best, and note that value for future
runs.

Reading the excess heatmap
--------------------------

The ``excess_heatmap.png`` plot in ``pipeline_output/`` is the key
visual for comparing scale choices. It shows a 2-D histogram of pre
vs. post brightness with the diagonal reflection subtracted off —
anything visible is excess post-stain signal. Scale lines are
overlaid in different colours:

- **Green** (``#00cc88``) — Moffat fit
- **Orange** (``#ff9933``) — ratio percentile
- **Pink** (``#ff3366``) — manual value

A well-chosen scale passes along the ridge of the background
distribution, leaving the bright excess cells (the microbe signal)
cleanly above the line.

.. todo::

   Add an example ``excess_heatmap.png`` here showing all three
   scale lines overplotted. Save to
   ``docs/source/users/_images/excess_heatmap_example.png``.
