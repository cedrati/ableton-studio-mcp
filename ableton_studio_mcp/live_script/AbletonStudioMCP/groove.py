"""The Groove Pool."""
from __future__ import absolute_import, print_function, unicode_literals

from .registry import command


class GrooveCommands(object):

    # ------------------------------------------------------------- grooves
    def _groove_pool(self):
        pool = getattr(self._song, "groove_pool", None)
        if pool is None:
            raise RuntimeError("This Live version has no Groove Pool API (Live 11+)")
        return pool

    @staticmethod
    def _groove_info(i, g):
        out = {"index": i, "name": str(getattr(g, "name", ""))}
        for k in ("base", "quantization_amount", "timing_amount", "random_amount", "velocity_amount"):
            try:
                out[k] = float(getattr(g, k))
            except Exception:
                pass
        return out

    @command("get_groove_pool")
    def _get_groove_pool(self):
        pool = self._groove_pool()
        grooves = list(getattr(pool, "grooves", []))
        return {"global_amount": self._safe_attr(self._song, "groove_amount", float, None),
                "grooves": [self._groove_info(i, g) for i, g in enumerate(grooves)]}

    @command("set_clip_groove")
    def _set_clip_groove(self, track_index, clip_index, groove_index, location="session"):
        """Apply a Groove Pool groove to a clip (None removes it)."""
        clip, label = self._resolve_clip(track_index, clip_index, location)
        if groove_index is None:
            clip.groove = None
            return {"clip": label, "groove": None}
        grooves = list(self._groove_pool().grooves)
        if groove_index < 0 or groove_index >= len(grooves):
            raise IndexError("Groove index out of range (%d grooves in the pool)" % len(grooves))
        clip.groove = grooves[groove_index]
        return {"clip": label, "groove": self._groove_info(groove_index, grooves[groove_index])}

    @command("set_groove_params")
    def _set_groove_params(self, groove_index=None, values=None, global_amount=None):
        """Change a groove's amounts (timing/random/velocity/quantization in
        0-100 %, base as Live's index) and/or the global Groove amount (0-1.3)."""
        out = {}
        if groove_index is not None:
            grooves = list(self._groove_pool().grooves)
            if groove_index < 0 or groove_index >= len(grooves):
                raise IndexError("Groove index out of range (%d grooves in the pool)" % len(grooves))
            g = grooves[groove_index]
            for k, v in (values or {}).items():
                if k not in ("base", "quantization_amount", "timing_amount", "random_amount", "velocity_amount"):
                    raise ValueError("Unknown groove setting '%s'" % k)
                setattr(g, k, v)
            out["groove"] = self._groove_info(groove_index, g)
        if global_amount is not None:
            self._song.groove_amount = float(global_amount)
            out["global_amount"] = float(self._song.groove_amount)
        return out
