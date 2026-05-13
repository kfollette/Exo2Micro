"""
parallel.py
===========
Batch processing for the exo2micro pipeline.

Provides serial and parallel execution of multiple sample+dye combinations.
Each task is processed by creating a :class:`SampleDye` instance and
calling ``run()``.

Usage
-----
::

    from exo2micro.parallel import run_batch

    results = run_batch(
        samples=['CD070', 'CD063'],
        dyes=['SybrGld', 'DAPI'],
        parallel=True,
        n_workers=4,
        output_dir='processed',
    )

Strict vs lenient mode
----------------------
By default (``strict_dyes=True``), :func:`run_batch` raises
:class:`FileNotFoundError` if any requested ``(sample, dye)`` pair has
no raw files on disk. The error message lists every missing pair so
typos surface immediately rather than after a long batch.

To skip missing pairs silently (e.g. when you have heterogeneous
samples where not every dye exists for every sample), pass
``strict_dyes=False``. Skipped pairs are listed in the run log and
omitted from the task list.

Notes
-----
Parallel mode uses :class:`multiprocessing.Pool`. On macOS this uses
``spawn``, so each worker starts a fresh Python interpreter. The
``process_one`` function is importable from this module by design.

Memory and execution mode
-------------------------
The serial loop in :func:`run_serial` explicitly releases per-task
memory (matplotlib figures + the :class:`SampleDye` instance) between
tasks. On low-RAM machines, prefer ``parallel=False`` over
``parallel=True, n_workers=1`` — the serial loop's cleanup is more
aggressive than relying on a single worker process to recycle.

Rule of thumb for ``n_workers``:
``n_workers * (peak RAM per sample) < available RAM``.
If images are large (>1 GB each), start with ``n_workers=4`` and
adjust based on observed memory usage.
"""

import gc
import os
from .pipeline import SampleDye
from .utils import discover_tasks


def process_one(args):
    """
    Process a single (sample, dye) combination.

    This function must be importable by name for multiprocessing
    (required on macOS with the ``spawn`` start method).

    Parameters
    ----------
    args : tuple
        ``(sample, dye, params)`` where ``params`` is a dict of pipeline
        parameters. The keys ``output_dir``, ``raw_dir``, ``from_stage``,
        ``to_stage``, and ``force`` are consumed here; the rest are
        passed to :meth:`SampleDye.set_params`.

    Returns
    -------
    dict
        Result dict with at least ``sample``, ``dye``, and ``status``
        keys, plus ``scale_estimate`` on successful runs.
    """
    import matplotlib
    matplotlib.use('Agg')

    sample, dye, params = args

    # Pop run-control keys before passing remainder to set_params
    output_dir = params.pop('output_dir', 'processed')
    raw_dir = params.pop('raw_dir', 'raw')
    from_stage = params.pop('from_stage', None)
    to_stage = params.pop('to_stage', None)
    force = params.pop('force', False)
    checkpoint_format = params.pop('checkpoint_format', 'tiff')

    run = SampleDye(sample, dye, output_dir=output_dir, raw_dir=raw_dir,
                    checkpoint_format=checkpoint_format)

    # Apply any non-default parameters
    pipeline_params = {k: v for k, v in params.items()}
    if pipeline_params:
        run.set_params(**pipeline_params)

    result = run.run(from_stage=from_stage, to_stage=to_stage, force=force)
    return result


def build_task_list(pairs, params=None,
                    output_dir='processed', raw_dir='raw',
                    from_stage=None, to_stage=None, force=False,
                    checkpoint_format='tiff'):
    """
    Build the list of ``(sample, dye, params)`` tuples for batch processing.

    This is a low-level helper. Callers are responsible for resolving
    which ``(sample, dye)`` pairs actually exist on disk — see
    :func:`exo2micro.utils.discover_tasks`. :func:`run_batch` does this
    automatically; only call ``build_task_list`` directly if you want
    full control over which pairs are queued.

    Parameters
    ----------
    pairs : list of (str, str) tuples
        Explicit list of ``(sample, dye)`` combinations to queue. No
        filesystem checks are performed here; missing files will surface
        as task-level errors at run time.
    params : dict or None
        Pipeline parameters to apply to all tasks. If ``None``, each
        SampleDye uses its built-in defaults.
    output_dir : str
        Root output directory (default ``'processed'``).
    raw_dir : str
        Root raw image directory (default ``'raw'``).
    from_stage : int or None
        Force re-run from this stage onward. Passed through to
        :meth:`SampleDye.run`.
    to_stage : int or None
        Stop after this stage. Passed through to :meth:`SampleDye.run`.
    force : bool
        If True, re-run stages even if checkpoints exist.
    checkpoint_format : {'tiff', 'fits', 'both'}
        Which file format(s) to write for each checkpoint (default
        ``'tiff'``). Passed through to :class:`SampleDye`.

    Returns
    -------
    list of tuple
        Each tuple is ``(sample, dye, params_dict)``.
    """
    task_params = dict(params) if params else {}
    task_params['output_dir'] = output_dir
    task_params['raw_dir'] = raw_dir
    task_params['checkpoint_format'] = checkpoint_format
    if from_stage is not None:
        task_params['from_stage'] = from_stage
    if to_stage is not None:
        task_params['to_stage'] = to_stage
    if force:
        task_params['force'] = force

    return [(sample, dye, dict(task_params))
            for sample, dye in pairs]


