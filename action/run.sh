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

  # API addition detection
  if [[ "${INPUT_FAIL_ON_ADDITIONS:-false}" == "true" ]]; then
    CMD+=(--fail-on-additions)
  fi

  # Note: --gcc-path, --gcc-prefix, --gcc-options, --sysroot, --nostdinc are
  # dump-only flags. In compare mode abicheck performs the dump internally
  # when an input is a binary, but these cross-compilation flags are not
  # exposed on the compare CLI. They are only passed in dump mode.

else
  echo "::error::Unknown mode '$MODE'. Use 'compare' or 'dump'."
  exit 1
fi

if [[ "${INPUT_VERBOSE:-false}" == "true" ]]; then
  CMD+=(-v)
fi

# ---------------------------------------------------------------------------
# Run abicheck
# ---------------------------------------------------------------------------
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
# abicheck exit codes: 0=compatible, 2=API_BREAK, 4=BREAKING.
# However, Click (the CLI framework) also uses exit code 2 for usage/argument
# errors (e.g. invalid option, missing required arg). We distinguish them by
# checking stderr for Click's "Error:" or "Usage:" markers.
STDERR_CONTENT=""
if [[ -s "$STDERR_FILE" ]]; then
  STDERR_CONTENT=$(cat "$STDERR_FILE")
fi

if [[ $ABICHECK_EXIT -eq 2 ]] && echo "$STDERR_CONTENT" | grep -qE '(^Usage:|^Error:|^Try )'; then
  # This is a CLI/argument error, not a real API_BREAK verdict
  VERDICT="ERROR"
  echo "::error::abicheck failed due to a CLI argument or configuration error (exit code 2)."
  echo "::error::Check the command and inputs above. This is NOT an API break — the check did not run."
else
  case $ABICHECK_EXIT in
    0) VERDICT="COMPATIBLE" ;;
    1)
      # Exit code 1 is produced by --fail-on-additions for genuine API expansion.
      # Guard against Click CLI/parse errors that also exit 1 (e.g. bad flags).
      if echo "$STDERR_CONTENT" | grep -qE '(^Usage:|^Error:|^Try |Traceback|click\.)'; then
        VERDICT="ERROR"
        echo "::error::abicheck failed due to a CLI argument or configuration error (exit code 1)."
        echo "::error::Check the command and inputs above."
      else
        VERDICT="ADDITIONS"
      fi
      ;;
    2) VERDICT="API_BREAK" ;;
    4) VERDICT="BREAKING" ;;
    *) VERDICT="ERROR" ;;
  esac
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
if [[ "${INPUT_ADD_JOB_SUMMARY:-true}" == "true" && "$MODE" == "compare" ]]; then
  {
    echo "## abicheck ABI Compatibility Report"
    echo ""

    case $VERDICT in
      COMPATIBLE)
        echo "> **Verdict: COMPATIBLE** — No binary ABI break detected."
        ;;
      ADDITIONS)
        echo "> **Verdict: ADDITIONS** ⚠️ — No binary ABI break, but new public API was added unexpectedly."
        ;;
      API_BREAK)
        echo "> **Verdict: API_BREAK** — Source-level API break detected. Recompilation required."
        ;;
      BREAKING)
        echo "> **Verdict: BREAKING** — Binary ABI break detected. Existing binaries will fail at runtime."
        ;;
      ERROR)
        echo "> **Verdict: ERROR** — abicheck encountered an error (exit code $ABICHECK_EXIT)."
        ;;
    esac

    echo ""
    echo "| Property | Value |"
    echo "|----------|-------|"
    echo "| Old | \`${INPUT_OLD_LIBRARY:-}\` (${INPUT_OLD_VERSION:-old}) |"
    echo "| New | \`${INPUT_NEW_LIBRARY:-}\` (${INPUT_NEW_VERSION:-new}) |"
    echo "| Policy | ${INPUT_POLICY:-strict_abi} |"
    echo "| Format | ${INPUT_FORMAT:-markdown} |"
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

if [[ $ABICHECK_EXIT -eq 4 && "${INPUT_FAIL_ON_BREAKING:-true}" == "true" ]]; then
  echo "::error::ABI break detected. Set fail-on-breaking: false to continue despite breaks."
  FINAL_EXIT=1
fi

if [[ "$VERDICT" == "API_BREAK" && "${INPUT_FAIL_ON_API_BREAK:-false}" == "true" ]]; then
  echo "::error::API break detected. Set fail-on-api-break: false to ignore API-level breaks."
  FINAL_EXIT=1
fi

if [[ "$VERDICT" == "ADDITIONS" && "${INPUT_FAIL_ON_ADDITIONS:-false}" == "true" ]]; then
  echo "::error::API additions detected (unintentional API expansion). Set fail-on-additions: false to allow."
  FINAL_EXIT=1
fi

if [[ "$VERDICT" == "ERROR" ]]; then
  echo "::error::abicheck failed with exit code $ABICHECK_EXIT"
  FINAL_EXIT=1
fi

exit $FINAL_EXIT
