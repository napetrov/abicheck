#!/usr/bin/env bash
# Main entrypoint for the abicheck GitHub Action.
# Assembles the CLI command from INPUT_* environment variables,
# runs abicheck, captures the exit code, and sets outputs.
set -uo pipefail

# ---------------------------------------------------------------------------
# Helper: append a flag with value(s) to the command array.
# Space-separated values become repeated flags (e.g. -H a.h -H b.h).
# Note: Paths containing spaces are not supported — word-splitting is
# intentional here but will break on space-containing values.
# ---------------------------------------------------------------------------
add_flag() {
  local flag="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    for item in $value; do
      CMD+=("$flag" "$item")
    done
  fi
}

add_single_flag() {
  local flag="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    CMD+=("$flag" "$value")
  fi
}

# ---------------------------------------------------------------------------
# Build the abicheck command
# ---------------------------------------------------------------------------
CMD=(abicheck)

MODE="${INPUT_MODE:-compare}"

# ---------------------------------------------------------------------------
# Baseline auto-fetch: resolve INPUT_ABI_BASELINE → INPUT_OLD_LIBRARY
# ---------------------------------------------------------------------------
ABI_BASELINE="${INPUT_ABI_BASELINE:-}"
if [[ -n "$ABI_BASELINE" && "$MODE" == "compare" ]]; then
  BASELINE_DIR=$(mktemp -d)
  if [[ "$ABI_BASELINE" == "latest-release" ]]; then
    echo "::group::Fetch ABI baseline from latest release"
    if ! gh release download --pattern '*.abicheck.json' -D "$BASELINE_DIR" 2>&1; then
      echo "::error::No ABI baseline found in latest release. Run 'abicheck dump --output-name auto' in your release workflow and upload the *.abicheck.json file as a release asset."
      exit 1
    fi
    echo "::endgroup::"
  elif [[ -f "$ABI_BASELINE" ]]; then
    # Direct file path — use as-is
    cp "$ABI_BASELINE" "$BASELINE_DIR/"
  else
    # Treat as a tag name
    echo "::group::Fetch ABI baseline from release $ABI_BASELINE"
    if ! gh release download "$ABI_BASELINE" --pattern '*.abicheck.json' -D "$BASELINE_DIR" 2>&1; then
      echo "::error::No ABI baseline found in release '$ABI_BASELINE'. Ensure the release has a *.abicheck.json asset."
      exit 1
    fi
    echo "::endgroup::"
  fi
  # Pick the first .abicheck.json found
  BASELINE_FILE=$(find "$BASELINE_DIR" -name '*.abicheck.json' | head -1)
  if [[ -z "$BASELINE_FILE" ]]; then
    echo "::error::No *.abicheck.json file found after download."
    exit 1
  fi
  echo "Using ABI baseline: $BASELINE_FILE"
  INPUT_OLD_LIBRARY="$BASELINE_FILE"
fi

if [[ "$MODE" == "dump" ]]; then
  # ── Dump mode ───────────────────────────────────────────────────────────
  CMD+=(dump)
  CMD+=("${INPUT_NEW_LIBRARY:?new-library is required}")

  add_flag "-H" "${INPUT_HEADER:-}"
  add_flag "-H" "${INPUT_NEW_HEADER:-}"
  add_flag "-I" "${INPUT_INCLUDE:-}"
  add_flag "-I" "${INPUT_NEW_INCLUDE:-}"
  add_single_flag "--version" "${INPUT_NEW_VERSION:-}"
  add_single_flag "--lang" "${INPUT_LANG:-}"
  add_single_flag "--gcc-path" "${INPUT_GCC_PATH:-}"
  add_single_flag "--gcc-prefix" "${INPUT_GCC_PREFIX:-}"
  add_single_flag "--gcc-options" "${INPUT_GCC_OPTIONS:-}"
  add_single_flag "--sysroot" "${INPUT_SYSROOT:-}"

  if [[ "${INPUT_NOSTDINC:-false}" == "true" ]]; then
    CMD+=(--nostdinc)
  fi

  if [[ "${INPUT_FOLLOW_DEPS:-false}" == "true" ]]; then
    CMD+=(--follow-deps)
    add_flag "--search-path" "${INPUT_SEARCH_PATH:-}"
    add_single_flag "--ld-library-path" "${INPUT_LD_LIBRARY_PATH:-}"
  fi

  # Output file — required for dump in action context (otherwise stdout)
  OUTPUT_FILE="${INPUT_OUTPUT_FILE:-abicheck-baseline.json}"
  CMD+=(-o "$OUTPUT_FILE")

