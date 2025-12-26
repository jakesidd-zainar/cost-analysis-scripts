#!/usr/bin/env python3
import argparse
import datetime as dt
import boto3


def get_linked_accounts(session: boto3.Session):
    """Fetch linked accounts and their 30-day spend from Cost Explorer."""
    ce = session.client("ce")
    end = dt.datetime.now(dt.timezone.utc).date().isoformat()
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=30)).isoformat()

    # Get costs by linked account
    cost_resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}]
    )

    costs_by_account = {}
    for period in cost_resp.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            account_id = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            costs_by_account[account_id] = costs_by_account.get(account_id, 0) + amount

    accounts = []
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
            account_name = None
            attrs = v.get("Attributes")
            if attrs and "description" in attrs:
                account_name = attrs["description"]
            if account_id:
                accounts.append((account_id, account_name))

        token = resp.get("NextPageToken")
        if not token:
            break

    # De-duplicate and add costs
    seen = set()
    unique_accounts = []
    for account_id, account_name in accounts:
        if account_id not in seen:
            cost = costs_by_account.get(account_id, 0.0)
            unique_accounts.append((account_id, account_name, cost))
            seen.add(account_id)

    # Sort by cost descending
    unique_accounts.sort(key=lambda x: x[2], reverse=True)

    return unique_accounts


def main():
    parser = argparse.ArgumentParser(description="List AWS linked accounts")
    parser.add_argument("--profile", help="AWS profile to use")
    args = parser.parse_args()

    if args.profile:
        session = boto3.Session(profile_name=args.profile)
    else:
        session = boto3.Session()

    accounts = get_linked_accounts(session)
    total_spend = sum(cost for _, _, cost in accounts)

    print(f"Found {len(accounts)} linked accounts (30-day total: ${total_spend:,.2f}):\n")
    print(f"  {'Account ID':<14}  {'Cost (30d)':>12}  Name")
    print(f"  {'-'*14}  {'-'*12}  {'-'*20}")
    for account_id, account_name, cost in accounts:
        name = account_name or "(no name)"
        print(f"  {account_id:<14}  ${cost:>11,.2f}  {name}")


if __name__ == "__main__":
    main()
