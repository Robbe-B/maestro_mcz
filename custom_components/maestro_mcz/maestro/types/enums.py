"""Enum definitions for Maestro MCZ integration."""

from enum import Enum


class SensorTypeEnum(Enum):
    """Enum for sensor types."""

    BOOLEAN = "boolean"
    DOUBLE = "double"
    INT = "int"
    STRING = "string"