elif [[ "$MODE" == "compare" ]]; then
  # ── Compare mode ────────────────────────────────────────────────────────
  CMD+=(compare)
  CMD+=("${INPUT_OLD_LIBRARY:?old-library is required for compare mode}")
  CMD+=("${INPUT_NEW_LIBRARY:?new-library is required}")

  add_flag "-H" "${INPUT_HEADER:-}"
  add_flag "--old-header" "${INPUT_OLD_HEADER:-}"
  add_flag "--new-header" "${INPUT_NEW_HEADER:-}"
  add_flag "-I" "${INPUT_INCLUDE:-}"
  add_flag "--old-include" "${INPUT_OLD_INCLUDE:-}"
  add_flag "--new-include" "${INPUT_NEW_INCLUDE:-}"
  add_single_flag "--old-version" "${INPUT_OLD_VERSION:-}"
  add_single_flag "--new-version" "${INPUT_NEW_VERSION:-}"
  add_single_flag "--lang" "${INPUT_LANG:-}"

  # Format — for SARIF, always write to a file so upload-sarif can find it
  FORMAT="${INPUT_FORMAT:-markdown}"
  CMD+=(--format "$FORMAT")

  OUTPUT_FILE="${INPUT_OUTPUT_FILE:-}"
  if [[ "$FORMAT" == "sarif" && -z "$OUTPUT_FILE" ]]; then
    OUTPUT_FILE="abicheck-results.sarif"
  fi
  if [[ -n "$OUTPUT_FILE" ]]; then
    CMD+=(-o "$OUTPUT_FILE")
  fi

  add_single_flag "--policy" "${INPUT_POLICY:-}"
  add_single_flag "--policy-file" "${INPUT_POLICY_FILE:-}"
  add_single_flag "--suppress" "${INPUT_SUPPRESS:-}"

  # Severity configuration
  add_single_flag "--severity-preset" "${INPUT_SEVERITY_PRESET:-}"
  add_single_flag "--severity-addition" "${INPUT_SEVERITY_ADDITION:-}"

  if [[ "${INPUT_FOLLOW_DEPS:-false}" == "true" ]]; then
    CMD+=(--follow-deps)
    add_flag "--search-path" "${INPUT_SEARCH_PATH:-}"
    add_single_flag "--ld-library-path" "${INPUT_LD_LIBRARY_PATH:-}"
  fi

  # Note: --gcc-path, --gcc-prefix, --gcc-options, --sysroot, --nostdinc are
  # dump-only flags. In compare mode abicheck performs the dump internally
  # when an input is a binary, but these cross-compilation flags are not
  # exposed on the compare CLI. They are only passed in dump mode.

elif [[ "$MODE" == "appcompat" ]]; then
  # ── Appcompat mode ─────────────────────────────────────────────────────
  CMD+=(appcompat)
  CMD+=("${INPUT_APP_BINARY:?app-binary is required for appcompat mode}")

  CHECK_AGAINST="${INPUT_CHECK_AGAINST:-}"
  if [[ -n "$CHECK_AGAINST" ]]; then
    # Weak mode: symbol availability check only (no old library needed)
    CMD+=(--check-against "$CHECK_AGAINST")
  else
    # Full mode: old + new library comparison
    CMD+=("${INPUT_OLD_LIBRARY:?old-library is required for appcompat full mode (or use check-against for weak mode)}")
    CMD+=("${INPUT_NEW_LIBRARY:?new-library is required for appcompat full mode}")
  fi

  add_flag "-H" "${INPUT_HEADER:-}"
  add_flag "--old-header" "${INPUT_OLD_HEADER:-}"
  add_flag "--new-header" "${INPUT_NEW_HEADER:-}"
  add_flag "-I" "${INPUT_INCLUDE:-}"
  add_flag "--old-include" "${INPUT_OLD_INCLUDE:-}"
  add_flag "--new-include" "${INPUT_NEW_INCLUDE:-}"
  add_single_flag "--old-version" "${INPUT_OLD_VERSION:-}"
  add_single_flag "--new-version" "${INPUT_NEW_VERSION:-}"
  add_single_flag "--lang" "${INPUT_LANG:-}"

  # Format — appcompat only supports markdown and json
  FORMAT="${INPUT_FORMAT:-markdown}"
  if [[ "$FORMAT" != "markdown" && "$FORMAT" != "json" ]]; then
    echo "::warning::appcompat mode only supports 'markdown' and 'json' formats. Falling back to 'markdown'."
    FORMAT="markdown"
  fi
  CMD+=(--format "$FORMAT")

  OUTPUT_FILE="${INPUT_OUTPUT_FILE:-}"
  if [[ -n "$OUTPUT_FILE" ]]; then
    CMD+=(-o "$OUTPUT_FILE")
  fi

  add_single_flag "--policy" "${INPUT_POLICY:-}"
  add_single_flag "--policy-file" "${INPUT_POLICY_FILE:-}"
  add_single_flag "--suppress" "${INPUT_SUPPRESS:-}"

  if [[ "${INPUT_SHOW_IRRELEVANT:-false}" == "true" ]]; then
    CMD+=(--show-irrelevant)
  fi

  if [[ "${INPUT_LIST_REQUIRED_SYMBOLS:-false}" == "true" ]]; then
    CMD+=(--list-required-symbols)
  fi

