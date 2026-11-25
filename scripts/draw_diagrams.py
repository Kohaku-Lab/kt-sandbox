"""Draw the README figures as light and dark SVGs from one layout.

    python scripts/draw_diagrams.py

writes ``docs/images/<figure>-light.svg`` and ``<figure>-dark.svg``. The README
embeds each pair with a ``<picture>`` element.
"""

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
FONT = "-apple-system, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
WIDTH = 830


@dataclass(frozen=True)
class Palette:
    """The colours of one theme; every figure uses names, never raw colours."""

    bg: str
    panel: str
    border: str
    text: str
    muted: str
    gray: str
    gray_fill: str
    blue: str
    blue_fill: str
    teal: str
    teal_fill: str
    orange: str
    orange_fill: str
    yellow: str
    yellow_fill: str


LIGHT = Palette(
    bg="#ffffff",
    panel="#f6f8fa",
    border="#d1d9e0",
    text="#1f2328",
    muted="#59636e",
    gray="#818b98",
    gray_fill="#eaeef2",
    blue="#0969da",
    blue_fill="#a5d4ff",
    teal="#1b7c83",
    teal_fill="#a6e0e3",
    orange="#bc4c00",
    orange_fill="#ffc999",
    yellow="#9a6700",
    yellow_fill="#ffe27a",
)
DARK = Palette(
    bg="#0d1117",
    panel="#161b22",
    border="#3d444d",
    text="#e6edf3",
    muted="#9198a1",
    gray="#6e7681",
    gray_fill="#21262d",
    blue="#4493f8",
    blue_fill="#1d4b99",
    teal="#39c5cf",
    teal_fill="#14555a",
    orange="#f0883e",
    orange_fill="#6b3a14",
    yellow="#d29922",
    yellow_fill="#6b4e0a",
)
ARROW_COLOURS = ("blue", "teal", "orange", "yellow", "gray")


class Canvas:
    """Collects SVG elements for one figure in one theme."""

    def __init__(self, palette: Palette, height: int, title: str):
        self.p = palette
        self.height = height
        self.title = title
        self.parts: list[str] = []

    def colour(self, name: str) -> str:
        return getattr(self.p, name)

    def rect(self, x, y, w, h, fill="panel", stroke="border", rx=4, dash=False):
        dashed = ' stroke-dasharray="5 4"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{self.colour(fill)}" stroke="{self.colour(stroke)}" stroke-width="1"{dashed}/>'
        )

    def text(
        self,
        x,
        y,
        content,
        *,
        size=12,
        fill="text",
        weight=None,
        anchor="start",
        mono=False,
    ):
        family = MONO if mono else FONT
        bold = f' font-weight="{weight}"' if weight else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}"{bold} '
            f'fill="{self.colour(fill)}" text-anchor="{anchor}" xml:space="preserve">{escape(content)}</text>'
        )

    def line(self, x1, y1, x2, y2, stroke="border", dash=False):
        dashed = ' stroke-dasharray="5 4"' if dash else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{self.colour(stroke)}" stroke-width="1"{dashed}/>'
        )

    def arrow(self, x1, y1, x2, y2, colour="gray", both=False):
        start = f' marker-start="url(#h{colour[0]})"' if both else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{self.colour(colour)}" '
            f'stroke-width="1.5" marker-end="url(#h{colour[0]})"{start}/>'
        )

    def box(self, x, y, w, h, colour, lines, *, fill=None, mono_lines=0):
        """A filled box with a bold first line, plain lines, and optional monospace lines last."""
        self.rect(x, y, w, h, fill or f"{colour}_fill", colour, rx=5)
        top = y + (h - 18 * len(lines)) / 2 + 13
        first_mono = len(lines) - mono_lines
        for index, content in enumerate(lines):
            mono = index >= first_mono
            self.text(
                x + w / 2,
                top + index * 18,
                content,
                size=11 if mono else (13 if index == 0 else 12),
                weight="600" if index == 0 else None,
                fill="muted" if mono else "text",
                anchor="middle",
                mono=mono,
            )

    def panel(self, x, y, w, h, heading, colour="text", note=None):
        self.rect(x, y, w, h, "panel", "border")
        self.text(x + 14, y + 22, heading, size=14, weight="600", fill=colour)
        if note:
            self.text(x + w - 14, y + 22, note, fill="muted", anchor="end")

    def svg(self) -> str:
        markers = "".join(
            f'<marker id="h{name[0]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" '
            f'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{self.colour(name)}"/></marker>'
            for name in ARROW_COLOURS
        )
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{self.height}" '
            f'viewBox="0 0 {WIDTH} {self.height}" role="img">\n<title>{escape(self.title)}</title>\n'
            f"<defs>{markers}</defs>\n"
            f'<rect width="{WIDTH}" height="{self.height}" fill="{self.p.bg}"/>\n{body}\n</svg>\n'
        )


