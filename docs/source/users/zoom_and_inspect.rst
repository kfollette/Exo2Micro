Zoom & Inspect
==============

The **Zoom & Inspect** panel in the GUI lets you interactively
crop a region from any pipeline output, optionally smooth it with
a Gaussian blur, and either view it or save it to disk. It's
designed for inspecting fine structure in difference images, but
works on any stage output.

Why this exists
---------------

Raw microscopy images in this pipeline are typically around
30000 × 25000 pixels — about 3 GB of float32 data. Loading the full
image into an interactive viewer and dragging a selection box on
it is not workable.

exo2micro handles this by using a **downsampled preview** for the
interactive part of the workflow. When you load an image in the
zoom panel, it's cached at roughly 1500 pixels on its long axis so
slider interaction feels instant. When you want to see the actual
full-resolution crop, you check a box and exo2micro reloads the
full image from disk and crops it to match your current selection.
Saved views always write at full resolution.

Basic workflow
--------------

1. **Sample / Dye / Image.** Enter the sample and dye, then pick
   which image you want to inspect:

   - ``Post-stain`` — the reference frame
   - ``Aligned pre-stain`` — stage 3 output (best alignment)
   - ``ICP pre-stain`` — stage 2 output (coarser alignment)
   - ``Difference`` — stage 4 output, the main result

2. **Click Load.** exo2micro reads the TIFF from disk, builds a
   downsampled preview, and caches it. The sliders re-range to
   match the preview dimensions.

3. **Frame your region** using the **Row**, **Col**, and **Size**
   sliders. They operate on the downsampled preview, so movement
   is instant. The output panel below shows the current crop live.

4. **Adjust blur.** The **σ blur** slider applies a Gaussian filter
   to the crop before display. Useful for suppressing pixel noise
   so faint features show up. ``σ = 0`` means no blur.

5. **Check "Show full-res"** when you've found the region you want
   to inspect carefully. The full-resolution image is loaded from
   disk, cropped to match the current slider selection, smoothed
   with the current σ, and displayed.

6. **Click Save view** to write the current full-res crop to
   ``processed/{sample}/{dye}/pipeline_output/zoom_{kind}_r{row}_c{col}_s{size}[_sig{sigma}].png``.

Side-by-side comparison
-----------------------

Check **Show post + aligned pre + diff side-by-side** to render
three panels at the same crop coordinates: the post-stain, the
interior-aligned pre-stain, and the difference image. This is the
fastest way to verify that a feature you see in the difference
image has a plausible origin in the underlying data.

- If a bright spot in the difference image corresponds to a bright
  spot in post and nothing in pre, it's a real microbe candidate.
- If it corresponds to bright spots in both post and pre at
  different locations, it's an alignment artefact.
- If it's dim in both post and pre but bright in the difference,
  the scale factor may be too low (undersubtracting background).

Tips
----

- **Start with the difference image.** That's where the interesting
  features are. Use side-by-side mode to confirm anything
  suspicious.
- **Use blur sparingly.** A sigma of 1-3 is usually enough to
  suppress pixel-level noise without losing real structure. Higher
  values start hiding real features.
- **"Show full-res" is slow for huge images.** The first time you
  tick it, exo2micro has to load the full TIFF from disk (a few
  seconds for a 3 GB image). Subsequent full-res crops at
  different positions reload from disk each time — they don't
  cache. If you're comparing many regions quickly, leave
  "Show full-res" off until you've narrowed down.
- **Saved views always write full resolution**, regardless of
  whether "Show full-res" is ticked. So you can frame your region
  using the fast preview and then save without turning on
  full-res mode.

Using the zoom function from Python
-----------------------------------

All the zoom functionality is also available programmatically,
which is sometimes more convenient for batch inspection or
scripted figure generation::

   import tifffile
   from exo2micro import plot_zoom, plot_zoom_multi

   diff = tifffile.imread(
       'processed/CD070/SybrGld_microbe/tiff/04_difference_difference.tiff')

   # Single image
   fig, crop = plot_zoom(
       diff, row=5000, col=8000, size=800, sigma=2.0,
       diverging=True,
       title='CD070 / SybrGld_microbe — feature at (5000, 8000)',
       save_path='feature_zoom.png')

   # Side-by-side with post and aligned pre
   post = tifffile.imread(
       'processed/CD070/SybrGld_microbe/tiff/01_padded_post.tiff')
   pre  = tifffile.imread(
       'processed/CD070/SybrGld_microbe/tiff/03_interior_aligned_pre.tiff')

   fig2, crops = plot_zoom_multi(
       [post, pre, diff],
       labels=['post', 'aligned pre', 'difference'],
       row=5000, col=8000, size=800, sigma=2.0,
       diverging_flags=[False, False, True],
       sample='CD070', dye='SybrGld_microbe',
       save_path='feature_comparison.png')

See :doc:`../developers/api/plotting` for the full function
signatures.