elif [[ "$MODE" == "compare-release" ]]; then
  # ── Compare-release mode (package-level comparison) ──────────────────────
  CMD+=(compare-release)
  CMD+=("${INPUT_OLD_LIBRARY:?old-library is required for compare-release mode}")
  CMD+=("${INPUT_NEW_LIBRARY:?new-library is required}")

  add_flag "-H" "${INPUT_HEADER:-}"
  add_flag "--old-header" "${INPUT_OLD_HEADER:-}"
  add_flag "--new-header" "${INPUT_NEW_HEADER:-}"
  add_flag "-I" "${INPUT_INCLUDE:-}"
  add_single_flag "--old-version" "${INPUT_OLD_VERSION:-}"
  add_single_flag "--new-version" "${INPUT_NEW_VERSION:-}"
  add_single_flag "--lang" "${INPUT_LANG:-}"

  # Format — compare-release only supports markdown and json
  FORMAT="${INPUT_FORMAT:-markdown}"
  if [[ "$FORMAT" != "markdown" && "$FORMAT" != "json" ]]; then
    echo "::warning::compare-release mode only supports 'markdown' and 'json' formats. Falling back to 'markdown'."
    FORMAT="markdown"
  fi
  CMD+=(--format "$FORMAT")

  OUTPUT_FILE="${INPUT_OUTPUT_FILE:-}"
  if [[ -n "$OUTPUT_FILE" ]]; then
    CMD+=(-o "$OUTPUT_FILE")
  fi

  add_single_flag "--policy" "${INPUT_POLICY:-}"
  add_single_flag "--policy-file" "${INPUT_POLICY_FILE:-}"
  add_single_flag "--suppress" "${INPUT_SUPPRESS:-}"

  # Package-specific options
  add_single_flag "--debug-info1" "${INPUT_DEBUG_INFO1:-}"
  add_single_flag "--debug-info2" "${INPUT_DEBUG_INFO2:-}"
  add_single_flag "--devel-pkg1" "${INPUT_DEVEL_PKG1:-}"
  add_single_flag "--devel-pkg2" "${INPUT_DEVEL_PKG2:-}"

  if [[ "${INPUT_DSO_ONLY:-false}" == "true" ]]; then
    CMD+=(--dso-only)
  fi
  if [[ "${INPUT_INCLUDE_PRIVATE_DSO:-false}" == "true" ]]; then
    CMD+=(--include-private-dso)
  fi
  if [[ "${INPUT_KEEP_EXTRACTED:-false}" == "true" ]]; then
    CMD+=(--keep-extracted)
  fi
  if [[ "${INPUT_FAIL_ON_REMOVED_LIBRARY:-false}" == "true" ]]; then
    CMD+=(--fail-on-removed-library)
  fi
  add_single_flag "--jobs" "${INPUT_JOBS:-0}"

