"""
utils.py
========
Shared utility functions used across the exo2micro sub-modules.

Includes:
  - Image I/O helpers (TIFF / FITS reading and writing with metadata)
  - Preprocessing (median subtraction, normalisation, padding, trimming)
  - Masking helpers (tissue masks, joint masks, fill holes)
  - Gaussian smoothing with NaN conservation
  - Intensity equalisation for image pairs
  - Display helpers (robust vmax, RGB overlays)
"""

import gc
import os
import sys
import glob
from typing import Optional
import numpy as np
import cv2
from PIL import Image
from scipy import ndimage
from scipy.ndimage import binary_fill_holes, binary_dilation, generate_binary_structure

# Allow very large TIFF files without PIL's decompression-bomb guard.
Image.MAX_IMAGE_PIXELS = None


# ==============================================================================
# FILE I/O
# ==============================================================================

def _is_tiff(filename):
    """Return True if ``filename`` ends with ``.tif`` or ``.tiff`` (case-insensitive).

    Used by :func:`classify_raw_files`, :func:`survey_raw_channels`, and
    :func:`diagnose_raw_layout` so all three apply the same rule. Add new
    extensions or tweak the rule here in one place.
    """
    lower = filename.lower()
    return lower.endswith('.tif') or lower.endswith('.tiff')


def survey_raw_channels(raw_dir='raw', crop_size=1000):
    """
    Survey all raw TIFF files to report which RGB channels carry signal.

    Reads a small centre crop from each file to avoid loading full images
    into memory.

    Parameters
    ----------
    raw_dir : str
        Root directory containing sample subdirectories (default 'raw').
    crop_size : int
        Side length of the centre crop to inspect (default 1000).

    Returns
    -------
    results : list of dict
        One entry per file with keys: 'path', 'size', 'mode', 'channels'.
        'channels' is a dict mapping channel name ('R', 'G', 'B' or
        'gray') to {'max': int, 'mean': float, 'nonzero': int}.

    Notes
    -----
    If ``raw_dir`` is missing, empty, or has TIFFs in the wrong place
    (e.g. directly in ``raw_dir`` rather than in per-sample
    subdirectories), this function prints a human-readable layout
    diagnosis via :func:`diagnose_raw_layout` and returns an empty list.
    """
    # Catch the common layout problems up front and explain them in
    # plain English. If the layout is fine, this is silent.
    layout = diagnose_raw_layout(raw_dir)
    if not layout['ok']:
        print(layout['message'])
        return []

    # Walk the tree case-insensitively for both .tif and .tiff. The
    # previous glob ``**/*.tif`` was both case-sensitive on Linux/Mac
    # and missed .tiff files entirely.
    files = []
    for root, _dirs, names in os.walk(raw_dir):
        for name in names:
            if _is_tiff(name):
                files.append(os.path.join(root, name))
    files = sorted(files)

    if not files:
        # diagnose_raw_layout already covers the no-files case, but
        # keep a fallback for the (rare) case where the layout looked
        # ok but the recursive walk found nothing.
        print(f"  No .tif/.tiff files found under {raw_dir}")
        return []

    results = []
    half = crop_size // 2

    for f in files:
        try:
            im = Image.open(f)
        except Exception as e:
            print(f"  !! Could not open {f}: {e}")
            continue

        w, h = im.size
        cx, cy = w // 2, h // 2
        r0 = max(cy - half, 0)
        c0 = max(cx - half, 0)
        r1 = min(cy + half, h)
        c1 = min(cx + half, w)
        crop = np.array(im.crop((c0, r0, c1, r1)))

        entry = {
            'path': f,
            'size': (w, h),
            'mode': im.mode,
            'channels': {},
        }

        if crop.ndim == 2:
            entry['channels']['gray'] = {
                'max': int(crop.max()),
                'mean': float(crop.mean()),
                'nonzero': int(np.count_nonzero(crop)),
            }
        else:
            names = ['R', 'G', 'B'] + [f'ch{i}' for i in range(3, crop.shape[2])]
            for ch in range(crop.shape[2]):
                d = crop[:, :, ch]
                entry['channels'][names[ch]] = {
                    'max': int(d.max()),
                    'mean': float(d.mean()),
                    'nonzero': int(np.count_nonzero(d)),
                }

        # Print summary
        active = [f"{name}(max={info['max']})"
                  for name, info in entry['channels'].items()
                  if info['max'] > 0]
        print(f"  {f}  —  {', '.join(active) if active else 'all zero'}")

        results.append(entry)

    return results

def _extract_signal_channel(path):
    """
    Load a TIFF and extract the fluorescence signal as a 2-D uint8 array.

    For RGB images, auto-detects which channel(s) carry signal by
    comparing per-channel means on a centre crop.

    - If exactly one channel has signal: extracts that channel.
    - If multiple channels have signal: sums them (clipped to uint8)
      and prints an informative message.
    - If the image is already grayscale: returns it directly.

    Parameters
    ----------
    path : str
        Path to the TIFF file.

    Returns
    -------
    image : ndarray (2-D, uint8)
        Extracted fluorescence signal.
    """
    im = Image.open(path)

    if im.mode in ('L', 'I', 'F'):
        # Already single-channel
        return np.array(im)

    arr = np.array(im)
    if arr.ndim == 2:
        return arr

    n_channels = arr.shape[2]
    channel_names = ['R', 'G', 'B'] + [f'ch{i}' for i in range(3, n_channels)]

    # Find channels with meaningful signal (mean > 0.5 in the channel)
    means = [float(arr[:, :, ch].mean()) for ch in range(n_channels)]
    active = [(ch, channel_names[ch], means[ch])
              for ch in range(n_channels) if means[ch] > 0.5]

    if len(active) == 0:
        # Fallback: take the channel with the highest mean
        best = int(np.argmax(means))
        print(f"    channel auto-detect: no strong signal, "
              f"using {channel_names[best]}  ({path})")
        return arr[:, :, best]

    if len(active) == 1:
        ch, name, mn = active[0]
        print(f"    channel auto-detect: {name}  (mean={mn:.1f})  ({os.path.basename(path)})")
        return arr[:, :, ch]

    # Multiple channels have signal — sum them
    names = [name for _, name, _ in active]
    print(f"    channel auto-detect: signal in {'+'.join(names)}, "
          f"summing  ({os.path.basename(path)})")
    combined = np.zeros(arr.shape[:2], dtype=np.float64)
    for ch, _, _ in active:
        combined += arr[:, :, ch].astype(np.float64)
    return np.clip(combined, 0, 255).astype(np.uint8)


