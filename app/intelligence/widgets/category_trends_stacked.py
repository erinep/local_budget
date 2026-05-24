"""Monthly breakdown stacked bar widget.

Reuses CategoryTrendsVM from category_trends; renders as a stacked bar.
"""

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.intelligence.widgets.category_trends import build_category_trends

REGISTRY["category_trends_stacked"] = WidgetDef(
    key="category_trends_stacked",
    assembler=build_category_trends,
    template="intelligence/widgets/category_trends_stacked.html",
)