elif [[ "$MODE" == "deps" ]]; then
  # ── Deps mode (Linux ELF) ───────────────────────────────────────────────
  CMD+=(deps)
  CMD+=("${INPUT_NEW_LIBRARY:?new-library is required for deps mode}")

  add_single_flag "--sysroot" "${INPUT_SYSROOT:-}"
  add_flag "--search-path" "${INPUT_SEARCH_PATH:-}"
  add_single_flag "--ld-library-path" "${INPUT_LD_LIBRARY_PATH:-}"

  # Format — deps only supports markdown and json
  FORMAT="${INPUT_FORMAT:-markdown}"
  if [[ "$FORMAT" != "markdown" && "$FORMAT" != "json" ]]; then
    echo "::warning::deps mode only supports 'markdown' and 'json' formats. Falling back to 'markdown'."
    FORMAT="markdown"
  fi
  CMD+=(--format "$FORMAT")

  OUTPUT_FILE="${INPUT_OUTPUT_FILE:-}"
  if [[ -n "$OUTPUT_FILE" ]]; then
    CMD+=(-o "$OUTPUT_FILE")
  fi

elif [[ "$MODE" == "stack-check" ]]; then
  # ── Stack-check mode (Linux ELF) ────────────────────────────────────────
  CMD+=(stack-check)
  CMD+=("${INPUT_NEW_LIBRARY:?new-library (binary path) is required for stack-check mode}")
  CMD+=(--baseline "${INPUT_BASELINE:?baseline is required for stack-check mode}")
  CMD+=(--candidate "${INPUT_CANDIDATE:?candidate is required for stack-check mode}")

  add_flag "--search-path" "${INPUT_SEARCH_PATH:-}"
  add_single_flag "--ld-library-path" "${INPUT_LD_LIBRARY_PATH:-}"

  # Format — stack-check only supports markdown and json
  FORMAT="${INPUT_FORMAT:-markdown}"
  if [[ "$FORMAT" != "markdown" && "$FORMAT" != "json" ]]; then
    echo "::warning::stack-check mode only supports 'markdown' and 'json' formats. Falling back to 'markdown'."
    FORMAT="markdown"
  fi
  CMD+=(--format "$FORMAT")

  OUTPUT_FILE="${INPUT_OUTPUT_FILE:-}"
  if [[ -n "$OUTPUT_FILE" ]]; then
    CMD+=(-o "$OUTPUT_FILE")
  fi

else
  echo "::error::Unknown mode '$MODE'. Use 'compare', 'compare-release', 'dump', 'appcompat', 'deps', or 'stack-check'."
  exit 1
fi

if [[ "${INPUT_VERBOSE:-false}" == "true" ]]; then
  CMD+=(-v)
fi

# ---------------------------------------------------------------------------
# Run abicheck
# ---------------------------------------------------------------------------
# Append extra-args (pass-through CLI arguments)
if [[ -n "${INPUT_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  CMD+=($INPUT_EXTRA_ARGS)
fi

echo "::group::abicheck $MODE"
echo "Command: ${CMD[*]}"
echo ""

ABICHECK_EXIT=0
ABICHECK_OUTPUT=""
STDERR_FILE=$(mktemp)
trap 'rm -f "$STDERR_FILE"' EXIT

if [[ -n "${OUTPUT_FILE:-}" ]]; then
  # Output goes to file; capture stderr separately for error detection
  "${CMD[@]}" 2>"$STDERR_FILE" || ABICHECK_EXIT=$?
  if [[ -s "$STDERR_FILE" ]]; then
    cat "$STDERR_FILE" >&2
  fi
else
  # Capture stdout for job summary; stderr goes to temp file
  ABICHECK_OUTPUT=$("${CMD[@]}" 2>"$STDERR_FILE") || ABICHECK_EXIT=$?
  echo "$ABICHECK_OUTPUT"
  if [[ -s "$STDERR_FILE" ]]; then
    cat "$STDERR_FILE" >&2
  fi
fi
echo "::endgroup::"

# ---------------------------------------------------------------------------
# Map exit code to verdict
# ---------------------------------------------------------------------------
STDERR_CONTENT=""
if [[ -s "$STDERR_FILE" ]]; then
  STDERR_CONTENT=$(cat "$STDERR_FILE")
fi

_is_cli_error() {
  echo "$STDERR_CONTENT" | grep -qE '(^Usage:|^Error:|^Try |Traceback|click\.)'
}

if [[ "$MODE" == "stack-check" ]]; then
  # stack-check exit codes: 0=PASS, 1=WARN, 4=FAIL
  if _is_cli_error; then
    VERDICT="ERROR"
    echo "::error::abicheck stack-check failed due to a CLI error (exit code $ABICHECK_EXIT)."
  else
    case $ABICHECK_EXIT in
      0) VERDICT="PASS" ;;
      1) VERDICT="WARN" ;;
      4) VERDICT="FAIL" ;;
      *) VERDICT="ERROR" ;;
    esac
  fi

