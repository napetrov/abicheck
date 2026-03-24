"""Allow ``python -m abicheck`` as an alternative entry point."""

from .cli import main  # noqa: F401 – re-exported for testability

if __name__ == "__main__":
    main()
