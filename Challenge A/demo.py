"""Reproducible four-session proof required by Challenge A."""

from __future__ import annotations

from pathlib import Path

from memory_harness import MemoryStore, agent_response, format_injected_memory


ROOT = Path(__file__).resolve().parent
STORE_PATH = ROOT / "demo-output" / "memory.json"


def reset_demo_data() -> None:
    for path in (STORE_PATH, STORE_PATH.with_name("memory-audit.jsonl")):
        if path.exists():
            path.unlink()


def show_session(title: str, store: MemoryStore, task: str) -> None:
    payload = store.injected_memory(task=task, limit=3)
    print(f"\n===== {title} =====")
    print(format_injected_memory(payload))
    print("AGENT_RESPONSE")
    print(agent_response(task, payload))


def main() -> None:
    reset_demo_data()
    store = MemoryStore(STORE_PATH)

    print("===== SESSION day-1: agree a convention =====")
    store.record(
        "api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00+00:00"
    )
    print("Saved api_field_style v1 = camelCase")
    store.record(
        "database_migration_style", "PostgreSQL migrations", "day-1", "2026-10-21T09:01:00+00:00"
    )
    store.record(
        "authentication_scheme", "JWT bearer", "day-1", "2026-10-21T09:02:00+00:00"
    )
    print("Saved database_migration_style = PostgreSQL migrations")
    print("Saved authentication_scheme = JWT bearer")

    # A newly constructed store models a separate process/session reopening disk state.
    show_session(
        "SESSION day-2: a new session",
        MemoryStore(STORE_PATH),
        "Create a PostgreSQL API user endpoint protected by JWT",
    )

    print("\n===== SESSION day-3: change the convention =====")
    store.record(
        "api_field_style", "snake_case", "day-3", "2026-10-21T09:10:00+00:00"
    )
    print("Saved api_field_style v2 = snake_case; v1 is now superseded")

    show_session(
        "SESSION day-4: a new session after change",
        MemoryStore(STORE_PATH),
        "Create a PostgreSQL API user endpoint protected by JWT",
    )
    print("\n===== PERSISTED HISTORY =====")
    print(STORE_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
