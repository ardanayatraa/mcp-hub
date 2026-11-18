"""Connector types whose tools the Hub generates itself from a published contract.

``source_managed`` apps publish the contract; ``custom_api`` connections are described by the
admin as a list of endpoints, so the Hub builds the same contract from that list.
"""

MANAGED_TYPES = frozenset({"source_managed", "custom_api"})


def is_managed(connector_type: str | None) -> bool:
    return connector_type in MANAGED_TYPES
