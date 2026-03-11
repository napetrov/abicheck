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

## 3) "Why is compat mode missing API_BREAK?"

`abicheck compat` follows ABICC verdict vocabulary and does not emit `API_BREAK`.
Use `abicheck compare` if you need explicit source-level verdicts.

---

## 4) "Why are deep type changes not detected?"

Check if binary is stripped (no DWARF):

```bash
readelf --debug-dump=info libfoo.so >/dev/null 2>&1 || echo "No DWARF"
```

Without DWARF, Tier 3/4 checks are limited. Use debug builds for deeper analysis.

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

