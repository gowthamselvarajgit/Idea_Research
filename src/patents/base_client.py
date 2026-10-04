"""Base contract for patent data provider clients."""

from abc import ABC, abstractmethod


class PatentClientError(Exception):
    """Base exception for patent client errors."""
    pass


class BasePatentClient(ABC):
    """Abstract base class defining the contract for patent provider clients."""

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Search patent provider for candidate patents matching a query.

        Args:
            query: Domain topic or keyword search query.
            max_results: Maximum number of raw records to retrieve.

        Returns:
            list[dict]: List of raw provider response dictionaries.

        Raises:
            PatentClientError: On missing credentials, network failure, or bad response.
        """
        pass
