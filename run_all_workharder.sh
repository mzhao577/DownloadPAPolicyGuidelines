#!/bin/bash
# Run every per-payer "work harder" harvester.
#
#   ./run_all_workharder.sh                 # all payers, sequential
#   ./run_all_workharder.sh Aetna Cigna     # only these payers
#   PARALLEL=4 ./run_all_workharder.sh      # 4 payers at a time
#   EXTRA="--all-versions" ./run_all_workharder.sh
#
# Logs land in ./logs/<Payer>.log and a one-line summary per payer is printed
# at the end.

cd "$(dirname "$0")" || exit 1
mkdir -p logs

PAYERS=(Aetna UnitedHealthcare Cigna Humana Anthem Horizon Medica AveraCare \
        BCBS_AZ EviCore Carelon AvMed BannerHealth EverNorth DeanHealth \
        USFamilyHealth Highmark OneCare)
[ $# -gt 0 ] && PAYERS=("$@")

PARALLEL=${PARALLEL:-1}
running=0
for payer in "${PAYERS[@]}"; do
    script="download_${payer}_precert_policies_workharder.py"
    if [ ! -f "$script" ]; then
        echo "!! no script for $payer ($script)"
        continue
    fi
    echo ">> $payer"
    if [ "$PARALLEL" -gt 1 ]; then
        python3 "$script" $EXTRA >"logs/${payer}.log" 2>&1 &
        running=$((running + 1))
        if [ "$running" -ge "$PARALLEL" ]; then wait -n 2>/dev/null || wait; running=$((running - 1)); fi
    else
        python3 "$script" $EXTRA >"logs/${payer}.log" 2>&1
        tail -3 "logs/${payer}.log"
    fi
done
wait

echo
echo "===================== SUMMARY ====================="
for payer in "${PAYERS[@]}"; do
    [ -f "logs/${payer}.log" ] || continue
    printf '%-18s %s\n' "$payer" "$(grep -E '^[A-Za-z_]+: [0-9]+ new file' "logs/${payer}.log" | tail -1)"
done
echo
echo "File counts per payer folder:"
for d in downloaded/*/; do
    printf '  %-18s %s\n' "$(basename "$d")" "$(find "$d" -type f | wc -l | tr -d ' ')"
done
