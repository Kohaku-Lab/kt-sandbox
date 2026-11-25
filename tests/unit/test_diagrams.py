"""The README figures: the committed SVGs match the generator, and both themes share one layout."""

import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "draw_diagrams", ROOT / "scripts" / "draw_diagrams.py"
)
draw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draw)

THEMES = (("light", draw.LIGHT), ("dark", draw.DARK))


def render(name: str, palette) -> str:
    drawer, height, title = draw.FIGURES[name]
    canvas = draw.Canvas(palette, height, title)
    drawer(canvas)
    return canvas.svg()


@pytest.mark.parametrize("name", sorted(draw.FIGURES))
@pytest.mark.parametrize("theme,palette", THEMES)
def test_the_committed_svg_matches_the_generator(name, theme, palette):
    committed = (ROOT / "docs" / "images" / f"{name}-{theme}.svg").read_text(
        encoding="utf-8"
    )
    assert committed == render(name, palette), "run: python scripts/draw_diagrams.py"


@pytest.mark.parametrize("name", sorted(draw.FIGURES))
def test_both_themes_have_the_same_shapes_and_texts_and_only_colours_differ(name):
    light, dark = (ET.fromstring(render(name, palette)) for _, palette in THEMES)
    tag = lambda element: element.tag.split("}")[1]
    assert [tag(e) for e in light.iter()] == [tag(e) for e in dark.iter()]
    assert [e.text for e in light.iter() if tag(e) == "text"] == [
        e.text for e in dark.iter() if tag(e) == "text"
    ]
    geometry = lambda root: [
        (tag(e), e.get("x"), e.get("y"), e.get("width")) for e in root.iter()
    ]
    assert geometry(light) == geometry(dark)


@pytest.mark.parametrize("name", sorted(draw.FIGURES))
@pytest.mark.parametrize("theme,palette", THEMES)
def test_every_figure_is_a_titled_image_inside_its_canvas(name, theme, palette):
    root = ET.fromstring(render(name, palette))
    assert root.get("role") == "img" and root.get("width") == str(draw.WIDTH)
    assert root.find("{http://www.w3.org/2000/svg}title").text
    height = int(root.get("height"))
    for element in root.iter("{http://www.w3.org/2000/svg}rect"):
        x, y = float(element.get("x", 0)), float(element.get("y", 0))
        assert x + float(element.get("width")) <= draw.WIDTH + 0.01
        assert y + float(element.get("height")) <= height + 0.01


def test_the_readme_embeds_every_figure_with_a_dark_source_and_alt_text():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in draw.FIGURES:
        pattern = rf'srcset="docs/images/{name}-dark\.svg".*?src="docs/images/{name}-light\.svg"[^>]*alt="[^"]{{40,}}"'
        assert re.search(pattern, readme, re.S), name
