Before You Start
================

If you've never installed a Python package from GitHub before, this page is
for you. It walks through every piece of software you need on your computer
**before** you follow the :doc:`installation` instructions, and points you
to where each one lives.

If you already have a working Python environment, a GitHub account, and
Jupyter installed, skip ahead to :doc:`installation`.

What you'll need
----------------

To run exo2micro you need four things on your computer:

1. A **terminal** application (you already have one — see below).
2. A **GitHub account**, so you can download (clone) the code.
3. A **Python installation**, so the code can actually run.
4. **JupyterLab** (or Jupyter Notebook), to open the interactive GUI notebook.

The rest of this page walks through each one.

.. note::

   Throughout this page, anything shown in a code block (like ``cd Documents``)
   is a command you type into your terminal and then press Enter. Don't type
   the ``$`` or ``>`` prompt if your terminal shows one — just the text after it.

1. Opening a terminal
---------------------

Most of the setup is done by typing commands into a "terminal" — a text-based
window where you talk to your computer directly. Every modern computer has one
built in.

**On macOS:**

The app is called **Terminal**. To open it:

- Press ``Cmd`` + ``Space`` to open Spotlight search.
- Type ``Terminal`` and press Enter.

A small window with a text prompt will open. That's your terminal.

**On Windows:**

The app is called **Windows Terminal** (Windows 11) or **Command Prompt** /
**PowerShell** (Windows 10). The easiest option for following these
instructions is to install **Windows Terminal** if you don't have it — it's
free from the Microsoft Store. To open it:

- Click the Start menu.
- Type ``Terminal`` (or ``PowerShell`` if Terminal isn't there) and press Enter.

A window with a text prompt will open. That's your terminal.

.. tip::

   Keep the terminal window open — you'll be using it throughout this setup.
   You can close it when you're done; the changes you make are permanent.

2. Creating a GitHub account
----------------------------

exo2micro's code lives on **GitHub**, a website that hosts open-source software.
To download the code, you'll need a free GitHub account.

1. Go to https://github.com/signup
2. Enter an email address, password, and username. (Your username will be
   public; pick something professional if you plan to share code in the future.)
3. Verify your email when GitHub sends you a confirmation message.

That's it — you don't need to set up any other GitHub features to use exo2micro.

.. note::

   You don't strictly *need* a GitHub account just to download exo2micro
   (the code is public), but having one makes it much easier to report bugs,
   ask questions, and pull updates when new versions come out. It also means
   you'll have ``git`` configured properly, which the installation step
   assumes.

You also need the **git** command-line tool installed so your terminal can
talk to GitHub:

**On macOS:**

git comes pre-installed on most Macs. To check, type this into your terminal
and press Enter::

   git --version

If you see something like ``git version 2.39.0``, you're set. If you see
``command not found``, macOS will pop up a dialog offering to install the
"Command Line Developer Tools" — click **Install** and wait for it to finish
(a few minutes).

**On Windows:**

Download and install Git for Windows from https://git-scm.com/download/win.
Accept all the defaults during installation. After it finishes, **close and
reopen your terminal**, then check it worked by typing::

   git --version

3. Installing Python
--------------------

exo2micro is written in Python, so you need a Python installation on your
computer. The recommended way to install Python for scientific work is
**Miniforge**, which gives you Python plus ``conda``, a tool that manages
scientific Python packages cleanly.

.. note::

   You may already have a Python installation (especially on macOS, which
   ships with one). We strongly recommend installing Miniforge anyway and
   using it for exo2micro. Mixing the system Python with scientific packages
   tends to cause hard-to-debug problems.

**On macOS:**

1. Go to https://github.com/conda-forge/miniforge#download
2. Download the installer for your Mac. If you have an Apple Silicon Mac
   (M1, M2, M3, M4 — anything from 2020 or later), download
   ``Miniforge3-MacOSX-arm64.sh``. For older Intel Macs, download
   ``Miniforge3-MacOSX-x86_64.sh``.
3. In your terminal, navigate to your Downloads folder and run the installer::

      cd ~/Downloads
      bash Miniforge3-MacOSX-arm64.sh

   (Use the filename you actually downloaded.) Press Enter to scroll through
   the license, type ``yes`` to accept, press Enter to confirm the install
   location, and type ``yes`` when it asks whether to initialize Miniforge.
4. **Close and reopen your terminal.** This is required — the changes don't
   take effect in the window where you ran the installer.
5. Verify it worked::

      python --version

   You should see something like ``Python 3.12.7``.

**On Windows:**

1. Go to https://github.com/conda-forge/miniforge#download
2. Download ``Miniforge3-Windows-x86_64.exe``.
3. Double-click the downloaded file to run the installer. Accept the defaults,
   but on the "Advanced Installation Options" page, check the box that says
   **Add Miniforge3 to my PATH environment variable**. (The installer warns
   against this, but it makes things much easier for you. Ignore the warning.)
4. **Close and reopen your terminal.**
5. Verify it worked::

      python --version

   You should see something like ``Python 3.12.7``.

4. Installing JupyterLab
------------------------

JupyterLab is the application that lets you open ``.ipynb`` notebook files,
including the exo2micro interactive GUI. With Python installed, getting
JupyterLab is one command.

In your terminal, type::

   pip install jupyterlab ipywidgets

Wait for the install to finish (a minute or two). When it's done, test
it by launching JupyterLab::

   jupyter lab

Your default web browser will open with the JupyterLab interface. You'll see
a file browser on the left showing whatever folder you launched from.

To **stop** JupyterLab, go back to the terminal window where you ran
``jupyter lab`` and press ``Ctrl`` + ``C``. Confirm with ``y`` if asked.

.. tip::

   JupyterLab runs in your web browser, but it's not on the internet — it's
   a local server on your own computer. You can use it offline.

You're ready
------------

Once you have all four pieces working:

- A terminal you can open
- A GitHub account and the ``git`` command
- Python (via Miniforge)
- JupyterLab

…proceed to :doc:`installation`, which walks through downloading exo2micro
itself and installing its dependencies.

If anything on this page didn't work, see :doc:`troubleshooting` or open
an issue on the GitHub repository.
