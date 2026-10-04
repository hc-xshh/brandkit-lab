"""brandkit — brand source page -> measured facts -> frozen design kit.

Dependency-free (standard library only). The pipeline is:

``measure``  ->  ``drafter``  ->  ``assemble_kit``  ->  ``apply``

and each arrow is a file on disk, so every stage can be inspected, diffed and
re-run on its own. See ``README.md`` for the honest description of which stage
is real and which one is a seam.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
