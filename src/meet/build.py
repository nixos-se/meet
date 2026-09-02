"""Render the meetup files into a static site and an RSS feed.

Strict on purpose: anything wrong in a content file exits non-zero, so CI
catches it before the site is published.
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import markdown
from feedgen.feed import FeedGenerator
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from meet.content import Config, ContentError, Meetup, load_config, load_meetups, load_registries


def render_markdown(text: str) -> str:
    # markdown is untyped; pin what it returns rather than leaking Any.
    html: str = markdown.markdown(text, extensions=["extra", "smarty", "sane_lists"])
    return html


def format_day(value: datetime) -> str:
    return f"{value:%A} {value.day} {value:%B %Y}"  # %-d is not portable


def format_when(meetup: Meetup) -> str:
    """The date, with a time range when the file gave times."""
    day = format_day(meetup.start)
    if not meetup.has_time:
        return day
    if meetup.end is None:
        return f"{day}, {meetup.start:%H:%M}"
    if meetup.end.date() != meetup.start.date():
        return f"{day}, {meetup.start:%H:%M} – {format_day(meetup.end)}, {meetup.end:%H:%M}"
    return f"{day}, {meetup.start:%H:%M}–{meetup.end:%H:%M}"


def make_environment(templates: Path, config: Config, now: datetime) -> Environment:
    env = Environment(
        loader=FileSystemLoader(templates),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters |= {
        "markdown": render_markdown,
        "day": format_day,
        "when": format_when,
        "absolute": config.url_for,
    }
    env.globals |= {"config": config, "now": now}
    return env


def build_feed(config: Config, meetups: list[Meetup], env: Environment, now: datetime) -> str:
    feed = FeedGenerator()
    feed.title(config.title)
    # feedgen fills the RSS <link> from the last link registered, so self first.
    feed.link(href=config.url_for("/feed.xml"), rel="self")
    feed.link(href=config.url_for("/"), rel="alternate")
    feed.description(config.description or config.tagline)
    feed.language(config.language)
    # From the content rather than the clock, so a rebuild is not a phantom update.
    feed.lastBuildDate(max((m.announced for m in meetups), default=now))

    template = env.get_template("feed_entry.html")
    for meetup in sorted(meetups, key=lambda m: m.announced, reverse=True):
        url = config.url_for(meetup.path)
        entry = feed.add_entry(order="append")
        entry.guid(url, permalink=True)
        entry.title(f"Cancelled: {meetup.title}" if meetup.cancelled else meetup.title)
        entry.link(href=url)
        entry.description(". ".join(s for s in (format_when(meetup), meetup.summary) if s))
        entry.content(template.render(meetup=meetup), type="CDATA")
        entry.published(meetup.announced)

    rss: bytes = feed.rss_str(pretty=True)  # feedgen is untyped too
    return rss.decode()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(root: Path, output: Path) -> None:
    config = load_config(root / "site.toml")
    now = datetime.now(tz=config.timezone)
    meetups = load_meetups(root / "meetups", config, load_registries(root))
    upcoming = [m for m in reversed(meetups) if m.is_upcoming(now)]  # soonest first
    past = [m for m in meetups if not m.is_upcoming(now)]
    env = make_environment(root / "templates", config, now)

    # Meetup pages are the only output with dynamic names; clear them so a
    # renamed or deleted meetup does not linger in a local rebuild.
    shutil.rmtree(output / "meetups", ignore_errors=True)
    index = env.get_template("index.html")
    write(
        output / "index.html",
        index.render(upcoming=upcoming, past=past, next_meetup=upcoming[0] if upcoming else None),
    )
    page = env.get_template("meetup.html")
    for meetup in meetups:
        write(output / "meetups" / meetup.slug / "index.html", page.render(meetup=meetup))
    write(output / "feed.xml", build_feed(config, meetups, env, now))
    write(output / ".nojekyll", "")  # GitHub Pages: publish the files as they are
    if (root / "static").is_dir():
        shutil.copytree(root / "static", output / "static", dirs_exist_ok=True)
    tailwind: list[str | Path] = ["tailwindcss", "--minify"]
    tailwind += ["-i", root / "templates" / "style.css", "-o", output / "static" / "style.css"]
    try:
        subprocess.run(tailwind, check=True, capture_output=True)
    except FileNotFoundError:
        raise SystemExit("error: tailwindcss is not on PATH; run inside `nix develop`") from None
    print(
        f"built {len(meetups)} meetup(s), {len(upcoming)} upcoming, into {output}",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("public"), help="where to write the site"
    )
    try:
        build(Path.cwd(), parser.parse_args().output.resolve())
    except ContentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
