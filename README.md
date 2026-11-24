# David Times

A personal daily newspaper for the Kindle e-ink browser. Each run collects recent
articles from open sources, lets an LLM pick and write about 30 minutes of reading,
and renders a static, JavaScript-free website into `dist/`.

## Docker quickstart

```bash
cp .env.example .env        # then fill in the keys (see below)
make check                  # validate every source, print a table
make build                  # write today's edition into dist/YYYY-MM-DD/
make serve                  # http://localhost:8080/
```

`dist/index.html` always shows the latest edition. You can also open it directly
with `file://` — all links are relative.

Extra build flags: `make build ARGS="--force --section f1"`, or
`docker compose run --rm build --force --section f1`.

| Target | What it does |
|---|---|
| `make build` | run the pipeline (`davidtimes build`) |
| `make check` | `davidtimes check-sources` |
| `make serve` / `make stop` | nginx on :8080 serving `dist/` read-only |
| `make test` | unit tests inside a test image |
| `make ci` | image builds, `davidtimes --help` runs in it, tests pass |
| `make shell` | bash inside the build container |
| `make lock` | regenerate `uv.lock` and `requirements.txt` (no local uv needed) |

The build container is cron-friendly: non-interactive, exit code 0 on success,
1 when nothing at all could be produced. The fetch/LLM cache lives in the named
volume `cache`, so reruns on the same day are free and identical.

## Native (no Docker)

Needs Python 3.11+.

```bash
uv sync                     # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt -e .
uv run davidtimes check-sources
uv run davidtimes build
uv run davidtimes serve     # http://localhost:8080/
uv run pytest
```

Keys are read from `.env` in the project root (or the environment).

## API keys

| Variable | Needed for | How to get it |
|---|---|---|
| `GEMINI_API_KEY` | curation and writing (required for real pieces) | <https://aistudio.google.com/apikey> — free tier |
| `GUARDIAN_API_KEY` | full Guardian article bodies | <https://open-platform.theguardian.com/access/> — "developer key", free. The old public `test` key no longer works. |
| `FOOTBALL_DATA_API_KEY` | Premier League table, results, fixtures | <https://www.football-data.org/client/register> — free tier |
| `GROQ_API_KEY`, `OPENROUTER_API_KEY` | optional LLM fallbacks | console.groq.com / openrouter.ai |

A missing key never crashes the run: that source or provider is skipped and the
summary says so. Without any LLM key the edition contains unedited source text,
marked as such.

## Build flags

```
davidtimes build [--date YYYY-MM-DD] [--section ID ...] [--no-llm] [--offline]
                 [--force] [--max-pieces N] [--minutes N]
```

- `--no-llm` renders raw extracted text (tests the plumbing, costs nothing).
- `--offline` uses only cached fetches and LLM outputs.
- `--force` bypasses the fetch and LLM caches.
- `--section` rebuilds only those sections; the rest of the day's edition is kept.
- `--max-pieces` caps pieces per section; `--minutes` overrides the reading target.

## Configuration

### Add or remove a source

One line in `config/sources.yaml`:

```yaml
      - {type: rss, name: RaceFans, url: "https://www.racefans.net/feed/"}
```

Types: `rss`, `guardian_api` (`tag:`, `section:` or `q:`), `jolpica`,
`football_data` (`competition: PL`), `datos_gov_trm`. Add `enabled: false` to
switch a source off. Run `make check` afterwards: broken RSS feeds get feed
autodiscovery suggestions in the NOTE column.

### Language, weights, reading time

- Section language: `language: es` or `language: en` on the section.
- Section share of the reading time: `weight:` (default F1/PL 1.0, others 1.2).
- `settings.reading_time_minutes` (30) and `settings.words_per_minute` (220) set
  the word budget (6,600 words). Pieces per section ≈ section budget / `words_per_piece`.
- `recap_mode:` text is used when the structured source reports no race/matchday
  in the lookback window.

### LLM providers

`config/llm.yaml` lists providers in fallback order (switching on 429/5xx/errors).
Adding a provider = one more entry with `base_url`, `api_key_env` and `models`.
It also sets the throttle (`requests_per_minute`), the per-run call cap
(`max_calls_per_run`), and per-task extra parameters such as `reasoning_effort`.
The Gemini model IDs were checked against Google's docs in November 2026; the
Groq/OpenRouter model IDs were not verified.

## How a build works

1. **Fetch** every source in parallel (20 s timeout, honest User-Agent; failures are logged, never fatal).
2. **Dedupe** by canonical URL, then cluster by headline token overlap.
3. **Curate** (cheap model): per section, titles + snippets only → top N + spares.
4. **Extract** full text only for chosen clusters (API body, RSS content, else trafilatura); skip paywalled/thin text and refill from the next clusters.
5. **Synthesize** (better model): one call per section; any piece >25 % off its word target is rewritten once.
6. **Budget**: trim lowest-ranked pieces if the edition is >10 % over; ask for one extra piece if >10 % under.
7. **Render** static HTML. Tables (results, standings, TRM) come straight from APIs, never from the LLM.

## Layout

```
config/            sources.yaml, llm.yaml
src/davidtimes/    cli, build, fetch/, extract, dedupe, curate, synthesize, budget, llm/, render, cache
templates/         base, front, toc, article, archive (.html) + style.css (inlined)
dist/              output (gitignored)
tests/             unit tests with fixture files, no network
```
