#!/bin/bash
# ----------------------------------------------------------------------------------------------------
# check_gas.sh — Acton/Jest Gas Regression Guard (CI/CD check)
# ----------------------------------------------------------------------------------------------------

SNAPSHOT_FILE=".gas-snapshot"
TEMP_LOG="jest_run.log"

echo "=== Running Subscription Smart Contract Tests ==="
npx jest tests/SubscriptionTolk.spec.ts --verbose > $TEMP_LOG 2>&1
TEST_EXIT_CODE=$?

if [ $TEST_EXIT_CODE -ne 0 ]; then
    echo "ERROR: Test suite failed. Fix tests before checking gas regressions."
    cat $TEMP_LOG
    rm -f $TEMP_LOG
    exit 1
fi

# Extract gas value from test logs
# Format: [GAS_SNAPSHOT] Subscription Payment gas: 14234
CURRENT_GAS=$(grep -oP "\[GAS_SNAPSHOT\] Subscription Payment gas: \K[0-9]+" $TEMP_LOG)

if [ -z "$CURRENT_GAS" ]; then
    echo "WARNING: Could not find gas snapshot logs in test output. Make sure console.log('[GAS_SNAPSHOT] ...') is printed."
    rm -f $TEMP_LOG
    exit 0
fi

echo "Current payment gas usage: $CURRENT_GAS units"

# Check if snapshot file exists
if [ ! -f "$SNAPSHOT_FILE" ]; then
    echo "No existing .gas-snapshot found. Initializing with current gas value: $CURRENT_GAS"
    echo "$CURRENT_GAS" > "$SNAPSHOT_FILE"
    rm -f $TEMP_LOG
    exit 0
fi

# Read baseline gas from snapshot
BASELINE_GAS=$(cat "$SNAPSHOT_FILE")
echo "Baseline payment gas usage: $BASELINE_GAS units"

# Calculate percentage change
DIFFERENCE=$((CURRENT_GAS - BASELINE_GAS))
PERCENT_CHANGE=$(( DIFFERENCE * 100 / BASELINE_GAS ))

echo "Gas change: $PERCENT_CHANGE%"

if [ $PERCENT_CHANGE -gt 5 ]; then
    echo "========================================================================="
    echo "ERROR: Gas consumption increased by $PERCENT_CHANGE% (> 5% threshold limit!)"
    echo "Baseline: $BASELINE_GAS | Current: $CURRENT_GAS"
    echo "Please optimize subscription.tolk or update baseline if changes are intended."
    echo "========================================================================="
    rm -f $TEMP_LOG
    exit 2
else
    echo "SUCCESS: Gas check passed! Within acceptable deviation."
    # Update baseline if gas decreased or within limits
    echo "$CURRENT_GAS" > "$SNAPSHOT_FILE"
fi

rm -f $TEMP_LOG
exit 0
