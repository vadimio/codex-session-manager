from session_actions import Actions
from session_history import History
from session_inventory import Inventory


class SessionManager(Inventory, History, Actions):
    """Inventory, conversation reading, and explicit session mutations."""
