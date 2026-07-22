"""ForgeAgent: a lightweight code-as-action agent.

The model expresses actions as Python programs delivered through a vendor-agnostic
text protocol; the agent executes them and feeds results back until the task is done.
"""

from .http_config import HttpServiceConfig
from .http_server import create_http_server
from .http_task_service import TaskService

__all__ = ["HttpServiceConfig", "TaskService", "create_http_server"]
__version__ = "0.1.0"
