#!/usr/bin/env bash
# Main entrypoint for the abicheck GitHub Action.
# Assembles the CLI command from INPUT_* environment variables,
# runs abicheck, captures the exit code, and sets outputs.
set -uo pipefail

# ---------------------------------------------------------------------------
# Helper: append a flag with value(s) to the command array.
# Space-separated values become repeated flags (e.g. -H a.h -H b.h).
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
  add_single_flag "--gcc-path" "${INPUT_GCC_PATH:-}"
  add_single_flag "--gcc-prefix" "${INPUT_GCC_PREFIX:-}"
  add_single_flag "--gcc-options" "${INPUT_GCC_OPTIONS:-}"
  add_single_flag "--sysroot" "${INPUT_SYSROOT:-}"

  if [[ "${INPUT_NOSTDINC:-false}" == "true" ]]; then
    CMD+=(--nostdinc)
  fi

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
if [[ -n "${OUTPUT_FILE:-}" ]]; then
  # Output goes to file; capture stderr for diagnostics
  "${CMD[@]}" 2>&1 || ABICHECK_EXIT=$?
else
  # Capture stdout for job summary
  ABICHECK_OUTPUT=$("${CMD[@]}" 2>&1) || ABICHECK_EXIT=$?
  echo "$ABICHECK_OUTPUT"
fi
echo "::endgroup::"

# ---------------------------------------------------------------------------
# Map exit code to verdict
# ---------------------------------------------------------------------------
case $ABICHECK_EXIT in
  0) VERDICT="COMPATIBLE" ;;
  2) VERDICT="API_BREAK" ;;
  4) VERDICT="BREAKING" ;;
  *) VERDICT="ERROR" ;;
esac

echo "abicheck verdict: $VERDICT (exit code $ABICHECK_EXIT)"

# ---------------------------------------------------------------------------
# Set outputs
# ---------------------------------------------------------------------------
{
  echo "verdict=$VERDICT"
  echo "exit-code=$ABICHECK_EXIT"
  echo "report-path=${OUTPUT_FILE:-}"
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

if [[ $ABICHECK_EXIT -eq 2 && "${INPUT_FAIL_ON_API_BREAK:-false}" == "true" ]]; then
  echo "::error::API break detected. Set fail-on-api-break: false to ignore API-level breaks."
  FINAL_EXIT=1
fi

if [[ $ABICHECK_EXIT -ne 0 && $ABICHECK_EXIT -ne 2 && $ABICHECK_EXIT -ne 4 ]]; then
  echo "::error::abicheck failed with unexpected exit code $ABICHECK_EXIT"
  FINAL_EXIT=1
fi

exit $FINAL_EXIT
