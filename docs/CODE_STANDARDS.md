# Code standards

The conventions this project is written to, and how they are enforced. They are
the desktop-software analog of the security + readability standard used across
the author's other work — adapted from "secure reactive Java" to a **Python
daemon + C++/Qt6 overlay & config GUI + QML**, where the equivalent risks are
**raw device I/O, threading, and subprocess/IPC**, not web request handling.

The guiding principle is the same everywhere: **code reads like prose, magic
values are named, state is owned by exactly one place, and every non-obvious
protocol or threading decision carries a one-line plain-English reason.**

---

## Enforcement (run before every commit)

| Area | Command (from the component dir) | Gate |
|---|---|---|
| Python daemon | `cd daemon && ruff check` | lint (E/F/W/I/N/B/BLE/S) — must be clean |
| Python daemon | `cd daemon && ruff format --check` | 88-col formatting — must be clean |
| Python daemon | `cd daemon && pytest -q` | unit tests — must be green |
| C++ overlay / config-ui | `clang-format --dry-run -Werror overlay/src/*.{h,cpp} config-ui/src/*.{h,cpp}` | style baseline for **new** code |
| C++ overlay / config-ui | `cmake --build build` | must compile clean (treat warnings as review items) |

`ruff` config lives in [`daemon/ruff.toml`](../daemon/ruff.toml); the C++ style
lives in [`.clang-format`](../.clang-format). Both are committed so the gate is
reproducible.

> The C++ files are **hand-formatted** to the `.clang-format` house style but are
> **not** mass-reformatted by the tool: clang-format would expand a few
> deliberate one-line accessors and disturb the column-aligned hex comments
> without a readability gain. Run `clang-format` on **new** code and keep diffs
> tight; do not bulk-rewrite existing, hardware-proven files.

---

## Python (`daemon/mx4d`)

- **Type hints everywhere.** `from __future__ import annotations` at the top of
  every module; annotate every parameter and return. Public data is modelled as
  `@dataclass` (`Event`, `SourceConfig`, `MX4Device`).
- **No magic numbers.** Every HID++ feature id, function nibble, report id,
  flag bit, and waveform index is a named module constant
  (`FEATURE_HAPTIC = 0x19B0`, `HAPTIC_FN_PLAY = 0x4`, `_FLAG_DIVERT = 1 << 1`,
  `ACTIONS_RING_CID = 0x01A0`). A literal in a packet is always explained.
- **Docstrings + per-step comments.** Every module, class and public method has a
  docstring. Inside protocol/threading code, each non-obvious step gets a comment
  saying *why* (e.g. "key includes the function nibble so two functions on the
  same feature index never collide").
- **Named helpers, not nested lambdas.** Wire-format and policy logic lives in
  named functions (`build_play_packet`, `build_set_cid_reporting_params`,
  `parse_pressed_cids`, `_resolve_divert`) so each is independently testable and
  reads as a sentence.
- **One owner per piece of state.** No mutable module-global state. The daemon
  object owns the device, engine, trigger and sources for the process lifetime
  and tears them down in a defined order.
- **Narrow exceptions.** Catch the specific error (`OSError`, `HidppTimeout`,
  `configparser.Error`). A broad `except Exception` is allowed **only** at a
  thread / D-Bus-callback boundary that must never die, and then it is annotated
  `# noqa: BLE001` with a reason and logged — never silent.
- **Security.**
  - Subprocesses are **always** launched with an argv list, **never**
    `shell=True` — menu labels and commands can never inject. (`ruff`'s `S603`
    is ignored project-wide *because* this pattern is enforced by convention.)
  - The daemon **never runs as root**; the single privileged step is the
    `uaccess` udev rule. HID is reached through a session ACL.
  - Any device control we **divert** (the Actions Ring panel) is **always
    restored** on shutdown — `stop()`, an `atexit` hook, and a signal handler all
    converge on leaving the mouse clean, with a fire-and-forget last resort.
  - Haptic plays are **gated by the firmware capability mask**; an unsupported
    waveform falls back to the nearest supported one rather than silently no-op.
- **Threading discipline (the highest-risk area).**
  - **All blocking HID I/O runs on the dedicated device-I/O worker thread** —
    never on the GLib/dbus mainloop, never on a source thread.
  - D-Bus and overlay work is **marshalled onto the mainloop thread**
    (`GLib.idle_add`) because dbus-python and the overlay timers are
    single-threaded there.
  - Every callback's docstring states **which thread it runs on**.
  - Bursts are **debounced before any I/O**, so an event storm issues zero HID
    round-trips.

## C++ / Qt6 (`overlay/`, `config-ui/`)

- **Style:** 4-space indent, 80 columns, next-line braces for
  functions/classes/structs, attached braces for control flow, `Type *name`
  pointers — see [`.clang-format`](../.clang-format).
- **One class per file**, `.h` / `.cpp` split, all inside `namespace mx4`.
- **`const`-correctness:** const member functions for accessors, `const &`
  parameters for non-trivial types.
- **Ownership is explicit.** Objects are parented into the Qt `QObject` tree (no
  manual `delete`); a raw pointer that is *not* owned is commented `// not owned`.
  Every class header's Doxygen block states its ownership and threading model.
- **Named constants, not literals:** `constexpr char kBusName[] = "…"`,
  `constexpr int kOverlaySize = 520`. D-Bus names/paths/interfaces are defined
  once.
- **Logging:** one `Q_LOGGING_CATEGORY` per file (`mx4.<area>`); no stray
  `qDebug`.
- **Security:** windows launch actions via `QProcess::startDetached(program,
  args)` — argv only, no shell, no string interpolation. D-Bus calls into the
  daemon are **async / fire-and-forget** so the UI never blocks on the motor.

## QML (`overlay/qml`, `config-ui/qml`)

- One component per file; derived geometry is a `readonly property`.
- Non-obvious math (polar ↔ cartesian angle mapping, dead-zone) is commented.
- Theme icons are addressed by name and **resolve to nothing if missing** (never
  a broken-image box, never a crash).

## Cross-cutting contracts

- **The shared INI is a contract.** The daemon (Python `configparser`), the
  overlay and the config GUI (both Qt `QSettings`) read the *same* file. The
  config GUI therefore hand-emits a **configparser-compatible** INI (literal `:`
  in section names, literal `/` in keys) and **preserves unknown keys** on save.
  A key read by more than one process (e.g. `radial/center/command`) is spelled
  identically in all of them. Any change to the schema updates every reader.
- **Tests use seams, not hardware.** HID is tested against an in-memory fake
  hidraw (`tests/conftest.py`); the suite runs with no device attached.
- **Honesty about limitations.** Firmware waveform gating and Wayland
  center-screen placement are documented as designed behaviour, not hidden.
