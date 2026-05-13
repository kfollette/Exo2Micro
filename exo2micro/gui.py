"""
gui.py
======
Interactive Jupyter notebook interface for the exo2micro pipeline (v2.3).

Designed for non-coders: provides a widget-based GUI for selecting samples,
dyes, scale methods, and advanced parameters, with live inline image
previews, zoom-and-inspect, blink comparison, and batch processing with
progress bars.

Requirements
------------
    pip install ipywidgets

Works in both JupyterLab and classic Jupyter Notebook.

Usage
-----
::

    from exo2micro.gui import launch
    launch()

Or for more control::

    from exo2micro.gui import ExoMicroGUI
    gui = ExoMicroGUI(output_dir='processed', raw_dir='raw')
    gui.display()

Main panels
-----------
* **Input Selection** — sample/dye text fields, auto-detect, scan raw channels
* **Scale Method** — Auto (Moffat fit) / Ratio percentile / Manual
* **Execution Options** — parallel mode, force rerun, from_stage / to_stage
* **Advanced Parameters** — stage-grouped accordion
* **Action buttons** — Run / Status / Reset
* **Parameter Comparison** — sweep one parameter across a list of values
* **Zoom & Inspect** — region slider + Gaussian blur + save on the
  current sample's post/pre-aligned/difference images
* **Blink Comparison** — toggle-flip between alignment checkpoints
"""

import os
import glob
import numpy as np
import ipywidgets as widgets
from IPython.display import display, clear_output, HTML
import matplotlib.pyplot as plt

from .defaults import (DEFAULTS, PARAMETER_REGISTRY, PARAM_STAGES,
                        STAGE_NAMES, PARAM_DESCRIPTIONS, MAX_STAGE)
from .pipeline import SampleDye
from .utils import survey_raw_channels
from . import plotting


# ==============================================================================
# STYLE CONSTANTS
# ==============================================================================

_HEADER_STYLE = {'font_weight': 'bold', 'font_size': '14px'}
_SECTION_STYLE = {'font_weight': 'bold', 'font_size': '12px'}
_DESC_STYLE = {'font_size': '11px', 'text_color': '#666666'}
_BUTTON_LAYOUT = widgets.Layout(width='180px', height='36px')
_WIDE_LAYOUT = widgets.Layout(width='95%')
_NARROW_LAYOUT = widgets.Layout(width='300px')


# ==============================================================================
# WIDGET BUILDERS
# ==============================================================================

def _make_param_widget(name, default, description):
    """
    Create an ipywidget appropriate for a pipeline parameter.

    Parameters
    ----------
    name : str
        Parameter name (used as widget description).
    default : Any
        Default value — determines widget type (Checkbox / IntText /
        FloatText / Text).
    description : str
        Tooltip text.

    Returns
    -------
    widgets.Widget
    """
    label = name.replace('_', ' ').title()

    if isinstance(default, bool):
        w = widgets.Checkbox(
            value=default,
            description=label,
            style={'description_width': '180px'},
            layout=widgets.Layout(width='350px'),
        )
    elif isinstance(default, int) and not isinstance(default, bool):
        w = widgets.IntText(
            value=default,
            description=label,
            style={'description_width': '180px'},
            layout=widgets.Layout(width='350px'),
        )
    elif isinstance(default, float):
        w = widgets.FloatText(
            value=default,
            description=label,
            step=0.01,
            style={'description_width': '180px'},
            layout=widgets.Layout(width='350px'),
        )
    elif default is None:
        # For parameters that default to None but may take floats
        # (scale_percentile, manual_scale). We use a Text field so the
        # user can type 'None' or a decimal value like '99.1'.
        w = widgets.Text(
            value='None',
            description=label,
            style={'description_width': '180px'},
            layout=widgets.Layout(width='350px'),
        )
    else:
        w = widgets.Text(
            value=str(default),
            description=label,
            style={'description_width': '180px'},
            layout=widgets.Layout(width='350px'),
        )

    w.tooltip = description
    return w


def _parse_widget_value(widget, default):
    """Parse a widget value back to the correct Python type."""
    val = widget.value
    if isinstance(default, bool):
        return bool(val)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(val)
    if isinstance(default, float):
        return float(val)
    if default is None:
        if isinstance(val, str):
            val = val.strip()
            if val.lower() in ('none', ''):
                return None
            try:
                return float(val)
            except ValueError:
                return val
        return val
    return val


# Colours for the three scale kinds (shared with plot_excess_heatmap)
_SCALE_COLOR_MOFFAT = '#00cc88'
_SCALE_COLOR_PERCENTILE = '#ff9933'
_SCALE_COLOR_MANUAL = '#ff3366'


# ==============================================================================
# MAIN GUI CLASS
# ==============================================================================

