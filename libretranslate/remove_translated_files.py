import atexit
import os
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from libretranslate.progress import job_store


def remove_translated_files(upload_dir: str):
    now = time.mktime(datetime.now().timetuple())

    # Files referenced by active jobs (running/paused) must not be deleted:
    # the worker thread is still reading or writing them.
    protected = set()
    for job in job_store.all():
        if job.status in ("running", "paused"):
            if job.source_path:
                protected.add(os.path.normcase(os.path.abspath(job.source_path)))
            if job.translated_file_path:
                protected.add(os.path.normcase(os.path.abspath(job.translated_file_path)))

    for f in os.listdir(upload_dir):
        f = os.path.join(upload_dir, f)
        if os.path.isfile(f):
            if os.path.normcase(os.path.abspath(f)) in protected:
                continue
            f_time = os.path.getmtime(f)
            if (now - f_time) > 1800:  # 30 minutes
                os.remove(f)

    # Remove stale finished jobs
    job_store.cleanup()


def setup(upload_dir):
    scheduler = BackgroundScheduler(daemon=True, timezone='UTC')
    scheduler.add_job(remove_translated_files, "interval", minutes=30, kwargs={'upload_dir': upload_dir})
    scheduler.start()

    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())
