# CLI toolkit del Lab. Modello (ADR-001): datasets/ = un dataset per dir,
# ognuna con il proprio dataset.yml. I path relativi sono risolti rispetto
# alla dir del file.
TOOLKIT = toolkit

DATASETS := $(shell find datasets -name dataset.yml 2>/dev/null | sort)

# Event log e cache URN: fuori da git, su GCS. La lettura è pubblica (HTTPS),
# la scrittura richiede auth (job di ingest in CI).
GCS_STORE ?= gs://dataciviclab-clean/gu-monitor/_event_log
STORE_URL ?= https://storage.googleapis.com/dataciviclab-clean/gu-monitor/_event_log/gu_acts.parquet

.PHONY: store-pull
store-pull:
	@mkdir -p data
	@curl -fsSL "$(STORE_URL)" -o data/gu_acts.parquet && echo "store: scaricato" \
		|| echo "store: assente, si riparte dal locale"

.PHONY: store-push
store-push:
	@gcloud storage cp data/gu_acts.parquet $(GCS_STORE)/gu_acts.parquet --quiet

# Copia di sicurezza dell'ultimo store buono, prima di sovrascriverlo.
# Ripristino: gcloud storage cp $(GCS_STORE)/gu_acts_prev.parquet $(GCS_STORE)/gu_acts.parquet
.PHONY: store-backup
store-backup:
	@gcloud storage cp $(GCS_STORE)/gu_acts.parquet $(GCS_STORE)/gu_acts_prev.parquet --quiet \
		&& echo "backup: gu_acts_prev.parquet" || echo "backup: store assente"

.PHONY: ingest
ingest:
	@python scripts/collect.py

.PHONY: run
run:
	@for f in $(DATASETS); do \
		echo "=== $$f ==="; \
		$(TOOLKIT) run --config "$$f" || exit 1; \
	done

.PHONY: run-all
run-all: run

# Giro completo in locale. NON pubblica su GCS: lo store lo scrive solo la CI.
.PHONY: daily
daily: store-pull ingest run

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
	@test -n "$(ANNI)" || (echo "uso: make rebuild ANNI=2025" && exit 1)
	@python scripts/collect.py --anni $(ANNI)

.PHONY: registry registry-write
registry:
	$(TOOLKIT) registry build

registry-write:
	$(TOOLKIT) registry build --prefix gu-monitor --write

.PHONY: clean
clean:
	rm -rf out/data/_runs out/data/raw out/data/clean out/data/mart
