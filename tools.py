"""
Function calling tools for Gemini.
These functions can be invoked by the AI during conversations.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_service_status() -> str:
    """
    Get the current status of all monitored services.
    
    Returns:
        JSON string containing service statuses.
    """
    logger.info("Tool called: get_service_status()")
    
    # Hardcoded status as per requirements
    status = {
        "server_1": "online",
        "database": "online",
        "uptime": "99%"
    }
    
    result = json.dumps(status, ensure_ascii=False)
    logger.debug(f"Service status: {result}")
    return result


def set_reminder(text: str) -> str:
    """
    Set a reminder with the given text.
    
    Args:
        text: The reminder text to set.
        
    Returns:
        "Success" if the reminder was set successfully.
    """
    logger.info(f"Tool called: set_reminder(text={text!r})")
    
    # Print to console as per requirements
    print(f"Reminder set: {text}")
    
    return "Success"


# Tool definitions for Gemini API
# These follow the function declaration format expected by Gemini
TOOL_DEFINITIONS = [
    {
        "name": "get_service_status",
        "description": "Get the current status of all monitored services including servers and database. Use this when the user asks about service health, server status, or system uptime.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder with the given text. Use this when the user wants to be reminded about something.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The reminder text describing what the user wants to be reminded about."
                }
            },
            "required": ["text"]
        }
    }
]


# Mapping of function names to actual callables
TOOL_FUNCTIONS: dict[str, callable] = {
    "get_service_status": get_service_status,
    "set_reminder": set_reminder,
}


def execute_tool(name: str, args: dict[str, Any]) -> str:
    """
    Execute a tool by name with the given arguments.
    
    Args:
        name: The name of the tool to execute.
        args: Dictionary of arguments to pass to the tool.
        
    Returns:
        The result of the tool execution as a string.
        
    Raises:
        ValueError: If the tool name is not recognized.
    """
    if name not in TOOL_FUNCTIONS:
        error_msg = f"Unknown tool: {name}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    func = TOOL_FUNCTIONS[name]
    logger.debug(f"Executing tool {name} with args: {args}")
    
    try:
        result = func(**args)
        logger.debug(f"Tool {name} returned: {result}")
        return result
    except Exception as e:
        error_msg = f"Tool {name} failed: {e}"
        logger.error(error_msg)
        return json.dumps({"error": str(e)})