def run_serial(tasks):
    """
    Run all tasks sequentially in the current process.

    After each task, explicitly closes all matplotlib figures and runs
    a garbage-collection pass. This is more aggressive than relying on
    Python's reference-counted cleanup at scope exit and matters on
    low-RAM machines processing large images: per-task numpy arrays can
    otherwise linger long enough to overlap the next task's allocations.

    Parameters
    ----------
    tasks : list of tuple
        Each tuple is ``(sample, dye, params_dict)``, as built by
        :func:`build_task_list`.

    Returns
    -------
    list of dict
        Results for each task.
    """
    # Import here to keep top-of-module import cost low for callers
    # that only use run_parallel.
    try:
        import matplotlib.pyplot as plt
        have_plt = True
    except Exception:
        have_plt = False

    results = []
    for args in tasks:
        results.append(process_one(args))
        # Per-task memory release. Matplotlib's pyplot module retains
        # references to all open figures even after they're saved to
        # disk, so explicitly closing them is necessary; gc.collect()
        # then reclaims any cyclically-referenced numpy arrays that
        # the reference counter alone wouldn't free immediately.
        if have_plt:
            plt.close('all')
        gc.collect()
    return results


def run_parallel(tasks, n_workers=4):
    """
    Run all tasks in parallel across ``n_workers`` processes.

    Each worker saves figures to disk; this function blocks until all
    workers are done.

    Parameters
    ----------
    tasks : list of tuple
        Each tuple is ``(sample, dye, params_dict)``, as built by
        :func:`build_task_list`.
    n_workers : int
        Number of parallel worker processes (default 4).

    Returns
    -------
    list of dict
        Results for each task, in the same order as ``tasks``.
    """
    from multiprocessing import Pool
    print(f"Starting parallel run: {len(tasks)} tasks across {n_workers} workers")
    with Pool(processes=n_workers) as pool:
        results = pool.map(process_one, tasks)
    return results


def run_batch(samples, dyes, parallel=False, n_workers=4,
              params=None, output_dir='processed', raw_dir='raw',
              from_stage=None, to_stage=None, force=False,
              checkpoint_format='tiff', strict_dyes=True):
    """
    High-level batch processing entry point.

    Resolves the requested ``samples × dyes`` against what's actually
    on disk, then processes every present combination either serially
    or across a worker pool, and prints a summary table at the end.

    Discovery and strict mode
    -------------------------
    Before queueing tasks, the requested cartesian product is filtered
    against the filesystem via :func:`exo2micro.utils.discover_tasks`.
    A pair is considered "present" when both a pre-stain and a
    post-stain file exist for that dye in the sample's directory.

    - ``strict_dyes=True`` (default): if any requested pair is missing,
      raise :class:`FileNotFoundError` with a single message listing
      every missing pair. Catches typos before a long batch starts.
    - ``strict_dyes=False``: missing pairs are skipped silently (their
      reasons are printed in the batch summary, not raised).

    Parameters
    ----------
    samples : list of str
        Sample names.
    dyes : list of str
        Dye/channel names.
    parallel : bool
        Use multiprocessing (default ``False``). For small batches
        serial is usually faster due to spawn overhead. On low-RAM
        machines prefer ``parallel=False`` over ``parallel=True,
        n_workers=1`` — the serial loop releases memory more
        aggressively between tasks.
    n_workers : int
        Number of workers when ``parallel=True`` (default 4).
    params : dict or None
        Pipeline parameters applied to every task.
    output_dir : str
        Root output directory.
    raw_dir : str
        Root raw image directory.
    from_stage : int or None
        Force re-run from this stage onward.
    to_stage : int or None
        Stop after this stage.
    force : bool
        If True, re-run stages even if checkpoints exist.
    checkpoint_format : {'tiff', 'fits', 'both'}
        Which file format(s) to write for each intermediate
        checkpoint (default ``'tiff'``). Using ``'tiff'`` or
        ``'fits'`` alone cuts disk usage roughly in half compared
        to ``'both'``.
    strict_dyes : bool
        If True (default), raise :class:`FileNotFoundError` when any
        requested ``(sample, dye)`` pair has no raw files on disk.
        Set to False to skip such pairs silently and run only the
        present ones.

    Returns
    -------
    list of dict
        One result per resolvable sample+dye combination.

    Raises
    ------
    FileNotFoundError
        When ``strict_dyes=True`` and one or more requested
        ``(sample, dye)`` pairs cannot be resolved from raw files,
        OR when the raw directory itself has a fatal layout problem
        (missing, empty, no per-sample subfolders) regardless of
        ``strict_dyes``.
    """
    # Resolve requested pairs against the filesystem.
    discovery = discover_tasks(samples, dyes, raw_dir=raw_dir)

    if not discovery['layout_ok']:
        # Layout problem (missing raw_dir, all-empty subdirs, etc.)
        # is always fatal regardless of strict_dyes — there are no
        # pairs to run at all.
        layout_msg = next(
            (w for s, w in discovery['warnings'] if s == '(layout)'),
            f"raw directory '{raw_dir}' is not usable")
        raise FileNotFoundError(layout_msg)

    present = discovery['present']
    skipped = discovery['skipped']
    warnings_list = [(s, w) for s, w in discovery['warnings']
                     if s != '(layout)']

    # Surface filename warnings (separate from missing-pair "skipped"
    # entries) so the user knows about adjacent issues that didn't
    # block their requested pairs.
    if warnings_list:
        print(f"\nFilename warnings ({len(warnings_list)}):")
        for sample, w in warnings_list:
            print(f"  [{sample}] {w}")

    if skipped:
        if strict_dyes:
            # Build one message listing every missing pair so the user
            # sees all typos in one shot.
            lines = ["Some requested (sample, dye) pairs have no "
                     "raw files on disk:"]
            for sample, dye, reason in skipped:
                lines.append(f"  - {sample} / {dye}: {reason}")
            lines.append("")
            lines.append("Fix: either add the missing files, correct "
                         "typos in your sample/dye lists, or pass "
                         "strict_dyes=False to run_batch to skip "
                         "missing pairs and process the rest.")
            raise FileNotFoundError("\n".join(lines))
        else:
            print(f"\nSkipping {len(skipped)} (sample, dye) pair(s) "
                  f"with no raw files:")
            for sample, dye, reason in skipped:
                print(f"  - {sample} / {dye}: {reason}")

    if not present:
        print("\nNo runnable (sample, dye) pairs after discovery — "
              "nothing to do.")
        return []

    tasks = build_task_list(present, params, output_dir, raw_dir,
                            from_stage, to_stage, force,
                            checkpoint_format=checkpoint_format)

    if parallel:
        results = run_parallel(tasks, n_workers)
    else:
        results = run_serial(tasks)

    print_summary(results)
    return results


