"""Color scheme and styling for LENS TUI."""

from __future__ import annotations

from textual.theme import Theme

# LENS color palette
COLORS = {
    "background": "#000000",
    "surface": "#0a0a0a",
    "panel": "#111111",
    "border": "#222222",
    "text": "#e8e8e8",
    "text_dim": "#666666",
    "accent": "#f59e0b",
    "accent_dim": "#92600a",
    "positive": "#22c55e",
    "negative": "#ef4444",
    "neutral": "#94a3b8",
    "header": "#1a1a1a",
    "selection": "#1c2a1c",
    "cursor": "#f59e0b",
}

LENS_THEME = Theme(
    name="lens",
    primary="#f59e0b",
    secondary="#94a3b8",
    accent="#f59e0b",
    background="#000000",
    surface="#0a0a0a",
    panel="#111111",
    boost="#222222",
    warning="#f59e0b",
    error="#ef4444",
    success="#22c55e",
    foreground="#e8e8e8",
    dark=True,
    variables={
        "text-muted": "#666666",
        "border": "#222222",
        "border-bright": "#333333",
        "link-color": "#f59e0b",
        "scrollbar-color": "#333333",
        "scrollbar-color-hover": "#555555",
        "scrollbar-background": "#000000",
        "input-cursor-foreground": "#000000",
        "input-cursor-background": "#f59e0b",
        "block-cursor-foreground": "#000000",
        "block-cursor-background": "#f59e0b",
        "block-cursor-text-style": "bold",
        "footer-key-foreground": "#f59e0b",
        "footer-background": "#0a0a0a",
    },
)

LENS_CSS = """
Screen {
    background: #000000;
    color: #e8e8e8;
}

Header {
    background: #0a0a0a;
    color: #f59e0b;
    text-style: bold;
    border-bottom: solid #222222;
}

Footer {
    background: #0a0a0a;
    color: #666666;
    border-top: solid #222222;
}

.panel {
    background: #0a0a0a;
    border: solid #222222;
    padding: 0 1;
}

.panel--title {
    color: #f59e0b;
    text-style: bold;
    background: #0a0a0a;
    padding: 0 1;
    border-bottom: solid #222222;
}

.positive {
    color: #22c55e;
}

.negative {
    color: #ef4444;
}

.accent {
    color: #f59e0b;
}

.dim {
    color: #666666;
}

.text {
    color: #e8e8e8;
}

DataTable {
    background: #000000;
    color: #e8e8e8;
}

DataTable > .datatable--header {
    background: #111111;
    color: #f59e0b;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1a1a00;
    color: #f59e0b;
}

DataTable > .datatable--hover {
    background: #0d0d00;
}

DataTable > .datatable--even-row {
    background: #050505;
}

Input {
    background: #111111;
    border: solid #333333;
    color: #e8e8e8;
}

Input:focus {
    border: solid #f59e0b;
}

Select {
    background: #111111;
    border: solid #333333;
    color: #e8e8e8;
}

Button {
    background: #222222;
    color: #e8e8e8;
    border: solid #333333;
}

Button:hover {
    background: #333333;
}

Button.-primary {
    background: #92600a;
    color: #f59e0b;
    border: solid #f59e0b;
}

Button.-primary:hover {
    background: #b07a14;
}

Tabs {
    background: #0a0a0a;
    border-bottom: solid #222222;
}

Tab {
    color: #666666;
}

Tab.-active {
    color: #f59e0b;
    border-bottom: solid #f59e0b;
}

Label {
    color: #e8e8e8;
}

.label-dim {
    color: #666666;
}

.label-accent {
    color: #f59e0b;
}

.price-positive {
    color: #22c55e;
    text-style: bold;
}

.price-negative {
    color: #ef4444;
    text-style: bold;
}

.price-neutral {
    color: #e8e8e8;
    text-style: bold;
}

LoadingIndicator {
    background: #000000;
    color: #f59e0b;
}

ProgressBar {
    color: #f59e0b;
    background: #222222;
}

Tooltip {
    background: #111111;
    color: #e8e8e8;
    border: solid #333333;
}

Switch.-on {
    background: #22c55e;
}
"""