def classify_raw_files(sample_dir):
    """
    Classify TIFF files in a sample directory by stain type and dye.

    Filename rules
    --------------
    A valid raw image filename must:

    1. End with ``.tif`` or ``.tiff`` (case-insensitive).
    2. Contain ``pre`` or ``post`` (case-insensitive) somewhere in the
       basename, marking it as a pre-stain or post-stain image.
    3. End with ``_<DyeName>.tif`` (or ``.tiff``), where ``<DyeName>``
       is the dye identifier and contains **no underscores**. The dye
       name is the substring between the last underscore and the
       extension.

    Examples of valid filenames::

        Sample001_PreStain_SybrGld.tif        -> pre,  dye=SybrGld
        Sample001_PostStain_SybrGld.tiff      -> post, dye=SybrGld
        my_2024_pre_run3_DAPI.tif             -> pre,  dye=DAPI
        whatever_post_Cy5.tiff                -> post, dye=Cy5

    Examples of *invalid* filenames (will be flagged in ``warnings``):

    - ``Sample001_PreStain_SybrGld_microbe.tif`` -- dye name contains
      an underscore. Would be parsed as dye ``microbe``. Rename
      ``SybrGld_microbe`` to ``SybrGldmicrobe`` or similar.
    - ``Sample001_pre_post_SybrGld.tif`` -- contains both ``pre`` and
      ``post``. Ambiguous, skipped.
    - ``Sample001_SybrGld.tif`` -- contains neither ``pre`` nor
      ``post``. Cannot be classified, skipped.

    This function is **non-raising**: it returns whatever it could
    parse plus a list of human-readable warnings about anything it
    couldn't. Callers that need to fail hard on missing or duplicate
    pairs (e.g. :func:`load_image_pair`) should check the returned
    structures themselves.

    Parameters
    ----------
    sample_dir : str
        Path to a single sample's directory.

    Returns
    -------
    pairs : dict
        Maps each detected dye name to a dict of candidate file
        paths::

            {
                'SybrGld': {'pre': ['/.../...PreStain_SybrGld.tif'],
                            'post': ['/.../...PostStain_SybrGld.tif']},
                'DAPI':    {'pre': ['/.../...Pre_DAPI.tiff'],
                            'post': ['/.../...Post_DAPI.tiff']},
            }

        Each list may have 0, 1, or many entries. Callers decide
        what to do about duplicates and missing sides.
    warnings : list of str
        Human-readable problem descriptions for individual files
        that couldn't be classified. One entry per problematic file.
    """
    if not os.path.isdir(sample_dir):
        return {}, [f"directory not found: {sample_dir}"]

    candidates = []
    for entry in os.listdir(sample_dir):
        if _is_tiff(entry):
            candidates.append(os.path.join(sample_dir, entry))

    pairs = {}
    warnings = []

    for path in sorted(candidates):
        basename = os.path.basename(path)
        # Strip extension (case-insensitive .tif or .tiff)
        if basename.lower().endswith('.tiff'):
            stem = basename[:-5]
        elif basename.lower().endswith('.tif'):
            stem = basename[:-4]
        else:
            continue

        lower_stem = stem.lower()
        has_pre = 'pre' in lower_stem
        has_post = 'post' in lower_stem

        if has_pre and has_post:
            warnings.append(
                f"AMBIGUOUS: {basename} contains both 'pre' and 'post' "
                f"in the filename -- cannot determine stain type. "
                f"Rename so only one of these substrings appears.")
            continue
        if not has_pre and not has_post:
            warnings.append(
                f"NO STAIN MARKER: {basename} contains neither 'pre' nor "
                f"'post' in the filename. Add 'Pre' or 'Post' to the "
                f"filename so the loader can classify it.")
            continue

        kind = 'pre' if has_pre else 'post'

        if '_' not in stem:
            warnings.append(
                f"NO UNDERSCORE: {basename} has no underscore before the "
                f"extension. Filenames must end with '_<DyeName>.tif' or "
                f"'_<DyeName>.tiff', where the dye name contains no "
                f"underscores.")
            continue

        dye = stem.rsplit('_', 1)[1]
        if not dye:
            warnings.append(
                f"EMPTY DYE: {basename} has nothing between the last "
                f"underscore and the extension. The filename must end "
                f"with '_<DyeName>.tif' or '_<DyeName>.tiff', where the "
                f"dye name (e.g. SybrGld, DAPI, Cy5) contains no "
                f"underscores.")
            continue

        pairs.setdefault(dye, {'pre': [], 'post': []})[kind].append(path)

    return pairs, warnings


