"""Worker entry point for the demo detection plugin.

Invoked by saki-executor as a subprocess using this plugin's virtualenv Python.
"""

from saki_plugin_sdk.ipc.worker import run_worker
from saki_plugin_demo_det.plugin import DemoDetectionPlugin


def main() -> None:
    run_worker(DemoDetectionPlugin())


if __name__ == "__main__":
    main()
