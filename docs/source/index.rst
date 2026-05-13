exo2micro Documentation
=======================

**exo2micro** is an image registration and fluorescence subtraction
pipeline for pre/post-stain microscopy. It has been designed to process paired pre-stain and
post-stain microscopy images by (a) aligning the images using an iterative process that allows for translation, rotation, shear, and magnification differences between pre- and post- stain images, (b) estimating the autofluorescent mineral background signal, and
(c) optimally subtracting pre- from post-stain images to reveal microbe-only signal. The software is still in active development. 

This software was developed as a collaboration between the `Follette Lab at Amherst College <https://www.follettelab.com>`_, which specializes in astronomical image processing, especially of extrasolar planets and the `Marlow Lab at Boston University <https://www.marlowscience.com/>`_, which specializes in microscopy imaging of astrobiologically interesting terrestrial rock samples. Development of this software was supported by Heising-Simons Foundation grant \#2022-3992 issued as part of the `Scialog: Signatures of Life in the Universe <https://rescorp.org/scialog/signatures-of-life-in-the-universe/>`_ conference series. The software is named for the title of our original grant proposal: "Exoplanets to Microbes: Using Astronomical Image Processing Techniques to Detect Microbes in Astrobiological Contexts".

The current software was written and is maintained by Kate Follette. Undergraduate researchers Giselle Hoermann, Kinsey Cronin, Jessica Laboissiere, Sarah Vierling, and Suyash Deshmukh contributed significantly to early versions of some of its functionalities. 


.. note::

   This documentation is split into two tracks. If you're here to
   **process images**, start with the :doc:`Users track <users/index>`.
   If you're here to **extend, script, or tune** the pipeline, head to
   the :doc:`Developers track <developers/index>`. Most people will
   want the Users track.

.. toctree::
   :maxdepth: 2
   :caption: Users

   users/index

.. toctree::
   :maxdepth: 2
   :caption: Developers

   developers/index

.. toctree::
   :maxdepth: 1
   :caption: Reference

   migration

What exo2micro does
-------------------

Take two fluorescence microscopy images of the same mineral sample — one
before staining (autofluorescent mineral background only) and one after
(background + any microbes that took up the stain) — and produce a
difference image in which microbial signal dominates.

The challenge is that the two images aren't perfectly aligned (the
sample may have shifted, rotated, or been imaged at a slightly different
magnification) and the autofluorescent background has a slightly
different overall brightness in the two images (because autofluorescence
itself can vary with staining chemistry and sample orientation). exo2micro solves both: it
registers the pre-stain image to the post-stain image using a
multi-stage alignment pipeline, then estimates and subtracts a scaled
version of the background.

Four stages, roughly:

1. **Padding** — load raw TIFFs onto a common zero-padded canvas.
2. **Boundary alignment** — phase correlation + ICP on the sample outline.
3. **Interior alignment** — SIFT feature matching on interior structure.
4. **Diagnostics** — estimate the background scale factor (via a Moffat
   fit on the log-ratio distribution) and produce the scaled difference
   image, plus diagnostic plots.

Quick start
-----------

The fastest way in, for most people, is the interactive GUI::

   from exo2micro.gui import launch
   launch()

For scripting::

   import exo2micro as e2m
   run = e2m.SampleDye('CD070', 'SybrGld_microbe')
   run.run()

For everything else, pick a track above.

Version
-------

This documentation is for exo2micro 2.3. The full release history lives
in ``CHANGELOG.md`` at the repository root. See :doc:`migration` for
upgrading from earlier versions.
