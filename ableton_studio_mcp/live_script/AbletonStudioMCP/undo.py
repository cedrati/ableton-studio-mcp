"""Undo and redo, one assistant action at a time.

What Live does (measured in Live 12.4):

* every change a script makes is merged into one undo step until something
  closes it, so each action is wrapped in ``begin_undo_step`` /
  ``end_undo_step`` (see surface.py) or in a group;
* loading a browser item closes the open step and records its own, so an
  action that loads a device spans up to ``1 + 2 × loads`` of Live's steps.

So each action is recorded here as an *entry*. Undoing an entry that loaded
something undoes Live's steps one at a time and stops as soon as the set is
back to the fingerprint taken before the action: it never goes further back
than the action itself. Redo replays the same number of steps.

Like Cmd/Ctrl+Z, this assumes nothing else was edited meanwhile: an edit made
by hand in between is what Live undoes first.
"""
from __future__ import absolute_import, print_function, unicode_literals

import time

from .constants import UNDO_GROUP_MAX_SECONDS
from .registry import command

HISTORY_LIMIT = 200
# How many of Live's undo steps one action may span before undo gives up
# (and puts everything back). Loads and recordings split actions into
# several steps.
FINGERPRINT_MAX_STEPS = 32


class UndoCommands(object):

    # ── recording actions ───────────────────────────────────────────────────

    def _undo_lists(self):
        if not hasattr(self, "_undo_history"):
            self._undo_history, self._redo_history = [], []
        return self._undo_history, self._redo_history

    def _open_entry(self, name, fingerprint=False):
        self._song.begin_undo_step()
        self._undo_entry = {"name": name, "loads": 0,
                            "before": self._set_fingerprint() if fingerprint else None}

    def _close_entry(self):
        entry = getattr(self, "_undo_entry", None)
        if entry is None:
            return
        self._undo_entry = None
        self._song.end_undo_step()
        history, redo = self._undo_lists()
        history.append(entry)
        del history[:-HISTORY_LIMIT]
        del redo[:]          # a new change makes the redo list obsolete

    def _note_browser_load(self):
        """Called right before a browser load: it will split the current step."""
        entry = getattr(self, "_undo_entry", None)
        if entry is None:
            return
        if entry["before"] is None:
            entry["before"] = self._set_fingerprint()
        entry["loads"] += 1

    # ── state ───────────────────────────────────────────────────────────────

    def _undo_state(self):
        song = self._song
        return {"can_undo": self._safe_attr(song, "can_undo", bool, False),
                "can_redo": self._safe_attr(song, "can_redo", bool, False),
                "undo_group_open": bool(getattr(self, "_undo_group", None))}

    @command("get_undo_state")
    def _get_undo_state(self):
        return self._undo_state()

    # ── undo / redo ─────────────────────────────────────────────────────────

    def _live_step(self, action):
        song = self._song
        if not self._safe_attr(song, "can_" + action, bool, False):
            return False
        getattr(song, action)()
        return True

    def _undo_entry_steps(self, entry):
        """Undo one recorded action; return how many of Live's steps it took.

        An action with a fingerprint (every group, and any action that loaded
        a device) is undone step by step until the set matches the
        fingerprint taken before it. If that doesn't happen within
        FINGERPRINT_MAX_STEPS, every step taken is redone, so the set is
        exactly as it was, and the failure is reported: an undo never goes
        further back than the action it was asked to undo.
        """
        if entry["before"] is None:
            return 1 if self._live_step("undo") else 0
        done = 0
        for _ in range(max(1 + 2 * entry["loads"], FINGERPRINT_MAX_STEPS)):
            if not self._live_step("undo"):
                break
            done += 1
            if self._set_fingerprint() == entry["before"]:
                return done
        for _ in range(done):
            self._live_step("redo")
        raise RuntimeError("Could not undo '%s' cleanly: %d of Live's undo steps did not lead back to "
                           "the set as it was before it, so nothing was undone" % (entry["name"], done))

    def _check_steps(self, steps):
        steps = int(steps)
        if not 1 <= steps <= 50:
            raise ValueError("steps goes from 1 to 50, not %d" % steps)
        if getattr(self, "_undo_group", None):
            raise RuntimeError("An undo group is open ('%s'): end it first" % self._undo_group)
        return steps

    @command("undo")
    def _undo(self, steps=1):
        """Undo the last ``steps`` actions (an action loading devices may
        span several of Live's undo steps)."""
        history, redo = self._undo_lists()
        done = live_steps = 0
        for _ in range(self._check_steps(steps)):
            entry = history.pop() if history else {"name": None, "loads": 0, "before": None}
            try:
                taken = self._undo_entry_steps(entry)
            except RuntimeError:
                history.append(entry)       # still there: it was not undone
                raise
            if not taken:
                if entry["name"] is not None:
                    history.append(entry)
                break
            entry["taken"] = taken
            redo.append(entry)
            done += 1
            live_steps += taken
        return dict(self._undo_state(), done=done, live_steps=live_steps)

    @command("redo")
    def _redo(self, steps=1):
        history, redo = self._undo_lists()
        done = live_steps = 0
        for _ in range(self._check_steps(steps)):
            if not redo:
                taken = 1 if self._live_step("redo") else 0
                if not taken:
                    break
            else:
                entry = redo.pop()
                taken = 0
                for _ in range(entry.get("taken", 1)):
                    if not self._live_step("redo"):
                        break
                    taken += 1
                if entry["name"] is not None:
                    history.append(entry)
            done += 1
            live_steps += taken
        return dict(self._undo_state(), done=done, live_steps=live_steps)

    # ── groups ──────────────────────────────────────────────────────────────

    @command("begin_undo_group")
    def _begin_undo_group(self, name="Ableton Studio MCP"):
        """Changes until end_undo_group form one action."""
        if not hasattr(self._song, "begin_undo_step"):
            raise RuntimeError("This Live version cannot group undo steps (Live 11+)")
        if getattr(self, "_undo_group", None):
            raise RuntimeError("An undo group is already open ('%s')" % self._undo_group)
        self._open_entry(str(name), fingerprint=True)
        self._undo_group = str(name)
        self._undo_group_since = time.time()
        return self._undo_state()

    @command("end_undo_group")
    def _end_undo_group(self):
        if not getattr(self, "_undo_group", None):
            return dict(self._undo_state(), ended=False)
        name, self._undo_group = self._undo_group, None
        self._close_entry()
        return dict(self._undo_state(), ended=True, name=name)

    def _close_stale_undo_group(self):
        """A group whose end never came (the server died, the client hung up)
        must not swallow every later change into one step."""
        if getattr(self, "_undo_group", None) and \
                time.time() - getattr(self, "_undo_group_since", 0) > UNDO_GROUP_MAX_SECONDS:
            self.log_message("closing undo group '%s' left open" % self._undo_group)
            self._end_undo_group()