def diagnose_raw_layout(raw_dir='raw'):
    """
    Diagnose the layout of a raw image directory and return a structured report.

    Catches the common "I don't see any images" failure modes before the
    pipeline gets a chance to fail confusingly downstream:

    1. ``raw_dir`` doesn't exist at all.
    2. ``raw_dir`` exists but is empty.
    3. ``raw_dir`` contains TIFF files directly (no per-sample folders).
       This is the most common mistake — users dump all their files in
       one place instead of separating by sample.
    4. ``raw_dir`` contains subdirectories but none of them contain any
       TIFF files.

    When the layout looks correct, returns ``ok=True`` and a short
    informational summary. When something is wrong, returns ``ok=False``
    and a multi-line ``message`` explaining what's wrong and how the
    directory should be structured.

    Parameters
    ----------
    raw_dir : str
        Path to the raw image directory (default ``'raw'``).

    Returns
    -------
    report : dict
        Keys:

        - ``ok`` (bool): True if the layout looks usable.
        - ``message`` (str): Human-readable multi-line message. Empty
          string when ``ok=True`` and there's nothing to report.
        - ``raw_dir`` (str): The directory that was inspected.
        - ``exists`` (bool): Whether ``raw_dir`` itself exists.
        - ``subdirs`` (list of str): Subdirectory names found (sorted).
        - ``loose_tiffs`` (list of str): TIFF filenames found directly
          in ``raw_dir`` (sorted). Non-empty implies the layout is
          wrong even if ``subdirs`` is also non-empty.
        - ``empty_subdirs`` (list of str): Subdirectory names that
          contain no TIFF files (sorted). Informational only.
    """
    report = {
        'ok': False,
        'message': '',
        'raw_dir': raw_dir,
        'exists': False,
        'subdirs': [],
        'loose_tiffs': [],
        'empty_subdirs': [],
    }

    # The "canonical layout" string used in several error messages.
    # Reuses the rules from classify_raw_files; if either changes,
    # update both together.
    layout_hint = (
        "Expected layout:\n"
        "    {raw_dir}/\n"
        "      Sample001/\n"
        "        Sample001_PreStain_SybrGld.tif\n"
        "        Sample001_PostStain_SybrGld.tif\n"
        "      Sample002/\n"
        "        Sample002_PreStain_DAPI.tif\n"
        "        Sample002_PostStain_DAPI.tif\n\n"
        "Filename rules:\n"
        "  1. Each sample must live in its OWN subdirectory under {raw_dir}.\n"
        "  2. Files end with .tif or .tiff (case-insensitive).\n"
        "  3. Filename contains 'pre' or 'post' (case-insensitive)\n"
        "     somewhere in the basename.\n"
        "  4. Filename ends with '_<DyeName>.tif' (or .tiff). The dye\n"
        "     name MUST NOT contain underscores. Use 'SybrGld', 'DAPI',\n"
        "     'Cy5', etc. — not 'SybrGld_microbe'.\n"
        "  5. Each sample directory contains exactly one pre-stain and\n"
        "     one post-stain file per dye."
    ).format(raw_dir=raw_dir)

    # Case 1: raw_dir doesn't exist
    if not os.path.exists(raw_dir):
        report['message'] = (
            f"Raw image directory not found: '{raw_dir}'\n"
            f"  -> exo2micro looked for this directory in your current "
            f"working directory and didn't find it.\n"
            f"  -> Either create it and put your sample folders inside, "
            f"or point the GUI / SampleDye / run_batch at the directory "
            f"where your raw images actually live (raw_dir='...').\n\n"
            f"{layout_hint}"
        )
        return report

    if not os.path.isdir(raw_dir):
        report['message'] = (
            f"'{raw_dir}' exists but is not a directory.\n"
            f"  -> exo2micro needs raw_dir to be a folder containing "
            f"per-sample subfolders.\n\n"
            f"{layout_hint}"
        )
        return report

    report['exists'] = True

    # Inventory the immediate children of raw_dir
    entries = [e for e in os.listdir(raw_dir) if not e.startswith('.')]
    loose_tiffs = sorted([e for e in entries if _is_tiff(e)])
    subdirs = sorted([
        e for e in entries
        if os.path.isdir(os.path.join(raw_dir, e))
    ])
    report['subdirs'] = subdirs
    report['loose_tiffs'] = loose_tiffs

    # Case 2: empty raw_dir
    if not entries:
        report['message'] = (
            f"Raw image directory is empty: '{raw_dir}'\n"
            f"  -> exo2micro needs this directory to contain one folder "
            f"per sample, with paired pre-stain and post-stain TIFFs "
            f"inside each folder.\n\n"
            f"{layout_hint}"
        )
        return report

    # Case 3: TIFFs are directly in raw_dir (no per-sample folders)
    if loose_tiffs and not subdirs:
        # Show up to 5 example filenames so the user can recognize their
        # files and not be confused about which directory is meant.
        examples = loose_tiffs[:5]
        more = (f"\n     ... and {len(loose_tiffs) - 5} more"
                if len(loose_tiffs) > 5 else "")
        report['message'] = (
            f"Found {len(loose_tiffs)} TIFF file(s) directly inside "
            f"'{raw_dir}', but no per-sample subfolders.\n"
            f"  -> exo2micro requires each sample to live in its own "
            f"subdirectory under '{raw_dir}'. The current layout puts "
            f"all images in one folder, which exo2micro doesn't know "
            f"how to interpret.\n"
            f"  -> Found these files:\n"
            f"     " + "\n     ".join(examples) + more + "\n"
            f"  -> Fix: create a folder per sample (e.g. '{raw_dir}/Sample001/'),\n"
            f"     and move each sample's pre/post files into its folder.\n\n"
            f"{layout_hint}"
        )
        return report

    # Mixed case: loose TIFFs AND subdirectories. Probably a mistake.
    if loose_tiffs and subdirs:
        examples = loose_tiffs[:5]
        more = (f" (and {len(loose_tiffs) - 5} more)"
                if len(loose_tiffs) > 5 else "")
        report['message'] = (
            f"Found {len(loose_tiffs)} TIFF file(s) directly inside "
            f"'{raw_dir}' (alongside {len(subdirs)} subdirectory(ies)).\n"
            f"  -> exo2micro only reads images from per-sample "
            f"subdirectories. The loose files at the top level will be "
            f"ignored:\n"
            f"     " + ", ".join(examples) + more + "\n"
            f"  -> If those files belong to one of the existing samples, "
            f"move them into the appropriate subfolder. If they're a new "
            f"sample, create a folder for them.\n\n"
            f"{layout_hint}"
        )
        # This is recoverable — the existing subdirs may still process —
        # so we report it as a warning, not a fatal error.
        report['ok'] = True
        # Check whether the subdirs themselves have any usable images
        # before claiming the layout is OK.
        # (fall through to the subdir-check block below)

    # Case 4: subdirectories exist but none contain TIFFs
    empty_subdirs = []
    nonempty_subdirs = []
    for sub in subdirs:
        sub_path = os.path.join(raw_dir, sub)
        try:
            sub_entries = os.listdir(sub_path)
        except OSError:
            empty_subdirs.append(sub)
            continue
        has_tiff = any(_is_tiff(e) for e in sub_entries)
        if has_tiff:
            nonempty_subdirs.append(sub)
        else:
            empty_subdirs.append(sub)
    report['empty_subdirs'] = empty_subdirs

    if subdirs and not nonempty_subdirs:
        report['message'] = (
            f"Found {len(subdirs)} sample subdirectory(ies) under "
            f"'{raw_dir}', but none of them contain any TIFF files.\n"
            f"  -> exo2micro found these folders:\n"
            f"     " + ", ".join(subdirs[:10])
            + ("..." if len(subdirs) > 10 else "") + "\n"
            f"  -> Each one should contain at least one pre-stain TIFF "
            f"and one post-stain TIFF.\n\n"
            f"{layout_hint}"
        )
        report['ok'] = False
        return report

    # All good (possibly with the mixed-loose-and-subdirs warning above)
    if not report['message']:
        # Pure-success path: build an informational summary, leave ok=True.
        summary_parts = [
            f"raw_dir='{raw_dir}': {len(nonempty_subdirs)} "
            f"sample folder(s) with TIFFs"
        ]
        if empty_subdirs:
            summary_parts.append(
                f", {len(empty_subdirs)} empty folder(s) ignored")
        report['message'] = ''.join(summary_parts)
    report['ok'] = True
    return report


def discover_tasks(samples, dyes, raw_dir='raw'):
    """
    Resolve a (samples, dyes) request into the actual list of tasks present on disk.

    Given a list of sample names and a list of dye names the user wants
    to process, walk each sample directory and return:

    - ``present``: list of ``(sample, dye)`` tuples that have both a
      pre-stain and a post-stain file. These are runnable.
    - ``skipped``: list of ``(sample, dye, reason)`` tuples that were
      requested but can't run, with a short human-readable reason.
    - ``warnings``: list of ``(sample, warning_str)`` tuples for
      filename problems encountered along the way (ambiguous, no
      underscore, etc. — same wording as :func:`classify_raw_files`
      returns).

    This is the canonical "what tasks should we actually run?" helper.
    Both the batch processor (:func:`exo2micro.parallel.build_task_list`)
    and the GUI use it so they share one source of truth.

    Parameters
    ----------
    samples : list of str
        Sample names requested by the user.
    dyes : list of str
        Dye names requested by the user.
    raw_dir : str
        Root directory containing per-sample subdirectories (default
        ``'raw'``).

    Returns
    -------
    result : dict
        Keys: ``present`` (list of (sample, dye)), ``skipped`` (list of
        (sample, dye, reason)), ``warnings`` (list of (sample,
        warning_str)), and ``layout_ok`` (bool — False if
        :func:`diagnose_raw_layout` flagged a fatal layout problem; in
        that case ``present`` and ``skipped`` will both be empty and
        a single layout warning is added to ``warnings``).
    """
    result = {
        'present': [],
        'skipped': [],
        'warnings': [],
        'layout_ok': True,
    }

    # Top-level layout check first. If raw_dir is missing or shaped
    # wrong, there's no point even trying to resolve individual pairs.
    layout = diagnose_raw_layout(raw_dir)
    if not layout['ok']:
        result['layout_ok'] = False
        result['warnings'].append(('(layout)', layout['message']))
        return result

    for sample in samples:
        sample_dir = os.path.join(raw_dir, sample)
        if not os.path.isdir(sample_dir):
            for dye in dyes:
                result['skipped'].append(
                    (sample, dye,
                     f"sample directory '{sample_dir}' does not exist"))
            continue

        pairs, file_warnings = classify_raw_files(sample_dir)
        for w in file_warnings:
            result['warnings'].append((sample, w))

        for dye in dyes:
            if dye not in pairs:
                available = sorted(pairs.keys())
                if available:
                    reason = (f"no '{dye}' files in this sample "
                              f"(dyes present: {', '.join(available)})")
                else:
                    reason = (f"no validly-named raw files in "
                              f"'{sample_dir}'")
                result['skipped'].append((sample, dye, reason))
                continue

            pre_n = len(pairs[dye]['pre'])
            post_n = len(pairs[dye]['post'])
            if pre_n == 0 or post_n == 0:
                missing_side = 'pre-stain' if pre_n == 0 else 'post-stain'
                reason = (f"incomplete pair — {missing_side} file is "
                          f"missing (found {pre_n} pre, {post_n} post)")
                result['skipped'].append((sample, dye, reason))
                continue

            if pre_n > 1 or post_n > 1:
                reason = (f"duplicate files — found {pre_n} pre and "
                          f"{post_n} post for this dye, expected 1+1")
                result['skipped'].append((sample, dye, reason))
                continue

            result['present'].append((sample, dye))

    return result


