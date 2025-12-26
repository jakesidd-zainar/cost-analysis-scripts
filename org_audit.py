import boto3
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError

# --- CONFIGURATION ---
AWS_PROFILE = 'RootAdminAccess'  # Your Root Account profile
TARGET_REGIONS = ['us-west-2', 'us-east-1']  # Add your regions here
ROLE_NAME = 'OrganizationAccountAccessRole'  # Default AWS Org role name

def get_org_accounts(session):
    """List all ACTIVE accounts in the Organization"""
    org_client = session.client('organizations')
    accounts = []
    paginator = org_client.get_paginator('list_accounts')
    
    print("📋 Fetching account list from Organization...")
    for page in paginator.paginate():
        for acct in page['Accounts']:
            if acct['Status'] == 'ACTIVE':
                accounts.append(acct)
    
    print(f"   Found {len(accounts)} active accounts.")
    return accounts

def assume_role_session(root_session, account_id, account_name):
    """Create a boto3 session for a child account by assuming the Org role"""
    sts_client = root_session.client('sts')
    role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
    
    try:
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"AuditSession-{account_id}"
        )
        creds = response['Credentials']
        
        # Create a new session using the temporary credentials
        return boto3.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken']
        )
    except ClientError as e:
        print(f"   ❌ Could not access {account_name} ({account_id}): {e}")
        return None

def audit_account(session, account_name, region):
    """Run the audit logic for a specific account/region"""
    ec2 = session.resource('ec2', region_name=region)
    cw_client = session.client('cloudwatch', region_name=region)
    
    # 1. Check for Unattached Volumes (The Hidden EBS Cost)
    volumes = ec2.volumes.filter(Filters=[{'Name': 'status', 'Values': ['available']}])
    vol_waste = 0
    vol_count = 0
    
    for vol in volumes:
        vol_count += 1
        vol_waste += vol.size

    if vol_count > 0:
        print(f"      ⚠️  [EBS Waste] {vol_count} unattached volumes ({vol_waste} GB)")

    # 2. Check for Expensive NAT Gateways (The "EC2-Other" Cost)
    ec2_client = session.client('ec2', region_name=region)
    nats = ec2_client.describe_nat_gateways()['NatGateways']
    
    for nat in nats:
        if nat['State'] == 'available':
            # Check 7-day throughput
            metrics = cw_client.get_metric_statistics(
                Namespace='AWS/NATGateway',
                MetricName='BytesProcessed',
                Dimensions=[{'Name': 'NatGatewayId', 'Value': nat['NatGatewayId']}],
                StartTime=datetime.utcnow() - timedelta(days=7),
                EndTime=datetime.utcnow(),
                Period=604800,
                Statistics=['Sum']
            )
            if metrics['Datapoints']:
                gb = metrics['Datapoints'][0]['Sum'] / (1024**3)
                if gb > 10:  # Only noise if > 10GB processed
                    print(f"      💸 [NAT Gateway] {nat['NatGatewayId']} processed {gb:.2f} GB (last 7 days)")

    # 3. Check for Old Snapshots
    # (Simplified for speed: just counting them)
    snapshot_iterator = ec2.snapshots.filter(OwnerIds=['self'])
    old_snap_count = 0
    limit_date = datetime.now(timezone.utc) - timedelta(days=30)
    
    for snap in snapshot_iterator:
        if snap.start_time < limit_date:
            old_snap_count += 1
            
    if old_snap_count > 0:
         print(f"      📸 [Old Snapshots] {old_snap_count} snapshots older than 30 days")

def main():
    root_session = boto3.Session(profile_name=AWS_PROFILE)
    
    # 1. Get List of Accounts
    accounts = get_org_accounts(root_session)
    
    print(f"\n🚀 Starting audit across {len(accounts)} accounts and regions: {TARGET_REGIONS}\n")

    for acct in accounts:
        acct_id = acct['Id']
        acct_name = acct['Name']
        
        # Skip the root account itself if you only want to check children, 
        # or handle it separately (root doesn't need assume_role)
        if acct_id == root_session.client('sts').get_caller_identity()['Account']:
            print(f"➡️  Scanning ROOT account: {acct_name}...")
            target_session = root_session
        else:
            print(f"➡️  Scanning Linked Account: {acct_name} ({acct_id})...")
            target_session = assume_role_session(root_session, acct_id, acct_name)
        
        if not target_session:
            continue
            
        for region in TARGET_REGIONS:
            try:
                # print(f"   📍 Region: {region}")
                audit_account(target_session, acct_name, region)
            except ClientError as e:
                print(f"      ❌ Error in {region}: {e}")

if __name__ == "__main__":
    main()