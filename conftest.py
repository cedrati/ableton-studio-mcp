# Ensures `import ableton_studio_mcp.server` resolves no matter how pytest is invoked.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
