from __future__ import annotations


SERIF_FONTS = [
    "Times New Roman",
    "Times",
    "Nimbus Roman",
    "Liberation Serif",
    "DejaVu Serif",
]


def configure_matplotlib(matplotlib) -> None:
    matplotlib.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.family": "serif",
            "font.serif": SERIF_FONTS,
            "mathtext.fontset": "stix",
        }
    )
