import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import psutil
from loguru import logger

from saki_runtime.jobs.interfaces import JobRunner, PluginAdapter
from saki_runtime.jobs.workspace import Workspace


class SubprocessJobRunner(JobRunner):
    def __init__(self, plugins: Dict[str, PluginAdapter]):
        self.plugins = plugins

    async def start_train(self, workspace: Workspace, gpu_id: int) -> None:
        config = workspace.load_config()
        if not config:
            raise ValueError(f"Config not found for job {workspace.job_id}")

        plugin_id = config["plugin_id"]
        if plugin_id not in self.plugins:
            raise ValueError(f"Plugin {plugin_id} not found")
        
        plugin = self.plugins[plugin_id]
        entrypoint = plugin.trainer_entrypoint

        # Prepare command
        # Assuming entrypoint is a module if it doesn't end with .py, else script
        if entrypoint.endswith(".py"):
            cmd = [sys.executable, entrypoint]
        else:
            cmd = [sys.executable, "-m", entrypoint]

        # Add arguments
        cmd.extend([
            "--job-id", workspace.job_id,
            "--workdir", str(workspace.workdir.resolve()),
            "--config", str(workspace.config_path.resolve()),
            "--data-dir", str(workspace.data_dir.resolve()),
            "--artifacts-dir", str(workspace.artifacts_dir.resolve()),
            "--events", str(workspace.events_path.resolve()),
        ])

        # Prepare environment
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        env["PYTHONUNBUFFERED"] = "1"
        
        # Add PYTHONPATH to include current project root if needed
        # For MVP, assuming plugins are installed or in path
        
        # Redirect stdout/stderr
        stdout_path = workspace.artifacts_dir / "stdout.log"
        stderr_path = workspace.artifacts_dir / "stderr.log"
        
        stdout_f = open(stdout_path, "w")
        stderr_f = open(stderr_path, "w")

        try:
            process = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(workspace.workdir.resolve()),
                stdout=stdout_f,
                stderr=stderr_f,
                # close_fds=True # Windows doesn't support close_fds=True with std redirection easily without extra care
            )
            
            # Save PID
            pid_path = workspace.artifacts_dir / "pid.txt"
            with open(pid_path, "w") as f:
                f.write(str(process.pid))
                
            logger.info(f"Started job {workspace.job_id} (PID {process.pid}) with GPU {gpu_id}")
            
        except Exception as e:
            stdout_f.close()
            stderr_f.close()
            logger.error(f"Failed to start subprocess for job {workspace.job_id}: {e}")
            raise

    async def stop(self, job_id: str) -> None:
        # We need workspace to find pid file. 
        # But stop signature in interface is just job_id.
        # We can reconstruct workspace path from settings or pass workspace.
        # Let's assume we can get workspace from job_id using default runs dir.
        # Ideally JobManager passes workspace, but interface says job_id.
        # We'll use the same logic as JobManager to find workspace.
        from saki_runtime.core.config import settings
        workspace = Workspace(settings.RUNS_DIR, job_id)
        
        pid_path = workspace.artifacts_dir / "pid.txt"
        if not pid_path.exists():
            logger.warning(f"PID file not found for job {job_id}, assuming stopped.")
            return

        try:
            with open(pid_path, "r") as f:
                pid = int(f.read().strip())
        except ValueError:
            logger.warning(f"Invalid PID file for job {job_id}")
            return

        if not psutil.pid_exists(pid):
            logger.info(f"Process {pid} for job {job_id} already gone.")
            return

        try:
            process = psutil.Process(pid)
            process.terminate()
            
            try:
                process.wait(timeout=10)
                logger.info(f"Job {job_id} (PID {pid}) terminated gracefully.")
            except psutil.TimeoutExpired:
                logger.warning(f"Job {job_id} (PID {pid}) did not terminate, killing...")
                process.kill()
                process.wait(timeout=5)
                logger.info(f"Job {job_id} (PID {pid}) killed.")
                
        except psutil.NoSuchProcess:
            logger.info(f"Process {pid} for job {job_id} already gone.")
        except Exception as e:
            logger.error(f"Error stopping job {job_id}: {e}")

    def is_running(self, job_id: str) -> bool:
        from saki_runtime.core.config import settings
        workspace = Workspace(settings.RUNS_DIR, job_id)
        
        pid_path = workspace.artifacts_dir / "pid.txt"
        if not pid_path.exists():
            return False

        try:
            with open(pid_path, "r") as f:
                pid = int(f.read().strip())
            
            if not psutil.pid_exists(pid):
                return False
                
            # Optional: Check if it's a zombie
            p = psutil.Process(pid)
            if p.status() == psutil.STATUS_ZOMBIE:
                return False
                
            return True
        except Exception:
            return False
