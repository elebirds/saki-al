import argparse
import time
import sys
from pathlib import Path

# Add project root to sys.path to allow imports
# This is needed because we run this script as __main__ but it imports from saki_runtime
current_dir = Path(__file__).resolve().parent
# src/saki_runtime/plugins/builtin/yolo_det_v1 -> src
# parents[0] = yolo_det_v1
# parents[1] = builtin
# parents[2] = plugins
# parents[3] = saki_runtime
# parents[4] = src
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
    
    # Simulate training process
    print(f"Starting training for job {args.job_id}")
    reporter.log("Starting training process...")
    
    # Simulate epochs
    total_epochs = 5
    for epoch in range(1, total_epochs + 1):
        time.sleep(1) # Simulate work
        
        # Log progress
        progress = (epoch / total_epochs) * 100
        reporter.progress(progress, f"Epoch {epoch}/{total_epochs}")
        
        # Log metrics
        loss = 1.0 / epoch
        mAP = 0.5 + (epoch * 0.1)
        reporter.metric(
            step=epoch,
            metrics={"loss": loss, "mAP": mAP},
            epoch=epoch
        )
        
        print(f"Epoch {epoch}: loss={loss:.4f}, mAP={mAP:.4f}")

    # Create dummy artifact
    artifacts_dir = Path(args.artifacts_dir)
    model_path = artifacts_dir / "best.pt"
    with open(model_path, "w") as f:
        f.write("dummy model content")
        
    reporter.artifact("best.pt", model_path.as_uri(), "model")
    
    reporter.log("Training completed successfully.")
    
    # Final status update is handled by JobManager based on process exit code?
    # Or should the runner report success?
    # The prompt says: "job succeeded/failed：由训练子进程通过 SDK 写入 status event"
    reporter.status(JobStatus.SUCCEEDED, JobStatus.RUNNING, "Training finished")

if __name__ == "__main__":
    main()
