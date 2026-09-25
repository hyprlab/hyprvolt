"""A field of a kind the core doesn't know."""
from hyprvolt.manifest import EntityType, Field, Module

module = Module(id="badfield", name="Bad field", types=(
    EntityType("oddity", "Oddity", "Oddities", fields=(Field("x", "X", kind="hologram"),)),
))
