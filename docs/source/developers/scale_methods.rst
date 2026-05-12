Scale Estimation Methods
========================

This page explains the math behind exo2micro's scale estimation
methods. For a lower-level user-facing version, see
:doc:`../users/scale_methods`.

The goal
--------

After alignment, we need a scalar ``s`` such that:

.. code-block:: text

   diff = post − s × pre

cleanly separates background from signal. Specifically we want
``s`` to equal the ratio between post-stain and pre-stain
autofluorescent background, so that background pixels (where
``post ≈ s × pre``) subtract out near zero and microbe pixels
(where ``post > s × pre``) stand out as positive excess.

The Moffat-fit method (default)
-------------------------------

The canonical v2.3 method fits a Moffat profile to the left wing
of the log-ratio distribution.

The setup
~~~~~~~~~

Compute per-pixel ratios for the "both have signal" pixels::

   r = post[both] / pre[both]

and take ``log₁₀``::

   x = log10(r)

For pixels where the post-stain is pure autofluorescence (same as
pre-stain × true ratio), ``r`` clusters tightly around the true
background scale. For pixels where the post-stain also contains
microbe signal, ``r`` is larger — these pixels live in the right
tail of the log-ratio distribution.

So the distribution of ``x`` has:

- A peak at ``log10(true_background_scale)``.
- A left wing from noise fluctuations around that peak.
- A right tail from microbe-contaminated pixels.

We want to find the peak centre, ignoring the right tail.

The Moffat profile
~~~~~~~~~~~~~~~~~~

.. code-block:: text

   M(x; amp, μ, α, β) = amp × (1 + ((x − μ) / α)²)^(−β)

Moffat profiles were originally developed for astronomical
point-spread functions. They have:

- A sharper peak than a Gaussian (when ``β`` is small), which
  matches empirical microscopy noise better.
- Power-law wings rather than exponential ones, which handles
  outliers more gracefully.

The family smoothly interpolates: ``β = 1`` is a Lorentzian
(heavy tails), large ``β`` approaches a Gaussian. We fit ``β``
freely and let the data decide.

Why not just fit a Gaussian? Because the pre/post ratio
distribution in real microscopy data consistently has sharper
peaks and longer tails than a Gaussian would predict. The
pre-v2.2 code tried a Voigt profile (Gaussian × Lorentzian
convolution) and it was OK, but Moffat is cleaner to fit — one
fewer parameter, and ``curve_fit`` converges more reliably.

Why not use a simple histogram peak finder? The log-ratio
histogram has quantization artifacts near ``log10(1) = 0`` from
integer pixel values (e.g. ``post = 5, pre = 5`` produces
exactly zero). These form a spurious spike that can fool a naive
peak finder.

The fitting procedure
~~~~~~~~~~~~~~~~~~~~~

The ``plot_ratio_histogram_simple`` function in
``exo2micro.plotting`` does:

1. Histogram ``x`` with 200 bins over its full range.
2. Smooth with a uniform filter (kernel size ``2*sigma+1``
   where ``sigma`` is a constant 3). This gives a clean peak to
   find.
3. Exclude bins within ``3 × bin_width`` of ``x = 0`` to avoid
   the quantization spike.
4. Find the peak of the smoothed, spike-excluded histogram. Call
   this ``μ₀`` — the initial guess.
5. Select the left wing: bins with ``x ≤ μ₀`` excluding the
   near-zero band.
6. Mirror it across ``μ₀``: for each ``(x, y)`` point in the
   left wing, synthesize ``(2μ₀ − x, y)``.
7. Fit a Moffat profile to the combined real-left-wing +
   synthetic-right-wing data using :func:`scipy.optimize.curve_fit`.
8. The fitted ``μ`` is the refined peak centre.
9. ``scale = 10^μ``.

Why mirror the left wing? Because the right side of the real
distribution is contaminated by microbe signal (the long
positive tail we want to ignore). Mirroring the left wing gives
``curve_fit`` a symmetric target that represents what the noise
distribution *would* look like without the microbe contribution,
and that's what we want to match.

Failure modes
~~~~~~~~~~~~~

- **``curve_fit`` doesn't converge.** Rare with 200 bins, but
  possible on pathological data. The pipeline falls back to the
  smoothed-histogram peak ``μ₀`` and prints a message. Still a
  usable scale, just less refined.
- **Peak lands in the wrong place.** Can happen when the data
  has multiple modes (e.g. two distinct tissue types with
  different autofluorescence ratios). In that case, check the
  ``ratio_histogram.png`` plot — if the peak is clearly wrong,
  fall back to a percentile-based method.
