"""Clock trust, used to correct readings taken before NTP set the time.

piw has no battery backed clock. After a power cut it restores the time that
systemd-timesyncd last recorded, then depends on NTP to correct itself. Any
reading taken in between carries a wall clock timestamp that can be hours wrong.

CLOCK_BOOTTIME counts real elapsed time since boot and never steps, whatever
NTP does to the wall clock, so it recovers the true time of those readings.
"""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# systemd-timesyncd creates this file the first time it synchronises the clock.
# It lives in a tmpfs, so it is absent again after every boot.
SYNC_MARKER = Path("/run/systemd/timesync/synchronized")

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def clock_is_synced() -> bool:
    """Report whether NTP has set the system clock since this boot."""
    return SYNC_MARKER.exists()


def monotonic_ns() -> int:
    """Return nanoseconds since boot, from a clock that never steps."""
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def boot_id() -> str:
    """Return the kernel identifier for the current boot.

    The identifier ties a reading to the monotonic clock that produced it,
    because that clock restarts at zero on every boot.
    """
    try:
        return BOOT_ID_PATH.read_text().strip()
    except OSError:
        logger.warning("[Weather Client] Could not read the boot id", exc_info=True)
        return ""
