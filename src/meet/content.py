"""The TOML files this site is made of, validated into pydantic models.

The README documents the file formats.
"""

import datetime as dt
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    TypeAdapter,
    ValidationError,
)

# Assumed length of a meetup without an explicit `end`, for deciding when it
# stops being upcoming.
DEFAULT_DURATION = dt.timedelta(hours=3)

FRONTMATTER_RE = re.compile(
    r"\A\+\+\+[^\S\n]*\n(?P<meta>.*?)\n\+\+\+[^\S\n]*(?:\n(?P<body>.*))?\Z",
    re.DOTALL,
)


class ContentError(Exception):
    """Anything a contributor can fix by editing a file."""


class _Model(BaseModel):
    # Strict: TOML already produced typed values, so coercion would only hide
    # mistakes. Forbid extras: an unknown key is a typo.
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError):
        raise ValueError(f"unknown timezone {name!r}") from None


class Link(_Model):
    name: str
    url: str


class Venue(_Model):
    name: str
    address: str | None = None
    url: str | None = None
    directions: str | None = None


class Speaker(_Model):
    name: str
    url: str | None = None
    bio: str | None = None


class Config(_Model):
    title: str
    base_url: Annotated[str, AfterValidator(lambda url: url.rstrip("/"))]
    tagline: str = ""
    description: str = ""
    repository: str | None = None
    language: str = "en"
    timezone: Annotated[ZoneInfo, BeforeValidator(_zone)] = ZoneInfo("Europe/Stockholm")
    links: list[Link] = []

    def url_for(self, path: str) -> str:
        return f"{self.base_url}{path}"


class Talk(_Model):
    title: str
    speaker: Speaker | None = None
    abstract: str | None = None


class Meetup(_Model):
    slug: str
    title: str
    start: dt.datetime
    has_time: bool  # False when the file only gave a day: never print "00:00".
    end: dt.datetime | None
    summary: str
    body: str
    venue: Venue | None
    cancelled: bool
    announced: dt.datetime
    talks: list[Talk]

    @property
    def path(self) -> str:
        return f"/meetups/{self.slug}/"

    @property
    def machine_date(self) -> str:
        """For a <time datetime=...> attribute."""
        return self.start.isoformat() if self.has_time else self.start.date().isoformat()

    @property
    def finish(self) -> dt.datetime:
        if self.end is not None:
            return self.end
        return self.start + (DEFAULT_DURATION if self.has_time else dt.timedelta(days=1))

    def is_upcoming(self, now: dt.datetime) -> bool:
        return self.finish >= now


class Registries(_Model):
    venues: dict[str, Venue]
    speakers: dict[str, Speaker]


# The frontmatter as written: dates have no timezone yet, and a venue or
# speaker may be a name to look up rather than a table.
class _TalkFile(_Model):
    title: str
    speaker: str | Speaker | None = None
    abstract: str | None = None


class _MeetupFile(_Model):
    title: str
    date: dt.datetime | dt.date
    end: dt.datetime | dt.time | None = None
    announced: dt.datetime | dt.date | None = None
    summary: str = ""
    cancelled: bool = False
    venue: str | Venue | None = None
    talks: list[_TalkFile] = []


_CONFIG = TypeAdapter(Config)
_VENUES = TypeAdapter(dict[str, Venue])
_SPEAKERS = TypeAdapter(dict[str, Speaker])
_MEETUP = TypeAdapter(_MeetupFile)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContentError(f"{path}: no such file") from exc


def _load[T](adapter: TypeAdapter[T], toml: str, path: Path) -> T:
    """Parse and validate *toml*, reporting problems against *path*."""
    try:
        return adapter.validate_python(tomllib.loads(toml))
    except tomllib.TOMLDecodeError as exc:
        raise ContentError(f"{path}: invalid TOML: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ContentError(f"{path}: {problems}") from exc


def load_config(path: Path) -> Config:
    return _load(_CONFIG, _read(path), path)


def load_registries(root: Path) -> Registries:
    return Registries(
        venues=_registry(_VENUES, root / "venues.toml"),
        speakers=_registry(_SPEAKERS, root / "speakers.toml"),
    )


def _registry[T](adapter: TypeAdapter[dict[str, T]], path: Path) -> dict[str, T]:
    """Registries are optional; without one, meetups spell everything out."""
    return _load(adapter, _read(path), path) if path.is_file() else {}


def _resolve[T](
    value: str | T | None, registry: Mapping[str, T], path: Path, what: str
) -> T | None:
    """A name is looked up in its registry; a table written in place is used as is."""
    if not isinstance(value, str):
        return value
    if value not in registry:
        known = ", ".join(sorted(registry)) or "none defined"
        raise ContentError(f"{path}: unknown {what} '{value}'; {what}s.toml defines: {known}")
    return registry[value]


def load_meetups(directory: Path, config: Config, registries: Registries) -> list[Meetup]:
    """Every ``*.md`` in *directory*, newest first."""
    if not directory.is_dir():
        raise ContentError(f"{directory}: no such directory")
    meetups = [parse_meetup(path, config, registries) for path in directory.glob("*.md")]
    return sorted(meetups, key=lambda m: m.start, reverse=True)


def parse_meetup(path: Path, config: Config, registries: Registries) -> Meetup:
    match = FRONTMATTER_RE.match(_read(path))
    if match is None:
        raise ContentError(f"{path}: missing '+++' TOML frontmatter block")
    file = _load(_MEETUP, match["meta"], path)
    tz = config.timezone

    start, has_time = _moment(file.date, tz)
    end = _end(file.end, start, tz)
    if end is not None and end < start:
        raise ContentError(f"{path}: 'end' is before 'date'")

    return Meetup(
        slug=path.stem,
        title=file.title,
        start=start,
        has_time=has_time,
        end=end,
        summary=file.summary,
        body=(match["body"] or "").strip(),
        venue=_resolve(file.venue, registries.venues, path, "venue"),
        cancelled=file.cancelled,
        announced=start if file.announced is None else _moment(file.announced, tz)[0],
        talks=[
            Talk(
                title=talk.title,
                speaker=_resolve(talk.speaker, registries.speakers, path, "speaker"),
                abstract=talk.abstract,
            )
            for talk in file.talks
        ],
    )


def _localize(value: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def _moment(value: dt.datetime | dt.date, tz: ZoneInfo) -> tuple[dt.datetime, bool]:
    """The moment, and whether the file gave a time of day at all."""
    if isinstance(value, dt.datetime):  # a subclass of date, so tested first
        return _localize(value, tz), True
    return _localize(dt.datetime.combine(value, dt.time()), tz), False


def _end(
    value: dt.datetime | dt.time | None, start: dt.datetime, tz: ZoneInfo
) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.time):  # a bare `end = 21:00:00` means the same day
        value = dt.datetime.combine(start.date(), value)
    return _localize(value, tz)
