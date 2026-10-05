# Backend tests

Текущая стратегия backend-тестов:

- `*.rs` в корне `backend/tests/` — реальные Rust integration tests для `cargo test`;
- `smoke_core_api.py` — black-box smoke против запущенного backend;
- подкаталоги ниже — место для fixtures, contract data, replayable scenarios и support notes.

Почему Rust integration tests остаются в корне:
`cargo` автоматически подхватывает integration tests из `tests/*.rs`, поэтому переносить их глубже без дополнительной сборочной схемы сейчас невыгодно.

См. также:
- `docs/architecture/testing-strategy-v1.md`
- `docs/architecture/testing-pyramid-v1.md`
- `backend/tests/SMOKE_SCENARIOS.md`