def estimate_pipeline_output_size(sample_dye_pairs, raw_dir='raw',
                                   pad=2000, save_all_intermediates=False,
                                   n_scale_methods=1,
                                   checkpoint_format='tiff'):
    """
    Estimate the on-disk footprint of a pipeline run.

    Returns a best-effort estimate of how much disk space the pipeline
    will consume if run on the given (sample, dye) combinations with
    the given parameters. Used by the GUI to pre-warn users when the
    estimate would exceed available disk space.

    The estimate is based on the raw TIFF dimensions: exo2micro pads
    each raw image by ``pad`` pixels on every side, converts to
    float32 (4 bytes per pixel), and saves intermediates at each
    pipeline stage. Approximate breakdown per (sample, dye):

    - Stage 1: padded post + padded pre (2 files, float32)
    - Stage 2: ICP-aligned pre (1 file); +coarse-aligned pre if
      ``save_all_intermediates=True``
    - Stage 3: interior-aligned pre (1 file)
    - Stage 4: difference image (``n_scale_methods`` files, one per
      active scale method: Moffat-only = 1, Moffat+percentile = 2,
      Moffat+manual = 2, all three = 3)

    Each intermediate can be written as TIFF, FITS, or both depending
    on ``checkpoint_format``. TIFF-only and FITS-only runs use roughly
    half the disk space of ``'both'``. Diagnostic PNG plots add a
    small fixed overhead (~10 MB per (sample, dye) regardless).

    Parameters
    ----------
    sample_dye_pairs : list of tuple
        List of ``(sample, dye)`` combinations to estimate.
    raw_dir : str
        Root raw image directory (default ``'raw'``).
    pad : int
        Padding value (default ``2000``).
    save_all_intermediates : bool
        If True, adds the stage-2 coarse intermediate to the estimate.
    n_scale_methods : int
        How many difference images stage 4 will produce (1-3).
    checkpoint_format : {'tiff', 'fits', 'both'}
        Which file format(s) each checkpoint gets written as. TIFF
        and FITS are roughly the same size on disk; ``'both'`` doubles
        the per-file footprint.

    Returns
    -------
    estimate : dict
        ``{'bytes_per_task': [list], 'total_bytes': int,
           'n_tasks': int, 'n_resolvable': int, 'warnings': [list]}``
    """
    PNG_OVERHEAD_BYTES = 10 * 1024 * 1024  # ~10 MB of diagnostic PNGs per task

    n_stage4_tiffs = max(1, n_scale_methods)

    # Total full-res image files produced per task (in one format):
    #   stage 1: post + pre                          = 2
    #   stage 2: icp_aligned_pre                     = 1 (+ 1 if intermediates)
    #   stage 3: interior_aligned_pre                = 1
    #   stage 4: difference (per scale method)       = n_stage4_tiffs
    n_fullres_single_format = 2 + 1 + 1 + n_stage4_tiffs
    if save_all_intermediates:
        n_fullres_single_format += 1

    # If the user is saving both formats, each of those files is
    # written twice (TIFF and FITS copies). Otherwise it's written
    # once in the chosen format.
    format_multiplier = 2 if checkpoint_format == 'both' else 1
    n_fullres = n_fullres_single_format * format_multiplier

    per_task = []
    warnings = []
    for sample, dye in sample_dye_pairs:
        sample_dir = os.path.join(raw_dir, sample)
        pairs, _ = classify_raw_files(sample_dir)

        if dye not in pairs or not pairs[dye]['pre'] or not pairs[dye]['post']:
            warnings.append(
                f"{sample} / {dye}: cannot resolve raw files for estimate")
            per_task.append(0)
            continue

        # Read raw file size of the post-stain file and infer full
        # dimensions. We could open it with tifffile to get shape,
        # but that's slow on networked drives; the raw file size is
        # close enough since uncompressed TIFFs dominate here.
        raw_path = pairs[dye]['post'][0]
        try:
            raw_bytes = os.path.getsize(raw_path)
        except OSError as e:
            warnings.append(f"{sample} / {dye}: cannot stat {raw_path}: {e}")
            per_task.append(0)
            continue

        # Raw TIFF is typically uint8 × 3 channels = 3 bytes/px.
        # Full-res float32 single channel = 4 bytes/px.
        # So per-pixel ratio of output to raw input = 4/3.
        # Then multiply by the padding inflation:
        #   input area = H * W
        #   padded area ~ (H + 2*pad) * (W + 2*pad)
        # For H, W in the ~25000 px range and pad=2000, this is
        # roughly 1.18×. We use a fixed 1.2× inflation since we
        # don't know exact dims without opening the file.
        PADDING_INFLATION = 1.2
        CHANNEL_RATIO = 4.0 / 3.0

        output_bytes_per_image = int(
            raw_bytes * CHANNEL_RATIO * PADDING_INFLATION)
        task_bytes = n_fullres * output_bytes_per_image + PNG_OVERHEAD_BYTES
        per_task.append(task_bytes)

    total = sum(per_task)
    n_resolvable = sum(1 for b in per_task if b > 0)

    return {
        'bytes_per_task': per_task,
        'total_bytes': total,
        'n_tasks': len(sample_dye_pairs),
        'n_resolvable': n_resolvable,
        'warnings': warnings,
    }


def get_free_disk_space(path):
    """Return free disk space at ``path`` in bytes."""
    try:
        stat = os.statvfs(path)
        return stat.f_bavail * stat.f_frsize
    except (OSError, AttributeError):
        # Fallback for Windows or if path doesn't exist
        try:
            import shutil
            return shutil.disk_usage(path).free
        except Exception:
            return None


def format_bytes(n):
    """Format a byte count as a human-readable string."""
    if n is None:
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f'{n:.1f} {unit}' if unit != 'B' else f'{int(n)} {unit}'
        n /= 1024
    return f'{n:.1f} PB'


# ──────────────────────────────────────────────────────────────────────────
# Persistent run log
# ──────────────────────────────────────────────────────────────────────────
#
# The GUI's ipywidgets Output widget is ephemeral — its content lives
# only in the Python kernel and disappears when the kernel restarts or
# the notebook is closed. For users who want to reopen a notebook later
# and see what a previous run produced, we also append every line to a
# persistent log file in the output directory.

RUN_LOG_FILENAME = '.exo2micro_run_log.txt'


def get_run_log_path(output_dir):
    """Return the path to the persistent run log file.

    The log lives at ``{output_dir}/.exo2micro_run_log.txt``. The
    leading dot keeps it out of casual file listings since it's
    mostly for recovery/debugging, not regular browsing.
    """
    return os.path.join(output_dir, RUN_LOG_FILENAME)


