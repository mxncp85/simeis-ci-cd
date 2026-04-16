# Centralized build flags used by all cargo invocations in this Makefile.
RUSTFLAGS_CODEGEN := -C code-model=kernel -C codegen-units=1
export RUSTFLAGS := $(strip $(RUSTFLAGS) $(RUSTFLAGS_CODEGEN))

SERVER_BIN_DEBUG := target/debug/simeis-server
SERVER_BIN_RELEASE := target/release/simeis-server
MANUAL_SRC := doc/manual.typ
MANUAL_OUT := doc/manual.pdf

.PHONY: all debug release manual check test clean show-rustflags ci-dev ci-release

all: debug

show-rustflags:
	@echo RUSTFLAGS=$(RUSTFLAGS)

debug:
	@echo Build du projet en mode debug avec des commandes rustc détaillées
	cargo build --workspace --verbose
	strip $(SERVER_BIN_DEBUG) || true

release:
	@echo Build du projet en mode release avec des commandes rustc détaillées
	cargo build --workspace --release --verbose
	strip $(SERVER_BIN_RELEASE) || true

manual:
	typst compile $(MANUAL_SRC) $(MANUAL_OUT)

check:
	cargo check --workspace --all-targets --verbose

test:
	cargo test --workspace --verbose

clean:
	cargo clean

# CI pour les merge request et les push sur des branches hors main.
ci-dev: check test

# CI une fois merge sur main.
ci-release: release manual
