.PHONY: build check serve stop test shell image ci lock native-test

ARGS ?=

image:
	docker compose build build

build:   ## make build ARGS="--force --section f1"
	docker compose run --rm build $(ARGS)

check:
	docker compose run --rm check-sources

serve:
	docker compose up -d serve
	@echo "David Times: http://localhost:8080/"

stop:
	docker compose down

test:
	docker build --target test -t davidtimes:test .
	docker run --rm davidtimes:test

shell:
	docker compose run --rm --entrypoint bash build

ci: image test   ## image builds, --help runs inside it, unit tests pass
	docker compose run --rm --entrypoint davidtimes build --help

lock:    ## regenerate uv.lock and requirements.txt without a local uv
	docker run --rm -v "$(CURDIR)":/w -w /w ghcr.io/astral-sh/uv:0.8.17-python3.12-bookworm-slim \
	  sh -c "uv lock && uv export --no-hashes --no-dev --no-emit-project -o requirements.txt"

native-test:
	uv run pytest -q