def append_to_run_log(output_dir, message):
    """Append a line to the persistent run log.

    Failures (e.g. permission errors, missing directory) are
    silently ignored — the log is a best-effort persistence aid,
    not a critical path.
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        path = get_run_log_path(output_dir)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(message)
            if not message.endswith('\n'):
                f.write('\n')
    except Exception:
        pass


def read_run_log_tail(output_dir, max_lines=500):
    """Read the tail of the persistent run log.

    Parameters
    ----------
    output_dir : str
        Directory containing ``.exo2micro_run_log.txt``.
    max_lines : int
        Maximum number of lines to return (most recent). Reading
        the whole file into memory is fine for typical log sizes
        (~megabytes), but we cap it defensively.

    Returns
    -------
    text : str or None
        The last ``max_lines`` lines of the file, joined into a
        single string, or None if the file doesn't exist.
    """
    path = get_run_log_path(output_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return ''.join(lines)
    except Exception as e:
        return f'(error reading log: {e})'


def clear_run_log(output_dir):
    """Delete the persistent run log file, if it exists."""
    path = get_run_log_path(output_dir)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


class TeeStdout:
    """File-like object that writes to both stdout and a log file.

    Used as a context manager during pipeline runs to capture every
    line of pipeline output (including text from inside library
    functions that use ``print()`` directly) into the persistent
    run log, without disturbing the normal stdout flow that the
    GUI's :class:`widgets.Output` context manager captures.

    Usage::

        with TeeStdout(log_path):
            with widget_output:
                run.run()  # all prints go to widget AND log file

    Failures writing to the file are silently swallowed; the
    underlying stdout writes always succeed.
    """

    def __init__(self, log_path):
        self.log_path = log_path
        self._original_stdout = None
        self._fh = None

    def __enter__(self):
        self._original_stdout = sys.stdout
        try:
            os.makedirs(os.path.dirname(self.log_path) or '.', exist_ok=True)
            self._fh = open(self.log_path, 'a', encoding='utf-8',
                            buffering=1)  # line-buffered
        except Exception:
            self._fh = None
        sys.stdout = self
        return self

    def __exit__(self, *args):
        sys.stdout = self._original_stdout
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def write(self, data):
        # Always write to the original stdout first so widget capture
        # works exactly as before.
        try:
            self._original_stdout.write(data)
        except Exception:
            pass
        # Best-effort write to the log file.
        if self._fh is not None:
            try:
                self._fh.write(data)
            except Exception:
                pass

    def flush(self):
        try:
            self._original_stdout.flush()
        except Exception:
            pass
        if self._fh is not None:
            try:
                self._fh.flush()
            except Exception:
                pass


def load_image_pair(sample, dye, raw_dir='raw'):
    """
    Load a pre-stain and post-stain image pair for a given sample and dye.

    Automatically detects which RGB channel carries the fluorescence
    signal and extracts it at full 8-bit precision, rather than using
    :meth:`PIL.Image.convert` which loses ~41% of the dynamic range.

    Filename convention
    -------------------
    Each sample directory must contain exactly one pre-stain file and
    exactly one post-stain file per dye, named so that:

    1. The filename ends with ``.tif`` or ``.tiff``
       (case-insensitive).
    2. The basename contains ``pre`` or ``post`` (case-insensitive)
       to mark the stain type.
    3. The basename ends with ``_<dye>.<ext>``, where ``<dye>``
       matches the ``dye`` argument and contains no underscores.

    See :func:`classify_raw_files` for full details and examples.

    Behaviour on problems
    ---------------------
    This function is strict: it raises rather than returning
    placeholder values when anything goes wrong. The exception
    message is multi-line and tells the user exactly what to fix.

    - **Missing sample directory** -> :class:`FileNotFoundError`
    - **No file matches the requested dye** ->
      :class:`FileNotFoundError`
    - **Only one side of the pair found** ->
      :class:`FileNotFoundError`
    - **Multiple pre-stain or post-stain files for the same dye** ->
      :class:`ValueError`

    When other dyes in the same directory are misnamed (ambiguous,
    no underscore, etc.), warnings about them are printed but
    do not block loading the requested dye.

    Parameters
    ----------
    sample : str
        Sample name, e.g. ``'CD070'``. Must match the name of a
        subdirectory under ``raw_dir``.
    dye : str
        Dye name, e.g. ``'SybrGld'`` or ``'DAPI'``. Must match the
        substring after the last underscore in the raw filenames.
    raw_dir : str
        Base directory containing sample subdirectories (default
        ``'raw'``).

    Returns
    -------
    post_im : ndarray
        Post-stain image as a 2-D numpy array.
    pre_im : ndarray
        Pre-stain image as a 2-D numpy array.
    post_path : str
        Path to the post-stain file.
    pre_path : str
        Path to the pre-stain file.

    Raises
    ------
    FileNotFoundError
        If the sample directory is missing, the requested dye has
        no matching files, or only one side of the pair exists.
    ValueError
        If the requested dye matches more than one pre-stain or
        post-stain file in the directory.
    """
    sample_dir = os.path.join(raw_dir, sample)
    if not os.path.isdir(sample_dir):
        raise FileNotFoundError(
            f"Sample directory not found: {sample_dir}\n"
            f"  -> expected '{sample}' to be a subdirectory of '{raw_dir}'")

    pairs, warnings = classify_raw_files(sample_dir)

    # Surface any per-file warnings (these affect other files in the
    # same directory but don't necessarily block the requested dye).
    if warnings:
        print(f"  ({len(warnings)} filename problem(s) in {sample_dir}:)")
        for w in warnings:
            print(f"    !! {w}")

    if dye not in pairs:
        available = sorted(pairs.keys())
        msg = (f"No raw files matching dye '{dye}' in {sample_dir}\n"
               f"  -> looked for files containing 'pre' or 'post' and "
               f"ending with '_{dye}.tif' or '_{dye}.tiff'")
        if available:
            msg += f"\n  -> dyes detected in this directory: {available}"
        else:
            msg += f"\n  -> no validly-named raw files in this directory"
        if '_' in dye:
            # Most common typo: user passed 'SybrGld_microbe' as the dye
            # name when the actual file is named with just 'SybrGld' as
            # the dye and 'microbe' is a leftover descriptor. Dye names
            # must not contain underscores.
            msg += (f"\n  -> note: dye names must not contain underscores. "
                    f"The dye is the substring AFTER the last underscore "
                    f"in the filename. If your files are named like "
                    f"'..._{dye}.tif', the dye here would be "
                    f"'{dye.rsplit('_', 1)[1]}'. Either rename the files "
                    f"or request the dye as '{dye.rsplit('_', 1)[1]}'.")
        raise FileNotFoundError(msg)

    pre_files = pairs[dye]['pre']
    post_files = pairs[dye]['post']

    if not pre_files or not post_files:
        msg = f"Incomplete pair for {sample} / {dye} in {sample_dir}\n"
        if not pre_files:
            msg += (f"  -> no file containing 'pre' ends with "
                    f"'_{dye}.tif' or '_{dye}.tiff'\n")
        else:
            msg += f"  -> pre-stain found: {os.path.basename(pre_files[0])}\n"
        if not post_files:
            msg += (f"  -> no file containing 'post' ends with "
                    f"'_{dye}.tif' or '_{dye}.tiff'\n")
        else:
            msg += f"  -> post-stain found: {os.path.basename(post_files[0])}\n"
        msg += (f"  -> rename or add the missing file so the directory "
                f"has exactly one pre-stain and one post-stain image "
                f"for this dye")
        raise FileNotFoundError(msg)

    if len(pre_files) > 1 or len(post_files) > 1:
        msg = (f"Duplicate pair for {sample} / {dye} in {sample_dir}\n"
               f"  -> expected exactly one pre-stain and one post-stain "
               f"file for this dye, but found:\n")
        if len(pre_files) > 1:
            msg += f"  -> pre-stain candidates ({len(pre_files)}):\n"
            for p in pre_files:
                msg += f"     {os.path.basename(p)}\n"
        if len(post_files) > 1:
            msg += f"  -> post-stain candidates ({len(post_files)}):\n"
            for p in post_files:
                msg += f"     {os.path.basename(p)}\n"
        msg += (f"  -> rename or remove the extras so each sample "
                f"directory contains exactly one pre-stain and one "
                f"post-stain image per dye")
        raise ValueError(msg)

    pre_path = pre_files[0]
    post_path = post_files[0]

    post_im = _extract_signal_channel(post_path)
    pre_im = _extract_signal_channel(pre_path)
    print(f"  Loaded  post-stain : {post_path}  shape={post_im.shape}  "
          f"range=[{post_im.min()}, {post_im.max()}]")
    print(f"  Loaded  pre-stain  : {pre_path}   shape={pre_im.shape}  "
          f"range=[{pre_im.min()}, {pre_im.max()}]")

    return post_im, pre_im, post_path, pre_path


def save_checkpoint(image, filepath, sample='', dye='', stage='',
                    params=None, extra_headers=None):
    """
    Save an intermediate image as both TIFF and FITS, with metadata.

    The TIFF is saved in the 'tiff/' subdirectory and the FITS in the 'fits/'
    subdirectory of the same parent.

    Parameters
    ----------
    image : ndarray
        2D image array to save.
    filepath : str
        Base filepath WITHOUT extension, e.g.
        'processed/CD070/SybrGld_microbe/01_padded_post'.
        The function appends .tiff and .fits and places them in the
        appropriate subdirectories.
    sample : str
        Sample name for FITS header.
    dye : str
        Dye name for FITS header.
    stage : str
        Pipeline stage name for FITS header.
    params : dict or None
        Non-default parameters to record in FITS header.
    extra_headers : dict or None
        Additional FITS header keywords (e.g., warp matrix elements).
    """
    from astropy.io import fits
    from datetime import datetime

    # Determine base directory and filename
    parent = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    # Construct tiff and fits directories
    # filepath is expected to be like: .../sample/dye/images/01_padded_post_suffix
    # We need to route to .../sample/dye/tiff/ and .../sample/dye/fits/
    # Go up from images/ to the sample/dye level
    sample_dye_dir = os.path.dirname(parent) if os.path.basename(parent) == 'images' else parent
    tiff_dir = os.path.join(sample_dye_dir, 'tiff')
    fits_dir = os.path.join(sample_dye_dir, 'fits')
    os.makedirs(tiff_dir, exist_ok=True)
    os.makedirs(fits_dir, exist_ok=True)

    tiff_path = os.path.join(tiff_dir, basename + '.tiff')
    fits_path = os.path.join(fits_dir, basename + '.fits')

    # Save TIFF — preserve full precision
    if image.dtype == np.float32 or image.dtype == np.float64:
        # Use PIL for float images via intermediate conversion
        # For full float precision, save as 32-bit TIFF
        import tifffile
        tifffile.imwrite(tiff_path, image.astype(np.float32))
    else:
        tifffile_save(image, tiff_path)

    # Save FITS with metadata
    hdu = fits.PrimaryHDU(image.astype(np.float32))
    header = hdu.header
    header['SAMPLE'] = (sample, 'Sample name')
    header['DYE'] = (dye, 'Dye/channel name')
    header['STAGE'] = (stage, 'Pipeline stage')
    header['CREATED'] = (datetime.now().isoformat(), 'File creation timestamp')

    if params:
        for key, value in params.items():
            # FITS keywords are max 8 chars; use abbreviation if available
            from .defaults import ABBREVIATIONS
            fits_key = ABBREVIATIONS.get(key, key[:8]).upper()
            if value is None:
                header[fits_key] = ('None', key)
            elif isinstance(value, bool):
                header[fits_key] = (value, key)
            else:
                header[fits_key] = (value, key)

    if extra_headers:
        for key, value in extra_headers.items():
            header[key[:8].upper()] = value

    hdu.writeto(fits_path, overwrite=True)
    print(f"  Saved checkpoint: {tiff_path}")
    print(f"  Saved checkpoint: {fits_path}")


def tifffile_save(image, path):
    """Save image as TIFF using tifffile for full-precision support."""
    import tifffile
    tifffile.imwrite(path, image.astype(np.float32))


def load_checkpoint(filepath):
    """
    Load a checkpoint image from TIFF.

    Parameters
    ----------
    filepath : str
        Base filepath WITHOUT extension (same as passed to save_checkpoint).

    Returns
    -------
    image : ndarray or None
        The loaded image, or None if not found.
    """
    parent = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    sample_dye_dir = os.path.dirname(parent) if os.path.basename(parent) == 'images' else parent
    tiff_dir = os.path.join(sample_dye_dir, 'tiff')
    tiff_path = os.path.join(tiff_dir, basename + '.tiff')

    if os.path.exists(tiff_path):
        import tifffile
        image = tifffile.imread(tiff_path)
        print(f"  Loaded checkpoint: {tiff_path}  shape={image.shape}")
        return image
    return None


def checkpoint_exists(filepath):
    """
    Check whether a checkpoint file exists.

    Parameters
    ----------
    filepath : str
        Base filepath WITHOUT extension.

    Returns
    -------
    bool
    """
    parent = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    sample_dye_dir = os.path.dirname(parent) if os.path.basename(parent) == 'images' else parent
    tiff_dir = os.path.join(sample_dye_dir, 'tiff')
    tiff_path = os.path.join(tiff_dir, basename + '.tiff')
    return os.path.exists(tiff_path)


def tiff_to_fits(tiff_file, return_data=False):
    """
    Convert a three-channel RGB TIFF file to a FITS file.

    Each colour channel is stored as a named image extension
    (RED1, GREEN2, BLUE3).

    Parameters
    ----------
    tiff_file : str
        Path to the source TIFF file.
    return_data : bool
        If True, also return the raw TIFF array (default False).

    Returns
    -------
    fits_filename : str
        Path to the generated FITS file.
    tiff_data : ndarray
        Raw uint8 array of shape (H, W, 3); only if return_data=True.
    """
    from astropy.io import fits

    tiff_image = Image.open(tiff_file)
    tiff_data = np.array(tiff_image)

    red_channel = tiff_data[:, :, 0]
    green_channel = tiff_data[:, :, 1]
    blue_channel = tiff_data[:, :, 2]

    hdu_list = fits.HDUList([
        fits.PrimaryHDU(),
        fits.ImageHDU(red_channel, name='RED1'),
        fits.ImageHDU(green_channel, name='GREEN2'),
        fits.ImageHDU(blue_channel, name='BLUE3'),
    ])

    fits_filename = os.path.splitext(tiff_file)[0] + ".fits"
    hdu_list.writeto(fits_filename, overwrite=True)
    print(f"tiff_to_fits: wrote {fits_filename}")

    if return_data:
        return fits_filename, tiff_data
    return fits_filename


# ==============================================================================
# IMAGE PREPROCESSING
# ==============================================================================

def subtract_median(image, region=(0, 5000, 0, 5000)):
    """
    Subtract the median background level estimated from a rectangular region.

    Parameters
    ----------
    image : ndarray
        2D image array.
    region : tuple of 4 ints
        (row_min, row_max, col_min, col_max) region for background estimation.

    Returns
    -------
    ndarray
        Background-subtracted image.
    """
    r0, r1, c0, c1 = region
    # Clamp region to image bounds
    r1 = min(r1, image.shape[0])
    c1 = min(c1, image.shape[1])
    bgnd_level = np.nanmedian(image[r0:r1, c0:c1])
    print(f"subtract_median: background level = {bgnd_level:.4f}")
    return image - bgnd_level


def normalize_image(image, norm_percentile=None):
    """
    Normalize an image to its maximum or to a specified percentile value.

    Parameters
    ----------
    image : ndarray
        2D image array.
    norm_percentile : float or None
        If None, normalize by the image maximum.  Otherwise normalize by
        this percentile value.

    Returns
    -------
    ndarray
        Normalized image.
    """
    if norm_percentile is None:
        return image / np.nanmax(image)
    return image / np.nanpercentile(image, norm_percentile)


def pad_images(post_im, pre_im, pad=50):
    """
    Pad two images with zeros onto a common canvas plus a border.

    The extra border gives the registration algorithm room to shift the
    pre-stain image without it falling off the canvas edge.

    Parameters
    ----------
    post_im : ndarray
        Post-stain image (2D).
    pre_im : ndarray
        Pre-stain image (2D).
    pad : int
        Number of zero-padding pixels on each side (default 50).

    Returns
    -------
    post_im_pad : ndarray
        Zero-padded post-stain image.
    pre_im_pad : ndarray
        Zero-padded pre-stain image on the same canvas.
    """
    max_rows = max(post_im.shape[0], pre_im.shape[0])
    max_cols = max(post_im.shape[1], pre_im.shape[1])

    canvas_shape = (max_rows + pad * 2, max_cols + pad * 2)
    post_im_pad = np.zeros(canvas_shape, dtype=post_im.dtype)
    pre_im_pad = np.zeros(canvas_shape, dtype=pre_im.dtype)

    post_im_pad[pad:post_im.shape[0] + pad,
                pad:post_im.shape[1] + pad] = post_im
    pre_im_pad[pad:pre_im.shape[0] + pad,
               pad:pre_im.shape[1] + pad] = pre_im

    return post_im_pad, pre_im_pad


def trim_to_signal(post_im, pre_im, threshold=0):
    """
    Trim both images to the bounding box of their combined nonzero signal.

    Discards large empty margins before padding and registration.  This is
    critical when images have significant zero-padded borders, because those
    empty regions confuse phase correlation and ECC.

    Parameters
    ----------
    post_im : ndarray
        Post-stain image (2D).
    pre_im : ndarray
        Pre-stain image (2D).
    threshold : float
        Pixel values <= this are treated as empty background (default 0).

    Returns
    -------
    post_trimmed : ndarray
    pre_trimmed : ndarray
    bbox : tuple
        (row_min, row_max, col_min, col_max) bounding box applied.
    """
    combined_rows = np.any(post_im > threshold, axis=1) | \
                    np.any(pre_im > threshold, axis=1)
    combined_cols = np.any(post_im > threshold, axis=0) | \
                    np.any(pre_im > threshold, axis=0)

    if not np.any(combined_rows) or not np.any(combined_cols):
        print("trim_to_signal: no signal found — returning originals")
        return post_im, pre_im, (0, post_im.shape[0], 0, post_im.shape[1])

    row_min = np.argmax(combined_rows)
    row_max = len(combined_rows) - np.argmax(combined_rows[::-1])
    col_min = np.argmax(combined_cols)
    col_max = len(combined_cols) - np.argmax(combined_cols[::-1])

    bbox = (row_min, row_max, col_min, col_max)
    print(f"trim_to_signal: rows {row_min}:{row_max}, cols {col_min}:{col_max}")

    return (post_im[row_min:row_max, col_min:col_max],
            pre_im[row_min:row_max, col_min:col_max],
            bbox)


# ==============================================================================
# GAUSSIAN SMOOTHING
# ==============================================================================

def filter_nan_gaussian_conserving(arr, sigma):
    """
    Apply a Gaussian smooth to an array that may contain NaNs, conserving
    total intensity.  NaN positions remain NaN in the output.

    Parameters
    ----------
    arr : ndarray
        Input 2D array, may contain NaNs.
    sigma : float
        Gaussian smoothing sigma in pixels.

    Returns
    -------
    ndarray
        Smoothed array with NaNs preserved.
    """
    nan_msk = np.isnan(arr)

    loss = np.zeros(arr.shape)
    loss[nan_msk] = 1
    loss = ndimage.gaussian_filter(loss, sigma=sigma, mode='constant', cval=1)

    gauss = arr.astype(float)
    gauss[nan_msk] = 0
    gauss = ndimage.gaussian_filter(gauss, sigma=sigma, mode='constant', cval=0)
    gauss[nan_msk] = np.nan

    gauss += loss * arr
    return gauss


# ==============================================================================
# INTENSITY EQUALISATION
# ==============================================================================

def equalize_pair(post, pre):
    """
    Intensity-equalize a pair of images for registration.

    Histogram-matches the pre-stain image's intensity distribution to the
    post-stain's, then jointly normalises both to [0, 1] using the shared
    99th percentile of post-stain nonzero pixels.

    Parameters
    ----------
    post : ndarray
        Post-stain image as float32 (2D).
    pre : ndarray
        Pre-stain image as float32 (2D).

    Returns
    -------
    post_eq : ndarray
        Post-stain normalised to [0, 1].
    pre_eq : ndarray
        Pre-stain histogram-matched and normalised.
    """
    post_px = post[post > 0].ravel()
    pre_px = pre[pre > 0].ravel()

    if len(post_px) == 0 or len(pre_px) == 0:
        post_eq = post / (post.max() + 1e-8)
        pre_eq = pre / (pre.max() + 1e-8)
        return post_eq, pre_eq

    n_bins = 256
    post_hist, post_edges = np.histogram(post_px, bins=n_bins)
    pre_hist, pre_edges = np.histogram(pre_px, bins=n_bins)

    post_cdf = np.cumsum(post_hist).astype(np.float64)
    pre_cdf = np.cumsum(pre_hist).astype(np.float64)
    post_cdf /= post_cdf[-1]
    pre_cdf /= pre_cdf[-1]

    post_bin_centres = (post_edges[:-1] + post_edges[1:]) / 2.0

    pre_bin_idx = np.searchsorted(pre_edges[1:], pre.ravel(), side='left')
    pre_bin_idx = np.clip(pre_bin_idx, 0, n_bins - 1)
    pre_cdf_vals = pre_cdf[pre_bin_idx]

    post_matched_idx = np.searchsorted(post_cdf, pre_cdf_vals, side='left')
    post_matched_idx = np.clip(post_matched_idx, 0, n_bins - 1)
    pre_matched = post_bin_centres[post_matched_idx].reshape(pre.shape).astype(np.float32)
    pre_matched[pre == 0] = 0.0

    post_99 = np.percentile(post_px, 99)
    if post_99 < 1e-8:
        post_99 = 1.0

    post_eq = np.clip(post / post_99, 0.0, 1.0)
    pre_eq = np.clip(pre_matched / post_99, 0.0, 1.0)

    return post_eq, pre_eq


# ==============================================================================
# MASKING
# ==============================================================================

def build_tissue_mask(post_im, pre_im, signal_threshold=0, dilation_iters=50):
    """
    Build a joint tissue mask from post-stain and pre-stain images.

    Each image is independently thresholded, dilated, and hole-filled,
    then the two masks are intersected.

    Parameters
    ----------
    post_im : ndarray
        Post-stain image (2D).
    pre_im : ndarray
        Pre-stain aligned image (2D).
    signal_threshold : float
        Pixels <= this are excluded (default 0).
    dilation_iters : int
        Morphological dilation iterations (default 50).

    Returns
    -------
    joint_mask : ndarray of bool
        Intersection of post and pre tissue masks.
    """
    struct = generate_binary_structure(2, 1)

    post_mask = binary_fill_holes(binary_dilation(
        post_im > signal_threshold, structure=struct,
        iterations=dilation_iters))
    pre_mask = binary_fill_holes(binary_dilation(
        pre_im > signal_threshold, structure=struct,
        iterations=dilation_iters))
    joint_mask = post_mask & pre_mask

    joint_fraction = np.mean(joint_mask)
    print(f"  Joint mask coverage: {joint_fraction:.3f}  "
          f"({'OK' if joint_fraction > 0.05 else '!! LOW'})")

    return joint_mask


def build_clean_tissue_mask(post, pre):
    """
    Build a clean tissue mask using binary_fill_holes only (no dilation).

    This is the mask used for residual histograms and as the base for the
    signal-only fitting mask.

    Parameters
    ----------
    post : ndarray
        Post-stain image (float).
    pre : ndarray
        Pre-stain aligned image (float).

    Returns
    -------
    tissue_mask : ndarray of bool
    """
    return binary_fill_holes(post > 0) & binary_fill_holes(pre > 0)


# ==============================================================================
# DISPLAY HELPERS
# ==============================================================================

def robust_vmax(im, n_mad=5):
    """
    Compute a display vmax robust to bright outliers.

    Uses median + n_mad * MAD over nonzero pixels.

    Parameters
    ----------
    im : ndarray
        2D image array.
    n_mad : float
        Number of median absolute deviations above the median (default 5).

    Returns
    -------
    float
        Robust display maximum.
    """
    px = im[im > 0]
    if len(px) == 0:
        return 1.0
    med = np.median(px)
    mad = np.median(np.abs(px - med))
    return med + n_mad * mad


def make_rgb_overlay(post, pre, post_edges=None, pre_edges=None):
    """
    Build a 3-channel RGB overlay for alignment assessment.

    Post-stain in Red, pre-stain in Green.  Overlap appears yellow.
    Optional boundary edges drawn in cyan (post) and magenta (pre).

    Parameters
    ----------
    post : ndarray
        Post-stain image (float32, 2D).
    pre : ndarray
        Pre-stain image (float32, 2D).
    post_edges : ndarray or None
        Post-stain boundary ring.
    pre_edges : ndarray or None
        Pre-stain boundary ring.

    Returns
    -------
    rgb : ndarray
        uint8 array of shape (H, W, 3).
    """
    def _to_uint8(im):
        px = im[im > 0]
        if len(px) == 0:
            return np.zeros_like(im, dtype=np.uint8)
        vmax = np.percentile(px, 99)
        if vmax < 1e-8:
            return np.zeros_like(im, dtype=np.uint8)
        return np.clip(im / vmax * 255, 0, 255).astype(np.uint8)

    r = _to_uint8(post)
    g = _to_uint8(pre)
    b = np.zeros_like(r)
    rgb = np.stack([r, g, b], axis=-1)

    if post_edges is not None:
        rgb[post_edges > 0] = [0, 255, 255]    # cyan
    if pre_edges is not None:
        rgb[pre_edges > 0] = [255, 0, 255]     # magenta

    return rgb


def estimate_gauss_sigma(im, down_scale, sparse_threshold=0.1,
                         sparse_sigma=5, dense_sigma=0):
    """
    Estimate an appropriate Gaussian pre-smoothing sigma for ECC registration
    based on image density.

    Parameters
    ----------
    im : ndarray
        Full-resolution image (2D).
    down_scale : float
        Downsample factor that will be applied before ECC.
    sparse_threshold : float
        Nonzero pixel fraction below which the image is sparse (default 0.1).
    sparse_sigma : float
        Sigma for sparse images at downsampled resolution (default 5).
    dense_sigma : float
        Sigma for dense images; 0 disables smoothing (default 0).

    Returns
    -------
    float
        Recommended gauss_sigma value.
    """
    nonzero_fraction = np.mean(im > 0)
    if nonzero_fraction < sparse_threshold:
        sigma = sparse_sigma
        print(f"estimate_gauss_sigma: sparse (nonzero={nonzero_fraction:.3f}) "
              f"— using sigma={sigma}")
    else:
        sigma = dense_sigma
        print(f"estimate_gauss_sigma: dense  (nonzero={nonzero_fraction:.3f}) "
              f"— using sigma={sigma}")
    return sigma


# ==============================================================================
# MEMORY DIAGNOSTICS
# ==============================================================================

def _get_psutil():
    """Import psutil lazily so it's an optional dependency."""
    try:
        import psutil
        return psutil
    except ImportError:
        return None


