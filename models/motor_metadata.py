"""General motor information (identity, dimensions, masses, free text).

Internal units are fixed: millimetres for lengths and grams for masses.
Conversions to other units are handled by :mod:`models.units` and by the
file services (for instance the ENG format stores masses in kilograms).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Common propellant families offered in the property editor.
PROPELLANT_TYPES: tuple[str, ...] = (
    "Black powder",
    "APCP (Ammonium perchlorate composite)",
    "KNSU (Potassium nitrate / sucrose)",
    "KNDX (Potassium nitrate / dextrose)",
    "KNSB (Potassium nitrate / sorbitol)",
    "Hybrid",
    "Liquid",
    "Other",
)


@dataclass
class MotorMetadata:
    """Descriptive and physical properties of a rocket motor.

    Attributes:
        name: Motor name (used as the ENG motor code, e.g. ``C6``).
        manufacturer: Manufacturer name or abbreviation.
        designation: Full commercial designation (e.g. ``C6-5``).
        diameter_mm: Casing outside diameter in millimetres.
        length_mm: Casing length in millimetres.
        delays: Ejection delays as ENG text (``"3-5-7"``, ``"P"`` = plugged,
            ``"0"`` = none).
        propellant_mass_g: Propellant mass in grams.
        casing_mass_g: Empty casing mass in grams (optional).
        nozzle_closure_mass_g: Nozzle and closure mass in grams (optional).
        declared_total_mass_g: Total loaded mass declared by a source file
            (ENG) when the component masses are unknown.
        propellant_type: Propellant family.
        description: Free description.
        comments: Free user comments.
        eng_comments: Comment lines read from an ENG file (without the
            leading ``;``), kept so that a round trip never loses them.
        source_file: Original file the motor was imported from, if any.
        created: ISO-8601 creation timestamp.
        modified: ISO-8601 last modification timestamp.
        extra: Additional key/value information (kept in the XML project).
    """

    name: str = ""
    manufacturer: str = ""
    designation: str = ""
    diameter_mm: Optional[float] = None
    length_mm: Optional[float] = None
    delays: str = "0"
    propellant_mass_g: Optional[float] = None
    casing_mass_g: Optional[float] = None
    nozzle_closure_mass_g: Optional[float] = None
    declared_total_mass_g: Optional[float] = None
    propellant_type: str = ""
    description: str = ""
    comments: str = ""
    eng_comments: list[str] = field(default_factory=list)
    source_file: str = ""
    created: str = ""
    modified: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Mass handling
    # ------------------------------------------------------------------
    def has_component_masses(self) -> bool:
        """Return True when the casing or nozzle/closure mass is known.

        In that case the total mass is computed from the components;
        otherwise the declared total mass (for example read from an ENG
        file) is used.
        """
        return self.casing_mass_g is not None or self.nozzle_closure_mass_g is not None

    @property
    def total_mass_g(self) -> Optional[float]:
        """Total loaded motor mass in grams.

        Computed as propellant + casing + nozzle/closure when at least one
        component mass is known, otherwise the declared total mass.
        """
        if self.has_component_masses():
            return (
                (self.propellant_mass_g or 0.0)
                + (self.casing_mass_g or 0.0)
                + (self.nozzle_closure_mass_g or 0.0)
            )
        return self.declared_total_mass_g

    @property
    def empty_mass_g(self) -> Optional[float]:
        """Burnt-out motor mass in grams (total minus propellant)."""
        total = self.total_mass_g
        if total is None or self.propellant_mass_g is None:
            return None
        return total - self.propellant_mass_g

    def delay_list(self) -> list[str]:
        """Return the individual delay tokens (``"3-5-7"`` -> ``[3, 5, 7]``)."""
        return [token for token in self.delays.replace(",", "-").split("-") if token]
