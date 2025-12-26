# Claude Project Context

## Overview

This repository contains Python scripts for auditing AWS costs and resources across AWS Organizations. The scripts help identify cost optimization opportunities and resource waste.

## Tech Stack

- Python 3.9+
- boto3 (AWS SDK)
- No external dependencies beyond boto3

## Architecture

All scripts use the boto3 credential chain for authentication:
1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
2. Named profiles in `~/.aws/credentials`
3. IAM roles (when running on EC2/Lambda)

For Organization-wide scripts, cross-account access uses STS AssumeRole with `OrganizationAccountAccessRole`.

## Key Patterns

- **Cost Explorer API**: Used for cost queries (`ce.get_cost_and_usage`, `ce.get_dimension_values`)
- **Pagination**: All list operations handle pagination tokens
- **Cross-account access**: Management account assumes roles into member accounts
- **Region iteration**: Some scripts iterate through all enabled regions

## Scripts Summary

| Script | Scope | Purpose |
|--------|-------|---------|
| `list_accounts.py` | Org-wide | List accounts with 30-day spend |
| `account_service_costs.py` | Org-wide | Cost matrix by account/service |
| `aws_cost_compare.py` | Org-wide | Compare costs between date ranges |
| `aws_cost.py` | Org-wide | Service costs by account and region |
| `org_audit.py` | Org-wide | Audit waste across all accounts |
| `audit_ec2_waste.py` | Single account | EBS volumes and snapshots audit |
| `audit_cloudwatch_and_nat.py` | Single account | CloudWatch logs and NAT audit |

## Code Style

- Scripts are standalone (no shared modules)
- Configuration via constants at top of file or CLI arguments
- argparse for CLI interfaces
- CSV output for data export
- Console output with emoji indicators for readability

## Common Tasks

When modifying these scripts:
- Maintain backward compatibility with existing CLI arguments
- Use boto3 paginators where available
- Handle `ClientError` exceptions for API calls
- Keep scripts self-contained (no cross-imports)
