# AWS Cost & Resource Audit Scripts

A collection of Python scripts for auditing AWS costs, resources, and identifying waste across AWS Organizations.

## Prerequisites

- Python 3.9+
- boto3 library

### Installation

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install boto3
```

## AWS Credentials Setup

These scripts use the standard boto3 credential chain. The easiest method is to copy/paste environment variables from the AWS Access Portal (IAM Identity Center):

1. Log into your AWS Access Portal
2. Click on the account you want to access
3. Click "Command line or programmatic access"
4. Copy the environment variables (Option 1) and paste them into your terminal:

```bash
export AWS_ACCESS_KEY_ID="ASIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
```

Alternatively, you can use named profiles in `~/.aws/credentials` and specify them with `--profile`.

## Scripts

### list_accounts.py

Lists all linked accounts in your AWS Organization with their 30-day spend.

```bash
python list_accounts.py
python list_accounts.py --profile MyProfile
```

**Output:** Table showing account ID, name, and 30-day cost for each linked account.

---

### account_service_costs.py

Generates a cost matrix showing spend by account and AWS service for the last 30 days.

```bash
python account_service_costs.py
python account_service_costs.py --profile MyProfile
python account_service_costs.py --top-services 10  # Limit to top 10 services
python account_service_costs.py --min-cost 100     # Only accounts with >$100 spend
python account_service_costs.py -o my_costs.csv    # Custom output file
```

**Output:** Console table and CSV file (`account_service_costs.csv`).

---

### aws_cost_compare.py

Compares AWS costs between two date ranges across all linked accounts. Useful for month-over-month or year-over-year comparisons.

```bash
python aws_cost_compare.py "01-01-25 to 31-01-25" "01-12-24 to 31-12-24"
python aws_cost_compare.py "01-06-24 to 30-06-24" "01-06-25 to 30-06-25" --profile MyProfile
python aws_cost_compare.py "01-01-25 to 31-01-25" "01-11-25 to 30-11-25" -o comparison.csv
```

**Date format:** `dd-mm-yy to dd-mm-yy`

**Output:** Comparison tables per account showing cost differences and percentage changes, plus CSV export.

---

### aws_cost.py

Reports AWS service costs by account and region for the last 30 days. Iterates through all enabled regions.

```bash
python aws_cost.py
python aws_cost.py --account-name "Production"  # Filter by account name
python aws_cost.py --account-id 123456789012    # Filter by account ID
python aws_cost.py --profiles profile1,profile2 # Include specific profiles
```

---

### org_audit.py

Audits all accounts in an AWS Organization for resource waste:
- Unattached EBS volumes
- NAT Gateway throughput (high data processing costs)
- Old snapshots (>30 days)

**Configuration:** Edit the script to set:
- `AWS_PROFILE`: Your root/management account profile
- `TARGET_REGIONS`: Regions to scan
- `ROLE_NAME`: Cross-account role name (default: `OrganizationAccountAccessRole`)

```bash
python org_audit.py
```

**Output:** Console report of waste found across all accounts and regions.

---

### audit_ec2_waste.py

Single-account audit for EBS waste:
- Unattached (available) EBS volumes with cost estimates
- Old snapshots (>30 days)

**Configuration:** Edit the script to set `AWS_PROFILE` and `REGION`.

```bash
python audit_ec2_waste.py
```

---

### audit_cloudwatch_and_nat.py

Single-account audit for CloudWatch and networking costs:
- Top 10 largest CloudWatch Log Groups (flags "Forever" retention)
- Log ingestion volume and estimated costs
- NAT Gateway throughput and estimated data processing costs

**Configuration:** Edit the script to set `AWS_PROFILE` and `REGION`.

```bash
python audit_cloudwatch_and_nat.py
```

## Required IAM Permissions

These scripts require read-only access to:
- `ce:*` (Cost Explorer)
- `organizations:ListAccounts`
- `sts:AssumeRole` (for cross-account access)
- `ec2:Describe*`
- `logs:DescribeLogGroups`
- `cloudwatch:GetMetricStatistics`

For Organization-wide scripts, you need access to the management account and the `OrganizationAccountAccessRole` (or equivalent) in member accounts.
