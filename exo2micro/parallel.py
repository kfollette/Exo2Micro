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
import json
import os
import subprocess
import sys
from .pipeline import SampleDye
from .utils import discover_tasks, MemoryTracker


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


def run_serial(tasks, tracker=None):
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
    tracker : MemoryTracker or None
        Optional memory tracker. When provided, snapshots RSS before
        and after each task (with a gc.collect() pass between them) so
        leaks can be diagnosed. ``None`` (default) means no tracking.

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
        sample, dye, _ = args
        if tracker is not None:
            tracker.snapshot(f"before {sample}/{dye}")
        results.append(process_one(args))
        # Per-task memory release. Matplotlib's pyplot module retains
        # references to all open figures even after they're saved to
        # disk, so explicitly closing them is necessary; gc.collect()
        # then reclaims any cyclically-referenced numpy arrays that
        # the reference counter alone wouldn't free immediately.
        if have_plt:
            plt.close('all')
        if tracker is not None:
            tracker.collect_and_snapshot(f"after gc {sample}/{dye}")
        else:
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


# ==============================================================================
# SUBPROCESS-PER-TASK RUNNER
# ==============================================================================
#
# Motivation: even in serial mode, some matplotlib / cv2 / tifffile state
# and Jupyter Out[] references can accumulate across tasks. The only fully
# reliable cure for accumulated leaks is to run each task in a fresh Python
# process and let the OS reclaim everything when the process exits.
#
# This is DIFFERENT from `parallel=True, n_workers=1`, which uses a
# multiprocessing.Pool that keeps the same worker process alive across all
# tasks (so leaks accumulate just as they would in serial mode).
# Subprocess-per-task spawns a NEW process for EACH task and tears it down
# after.
#
# Cost: ~1-2 sec spawn + module-import overhead per task. For batches of
# large samples (alignment runtime in minutes) this is negligible. The
# tradeoff is worth it on any machine where serial mode is OOMing.
# ==============================================================================

# Child-process script. Kept as a string (rather than a module-level
# function called via multiprocessing) so the subprocess is a clean,
# debuggable one-shot invocation — you can copy the printed command and
# re-run it manually to reproduce a failure.
_SUBPROCESS_CHILD_SCRIPT = """
import json, sys, traceback
try:
    import matplotlib
    matplotlib.use('Agg')
    import exo2micro as e2m
    args = json.loads(sys.argv[1])
    sample = args['sample']
    dye = args['dye']
    params = args['params'] or {}
    output_dir = params.pop('output_dir', 'processed')
    raw_dir = params.pop('raw_dir', 'raw')
    from_stage = params.pop('from_stage', None)
    to_stage = params.pop('to_stage', None)
    force = params.pop('force', False)
    checkpoint_format = params.pop('checkpoint_format', 'tiff')
    run = e2m.SampleDye(sample, dye, output_dir=output_dir,
                        raw_dir=raw_dir,
                        checkpoint_format=checkpoint_format)
    if params:
        run.set_params(**params)
    result = run.run(from_stage=from_stage, to_stage=to_stage, force=force)
    print('__EXO2MICRO_RESULT__' + json.dumps(result))
except Exception as e:
    traceback.print_exc()
    try:
        a = json.loads(sys.argv[1])
        sample, dye = a.get('sample'), a.get('dye')
    except Exception:
        sample, dye = None, None
    err = {'sample': sample, 'dye': dye, 'status': 'error: ' + str(e)}
    print('__EXO2MICRO_RESULT__' + json.dumps(err))
    sys.exit(1)
"""


