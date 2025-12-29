"""
Handler registry for annotation system handlers.
Provides automatic registration and retrieval of handlers.
"""

import importlib
import logging
from typing import Dict, Optional, Type

from saki_api.models.enums import AnnotationSystemType
from .base import AnnotationSystemHandler

logger = logging.getLogger(__name__)


class HandlerRegistry:
    """
    Singleton registry for annotation system handlers.
    
    Handlers can be registered via decorator or manually.
    
    Example:
        @register_handler
        class FedoHandler(AnnotationSystemHandler):
            system_type = AnnotationSystemType.FEDO
            ...
        
        # Getting a handler
        handler = get_handler(AnnotationSystemType.FEDO)
    """

    _instance: Optional["HandlerRegistry"] = None
    _handlers: Dict[AnnotationSystemType, Type[AnnotationSystemHandler]] = {}
    _cached_instances: Dict[AnnotationSystemType, AnnotationSystemHandler] = {}

    def __new__(cls) -> "HandlerRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "HandlerRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, handler_class: Type[AnnotationSystemHandler]) -> Type[AnnotationSystemHandler]:
        """Register a handler class."""
        if not hasattr(handler_class, 'system_type'):
            raise ValueError(f"Handler {handler_class.__name__} must define 'system_type'")

        system_type = handler_class.system_type
        self._handlers[system_type] = handler_class
        logger.info(f"Registered handler: {handler_class.__name__} for {system_type.value}")
        return handler_class

    def get(self, system_type: AnnotationSystemType, cached: bool = True) -> AnnotationSystemHandler:
        """
        Get a handler instance for the given system type.
        
        Args:
            system_type: The annotation system type
            cached: Whether to return cached instance (default True)
            
        Returns:
            Handler instance
            
        Raises:
            ValueError: If no handler registered for the system type
        """
        if system_type not in self._handlers:
            raise ValueError(f"No handler for system type: {system_type.value}")

        if cached and system_type in self._cached_instances:
            return self._cached_instances[system_type]

        handler = self._handlers[system_type]()
        if cached:
            self._cached_instances[system_type] = handler
        return handler

    def has(self, system_type: AnnotationSystemType) -> bool:
        """Check if a handler is registered."""
        return system_type in self._handlers

    def list_all(self) -> Dict[str, str]:
        """List all registered handlers."""
        return {st.value: hc.__name__ for st, hc in self._handlers.items()}


# ============================================================================
# Module-level convenience functions
# ============================================================================

def register_handler(cls: Type[AnnotationSystemHandler]) -> Type[AnnotationSystemHandler]:
    """Decorator to register a handler class."""
    return HandlerRegistry.get_instance().register(cls)


def get_handler(system_type: AnnotationSystemType) -> AnnotationSystemHandler:
    """Get a handler instance for a system type."""
    return HandlerRegistry.get_instance().get(system_type)


def discover_handlers() -> None:
    """
    Import all handler modules to trigger registration.
    Call during application startup.
    """
    handler_modules = [
        "saki_api.annotation_systems.handlers.classic",
        "saki_api.annotation_systems.handlers.fedo",
    ]

    for module_name in handler_modules:
        try:
            importlib.import_module(module_name)
            logger.info(f"Loaded handler: {module_name}")
        except ImportError as e:
            logger.warning(f"Could not load handler {module_name}: {e}")