elif [[ "$MODE" == "deps" ]]; then
  # deps exit codes: 0=OK, 1=missing deps/symbols
  if _is_cli_error; then
    VERDICT="ERROR"
    echo "::error::abicheck deps failed due to a CLI error (exit code $ABICHECK_EXIT)."
  else
    case $ABICHECK_EXIT in
      0) VERDICT="PASS" ;;
      1) VERDICT="FAIL" ;;
      *) VERDICT="ERROR" ;;
    esac
  fi

elif [[ "$MODE" == "dump" ]]; then
  # dump exit codes: 0=success, anything else=error.
  # dump never produces API_BREAK/BREAKING/SEVERITY_ERROR verdicts.
  if [[ $ABICHECK_EXIT -eq 0 ]]; then
    VERDICT="COMPATIBLE"
  else
    VERDICT="ERROR"
    if _is_cli_error; then
      echo "::error::abicheck dump failed due to a CLI argument or configuration error (exit code $ABICHECK_EXIT)."
    else
      echo "::error::abicheck dump failed (exit code $ABICHECK_EXIT)."
    fi
  fi

elif [[ "$MODE" == "appcompat" ]]; then
  # appcompat exit codes: 0=compatible, 2=API_BREAK, 4=BREAKING
  # No severity support — exit code 1 is always a CLI error.
  if [[ $ABICHECK_EXIT -eq 2 ]] && echo "$STDERR_CONTENT" | grep -qE '(^Usage:|^Error:|^Try )'; then
    VERDICT="ERROR"
    echo "::error::abicheck appcompat failed due to a CLI argument or configuration error (exit code 2)."
    echo "::error::Check the command and inputs above. This is NOT an API break — the check did not run."
  else
    case $ABICHECK_EXIT in
      0) VERDICT="COMPATIBLE" ;;
      2) VERDICT="API_BREAK" ;;
      4) VERDICT="BREAKING" ;;
      *)
        VERDICT="ERROR"
        if _is_cli_error; then
          echo "::error::abicheck appcompat failed due to a CLI error (exit code $ABICHECK_EXIT)."
        fi
        ;;
    esac
  fi

elif [[ "$MODE" == "compare-release" ]]; then
  # compare-release exit codes: 0=compatible, 2=API_BREAK, 4=BREAKING, 8=REMOVED_LIBRARY
  # No severity support — exit code 1 is always a CLI error.
  if [[ $ABICHECK_EXIT -eq 2 ]] && echo "$STDERR_CONTENT" | grep -qE '(^Usage:|^Error:|^Try )'; then
    VERDICT="ERROR"
    echo "::error::abicheck compare-release failed due to a CLI argument or configuration error (exit code 2)."
    echo "::error::Check the command and inputs above. This is NOT an API break — the check did not run."
  else
    case $ABICHECK_EXIT in
      0) VERDICT="COMPATIBLE" ;;
      2) VERDICT="API_BREAK" ;;
      4) VERDICT="BREAKING" ;;
      8) VERDICT="REMOVED_LIBRARY" ;;
      *)
        VERDICT="ERROR"
        if _is_cli_error; then
          echo "::error::abicheck compare-release failed due to a CLI error (exit code $ABICHECK_EXIT)."
        fi
        ;;
    esac
  fi

else
  # compare exit codes: 0=compatible, 1=severity error, 2=API_BREAK, 4=BREAKING
  # Click also uses exit code 2 for usage/argument errors — detect via stderr.
  if [[ $ABICHECK_EXIT -eq 2 ]] && echo "$STDERR_CONTENT" | grep -qE '(^Usage:|^Error:|^Try )'; then
    VERDICT="ERROR"
    echo "::error::abicheck failed due to a CLI argument or configuration error (exit code 2)."
    echo "::error::Check the command and inputs above. This is NOT an API break — the check did not run."
  else
    case $ABICHECK_EXIT in
      0) VERDICT="COMPATIBLE" ;;
      1)
        if _is_cli_error; then
          VERDICT="ERROR"
          echo "::error::abicheck failed due to a CLI argument or configuration error (exit code 1)."
          echo "::error::Check the command and inputs above."
        else
          VERDICT="SEVERITY_ERROR"
        fi
        ;;
      2) VERDICT="API_BREAK" ;;
      4) VERDICT="BREAKING" ;;
      *) VERDICT="ERROR" ;;
    esac
  fi
