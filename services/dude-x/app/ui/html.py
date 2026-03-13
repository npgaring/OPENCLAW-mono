"""Shared HTML UI helpers for DUDE-X pages."""

from __future__ import annotations

from typing import Iterable, Mapping


BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  color-scheme: light;
  --bg: #0f172a;
  --bg-soft: #111b34;
  --panel: #121a2b;
  --panel-border: rgba(148, 163, 184, 0.25);
  --text: #e2e8f0;
  --text-muted: #94a3b8;
  --accent: #38bdf8;
  --accent-strong: #0ea5e9;
  --accent-glow: rgba(56, 189, 248, 0.18);
  --success: #22c55e;
  --warning: #f59e0b;
  --shadow: 0 20px 60px rgba(15, 23, 42, 0.45);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  font-family: 'Space Grotesk', system-ui, -apple-system, sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top, rgba(56, 189, 248, 0.18), transparent 55%),
    radial-gradient(circle at 20% 80%, rgba(34, 197, 94, 0.12), transparent 50%),
    var(--bg);
}

.page {
  max-width: 980px;
  margin: 0 auto;
  padding: 64px 24px 88px;
}

.card {
  background: linear-gradient(180deg, rgba(18, 26, 43, 0.95), rgba(15, 23, 42, 0.92));
  border: 1px solid var(--panel-border);
  border-radius: 22px;
  padding: 40px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.24em;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

h1 {
  margin: 16px 0 12px;
  font-size: clamp(28px, 4vw, 42px);
  line-height: 1.1;
}

p {
  margin: 0 0 16px;
  color: var(--text-muted);
  font-size: 16px;
}

.meta {
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  color: var(--text-muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-weight: 600;
  font-size: 14px;
  text-decoration: none;
  transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}

.btn.primary {
  background: linear-gradient(135deg, var(--accent), var(--accent-strong));
  color: #0b1220;
  box-shadow: 0 12px 24px var(--accent-glow);
}

.btn.secondary {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text);
  border-color: rgba(148, 163, 184, 0.3);
}

.btn.ghost {
  background: transparent;
  color: var(--text-muted);
  border-color: rgba(148, 163, 184, 0.2);
}

.btn:hover {
  transform: translateY(-1px);
}

.divider {
  margin: 24px 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.3), transparent);
}

@media (max-width: 700px) {
  .card {
    padding: 28px;
  }
}
"""


def render_page(
    *,
    title: str,
    eyebrow: str,
    heading: str,
    description: str,
    actions: Iterable[Mapping[str, str]] | None = None,
    meta: str | None = None,
) -> str:
    actions_html = ""
    if actions:
        buttons = []
        for action in actions:
            label = action["label"]
            href = action["href"]
            kind = action.get("kind", "secondary")
            buttons.append(f"<a class='btn {kind}' href='{href}'>{label}</a>")
        actions_html = "<div class='actions'>" + "".join(buttons) + "</div>"

    meta_html = f"<div class='meta'>{meta}</div>" if meta else ""

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>{BASE_CSS}</style>
  </head>
  <body>
    <main class="page">
      <section class="card">
        <div class="eyebrow">{eyebrow}</div>
        <h1>{heading}</h1>
        <p>{description}</p>
        {actions_html}
        <div class="divider"></div>
        {meta_html}
      </section>
    </main>
  </body>
</html>
"""
