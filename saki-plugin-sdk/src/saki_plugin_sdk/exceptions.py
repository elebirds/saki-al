"""插件 SDK 异常层次结构。

提供清晰的异常类型用于错误处理和调试。
"""


class PluginError(Exception):
    """插件系统基础异常。

    所有插件相关异常的基类。
    """
    pass


class PluginConfigError(PluginError):
    """配置相关错误。

    当配置解析、验证或访问失败时抛出。
    """
    pass


class PluginValidationError(PluginConfigError):
    """配置验证失败。

    当配置值不符合 schema 约束时抛出。
    """
    pass


class PluginLifecycleError(PluginError):
    """生命周期钩子执行失败。

    当 on_load, on_start, on_stop, on_unload 钩子抛出异常时包装此异常。
    """
    pass
