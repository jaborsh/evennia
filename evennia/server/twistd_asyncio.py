"""
Wrapper around twistd that installs the asyncio reactor.

Python 3.12+ removed the implicit creation of an event loop in the main
thread, so ``twistd --reactor=asyncio`` fails with "There is no current
event loop". This module creates one before handing off to twistd.

With the asyncio reactor running, Django detects an active event loop and
blocks synchronous ORM calls. Since Evennia's entire data layer is
synchronous, we set DJANGO_ALLOW_ASYNC_UNSAFE to permit these calls.
This is safe — the threading model is unchanged, only the underlying
event loop implementation differs.

Used by the launcher in place of the bare ``twistd`` binary.
"""

import asyncio
import os

asyncio.set_event_loop(asyncio.new_event_loop())
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

from twisted.scripts.twistd import run  # noqa: E402

if __name__ == "__main__":
    run()
