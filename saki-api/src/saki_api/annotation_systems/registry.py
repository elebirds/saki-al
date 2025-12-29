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
    Registry for annotation system handlers.
    
    Handlers can be registered either via decorator or manually.
    The registry is a singleton that manages all available handlers.
    
    Example:
        # Using decorator
        @register_handler
        class FedoHandler(AnnotationSystemHandler):
            system_type = AnnotationSystemType.FEDO
            ...
        
        # Manual registration
        registry = HandlerRegistry.get_instance()
        registry.register(FedoHandler)
        
        # Getting a handler
        handler = registry.get_handler(AnnotationSystemType.FEDO)
    """

    _instance: Optional["HandlerRegistry"] = None
    _handlers: Dict[AnnotationSystemType, Type[AnnotationSystemHandler]] = {}
    _handler_instances: Dict[AnnotationSystemType, AnnotationSystemHandler] = {}

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
        """
        Register a handler class.
        
        Args:
            handler_class: The handler class to register
            
        Returns:
            The handler class (for use as decorator)
        """
        if not hasattr(handler_class, 'system_type'):
            raise ValueError(
                f"Handler class {handler_class.__name__} must define 'system_type' class attribute"
            )

        system_type = handler_class.system_type
        self._handlers[system_type] = handler_class
        logger.info(f"Registered handler: {handler_class.__name__} for {system_type.value}")
        return handler_class

    def get_handler(
            self,
            system_type: AnnotationSystemType,
            cached: bool = True,
    ) -> AnnotationSystemHandler:
        """
        Get a handler instance for the given system type.
        
        Args:
            system_type: The annotation system type
            cached: Whether to return a cached instance (default True)
            
        Returns:
            Handler instance
            
        Raises:
            ValueError: If no handler is registered for the system type
        """
        if system_type not in self._handlers:
            raise ValueError(f"No handler registered for system type: {system_type.value}")

        if cached and system_type in self._handler_instances:
            return self._handler_instances[system_type]

        handler_class = self._handlers[system_type]
        handler = handler_class()

        if cached:
            self._handler_instances[system_type] = handler

        return handler

    def has_handler(self, system_type: AnnotationSystemType) -> bool:
        """Check if a handler is registered for the given system type."""
        return system_type in self._handlers

    def list_handlers(self) -> Dict[str, str]:
        """List all registered handlers."""
        return {
            st.value: hc.__name__
            for st, hc in self._handlers.items()
        }

    def clear(self) -> None:
        """Clear all registered handlers (mainly for testing)."""
        self._handlers.clear()
        self._handler_instances.clear()


def register_handler(cls: Type[AnnotationSystemHandler]) -> Type[AnnotationSystemHandler]:
    """
    Decorator to register a handler class.
    
    Example:
        @register_handler
        class FedoHandler(AnnotationSystemHandler):
            system_type = AnnotationSystemType.FEDO
            ...
    """
    registry = HandlerRegistry.get_instance()
    return registry.register(cls)


def get_handler(system_type: AnnotationSystemType) -> AnnotationSystemHandler:
    """
    Convenience function to get a handler for a system type.
    
    Args:
        system_type: The annotation system type
        
    Returns:
        Handler instance
    """
    registry = HandlerRegistry.get_instance()
    return registry.get_handler(system_type)


def discover_handlers() -> None:
    """
    Discover and load all handler modules.
    This imports handler modules to trigger registration.
    """
    handler_modules = [
        "annotation_systems.handlers.classic",
        "annotation_systems.satellite_fedo.handler",
    ]

    for module_name in handler_modules:
        try:
            importlib.import_module(module_name)
            logger.info(f"Loaded handler module: {module_name}")
        except ImportError as e:
            logger.warning(f"Could not load handler module {module_name}: {e}")
