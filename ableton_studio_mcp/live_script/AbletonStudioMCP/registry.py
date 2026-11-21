"""The table of commands the control surface answers.

Each handler is a method marked with ``@command("name")``. The protocol
parameters are passed by name to the method's arguments, so the method
signature *is* the command's contract: arguments without a default are
required, unknown parameters are rejected, and the advertised capability
list is generated from this table (it cannot drift from the code).
"""
from __future__ import absolute_import, print_function, unicode_literals

import inspect

# name -> (method name, {protocol key: argument name})
COMMANDS = {}

# Behaviours older servers need to know about, beyond command names.
FEATURES = (
    "arrangement_notes",       # note commands accept location="arrangement"
    "return_master_devices",   # track commands accept track_type="return"/"master"
    "parameter_display",       # parameters report Live's display strings
    "note_probability",        # notes keep probability / velocity deviation / release velocity
)


class CommandError(Exception):
    """A request the control surface refuses (bad or missing parameters...)."""


def command(name, **renamed):
    """Register the decorated method as the handler of command ``name``.

    ``renamed`` maps protocol keys to argument names when they differ,
    e.g. ``@command("create_locator", time="time_val")``.
    """
    def register(method):
        if name in COMMANDS:
            raise ValueError("command registered twice: " + name)
        COMMANDS[name] = (method.__name__, dict(renamed))
        return method
    return register


def capabilities():
    return sorted(COMMANDS) + list(FEATURES)


def bind_arguments(handler, name, params):
    """Turn a request's params into keyword arguments for ``handler``."""
    params = params or {}
    if not isinstance(params, dict):
        raise CommandError("'params' must be an object")
    renamed = COMMANDS[name][1]
    signature = inspect.signature(handler)
    accepted = set(signature.parameters)
    kwargs = {}
    for key, value in params.items():
        arg = renamed.get(key, key)
        if arg not in accepted:
            raise CommandError("%s does not take '%s'" % (name, key))
        kwargs[arg] = value
    missing = [arg for arg, p in signature.parameters.items()
               if p.default is inspect.Parameter.empty and arg not in kwargs
               and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    if missing:
        keys = dict((v, k) for k, v in renamed.items())
        raise CommandError("%s needs %s" % (name, ", ".join("'%s'" % keys.get(m, m) for m in missing)))
    return kwargs
