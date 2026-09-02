# nixos.se

Homepage and RSS feed for the Stockholm NixOS meetup. A meetup is a markdown
file in `meetups/`; CI renders the site and deploys it to GitHub Pages.

## Adding a meetup

Create `meetups/YYYY-MM-DD-title.md`; the file name is the URL. TOML
frontmatter between `+++` lines, markdown after:

```markdown
+++
title = "Nix meetup, 28 January"
date = 2027-01-28T19:00:00
end = 22:00:00
summary = "One sentence for the front page and the feed."
venue = "nordic-light"

[[talks]]
title = "Overlays, finally"
speaker = "kim"
abstract = "Optional, markdown."
+++

Free-form markdown.
```

- `title`, `date`: required. `date = 2027-01-28` without a time is allowed; no time is shown.
- `end`: `22:00:00` for the same day, or a full datetime.
- `summary`, `cancelled`, `announced` (feed date, defaults to `date`): optional.
- `venue`, `talks[].speaker`: a key from `venues.toml` / `speakers.toml`, or an
  inline table (`[venue]`, `speaker = { name = "…" }`) for a one-off.

Unknown keys and unknown venue or speaker names fail the build. The registry
files document their own format in their headers; `site.toml` holds title, URLs,
timezone and footer links.

## Development

```console
$ nix develop
$ meet-build                        # writes ./public
$ python -m http.server -d public   # preview
$ nix flake check                   # site build, ruff, mypy --strict
```

`src/meet/content.py`: pydantic models for every file. `build.py`: Jinja2
templates, feed, and the Tailwind stylesheet (input in `templates/style.css`,
standalone CLI from nixpkgs). Python dependencies: `pyproject.toml` + `uv.lock`
via uv2nix; run `uv lock` after changing them.

Pull requests run `nix flake check` (`.github/workflows/check.yml`). Pushes to
`main` and a daily schedule build and deploy to GitHub Pages
(`.github/workflows/deploy.yml`). The schedule is what moves meetups into the
archive on their own.

## Logo

`static/nix-snowflake-sweden.svg` is the NixOS snowflake recoloured to the
Swedish flag, © the NixOS project, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
