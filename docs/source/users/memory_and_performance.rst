Memory and Performance
======================

This page is about choosing between serial and parallel mode, and
how to avoid running out of memory when processing big batches. If
you're not sure what those words mean, the short answer is:

**Leave parallel mode OFF.** It's the default. Read on if you want
to know when it's safe to turn it on, or if you've hit memory
problems.

What "serial" and "parallel" mean here
--------------------------------------

exo2micro processes one ``(sample, dye)`` combination at a time as
a "task". When you have many samples and many dyes, you have many
tasks. There are two ways to run them:

- **Serial mode** (``parallel=False``, the default): exo2micro
  processes one task, then the next, then the next. Each task
  fully finishes before the next one starts.
- **Parallel mode** (``parallel=True``): exo2micro launches
  multiple worker processes that each process one task at a time.
  If you set ``n_workers=4``, four tasks run at the same time.

Parallel mode can be a lot faster when you have many tasks. But it
comes with a real memory cost.

Why parallel mode uses more memory
----------------------------------

Each parallel worker is a separate Python process. Each one holds
its own copy of the current sample's images, padded canvases,
alignment buffers, and so on. If a single sample uses 12 GB of RAM
at peak, **four parallel workers use 48 GB**.

Worse: when you exceed your computer's physical RAM, the operating
system starts using disk as "virtual memory" (called *swapping* on
Linux/Mac, *paging* on Windows). Disk is hundreds of times slower
than RAM, so a run that's swapping will be vastly slower than the
same run in serial mode — and may also crash the Python process
entirely if it runs out completely.

When to leave parallel mode OFF
-------------------------------

**Leave it off if any of these are true:**

- You have 16 GB of RAM or less.
- You're not sure how much RAM you have.
- Your images are large (typical exo2micro images are
  30,000 × 25,000 pixels; one of those is about 2.3 GB on disk
  and even larger in memory).
- You're going to use the computer for other things while the
  batch runs.
- You only have a handful of tasks (3 or fewer). The overhead of
  starting worker processes usually makes serial just as fast.

A specific anti-pattern: **don't** set ``parallel=True,
n_workers=1`` to "try parallel mode safely". That gives you the
worst of both worlds — the spawn overhead of parallel mode without
any of the speed benefit, and serial mode's explicit memory
cleanup doesn't run between tasks the way it does in actual serial
mode. If you have RAM for only one worker, just use
``parallel=False``.

When to turn parallel mode ON
-----------------------------

Turn it on when **all** of these are true:

- You have **5 or more** tasks to process.
- You have **enough RAM** to hold multiple full-resolution images
  at once (see the table below).
- You're not planning to use the computer for anything else during
  the run.

How many workers
~~~~~~~~~~~~~~~~

Start conservative. Rough rule of thumb based on your total RAM:

============== ======================
Total RAM      Recommended max workers
============== ======================
8 GB or less   1 (use ``parallel=False``)
16 GB          1 (use ``parallel=False``)
32 GB          2
64 GB          4
128 GB         8
============== ======================

Also never exceed **(your CPU core count) − 1**, so your computer
stays responsive for system tasks.

Checking your RAM
-----------------

- **macOS**: Apple menu → About This Mac → Memory shows installed
  RAM. Applications → Utilities → Activity Monitor → Memory tab
  shows live usage.
- **Windows**: Settings → System → About → Device specifications
  → Installed RAM. Ctrl+Shift+Esc → Task Manager → Performance
  tab → Memory shows live usage.

Watching memory during a run
----------------------------

The first time you run a large batch in parallel, open your
system's task/activity monitor and watch memory usage. If RAM
usage climbs past 90%, or if your computer becomes sluggish:

1. Click the **Abort** button in the GUI (or interrupt the kernel
   in JupyterLab: Kernel → Interrupt Kernel).
2. Reduce ``n_workers`` and try again.
3. If even ``n_workers=2`` runs out of memory, switch to
   ``parallel=False``.

Already-completed tasks are preserved when you abort. The pipeline
saves checkpoints after each stage of each task, so re-running
will pick up where you left off rather than starting over.

Pre-flight resource checks (new in 2.4)
---------------------------------------

