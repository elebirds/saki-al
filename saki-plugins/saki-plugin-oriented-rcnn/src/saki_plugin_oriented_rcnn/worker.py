"""Oriented R-CNN 插件 worker 入口。"""

from saki_plugin_sdk.ipc.worker import run_worker
from saki_plugin_oriented_rcnn.plugin import OrientedRCNNPlugin


def main() -> None:
    run_worker(OrientedRCNNPlugin())


if __name__ == "__main__":
    main()
