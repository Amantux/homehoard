"""Visible severity labels for the shipped HomeHoard Lovelace card.

The card (``custom_components/homehoard/homehoard-card.js``) is a dependency-free
vanilla JS custom element -- no ES modules, no build step -- so its rendered
output is pinned here at the source level:

* the plain-language severity mapping stays inlined (the card must stay
  dependency-free, so it cannot import the frontend util module),
* every colored status renders a visible text label through that mapping, and
* the colored chips keep their color classes,
* the status is mirrored into a polite live region (visually hidden) so screen
  readers announce it -- the dot is otherwise color-only.
"""

from pathlib import Path

CARD_PATH = (
    Path(__file__).resolve().parents[2] / "custom_components" / "homehoard" / "homehoard-card.js"
)


def _card_source() -> str:
    return CARD_PATH.read_text(encoding="utf-8")


def test_card_keeps_colored_chip_classes() -> None:
    """Colored chips/dots keep their color classes -- color is not the only signal."""
    src = _card_source()
    # The warning badge (overdue) and the online dot keep their color classes.
    assert ".badge.warn" in src
    assert ".dot.on" in src


def test_card_renders_visible_severity_labels() -> None:
    """Status text is a visible plain-language label, not a bare token / color-only."""
    src = _card_source()
    # The dependency-free plain-language severity mapping + lookup are inlined.
    assert "const SEVERITY_LABELS" in src
    assert "function severityLabel" in src
    # The colored overdue badge renders the mapped plain-language label as text.
    assert 'class="badge warn">${severityLabel("overdue")}' in src
    # The online dot renders a visible label span beside the colored dot.
    assert 'id="dot_label"' in src


def test_card_announces_status_via_polite_live_region() -> None:
    """The colored dot is not spoken on its own: a polite live region carries it."""
    src = _card_source()
    # The visually hidden polite live region exists in the built DOM.
    assert 'id="live_status"' in src
    assert 'aria-live="polite"' in src
    assert ".visually-hidden" in src
    # The update path fills the region with the spoken status, once it changes.
    assert "live.textContent = statusLine" in src
    assert "live.textContent !== statusLine" in src
