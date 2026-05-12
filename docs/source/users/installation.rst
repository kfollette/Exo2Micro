Installation
============

Requirements
------------

exo2micro is a Python package. You need:

- **Python 3.9 or newer.** Most conda/miniforge or pyenv installations
  will work. If you don't already have Python set up, install
  `Miniforge <https://github.com/conda-forge/miniforge>`_ — it's the
  quickest path.
- A working **Jupyter** environment if you want to use the interactive
  GUI (recommended for first-time users).

Getting the code
----------------

.. code-block:: bash

   git clone https://github.com/kfollette/Exo2Micro.git
   cd Exo2Micro

Installing the dependencies
---------------------------

All dependencies are available via pip:

.. code-block:: bash

   pip install numpy scipy opencv-python-headless matplotlib \
               astropy tifffile Pillow ipywidgets

Or, if you prefer a single copy-paste command with version pins:

.. code-block:: bash

   pip install "numpy>=1.22" "scipy>=1.8" "opencv-python-headless>=4.5" \
               "matplotlib>=3.5" "astropy>=5.0" "tifffile>=2022.0" \
               "Pillow>=9.0" "ipywidgets>=8.0"

``ipywidgets`` is only needed for the interactive GUI; everything else
is required.

Setting up your raw image directory
-----------------------------------

exo2micro expects your raw images to live in a directory tree with
one folder per sample::

   raw/
     CD070/
       Sample001_PreStain_SybrGld.tif
       Sample001_PostStain_SybrGld.tif
     CD063/
       Sample002_PreStain_SybrGld.tif
       Sample002_PostStain_SybrGld.tif
       Sample002_pre_run3_DAPI.tiff
       Sample002_post_run3_DAPI.tiff

Filename rules
~~~~~~~~~~~~~~

Each raw image filename **must** follow these rules:

1. The filename must end with ``.tif`` or ``.tiff``
   (case-insensitive — ``.TIF`` and ``.TIFF`` are also fine).
2. The filename must contain ``pre`` *or* ``post`` (case-insensitive)
   somewhere in the basename. This tells exo2micro whether the file
   is a pre-stain or post-stain image. The substring can be anywhere
   — ``PreStain``, ``pre``, ``Pre_run3``, and so on all work.
3. The filename must end with ``_<DyeName>.tif`` (or ``.tiff``),
   where ``<DyeName>`` is your dye identifier. The dye name is the
   substring between the **last** underscore and the extension.
4. **Dye names must not contain underscores.** ``SybrGld`` and
   ``DAPI`` and ``Cy5`` are fine; ``SybrGld_microbe`` is not — the
   loader will only see ``microbe``. Use ``SybrGldMicrobe`` or
   similar instead.

Each sample directory must contain **exactly one pre-stain and one
post-stain file per dye**. If multiple dyes are stained on the same
sample, you can have multiple pre/post pairs in the same folder
(see ``CD063`` above), but no more than one of each per dye.

Examples
~~~~~~~~

Valid filenames (all of these work):

- ``Sample001_PreStain_SybrGld.tif``
- ``Sample001_PostStain_SybrGld.tif``
- ``my_2024-03-15_pre_run3_DAPI.tiff``
- ``whatever_post_Cy5.TIF``

Invalid filenames (these will be skipped or rejected):

- ``Sample001_PreStain_SybrGld_microbe.tif`` — dye name has an
  underscore. The loader will parse the dye as ``microbe``, which
  is almost certainly not what you want.
- ``Sample001_pre_post_SybrGld.tif`` — contains both ``pre`` and
  ``post``. Ambiguous — the loader can't tell which one applies.
- ``Sample001_SybrGld.tif`` — contains neither ``pre`` nor ``post``.
  The loader has no way to classify the stain type.
- ``CD050/Sample004a_PreStain_SybrGld.tif`` and
  ``CD050/Sample004b_PreStain_SybrGld.tif`` — two pre-stain files
  for the same dye in one sample. The loader expects exactly one of
  each.

What happens when a filename is wrong
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you click **▶ Run Pipeline** in the GUI or call
:func:`SampleDye.run` from a script, the pipeline iterates over every
``(sample, dye)`` task you requested. Each task is loaded
independently:

- If the filenames for that ``(sample, dye)`` are clean, processing
  proceeds normally.
- If the loader can't cleanly resolve the requested pair, the task
  fails with a multi-line "FILE PROBLEM" message in the output and
  the run continues with the next task.
- All failed tasks are listed in a "PROBLEMS" section at the bottom
  of the summary table after the batch finishes.

This means a single broken filename doesn't block your whole batch
— other dyes and other samples keep processing. You see exactly what
broke and why, all in one place at the end. See :doc:`troubleshooting`
for the catalogue of error messages and what each one means.

If your directory layout is different, you can pass a custom
``raw_dir`` to the GUI or the scripting API.

Verifying the install
---------------------

Open a Python prompt and confirm the package imports::

   import exo2micro as e2m
   print(e2m.__version__)

If that prints ``2.3.0`` (or newer), you're set.

Next: :doc:`quickstart`.
