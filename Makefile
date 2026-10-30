# CLI toolkit del Lab. Modello (ADR-001): datasets/ = un dataset per dir,
# ognuna con il proprio dataset.yml. I path relativi sono risolti rispetto
# alla dir del file.
TOOLKIT = toolkit

DATASETS := $(shell find datasets -name dataset.yml 2>/dev/null | sort)

.PHONY: ingest
ingest:
	@python scripts/capture.py
	@python scripts/to_parquet.py --input data/gu_atti_delta.json
	@python scripts/crossref.py
	@python scripts/to_parquet.py --input data/gu_atti_delta.json

.PHONY: run
run:
	@for f in $(DATASETS); do \
		echo "=== $$f ==="; \
		$(TOOLKIT) run --config "$$f" || exit 1; \
	done

.PHONY: run-all
run-all: run

# Cattura + pipeline: quello che gira ogni notte.
.PHONY: daily
daily: ingest run

.PHONY: check
check:
	@for f in $(DATASETS); do \
		echo "=== $$f ==="; \
		$(TOOLKIT) run preflight --config "$$f" > /dev/null 2>&1 || exit 1; \
	done
	@echo "config validi"

.PHONY: test
test:
	@python -m pytest tests/ -q
	@python -m ruff check .

.PHONY: rebuild
rebuild:
	@test -n "$(ANNO)" || (echo "uso: make rebuild ANNO=2026" && exit 1)
	@python scripts/rebuild_archivio.py --anno $(ANNO)
	@python scripts/to_parquet.py --rebuild --input data/gu_atti_rebuild.json

.PHONY: registry registry-write
registry:
	$(TOOLKIT) registry build

registry-write:
	$(TOOLKIT) registry build --prefix gu-monitor --write

.PHONY: clean
clean:
	rm -rf out/data/_runs out/data/raw out/data/clean out/data/mart
