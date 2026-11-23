"""Enum definitions for Maestro MCZ integration."""

from enum import Enum


class SensorTypeEnum(Enum):
    """Identify service control-value types when matching model configurations."""

    BOOLEAN = "boolean"
    DOUBLE = "double"
    INT = "int"
    STRING = "string"
