"""Every MCP tool, grouped by what it works on.

Importing this package registers all tools with the MCP application
(``ableton_studio_mcp.app.mcp``); the names below are re-exported so code and
tests can call a tool as ``tools.<name>``.
"""

from .session import *      # noqa: F401,F403
from .tracks import *       # noqa: F401,F403
from .clips import *        # noqa: F401,F403
from .devices import *      # noqa: F401,F403
from .browser import *      # noqa: F401,F403
from .routing import *      # noqa: F401,F403
from .listening import *    # noqa: F401,F403
from .midi import *         # noqa: F401,F403
from .theory import *       # noqa: F401,F403
from .drums import *        # noqa: F401,F403
from .evolution import *    # noqa: F401,F403
from .sound import *        # noqa: F401,F403
