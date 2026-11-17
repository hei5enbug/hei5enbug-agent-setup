"""Render sitemap.xml."""

from __future__ import annotations

from .pages import Page

BASE_URL = "https://docs.example.com"


def render(pages: list[Page]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in pages:
        lines.append(f"  <url><loc>{BASE_URL}/{page.slug}.html</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