class ExoMicroGUI:
    """
    Interactive Jupyter widget interface for the exo2micro v2.3 pipeline.

    Parameters
    ----------
    output_dir : str
        Root output directory (default ``'processed'``).
    raw_dir : str
        Root raw image directory (default ``'raw'``).

    Attributes
    ----------
    output_dir, raw_dir : str
        Configured paths.
    """

    def __init__(self, output_dir='processed', raw_dir='raw'):
        self.output_dir = output_dir
        self.raw_dir = raw_dir
        self._param_widgets = {}
        # Cached downsampled previews for the zoom panel:
        # {(sample, dye, kind): (preview_ndarray, stride)}
        self._preview_cache = {}
        # Cached full-resolution images for the blink comparison, keyed the
        # same way. We intentionally do not cache the full-res images for
        # the zoom panel — they are loaded on demand when the user checks
        # "Show full-res".
        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Construct the full widget interface."""

        # ── Title ─────────────────────────────────────────────────────────
        self._title = widgets.HTML(
            value='<h2 style="color:#2c3e50; margin-bottom:2px;">'
                  '🔬 exo2micro Pipeline  <span style="font-size:12px; '
                  'color:#7f8c8d;">v2.3</span></h2>'
                  '<p style="color:#7f8c8d; margin-top:0;">'
                  'Fluorescence subtraction for pre/post-stain microscopy'
                  '</p>'
        )

        # ── Sample / Dye selection ────────────────────────────────────────
        self._samples_input = widgets.Textarea(
            value='',
            placeholder='One sample per line, e.g.:\nCD070\nCD063\nCD055',
            description='Samples:',
            style={'description_width': '80px'},
            layout=widgets.Layout(width='300px', height='100px'),
        )
        self._dyes_input = widgets.Textarea(
            value='',
            placeholder='One dye per line, e.g.:\nSybrGld_microbe\nDAPI',
            description='Dyes:',
            style={'description_width': '80px'},
            layout=widgets.Layout(width='300px', height='100px'),
        )

        self._detect_btn = widgets.Button(
            description='Auto-detect',
            button_style='info',
            icon='search',
            layout=widgets.Layout(width='140px', height='32px'),
            tooltip='Scan the raw directory for samples and dyes',
        )
        self._detect_btn.on_click(self._on_detect)
        self._detect_status = widgets.HTML(value='')

        self._survey_btn = widgets.Button(
            description='Survey raw channels',
            button_style='',
            icon='eye',
            layout=widgets.Layout(width='180px', height='32px'),
            tooltip='Check which RGB channels carry signal in each raw TIFF',
        )
        self._survey_btn.on_click(self._on_survey)

        sample_dye_box = widgets.HBox([
            self._samples_input,
            self._dyes_input,
            widgets.VBox([self._detect_btn, self._survey_btn,
                          self._detect_status]),
        ], layout=widgets.Layout(gap='12px'))

        # ── Scale method controls ────────────────────────────────────────
        self._scale_method = widgets.Dropdown(
            options=[
                ('Auto (Moffat fit)', 'auto'),
                ('Auto + ratio percentile', 'percentile'),
                ('Auto + manual override', 'manual'),
                ('Auto + percentile + manual', 'all'),
            ],
            value='auto',
            description='Scale:',
            style={'description_width': '80px'},
            layout=widgets.Layout(width='360px'),
            tooltip='Which scale method(s) to produce difference images for. '
                    'The Moffat fit is always computed.',
        )
        self._scale_method.observe(self._on_scale_method_change,
                                   names='value')

        self._percentile_input = widgets.FloatText(
            value=99.0,
            description='Percentile:',
            step=0.1,
            style={'description_width': '90px'},
            layout=widgets.Layout(width='240px',
                                  visibility='hidden'),
            tooltip='Percentile of log10(post/pre) used as the scale factor. '
                    'Accepts decimal values, e.g. 99.1',
        )
        self._manual_input = widgets.FloatText(
            value=1.0,
            description='Manual:',
            step=0.01,
            style={'description_width': '80px'},
            layout=widgets.Layout(width='240px',
                                  visibility='hidden'),
            tooltip='Exact scale factor override (user-supplied)',
        )

        scale_row = widgets.HBox([
            self._scale_method,
            self._percentile_input,
            self._manual_input,
        ], layout=widgets.Layout(gap='10px'))

        # ── Output format (top-level) ─────────────────────────────────────
        # Which file format(s) each pipeline checkpoint is saved as.
        # Defaults to 'tiff' (single format, ~half the disk usage of
        # 'both'). Controls SampleDye's checkpoint_format kwarg.
        #
        # Layout note: RadioButtons in an HBox next to help text squeezes
        # the radio widget horizontally and causes options to wrap /
        # lose their bullet indicators. Stack label + radio + help
        # vertically with explicit widths instead.
        self._checkpoint_format_label = widgets.HTML(
            value='<b style="color:#34495e; font-size:13px;">Save as:</b>'
        )
        self._checkpoint_format = widgets.RadioButtons(
            options=[
                ('TIFF only (smallest)', 'tiff'),
                ('FITS only', 'fits'),
                ('Both (largest, full metadata)', 'both'),
            ],
            value='tiff',
            description='',  # blank — separate label above avoids squeeze
            layout=widgets.Layout(width='340px'),
        )
        self._checkpoint_format.observe(
            lambda c: self._mark_disk_dirty(), names='value')

        checkpoint_help = widgets.HTML(
            value='<div style="color:#666; font-size:11px; '
                  'max-width:700px; line-height:1.4; margin-top:4px;">'
                  'FITS files carry full metadata (parameter history, '
                  'stage info) in their headers. TIFF files are '
                  'simpler and more widely supported. Choose "Both" '
                  'only if you need FITS headers for provenance. '
                  'Reads automatically fall back to whichever format '
                  'is present on disk.</div>')

        checkpoint_row = widgets.VBox(
            [self._checkpoint_format_label,
             self._checkpoint_format,
             checkpoint_help],
            layout=widgets.Layout(gap='2px', align_items='flex-start'))

        # ── Execution options ────────────────────────────────────────────
        # Parallel and workers moved to Advanced Parameters → Execution tab.
        # These controls live here because users touch them on every run.
        stage_choices = [('Auto (resume)', None)]
        for s in range(1, MAX_STAGE + 1):
            stage_choices.append((f'{s} — {STAGE_NAMES[s].split("_", 1)[1]}',
                                  s))

        # Use style={'description_width': 'initial'} + layout width='auto'
        # so the full checkbox labels always fit. This fixes the
        # "Parall..." / "Forc..." / "Sho..." truncation from earlier
        # versions.
        _cb_style = {'description_width': 'initial'}
        _cb_layout = widgets.Layout(width='auto')

        self._force_rerun = widgets.Checkbox(
            value=False,
            description='Force rerun (ignore checkpoints)',
            style=_cb_style,
            layout=_cb_layout,
        )
        self._from_stage = widgets.Dropdown(
            options=stage_choices,
            value=None,
            description='From stage:',
            style={'description_width': '90px'},
            layout=widgets.Layout(width='280px'),
        )
        self._to_stage = widgets.Dropdown(
            options=stage_choices,
            value=None,
            description='To stage:',
            style={'description_width': '90px'},
            layout=widgets.Layout(width='280px'),
        )
        self._inline_preview = widgets.Checkbox(
            value=True,
            description='Show diagnostic plots inline',
            style=_cb_style,
            layout=_cb_layout,
        )

        # Stage row and force/inline row, both with generous spacing
        # and auto-widths so checkbox labels are never clipped.
        exec_box = widgets.VBox([
            widgets.HBox([self._from_stage, self._to_stage],
                         layout=widgets.Layout(gap='20px',
                                               flex_flow='row wrap')),
            widgets.HBox([self._force_rerun, self._inline_preview],
                         layout=widgets.Layout(gap='24px',
                                               flex_flow='row wrap')),
        ], layout=widgets.Layout(gap='8px'))

        # ── Advanced parameters (accordion, stage-grouped tabs) ──────────
        self._build_advanced_params()

        # ── Action buttons ───────────────────────────────────────────────
        self._run_btn = widgets.Button(
            description='▶  Run Pipeline',
            button_style='success',
            icon='play',
            layout=widgets.Layout(width='200px', height='42px'),
        )
        self._run_btn.on_click(self._on_run)

        # Abort button: hidden by default, shown during a run.
        # Click handler branches on execution mode:
        # - Parallel mode → pool.terminate()
        # - Serial mode → kernel interrupt via JavaScript
        # See _on_abort for the cross-environment details.
        self._abort_btn = widgets.Button(
            description='⛔ Abort',
            button_style='danger',
            icon='stop',
            layout=widgets.Layout(width='140px', height='42px',
                                  visibility='hidden'),
            tooltip='Stop the current pipeline run. In parallel mode '
                    'terminates worker processes; in serial mode '
                    'interrupts the kernel.',
        )
        self._abort_btn.on_click(self._on_abort)

        self._status_btn = widgets.Button(
            description='📋 Check Status',
            button_style='info',
            icon='info',
            layout=widgets.Layout(width='160px', height='42px'),
        )
        self._status_btn.on_click(self._on_status)

        self._reset_btn = widgets.Button(
            description='↺  Reset Params',
            button_style='warning',
            icon='refresh',
            layout=widgets.Layout(width='160px', height='42px'),
        )
        self._reset_btn.on_click(self._on_reset)

        self._view_log_btn = widgets.Button(
            description='📄 View Prev Log',
            button_style='',
            icon='file-text-o',
            layout=widgets.Layout(width='160px', height='42px'),
            tooltip='Load the persistent run log file from disk. '
                    'The log is appended to on every run and '
                    'survives kernel restarts.',
        )
        self._view_log_btn.on_click(self._on_view_log)

        button_box = widgets.HBox(
            [self._run_btn, self._abort_btn,
             self._status_btn, self._reset_btn, self._view_log_btn],
            layout=widgets.Layout(gap='10px'),
        )

        # Parallel-mode abort state: when a pool is active, we hold a
        # reference to it here so _on_abort can call pool.terminate().
        # Cleared between runs.
        self._active_pool = None
        self._abort_requested = False
        self._tee_active = False

        # ── Compare section ──────────────────────────────────────────────
        self._build_compare_section()

        # ── Zoom & inspect section ───────────────────────────────────────
        self._build_zoom_section()

        # ── Blink comparison section ─────────────────────────────────────
        self._build_blink_section()

        # ── Per-section collapsible mini-output widgets ──────────────────
        # Each major section has its own small output area underneath
        # that captures messages related to that section. Collapsed by
        # default; users click to expand. The main bottom output area
        # still captures the full unfiltered stream.
        self._section_outputs = {}
        self._section_accordions = {}
        for key in ('input', 'run'):
            out = widgets.Output(
                layout=widgets.Layout(
                    border='1px solid #eee',
                    max_height='180px',
                    overflow_y='auto',
                    padding='6px',
                    background_color='#fafafa',
                )
            )
            self._section_outputs[key] = out
            acc = widgets.Accordion(children=[out])
            acc.set_title(0, '📜 Output for this section (click to expand)')
            acc.selected_index = None  # collapsed by default
            self._section_accordions[key] = acc

        # ── Output area ──────────────────────────────────────────────────
        # Fixed-height scrollable region so the output never grows
        # taller than ~320px; users scroll within the widget rather
        # than scrolling the whole notebook cell. This is the "floating
        # output" request from the user — true floating widgets aren't
        # supported by ipywidgets, so we use a fixed-height scroll area
        # as the next-best thing.
        self._output = widgets.Output(
            layout=widgets.Layout(
                border='2px solid #3498db',
                height='320px',
                overflow_y='auto',
                overflow_x='auto',
                padding='8px',
                background_color='#fcfcfc',
            )
        )

        # ── Task tiles slot ──────────────────────────────────────────────
        # Placeholder container that _run_pipeline fills with a fresh
        # tile grid at the start of each run. Empty between runs.
        self._task_tiles = {}
        self._tiles_slot = widgets.Box(
            children=(),
            layout=widgets.Layout(display='flex', flex_flow='column'),
        )

        # ── Progress bar ─────────────────────────────────────────────────
        self._progress = widgets.IntProgress(
            value=0, min=0, max=100,
            description='Progress:',
            bar_style='info',
            style={'bar_color': '#3498db'},
            layout=widgets.Layout(width='95%', visibility='hidden'),
        )
        self._progress_label = widgets.HTML(value='')

        # ── Disk space estimate display ──────────────────────────────────
        # A short one-line note near the Run button showing estimated
        # output size vs available free space. Updated whenever the
        # sample/dye list changes or scale method changes. When the
        # estimate exceeds a threshold fraction of free space, the
        # confirmation banner below is revealed and the Run button is
        # temporarily disabled.
        self._disk_estimate_label = widgets.HTML(value='')
        self._disk_estimate_dirty = True  # recompute on next update request

        self._confirm_banner = widgets.HTML(value='')
        self._confirm_proceed_btn = widgets.Button(
            description='⚠ Confirm and run anyway',
            button_style='warning',
            layout=widgets.Layout(width='260px', height='36px',
                                  visibility='hidden'),
        )
        self._confirm_cancel_btn = widgets.Button(
            description='Cancel',
            button_style='',
            layout=widgets.Layout(width='110px', height='36px',
                                  visibility='hidden'),
        )
        self._confirm_proceed_btn.on_click(self._on_confirm_proceed)
        self._confirm_cancel_btn.on_click(self._on_confirm_cancel)
        self._pending_run_args = None  # holds kwargs for _run_pipeline

        confirm_box = widgets.VBox([
            self._confirm_banner,
            widgets.HBox([self._confirm_proceed_btn,
                          self._confirm_cancel_btn],
                         layout=widgets.Layout(gap='10px')),
        ])

        # Recompute the disk estimate when the sample or dye list
        # changes (on auto-detect or manual edit), or when scale
        # method changes (affects n_scale_methods).
        self._samples_input.observe(
            lambda c: self._mark_disk_dirty(), names='value')
        self._dyes_input.observe(
            lambda c: self._mark_disk_dirty(), names='value')
        self._scale_method.observe(
            lambda c: self._mark_disk_dirty(), names='value')

        # ── Assemble layout ──────────────────────────────────────────────
        # ── Assemble layout ───────────────────────────────────────────────
        # Three top-level panes: Input Selection / Run / Full Output
        # Log. Everything that used to be a sibling pane (Scale Method,
        # Output Format, Execution Options, Advanced Parameters) now
        # lives inside the Run pane as collapsible accordions that
        # start closed — so on first open the user sees only the
        # three panes and the Run button, with all the tuning
        # controls hidden one click away.
        #
        # The Parameter Comparison, Zoom & Inspect, and Blink
        # Comparison sections are wrapped in their own "(Optional)"
        # accordions below the main panes, also collapsed by default.

        section_inputs = widgets.VBox([
            widgets.HTML('<h3 style="color:#34495e;">📁 Input Selection</h3>'),
            sample_dye_box,
            self._section_accordions['input'],
        ])

        # Inside the Run pane: four collapsible sub-accordions plus
        # the always-visible run controls. Each sub-accordion starts
        # with selected_index=None (collapsed).
        scale_inner = widgets.VBox([scale_row])
        scale_accordion = widgets.Accordion(children=[scale_inner])
        scale_accordion.set_title(0, '🎚 Scale Method')
        scale_accordion.selected_index = None

        format_inner = widgets.VBox([checkpoint_row])
        format_accordion = widgets.Accordion(children=[format_inner])
        format_accordion.set_title(0, '📝 Output Format')
        format_accordion.selected_index = None

        stages_inner = widgets.VBox([exec_box])
        stages_accordion = widgets.Accordion(children=[stages_inner])
        stages_accordion.set_title(0, '⚙️ Stage Selection & Execution Options')
        stages_accordion.selected_index = None

        # Note: self._advanced_accordion is the existing Accordion
        # that wraps the Execution tab + 4 stage tabs (now including
        # Stage 2.5 Fine ECC). Re-parent it into the Run pane.

        section_run = widgets.VBox([
            widgets.HTML('<h3 style="color:#34495e;">▶ Run</h3>'),
            scale_accordion,
            format_accordion,
            stages_accordion,
            self._advanced_accordion,
            self._disk_estimate_label,
            confirm_box,
            button_box,
            self._progress,
            self._progress_label,
            self._tiles_slot,
            self._section_accordions['run'],
        ], layout=widgets.Layout(gap='6px'))

        # Three optional sections, each in its own collapsed
        # accordion. The accordion title is the only thing visible
        # on first open; clicking reveals the full contents.
        compare_accordion = widgets.Accordion(children=[self._compare_box])
        compare_accordion.set_title(0, '🔬 Parameter Comparison (Optional)')
        compare_accordion.selected_index = None

        zoom_accordion = widgets.Accordion(children=[self._zoom_box])
        zoom_accordion.set_title(0, '🔍 Zoom & Inspect (Optional)')
        zoom_accordion.selected_index = None

        blink_accordion = widgets.Accordion(children=[self._blink_box])
        blink_accordion.set_title(0, '👁️ Blink Comparison (Optional)')
        blink_accordion.selected_index = None

        self._main_ui = widgets.VBox([
            self._title,
            section_inputs,
            section_run,
            widgets.HTML('<hr style="margin:8px 0;">'),
            compare_accordion,
            zoom_accordion,
            blink_accordion,
            widgets.HTML('<hr style="margin:8px 0;">'),
            widgets.HTML('<h4 style="color:#34495e; margin:4px 0;">'
                         '📝 Full Output Log</h4>'),
            self._output,
        ], layout=widgets.Layout(padding='12px'))

    def _build_execution_tab(self):
        """Build the Execution tab widget for the Advanced Parameters accordion.

        Contains the parallel/workers controls plus written guidance on
        when to enable parallel mode and how to choose worker count.
        These controls are in the advanced accordion rather than the
        main Execution Options row because most users shouldn't touch
        them: the defaults (serial mode) are safe for any batch size,
        and parallel mode has meaningful memory and CPU tradeoffs that
        warrant reading the guidance first.
        """
        self._parallel_check = widgets.Checkbox(
            value=False,
            description='Run samples in parallel (multiprocessing)',
            style={'description_width': 'initial'},
            layout=widgets.Layout(width='auto'),
            tooltip=(
                "Leave OFF if your computer has limited RAM (8 GB or "
                "less), or if you're processing very large images. "
                "The one-at-a-time mode actively clears each sample "
                "out of memory before starting the next one. Turn ON "
                "only if you have plenty of RAM to spare — see the "
                "guidance below for how to pick a worker count."
            ),
        )
        self._n_workers = widgets.IntSlider(
            value=2, min=1, max=16, step=1,
            description='Number of workers:',
            style={'description_width': 'initial'},
            layout=widgets.Layout(width='420px'),
        )

        guidance_html = widgets.HTML(value="""
<div style="max-width:720px; font-size:12px; color:#333;
            line-height:1.55; padding:4px 0;">
<p><b>What this does.</b> When <i>Run samples in parallel</i> is off (the
default), exo2micro processes one sample × dye combination at a time.
When it's on, the pipeline launches multiple worker processes that
each process one combination concurrently. For large batches this
can give a significant speedup, but it comes with real memory and
CPU tradeoffs.</p>

<p style="background:#f5f9ff; border-left:4px solid #2a6fb8;
          padding:8px 10px; margin:8px 0;">
<b>💡 Running out of memory?</b> If your computer has limited RAM
(say, 8&nbsp;GB or less), or your images are very large, leave
<i>Run samples in parallel</i> turned <b>off</b>. Even though it sounds
slower, the one-at-a-time mode actively clears each sample out of
memory before starting the next one, so you can process big batches
without your machine running out of RAM. Parallel mode is faster when
you have memory to spare, but each parallel worker holds its own copy
of the current sample's images — so 4 workers means 4× the memory
use.</p>

<p><b>When to enable it.</b> Parallel mode is worthwhile when:</p>
<ul style="margin-top:2px; margin-bottom:8px;">
  <li>You have <b>5 or more</b> sample × dye combinations to process.
      For smaller batches, the overhead of spawning workers usually
      makes serial mode just as fast or faster.</li>
  <li>You have <b>enough RAM</b> to hold several raw images in memory
      at once (see below).</li>
  <li>You're not planning to use the computer for anything else
      during the run.</li>
</ul>

<p><b>⚠️ Raw image size warning.</b>
exo2micro's raw images are typically <b>very large</b> —
30000 × 25000 pixels of 8-bit RGB is about <b>2.3 GB per file</b>, and
the pipeline holds several images in memory at once per worker
(raw post, raw pre, padded post, padded pre, aligned versions). A
single worker can easily use <b>8–16 GB of RAM</b> at peak. Running
with too many workers will hit swap and dramatically <i>slow down</i>
the whole batch — or crash Python if you run out of memory
entirely.</p>

<p><b>How to pick a worker count.</b> Start conservative. A good
rule of thumb:</p>
<ul style="margin-top:2px; margin-bottom:8px;">
  <li><b>2–3 workers</b> for most people. This is the default.</li>
  <li>Up to <b>(your RAM in GB) ÷ 16</b> workers. If you have 64 GB
      of RAM, 4 workers is a reasonable ceiling. If you have 16 GB,
      stay at 1 worker and don't enable parallel mode at all.</li>
  <li>Never exceed <b>(your CPU core count) − 1</b>. Leave at least
      one core free so your computer stays responsive.</li>
</ul>

<p><b>Monitor your system during the first run.</b> The first time
you run a large batch in parallel, open your system's task/activity
monitor and watch CPU and memory usage. If RAM usage climbs past
90%, or if your computer becomes sluggish, stop the run (interrupt
the notebook kernel) and reduce the worker count.</p>

<ul style="margin-top:2px; margin-bottom:8px;">
  <li><b>macOS</b>: Applications → Utilities → Activity Monitor →
      CPU and Memory tabs.</li>
  <li><b>Windows</b>: Ctrl+Shift+Esc → Task Manager → Performance
      tab.</li>
</ul>

