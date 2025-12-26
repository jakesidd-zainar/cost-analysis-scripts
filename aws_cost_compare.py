#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
from datetime import datetime
from collections import defaultdict
from typing import Optional
import boto3


def parse_date_range(date_range_str: str) -> tuple[datetime, datetime]:
    """Parse a date range string in format 'dd-mm-yy to dd-mm-yy'."""
    parts = date_range_str.split(" to ")
    if len(parts) != 2:
        raise ValueError(f"Invalid date range format: {date_range_str}. Expected 'dd-mm-yy to dd-mm-yy'")

    start = datetime.strptime(parts[0].strip(), "%d-%m-%y")
    end = datetime.strptime(parts[1].strip(), "%d-%m-%y")
    return start, end


def get_linked_accounts(session: boto3.Session) -> list[tuple[str, Optional[str]]]:
    """Get all linked accounts from Cost Explorer."""
    ce = session.client("ce", region_name="us-east-1")
    end = datetime.utcnow().date().isoformat()
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=90)).isoformat()

    accounts = []
    token = None

    while True:
        kwargs = {"TimePeriod": {"Start": start, "End": end}, "Dimension": "LINKED_ACCOUNT"}
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_dimension_values(**kwargs)

        for v in resp.get("DimensionValues", []):
            account_id = v.get("Value")
            name = None
            attrs = v.get("Attributes")
            if attrs and "description" in attrs:
                name = attrs["description"]
            if account_id:
                accounts.append((account_id, name))

        token = resp.get("NextPageToken")
        if not token:
            break

    # De-duplicate
    seen, dedup = set(), []
    for aid, name in accounts:
        if aid not in seen:
            dedup.append((aid, name))
            seen.add(aid)

    return dedup


def get_service_costs(session: boto3.Session, start_date: datetime, end_date: datetime, account_id: Optional[str] = None) -> dict[str, float]:
    """Get AWS service costs for a given date range, optionally filtered by account."""
    ce = session.client("ce", region_name="us-east-1")

    kwargs = {
        "TimePeriod": {
            "Start": start_date.strftime("%Y-%m-%d"),
            "End": end_date.strftime("%Y-%m-%d")
        },
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [
            {"Type": "DIMENSION", "Key": "SERVICE"}
        ]
    }

    if account_id:
        kwargs["Filter"] = {
            "Dimensions": {
                "Key": "LINKED_ACCOUNT",
                "Values": [account_id]
            }
        }

    response = ce.get_cost_and_usage(**kwargs)

    totals = defaultdict(float)

    for period in response["ResultsByTime"]:
        for group in period["Groups"]:
            service = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[service] += amount

    return dict(totals)


def compare_costs(period1_costs: dict, period2_costs: dict) -> list[dict]:
    """Compare costs between two periods and return sorted comparison data."""
    all_services = set(period1_costs.keys()) | set(period2_costs.keys())

    comparisons = []
    for service in all_services:
        cost1 = period1_costs.get(service, 0.0)
        cost2 = period2_costs.get(service, 0.0)
        diff = cost2 - cost1

        if cost1 > 0:
            pct_change = ((cost2 - cost1) / cost1) * 100
        elif cost2 > 0:
            pct_change = float('inf')  # New service
        else:
            pct_change = 0.0

        comparisons.append({
            "service": service,
            "period1": cost1,
            "period2": cost2,
            "diff": diff,
            "pct_change": pct_change
        })

    # Sort by absolute difference (largest changes first)
    comparisons.sort(key=lambda x: abs(x["diff"]), reverse=True)
    return comparisons


def format_pct(pct: float) -> str:
    """Format percentage change for display."""
    if pct == float('inf'):
        return "NEW"
    elif pct == float('-inf') or (pct < 0 and abs(pct) > 1000):
        return "REMOVED"
    else:
        return f"{pct:+.1f}%"


def format_pct_csv(pct: float) -> str:
    """Format percentage change for CSV output."""
    if pct == float('inf'):
        return "NEW"
    elif pct == float('-inf') or (pct < 0 and abs(pct) > 1000):
        return "REMOVED"
    else:
        return f"{pct:+.1f}%"


def print_comparison_table(comparisons: list[dict], title: str, period1_label: str, period2_label: str):
    """Print a formatted comparison table to the terminal."""
    total1 = sum(item["period1"] for item in comparisons)
    total2 = sum(item["period2"] for item in comparisons)
    total_diff = total2 - total1
    total_pct = ((total2 - total1) / total1 * 100) if total1 > 0 else 0

    print()
    print("=" * 94)
    print(f" {title}")
    print("=" * 94)
    print(f"{'SERVICE':<40} {period1_label:>12} {period2_label:>12} {'DIFF':>12} {'CHANGE':>12}")
    print("-" * 94)

    for item in comparisons:
        # Skip negligible costs
        if item["period1"] < 0.01 and item["period2"] < 0.01:
            continue

        service_name = item["service"][:39]
        print(f"{service_name:<40} ${item['period1']:>10.2f} ${item['period2']:>10.2f} ${item['diff']:>+10.2f} {format_pct(item['pct_change']):>12}")

    print("-" * 94)
    print(f"{'TOTAL':<40} ${total1:>10.2f} ${total2:>10.2f} ${total_diff:>+10.2f} {format_pct(total_pct):>12}")
    print("=" * 94)


