"""Allow ``python -m abicheck`` as an alternative entry point."""

from .cli import main

if __name__ == "__main__":
    main()
