# Troubleshooting

Use this page when results look surprising (false positive, false negative, or unexpected verdict).

---

## 1) "Why did I get API_BREAK/BREAKING unexpectedly?"

### Check header/binary mismatch first

- Are these the exact headers used to build the analyzed `.so`?
- Are required `-D` macros the same as build time?
- Is include search path the same as build environment?

If not, fix input parity and rerun.

---

## 2) "Why is verdict COMPATIBLE, but I expected NO_CHANGE?"

`COMPATIBLE` means real differences exist (new symbols, policy changes) but no binary break.

Run JSON output for detail:

```bash
abicheck compare old.json new.json --format json -o result.json
python3 -c "import json; r=json.load(open('result.json')); print(r['verdict']); print(len(r['changes']))"
```

---

## 3) "How does `compat` mode report API_BREAK?"

`abicheck compat` uses ABICC-style report text, but still returns **exit code `2`**
for source-level `API_BREAK` conditions.

If you need an explicit `API_BREAK` verdict string in machine-readable output,
use `abicheck compare --format json`.

---

## 4) "Why are deep type changes not detected?"

Check if the binary has DWARF debug info:

```bash
readelf --sections libfoo.so | grep -E "\.debug_info|\.zdebug_info" || echo "No DWARF sections"
```

Without DWARF, Tier 3/4 checks are limited. Use debug builds (`-g`) for deeper analysis.

---

## 5) CI script says success but report shows changes

Remember: `compare` exit code `0` includes both `NO_CHANGE` and `COMPATIBLE`.
If you need exact policy, parse JSON verdict instead of checking `$? == 0`.

---

## 6) Still unsure?

Open an issue with:
- command line used
- tool version (`abicheck --version`)
- minimal header + `.so` pair
- JSON output (`--format json`)