class MemoryTracker:
    """
    Track resident-set-size (RSS) across pipeline tasks.

    Use this to confirm whether memory is actually being released between
    tasks in a batch. If RSS climbs monotonically across tasks, there is a
    leak somewhere (matplotlib figures, Jupyter ``Out[]`` history, retained
    widget state, unfreed numpy temporaries). If RSS returns to baseline
    after the explicit ``gc.collect()`` in each task footer, then per-task
    peak is just exceeding available RAM and the answer is reducing
    ``pad``, using a smaller working resolution, or switching to
    subprocess-per-task mode (see
    :func:`exo2micro.parallel.run_batch_subprocess`).

    When ``enabled=False`` (the default) all methods are cheap no-ops, so
    leaving the calls in production code costs essentially nothing.

    Requires ``psutil`` to actually do anything. If psutil is missing the
    tracker prints a one-time warning and no-ops.

    Example
    -------
    >>> from exo2micro.utils import MemoryTracker
    >>> tracker = MemoryTracker(enabled=True)
    >>> tracker.snapshot('start')
    >>> for sample, dye in tasks:
    ...     tracker.snapshot(f'before {sample}/{dye}')
    ...     SampleDye(sample, dye).run()
    ...     tracker.collect_and_snapshot(f'after gc {sample}/{dye}')
    >>> tracker.summary()
    """

    def __init__(self, enabled=False):
        self.enabled = enabled
        self._psutil = _get_psutil() if enabled else None
        self._process = (self._psutil.Process(os.getpid())
                         if self._psutil else None)
        self._history = []  # list of (label, rss_gb)

        if enabled and self._psutil is None:
            print("[MemoryTracker] psutil not installed; tracking disabled. "
                  "`pip install psutil` to enable.")

    def _rss_gb(self):
        if self._process is None:
            return None
        return self._process.memory_info().rss / 1e9

    def snapshot(self, label):
        """Record current RSS with a label and print it."""
        if not self.enabled or self._process is None:
            return
        rss = self._rss_gb()
        self._history.append((label, rss))
        print(f"[mem] {rss:6.2f} GB  {label}")

    def collect_and_snapshot(self, label):
        """Run ``gc.collect()`` twice then snapshot. Use between tasks."""
        if not self.enabled or self._process is None:
            return
        # Two passes — the first frees cycles, the second sweeps anything
        # that finalizers freed during the first.
        gc.collect()
        gc.collect()
        self.snapshot(label)

    def summary(self):
        """Print a summary table at end of batch."""
        if not self.enabled or not self._history:
            return
        baseline = self._history[0][1]
        peak = max(rss for _, rss in self._history)
        final = self._history[-1][1]
        print("\n[mem] === memory summary ===")
        print(f"[mem] baseline: {baseline:6.2f} GB")
        print(f"[mem] peak:     {peak:6.2f} GB  (+{peak - baseline:.2f} GB)")
        print(f"[mem] final:    {final:6.2f} GB  (+{final - baseline:.2f} GB)")
        if final - baseline > 0.5:
            print("[mem] WARNING: final RSS is >0.5 GB above baseline. "
                  "This suggests a leak rather than just high peak usage. "
                  "Consider switching to subprocess-per-task mode "
                  "(exo2micro.parallel.run_batch_subprocess).")
        print("[mem] ======================\n")
