"""
defaults.py
===========
Central registry of all pipeline parameters, their default values, and the
short abbreviations used in checkpoint filenames.

When a parameter is set to its default value, it is omitted from filenames
entirely. Only non-default values appear, keeping names concise for typical
runs.

Pipeline stages
---------------
1. Padding            — load raw images onto a common padded canvas
2. Boundary alignment — phase correlation + ICP on tissue boundary
3. Interior alignment — SIFT feature matching on tissue interior
4. Diagnostics        — diagnostic plots, scale estimation, difference image

Stage 4 always generates the five diagnostic plots and a difference image
using the Moffat-fit scale estimate. When ``scale_percentile`` or
``manual_scale`` are set, stage 4 additionally computes difference images
for those alternative scales and overplots them on the excess heatmap.
"""

from collections import OrderedDict


# Each entry: (default_value, abbreviation, stage_number, description)
# stage_number determines which checkpoint file this parameter affects.
PARAMETER_REGISTRY = OrderedDict([
    # ── Stage 1: Padding ──────────────────────────────────────────────────
    ('pad',                    (2000,  'pad',   1,
     'Zero-padding pixels added on each side before registration')),

    # ── Stage 2: Boundary correlation + ICP ───────────────────────────────
    ('use_edges',              (True,  'ue',    2,
     'Focus coarse pass on tissue boundary rings')),
    ('boundary_width',         (15,    'bw',    2,
     'Boundary ring thickness in pixels at coarse resolution')),
    ('boundary_smooth',        (10,    'bs',    2,
     'Gaussian softening sigma on the boundary ring')),
    ('rotation_search',        (True,  'rs',    2,
     'Search over rotations in the coarse pass')),
    ('angle_range',            (20,    'ar',    2,
     'Rotation search range: +/- degrees')),
    ('angle_step',             (1,     'astep', 2,
     'Rotation search step size in degrees')),
    ('scale_search',           (True,  'ss',    2,
     'Search over isotropic scale factors in coarse pass')),
    ('scale_min',              (0.85,  'smin',  2,
     'Minimum scale factor to search')),
    ('scale_max',              (1.15,  'smax',  2,
     'Maximum scale factor to search')),
    ('scale_step',             (0.05,  'sstep', 2,
     'Scale search step size')),
    ('multiscale',             (True,  'ms',    2,
     'Run boundary correlation coarse pass before ICP')),
    ('down_scale',             (0.3,   'ds',    2,
     'Downsample factor for alignment visualization')),
    ('max_translation',        (200,   'mtr',   2,
     'Maximum allowed ICP translation in pixels')),
    ('max_rotation',           (5.0,   'mrot',  2,
     'Maximum allowed ICP rotation in degrees')),
    ('max_scale_delta',        (0.2,   'msd',   2,
     'Maximum deviation of scale_x or scale_y from 1.0')),
    ('max_scale_diff',         (0.15,  'msdf',  2,
     'Maximum allowed absolute difference between scale_x and scale_y')),
    ('save_all_intermediates', (False, 'sai',   2,
     'Save all alignment intermediates (coarse, ICP) for diagnosis')),

    # ── Stage 2.5 (optional): Fine ECC refinement ─────────────────────────
    # These parameters control the optional fine ECC pass that runs
    # after ICP when fine_ecc=True. Grouped separately in the GUI as
    # "Stage 2.5 — Fine ECC (optional)" since most users don't touch
    # them and the ECC pass is off by default. Technically these are
    # stage 2 parameters; the 2.5 grouping is purely for GUI display.
    ('fine_ecc',               (False, 'fecc',  2,
     'Enable an optional fine-grained ECC homography refinement in '
     'stage 2 after the boundary correlation + ICP pass. Off by '
     'default — most runs do not need it.')),
    ('stopit',                 (500,   'sit',   2,
     'Maximum ECC iterations for the fine_ecc pass. Only used when '
     'fine_ecc=True.')),
    ('stopdelta',              (1e-6,  'sdl',   2,
     'ECC convergence threshold for the fine_ecc pass. Only used '
     'when fine_ecc=True.')),

    # ── Stage 3: Interior SIFT alignment ──────────────────────────────────
    ('interior_ecc',           (True,  'iecc',  3,
     'Enable interior SIFT refinement after ICP')),
    ('interior_blur_base',     (8.0,   'iblur', 3,
     'Gaussian blur sigma applied before SIFT feature detection')),
    ('interior_max_correction', (500,  'imc',   3,
     'Max allowed total correction from SIFT matching (full-res px)')),
    ('interior_min_inlier_ratio', (0.4, 'imir', 3,
     'Minimum RANSAC inlier ratio to accept interior alignment')),

    # ── Stage 4: Diagnostics & subtraction ────────────────────────────────
    ('scale_percentile',       (None,  'sp',    4,
     'If set (float, e.g. 99.1), compute an additional difference image '
     'using this percentile of the log10(post/pre) distribution as the '
     'scale factor. None = use only the Moffat fit.')),
    ('manual_scale',           (None,  'msc',   4,
     'If set (float), compute an additional difference image using this '
     'exact scale factor (user override). None = use only the Moffat fit.')),
])


# ── Derived lookup tables ─────────────────────────────────────────────────

