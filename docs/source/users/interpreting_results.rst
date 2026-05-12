Interpreting Results
====================

Stage 4 produces five diagnostic plots plus the final difference
image. Each is a different view of the same underlying question:
*how well does the scaled pre-stain image match the post-stain
background?* This page shows what to look for in each.

All plots are saved to
``processed/{sample}/{dye}/pipeline_output/``.

Pre/post heatmap
----------------

.. todo::

   Add an example ``pre_post_heatmap.png``. Save to
   ``docs/source/users/_images/pre_post_heatmap_example.png``.

**What it is.** A 2-D density heatmap binned on integer pre-stain
and post-stain values (256 × 256 grid). Brightness is log₁₀ pixel
count.

**What a good one looks like.** Most pixels cluster along a single
ridge running from bottom-left to upper-right. The ridge should be
roughly linear with small scatter, and its slope is the true
background scale factor. Bright pixels above the ridge are
candidate microbe signal.

**What a bad one looks like.** A cloud instead of a ridge usually
means the pre and post images aren't aligned. Multiple disconnected
ridges may mean channel mismatch — check :doc:`troubleshooting`.

Excess heatmap
--------------

.. todo::

   Add an example ``excess_heatmap.png``. Save to
   ``docs/source/users/_images/excess_heatmap_example.png``.

**What it is.** The same pre/post density grid, but with its
transpose subtracted off. The diagonal reflection cancels any
symmetric noise component, leaving only the asymmetric "excess"
signal where the post-stain image is brighter than the pre-stain
image at a given background level. Negative and zero cells are
masked white; visible cells are candidate microbe signal.

Scale lines are overplotted:

- **Green** — Moffat fit
- **Orange** — ratio percentile (if ``scale_percentile`` is set)
- **Pink** — manual value (if ``manual_scale`` is set)

**What a good one looks like.** The scale line runs right along the
lower edge of the bright excess cells. All the excess signal sits
above the line — these are the microbes.

**What a bad one looks like.** If the scale line cuts through the
middle of the excess cells, you're oversubtracting. If the line is
well below the excess cells (lots of space between them), you're
undersubtracting slightly but the difference image should still be
usable.

This is the single most useful plot for comparing multiple scale
choices. If you ran with all three methods active, they'll all
appear here and you can see which one best hugs the ridge.

Pre/post histograms
-------------------

.. todo::

   Add an example ``pre_post_histograms.png``. Save to
   ``docs/source/users/_images/pre_post_histograms_example.png``.

**What it is.** Two overlapping histograms of pixel brightness, one
for pre-stain and one for post-stain, integer-aligned bins, log
y-axis.

**What it tells you.** Whether the overall brightness distribution
shifted between the two images. A post-stain distribution that's
uniformly right-shifted is the expected case (because the stain
added light). A post-stain distribution that looks like the
pre-stain one "pulled upward by a constant" means the background
scale factor is roughly uniform — ideal. A post-stain distribution
that's differently shaped usually means something went wrong in
acquisition.

Difference histogram
--------------------

.. todo::

   Add an example ``difference_histogram.png``. Save to
   ``docs/source/users/_images/difference_histogram_example.png``.

**What it is.** A histogram of ``post − pre`` (unscaled) per pixel,
with three overlaid subsets: all pixels (outline), pixels where both
pre and post have signal (teal fill), and pixels where only post
has signal (orange fill).

**What to look for.** The orange fill (post-only excess) should sit
entirely in the positive half of the histogram — these are the
microbe pixels. The teal fill should be roughly centred on zero
with a long positive tail; a strong negative shift means your
alignment is off or your background scale is unusual.

Ratio histogram with Moffat fit
-------------------------------

.. todo::

   Add an example ``ratio_histogram.png``. Save to
   ``docs/source/users/_images/ratio_histogram_example.png``.

**What it is.** Histogram of ``log₁₀(post/pre)`` for pixels where
both images have signal. The grey curve shows the fitted Moffat
profile, and the orange vertical line marks the fitted peak centre
(which becomes the scale estimate).

**What a good fit looks like.** The histogram has a clear peak,
the Moffat profile traces the left wing cleanly, and the peak
centre sits at the top of the histogram. The "scale estimate =
1.xxx" label in the legend is the value that ends up in the
difference image.

**What a bad fit looks like.** If the peak is very broad or split
into multiple peaks, the fit may land in the wrong place. If you
see ``Moffat fit failed`` in the console output, the pipeline falls
back to the peak of the smoothed histogram — still usable, but
worth checking against an alternative method (e.g.
``scale_percentile=50``).

Difference image
----------------

.. todo::

   Add an example ``difference_image.png``. Save to
   ``docs/source/users/_images/difference_image_example.png``.

**What it is.** The final scaled difference ``post − scale × pre``
with an asinh stretch (which compresses extreme values while
preserving sign) and a diverging colormap.

**How to read it.** Positive (warm) values are pixels where the
post-stain is brighter than expected — candidate microbe signal.
Near-zero (dark) values are well-subtracted background. Negative
(cool) values are pixels where the pre-stain was brighter than the
scaled post-stain — typically noise, alignment artefacts near
edges, or mild oversubtraction.

A well-processed image shows distinct bright features on a
near-black background, with no large negative (cool) patches except
possibly a thin ring at the tissue edge.

For higher-resolution inspection of specific regions, use
:doc:`zoom_and_inspect`.

What to do next
---------------

If the difference image looks great — you're done. Load the
``.tiff`` or ``.fits`` into ImageJ / Python / MATLAB and move on to
your downstream analysis.

If something looks off, see :doc:`troubleshooting`.