<p>For a multi-platform walkthrough of how to read CPU and memory
usage in these tools, see
<a href="https://www.digitalcitizen.life/how-to-check-cpu-usage/"
   target="_blank">this guide on digitalcitizen.life</a>.</p>
</div>
        """)

        return widgets.VBox([
            widgets.HTML('<h4 style="color:#34495e; margin:6px 0 4px 0;">'
                         'Execution mode</h4>'),
            self._parallel_check,
            self._n_workers,
            widgets.HTML('<hr style="margin:10px 0;">'),
            widgets.HTML('<h4 style="color:#34495e; margin:6px 0 4px 0;">'
                         'Guidance</h4>'),
            guidance_html,
        ], layout=widgets.Layout(padding='10px', gap='4px'))

    def _build_advanced_params(self):
        """Group-tabbed accordion of parameter widgets.

        The first tab is "Execution" (parallel/workers + guidance).
        Subsequent tabs correspond to the display groups in
        :data:`exo2micro.defaults.PARAM_GROUPS` — typically one per
        pipeline stage, plus "Stage 2.5 — Fine ECC (optional)" for
        the opt-in fine ECC refinement parameters. Tab order follows
        first-seen order in the registry so Stage 2.5 lands between
        Stage 2 and Stage 3.
        """
        from .defaults import PARAM_GROUPS

        # Build rows for each parameter, keyed by display group.
        # OrderedDict-style preservation of first-seen order.
        group_rows = {}
        for name, (default, abbrev, stage, desc) in PARAMETER_REGISTRY.items():
            w = _make_param_widget(name, default, desc)
            self._param_widgets[name] = w

            desc_html = widgets.HTML(
                value=f'<span style="color:#888; font-size:11px;">'
                      f'({abbrev}) {desc}</span>',
                layout=widgets.Layout(width='500px'),
            )
            row = widgets.HBox([w, desc_html],
                               layout=widgets.Layout(gap='8px'))
            group_label = PARAM_GROUPS.get(name, f'Stage {stage}')
            group_rows.setdefault(group_label, []).append(row)

        # Build the Execution tab first (prepended before group tabs)
        tab_children = [self._build_execution_tab()]
        tab_titles = ['⚡ Execution']

        # Preserve the order groups were first seen in the registry,
        # so Stage 2.5 appears after Stage 2 and before Stage 3.
        for group_label in group_rows.keys():
            rows = group_rows[group_label]
            tab_children.append(widgets.VBox(
                rows, layout=widgets.Layout(padding='8px', gap='4px')))
            tab_titles.append(group_label)

        self._param_tabs = widgets.Tab(children=tab_children)
        for i, title in enumerate(tab_titles):
            self._param_tabs.set_title(i, title)

        self._advanced_accordion = widgets.Accordion(
            children=[self._param_tabs])
        self._advanced_accordion.set_title(0, '🔧 Advanced Parameters')
        self._advanced_accordion.selected_index = None  # collapsed

    def _build_compare_section(self):
        """Parameter-sweep comparison widget block."""
        self._compare_param = widgets.Dropdown(
            options=list(DEFAULTS.keys()),
            value='boundary_width',
            description='Parameter:',
            style={'description_width': '90px'},
            layout=widgets.Layout(width='300px'),
        )
        self._compare_values = widgets.Text(
            value='10, 15, 20',
            description='Values:',
            placeholder='comma-separated, e.g. 10, 15, 20',
            style={'description_width': '70px'},
            layout=widgets.Layout(width='300px'),
        )
        self._compare_save = widgets.Checkbox(
            value=False,
            description='Save variants to disk',
            style={'description_width': '200px'},
            layout=widgets.Layout(width='240px'),
        )
        self._compare_btn = widgets.Button(
            description='Compare',
            button_style='primary',
            icon='columns',
            layout=widgets.Layout(width='120px', height='34px'),
        )
        self._compare_btn.on_click(self._on_compare)

        self._compare_box = widgets.VBox([
            widgets.HTML('<h3 style="color:#34495e;">📊 Parameter Comparison</h3>'),
            widgets.HBox([
                self._compare_param, self._compare_values,
                self._compare_save, self._compare_btn,
            ], layout=widgets.Layout(gap='8px')),
        ])

    def _build_zoom_section(self):
        """Zoom & inspect panel with downsampled live preview."""
        self._zoom_sample = widgets.Text(
            value='',
            description='Sample:',
            placeholder='e.g. CD070',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='200px'),
        )
        self._zoom_dye = widgets.Text(
            value='',
            description='Dye:',
            placeholder='e.g. SybrGld_microbe',
            style={'description_width': '40px'},
            layout=widgets.Layout(width='260px'),
        )
        self._zoom_kind = widgets.Dropdown(
            options=[
                ('Post-stain (01_padded_post)', 'post'),
                ('Aligned pre-stain (03_interior_aligned_pre)',
                 'pre_interior'),
                ('ICP pre-stain (02_icp_aligned_pre)', 'pre_icp'),
                ('Difference (04_difference_difference)', 'difference'),
            ],
            value='difference',
            description='Image:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='420px'),
        )
        self._zoom_load_btn = widgets.Button(
            description='Load',
            button_style='info',
            icon='refresh',
            layout=widgets.Layout(width='90px', height='30px'),
            tooltip='Load a downsampled preview for the selected image',
        )
        self._zoom_load_btn.on_click(self._on_zoom_load)

        self._zoom_row = widgets.IntSlider(
            value=0, min=0, max=1000, step=10,
            description='Row:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='460px'),
            continuous_update=False,
        )
        self._zoom_col = widgets.IntSlider(
            value=0, min=0, max=1000, step=10,
            description='Col:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='460px'),
            continuous_update=False,
        )
        self._zoom_size = widgets.IntSlider(
            value=300, min=50, max=2000, step=10,
            description='Size:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='460px'),
            continuous_update=False,
        )
        self._zoom_sigma = widgets.FloatSlider(
            value=0.0, min=0.0, max=20.0, step=0.5,
            description='σ blur:',
            style={'description_width': '70px'},
            layout=widgets.Layout(width='460px'),
            continuous_update=False,
        )
        for w in (self._zoom_row, self._zoom_col,
                  self._zoom_size, self._zoom_sigma):
            w.observe(self._on_zoom_change, names='value')

        self._zoom_fullres = widgets.Checkbox(
            value=False,
            description='Show full-res (loads from disk on change)',
            style={'description_width': '300px'},
            layout=widgets.Layout(width='400px'),
        )
        self._zoom_fullres.observe(self._on_zoom_change, names='value')

        self._zoom_side_by_side = widgets.Checkbox(
            value=False,
            description='Show post + aligned pre + diff side-by-side',
            style={'description_width': '320px'},
            layout=widgets.Layout(width='420px'),
        )
        self._zoom_side_by_side.observe(self._on_zoom_change, names='value')

        self._zoom_save_btn = widgets.Button(
            description='💾  Save view',
            button_style='success',
            icon='save',
            layout=widgets.Layout(width='160px', height='32px'),
            tooltip='Save the current zoom (full resolution) to '
                    'pipeline_output/zoom_*.png',
        )
        self._zoom_save_btn.on_click(self._on_zoom_save)

        self._zoom_out = widgets.Output(
            layout=widgets.Layout(
                border='1px solid #eee', padding='6px',
                min_height='300px', max_height='700px',
                overflow_y='auto'),
        )
        self._zoom_status = widgets.HTML(value='')

        self._zoom_box = widgets.VBox([
            widgets.HTML(
                '<h3 style="color:#34495e;">🔍 Zoom &amp; Inspect</h3>'
                '<p style="color:#7f8c8d; margin-top:0; font-size:11px;">'
                'Slider interaction uses a downsampled preview; '
                '"Show full-res" re-reads the full image for the current '
                'crop. Saving always writes full resolution.</p>'),
            widgets.HBox([
                self._zoom_sample, self._zoom_dye, self._zoom_kind,
                self._zoom_load_btn,
            ], layout=widgets.Layout(gap='8px')),
            self._zoom_row, self._zoom_col,
            self._zoom_size, self._zoom_sigma,
            widgets.HBox([self._zoom_fullres, self._zoom_side_by_side,
                          self._zoom_save_btn],
                         layout=widgets.Layout(gap='12px')),
            self._zoom_status,
            self._zoom_out,
        ])

    def _build_blink_section(self):
        """Blink comparison helper for visually checking alignment quality."""
        self._blink_sample = widgets.Text(
            value='',
            description='Sample:',
            placeholder='e.g. CD070',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='200px'),
        )
        self._blink_dye = widgets.Text(
            value='',
            description='Dye:',
            placeholder='e.g. SybrGld_microbe',
            style={'description_width': '40px'},
            layout=widgets.Layout(width='260px'),
        )
        self._blink_ref = widgets.Dropdown(
            options=[('Post (reference, stage 1)', 'post')],
            value='post',
            description='A:',
            style={'description_width': '30px'},
            layout=widgets.Layout(width='280px'),
        )
        self._blink_other = widgets.Dropdown(
            options=[
                ('ICP-aligned pre (stage 2)', 'pre_icp'),
                ('Interior-aligned pre (stage 3)', 'pre_interior'),
            ],
            value='pre_interior',
            description='B:',
            style={'description_width': '30px'},
            layout=widgets.Layout(width='340px'),
        )
        self._blink_size = widgets.IntSlider(
            value=400, min=100, max=2000, step=20,
            description='Size:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='420px'),
            continuous_update=False,
        )
        self._blink_row = widgets.IntSlider(
            value=0, min=0, max=1000, step=10,
            description='Row:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='420px'),
            continuous_update=False,
        )
        self._blink_col = widgets.IntSlider(
            value=0, min=0, max=1000, step=10,
            description='Col:',
            style={'description_width': '60px'},
            layout=widgets.Layout(width='420px'),
            continuous_update=False,
        )
        self._blink_load_btn = widgets.Button(
            description='Load',
            button_style='info',
            icon='refresh',
            layout=widgets.Layout(width='90px', height='30px'),
        )
        self._blink_load_btn.on_click(self._on_blink_load)

        self._blink_toggle_btn = widgets.ToggleButton(
            value=False,
            description='Blink: A  ⇄  B',
            icon='exchange',
            layout=widgets.Layout(width='200px', height='34px'),
            tooltip='Flip between image A and image B at the current crop',
        )
        self._blink_toggle_btn.observe(self._on_blink_toggle, names='value')

        for w in (self._blink_size, self._blink_row, self._blink_col):
            w.observe(self._on_blink_draw, names='value')

        self._blink_out = widgets.Output(
            layout=widgets.Layout(
                border='1px solid #eee', padding='6px',
                min_height='300px', max_height='700px',
                overflow_y='auto'),
        )
        self._blink_status = widgets.HTML(value='')

        self._blink_box = widgets.VBox([
            widgets.HTML(
                '<h3 style="color:#34495e;">👁️ Blink Comparison</h3>'
                '<p style="color:#7f8c8d; margin-top:0; font-size:11px;">'
                'Load two alignment checkpoints, then click the toggle '
                'button to flip between them. Sliders move the region '
                'of interest.</p>'),
            widgets.HBox([self._blink_sample, self._blink_dye,
                          self._blink_load_btn],
                         layout=widgets.Layout(gap='8px')),
            widgets.HBox([self._blink_ref, self._blink_other],
                         layout=widgets.Layout(gap='8px')),
            self._blink_row, self._blink_col, self._blink_size,
            self._blink_toggle_btn,
            self._blink_status,
            self._blink_out,
        ])

    # ──────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────

    def _get_samples(self):
        text = self._samples_input.value.strip()
        if not text:
            return []
        return [s.strip() for s in text.split('\n') if s.strip()]

    def _get_dyes(self):
        text = self._dyes_input.value.strip()
        if not text:
            return []
        return [d.strip() for d in text.split('\n') if d.strip()]

    def _get_params(self):
        """Read parameter widgets and return a dict of non-default values.

        Incorporates the top-level Scale Method controls (percentile /
        manual) so they take precedence over the accordion widgets of the
        same name.
        """
        params = {}
        for name, widget in self._param_widgets.items():
            default = DEFAULTS[name]
            value = _parse_widget_value(widget, default)
            if value != default:
                params[name] = value

        # Merge in scale-method overrides from the top-level controls
        method = self._scale_method.value
        if method in ('percentile', 'all'):
            params['scale_percentile'] = float(self._percentile_input.value)
        else:
            params.pop('scale_percentile', None)
        if method in ('manual', 'all'):
            params['manual_scale'] = float(self._manual_input.value)
        else:
            params.pop('manual_scale', None)

        return params

    # ── Task tiles (per sample/dye status cards) ─────────────────────────
    #
    # A grid of compact tiles, one per (sample, dye) task in the current
    # run. Each tile shows the task's state (waiting / in progress /
    # done / error) with an icon, the sample and dye names, and any
    # relevant details (e.g. Moffat scale on success). Tiles are
    # clickable — clicking a completed tile scrolls the main Run output
    # to that task's inline previews.
    #
    # In serial mode, tiles are set to "in progress" at the start of
    # each task and "done" or "error" at the end. In parallel mode, the
    # first N tiles (N = worker count) start as "in progress" and
    # tasks are moved to done/error as imap_unordered yields results,
    # with new waiting tasks promoted to in-progress as worker slots
    # free up.

    _TILE_STATES = {
        'waiting': ('⏳', '#888',    '#f5f5f5', '#ddd'),
        'running': ('🔄', '#0066cc', '#e7f0fb', '#99c2ff'),
        'done':    ('✅', '#2a7a2a', '#eaf7ea', '#9fd39f'),
        'error':   ('❌', '#cc0000', '#fbeaea', '#d99'),
        'skipped': ('—',  '#999',    '#f0f0f0', '#d0d0d0'),
    }

    def _build_task_tile(self, sample, dye):
        """Create a single compact task tile widget.

        Returns an HTML widget that will be updated in place via its
        ``.value`` attribute by :meth:`_set_tile_state`. The tile
        responds to clicks by showing an expanded inline preview of
        its task below itself in the tiles area.
        """
        tile = widgets.HTML(
            value=self._render_tile(sample, dye, 'waiting'),
            layout=widgets.Layout(
                width='240px',
                height='auto',
                min_height='80px',
                margin='4px',
            ),
        )
        return tile

    def _render_tile(self, sample, dye, state, detail=None):
        """Return the HTML string for a tile in the given state."""
        icon, fg, bg, border = self._TILE_STATES.get(
            state, self._TILE_STATES['waiting'])
        label = f'{sample} / {dye}'
        detail_html = ''
        if detail:
            # Escape <, > and & so arbitrary error text can't break layout
            d = (detail.replace('&', '&amp;')
                        .replace('<', '&lt;')
                        .replace('>', '&gt;'))
            detail_html = (f'<div style="color:#555; font-size:11px; '
                           f'margin-top:4px; line-height:1.3;">{d}</div>')

        click_hint = ''
        if state == 'done':
            click_hint = ('<div style="color:#888; font-size:10px; '
                          'margin-top:4px;">previews in main log below</div>')
        elif state == 'error':
            click_hint = ('<div style="color:#888; font-size:10px; '
                          'margin-top:4px;">see main log for full error</div>')

        return (
            f'<div style="border:1px solid {border}; background:{bg}; '
            f'border-radius:4px; padding:8px 10px; min-height:60px;">'
            f'<div style="color:{fg}; font-weight:bold; font-size:12px;">'
            f'{icon} {label}</div>'
            f'{detail_html}'
            f'{click_hint}'
            f'</div>'
        )

    def _set_tile_state(self, sample, dye, state, detail=None):
        """Update a tile's visible state."""
        key = (sample, dye)
        tile = self._task_tiles.get(key)
        if tile is None:
            return
        tile.value = self._render_tile(sample, dye, state, detail=detail)

    def _build_tiles_container(self, task_pairs):
        """Build the grid of task tiles for the current run.

        Parameters
        ----------
        task_pairs : list of (sample, dye) tuples
            Every task that will run in this invocation.

        Returns
        -------
        container : ipywidgets widget
            A Box containing the tiles in flex-wrap layout, suitable
            for inserting into the Run section.
        """
        self._task_tiles = {}
        tile_widgets = []
        for sample, dye in task_pairs:
            tile = self._build_task_tile(sample, dye)
            self._task_tiles[(sample, dye)] = tile
            tile_widgets.append(tile)

        container = widgets.Box(
            children=tile_widgets,
            layout=widgets.Layout(
                display='flex',
                flex_flow='row wrap',
                align_items='flex-start',
                padding='4px 0',
                border='1px solid #e0e0e0',
                background_color='#fafafa',
                margin='6px 0',
            ),
        )
        return container

    def _show_tiles(self, task_pairs, skipped_pairs=None):
        """Create and display the tile grid for a new run.

        Replaces any existing tile grid in the run section's dedicated
        tile slot. Called once at the start of :meth:`_run_pipeline`.

        Parameters
        ----------
        task_pairs : list of (sample, dye) tuples
            Tasks that will actually run, rendered as active tiles
            that cycle waiting → running → done/error.
        skipped_pairs : list of (sample, dye, reason) tuples or None
            Tasks that were requested but have no raw files on disk.
            Rendered as muted gray "(no files)" tiles after the
            active ones so the user can see what got filtered.
        """
        container = self._build_tiles_container(task_pairs)
        children = [container]

        if skipped_pairs:
            children.append(self._build_skipped_tiles_container(skipped_pairs))

        self._tiles_slot.children = tuple(children)

    def _show_skipped_tiles(self, skipped_pairs):
        """Append a row of muted "(no files)" tiles for skipped pairs.

        Used when _show_tiles has already been called but skipped
        pairs need to be added separately (rare; mainly for the
        flow where _run_pipeline does its own discovery and wants
        to update the tile area after _show_tiles).
        """
        existing = list(self._tiles_slot.children)
        existing.append(self._build_skipped_tiles_container(skipped_pairs))
        self._tiles_slot.children = tuple(existing)

    def _build_skipped_tiles_container(self, skipped_pairs):
        """Build the muted gray tile row for pairs with no raw files.

        Each tile shows the sample/dye name and the short reason from
        :func:`discover_tasks`. Tiles in this row are not interactive
        and are not stored in ``self._task_tiles`` (so the run loop
        never tries to update them).
        """
        tile_widgets = []
        for sample, dye, reason in skipped_pairs:
            html = self._render_skipped_tile(sample, dye, reason)
            tile_widgets.append(
                widgets.HTML(
                    value=html,
                    layout=widgets.Layout(
                        width='240px',
                        height='auto',
                        min_height='80px',
                        margin='4px',
                    ),
                ))
        return widgets.Box(
            children=tile_widgets,
            layout=widgets.Layout(
                display='flex',
                flex_flow='row wrap',
                align_items='flex-start',
                padding='4px 0',
                margin='2px 0',
            ),
        )

    def _render_skipped_tile(self, sample, dye, reason):
        """Return HTML for a muted (no files) tile."""
        icon, fg, bg, border = self._TILE_STATES['skipped']
        label = f'{sample} / {dye}'
        # Escape the reason text so unusual paths can't break layout
        r = (reason.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;'))
        return (
            f'<div style="border:1px dashed {border}; background:{bg}; '
            f'border-radius:4px; padding:8px 10px; min-height:60px; '
            f'opacity:0.75;">'
            f'<div style="color:{fg}; font-weight:bold; font-size:12px;">'
            f'{icon} {label}</div>'
            f'<div style="color:#777; font-size:11px; margin-top:4px; '
            f'line-height:1.3;">(no files) {r}</div>'
            f'</div>'
        )

    def _clear_tiles(self):
        """Remove all task tiles from the run section."""
        self._tiles_slot.children = ()
        self._task_tiles = {}

    def _log(self, section, *args, also_main=True, **kwargs):
        """Write a line to a section's mini-output and (optionally) to
        the main output.

        Also persists to the run log file at
        ``{output_dir}/.exo2micro_run_log.txt``. The persistence path
        depends on whether a tee is active:

        - **No tee active** (e.g. auto-detect, view-log, status checks):
          ``_log`` makes one explicit ``append_to_run_log`` call. The
          widget-output writes go to the widgets only, not to a file.
        - **Tee active** (during a pipeline run): the main-output
          ``print`` flows through ``self._output`` → stdout → tee →
          file, so we suppress both the explicit append AND the
          section-output write to avoid duplicating the line in the
          file. Section-output content is still written via a
          temporary tee-bypass so the section mini-output widget
          updates live without the bypass writes also reaching the
          file (which would duplicate them).

        Parameters
        ----------
        section : str or None
            One of 'input', 'run', or None to write only to the main
            output.
        *args, **kwargs
            Passed to ``print``.
        also_main : bool
            If True (default), also write the same line to the main
            output so the full stream is always captured there.
        """
        tee_active = getattr(self, '_tee_active', False)

        # Section output: write directly to the widget. When the tee
        # is active, temporarily detach it so the section-output's
        # internal stdout writes don't also get captured by the tee
        # (which would duplicate the line in the log file). The main
        # output's writes will still flow through the tee.
        if section is not None and section in self._section_outputs:
            if tee_active:
                # Temporarily restore the original stdout so the
                # widget context's prints don't hit the tee.
                import sys as _sys
                tee_obj = _sys.stdout
                if hasattr(tee_obj, '_original_stdout') and \
                        tee_obj._original_stdout is not None:
                    _sys.stdout = tee_obj._original_stdout
                    try:
                        with self._section_outputs[section]:
                            print(*args, **kwargs)
                    finally:
                        _sys.stdout = tee_obj
                else:
                    with self._section_outputs[section]:
                        print(*args, **kwargs)
            else:
                with self._section_outputs[section]:
                    print(*args, **kwargs)

        if also_main:
            with self._output:
                print(*args, **kwargs)

        # Explicit file append ONLY when no tee is active. When the
        # tee is active, the main-output write above already routed
        # to the file via stdout → tee, so an explicit append here
        # would duplicate.
        if not tee_active:
            from .utils import append_to_run_log
            sep = kwargs.get('sep', ' ')
            text = sep.join(str(a) for a in args)
            append_to_run_log(self.output_dir, text)

    def _clear_section(self, section):
        """Clear one section's mini-output widget."""
        if section in self._section_outputs:
            self._section_outputs[section].clear_output()

    def _expand_section(self, section):
        """Programmatically expand a section's collapsible output area."""
        if section in self._section_accordions:
            self._section_accordions[section].selected_index = 0

    # ── Disk space estimate ──────────────────────────────────────────────

    def _mark_disk_dirty(self):
        """Flag that the disk-space estimate needs recomputing.

        Called from the sample/dye/scale-method observers. We don't
        recompute immediately because the typical edit pattern is
        several keystrokes in a row; instead we recompute on demand
        at Run-button click time, and show an "estimate pending"
        label until then.
        """
        self._disk_estimate_dirty = True
        self._disk_estimate_label.value = (
            '<span style="color:#888; font-size:11px;">'
            'Disk estimate: pending (will compute at Run time)</span>')
        # Hide the confirm banner if the user edits the inputs after
        # a previous estimate flagged a problem.
        self._confirm_banner.value = ''
        self._confirm_proceed_btn.layout.visibility = 'hidden'
        self._confirm_cancel_btn.layout.visibility = 'hidden'

    def _compute_disk_estimate(self):
        """Compute the disk-space estimate for the current run plan.

        Calls :func:`discover_tasks` to filter the requested
        ``samples × dyes`` down to pairs that actually exist on disk,
        then estimates output footprint for those present pairs only.
        Pairs requested but missing on disk are surfaced via
        ``skipped`` in the returned dict so the GUI can render them as
        muted tiles or display them in the confirm banner.

        Returns a dict with keys ``total_bytes``, ``free_bytes``,
        ``n_tasks``, ``n_resolvable``, ``warnings``, ``needs_confirm``
        (True if the estimated output exceeds 90% of free space),
        ``present``, ``skipped``, and ``layout_ok``.
        """
        from .utils import (estimate_pipeline_output_size,
                            get_free_disk_space, format_bytes,
                            discover_tasks)

        samples = self._get_samples()
        dyes = self._get_dyes()

        # Resolve against the filesystem.
        discovery = discover_tasks(samples, dyes, raw_dir=self.raw_dir)
        present = discovery['present']
        skipped = discovery['skipped']

        params = self._get_params()
        n_scale_methods = 1  # always Moffat
        if params.get('scale_percentile') is not None:
            n_scale_methods += 1
        if params.get('manual_scale') is not None:
            n_scale_methods += 1

        estimate = estimate_pipeline_output_size(
            present,
            raw_dir=self.raw_dir,
            pad=params.get('pad', 2000),
            save_all_intermediates=params.get('save_all_intermediates', False),
            n_scale_methods=n_scale_methods,
            checkpoint_format=self._checkpoint_format.value,
        )
        free = get_free_disk_space(self.output_dir) or \
               get_free_disk_space('.') or 0

        needs_confirm = False
        if free > 0 and estimate['total_bytes'] > 0.9 * free:
            needs_confirm = True

        self._disk_estimate_dirty = False
        return {
            'total_bytes': estimate['total_bytes'],
            'free_bytes': free,
            'n_tasks': estimate['n_tasks'],
            'n_resolvable': estimate['n_resolvable'],
            'warnings': estimate['warnings'],
            'needs_confirm': needs_confirm,
            'format_bytes': format_bytes,
            'present': present,
            'skipped': skipped,
            'layout_ok': discovery['layout_ok'],
        }

    def _update_disk_estimate_display(self, estimate=None):
        """Update the one-line disk estimate display near the Run button.

        If ``estimate`` is None, computes it fresh.
        """
        if estimate is None:
            estimate = self._compute_disk_estimate()

        fb = estimate['format_bytes']
        total = fb(estimate['total_bytes'])
        free = fb(estimate['free_bytes']) if estimate['free_bytes'] else '?'

        if estimate['total_bytes'] == 0:
            msg = ('<span style="color:#888; font-size:11px;">'
                   'Disk estimate: no resolvable (sample, dye) pairs yet '
                   '— auto-detect or enter samples/dyes above</span>')
        elif estimate['needs_confirm']:
            msg = (f'<span style="color:#cc0000; font-weight:bold; '
                   f'font-size:12px;">'
                   f'⚠ Disk estimate: {total} output for '
                   f'{estimate["n_resolvable"]} task(s) '
                   f'— only {free} free in {self.output_dir}</span>')
        else:
            msg = (f'<span style="color:#2a7a2a; font-size:11px;">'
                   f'✓ Disk estimate: {total} output for '
                   f'{estimate["n_resolvable"]} task(s) '
                   f'({free} free in {self.output_dir})</span>')

        self._disk_estimate_label.value = msg

    # ── Confirmation flow ─────────────────────────────────────────────────

    def _show_confirm_banner(self, estimate):
        """Display the confirm-to-proceed banner and reveal its buttons."""
        fb = estimate['format_bytes']
        total = fb(estimate['total_bytes'])
        free = fb(estimate['free_bytes']) if estimate['free_bytes'] else '?'
        self._confirm_banner.value = (
            f'<div style="background:#fff3cd; border:2px solid #cc0000; '
            f'padding:12px; border-radius:4px; margin:8px 0; '
            f'color:#7a1a1a;">'
            f'<b>⚠ Disk space warning</b><br>'
            f'This run will produce approximately '
            f'<b>{total}</b> of output across '
            f'{estimate["n_resolvable"]} task(s), but only '
            f'<b>{free}</b> is free at <code>{self.output_dir}</code>. '
            f'The run may fail partway through when the disk fills up.'
            f'<br><br>'
            f'Click <b>Confirm and run anyway</b> if you want to '
            f'proceed regardless (you can free space during the run '
            f'and it may still complete), or <b>Cancel</b> to stop '
            f'and free space first.'
            f'</div>'
        )
        self._confirm_proceed_btn.layout.visibility = 'visible'
        self._confirm_cancel_btn.layout.visibility = 'visible'

    def _show_missing_pairs_banner(self, skipped, present_count):
        """Display the missing-pairs banner and reveal its buttons.

        Shown when the user requested ``(sample, dye)`` combinations
        that don't exist on disk. "Confirm and run anyway" proceeds
        with only the present pairs; "Cancel" stops the run so the
        user can fix the inputs.

        Parameters
        ----------
        skipped : list of (sample, dye, reason) tuples
            Pairs that were requested but cannot run.
        present_count : int
            How many pairs DO have raw files. Shown to give the user
            a sense of "is this skipping 2 of 30 or 28 of 30?".
        """
        n_skip = len(skipped)
        # Show up to 8 missing pairs inline; collapse the rest behind a count.
        rows = []
        for sample, dye, reason in skipped[:8]:
            rows.append(
                f'<li><b>{sample}</b> / <b>{dye}</b> — '
                f'<span style="color:#7a1a1a;">{reason}</span></li>')
        if n_skip > 8:
            rows.append(f'<li>… and {n_skip - 8} more</li>')
        rows_html = '\n'.join(rows)

        self._confirm_banner.value = (
            f'<div style="background:#fff3cd; border:2px solid #cc8800; '
            f'padding:12px; border-radius:4px; margin:8px 0; '
            f'color:#5a3a00;">'
            f'<b>⚠ Some requested (sample, dye) pairs have no raw files</b>'
            f'<br><br>'
            f'<b>{present_count}</b> pair(s) can run, but <b>{n_skip}</b> '
            f'are missing from the raw directory:'
            f'<ul style="margin:6px 0 6px 18px;">{rows_html}</ul>'
            f'Most often this is a typo in the sample or dye list, or '
            f'a file that hasn\'t been copied into the raw directory yet.'
            f'<br><br>'
            f'Click <b>Confirm and run anyway</b> to run the '
            f'{present_count} present pair(s) and skip the missing ones, '
            f'or <b>Cancel</b> to fix the inputs first.'
            f'</div>'
        )
        self._confirm_proceed_btn.layout.visibility = 'visible'
        self._confirm_cancel_btn.layout.visibility = 'visible'

    def _hide_confirm_banner(self):
        self._confirm_banner.value = ''
        self._confirm_proceed_btn.layout.visibility = 'hidden'
        self._confirm_cancel_btn.layout.visibility = 'hidden'

    def _on_confirm_proceed(self, btn):
        """User clicked the override button — proceed with the pending run.

        Both the disk-space banner and the missing-pairs banner use
        this handler. The pending args dict carries whatever overrides
        were needed (e.g. ``strict_dyes=False`` from missing-pairs
        flow), so this handler just replays them.
        """
        self._hide_confirm_banner()
        if self._pending_run_args is not None:
            args = self._pending_run_args
            self._pending_run_args = None
            self._run_pipeline(**args)

    def _on_confirm_cancel(self, btn):
        """User clicked cancel — drop the pending run.

        Works for both the disk-space banner and the missing-pairs
        banner. The generic wording covers both cases without needing
        to track which banner was up.
        """
        self._hide_confirm_banner()
        self._pending_run_args = None
        self._log('run', "Run cancelled — fix the inputs and click Run again.")

    def _show_progress(self, value, max_val, label=''):
        self._progress.max = max_val
        self._progress.value = value
        self._progress.layout.visibility = 'visible'
        self._progress_label.value = (
            f'<span style="color:#555; font-size:12px;">{label}</span>')

    def _hide_progress(self):
        self._progress.layout.visibility = 'hidden'
        self._progress_label.value = ''

    def _check_missing_checkpoints(self, run):
        """Return a list of (stage, name) upstream checkpoints that are
        missing for the current parameter configuration."""
        missing = []
        stage_files = {
            1: ['post', 'pre'],
            2: ['pre'],
            3: ['pre'],
        }
        for stage, names in stage_files.items():
            for name in names:
                if not run._has_checkpoint(stage, name):
                    missing.append((stage, name))
        return missing

    def _kind_to_checkpoint(self, kind):
        """
        Map a zoom/blink ``kind`` string to the
        ``(stage, name)`` pair SampleDye uses internally.
        Returns None for kinds without a direct checkpoint (e.g.
        the live stage-4 difference image).
        """
        return {
            'post':         (1, 'post'),
            'pre_icp':      (2, 'pre'),
            'pre_interior': (3, 'pre'),
            'difference':   (MAX_STAGE, 'difference'),
        }.get(kind)

    def _load_full_image(self, sample, dye, kind):
        """Load the full-resolution TIFF for a given sample/dye/kind.

        Returns ``(image, path)`` or ``(None, reason)`` if unavailable.
        """
        import tifffile
        run = SampleDye(sample, dye,
                        output_dir=self.output_dir, raw_dir=self.raw_dir)
        # Apply current params so filename suffix matches the run on disk
        params = self._get_params()
        if params:
            try:
                run.set_params(**params)
            except ValueError:
                # Silently ignore unknown params (shouldn't happen)
                pass
        mapping = self._kind_to_checkpoint(kind)
        if mapping is None:
            return None, f'no checkpoint mapping for kind={kind!r}'
        stage, name = mapping
        path = run._tiff_path(stage, name)
        if not os.path.exists(path):
            return None, f'file not found: {path}'
        try:
            image = tifffile.imread(path)
        except Exception as e:
            return None, f'failed to read: {e}'
        return image, path

    def _downsample_preview(self, image, target=1500):
        """
        Return a downsampled copy suitable for interactive preview.

        Parameters
        ----------
        image : ndarray (2-D)
        target : int
            Target max dimension for the preview.

        Returns
        -------
        preview : ndarray (2-D)
        stride : int
            Every ``stride``-th row/column was taken.
        """
        h, w = image.shape[:2]
        m = max(h, w)
        stride = max(1, int(np.ceil(m / target)))
        preview = image[::stride, ::stride]
        return preview, stride

    def _update_sliders_for_image(self, image_shape, slider_row,
                                  slider_col, slider_size):
        """Re-range the row/col/size sliders based on an image shape."""
        h, w = image_shape[:2]
        # Size can go up to the smaller dimension (but keep a sensible min)
        slider_size.max = max(slider_size.min + 1, min(h, w))
        # Keep current size if it still fits, else clamp
        if slider_size.value > slider_size.max:
            slider_size.value = slider_size.max
        # Row and col ranges depend on the current size
        slider_row.max = max(0, h - slider_size.value)
        slider_col.max = max(0, w - slider_size.value)
        if slider_row.value > slider_row.max:
            slider_row.value = slider_row.max
        if slider_col.value > slider_col.max:
            slider_col.value = slider_col.max

    # ──────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS — inputs / execution
    # ──────────────────────────────────────────────────────────────────────

    def _on_scale_method_change(self, change):
        """Show/hide percentile and manual inputs based on dropdown."""
        method = change['new']
        self._percentile_input.layout.visibility = (
            'visible' if method in ('percentile', 'all') else 'hidden')
        self._manual_input.layout.visibility = (
            'visible' if method in ('manual', 'all') else 'hidden')

    def _on_detect(self, btn):
        """Auto-detect samples and dyes from the raw directory.

        Uses :func:`diagnose_raw_layout` to catch top-level layout
        problems (missing dir, flat files with no per-sample folders,
        etc.) before falling through to per-sample dye discovery via
        :func:`classify_raw_files`. Results are reported into the Input
        Selection section's mini-output (and the main log). After a
        successful detect, the disk-space estimate is recomputed.
        """
        from .utils import classify_raw_files, diagnose_raw_layout

        self._detect_status.value = (
            '<span style="color:#888;">Scanning...</span>')
        self._clear_section('input')

        raw = self.raw_dir

        # Layout-level pre-check. Catches missing dirs, empty dirs,
        # flat layouts (TIFFs at top level instead of in per-sample
        # subdirectories), and all-empty subdirs with a single
        # human-readable explanation rather than the previous
        # one-line "Directory not found".
        layout = diagnose_raw_layout(raw)
        if not layout['ok']:
            short = layout['message'].splitlines()[0]
            self._detect_status.value = (
                f'<span style="color:red;">{short}</span>')
            self._log('input', "⚠️  Raw directory layout problem:")
            for line in layout['message'].splitlines():
                self._log('input', f"    {line}")
            self._expand_section('input')
            return

        samples = sorted([
            d for d in os.listdir(raw)
            if os.path.isdir(os.path.join(raw, d)) and not d.startswith('.')
        ])

        all_dyes = set()
        all_warnings = []  # list of (sample, warning_str)
        for sample in samples:
            sample_dir = os.path.join(raw, sample)
            pairs, warnings = classify_raw_files(sample_dir)
            for w in warnings:
                all_warnings.append((sample, w))
            # Only count dyes that have BOTH a pre and a post file in
            # this sample. Single-sided matches are not usable.
            for dye, files in pairs.items():
                if files['pre'] and files['post']:
                    all_dyes.add(dye)
                else:
                    side = 'post' if not files['pre'] else 'pre'
                    all_warnings.append((sample,
                        f"INCOMPLETE PAIR: dye '{dye}' has no {side}-stain "
                        f"file (only {len(files['pre'])} pre, "
                        f"{len(files['post'])} post)"))
                # Duplicate detection
                if len(files['pre']) > 1:
                    all_warnings.append((sample,
                        f"DUPLICATE PRE: dye '{dye}' has "
                        f"{len(files['pre'])} pre-stain candidates"))
                if len(files['post']) > 1:
                    all_warnings.append((sample,
                        f"DUPLICATE POST: dye '{dye}' has "
                        f"{len(files['post'])} post-stain candidates"))

        if samples:
            self._samples_input.value = '\n'.join(samples)
        if all_dyes:
            self._dyes_input.value = '\n'.join(sorted(all_dyes))

        n_samples = len(samples)
        n_dyes = len(all_dyes)
        n_problems = len(all_warnings)

        # Mini-output: always show what we found, plus any warnings.
        self._log('input',
                  f"Auto-detect scanned {n_samples} sample "
                  f"directory(ies) in {raw}")
        self._log('input',
                  f"  Found {n_dyes} dye(s) with valid pre/post pairs:"
                  f" {sorted(all_dyes) if all_dyes else '(none)'}")

        if n_problems == 0:
            self._detect_status.value = (
                f'<span style="color:green;">'
                f'Found {n_samples} samples, {n_dyes} dyes</span>')
            self._log('input',
                      f"  ✓ No filename problems detected.")
        else:
            self._detect_status.value = (
                f'<span style="color:#cc8800;">'
                f'Found {n_samples} samples, {n_dyes} dyes  '
                f'({n_problems} problem(s) — see Input section output)</span>')
            self._log('input',
                      f"  ⚠ {n_problems} filename problem(s):")
            for sample, w in all_warnings:
                self._log('input', f"     [{sample}] {w}")
            self._log('input',
                      "  These files will be skipped at run time. Fix the "
                      "filenames or remove the offending files to include "
                      "them.")
            self._expand_section('input')

        # Recompute disk-space estimate with the new inputs.
        self._update_disk_estimate_display()

    def _on_survey(self, btn):
        """Run survey_raw_channels on the raw_dir and print to output."""
        self._clear_section('input')
        self._expand_section('input')
        self._log('input', f"Surveying raw channels in {self.raw_dir} ...\n")
        # survey_raw_channels prints to stdout; capture via context
        # manager on the main output, and duplicate a short summary
        # into the Input section after.
        with self._output:
            try:
                survey_raw_channels(self.raw_dir)
            except Exception as e:
                self._log('input', f"  !! Survey failed: {e}")
                return
        self._log('input',
                  "  ✓ Survey complete. Full per-file output in the "
                  "main log below.")

    def _on_run(self, btn):
        """Run button handler: validate inputs, run pre-flight checks
        (missing pairs first, then disk space), and either dispatch to
        :meth:`_run_pipeline` directly or stash the run args and show
        the appropriate confirmation banner.

        Order matters: missing-pairs evaluation has to come before the
        disk-space estimate, because the disk estimate depends on how
        many pairs will actually run. If the user has both problems at
        once, the missing-pairs banner fires first; once they confirm
        skipping (or fix the inputs and click Run again), the disk
        check evaluates against the reduced set.
        """
        samples = self._get_samples()
        dyes = self._get_dyes()

        # Always clear the run section's mini-output at the start of
        # a new invocation so stale messages from a previous run or
        # cancel don't pile up.
        self._clear_section('run')
        self._hide_confirm_banner()

        if not samples or not dyes:
            self._log('run', "⚠️  Please enter at least one sample and one dye.")
            self._expand_section('run')
            return

        # Collect all the arguments for the actual run, so we can
        # replay them after a confirm click.
        run_args = dict(
            samples=samples,
            dyes=dyes,
            params=self._get_params(),
            force=self._force_rerun.value,
            from_stage=self._from_stage.value,
            to_stage=self._to_stage.value,
            show_inline=self._inline_preview.value,
            parallel=self._parallel_check.value,
            n_workers=self._n_workers.value,
            checkpoint_format=self._checkpoint_format.value,
            strict_dyes=True,
        )

        # ── Pre-flight check 1: layout + missing pairs ─────────────────
        # Resolve the cartesian product against the filesystem. If the
        # raw directory has a fatal layout problem, fail with the same
        # human-readable message the API would emit. If individual
        # pairs are missing, prompt the user to confirm skipping.
        estimate = self._compute_disk_estimate()
        self._update_disk_estimate_display(estimate)

        if not estimate.get('layout_ok', True):
            # The raw_dir itself is unusable. Surface the message that
            # diagnose_raw_layout produced via discover_tasks, which is
            # carried in estimate['warnings'] as a layout entry.
            from .utils import diagnose_raw_layout
            layout = diagnose_raw_layout(self.raw_dir)
            self._log('run', "⚠️  Raw directory layout problem — cannot run.")
            for line in layout['message'].splitlines():
                self._log('run', f"    {line}")
            self._expand_section('run')
            return

        skipped = estimate.get('skipped', [])
        present = estimate.get('present', [])

        if not present:
            self._log('run',
                      "⚠️  No (sample, dye) pairs could be resolved from "
                      "the raw directory — nothing to run.")
            if skipped:
                self._log('run',
                          f"   {len(skipped)} requested pair(s) had no "
                          f"matching files. Click Auto-detect to see "
                          f"what's actually present.")
            self._expand_section('run')
            return

        if skipped:
            # Stash the run args with strict_dyes=False so that if the
            # user confirms, the pipeline will skip the missing pairs
            # instead of raising.
            run_args['strict_dyes'] = False
            self._pending_run_args = run_args
            self._show_missing_pairs_banner(skipped, present_count=len(present))
            self._log('run',
                      f"Run paused — {len(skipped)} (sample, dye) "
                      f"pair(s) have no raw files (see banner above). "
                      f"Click 'Confirm and run anyway' to run the "
                      f"{len(present)} present pair(s) and skip the "
                      f"missing ones, or 'Cancel' to fix the inputs.")
            self._expand_section('run')
            return

        # ── Pre-flight check 2: disk space ─────────────────────────────
        if estimate['needs_confirm']:
            self._pending_run_args = run_args
            self._show_confirm_banner(estimate)
            self._log('run',
                      "Run paused — see the disk-space warning above. "
                      "Click 'Confirm and run anyway' to proceed or "
                      "'Cancel' to stop.")
            self._expand_section('run')
            return

        # All good — run directly.
        self._run_pipeline(**run_args)

    def _show_abort_button(self):
        """Reveal the Abort button and dim the Run button while running."""
        self._abort_btn.layout.visibility = 'visible'
        self._run_btn.disabled = True

    def _hide_abort_button(self):
        """Hide the Abort button and re-enable the Run button."""
        self._abort_btn.layout.visibility = 'hidden'
        self._run_btn.disabled = False

    def _on_abort(self, btn):
        """Abort the current pipeline run.

        Dispatches on execution mode:

        - **Parallel mode.** If there's an active multiprocessing Pool
          stored in ``self._active_pool``, call ``pool.terminate()``
          to kill the workers immediately. The ``imap_unordered``
          iterator in :meth:`_run_pipeline` will then raise, and the
          surrounding try/except in this class catches it and
          finalises the run.

        - **Serial mode.** ipywidgets button clicks can't be
          processed while the main kernel thread is executing Python
          code, so we can't directly raise an exception in the
          running pipeline loop. Instead we emit a JavaScript snippet
          that tells the Jupyter frontend to send SIGINT to the
          kernel — the same thing the Jupyter toolbar's "Interrupt
          Kernel" menu item does. This works because the interrupt
          request travels out-of-band via the Jupyter protocol and is
          received even when the kernel is busy. At the next Python
          opcode, the kernel raises ``KeyboardInterrupt``, which is
          caught by :meth:`_run_pipeline`'s outer try/except.

        Works in both JupyterLab and classic Jupyter Notebook — the
        injected JavaScript tries the classic API first and falls
        back to JupyterLab's command registry on failure.
        """
        self._abort_requested = True
        self._log('run', "\n⛔ Abort requested by user.")

        # Parallel-mode abort: terminate the pool directly.
        if self._active_pool is not None:
            try:
                self._active_pool.terminate()
                self._log('run',
                          "   Parallel workers terminated. "
                          "Already-completed tasks are preserved.")
            except Exception as e:
                self._log('run', f"   Pool termination failed: {e}")
            # Leave it to _run_pipeline's exception handling to clean
            # up; don't clear self._active_pool here since the
            # iterator needs to observe the terminated state.
            return

        # Serial-mode abort: inject JavaScript to trigger a kernel
        # interrupt. The frontend dispatches SIGINT to the kernel
        # process, which Python receives as KeyboardInterrupt.
        from IPython.display import display, Javascript
        js = """
        (function() {
            // Classic Jupyter Notebook:
            if (typeof IPython !== 'undefined'
                && IPython.notebook
                && IPython.notebook.kernel) {
                IPython.notebook.kernel.interrupt();
                return;
            }
            // JupyterLab (via command registry, when available):
            if (typeof Jupyter !== 'undefined'
                && Jupyter.notebook
                && Jupyter.notebook.kernel) {
                Jupyter.notebook.kernel.interrupt();
                return;
            }
            // JupyterLab command registry:
            try {
                var cmd = 'notebook:interrupt-kernel';
                if (window.jupyterapp
                    && window.jupyterapp.commands
                    && window.jupyterapp.commands.hasCommand(cmd)) {
                    window.jupyterapp.commands.execute(cmd);
                    return;
                }
            } catch (e) {}
            // Last-resort fallback message for environments we
            // don't recognise (e.g. VSCode notebooks):
            console.warn('exo2micro abort: could not find a '
                + 'kernel-interrupt API. Use the toolbar '
                + '"Interrupt Kernel" button instead.');
        })();
        """
        try:
            display(Javascript(js))
            self._log('run',
                      "   Kernel interrupt requested. The run will "
                      "stop at the next safe point (may take a few "
                      "seconds if inside a long NumPy/OpenCV call).")
            self._log('run',
                      "   If the button doesn't take effect, use the "
                      "Jupyter toolbar's 'Interrupt Kernel' menu item.")
        except Exception as e:
            self._log('run',
                      f"   Abort failed to inject JavaScript: {e}. "
                      f"Use the Jupyter toolbar's 'Interrupt Kernel' "
                      f"menu item instead.")

    def _run_pipeline(self, samples, dyes, params, force, from_stage,
                      to_stage, show_inline, parallel, n_workers,
                      checkpoint_format='tiff', strict_dyes=True):
        """Actually execute the pipeline.

        Invoked either directly from :meth:`_on_run` when both
        pre-flight checks pass, or from :meth:`_on_confirm_proceed`
        when the user overrides one. The ``strict_dyes`` flag carries
        the user's choice from the missing-pairs banner: True means
        any unresolvable pair would have raised in :func:`run_batch`,
        but we already evaluated that in :meth:`_on_run` and either
        returned early or got user consent before getting here.

        Creates a grid of task tiles (one per sample × dye) in the Run
        section. Pairs that exist on disk render as active tiles that
        cycle waiting → running → done/error. Pairs that were
        requested but have no raw files render as muted gray tiles
        with a "(no files)" label so the user can see at a glance
        what was filtered out.

        In serial mode each active tile cycles waiting → running →
        done/error. In parallel mode tiles also update as
        :meth:`multiprocessing.Pool.imap_unordered` yields completed
        results, and inline previews are shown for each completed task.

        The ``checkpoint_format`` kwarg controls which file format(s)
        each :class:`SampleDye` writes for its intermediates.
        """
        # Re-resolve here (rather than reusing _on_run's discovery)
        # because _on_confirm_proceed → _run_pipeline can be called
        # after the user has had time to edit the raw directory.
        from .utils import discover_tasks
        discovery = discover_tasks(samples, dyes, raw_dir=self.raw_dir)
        task_pairs = discovery['present']           # runnable
        skipped_pairs = discovery['skipped']        # rendered muted
        total_tasks = len(task_pairs)
        results = []

        # Reset abort state for this run and reveal the Abort button.
        self._abort_requested = False
        self._active_pool = None
        self._show_abort_button()

        # Initialise the tile grid before printing anything else so it
        # appears above the run log. Active tiles first, muted tiles
        # for skipped pairs after.
        self._show_tiles(task_pairs, skipped_pairs=skipped_pairs)

        # Main output still captures the full stream. Expand the Run
        # Mini-output so the user sees activity immediately.
        self._expand_section('run')
        with self._output:
            clear_output()

        if skipped_pairs:
            self._log('run',
                      f"⏭  Skipping {len(skipped_pairs)} (sample, dye) "
                      f"pair(s) with no raw files:")
            for sample, dye, reason in skipped_pairs:
                self._log('run', f"    {sample} / {dye} — {reason}")
            self._log('run', "")

        if not task_pairs:
            self._log('run',
                      "⚠️  No runnable (sample, dye) pairs after "
                      "discovery — nothing to do.")
            self._hide_abort_button()
            return

        # Open the persistent run log via TeeStdout so EVERY line of
        # pipeline output (including raw print() calls inside library
        # functions) gets captured to disk for later inspection. The
        # tee wraps the entire run; nested `with self._output:` blocks
        # still work because TeeStdout writes to the original stdout
        # first (which the widget context captures) before mirroring
        # to the file. Without this, only the GUI's own _log() calls
        # would persist, not the bulk of the pipeline's output.
        from .utils import TeeStdout, get_run_log_path
        log_path = get_run_log_path(self.output_dir)

        try:
            self._tee_active = True
            with TeeStdout(log_path):
                self._run_pipeline_body(
                    task_pairs, total_tasks, samples, dyes, params,
                    force, from_stage, to_stage, show_inline,
                    parallel, n_workers, checkpoint_format, results)
        except KeyboardInterrupt:
            self._log('run',
                      "\n⛔ Run interrupted. Already-completed tasks "
                      "are preserved; remaining tasks were cancelled.")
            # Mark any still-waiting tiles as cancelled. Running tiles
            # stay in their 'running' state since we can't know
            # whether the interrupt fired mid-stage or between tasks.
            for (s, d), tile in self._task_tiles.items():
                if 'waiting' in tile.value:
                    self._set_tile_state(s, d, 'error',
                                         detail='Cancelled by abort')
        except Exception as e:
            # Any other unexpected exception: log it and let the
            # finally block clean up the UI state.
            self._log('run', f"\n❌ Unexpected error: {e}")
            import traceback
            with self._output:
                traceback.print_exc()
        finally:
            # Clean up: hide the abort button, clear pool reference,
            # turn off the tee-active flag so subsequent _log calls
            # outside a run resume their direct file appends.
            self._tee_active = False
            self._hide_abort_button()
            self._active_pool = None

            # Summary always goes to the main output (full detail)
            # so the user can see partial results even after abort.
            with self._output:
                self._print_summary(results)

    def _run_pipeline_body(self, task_pairs, total_tasks, samples, dyes,
                           params, force, from_stage, to_stage,
                           show_inline, parallel, n_workers,
                           checkpoint_format, results):
        """Inner body of _run_pipeline, separated so the outer method
        can wrap it in try/except/finally for abort handling.
        """
        if parallel and total_tasks > 1:
            self._log('run',
                      f"🚀 Starting parallel run: {total_tasks} tasks "
                      f"across {n_workers} workers")
            self._log('run',
                      "   Inline previews will appear as each task "
                      "completes.\n")

            from .parallel import process_one
            import multiprocessing

            # Build the per-task (sample, dye, params) tuples that
            # process_one expects. Each needs its own copy of params
            # with the run-control keys baked in.
            tasks = []
            for sample, dye in task_pairs:
                task_params = dict(params) if params else {}
                task_params['output_dir'] = self.output_dir
                task_params['raw_dir'] = self.raw_dir
                task_params['from_stage'] = from_stage
                task_params['to_stage'] = to_stage
                task_params['force'] = force
                task_params['checkpoint_format'] = checkpoint_format
                tasks.append((sample, dye, task_params))

            # Mark the first n_workers tiles as 'running' so the user
            # sees which tasks are in flight immediately. This is a
            # cosmetic approximation — imap_unordered won't
            # necessarily assign workers to the first N tasks in
            # order, but visually it's fine and changes below as
            # tasks complete.
            in_flight = set()
            for (s, d) in task_pairs[:n_workers]:
                self._set_tile_state(s, d, 'running')
                in_flight.add((s, d))

            # Index remaining tasks by (sample, dye) so we can promote
            # the next waiting one when a slot frees up.
            waiting_queue = list(task_pairs[n_workers:])

            self._show_progress(0, total_tasks, 'Running in parallel...')

            # Use spawn context to be macOS-safe (matches run_parallel)
            ctx = multiprocessing.get_context('spawn')
            n_complete = 0
            with self._output:
                with ctx.Pool(n_workers) as pool:
                    # Store the pool so _on_abort can terminate it
                    # from the event handler thread if the user
                    # clicks Abort.
                    self._active_pool = pool
                    for result in pool.imap_unordered(process_one, tasks):
                        n_complete += 1
                        sample = result.get('sample', '?')
                        dye = result.get('dye', '?')
                        status = result.get('status', '?')

                        # Update the completed tile
                        if 'error' in str(status):
                            detail = str(status)[7:] if \
                                str(status).startswith('error: ') \
                                else str(status)
                            self._set_tile_state(
                                sample, dye, 'error',
                                detail=detail[:80] +
                                       ('...' if len(detail) > 80 else ''))
                        else:
                            scale = result.get('scale_estimate')
                            detail = (f'Moffat: {scale:.4f}'
                                      if scale is not None else status)
                            self._set_tile_state(
                                sample, dye, 'done', detail=detail)

                        in_flight.discard((sample, dye))
                        results.append(result)

                        # Promote the next waiting task to 'running'
                        if waiting_queue:
                            next_s, next_d = waiting_queue.pop(0)
                            self._set_tile_state(next_s, next_d, 'running')
                            in_flight.add((next_s, next_d))

                        # Show inline preview for this completed task.
                        # This reads PNGs from disk that the worker
                        # already wrote, so no IPC with the worker is
                        # needed.
                        if show_inline and 'error' not in str(status):
                            # Build a SampleDye locally to point at the
                            # files the worker wrote. Only used for
                            # file path resolution — doesn't re-run
                            # anything.
                            local_run = SampleDye(
                                sample, dye,
                                output_dir=self.output_dir,
                                raw_dir=self.raw_dir,
                                checkpoint_format=checkpoint_format)
                            if params:
                                try:
                                    # Strip the run-control keys that
                                    # process_one pops off its params
                                    stripped = {k: v for k, v in
                                                params.items()
                                                if k not in
                                                ('output_dir', 'raw_dir',
                                                 'from_stage', 'to_stage',
                                                 'force')}
                                    if stripped:
                                        local_run.set_params(**stripped)
                                except ValueError:
                                    pass
                            self._show_inline_results(local_run, result)

                        # Update progress as each task completes
                        self._show_progress(
                            n_complete, total_tasks,
                            f'Completed {n_complete}/{total_tasks}')

            self._show_progress(total_tasks, total_tasks, 'Complete!')

        else:
            task_idx = 0
            for sample, dye in task_pairs:
                # Between-task abort check. In serial mode the main
                # kernel thread is busy running pipeline code, so the
                # Abort button can't trigger a handler directly — but
                # if the user hit the Jupyter toolbar's Interrupt
                # Kernel button or if the JS interrupt landed, the
                # KeyboardInterrupt will fire. We also poll
                # _abort_requested here for any code path that sets
                # it synchronously.
                if self._abort_requested:
                    raise KeyboardInterrupt("aborted by user")

                task_idx += 1
                self._show_progress(
                    task_idx - 1, total_tasks,
                    f'Processing {sample} / {dye}  '
                    f'({task_idx}/{total_tasks})')
                self._set_tile_state(sample, dye, 'running')

                self._log('run',
                          f"\n═══ {sample} / {dye}  "
                          f"(task {task_idx}/{total_tasks}) ═══")

                run = SampleDye(sample, dye,
                                output_dir=self.output_dir,
                                raw_dir=self.raw_dir,
                                checkpoint_format=checkpoint_format)
                if params:
                    try:
                        run.set_params(**params)
                    except ValueError as e:
                        self._log('run', f"  !! Parameter error: {e}")
                        self._set_tile_state(
                            sample, dye, 'error',
                            detail=f'Parameter error: {e}')
                        continue

                # Auto-fall-back if upstream checkpoints are missing.
                if (not force and from_stage is not None
                        and from_stage > 1):
                    missing = self._check_missing_checkpoints(run)
                    if missing:
                        self._log('run',
                            f"⚠️  {sample}/{dye}: upstream "
                            f"checkpoints missing for current "
                            f"params: {missing}")
                        self._log('run',
                            f"   Running from stage 1 instead.\n")
                        from_stage_actual = 1
                    else:
                        from_stage_actual = from_stage
                else:
                    from_stage_actual = from_stage

                # Stage output goes to the main log via the output
                # widget context manager. The run mini-output only
                # sees the task banner and summary.
                with self._output:
                    result = run.run(
                        from_stage=from_stage_actual,
                        to_stage=to_stage,
                        force=force,
                    )
                results.append(result)

                # Update tile and run section with the completion
                status = result.get('status', '?')
                scale = result.get('scale_estimate')
                if 'error' in str(status):
                    detail = str(status)[7:] if \
                        str(status).startswith('error: ') else str(status)
                    self._set_tile_state(
                        sample, dye, 'error',
                        detail=detail[:80] +
                               ('...' if len(detail) > 80 else ''))
                    self._log('run', f"  ❌ {sample}/{dye}: {status}")
                elif scale is not None:
                    self._set_tile_state(
                        sample, dye, 'done',
                        detail=f'Moffat: {scale:.4f}')
                    self._log('run',
                              f"  ✅ {sample}/{dye}: scale={scale:.4f}")
                else:
                    self._set_tile_state(sample, dye, 'done', detail=status)
                    self._log('run', f"  ⚠️ {sample}/{dye}: {status}")

                if show_inline:
                    self._show_inline_results(run, result)

            self._show_progress(total_tasks, total_tasks, 'Complete!')

    def _on_status(self, btn):
        """Show checkpoint status for all selected sample+dye combinations.

        Routes status output through the Run section so the results
        sit next to the Run button rather than hidden at the bottom.
        """
        samples = self._get_samples()
        dyes = self._get_dyes()

        self._clear_section('run')
        self._expand_section('run')

        if not samples or not dyes:
            self._log('run',
                      "⚠️  Please enter at least one sample and one dye.")
            return

        params = self._get_params()
        checkpoint_format = self._checkpoint_format.value

        with self._output:
            clear_output()
            for dye in dyes:
                for sample in samples:
                    run = SampleDye(sample, dye,
                                    output_dir=self.output_dir,
                                    raw_dir=self.raw_dir,
                                    checkpoint_format=checkpoint_format)
                    if params:
                        try:
                            run.set_params(**params)
                        except ValueError as e:
                            self._log('run',
                                      f"  parameter error: {e}")
                            continue
                    run.status()
                    print()

        self._log('run',
                  f"✓ Checked {len(samples) * len(dyes)} task(s). "
                  f"Full checkpoint checklist in the main log below.")

    def _on_reset(self, btn):
        """Reset all parameter widgets to their defaults."""
        for name, widget in self._param_widgets.items():
            default = DEFAULTS[name]
            if default is None:
                widget.value = 'None'
            else:
                widget.value = default
        self._scale_method.value = 'auto'
        self._percentile_input.value = 99.0
        self._manual_input.value = 1.0
        # Parallel/workers live in the Execution tab of the advanced
        # accordion and are reset to their safe defaults as well.
        self._parallel_check.value = False
        self._n_workers.value = 2
        # Output format resets to tiff-only (the space-saving default).
        self._checkpoint_format.value = 'tiff'

        self._clear_section('run')
        self._expand_section('run')
        self._log('run', "✅ All parameters reset to defaults.")
        # Defaults may change the estimate (fewer scale methods, etc.)
        self._mark_disk_dirty()
        self._update_disk_estimate_display()

    def _on_view_log(self, btn):
        """Load the persistent run log file into the main output.

        The log file is appended to on every run (via :meth:`_log`)
        and lives at ``{output_dir}/.exo2micro_run_log.txt``. This
        button is how users recover the log after a kernel restart —
        the in-memory widget state is gone by then, but the disk file
        persists. Only the tail (last 500 lines) is loaded to keep
        the output area responsive.
        """
        from .utils import read_run_log_tail, get_run_log_path

        self._clear_section('run')
        self._expand_section('run')

        log_path = get_run_log_path(self.output_dir)
        text = read_run_log_tail(self.output_dir, max_lines=500)

        if text is None:
            self._log('run',
                      f"No previous log found at {log_path}")
            self._log('run',
                      "The log file is written during runs and "
                      "persists across kernel restarts. It will "
                      "appear here after your first run.")
            return

        self._log('run',
                  f"📄 Loading previous log from {log_path}")
        self._log('run',
                  f"   (showing last {text.count(chr(10))} lines)")
        self._log('run', "")

        # Print the log content directly to the main output without
        # routing through _log to avoid re-appending to the file
        # (which would duplicate every line we just read).
        with self._output:
            print("═" * 72)
            print("  PREVIOUS RUN LOG (loaded from disk)")
            print("═" * 72)
            print(text)
            print("═" * 72)
            print("  END OF PREVIOUS LOG")
            print("═" * 72)

    def _on_compare(self, btn):
        """Run parameter comparison for the first selected sample+dye."""
        samples = self._get_samples()
        dyes = self._get_dyes()

        if not samples or not dyes:
            with self._output:
                clear_output()
                print("⚠️  Please enter at least one sample and one dye.")
            return

        param_name = self._compare_param.value
        values_str = self._compare_values.value.strip()
        save = self._compare_save.value

        try:
            default = DEFAULTS[param_name]
            if isinstance(default, bool):
                values = [v.strip().lower() in ('true', '1', 'yes')
                          for v in values_str.split(',')]
            elif isinstance(default, int) and not isinstance(default, bool):
                values = [int(v.strip()) for v in values_str.split(',')]
            elif isinstance(default, float):
                values = [float(v.strip()) for v in values_str.split(',')]
            elif default is None:
                # scale_percentile / manual_scale — accept float or None
                values = []
                for v in values_str.split(','):
                    v = v.strip()
                    if v.lower() == 'none':
                        values.append(None)
                    else:
                        values.append(float(v))
            else:
                values = [v.strip() for v in values_str.split(',')]
        except Exception as e:
            with self._output:
                clear_output()
                print(f"⚠️  Could not parse values: {e}")
            return

        params = self._get_params()
        checkpoint_format = self._checkpoint_format.value
        sample = samples[0]
        dye = dyes[0]

        with self._output:
            clear_output()
            print(f"📊 Comparing {param_name} = {values} "
                  f"for {sample} / {dye}\n")

            run = SampleDye(sample, dye,
                            output_dir=self.output_dir,
                            raw_dir=self.raw_dir,
                            checkpoint_format=checkpoint_format)
            if params:
                try:
                    run.set_params(**params)
                except ValueError as e:
                    print(f"  !! Parameter error: {e}")
                    return

            self._show_progress(0, len(values),
                                f'Comparing {param_name}...')
            results = run.compare(param_name, values, save=save)
            self._show_progress(len(values), len(values),
                                'Comparison complete!')

            if self._inline_preview.value:
                for r in results:
                    val = r['value']
                    result = r['result']
                    print(f"\n{'─' * 40}")
                    print(f"  {param_name} = {val}  →  "
                          f"status={result.get('status', '?')}")
                    if result.get('scale_estimate') is not None:
                        print(f"  Moffat scale = "
                              f"{result['scale_estimate']:.4f}")
                    if result.get('scale_percentile_value') is not None:
                        print(f"  Percentile scale = "
                              f"{result['scale_percentile_value']:.4f}")
                    if result.get('manual_scale') is not None:
                        print(f"  Manual scale = "
                              f"{result['manual_scale']:.4f}")

    # ──────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS — zoom panel
    # ──────────────────────────────────────────────────────────────────────

    def _on_zoom_load(self, btn):
        """Load a downsampled preview into the cache and redraw."""
        sample = self._zoom_sample.value.strip()
        dye = self._zoom_dye.value.strip()
        kind = self._zoom_kind.value
        if not sample or not dye:
            self._zoom_status.value = (
                '<span style="color:red;">Enter sample and dye first.</span>')
            return

        self._zoom_status.value = (
            f'<span style="color:#888;">Loading {kind} for '
            f'{sample}/{dye}...</span>')
        image, info = self._load_full_image(sample, dye, kind)
        if image is None:
            self._zoom_status.value = (
                f'<span style="color:red;">{info}</span>')
            return

        preview, stride = self._downsample_preview(image)
        self._preview_cache[(sample, dye, kind)] = (preview, stride)

        # Re-range sliders for the preview
        self._update_sliders_for_image(
            preview.shape, self._zoom_row, self._zoom_col, self._zoom_size)

        self._zoom_status.value = (
            f'<span style="color:green;">Loaded preview '
            f'{preview.shape[0]}×{preview.shape[1]} '
            f'(stride {stride}, full size '
            f'{image.shape[0]}×{image.shape[1]})</span>')

        self._redraw_zoom()

    def _on_zoom_change(self, change):
        """Redraw when any zoom control changes."""
        self._redraw_zoom()

    def _get_zoom_image_for_kind(self, sample, dye, kind):
        """Preview version of an image (loaded on demand)."""
        key = (sample, dye, kind)
        if key in self._preview_cache:
            return self._preview_cache[key]
        image, info = self._load_full_image(sample, dye, kind)
        if image is None:
            return None, info
        preview, stride = self._downsample_preview(image)
        self._preview_cache[key] = (preview, stride)
        return preview, stride

    def _redraw_zoom(self):
        """Render the current zoom region to the output panel."""
        sample = self._zoom_sample.value.strip()
        dye = self._zoom_dye.value.strip()
        kind = self._zoom_kind.value
        if not sample or not dye:
            return
        if (sample, dye, kind) not in self._preview_cache:
            return

        preview, stride = self._preview_cache[(sample, dye, kind)]
        row = self._zoom_row.value
        col = self._zoom_col.value
        size = self._zoom_size.value
        sigma = self._zoom_sigma.value
        fullres = self._zoom_fullres.value
        side_by_side = self._zoom_side_by_side.value

        is_diff = (kind == 'difference')

        with self._zoom_out:
            clear_output(wait=True)

            # Full-resolution crop path
            if fullres:
                if side_by_side:
                    images, labels, divs = [], [], []
                    for k in ('post', 'pre_interior', 'difference'):
                        img, info = self._load_full_image(sample, dye, k)
                        if img is None:
                            print(f"  {k}: {info}")
                            continue
                        images.append(img)
                        labels.append(k)
                        divs.append(k == 'difference')
                    if not images:
                        print("No full-res images available.")
                        return
                    full_row = row * stride
                    full_col = col * stride
                    full_size = size * stride
                    plotting.plot_zoom_multi(
                        images, labels,
                        row=full_row, col=full_col, size=full_size,
                        sigma=sigma,
                        diverging_flags=divs,
                        sample=sample, dye=dye)
                else:
                    img, info = self._load_full_image(sample, dye, kind)
                    if img is None:
                        print(info)
                        return
                    full_row = row * stride
                    full_col = col * stride
                    full_size = size * stride
                    plotting.plot_zoom(
                        img,
                        row=full_row, col=full_col, size=full_size,
                        sigma=sigma, diverging=is_diff,
                        title=f'{sample}/{dye}/{kind} (full res)')
                return

            # Preview path
            if side_by_side:
                previews, labels, divs = [], [], []
                for k in ('post', 'pre_interior', 'difference'):
                    prev, _ = self._get_zoom_image_for_kind(sample, dye, k)
                    if prev is None:
                        continue
                    previews.append(prev)
                    labels.append(k)
                    divs.append(k == 'difference')
                if not previews:
                    print("No previews available.")
                    return
                plotting.plot_zoom_multi(
                    previews, labels,
                    row=row, col=col, size=size, sigma=sigma,
                    diverging_flags=divs,
                    sample=sample, dye=dye)
            else:
                plotting.plot_zoom(
                    preview, row=row, col=col, size=size,
                    sigma=sigma, diverging=is_diff,
                    title=f'{sample}/{dye}/{kind} (preview, stride={stride})')

    def _on_zoom_save(self, btn):
        """Save the current zoom at full resolution to pipeline_output/."""
        sample = self._zoom_sample.value.strip()
        dye = self._zoom_dye.value.strip()
        kind = self._zoom_kind.value
        if not sample or not dye:
            self._zoom_status.value = (
                '<span style="color:red;">Enter sample and dye first.</span>')
            return

        preview_entry = self._preview_cache.get((sample, dye, kind))
        if preview_entry is None:
            self._zoom_status.value = (
                '<span style="color:red;">Load an image first.</span>')
            return
        _, stride = preview_entry

        # Load the full-resolution image from disk for the saved output
        image, info = self._load_full_image(sample, dye, kind)
        if image is None:
            self._zoom_status.value = (
                f'<span style="color:red;">{info}</span>')
            return

        row = self._zoom_row.value * stride
        col = self._zoom_col.value * stride
        size = self._zoom_size.value * stride
        sigma = self._zoom_sigma.value
        is_diff = (kind == 'difference')

        checks_dir = os.path.join(self.output_dir, sample, dye,
                                  'pipeline_output')
        os.makedirs(checks_dir, exist_ok=True)
        sigma_tag = f'_sig{sigma:g}' if sigma > 0 else ''
        fname = (f'zoom_{kind}_r{row}_c{col}_s{size}{sigma_tag}.png')
        save_path = os.path.join(checks_dir, fname)

        plotting.plot_zoom(
            image, row=row, col=col, size=size, sigma=sigma,
            diverging=is_diff,
            title=f'{sample}/{dye}/{kind} (full res)',
            save_path=save_path)
        self._zoom_status.value = (
            f'<span style="color:green;">Saved: {save_path}</span>')

    # ──────────────────────────────────────────────────────────────────────
    # EVENT HANDLERS — blink panel
    # ──────────────────────────────────────────────────────────────────────

    def _on_blink_load(self, btn):
        """Load both blink images (as downsampled previews)."""
        sample = self._blink_sample.value.strip()
        dye = self._blink_dye.value.strip()
        if not sample or not dye:
            self._blink_status.value = (
                '<span style="color:red;">Enter sample and dye first.</span>')
            return

        kind_a = self._blink_ref.value
        kind_b = self._blink_other.value

        img_a, info_a = self._load_full_image(sample, dye, kind_a)
        if img_a is None:
            self._blink_status.value = (
                f'<span style="color:red;">A: {info_a}</span>')
            return
        img_b, info_b = self._load_full_image(sample, dye, kind_b)
        if img_b is None:
            self._blink_status.value = (
                f'<span style="color:red;">B: {info_b}</span>')
            return

        prev_a, stride_a = self._downsample_preview(img_a)
        prev_b, stride_b = self._downsample_preview(img_b)
        # Use the coarser stride so both previews are on the same grid
        stride = max(stride_a, stride_b)
        if stride != stride_a:
            prev_a = img_a[::stride, ::stride]
        if stride != stride_b:
            prev_b = img_b[::stride, ::stride]

        self._preview_cache[(sample, dye, kind_a, 'blink')] = (prev_a, stride)
        self._preview_cache[(sample, dye, kind_b, 'blink')] = (prev_b, stride)

        shape = prev_a.shape
        self._update_sliders_for_image(
            shape, self._blink_row, self._blink_col, self._blink_size)

        self._blink_status.value = (
            f'<span style="color:green;">Loaded both previews '
            f'{shape[0]}×{shape[1]} (stride {stride})</span>')
        self._on_blink_draw(None)

    def _on_blink_toggle(self, change):
        self._on_blink_draw(None)

    def _on_blink_draw(self, change):
        """Render whichever blink image is currently selected."""
        sample = self._blink_sample.value.strip()
        dye = self._blink_dye.value.strip()
        if not sample or not dye:
            return

        kind_a = self._blink_ref.value
        kind_b = self._blink_other.value
        show_b = bool(self._blink_toggle_btn.value)
        kind = kind_b if show_b else kind_a
        label = 'B' if show_b else 'A'

        key = (sample, dye, kind, 'blink')
        entry = self._preview_cache.get(key)
        if entry is None:
            return
        preview, stride = entry

        row = self._blink_row.value
        col = self._blink_col.value
        size = self._blink_size.value

        with self._blink_out:
            clear_output(wait=True)
            plotting.plot_zoom(
                preview, row=row, col=col, size=size,
                sigma=0.0, diverging=False,
                title=f'{label}: {kind} (stride {stride})')

    # ──────────────────────────────────────────────────────────────────────
    # INLINE DISPLAY & SUMMARY
    # ──────────────────────────────────────────────────────────────────────

    def _show_inline_results(self, run, result):
        """
        Display the new stage-4 diagnostic plots inline after a run.

        Shows short captions explaining what to look for in each. All
        output (text and matplotlib figures) is routed through
        ``self._output`` via an internal context manager, so callers
        don't need to wrap the call themselves — this is how the
        previews end up in the Full Output Log section of the GUI
        regardless of which call site invokes them.
        """
        try:
            from IPython import get_ipython
            ip = get_ipython()
            if ip is not None:
                ip.run_line_magic('matplotlib', 'inline')
        except Exception:
            pass

        status = result.get('status', 'unknown')
        moffat = result.get('scale_estimate')
        sp_val = result.get('scale_percentile_value')
        ms_val = result.get('manual_scale')

        plots_to_show = [
            ('pre_post_heatmap',
             '2-D density of pre vs post pixel brightness.'),
            ('excess_heatmap',
             'Post-stain excess (upper triangle only). Brighter cells '
             'show brightness pairs where many more pixels have post > '
             'pre than the reflected post < pre. Sequential magma '
             'colormap; lower triangle is blank by construction.'),
            ('pre_post_histograms',
             'Overlapping pre and post intensity distributions.'),
            ('difference_histogram',
             'post − pre per pixel, unscaled. Positive tail = post-only '
             'excess (candidate microbes).'),
            ('ratio_histogram',
             'log₁₀(post/pre) distribution with Moffat noise fit. '
             'The orange line is the Moffat-fit scale estimate.'),
            ('difference_image',
             'Final scaled difference: post − scale × pre. Positive = '
             'post-only excess. Uses the Moffat scale.'),
        ]

        # Route ALL output (text and matplotlib figures) into the main
        # output widget. Without this wrapper, plt.show() renders to
        # whichever cell is currently capturing stdout — often NOT the
        # GUI's output widget — and the figures vanish into the
        # launching cell or nowhere at all.
        with self._output:
            print(f"\n{'━' * 60}")
            print(f"  {run.sample} / {run.dye}  —  {status}")
            if moffat is not None:
                print(f"  Moffat scale:     {moffat:.4f}")
            if sp_val is not None:
                print(f"  Percentile scale: {sp_val:.4f}")
            if ms_val is not None:
                print(f"  Manual scale:     {ms_val:.4f}")
            print(f"{'━' * 60}\n")

            for prefix, caption in plots_to_show:
                path = run._check_path(prefix)
                if not os.path.exists(path):
                    continue
                try:
                    img = plt.imread(path)
                    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
                    ax.imshow(img)
                    ax.set_title(f'{prefix}', fontsize=10)
                    ax.axis('off')
                    plt.tight_layout()
                    plt.show()
                    plt.close(fig)
                    print(f"  {caption}\n")
                except Exception as e:
                    print(f"  Could not display {prefix}: {e}")

    def _print_summary(self, results):
        """Pretty summary table for a completed run batch.

        Shows one row per (sample, dye) with scale estimates and a
        compact status indicator. Failed runs are followed by a
        "Problems" section listing each failed (sample, dye) with
        the full error message, so users with long error texts don't
        need to scroll back through mid-stream output to see what
        broke.
        """
        print(f"\n{'═' * 72}")
        print(f"  SUMMARY")
        print(f"{'═' * 72}")

        has_percentile = any(r.get('scale_percentile_value') is not None
                             for r in results)
        has_manual = any(r.get('manual_scale') is not None for r in results)

        header = f"  {'Sample':<12} {'Dye':<22} {'Moffat':>10}"
        if has_percentile:
            header += f" {'Percentile':>12}"
        if has_manual:
            header += f" {'Manual':>10}"
        header += f"  {'Status'}"
        print(header)
        print(f"  {'─' * (len(header) - 2)}")

        problems = []  # collected for the Problems section below

        for r in results:
            sample = r.get('sample', '?')
            dye = r.get('dye', '?')
            moffat = r.get('scale_estimate')
            sp_val = r.get('scale_percentile_value')
            ms_val = r.get('manual_scale')
            status = r.get('status', '?')

            if status == 'complete':
                status_icon = '✅'
                short_status = 'complete'
            elif 'error' in str(status):
                status_icon = '❌'
                short_status = 'error'
                problems.append((sample, dye, status))
            else:
                status_icon = '⚠️'
                short_status = str(status)[:30]

            line = f"  {sample:<12} {dye:<22}"
            line += (f" {moffat:>10.4f}" if moffat is not None
                     else f" {'—':>10}")
            if has_percentile:
                line += (f" {sp_val:>12.4f}" if sp_val is not None
                         else f" {'—':>12}")
            if has_manual:
                line += (f" {ms_val:>10.4f}" if ms_val is not None
                         else f" {'—':>10}")
            line += f"  {status_icon} {short_status}"
            print(line)

        if problems:
            print(f"\n{'─' * 72}")
            print(f"  PROBLEMS  ({len(problems)} failed task(s))")
            print(f"{'─' * 72}")
            for sample, dye, status in problems:
                print(f"\n  ❌ {sample} / {dye}")
                # Status is "error: <message>" — strip the prefix and
                # indent the message for readability.
                msg = str(status)
                if msg.startswith('error: '):
                    msg = msg[7:]
                for line in msg.splitlines():
                    print(f"     {line}")

    # ──────────────────────────────────────────────────────────────────────
    # DISPLAY
    # ──────────────────────────────────────────────────────────────────────

    def display(self):
        """Render the GUI in the notebook."""
        display(self._main_ui)


# ==============================================================================
# CONVENIENCE LAUNCHER
# ==============================================================================

def launch(output_dir='processed', raw_dir='raw'):
    """
    Launch the exo2micro interactive GUI in a Jupyter notebook.

    Parameters
    ----------
    output_dir : str
        Root output directory (default ``'processed'``).
    raw_dir : str
        Root raw image directory (default ``'raw'``).

    Returns
    -------
    ExoMicroGUI
        The GUI instance, useful for programmatic access to widget values.

    Example
    -------
    ::

        from exo2micro.gui import launch
        gui = launch()
    """
    gui = ExoMicroGUI(output_dir=output_dir, raw_dir=raw_dir)
    gui.display()
    return gui