def main():
    parser = argparse.ArgumentParser(
        description="Compare AWS costs between two date ranges across all linked accounts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python aws_cost_compare.py "01-01-25 to 31-01-25" "01-11-25 to 30-11-25"
  python aws_cost_compare.py "01-06-24 to 30-06-24" "01-06-25 to 30-06-25" --profile myprofile
  python aws_cost_compare.py "01-01-25 to 31-01-25" "01-11-25 to 30-11-25" --output costs.csv
        """
    )
    parser.add_argument("period1", help="First date range (dd-mm-yy to dd-mm-yy)")
    parser.add_argument("period2", help="Second date range (dd-mm-yy to dd-mm-yy)")
    parser.add_argument("--profile", default=None, help="AWS profile name")
    parser.add_argument("--output", "-o", default="cost_comparison.csv", help="Output CSV file (default: cost_comparison.csv)")
    args = parser.parse_args()

    # Parse date ranges
    try:
        start1, end1 = parse_date_range(args.period1)
        start2, end2 = parse_date_range(args.period2)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    # Create session
    if args.profile:
        session = boto3.Session(profile_name=args.profile)
    else:
        session = boto3.Session()

    period1_label = f"{start1.strftime('%b %Y')}"
    period2_label = f"{start2.strftime('%b %Y')}"

    print(f"[INFO] Period 1: {start1.strftime('%d %b %Y')} - {end1.strftime('%d %b %Y')}")
    print(f"[INFO] Period 2: {start2.strftime('%d %b %Y')} - {end2.strftime('%d %b %Y')}")
    print()

    # Discover linked accounts
    print("[INFO] Discovering linked accounts...")
    accounts = get_linked_accounts(session)
    print(f"[INFO] Found {len(accounts)} linked accounts")
    print()

    # Prepare CSV data
    csv_rows = []

    # ========== OVERALL COMPARISON (ALL ACCOUNTS) ==========
    print("[INFO] Fetching overall costs across all accounts...")
    overall_period1 = get_service_costs(session, start1, end1)
    overall_period2 = get_service_costs(session, start2, end2)
    overall_comparisons = compare_costs(overall_period1, overall_period2)

    print_comparison_table(overall_comparisons, "OVERALL - ALL ACCOUNTS", period1_label, period2_label)

    # Add overall to CSV
    for item in overall_comparisons:
        if item["period1"] >= 0.01 or item["period2"] >= 0.01:
            csv_rows.append({
                "account_id": "ALL",
                "account_name": "ALL ACCOUNTS",
                "service": item["service"],
                "period1_cost": round(item["period1"], 2),
                "period2_cost": round(item["period2"], 2),
                "difference": round(item["diff"], 2),
                "pct_change": format_pct_csv(item["pct_change"])
            })

    # Add overall totals to CSV
    overall_total1 = sum(item["period1"] for item in overall_comparisons)
    overall_total2 = sum(item["period2"] for item in overall_comparisons)
    overall_diff = overall_total2 - overall_total1
    overall_pct = ((overall_total2 - overall_total1) / overall_total1 * 100) if overall_total1 > 0 else 0
    csv_rows.append({
        "account_id": "ALL",
        "account_name": "ALL ACCOUNTS",
        "service": "TOTAL",
        "period1_cost": round(overall_total1, 2),
        "period2_cost": round(overall_total2, 2),
        "difference": round(overall_diff, 2),
        "pct_change": format_pct_csv(overall_pct)
    })

    # ========== PER-ACCOUNT COMPARISON ==========
    for account_id, account_name in accounts:
        display_name = account_name or account_id
        print(f"\n[INFO] Fetching costs for account: {display_name} ({account_id})...")

        try:
            acct_period1 = get_service_costs(session, start1, end1, account_id)
            acct_period2 = get_service_costs(session, start2, end2, account_id)
        except Exception as e:
            print(f"[ERROR] Failed to fetch costs for {account_id}: {e}")
            continue

        # Skip accounts with no costs in either period
        if not acct_period1 and not acct_period2:
            print(f"[INFO] No costs found for {display_name}, skipping...")
            continue

        acct_comparisons = compare_costs(acct_period1, acct_period2)

        # Only print if there are meaningful costs
        total1 = sum(item["period1"] for item in acct_comparisons)
        total2 = sum(item["period2"] for item in acct_comparisons)

        if total1 >= 0.01 or total2 >= 0.01:
            print_comparison_table(acct_comparisons, f"{display_name} ({account_id})", period1_label, period2_label)

            # Add to CSV
            for item in acct_comparisons:
                if item["period1"] >= 0.01 or item["period2"] >= 0.01:
                    csv_rows.append({
                        "account_id": account_id,
                        "account_name": account_name or "",
                        "service": item["service"],
                        "period1_cost": round(item["period1"], 2),
                        "period2_cost": round(item["period2"], 2),
                        "difference": round(item["diff"], 2),
                        "pct_change": format_pct_csv(item["pct_change"])
                    })

            # Add account totals to CSV
            total_diff = total2 - total1
            total_pct = ((total2 - total1) / total1 * 100) if total1 > 0 else 0
            csv_rows.append({
                "account_id": account_id,
                "account_name": account_name or "",
                "service": "TOTAL",
                "period1_cost": round(total1, 2),
                "period2_cost": round(total2, 2),
                "difference": round(total_diff, 2),
                "pct_change": format_pct_csv(total_pct)
            })

    # ========== WRITE CSV ==========
    print(f"\n[INFO] Writing CSV to {args.output}...")

    with open(args.output, 'w', newline='') as csvfile:
        fieldnames = ["account_id", "account_name", "service", "period1_cost", "period2_cost", "difference", "pct_change"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # Write header with date range info
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    print(f"[INFO] CSV saved to {args.output}")
    print("\n[INFO] Done!")

    return 0


if __name__ == "__main__":
    exit(main())
