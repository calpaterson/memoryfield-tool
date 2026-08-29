import sys

if sys.version_info >= (3, 14):
    from uuid import uuid6
else:
    from uuid6 import uuid6

__all__ = ["uuid6"]
