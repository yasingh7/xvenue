"""M1 compiler: parse RDSL and check cross-venue settlement relations.

The grammar lives in ``compiler/RDSL.md``. Importing this package does not
load Z3; the solver is used only by :mod:`xvenue.relate`.
"""

from xvenue.parser import parse_path, parse_rdsl
from xvenue.spec import Rel, ResolutionSpec

__all__ = ["Rel", "ResolutionSpec", "parse_path", "parse_rdsl", "__version__"]
__version__ = "0.1.0"
