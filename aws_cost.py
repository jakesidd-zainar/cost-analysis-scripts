#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from pprint import pprint
import boto3
from botocore.exceptions import ClientError, BotoCoreError

# -------------------------
# Utility
# -------------------------

def utc_now():
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)


# -------------------------
# Account & Role Handling
# -------------------------

def assume_role(sts, account_id: str, role_names: List[str], session_name_prefix="KinesisAudit") -> Optional[boto3.Session]:
    for rn in role_names:
        role_arn = f"arn:aws:iam::{account_id}:role/{rn}"
        try:
            resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=f"{session_name_prefix}-{int(time.time())}")
            creds = resp["Credentials"]
            return boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"]
            )
        except ClientError:
            continue
    return None


def get_linked_accounts_ce(session: boto3.Session) -> List[Tuple[str, Optional[str]]]:
    ce = session.client("ce")
    end = utc_now().date().isoformat()
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=30)).isoformat()

    out = []
    token = None

    while True:
        kwargs = {"TimePeriod": {"Start": start, "End": end}, "Dimension": "LINKED_ACCOUNT"}
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_dimension_values(**kwargs)

        for v in resp.get("DimensionValues", []):
            aid = v.get("Value")
            name = None
            attrs = v.get("Attributes")
            if attrs and "description" in attrs:
                name = attrs["description"]
            if aid:
                out.append((aid, name))

        token = resp.get("NextPageToken")
        if not token:
            break

    # De-duplicate
    seen, dedup = set(), []
    for aid, name in out:
        if aid not in seen:
            dedup.append((aid, name))
            seen.add(aid)

    return dedup


# -------------------------
# Kinesis Listing
# -------------------------

def list_enabled_regions(sess: boto3.Session) -> List[str]:
    ec2 = sess.client("ec2", region_name="us-east-1")
    regions = ec2.describe_regions(AllRegions=True)["Regions"]
    enabled = [r["RegionName"] for r in regions if r.get("OptInStatus") in (None, "opt-in-not-required", "opted-in")]
    return sorted(enabled)
def get_aws_service_totals_last_30_days(sess: boto3.Session, region: str) -> Dict[str, str]:
    """
    Returns a dictionary mapping:
        service_name -> total_cost_usd (float)
    For the last 30 days.
    """
    ce = sess.client("ce",region_name=region)

    end = datetime.utcnow().date()
    start = end - timedelta(days=30)

    response = ce.get_cost_and_usage(
        TimePeriod={
            "Start": start.strftime("%Y-%m-%d"),
            "End": end.strftime("%Y-%m-%d")
        },
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[
            {"Type": "DIMENSION", "Key": "SERVICE"}
        ]
    )

    totals = defaultdict(int)

    for day in response["ResultsByTime"]:
        for group in day["Groups"]:
            service = group["Keys"][0]
            amount = int(float(group["Metrics"]["UnblendedCost"]["Amount"]))
            totals[service] += amount

    return dict(totals)
# -------------------------
# Main
# -------------------------

def main():
    parser = argparse.ArgumentParser(description="Kinesis Cost & Throughput Report")
    parser.add_argument("--role-names", default="OrganizationAccountAccessRole")
    parser.add_argument("--profiles", default="")
    parser.add_argument("--output", default="kinesis_throughput.csv")
    parser.add_argument("--include-empty", action="store_true")
    parser.add_argument("--account-name")
    parser.add_argument("--account-id")
    args = parser.parse_args()

    role_names = [r.strip() for r in args.role_names.split(",") if r.strip()]
    session = boto3.Session()

    # Discover accounts
    try:
        print("[DEBUG] Starting account discovery...")
        accounts = get_linked_accounts_ce(session)
        print(f"[DEBUG] Found {len(accounts)} accounts")
    except Exception as e:
        print(f"[ERROR] Failed to get linked accounts: {type(e).__name__}: {e}")
        accounts = []

    # Add local profiles
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    for prof in profiles:
        try:
            s = boto3.Session(profile_name=prof)
            aid = s.client("sts").get_caller_identity()["Account"]
            accounts.append((aid, f"profile:{prof}"))
        except Exception:
            pass

    # Dedup
    seen, dedup = set(), []
    for aid, nm in accounts:
        if aid not in seen:
            dedup.append((aid, nm))
            seen.add(aid)

    # Apply filters
    if args.account_id:
        dedup = [(aid, nm) for aid, nm in dedup if aid == args.account_id]

    if args.account_name:
        key = args.account_name.lower()
        dedup = [(aid, nm) for aid, nm in dedup if (nm or "").lower().find(key) >= 0]

    mgmt_sts = session.client("sts")

    rows = []

    for account_id, account_name in dedup:
        print(f"[INFO] Processing account {account_id} ({account_name})")

        assumed = assume_role(mgmt_sts, account_id, role_names)
        if not assumed:
            continue

        try:
            regions = list_enabled_regions(assumed)
        except ClientError:
            continue

        for region in regions:
            summary = get_aws_service_totals_last_30_days(assumed,region)
            sorted_summary = sorted(summary.items(), key=lambda x: x[1], reverse=True)
            costs = False
            # Print key/value pairs
            for key, value in sorted_summary:
                if value > 0:
                    costs = True
            if costs:
                print(f"[INFO]   Found costs in {account_name} {region}")
                for key, value in sorted_summary:
                    print(f"   {key} ${value}")
            break

if __name__ == "__main__":
    main()
