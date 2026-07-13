"""Single source of truth for the CRMA ladder (Python side).

The ladder is a sequence of *cognitive postures*, not actions: CRMA
characterises a risk state and the analytical posture warranted by the
evidence. It does not prescribe a response — action stays with national DRM.
This is why the 4th rung is `Review` ("escalate for senior/organisational
review"), not the old `Actionable_Risk`, and why the action node was deleted
from the engine.

Mirrors `CRMA_STATES` / `TRAFFIC_LIGHT` in `drought_bn_ibf_v1.jl`. Import from
here rather than re-declaring the literals — the previous copy-paste of the
ladder into each script is exactly what let `Actionable_Risk` drift out of sync
with the engine (a latent KeyError at plot time).
"""
from __future__ import annotations

# Increasing-concern order. Index 3 was `Actionable_Risk` before the
# risk-cognition reconciliation.
CRMA_STATES: list[str] = ["Monitor", "Evaluate", "Assess", "Review"]

TRAFFIC_LIGHT: dict[str, str] = {
    "Monitor":  "Green",
    "Evaluate": "Yellow",
    "Assess":   "Orange",
    "Review":   "Red",
}

# Short labels for plot titles / compact tables.
CRMA_ABBREV: dict[str, str] = {
    "Monitor":  "Mon",
    "Evaluate": "Eva",
    "Assess":   "Ass",
    "Review":   "Rev",
}
