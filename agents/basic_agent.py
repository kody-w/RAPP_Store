"""
BasicAgent - Base class for all RAPP Store agents

All agents inherit from this class and implement the perform() method.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BasicAgent(ABC):
    """
    Abstract base class for RAPP agents.

    All agents must:
    1. Set self.name (string identifier)
    2. Set self.metadata (dict with name, description, parameters schema)
    3. Implement perform(**kwargs) method
    """

    def __init__(self, name: str, metadata: Dict[str, Any]):
        """
        Initialize the agent.

        Args:
            name: Agent identifier
            metadata: Dict containing:
                - name: Agent name
                - description: What the agent does
                - parameters: JSON Schema for function calling
        """
        self.name = name
        self.metadata = metadata

    @abstractmethod
    def perform(self, **kwargs) -> str:
        """
        Execute the agent's primary function.

        Args:
            **kwargs: Parameters as defined in metadata['parameters']

        Returns:
            str: Result of the operation
        """
        pass

    def get_function_definition(self) -> Dict[str, Any]:
        """
        Get the OpenAI function definition for this agent.

        Returns:
            Dict compatible with OpenAI function calling API
        """
        return {
            "name": self.metadata.get("name", self.name),
            "description": self.metadata.get("description", ""),
            "parameters": self.metadata.get("parameters", {
                "type": "object",
                "properties": {},
                "required": []
            })
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"
