"""eccodes isn't guaranteed thread-safe: the first GitHub run aborted (exit 134) with four
worker threads decoding at once. Every eccodes call goes through this lock; downloads,
resampling and PNG encoding stay parallel."""
import threading

LOCK = threading.Lock()
