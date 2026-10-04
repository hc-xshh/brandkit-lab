# brandkit-lab — everything runs offline with the standard library alone.
# `make demo` rebuilds every artefact this repository claims in its README.

PYTHON ?= python3
SOURCES := $(patsubst sources/%.html,%,$(wildcard sources/*.html))
SKELETONS := $(notdir $(patsubst %/layout-base.html,%,$(wildcard skeletons/*/layout-base.html)))
GALLERY_SKELETONS := 01-host-landing 02-saas-marketing 03-product-security
GALLERY_KITS := northwind-outfitters slate-assurance

.PHONY: help test lint eval measure demo gallery api clean all

help:
	@echo "brandkit-lab"
	@echo
	@echo "  make test      run the test suite (pytest, dev-only dependency)"
	@echo "  make lint      offline lint: no third-party imports, no remote assets"
	@echo "  make eval      (sources x skeletons) metrics with thresholds; writes docs/eval.json"
	@echo "  make measure   measure the three example sources into out/metrics/"
	@echo "  make demo      measure + eval + restyle everything into out/"
	@echo "  make gallery   rebuild docs/img/*.png and docs/index.html (needs headless Chrome)"
	@echo "  make all       lint + test + eval"
	@echo "  make api       print the registry and skeleton contracts"
	@echo "  make clean     remove out/"
	@echo
	@echo "sources:   $(SOURCES)"
	@echo "skeletons: $(SKELETONS)"

test:
	$(PYTHON) -m pytest tests -q

lint:
	$(PYTHON) scripts/check_lint.py

eval:
	$(PYTHON) scripts/eval_report.py

measure:
	@mkdir -p out/metrics
	@for s in $(SOURCES); do \
		$(PYTHON) -m brandkit.measure --source sources/$$s.html --out out/metrics/$$s.json; \
	done

# One brand source in, one page out, by hand:
#   make kit SOURCE=northwind-outfitters SKELETON=01-host-landing
kit:
	@test -n "$(SOURCE)" || (echo "usage: make kit SOURCE=<source-id> SKELETON=<skeleton-id>"; exit 2)
	@test -n "$(SKELETON)" || (echo "usage: make kit SOURCE=<source-id> SKELETON=<skeleton-id>"; exit 2)
	$(PYTHON) -m brandkit.measure --source sources/$(SOURCE).html --out out/metrics/$(SOURCE).json
	$(PYTHON) -m brandkit.assemble_kit --metrics out/metrics/$(SOURCE).json \
		--skeleton $(SKELETON) --out out/kits
	$(PYTHON) -m brandkit.apply --kit out/kits/$(SOURCE)--$(SKELETON).kit.json \
		--out out/restyled/$(SOURCE)--$(SKELETON).html
	@echo "open out/restyled/$(SOURCE)--$(SKELETON).html"

demo: measure eval

gallery:
	$(PYTHON) scripts/eval_report.py --keep
	$(PYTHON) scripts/shoot.py --out docs/img --size 1280x900 \
		$(foreach skel,$(GALLERY_SKELETONS),before-$(skel)=skeletons/$(skel)/layout-base.html) \
		$(foreach kit,$(GALLERY_KITS),$(foreach skel,$(GALLERY_SKELETONS),after-$(kit)--$(skel)=out/restyled/$(kit)--$(skel).html))
	$(PYTHON) scripts/build_gallery.py

api:
	$(PYTHON) -m brandkit.blocks
	@echo
	$(PYTHON) -m brandkit.skeletons

all: lint test eval

clean:
	rm -rf out
