"""Commands whose effect Live applies on a later tick.

Setting ``song.current_song_time``, toggling a cue or loading a browser item
only shows up a tick (~100 ms) later. Handlers for such commands return a
:class:`Deferred`; it finishes by polling Live once per tick.
"""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import TIME_TOLERANCE


class Deferred(object):
    """A result that settles later on the main thread.

    ``start(resolve, reject)`` is called once, on the main thread; it must end
    by calling exactly one of the two.
    """

    def __init__(self, start):
        self.start = start


class Waiting(object):
    """Polling helpers for Deferred handlers."""

    def _playhead_at(self, target_time):
        """Whether Live reports the playhead at ``target_time``.

        A running transport keeps moving, so anything up to half a beat past
        the target counts.
        """
        now = self._song.current_song_time
        if getattr(self._song, "is_playing", False):
            return target_time - TIME_TOLERANCE <= now < target_time + 0.5
        return abs(now - target_time) < TIME_TOLERANCE

    def _poll_until(self, predicate, on_ready, on_timeout, reject, max_ticks):
        """Run ``on_ready`` once ``predicate()`` holds, checking every tick;
        give up with ``on_timeout`` after ``max_ticks`` ticks. Exceptions go
        to ``reject``."""
        def tick(remaining):
            try:
                if predicate():
                    on_ready()
                elif remaining <= 0:
                    on_timeout()
                else:
                    self.schedule_message(1, lambda: tick(remaining - 1))
            except Exception as e:
                reject(str(e))
        tick(max_ticks)
