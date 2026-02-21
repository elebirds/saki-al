from __future__ import annotations

from pathlib import Path

from saki_kernel_sdk import KernelBase


class ExampleTrainKernel(KernelBase):
    def execute(self) -> None:
        output_dir = self.workspace / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 这里仅写入占位产物，真实 kernel 需替换为训练逻辑。
        model_file = output_dir / "best.pt"
        model_file.write_bytes(b"placeholder-model")

        self.metric(step=1, epoch=1, metrics={"train/loss": 0.123, "train/mAP50": 0.456})
        self.progress(epoch=1, step=1, total_steps=1, eta_sec=0)
        self.artifact_local_ready(file_path=str(model_file), kind="model", required=True)


if __name__ == "__main__":
    kernel = ExampleTrainKernel(
        control_uri="ipc:///var/run/saki-agent/dev.ctl.sock",
        event_uri="ipc:///var/run/saki-agent/dev.evt.sock",
        workspace=str(Path.cwd()),
        payload={},
    )
    raise SystemExit(kernel.run())
