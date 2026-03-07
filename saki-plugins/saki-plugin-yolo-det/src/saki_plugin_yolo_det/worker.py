"""Entry point for the YOLO Detection plugin worker process.

Launched by the executor via the plugin.yml ``entrypoint`` field::

    saki_plugin_yolo_det.worker:main
"""

from saki_plugin_sdk.ipc.worker import run_worker
from saki_plugin_yolo_det.plugin import YoloDetectionPlugin


def main() -> None:
    run_worker(YoloDetectionPlugin())


if __name__ == "__main__":
    main()
