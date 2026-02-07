import argparse
import time
import sys
from pathlib import Path

# Add project root to sys.path to allow imports
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parents[4]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from saki_runtime.sdk.reporter import JobReporter
from saki_runtime.schemas.enums import JobStatus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--events", required=True)
    args = parser.parse_args()

    reporter = JobReporter(args.events, args.job_id)
    reporter.log("Training started")

    total_epochs = 5
    total_steps = 100
    for epoch in range(1, total_epochs + 1):
        for step in range(1, total_steps + 1):
            time.sleep(0.01)
        reporter.progress(epoch=epoch, step=total_steps, total_steps=total_steps, eta_sec=0)
        loss = 1.0 / epoch
        mAP = 0.5 + (epoch * 0.1)
        reporter.metric(step=epoch, metrics={"loss": loss, "mAP": mAP}, epoch=epoch)

    artifacts_dir = Path(args.artifacts_dir)
    model_path = artifacts_dir / "best.pt"
    with open(model_path, "w") as f:
        f.write("dummy model content")

    reporter.artifact("best.pt", model_path.as_uri(), "weights")
    reporter.status(JobStatus.SUCCEEDED, JobStatus.RUNNING, "Training finished")


if __name__ == "__main__":
    main()
