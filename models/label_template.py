"""Label template data model (pure data, no rendering).

The renderer lives in :mod:`services.label_service`. A template is fully
serialisable to a dictionary so it can be stored as JSON (template library)
or inside the XML project file.
"""

from __future__ import annotations

from localization import N_

from dataclasses import asdict, dataclass, field, fields
from typing import Any

#: Fields that can be printed automatically on a label, in default order.
LABEL_FIELDS: tuple[str, ...] = (
    "motor_name",
    "manufacturer",
    "designation",
    "diameter",
    "length",
    "total_impulse",
    "average_thrust",
    "maximum_thrust",
    "burn_time",
    "propellant_mass",
    "total_mass",
    "propellant_type",
    "delays",
    "impulse_class",
)

#: Human-readable captions for each label field.
LABEL_FIELD_CAPTIONS: dict[str, str] = {
    "motor_name": N_("Motor name"),
    "manufacturer": N_("Manufacturer"),
    "designation": N_("Designation"),
    "diameter": N_("Diameter"),
    "length": N_("Length"),
    "total_impulse": N_("Total impulse"),
    "average_thrust": N_("Average thrust"),
    "maximum_thrust": N_("Maximum thrust"),
    "burn_time": N_("Burn time"),
    "propellant_mass": N_("Propellant mass"),
    "total_mass": N_("Total mass"),
    "propellant_type": N_("Propellant"),
    "delays": N_("Delays"),
    "impulse_class": N_("Impulse class"),
}

#: Supported layouts.
LABEL_LAYOUTS: tuple[str, ...] = ("stacked", "two_columns", "banner")

#: Supported paper formats (width, height in mm, portrait).
PAPER_FORMATS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "A6": (105.0, 148.0),
}


@dataclass
class LabelTemplate:
    """All the visual parameters of a motor label.

    Dimensions are in millimetres, font sizes in points, colours as
    ``#RRGGBB`` strings.
    """

    name: str = "Classic"
    width_mm: float = 90.0
    height_mm: float = 30.0
    paper_format: str = "A4"
    page_margin_mm: float = 10.0
    label_spacing_mm: float = 3.0
    inner_margin_mm: float = 2.0
    copies: int = 1
    fill_page: bool = False
    background_color: str = "#FFFFFF"
    text_color: str = "#111111"
    accent_color: str = "#1F4E79"
    border_color: str = "#1F4E79"
    border_width_mm: float = 0.5
    border_radius_mm: float = 1.5
    font_family: str = "Arial"
    title_font_size: float = 14.0
    body_font_size: float = 8.0
    bold_title: bool = True
    alignment: str = "left"  # left | center | right
    layout: str = "stacked"
    title_field: str = "designation"
    fields: list[str] = field(
        default_factory=lambda: [
            "manufacturer",
            "total_impulse",
            "average_thrust",
            "maximum_thrust",
            "burn_time",
            "total_mass",
        ]
    )
    show_captions: bool = True
    custom_text: str = ""
    logo_path: str = ""
    logo_x_mm: float = 70.0
    logo_y_mm: float = 3.0
    logo_width_mm: float = 17.0
    logo_height_mm: float = 17.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary of the template."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabelTemplate":
        """Build a template from a dictionary, ignoring unknown keys and
        coercing values to the declared types so that hand-edited or older
        files cannot inject wrong types."""
        template = cls()
        for spec in fields(cls):
            if spec.name not in data:
                continue
            value = data[spec.name]
            default = getattr(template, spec.name)
            try:
                if isinstance(default, bool):
                    value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
                elif isinstance(default, int):
                    value = int(float(value))
                elif isinstance(default, float):
                    value = float(value)
                elif isinstance(default, list):
                    value = [str(item) for item in value if str(item) in LABEL_FIELDS]
                else:
                    value = str(value)
            except (TypeError, ValueError):
                continue
            setattr(template, spec.name, value)
        if template.layout not in LABEL_LAYOUTS:
            template.layout = "stacked"
        if template.alignment not in ("left", "center", "right"):
            template.alignment = "left"
        if template.paper_format not in PAPER_FORMATS:
            template.paper_format = "A4"
        return template
