"""
Generic registry mixin for handler registration.

Provides common registration and retrieval methods that can be inherited
by specific registry classes (ProcessorRegistry, SyncHandlerRegistry, etc.).

Each registry class should implement its own singleton pattern (__new__, get_instance)
and inherit these methods for common functionality.
"""

import logging
from typing import Dict, Type

from saki_api.core.exceptions import NotFoundAppException
from saki_api.models.enums import DatasetType

logger = logging.getLogger(__name__)


class HandlerRegistryMixin:
    """
    Mixin class providing common handler registration methods.

    This class provides the core registration and retrieval logic
    that is shared between different handler registries.

    To use this mixin:
        class ProcessorRegistry(HandlerRegistryMixin):
            _instance: Optional["ProcessorRegistry"] = None
            _handlers: Dict[DatasetType, Type[BaseDatasetProcessor]] = {}
            _cached_instances: Dict[DatasetType, BaseDatasetProcessor] = {}

            def __new__(cls):
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                return cls._instance

            @classmethod
            def get_instance(cls) -> "ProcessorRegistry":
                if cls._instance is None:
                    cls._instance = cls()
                return cls._instance
    """

    def register(self, handler_class: Type[object]) -> Type[object]:
        """
        Register a handler class.

        Args:
            handler_class: Handler class to register

        Returns:
            The handler class (for decorator usage)

        Raises:
            ValueError: If handler class doesn't define 'system_type'
        """
        if not hasattr(handler_class, 'system_type'):
            raise ValueError(f"Handler {handler_class.__name__} must define 'system_type'")

        system_type = handler_class.system_type
        # Use type(self) to access class attributes when called as class method
        if not hasattr(self, '_handlers'):
            self._handlers = {}
        self._handlers[system_type] = handler_class
        logger.info(f"Registered handler: {handler_class.__name__} for {system_type.value}")
        return handler_class

    def get(self, system_type: DatasetType, cached: bool = True) -> object:
        """
        Get a handler instance for the given dataset type.

        Args:
            system_type: The dataset type
            cached: Whether to return cached instance (default True)

        Returns:
            Handler instance

        Raises:
            NotFoundAppException: If no handler registered for the dataset type
        """
        # Use type(self) to access class attributes when called as class method
        if not hasattr(self, '_handlers'):
            self._handlers = {}
        if not hasattr(self, '_cached_instances'):
            self._cached_instances = {}

        if system_type not in self._handlers:
            raise NotFoundAppException(f"No handler for dataset type: {system_type.value}")

        if cached and system_type in self._cached_instances:
            return self._cached_instances[system_type]

        handler_class = self._handlers[system_type]
        handler = handler_class()
        if cached:
            self._cached_instances[system_type] = handler
        return handler

    def has(self, system_type: DatasetType) -> bool:
        """Check if a handler is registered."""
        if not hasattr(self, '_handlers'):
            self._handlers = {}
        return system_type in self._handlers

    def list_all(self) -> Dict[str, str]:
        """List all registered handlers."""
        if not hasattr(self, '_handlers'):
            self._handlers = {}
        return {st.value: hc.__name__ for st, hc in self._handlers.items()}
