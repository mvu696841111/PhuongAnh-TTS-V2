"""
TTS Job Queue and Concurrency Management

Provides:
- Job queue for TTS requests
- Concurrency limits to prevent GPU overload
- Priority-based job scheduling
- Job status tracking
- Cancellable jobs
"""

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("PhuongAnh.JobQueue")


class JobStatus(Enum):
    """Status of a TTS job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TTSJob:
    """A TTS generation job."""
    job_id: str
    text: str
    voice_id: str
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    progress: float = 0.0
    priority: int = 0
    chunk_count: int = 0
    completed_chunks: int = 0
    progress_message: str = ""


@dataclass
class QueueConfig:
    """Configuration for the job queue."""
    max_concurrent_jobs: int = 2           # Max jobs running simultaneously
    max_queue_size: int = 100             # Max jobs waiting in queue
    job_timeout: float = 300.0            # Job timeout in seconds
    chunk_timeout: float = 60.0           # Chunk generation timeout
    enable_priority: bool = True          # Enable priority scheduling
    max_retries: int = 2                  # Max retries on failure


class TTSJobQueue:
    """
    Thread-safe job queue for TTS requests.

    Features:
    - Concurrency limiting
    - Priority-based scheduling
    - Job status tracking
    - Cancellation support
    - Result caching
    """

    def __init__(self, config: Optional[QueueConfig] = None):
        self.config = config or QueueConfig()

        # Thread-safe collections
        self._lock = threading.RLock()
        self._queue: List[TTSJob] = []
        self._running_jobs: Dict[str, TTSJob] = {}
        self._completed_jobs: Dict[str, TTSJob] = {}
        self._job_results: Dict[str, Any] = {}

        # Semaphore for concurrency control
        self._semaphore = threading.Semaphore(self.config.max_concurrent_jobs)

        # Callbacks
        self._progress_callbacks: Dict[str, Callable] = {}
        self._completion_callbacks: Dict[str, Callable] = {}

        # State
        self._is_running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Statistics
        self._stats = {
            'total_jobs': 0,
            'completed_jobs': 0,
            'failed_jobs': 0,
            'cancelled_jobs': 0,
            'cache_hits': 0,
        }

    @property
    def queue_size(self) -> int:
        """Get current queue size."""
        with self._lock:
            return len(self._queue)

    @property
    def running_count(self) -> int:
        """Get number of running jobs."""
        with self._lock:
            return len(self._running_jobs)

    @property
    def available_capacity(self) -> int:
        """Get available job slots."""
        return max(0, self.config.max_concurrent_jobs - self.running_count)

    def submit(
        self,
        text: str,
        voice_id: str = "Ly",
        priority: int = 0,
        job_id: Optional[str] = None,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
    ) -> str:
        """
        Submit a new TTS job.

        Args:
            text: Text to synthesize
            voice_id: Voice ID
            priority: Job priority (higher = more important)
            job_id: Optional custom job ID
            on_progress: Progress callback
            on_complete: Completion callback

        Returns:
            Job ID

        Raises:
            RuntimeError: If queue is full
        """
        with self._lock:
            if len(self._queue) >= self.config.max_queue_size:
                raise RuntimeError(f"Job queue is full ({self.config.max_queue_size} jobs)")

            if job_id is None:
                job_id = str(uuid.uuid4())

            job = TTSJob(
                job_id=job_id,
                text=text,
                voice_id=voice_id,
                priority=priority,
            )

            self._queue.append(job)
            self._queue.sort(key=lambda j: -j.priority)  # Higher priority first

            if on_progress:
                self._progress_callbacks[job_id] = on_progress
            if on_complete:
                self._completion_callbacks[job_id] = on_complete

            self._stats['total_jobs'] += 1

            logger.info(f"Job {job_id} submitted: voice={voice_id}, priority={priority}, queue_size={len(self._queue)}")

            return job_id

    def get_job(self, job_id: str) -> Optional[TTSJob]:
        """Get job status."""
        with self._lock:
            # Check queue
            for job in self._queue:
                if job.job_id == job_id:
                    return job

            # Check running
            if job_id in self._running_jobs:
                return self._running_jobs[job_id]

            # Check completed
            if job_id in self._completed_jobs:
                return self._completed_jobs[job_id]

            return None

    def get_result(self, job_id: str) -> Optional[Any]:
        """Get job result."""
        with self._lock:
            if job_id in self._job_results:
                self._stats['cache_hits'] += 1
                return self._job_results[job_id]
            return None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job."""
        with self._lock:
            # Check queue
            for i, job in enumerate(self._queue):
                if job.job_id == job_id:
                    job.status = JobStatus.CANCELLED
                    self._queue.pop(i)
                    self._stats['cancelled_jobs'] += 1
                    logger.info(f"Job {job_id} cancelled (was in queue)")
                    return True

            # Check running
            if job_id in self._running_jobs:
                job = self._running_jobs[job_id]
                job.status = JobStatus.CANCELLED
                self._stats['cancelled_jobs'] += 1
                logger.info(f"Job {job_id} marked for cancellation")
                return True

            return False

    def get_status(self) -> Dict[str, Any]:
        """Get queue status."""
        with self._lock:
            return {
                'queue_size': len(self._queue),
                'running_count': len(self._running_jobs),
                'max_concurrent': self.config.max_concurrent_jobs,
                'available_capacity': self.available_capacity,
                'total_jobs': self._stats['total_jobs'],
                'completed_jobs': self._stats['completed_jobs'],
                'failed_jobs': self._stats['failed_jobs'],
                'cancelled_jobs': self._stats['cancelled_jobs'],
                'cache_hits': self._stats['cache_hits'],
            }

    def clear_completed(self, older_than: float = 3600) -> int:
        """Clear completed jobs older than specified seconds."""
        with self._lock:
            now = time.time()
            to_remove = []

            for job_id, job in self._completed_jobs.items():
                if now - job.completed_at > older_than:
                    to_remove.append(job_id)

            for job_id in to_remove:
                del self._completed_jobs[job_id]
                if job_id in self._job_results:
                    del self._job_results[job_id]

            logger.info(f"Cleared {len(to_remove)} completed jobs")
            return len(to_remove)

    def start(self) -> None:
        """Start the queue worker thread."""
        if self._is_running:
            return

        self._is_running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("Job queue worker started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the queue worker."""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()

        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)

        logger.info("Job queue worker stopped")

    def _worker_loop(self) -> None:
        """Main worker loop."""
        while not self._stop_event.is_set():
            try:
                # Try to get a job
                job = self._get_next_job()

                if job is None:
                    # No jobs available, wait
                    time.sleep(0.1)
                    continue

                # Process job
                self._process_job(job)

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(1)

    def _get_next_job(self) -> Optional[TTSJob]:
        """Get next job from queue."""
        with self._lock:
            # Only get job if we have capacity
            if len(self._running_jobs) >= self.config.max_concurrent_jobs:
                return None

            # Get next priority job
            while self._queue:
                job = self._queue.pop(0)
                if job.status != JobStatus.CANCELLED:
                    return job

            return None

    def _process_job(self, job: TTSJob) -> None:
        """Process a single job."""
        with self._lock:
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
            self._running_jobs[job.job_id] = job

        logger.info(f"Processing job {job.job_id}")

        try:
            # This will be overridden by the actual TTS processor
            # For now, just mark as completed
            with self._lock:
                job.status = JobStatus.COMPLETED
                job.completed_at = time.time()
                job.progress = 1.0
                self._stats['completed_jobs'] += 1

                # Move to completed
                del self._running_jobs[job.job_id]
                self._completed_jobs[job.job_id] = job

            # Call completion callback
            if job.job_id in self._completion_callbacks:
                try:
                    self._completion_callbacks[job.job_id](job)
                except Exception as e:
                    logger.error(f"Completion callback error: {e}")

        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}")

            with self._lock:
                job.status = JobStatus.FAILED
                job.completed_at = time.time()
                job.error = str(e)
                self._stats['failed_jobs'] += 1

                # Move to completed
                if job.job_id in self._running_jobs:
                    del self._running_jobs[job.job_id]
                self._completed_jobs[job.job_id] = job


# Global queue instance
_job_queue: Optional[TTSJobQueue] = None


def get_job_queue(config: Optional[QueueConfig] = None) -> TTSJobQueue:
    """Get the global job queue instance."""
    global _job_queue
    if _job_queue is None:
        _job_queue = TTSJobQueue(config)
        _job_queue.start()
    return _job_queue


def shutdown_job_queue() -> None:
    """Shutdown the global job queue."""
    global _job_queue
    if _job_queue is not None:
        _job_queue.stop()
        _job_queue = None
