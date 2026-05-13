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
