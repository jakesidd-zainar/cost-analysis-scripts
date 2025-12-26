#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
from collections import defaultdict
import boto3


def get_account_service_costs(session: boto3.Session):
    """Fetch 30-day costs grouped by linked account and service."""
    ce = session.client("ce")
    end = dt.datetime.now(dt.timezone.utc).date().isoformat()
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=30)).isoformat()

    # Get account names
    account_names = {}
    token = None
    while True:
        kwargs = {
            "TimePeriod": {"Start": start, "End": end},
            "Dimension": "LINKED_ACCOUNT"
        }
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_dimension_values(**kwargs)
        for v in resp.get("DimensionValues", []):
            account_id = v.get("Value")
            attrs = v.get("Attributes")
            if account_id:
                account_names[account_id] = attrs.get("description") if attrs else None
        token = resp.get("NextPageToken")
        if not token:
            break

    # Get costs grouped by account and service
    costs = defaultdict(lambda: defaultdict(float))
    account_totals = defaultdict(float)
    service_totals = defaultdict(float)

    token = None
    while True:
        kwargs = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
                {"Type": "DIMENSION", "Key": "SERVICE"}
            ]
        }
        if token:
            kwargs["NextPageToken"] = token

        resp = ce.get_cost_and_usage(**kwargs)

        for period in resp.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                account_id = group["Keys"][0]
                service = group["Keys"][1]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if amount > 0:
                    costs[account_id][service] += amount
                    account_totals[account_id] += amount
                    service_totals[service] += amount

        token = resp.get("NextPageToken")
        if not token:
            break

    return costs, account_names, account_totals, service_totals


def truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis if too long."""
    if len(s) <= max_len:
        return s
    return s[:max_len - 2] + ".."


def main():
    parser = argparse.ArgumentParser(description="AWS cost matrix by account and service")
    parser.add_argument("--profile", help="AWS profile to use")
    parser.add_argument("--top-services", type=int, default=0,
                        help="Limit to top N services (default: 0 = show all)")
    parser.add_argument("--min-cost", type=float, default=1.0,
                        help="Minimum account cost to include (default: $1)")
    parser.add_argument("--output", "-o", default="account_service_costs.csv",
                        help="CSV output file (default: account_service_costs.csv)")
    args = parser.parse_args()

    if args.profile:
        session = boto3.Session(profile_name=args.profile)
    else:
        session = boto3.Session()

    print("Fetching cost data...")
    costs, account_names, account_totals, service_totals = get_account_service_costs(session)

    # Filter accounts by minimum cost
    accounts = [(aid, total) for aid, total in account_totals.items() if total >= args.min_cost]
    accounts.sort(key=lambda x: x[1], reverse=True)

    # Get services by total spend (all or top N)
    sorted_services = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)
    if args.top_services > 0:
        sorted_services = sorted_services[:args.top_services]
    service_names = [s[0] for s in sorted_services]

    if not accounts:
        print("No accounts found with costs above minimum threshold.")
        return

    # Column widths
    name_width = 20
    id_width = 14
    total_width = 10
    svc_width = 12

    # Header
    header = f"{'Account':<{name_width}}  {'ID':<{id_width}}  {'Total':>{total_width}}"
    for svc in service_names:
        header += f"  {truncate(svc, svc_width):>{svc_width}}"

    separator = "-" * len(header)

    svc_label = f"top {args.top_services}" if args.top_services > 0 else f"all {len(service_names)}"
    print(f"\nCost breakdown by account and service (30 days, {svc_label} services):\n")
    print(header)
    print(separator)

    grand_total = 0
    for account_id, total in accounts:
        name = truncate(account_names.get(account_id) or "(no name)", name_width)
        row = f"{name:<{name_width}}  {account_id:<{id_width}}  ${total:>{total_width - 1},.0f}"

        for svc in service_names:
            svc_cost = costs[account_id].get(svc, 0)
            if svc_cost >= 1:
                row += f"  ${svc_cost:>{svc_width - 1},.0f}"
            else:
                row += f"  {'-':>{svc_width}}"

        print(row)
        grand_total += total

    # Footer with service totals
    print(separator)
    footer = f"{'TOTAL':<{name_width}}  {'':<{id_width}}  ${grand_total:>{total_width - 1},.0f}"
    for svc in service_names:
        svc_total = service_totals.get(svc, 0)
        footer += f"  ${svc_total:>{svc_width - 1},.0f}"
    print(footer)

    # Write CSV
    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)

        # Header row
        header_row = ["Account", "Account ID", "Total"] + service_names
        writer.writerow(header_row)

        # Data rows
        for account_id, total in accounts:
            name = account_names.get(account_id) or ""
            row = [name, account_id, round(total, 2)]
            for svc in service_names:
                row.append(round(costs[account_id].get(svc, 0), 2))
            writer.writerow(row)

        # Total row
        total_row = ["TOTAL", "", round(grand_total, 2)]
        for svc in service_names:
            total_row.append(round(service_totals.get(svc, 0), 2))
        writer.writerow(total_row)

    print(f"\nCSV written to: {args.output}")


if __name__ == "__main__":
    main()
