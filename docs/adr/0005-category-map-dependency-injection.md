# ADR 0005 - Category Map Dependency Injection

- **Status:** Accepted
- **Date:** 2026-05-10
- **Phase:** P0
- **Deciders:** Architect agent

## Context

`app.py` currently loads category maps from JSON files into two module-level globals (`CUSTOM_CATEGORY_MAP`, `GENERIC_CATEGORY_MAP`) at import time, and `categorize(desc)` reads those globals directly at call time. This is the [Phase 0 work item](../roadmap.md#phase-0--foundation-hardening-1-2-weeks) to introduce a dependency-injection pattern so category maps are passed in rather than imported as globals. The decision matters beyond Phase 0: in Phase 1, `load_category_map()` (reading a JSON file) will be replaced by a per-user database read inside the application factory. Whichever DI form is chosen here becomes the interface that Phase 1 swaps out at the source — if the call site in the route handler or the `categorize` function itself must change at Phase 1, then Phase 0 solved the wrong problem. The risk of PII leakage in logs (`P0+`, High impact) also benefits from removing globals: a callable that carries its own maps is easier to instrument and test in isolation.

## Options considered

### Option A - functools.partial

`categorize` is promoted to `categorize(desc, custom_map, generic_map)`. The route handler binds the maps at request time with `partial(categorize, custom_map=custom_map, generic_map=generic_map)` and passes the result to `DataFrame.apply`.

**Pros.**
- `categorize` stays a plain function — no new class or closure construct.
- The maps are explicit in the signature, which makes the dependency visible to static analysis and type checkers.

**Cons.**
- `functools.partial` with keyword arguments is not universally understood; a reader must trace `partial(categorize, custom_map=..., generic_map=...)` to understand what `apply` is receiving.
- The call site in the route handler must change twice: once in Phase 0 to introduce `partial`, and again in Phase 1 if the name or source of the maps changes. If Phase 1 changes how many maps exist or renames them, the route handler is touched.
- `categorize` itself grows a three-argument signature that is more awkward to call directly in tests: `categorize("TIM HORTONS", custom_map={}, generic_map={...})` for every assertion.

### Option B - Factory closure

`make_categorizer(custom_map, generic_map)` is a factory that returns a single-argument closure `desc -> category`. The route handler calls `make_categorizer(custom_map, generic_map)` once, then passes the returned closure directly to `DataFrame.apply(categorize_fn)`.

**Pros.**
- The closure that `apply` receives is exactly `desc -> category` — no wrapping, no `partial`, no class instantiation at the call site.
- The route handler's call to `apply` does not change between Phase 0 and Phase 1. The only thing that changes in Phase 1 is how `custom_map` and `generic_map` are loaded before `make_categorizer` is called. The factory signature itself is stable.
- `categorize` as a pure function can survive unchanged under the factory, or be inlined — both are natural refactors.
- Testing the categorizer directly requires no test-framework machinery: `fn = make_categorizer({...}, {...}); assert fn("TIM HORTONS") == "Food"`.

**Cons.**
- Two names exist where one exists today: the factory function and the inner closure. A reader must follow one level of indirection.
- The returned closure is not independently importable; tests go through the factory. This is a minor overhead that is already paid in Option C.

### Option C - Callable class

`Categorizer(custom_map, generic_map)` is instantiated with the maps and exposes `__call__(self, desc)`. The route handler passes an instance to `apply`.

**Pros.**
- The maps live on the instance, accessible for inspection and debugging.
- Adding state (e.g., a call counter or a cache) later is straightforward via instance attributes.

**Cons.**
- A class is heavier than a closure for a function that has no mutable state and no methods other than `__call__`. The overhead is conceptual, not runtime.
- The `__call__` indirection is less obvious than a plain function to a reader scanning the `apply` call.
- No material advantage over Option B for the Phase 0 and Phase 1 requirements. The state extension argument applies equally to a closure that could be promoted to a class later, and is speculative at this stage.

## Decision

We will choose **Option B — factory closure** because it produces the cleanest `DataFrame.apply` call site and makes Phase 1's substitution entirely local to the point where maps are loaded.

The concrete outcome: `make_categorizer(custom_map, generic_map)` is defined in the categorization service. It returns a `Callable[[str], str]`. The route handler builds the categorizer once per request and passes it to `apply`:

```python
# services/categorization.py

def make_categorizer(
    custom_map: dict[str, list[str]],
    generic_map: dict[str, list[str]],
) -> Callable[[str], str]:
    """Return a single-argument callable suitable for DataFrame.apply."""
    def categorize(desc: str) -> str:
        desc = str(desc).upper()
        for category_map in (custom_map, generic_map):
            for category, keywords in category_map.items():
                for keyword in keywords:
                    if str(keyword).upper() in desc:
                        return category
        return "Slush Fund"
    return categorize
```

The route handler:

```python
# routes/upload.py (post-Phase 0 refactor)

categorize = make_categorizer(custom_map, generic_map)
df["Category"] = df["Description 1"].apply(categorize)
```

In Phase 1, `custom_map` and `generic_map` are loaded from the database instead of from JSON files. The `make_categorizer` call and the `apply` line are unchanged.

The module-level globals `CUSTOM_CATEGORY_MAP` and `GENERIC_CATEGORY_MAP` are removed from `app.py` once the factory is wired in.

## Consequences

- **Positive:** The `apply` call site in the route handler is stable across Phase 0 and Phase 1. Phase 1 touches only the map-loading code.
- **Positive:** `make_categorizer` and its returned closure are testable without any module-level state or monkeypatching: construct a factory call with controlled maps, assert on the result.
- **Positive:** The globals are gone, eliminating the risk that a future code path modifies them at runtime and causes silent cross-request contamination.
- **Negative:** One additional name (`make_categorizer`) exists in the public surface of the categorization service. This is the minimum necessary indirection.
- **Follow-up required — tests must be rewritten:** The existing tests in `tests/test_categorize.py` use `monkeypatch.setattr("app.CUSTOM_CATEGORY_MAP", {...})` and `monkeypatch.setattr("app.GENERIC_CATEGORY_MAP", {...})` to control the maps. Once the globals are removed, these `monkeypatch` calls silently become no-ops — they will not raise an `AttributeError` unless the test file is also updated, and the tests will appear green while testing nothing meaningful. The implementation agent must rewrite every test that patches globals so that it instead calls `make_categorizer` directly with the controlled maps. The monkeypatch pattern must not survive into Phase 1.
- **Follow-up required — ADR 0004:** ADR 0004 covers the Phase 0 module split (`routes/`, `services/`, `models/`). The home of `make_categorizer` is `services/categorization.py` per that structure. If ADR 0004 has not yet been written, this ADR assumes that module layout and the implementation agent should treat the two as a unit.

## Notes

The `partial` approach (Option A) was rejected primarily because it shifts complexity to the call site rather than the factory. A reader of the route handler should not need to understand `functools.partial` to understand how categorization is invoked. The factory pattern is the idiomatic Python answer to "bind some configuration, then get a single-argument callable."

The callable class (Option C) was rejected because no mutable state is needed and the class machinery adds conceptual overhead without benefit at this stage. If a future requirement introduces caching of `desc -> category` results or call telemetry, the factory closure can be promoted to a class at that point with a localized change.
