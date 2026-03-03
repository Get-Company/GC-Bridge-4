# Minimal makefile for Sphinx documentation

SPHINXOPTS ?=
SPHINXBUILD ?= ../.venv/bin/sphinx-build
SOURCEDIR = source
BUILDDIR = build

.PHONY: help inventory html clean

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

inventory:
	@../.venv/bin/python scripts/generate_model_admin_inventory.py

html:
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

clean:
	rm -rf "$(BUILDDIR)"/*
