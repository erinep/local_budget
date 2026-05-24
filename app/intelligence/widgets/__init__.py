"""Widget registry for the Intelligence Layer dashboard (ADR-0039).

Each widget module registers itself by calling:
    REGISTRY[key] = WidgetDef(key=key, assembler=fn, template="intelligence/widgets/<key>.html")

Importing app.intelligence.widgets.monthly_totals (etc.) populates the registry.
The route layer imports widget modules once at startup to trigger registration.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class WidgetDef:
    key: str
    assembler: Callable
    template: str


REGISTRY: dict[str, WidgetDef] = {}