def print_summary(results):
    """
    Print a summary table for all completed tasks.

    Shows the Moffat-fit scale estimate for each run, and — when any
    result has a ``scale_percentile_value`` or ``manual_scale`` —
    additional columns for those alternative scales. Failed tasks are
    listed in a "Problems" section after the main table with the full
    error message, so users running large batches can see all
    failures consolidated in one place.

    Parameters
    ----------
    results : list of dict
        Results from :func:`run_batch`, :func:`run_serial`, or
        :func:`run_parallel`.
    """
    print(f"\n{'='*72}")
    print(f"  SUMMARY")
    print(f"{'='*72}")

    has_scales = any(r.get('scale_estimate') is not None for r in results)
    has_percentile = any(r.get('scale_percentile_value') is not None
                         for r in results)
    has_manual = any(r.get('manual_scale') is not None for r in results)

    problems = []  # collected for the Problems section below

    if has_scales:
        header = f"  {'Sample':<12} {'Dye':<22} {'Moffat':>10}"
        if has_percentile:
            header += f" {'Percentile':>12}"
        if has_manual:
            header += f" {'Manual':>10}"
        header += f"  {'Status':<10}"
        print(header)
        print(f"  {'-' * (len(header) - 2)}")

        for r in results:
            sample = r.get('sample', '?')
            dye = r.get('dye', '?')
            moffat = r.get('scale_estimate')
            sp_val = r.get('scale_percentile_value')
            ms_val = r.get('manual_scale')
            status = r.get('status', '?')

            if 'error' in str(status):
                problems.append((sample, dye, status))
                short_status = 'error'
            elif status == 'complete':
                short_status = 'complete'
            else:
                short_status = str(status)[:10]

            line = f"  {sample:<12} {dye:<22}"
            line += (f" {moffat:>10.4f}" if moffat is not None
                     else f" {'—':>10}")
            if has_percentile:
                line += (f" {sp_val:>12.4f}" if sp_val is not None
                         else f" {'—':>12}")
            if has_manual:
                line += (f" {ms_val:>10.4f}" if ms_val is not None
                         else f" {'—':>10}")
            line += f"  {short_status:<10}"
            print(line)
    else:
        print(f"  {'Sample':<12} {'Dye':<22} {'Status':<10}")
        print(f"  {'-' * 46}")
        for r in results:
            sample = r.get('sample', '?')
            dye = r.get('dye', '?')
            status = r.get('status', '?')
            if 'error' in str(status):
                problems.append((sample, dye, status))
                print(f"  {sample:<12} {dye:<22} {'error':<10}")
            else:
                print(f"  {sample:<12} {dye:<22} {str(status)[:10]:<10}")

    if problems:
        print(f"\n{'-' * 72}")
        print(f"  PROBLEMS  ({len(problems)} failed task(s))")
        print(f"{'-' * 72}")
        for sample, dye, status in problems:
            print(f"\n  {sample} / {dye}")
            msg = str(status)
            if msg.startswith('error: '):
                msg = msg[7:]
            for line in msg.splitlines():
                print(f"     {line}")