fi

echo "abicheck verdict: $VERDICT (exit code $ABICHECK_EXIT)"

# ---------------------------------------------------------------------------
# Set outputs
# ---------------------------------------------------------------------------
{
  echo "verdict=$VERDICT"
  echo "exit-code=$ABICHECK_EXIT"
  # Only emit report-path when a real report file was produced
  if [[ -n "${OUTPUT_FILE:-}" && -f "${OUTPUT_FILE}" ]]; then
    echo "report-path=${OUTPUT_FILE}"
  else
    echo "report-path="
  fi
} >> "$GITHUB_OUTPUT"

# ---------------------------------------------------------------------------
# Job Summary
# ---------------------------------------------------------------------------
if [[ "${INPUT_ADD_JOB_SUMMARY:-true}" == "true" && "$MODE" != "dump" ]]; then
  {
    if [[ "$MODE" == "appcompat" ]]; then
      echo "## abicheck Application Compatibility Report"
    else
      echo "## abicheck ABI Compatibility Report"
    fi
    echo ""

    case $VERDICT in
      COMPATIBLE)
        if [[ "$MODE" == "appcompat" ]]; then
          echo "> **Verdict: COMPATIBLE** — Application is safe with the new library."
        else
          echo "> **Verdict: COMPATIBLE** — No binary ABI break detected."
        fi
        ;;
      SEVERITY_ERROR)
        echo "> **Verdict: SEVERITY_ERROR** ⚠️ — Severity-level issue detected (see severity configuration)."
        ;;
      API_BREAK)
        if [[ "$MODE" == "appcompat" ]]; then
          echo "> **Verdict: API_BREAK** — Source-level break affecting application symbols."
        else
          echo "> **Verdict: API_BREAK** — Source-level API break detected. Recompilation required."
        fi
        ;;
      BREAKING)
        if [[ "$MODE" == "appcompat" ]]; then
          echo "> **Verdict: BREAKING** — Binary ABI break or missing symbols affecting the application."
        else
          echo "> **Verdict: BREAKING** — Binary ABI break detected. Existing binaries will fail at runtime."
        fi
        ;;
      REMOVED_LIBRARY)
        echo "> **Verdict: REMOVED_LIBRARY** — A library present in the old package is missing from the new package."
        ;;
      PASS)
        echo "> **Verdict: PASS** — Binary loads and no harmful ABI changes detected."
        ;;
      WARN)
        echo "> **Verdict: WARN** ⚠️ — Binary loads but ABI risk detected in dependencies."
        ;;
      FAIL)
        echo "> **Verdict: FAIL** — Load failure or ABI break in dependency stack."
        ;;
      ERROR)
        echo "> **Verdict: ERROR** — abicheck encountered an error (exit code $ABICHECK_EXIT)."
        ;;
    esac

    echo ""
    echo "| Property | Value |"
    echo "|----------|-------|"
    if [[ "$MODE" == "appcompat" ]]; then
      echo "| Application | \`${INPUT_APP_BINARY:-}\` |"
      if [[ -n "${INPUT_CHECK_AGAINST:-}" ]]; then
        echo "| Check against | \`${INPUT_CHECK_AGAINST}\` |"
      else
        echo "| Old library | \`${INPUT_OLD_LIBRARY:-}\` (${INPUT_OLD_VERSION:-old}) |"
        echo "| New library | \`${INPUT_NEW_LIBRARY:-}\` (${INPUT_NEW_VERSION:-new}) |"
      fi
      echo "| Policy | ${INPUT_POLICY:-strict_abi} |"
    elif [[ "$MODE" == "compare" || "$MODE" == "compare-release" ]]; then
      echo "| Old | \`${INPUT_OLD_LIBRARY:-}\` (${INPUT_OLD_VERSION:-old}) |"
      echo "| New | \`${INPUT_NEW_LIBRARY:-}\` (${INPUT_NEW_VERSION:-new}) |"
      echo "| Policy | ${INPUT_POLICY:-strict_abi} |"
    elif [[ "$MODE" == "stack-check" ]]; then
      echo "| Binary | \`${INPUT_NEW_LIBRARY:-}\` |"
      echo "| Baseline | \`${INPUT_BASELINE:-}\` |"
      echo "| Candidate | \`${INPUT_CANDIDATE:-}\` |"
    elif [[ "$MODE" == "deps" ]]; then
      echo "| Binary | \`${INPUT_NEW_LIBRARY:-}\` |"
    fi
    echo "| Mode | $MODE |"
    echo "| Format | ${FORMAT:-markdown} |"
    if [[ -n "${OUTPUT_FILE:-}" ]]; then
      echo "| Report | \`${OUTPUT_FILE}\` |"
    fi
    echo ""

    # If output was captured (no output-file), include it in summary
    if [[ -n "$ABICHECK_OUTPUT" ]]; then
      echo "<details>"
      echo "<summary>Full report</summary>"
      echo ""
      echo '```'
      echo "$ABICHECK_OUTPUT"
      echo '```'
      echo "</details>"
    fi
  } >> "$GITHUB_STEP_SUMMARY"
