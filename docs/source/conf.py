# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

project = 'exo2micro'
copyright = '2026'
author = 'Kate Follette'
release = '2.4.0'
version = '2.4'

html_logo = "Exo2Micro_logo.png"
html_favicon = "Exo2Micro_logo.png"

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx.ext.todo',
]

# Napoleon settings (NumPy-style docstrings)
napoleon_google_docstrings = False
napoleon_numpy_docstrings = True
napoleon_include_init_with_doc = True

# TODO directives render as visible boxes in the built HTML so placeholders
# (GitHub URL, example plot PNGs) are obvious.
todo_include_todos = True

templates_path = ['_templates']
exclude_patterns = []

html_theme = 'sphinx_rtd_theme'
#html_static_path = ['_static']
html_title = 'exo2micro 2.3 documentation'

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'scipy': ('https://docs.scipy.org/doc/scipy/', None),
    'matplotlib': ('https://matplotlib.org/stable/', None),
}
