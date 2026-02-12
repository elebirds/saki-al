"""
Dataset processor implementations.

This package contains concrete implementations of BaseDatasetProcessor
for different dataset types.
"""

from saki_api.modules.annotation.extensions.dataset_processing.processors.classic import ClassicProcessor
from saki_api.modules.annotation.extensions.dataset_processing.processors.fedo import FedoProcessor

__all__ = [
    "ClassicProcessor",
    "FedoProcessor",
]