def architecture(c: Canvas) -> None:
    """Clients, the sandbox container, the egress proxy, and the manager under them."""
    c.panel(16, 10, 220, 300, "who talks to it")
    c.box(
        32,
        48,
        188,
        96,
        "blue",
        ["KohakuTerrarium agent", "or any MCP client", "mcp_servers: sandbox-lab"],
    )
    c.box(32, 180, 188, 96, "teal", ["you", "kt-sandbox connect", "a real terminal"])

    c.panel(305, 10, 250, 300, "sandbox container", "orange", "persistent")
    c.box(
        321,
        48,
        218,
        96,
        "orange",
        ["kt-sandbox-mcp", "bash · read · write · multi_edit", "glob · grep · tree"],
    )
    c.box(
        321,
        180,
        218,
        96,
        "gray",
        ["shell · /work · your tools", "files and packages", "stay between calls"],
        fill="gray_fill",
    )
    c.text(
        321,
        298,
        "limits: command time, output, CPU, memory, processes",
        fill="muted",
        size=11,
    )

    c.panel(624, 10, 190, 300, "standard level", "yellow", "optional")
    c.box(
        640,
        48,
        158,
        84,
        "gray",
        ["allowed hosts", "pypi.org · github.com", "and the ones you add"],
        fill="gray_fill",
    )
    c.box(
        640,
        180,
        158,
        96,
        "yellow",
        ["egress proxy", "a credential per sandbox", "DNS and caps here"],
    )

    c.arrow(220, 96, 321, 96, "blue")
    c.text(270, 86, "MCP", anchor="middle", fill="blue", weight="600")
    c.arrow(220, 228, 321, 228, "teal", both=True)
    c.text(270, 218, "terminal", anchor="middle", fill="teal", weight="600")
    c.arrow(555, 228, 640, 228, "yellow")
    c.text(597, 214, "own", anchor="middle", fill="yellow", weight="600")
    c.text(597, 246, "network", anchor="middle", fill="yellow", weight="600")
    c.arrow(719, 180, 719, 132, "yellow")

    c.panel(16, 346, 798, 120, "kt-sandbox manager", "text", "the CLI; talks to Docker")
    boxes = [
        ("up · down · rm · ls", "open a sandbox at a level"),
        ("save · images", "docker commit, any level later"),
        ("build", "slim · data · render · dev"),
        ("mcp · doctor · levels", "config and checks"),
    ]
    for index, (title, sub) in enumerate(boxes):
        c.box(32 + index * 194, 380, 178, 70, "blue", [title, sub], fill="panel")
    c.arrow(430, 346, 430, 310, "gray")
    c.text(
        440, 332, "Docker API: create with the level's settings", fill="muted", size=11
    )


def workflow(c: Canvas) -> None:
    """State flows from an open setup through a saved image; the level changes at the save."""
    c.panel(16, 10, 798, 322, "set it up open, lock it down later")
    c.text(30, 92, "state", fill="muted", weight="600")
    c.text(30, 108, "(in the image)", fill="muted", size=11)
    c.text(30, 232, "policy", fill="muted", weight="600")
    c.text(30, 248, "(the level)", fill="muted", size=11)

    xs = [150, 316, 482, 648]
    steps = [
        ("gray", ["base image", "python, curl, sudo", "kt-sandbox build"]),
        (
            "orange",
            [
                "your setup",
                "packages, files, dotfiles",
                "up lab --level open",
                "connect lab",
            ],
        ),
        ("blue", ["saved image", "lab-image", "save lab lab-image"]),
        (
            "blue",
            [
                "same state",
                "in a new sandbox",
                "up bot --level strict",
                "--from lab-image",
            ],
        ),
    ]
    for x, (colour, lines) in zip(xs, steps):
        mono = 1 if len(lines) == 3 else 2
        c.box(
            x,
            48,
            150,
            104,
            colour,
            lines,
            fill="gray_fill" if colour == "gray" else None,
            mono_lines=mono,
        )
    for left, right in zip(xs, xs[1:]):
        c.arrow(left + 150, 100, right, 100, "gray")

    c.line(474, 36, 474, 296, "border", dash=True)
    c.text(474, 30, "save", anchor="middle", fill="muted", size=11)

    c.rect(150, 192, 316, 88, "orange_fill", "orange", rx=5)
    c.text(308, 220, "open", size=13, weight="600", anchor="middle")
    c.text(308, 240, "network · sudo · 2 CPUs · 300 s a command", anchor="middle")
    c.text(
        308, 260, "to install and try things", anchor="middle", fill="muted", size=11
    )
    c.rect(482, 192, 316, 88, "teal_fill", "teal", rx=5)
    c.text(640, 220, "strict", size=13, weight="600", anchor="middle")
    c.text(640, 240, "no network · no sudo · 0.5 CPU · 15 s a command", anchor="middle")
    c.text(
        640,
        260,
        "for an agent anyone can steer",
        anchor="middle",
        fill="muted",
        size=11,
    )

    c.text(
        30,
        316,
        "The level is set when a sandbox is created; to change it, save and open the image as a new sandbox.",
        fill="muted",
        size=11,
    )


FIGURES = {
    "architecture": (
        architecture,
        482,
        "kt-sandbox: clients, a sandbox container with an MCP server inside, the egress proxy and the manager",
    ),
    "workflow": (
        workflow,
        342,
        "Set a sandbox up with everything open, save it, and reopen the same state locked down",
    ),
}


def main() -> None:
    """Write every figure in both themes."""
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (draw, height, title) in FIGURES.items():
        for theme, palette in (("light", LIGHT), ("dark", DARK)):
            canvas = Canvas(palette, height, title)
            draw(canvas)
            (OUT / f"{name}-{theme}.svg").write_text(canvas.svg(), encoding="utf-8")
            print(f"wrote docs/images/{name}-{theme}.svg")


if __name__ == "__main__":
    main()