- **Very few pixels.** If ``len(both) < ~1000``, the histogram is
  too sparse for a meaningful fit. This usually indicates a
  failed alignment.

The ratio percentile method
---------------------------

Sometimes you want a simpler, more transparent alternative. The
``scale_percentile`` parameter produces one.

Mathematically::

   x = log10(post[both] / pre[both])
   scale = 10^percentile(x, p)

for a user-chosen percentile ``p``. This is a one-line reduction
with no fitting, no histogramming, no assumptions about noise
distribution shape.

**When it beats the Moffat fit.** When the log-ratio
distribution is multi-modal or non-symmetric in a way that the
Moffat assumption can't handle, the percentile method can be
more robust — you're explicitly telling it "I want the value at
this fraction of the sorted distribution", which bypasses any
notion of "peak". The median (p = 50) in particular is a very
stable estimator that just asks "what's the typical ratio?".

**When it loses.** When microbe signal pushes the upper tail
around, extreme percentiles (p > 90) can land in the microbe
cluster. Always prefer moderate percentiles (20-70) unless you
have a strong reason.

**Implementation.** See ``SampleDye._compute_scale_percentile``
in ``pipeline.py``. It's three lines — compute both-signal mask,
take the per-pixel ratio, take the percentile.

The manual method
-----------------

``manual_scale`` is the simplest: the user specifies an exact
scale factor and exo2micro uses it verbatim. No estimation, no
fitting.

Use cases:

- Reproducing a published result that specified a particular
  scale factor.
- Sensitivity analysis (running the same sample with several
  nearby scale values).
- Bypassing the Moffat fit when it's clearly misbehaving on an
  unusual dataset.

Coexistence
-----------

All three methods can be active simultaneously:

- The Moffat fit is always computed (it drives the canonical
  difference image and the scale line on the excess heatmap).
- If ``scale_percentile`` is set, an additional difference image
  is produced at that percentile scale.
- If ``manual_scale`` is set, an additional difference image is
  produced at that exact scale.

The excess heatmap overplots all active scale lines in different
colors, so you can visually compare them side-by-side:

- **Green** (``#00cc88``) — Moffat fit
- **Orange** (``#ff9933``) — ratio percentile
- **Pink** (``#ff3366``) — manual value

This is the recommended workflow for a new dataset: run with all
three active, compare in the excess heatmap, and decide which
method you trust most for that sample type.

Internal code paths
-------------------

The stage-4 diagnostic code in ``pipeline.py`` calls:

- :func:`exo2micro.plot_ratio_histogram_simple` — returns the
  Moffat-fit scale and saves the histogram PNG.
- :meth:`SampleDye._compute_scale_percentile` — returns the
  percentile scale (or ``None`` if no valid pixels).
- :meth:`SampleDye._save_difference` — produces TIFF + FITS +
  PNG for a single scale value, labelled ``'moffat'``,
  ``'percentile_p<value>'``, or ``'manual'``.
- :func:`exo2micro.plot_excess_heatmap` with a ``scales=`` list
  of ``(label, value, colour)`` tuples, which draws one line
  per active scale.

Legacy scaling methods
----------------------

exo2micro 2.1 and earlier had two additional methods,
least-squares (LS) and robust-percentile, implemented in the
removed ``scaling.py`` module. Both are preserved verbatim in
``exo2micro.legacy`` for back-compat but are not called by the
v2.3 pipeline. The reasons they were dropped:

- **LS.** Minimizes squared residuals over a tissue mask. This
  is biased upward by bright microbe pixels, which pull the
  dot-product estimate toward higher scale values. On
  well-aligned images with visible microbe signal, LS commonly
  oversubtracted by ~10-30%.
- **Robust percentile.** The old ``robust_percentile=90`` default
  was too aggressive — with well-aligned images, the 90th
  percentile of the ratio distribution consistently landed in
  the microbe tail and produced scale estimates ~4× too high.
  Moderate percentiles worked fine; the current
  ``scale_percentile`` parameter is the same math with a clearer
  default (``None``, meaning "don't use this method unless you
  explicitly set a percentile").

If you need the old behaviour for reproducing an earlier result,
use ``exo2micro.legacy.optimize_subtraction`` directly::

   from exo2micro.legacy import optimize_subtraction
   opt_scale, scale_sig, tissue_mask, plot_data = optimize_subtraction(
       post_im, pre_im, method='least_squares')
