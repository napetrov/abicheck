"""abicheck — ABI compatibility checker."""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("abicheck")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"  # running from source without install

