"""
Annotation system handlers.

Each handler manages the complete lifecycle for an annotation system:
- Upload & processing
- Annotation sync (real-time)
- Batch save
"""

from .classic import ClassicHandler
from .fedo import FedoHandler

__all__ = ['ClassicHandler', 'FedoHandler']
