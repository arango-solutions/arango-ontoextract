"""Gold-standard dataset loaders for the extraction benchmark."""

from . import hitl_regression
from .base import GoldDocument

__all__ = ["GoldDocument", "hitl_regression"]
