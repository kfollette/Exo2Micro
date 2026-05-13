# 🔬 exo2micro

**Image registration and fluorescence subtraction for pre/post-stain microscopy.**

exo2micro takes paired pre-stain and post-stain fluorescence images of mineral samples, aligns them, estimates the autofluorescent background scale factor, and subtracts it to reveal microbe-only signal.

Version 2.3.1.

---

## Before You Start

If you've never installed a Python package from GitHub before, the
[Before You Start](https://exo2micro.readthedocs.io/en/latest/users/before_you_start.html)
page walks you through everything you need on your computer first — opening
a terminal on macOS or Windows, making a GitHub account, installing Python
(via Miniforge), and getting JupyterLab running. **Start there if any of
the following are true:**

- You don't have a Python installation on your computer.
- You don't have a GitHub account.
- You've never opened a terminal (Terminal on Mac, Windows Terminal on PC).
- You don't have JupyterLab or Jupyter Notebook installed.

If all four are already set up, skip ahead to [Installation](#installation)
below.

---

## Installation

```bash
# Clone the repository
git clone https://github.com/kfollette/Exo2Micro.git
cd Exo2Micro

# Install dependencies
pip install numpy scipy opencv-python-headless matplotlib astropy tifffile Pillow ipywidgets
```

### Dependencies

| Package | Purpose |
|---------|---------|
| numpy | Array operations |
| scipy | Gaussian filtering, morphology, optimisation, curve fitting |
| opencv-python-headless | Image registration (boundary correlation, ICP, SIFT) |
| matplotlib | All plotting |
| astropy | FITS file I/O with metadata headers |
| tifffile | Full-precision TIFF I/O |
| Pillow | Raw image loading with auto channel detection |
| ipywidgets | Interactive Jupyter GUI (optional) |

---

## Quick Start

### Raw image directory layout

Your raw images should live in a directory tree with one folder per sample:

```
raw/
  CD070/
    Sample001_PreStain_SybrGld.tif
    Sample001_PostStain_SybrGld.tif
  CD063/
    Sample002_PreStain_SybrGld.tif
    Sample002_PostStain_SybrGld.tif
    Sample002_pre_run3_DAPI.tiff
    Sample002_post_run3_DAPI.tiff
```

**Filename rules:**
- Files end with `.tif` or `.tiff` (case-insensitive).
- Filename contains `pre` or `post` (case-insensitive) somewhere in the basename.
- Filename ends with `_<DyeName>.tif` (or `.tiff`).
- **Dye names must not contain underscores.** Use `SybrGld`, `DAPI`, `Cy5`, etc. — not `SybrGld_microbe`.
- Each sample directory must contain exactly one pre-stain and one post-stain file per dye.

If a filename is wrong, the affected `(sample, dye)` task fails with a clear error message and the rest of the batch keeps running. See `docs/source/users/troubleshooting.rst` for the full catalogue of error messages.

### Option 1: Interactive GUI (recommended for non-coders)

In a terminal, navigate to the folder where you cloned exo2micro and launch
JupyterLab:

```bash
cd Exo2Micro          # or wherever you cloned the repo
jupyter lab
```

Your web browser will open with the JupyterLab interface. In the file browser
on the left, double-click `exo2micro_notebook.ipynb` to open it, then run
both setup cells (click in each cell and press Shift+Enter). The exo2micro
GUI should appear under the second cell.

If you see something like `VBox(children=(HTML(value=...)))` instead of an
actual GUI, ipywidgets isn't installed correctly — run
`pip install ipywidgets` in your terminal, then restart the JupyterLab
kernel (Kernel menu → Restart Kernel) and re-run the cells.

To stop JupyterLab when you're done, return to the terminal window and
press `Ctrl+C`.

### Option 2: Python API

```python
import exo2micro as e2m

# Process a single sample + dye combination
run = e2m.SampleDye('CD070', 'SybrGld')
run.run()

# Check what's been processed
run.status()
```

### Option 3: Batch processing

```python
results = e2m.run_batch(
    samples=['CD070', 'CD063'],
    dyes=['SybrGld', 'DAPI', 'Cy5', 'Spy700'],
    from_stage=1,
    to_stage=4,
    force=True,
    parallel=True,
    n_workers=4,
)
```

By default `run_batch` is strict: if any requested `(sample, dye)` pair has no raw files on disk, it raises `FileNotFoundError` listing every missing pair so you can catch typos before a long batch starts. If your samples are heterogeneous (not every dye exists for every sample), pass `strict_dyes=False` to skip missing pairs silently and run only the present ones:

```python
results = e2m.run_batch(
    samples=['CD070', 'CD063'],
    dyes=['SybrGld', 'DAPI', 'Cy5'],
    strict_dyes=False,
)
```

The GUI handles this for you: it shows missing pairs in a confirmation banner with a "Run the present pairs anyway" button, plus muted gray tiles for every pair that got filtered out.

### Memory and parallel mode

If your computer has limited RAM (8 GB or less), or your images are very large, leave `parallel=False` (the default). Serial mode actively clears each sample out of memory before starting the next one, so you can process big batches without running out of RAM. Parallel mode is faster when you have memory to spare, but each worker holds its own copy of the current sample's images — 4 workers means 4× the memory use. See [Memory and Performance](https://exo2micro.readthedocs.io/en/latest/users/memory_and_performance.html) for guidance on sizing `n_workers`.

---

## How It Works

The pipeline has four stages. Each stage saves checkpoints, so you can stop and resume at any point.

### Stage 1 — Padding

Loads raw TIFF images and places them on a common zero-padded canvas. Automatically detects which RGB channel carries the fluorescence signal (e.g. green for SybrGold, blue for DAPI, red for Cy5) and extracts it at full 8-bit precision. For dyes with signal in multiple channels (e.g. Spy700), channels are summed.

### Stage 2 — Boundary Alignment (Coarse + ICP)

Extracts sample boundary rings from both images, then finds the best rigid alignment (translation + rotation + isotropic scale) by maximising boundary overlap via phase correlation. The coarse alignment is refined with Iterative Closest Point (ICP) matching on boundary contour points.

The post-stain image is the reference frame throughout — only the pre-stain image is transformed. The post-stain is saved once at stage 1 (`01_padded_post`) and is never duplicated.

### Stage 3 — Interior Alignment (SIFT Feature Matching)

Refines the boundary+ICP alignment using SIFT feature matching on interior sample content. This corrects residual interior misalignment (~20–50 px) that boundary-only methods cannot resolve. See `docs/source/developers/concepts.rst` for why SIFT was chosen over ECC.

### Stage 4 — Diagnostics & Subtraction

Generates five diagnostic plots, fits a Moffat profile to the log-ratio distribution to estimate the background scale factor, and produces the scaled difference image.

**Always-produced outputs:**

| Plot | What it shows |
|------|---------------|
| `pre_post_heatmap` | 2-D density of pre vs post pixel brightness (256×256 grid, log colour scale) |
| `excess_heatmap` | Excess post-stain signal after diagonal noise cancellation, with all active scale lines overlaid |
| `pre_post_histograms` | Overlapping distributions of pre and post pixel values |
| `difference_histogram` | Distribution of `post − pre` split by pixel category |
| `ratio_histogram` | `post/pre` ratio in log space with Moffat noise fit and scale estimate |
| `difference_image` | Final `post − scale × pre` with asinh stretch |

**Scale methods (see `docs/source/users/scale_methods.rst`):**

- **Moffat fit** (always on) — fits a Moffat profile to the left wing of the log-ratio distribution mirrored across the peak. The fitted peak centre is the scale estimate.
- **Ratio percentile** (optional, set `scale_percentile`) — uses a user-chosen percentile of the log-ratio distribution. Produces an additional difference image alongside the Moffat one.
- **Manual override** (optional, set `manual_scale`) — uses an exact scale value. Produces an additional difference image.

When multiple scale methods are active, the `excess_heatmap` plot overlays all of them so you can compare side-by-side.

---

## Output Directory Structure

```
processed/
  {sample}/
    {dye}/
      tiff/                 # Intermediate and final images (float32 TIFF)
      fits/                 # Same images as FITS with metadata headers
      pipeline_checks/      # Diagnostic plots (heatmaps, histograms, ratio fit, difference image)
      difference_plots/     # (legacy — retained for old outputs)
```

### Checkpoint Filenames

Only non-default parameters appear in filenames. A run with all defaults produces:
```
01_padded_post.tiff
01_padded_pre.tiff
02_icp_aligned_pre.tiff
03_interior_aligned_pre.tiff
04_difference_difference.tiff
```

A run with `scale_percentile=99.1` and `manual_scale=1.42` additionally produces:
```
04_difference_difference_percentile_p99.1_sp99.1_msc1.42.tiff
04_difference_difference_manual_sp99.1_msc1.42.tiff
```

### Checking Raw Image Channels

Before processing, verify which RGB channels carry signal in your raw TIFFs:

```python
from exo2micro import survey_raw_channels
results = survey_raw_channels('raw')
```

Or click **Survey raw channels** in the GUI.

---

## Documentation

Full documentation lives in `docs/source/` and is organised into two tracks:

- **Users track** — installation, quickstart, GUI tour, scale method guidance, interpreting results, zoom/inspect workflow, troubleshooting.
- **Developers track** — conceptual overview, scripting API, full parameter reference, scale estimation internals, extending exo2micro, and autodoc-generated module reference.

Build the docs with:

```bash
cd docs
sphinx-build -b html source build/html
```

Or just read the `.rst` files directly — they're readable as plain text.

---

## Module Reference

| Module | Purpose |
|--------|---------|
| `exo2micro.pipeline` | `SampleDye` class — the main pipeline controller |
| `exo2micro.alignment` | Registration: boundary correlation, ICP, SIFT feature matching |
| `exo2micro.plotting` | Active visualization functions (diagnostics, zoom) |
| `exo2micro.parallel` | Batch processing (serial & parallel) |
| `exo2micro.gui` | Interactive Jupyter notebook interface |
| `exo2micro.utils` | Shared utilities (I/O, preprocessing, masking, channel detection) |
| `exo2micro.defaults` | Parameter registry and filename conventions |
| `exo2micro.legacy` | Deprecated / superseded functions, including the old LS/robust scaling code |

---

## Upgrading

**From 2.3.0 → 2.3.1.** One behaviour change for batch scripts: `run_batch` now defaults to `strict_dyes=True`, which raises `FileNotFoundError` if any requested `(sample, dye)` pair has no raw files. If you were relying on missing pairs failing one-by-one as task-level errors, either fix your sample/dye lists or pass `strict_dyes=False`. See `CHANGELOG.md` for the full list of 2.3.1 changes.

If you're upgrading from v2.2 or earlier, see `docs/source/migration.rst` for the full list of breaking changes. Key points:

- Pipeline is now 4 stages (no masking stage, no separate scaling stage).
- Final difference image is `04_difference_difference.tiff` (was mislabelled `05_` in v2.2).
- `scaling.py` has been removed — its contents live in `exo2micro.legacy` now.
- Eight dead parameters have been removed from `PARAMETER_REGISTRY`. Most users won't have used them.
- New parameters: `scale_percentile`, `manual_scale`.

---

## License

[Your license here]