Starting in 2.4, both :func:`~exo2micro.run_batch` and
:meth:`SampleDye.run` run a quick resource check before any task
starts. The check reads only the raw TIFF *headers* (no pixel
data, fast even on networked drives), estimates the peak RAM and
total disk output your batch will produce, and compares each to
the available headroom on the machine.

Three severity levels per resource:

- **≤ 80% of available — silent.** Run proceeds normally.
- **80%-100% — warning, run proceeds.** A "⚠️ HIGH" line is
  printed; you should consider closing other applications or
  reducing ``n_workers`` but the run continues.
- **> 100% — hard fail.** :class:`MemoryError` (for RAM) or
  :class:`OSError` (for disk) is raised before any task runs.
  The error message includes a remediation list with concrete
  suggestions (reduce ``n_workers``, reduce ``pad``, switch
  ``checkpoint_format`` to one format only, free disk, etc.) with
  your current values inline.

A typical successful check looks like this::

   === Pre-flight resource check ===
     RAM: estimated peak 2.8 GB vs 16.0 GB available (17%)  ✓
     Disk: estimated total 4.1 GB vs 412 GB free (1%)  ✓
   =================================

This catches the case that previously caused most "kernel dies
mid-batch" reports: starting an 8-worker batch on a 32 GB machine
that needs 6 GB per task. Before 2.4, you'd see the kernel die
with no useful diagnostic. In 2.4, the same configuration raises
``MemoryError`` immediately with a message telling you exactly
how many workers your machine can handle and why.

Overriding the check
~~~~~~~~~~~~~~~~~~~~

If you know the estimate is conservative for your specific data —
for example you've cleared other applications since the estimate
was computed, or your samples are unusually compressible — pass
``force_run=True`` to downgrade the hard fail to a warning::

   results = e2m.run_batch(
       samples=['CD070', 'CD063'],
       dyes=['SybrGld'],
       n_workers=8,
       force_run=True,
   )

