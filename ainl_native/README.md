# ainl_native

PyO3 extension for [AINL Cortex](https://github.com/sbhooley/ainl-cortex) strict-native graph memory (`memory.store_backend: "native"`).

Built with [maturin](https://www.maturin.rs/) against the published `ainl-*` Rust crates on crates.io. Wheels are **abi3** (Python 3.10+).

## Install

```bash
pip install "ainl_native>=0.1.1"
```

For plugin development from a git checkout, the Cortex hook may fall back to `maturin develop` when local Rust sources are newer than the installed wheel.

## Build from source

```bash
pip install maturin
maturin develop --release --manifest-path Cargo.toml
```
