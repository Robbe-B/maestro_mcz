"""Keep Cloud communication and its response formats in one package.

The provider owns live communication for one stove. The controller owns the
account's HTTP session, while the saved-report client replays the same formats.
These are Cloud-specific operations, not a contract that BLE must implement.
"""