# {param_name: default_value}
DEFAULTS = OrderedDict(
    (k, v[0]) for k, v in PARAMETER_REGISTRY.items()
)

# {param_name: abbreviation}
ABBREVIATIONS = OrderedDict(
    (k, v[1]) for k, v in PARAMETER_REGISTRY.items()
)

# {abbreviation: param_name}  (reverse lookup)
ABBREV_TO_PARAM = OrderedDict(
    (v[1], k) for k, v in PARAMETER_REGISTRY.items()
)

# {param_name: stage_number}
PARAM_STAGES = OrderedDict(
    (k, v[2]) for k, v in PARAMETER_REGISTRY.items()
)

# {param_name: display_group_label}
# Separate from PARAM_STAGES because the GUI groups some parameters
# into sub-stages (e.g., "Stage 2.5 — Fine ECC (optional)") that
# don't correspond to real pipeline stages. PARAM_STAGES remains
# the source of truth for checkpoint paths, filename suffixes, and
# _has_checkpoint lookups; PARAM_GROUPS is cosmetic only.
PARAM_GROUPS = OrderedDict()
for _name, (_default, _abbrev, _stage, _desc) in PARAMETER_REGISTRY.items():
    if _name in ('fine_ecc', 'stopit', 'stopdelta'):
        PARAM_GROUPS[_name] = 'Stage 2.5 — Fine ECC (optional)'
    elif _stage == 1:
        PARAM_GROUPS[_name] = 'Stage 1 — Padding'
    elif _stage == 2:
        PARAM_GROUPS[_name] = 'Stage 2 — Boundary + ICP'
    elif _stage == 3:
        PARAM_GROUPS[_name] = 'Stage 3 — Interior SIFT'
    elif _stage == 4:
        PARAM_GROUPS[_name] = 'Stage 4 — Diagnostics & subtraction'
    else:
        PARAM_GROUPS[_name] = f'Stage {_stage}'
del _name, _default, _abbrev, _stage, _desc

# {param_name: description}
PARAM_DESCRIPTIONS = OrderedDict(
    (k, v[3]) for k, v in PARAMETER_REGISTRY.items()
)

# Stage names for directory/file naming
STAGE_NAMES = {
    1: '01_padded',
    2: '02_icp_aligned',
    3: '03_interior_aligned',
    4: '04_difference',
}

# Maximum stage number in the current pipeline
MAX_STAGE = 4

# Parameters that affect each stage
STAGE_PARAMS = {}
for _param, _stage in PARAM_STAGES.items():
    STAGE_PARAMS.setdefault(_stage, []).append(_param)


def build_suffix(params, stage):
    """
    Build the non-default parameter suffix for a checkpoint filename.

    Only parameters relevant to the given stage (and all upstream stages)
    that differ from their defaults are included.

    Parameters
    ----------
    params : dict
        Current parameter values (keys must match PARAMETER_REGISTRY names).
    stage : int
        Pipeline stage number (1-4).

    Returns
    -------
    str
        Suffix string like '_bw20_bs15', or '' if all relevant params are
        at their defaults.
    """
    parts = []
    for param_name, (default, abbrev, param_stage, _desc) in PARAMETER_REGISTRY.items():
        if param_stage > stage:
            continue
        current = params.get(param_name, default)
        if current != default:
            if current is None:
                val_str = 'none'
            elif isinstance(current, bool):
                val_str = '1' if current else '0'
            elif isinstance(current, float):
                val_str = f'{current:g}'
            else:
                val_str = str(current)
            parts.append(f'{abbrev}{val_str}')
    return '_' + '_'.join(parts) if parts else ''


def params_from_suffix(suffix):
    """
    Parse a filename suffix back into a dict of non-default parameter values.

    Parameters
    ----------
    suffix : str
        The suffix portion of a filename, e.g. '_bw20_bs15'.

    Returns
    -------
    dict
        Parameter names and their parsed values.
    """
    if not suffix or suffix == '':
        return {}

    result = {}
    parts = suffix.lstrip('_').split('_')
    for part in parts:
        if not part:
            continue
        # Find the longest matching abbreviation prefix
        matched_abbrev = None
        matched_val = None
        for abbrev in sorted(ABBREV_TO_PARAM.keys(), key=len, reverse=True):
            if part.startswith(abbrev):
                matched_abbrev = abbrev
                matched_val = part[len(abbrev):]
                break
        if matched_abbrev is None:
            continue

        param_name = ABBREV_TO_PARAM[matched_abbrev]
        default = DEFAULTS[param_name]

        # Parse value to match default type
        if matched_val == 'none':
            result[param_name] = None
        elif isinstance(default, bool):
            result[param_name] = matched_val == '1'
        elif isinstance(default, int):
            try:
                result[param_name] = int(matched_val)
            except ValueError:
                result[param_name] = float(matched_val)
        elif isinstance(default, float):
            result[param_name] = float(matched_val)
        elif default is None:
            # Optional params whose default is None but take floats when set
            # (scale_percentile, manual_scale).
            try:
                result[param_name] = float(matched_val)
            except ValueError:
                result[param_name] = matched_val
        else:
            result[param_name] = matched_val

    return result