This is not recommended for normal use. If a run that's flagged
``❌ EXCEEDS AVAILABLE`` actually does OOM-kill the Python
process mid-batch, you may end up with corrupted checkpoint
files (a half-written TIFF that the next run can't read), so the
default behavior is to refuse the run rather than risk that.

The 6× factor
~~~~~~~~~~~~~

The RAM estimate is::

   peak per task ≈ (H + 2·pad) × (W + 2·pad) × 4 bytes × 6

The 6× factor reflects how many full-resolution float32 image
copies coexist at the worst point of a single task (stage 2 or
stage 3, where padded post + padded pre + downsampled working
copies + warp output buffer + SIFT internals all live in memory
simultaneously). It's a conservative estimate. If you find the
check is consistently refusing batches that actually fit on your
machine, the constant ``PEAK_FACTOR_PER_TASK`` at the top of the
memory-diagnostics section in ``exo2micro/utils.py`` can be
tuned. We expect most users won't need to touch it.

Subprocess mode for low-RAM machines (new in 2.4)
-------------------------------------------------

Even in serial mode, some memory can accumulate across tasks
that ``gc.collect()`` between tasks can't fully reclaim:
matplotlib figure state held by the pyplot module, Jupyter
``Out[]`` cell references, cv2/tifffile internal caches. If
you're seeing your collaborator's kernel die partway through a
serial batch even though the pre-flight check passed, the cause
is likely one of these slow accumulating leaks.

The fix is **subprocess mode**: run each task in a fresh Python
subprocess, exited and reclaimed by the OS between tasks.

::

   results = e2m.run_batch(
       samples=['CD070', 'CD063'],
       dyes=['SybrGld', 'DAPI'],
       parallel='subprocess',
   )

This is a third value for the ``parallel`` argument, alongside
``False`` (serial in-process, the default) and ``True``
(multiprocessing pool). Each task runs in a fresh process. Tasks
run one at a time (not concurrently — for that, use
``parallel=True``).

When to use subprocess mode:

- Your pre-flight check passes (per-task RAM fits) but the
  kernel still dies after a few tasks complete successfully.
- The :class:`~exo2micro.MemoryTracker` summary (below) shows
  RSS climbing monotonically across tasks.
- You want overnight unattended batches to be robust to wedged
  tasks (see ``timeout_per_task`` below).

Important: subprocess mode is **not** the same as
``parallel=True, n_workers=1``. That uses
:class:`multiprocessing.Pool`, which keeps a single worker
process alive across every task, so leaks accumulate in it just
as they do in serial mode. Subprocess mode spawns a new process
*per task* and tears it down after.

Subprocess mode adds ~1-2 seconds of process-spawn overhead per
task. For typical exo2micro tasks that take minutes to align,
this is invisible.

Timeouts and OOM detection
~~~~~~~~~~~~~~~~~~~~~~~~~~

In subprocess mode you can also set ``timeout_per_task`` to
abort any task that runs too long::

   results = e2m.run_batch(
       samples=samples,
       dyes=dyes,
       parallel='subprocess',
       timeout_per_task=1800,   # 30 minutes per task
   )

Recommended for unattended overnight batches so a wedged task
doesn't block the rest.

If a subprocess gets killed by the OS (most often SIGKILL from
the kernel's OOM killer), the parent detects this and records
the task as ``'error: subprocess killed (likely OOM)'`` rather
than crashing the batch. The remaining tasks continue normally.

Diagnosing memory issues (new in 2.4)
-------------------------------------

If you've hit a memory problem and you're not sure whether it's
a per-task peak overrun or an accumulating leak, the
:class:`~exo2micro.MemoryTracker` class can tell you. Pass
``memory_debug=True`` to :func:`run_batch`::

   results = e2m.run_batch(
       samples=['CD070', 'CD063'],
       dyes=['SybrGld', 'DAPI'],
       memory_debug=True,
   )

This prints RSS (resident set size) snapshots before and after
each task, with an explicit ``gc.collect()`` pass in between::

   [mem]   2.34 GB  batch start
   [mem]   2.34 GB  before CD070/SybrGld
   [mem]   8.91 GB  after gc CD070/SybrGld
   [mem]   8.91 GB  before CD070/DAPI
   [mem]  14.22 GB  after gc CD070/DAPI
   [mem]  14.22 GB  before CD063/SybrGld
   ...
   [mem] === memory summary ===
   [mem] baseline:   2.34 GB
   [mem] peak:      14.22 GB  (+11.88 GB)
   [mem] final:     14.22 GB  (+11.88 GB)
   [mem] WARNING: final RSS is >0.5 GB above baseline. ...

The pattern of those numbers tells you which problem you have:

- **RSS climbs monotonically and never returns to baseline** →
  real leak. ``gc.collect()`` isn't recovering memory between
  tasks. Use subprocess mode (above) — that's the only reliable
  cure.
- **RSS spikes during each task but returns to baseline between
  them** → no leak. Per-task peak just exceeds your RAM. Reduce
  ``n_workers``, reduce ``pad``, or close other applications.

The pre-flight check tries to predict the second case before any
task runs, but the tracker is what you want when you've gotten
past pre-flight and still have problems. Requires the optional
``psutil`` dependency::

   pip install psutil

Without psutil, ``memory_debug=True`` no-ops with a one-time
warning.

What exo2micro does on its own to manage memory
-----------------------------------------------

A few things happen automatically that you don't need to think
about:

- **In serial mode**, the pipeline explicitly closes all matplotlib
  figures and runs Python's garbage collector between tasks. This
  is more aggressive than relying on Python's default cleanup and
  is the main reason serial mode is the right choice on low-RAM
  machines.
- **Within a task**, intermediate image data is released as soon
  as each pipeline stage finishes. Stage 2's alignment debug data
  (downsampled images used for the diagnostic plots) is dropped
  as soon as those plots are saved. Stage 3's warp matrices are
  dropped at the end of stage 4. Only the small scalar scale
  estimates survive into the returned result.
- **All intermediate images are float32 on disk** (4 bytes per
  pixel) rather than float64 (8 bytes), which halves the working
  memory footprint without sacrificing visible precision.

You shouldn't normally need to do anything to make these happen.
They're built into the pipeline. They just mean that for the same
hardware, exo2micro can usually process larger batches than a
naive implementation could.