def _run_one_subprocess(task, timeout=None):
    """
    Run a single ``(sample, dye, params)`` task in a fresh subprocess.

    Returns a result dict matching :meth:`SampleDye.run`'s contract.
    On subprocess failure (crash, OOM kill, timeout, segfault in a C
    extension) returns a dict with ``status`` starting with
    ``'error: '`` so the caller can keep going.

    Parameters
    ----------
    task : tuple
        ``(sample, dye, params_dict)`` as produced by
        :func:`build_task_list`.
    timeout : float or None
        Maximum seconds for the subprocess. None = no timeout.
    """
    sample, dye, params = task
    payload = json.dumps({
        'sample': sample,
        'dye': dye,
        'params': params,
    })

    try:
        proc = subprocess.run(
            [sys.executable, '-c', _SUBPROCESS_CHILD_SCRIPT, payload],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {'sample': sample, 'dye': dye,
                'status': f'error: subprocess timed out after {timeout}s'}
    except Exception as e:
        return {'sample': sample, 'dye': dye,
                'status': f'error: subprocess launch failed: {e}'}

    # Echo child stdout to the parent so the user sees progress
    # messages, then pluck out the result marker line.
    result = None
    for line in proc.stdout.splitlines():
        if line.startswith('__EXO2MICRO_RESULT__'):
            try:
                result = json.loads(line[len('__EXO2MICRO_RESULT__'):])
            except Exception as e:
                print(f"[subprocess] could not parse result line: {e}")
        else:
            print(line)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    if result is None:
        # Process exited with no result marker — almost certainly an
        # OOM kill (SIGKILL on Linux/Mac leaves no traceback) or a
        # segfault in a C extension. Return code 137 == 128 + 9 == SIGKILL.
        if proc.returncode in (-9, 137):
            status = 'error: subprocess killed (likely OOM)'
        elif proc.returncode < 0:
            status = f'error: subprocess killed by signal {-proc.returncode}'
        else:
            status = (f'error: subprocess exited {proc.returncode} '
                      f'with no result')
        return {'sample': sample, 'dye': dye, 'status': status}

    return result


def run_subprocess(tasks, memory_debug=False, timeout_per_task=None):
    """
    Run all tasks, each in its own fresh Python subprocess.

    Use this on low-RAM machines where serial mode runs OOM partway
    through a batch. Each task gets a clean process, so any leaked
    matplotlib figures / numpy arrays / cv2 caches are reclaimed by
    the OS when the process exits between tasks.

    Parameters
    ----------
    tasks : list of tuple
        Each tuple is ``(sample, dye, params_dict)``, as built by
        :func:`build_task_list`.
    memory_debug : bool
        If True, prints RSS in the parent process before and after
        each task. Useful for confirming the OS is actually reclaiming
        memory between tasks. Requires ``psutil``. Default ``False``.
    timeout_per_task : float or None
        Maximum seconds for any single task. ``None`` (default) means
        no timeout. Recommended to set this for unattended overnight
        batches so a wedged task doesn't block the whole run.

    Returns
    -------
    list of dict
        Results for each task. Failed tasks have ``status`` starting
        with ``'error: '`` rather than raising.

    Notes
    -----
    A few seconds of overhead per task for subprocess launch + import.
    On a batch of large samples (alignment runtime measured in
    minutes) this is invisible. On a batch of small/fast tasks this
    overhead may dominate — use plain :func:`run_serial` in that
    case.
    """
    tracker = MemoryTracker(enabled=memory_debug)
    if memory_debug:
        tracker.snapshot("batch start")

    print(f"Starting subprocess run: {len(tasks)} task(s), one process per task")

    results = []
    for i, task in enumerate(tasks, 1):
        sample, dye, _ = task
        print(f"\n[{i}/{len(tasks)}] {sample}/{dye} (subprocess)")
        if memory_debug:
            tracker.snapshot(f"before {sample}/{dye}")

        result = _run_one_subprocess(task, timeout=timeout_per_task)
        results.append(result)

        if memory_debug:
            # No explicit gc.collect() here — the child process exiting
            # already returned every byte to the OS. The snapshot
            # just confirms that.
            tracker.snapshot(f"after  {sample}/{dye}")

        status = result.get('status', '')
        if 'error' in str(status):
            print(f"  ! {status}")

    if memory_debug:
        tracker.summary()

    return results


def run_batch(samples, dyes, parallel=False, n_workers=4,
              params=None, output_dir='processed', raw_dir='raw',
              from_stage=None, to_stage=None, force=False,
              checkpoint_format='tiff', strict_dyes=True,
              memory_debug=False, timeout_per_task=None):
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

    Execution modes
    ---------------
    Three modes, controlled by the ``parallel`` argument:

    - ``parallel=False`` (default) — **serial in current process**.
      One task at a time, with explicit matplotlib figure cleanup and
      ``gc.collect()`` between tasks. Safe on low-RAM machines for
      moderate batch sizes.
    - ``parallel=True`` — **process pool** of ``n_workers``. Multiple
      tasks run concurrently. Fastest when you have CPU and RAM to
      spare; can OOM on low-RAM machines.
    - ``parallel='subprocess'`` — **subprocess per task**. One fresh
      Python process per task, exited and reclaimed by the OS
      between tasks. Use when serial mode is OOMing on a low-RAM
      machine due to leaks (matplotlib figures, retained widget
      state, accumulated cv2/tifffile caches) that ``gc.collect()``
      can't reach. Adds ~1-2 sec per-task spawn overhead;
      negligible for large samples.

    Parameters
    ----------
    samples : list of str
        Sample names.
    dyes : list of str
        Dye/channel names.
    parallel : bool or str
        ``False`` (default) for serial in-process. ``True`` for a
        process pool. ``'subprocess'`` for one fresh subprocess per
        task. For small batches serial is usually faster than parallel
        due to spawn overhead. On low-RAM machines, prefer
        ``parallel=False`` over ``parallel=True, n_workers=1`` — the
        serial loop releases memory more aggressively between tasks.
        If serial is still OOMing, try ``parallel='subprocess'``.
    n_workers : int
        Number of workers when ``parallel=True`` (default 4). Ignored
        for the other two modes.
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
    memory_debug : bool
        If True, prints RSS before/after each task (with gc.collect()
        between) so leaks can be diagnosed. Requires ``psutil``.
        Useful for triaging "kernel dies mid-batch" reports. Default
        ``False``. Only effective in serial and subprocess modes;
        the parallel pool path ignores it (each worker is in its
        own process, so per-task RSS in the parent isn't meaningful).
    timeout_per_task : float or None
        Only used when ``parallel='subprocess'``. Maximum seconds for
        any single task; ``None`` (default) means no timeout.
        Recommended for unattended overnight batches so a wedged
        task doesn't block the whole run.

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

    # Dispatch by execution mode.
    # `parallel` accepts: False (serial), True (process pool),
    # or the string 'subprocess' (one fresh process per task).
    if parallel == 'subprocess':
        results = run_subprocess(tasks, memory_debug=memory_debug,
                                 timeout_per_task=timeout_per_task)
    elif parallel:
        if memory_debug:
            print("[mem] memory_debug ignored in pool mode (RSS in "
                  "parent is not meaningful when workers are in "
                  "separate processes).")
        results = run_parallel(tasks, n_workers)
    else:
        tracker = MemoryTracker(enabled=memory_debug)
        if memory_debug:
            tracker.snapshot("batch start")
        results = run_serial(tasks, tracker=tracker if memory_debug else None)
        if memory_debug:
            tracker.summary()

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