fi

# ---------------------------------------------------------------------------
# Determine final exit code based on user preferences
# ---------------------------------------------------------------------------
FINAL_EXIT=0

if [[ "$VERDICT" == "ERROR" ]]; then
  echo "::error::abicheck failed with exit code $ABICHECK_EXIT"
  FINAL_EXIT=1

elif [[ "$MODE" == "stack-check" || "$MODE" == "deps" ]]; then
  # stack-check: FAIL always fails; WARN fails when fail-on-breaking is true
  # deps: FAIL always fails the step
  if [[ "$VERDICT" == "FAIL" ]]; then
    echo "::error::Full-stack check failed (load failure or ABI break)."
    FINAL_EXIT=1
  elif [[ "$VERDICT" == "WARN" && "${INPUT_FAIL_ON_BREAKING:-true}" == "true" ]]; then
    echo "::warning::ABI risk detected in dependency stack. Set fail-on-breaking: false to allow."
    FINAL_EXIT=1
  fi

elif [[ "$MODE" == "dump" ]]; then
  # dump: non-zero is always an error (already mapped to ERROR above)
  :

elif [[ "$MODE" == "appcompat" ]]; then
  # appcompat: same failure flags as compare (fail-on-breaking, fail-on-api-break)
  if [[ "$VERDICT" == "BREAKING" && "${INPUT_FAIL_ON_BREAKING:-true}" == "true" ]]; then
    echo "::error::ABI break or missing symbols affecting application. Set fail-on-breaking: false to continue."
    FINAL_EXIT=1
  fi

  if [[ "$VERDICT" == "API_BREAK" && "${INPUT_FAIL_ON_API_BREAK:-false}" == "true" ]]; then
    echo "::error::API break affecting application. Set fail-on-api-break: false to ignore."
    FINAL_EXIT=1
  fi

elif [[ "$MODE" == "compare-release" ]]; then
  # compare-release: BREAKING/API_BREAK follow fail-on flags; REMOVED_LIBRARY
  # only appears when --fail-on-removed-library was passed to the CLI.
  if [[ "$VERDICT" == "BREAKING" && "${INPUT_FAIL_ON_BREAKING:-true}" == "true" ]]; then
    echo "::error::ABI break detected. Set fail-on-breaking: false to continue despite breaks."
    FINAL_EXIT=1
  fi

  if [[ "$VERDICT" == "API_BREAK" && "${INPUT_FAIL_ON_API_BREAK:-false}" == "true" ]]; then
    echo "::error::API break detected. Set fail-on-api-break: false to ignore API-level breaks."
    FINAL_EXIT=1
  fi

  if [[ "$VERDICT" == "REMOVED_LIBRARY" ]]; then
    echo "::error::Library removed between old and new package. Set fail-on-removed-library: false to allow."
    FINAL_EXIT=1
  fi

else
  # compare mode
  if [[ "$VERDICT" == "BREAKING" && "${INPUT_FAIL_ON_BREAKING:-true}" == "true" ]]; then
    echo "::error::ABI break detected. Set fail-on-breaking: false to continue despite breaks."
    FINAL_EXIT=1
  fi

  if [[ "$VERDICT" == "API_BREAK" && "${INPUT_FAIL_ON_API_BREAK:-false}" == "true" ]]; then
    echo "::error::API break detected. Set fail-on-api-break: false to ignore API-level breaks."
    FINAL_EXIT=1
  fi

  # Severity-driven exit code 1 (from --severity-* flags)
  if [[ "$VERDICT" == "SEVERITY_ERROR" ]]; then
    echo "::error::Severity-level error detected by abicheck."
    FINAL_EXIT=1
  fi
fi

exit $FINAL_EXIT
