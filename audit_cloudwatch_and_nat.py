import boto3
from datetime import datetime, timedelta

# --- CONFIGURATION ---
AWS_PROFILE = 'default'
REGION = 'us-west-2'  # Check us-east-1 too if you have global infra
DAYS_TO_ANALYZE = 30   # Look at last 7 days for ingestion rates

def audit_cloudwatch():
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    logs_client = session.client('logs')
    cw_client = session.client('cloudwatch')
    ec2_client = session.client('ec2')

    print(f"--- 🕵️‍♂️  CloudWatch & Data Transfer Audit: {AWS_PROFILE} ({REGION}) ---\n")

    # =========================================================
    # 1. Audit Log Groups (Storage & Retention)
    # =========================================================
    print("1️⃣  Scanning Log Groups for Storage & Retention Issues...")
    
    # Paginator to get all log groups
    paginator = logs_client.get_paginator('describe_log_groups')
    all_groups = []
    
    for page in paginator.paginate():
        all_groups.extend(page['logGroups'])

    # Sort by storedBytes (descending)
    sorted_groups = sorted(all_groups, key=lambda x: x.get('storedBytes', 0), reverse=True)
    
    top_n = 10
    print(f"\n   Top {top_n} Largest Log Groups (by Stored Data):")
    print(f"   {'Log Group Name':<50} | {'Size (GB)':<10} | {'Retention'}")
    print("   " + "-"*85)

    for group in sorted_groups[:top_n]:
        size_gb = group.get('storedBytes', 0) / (1024 ** 3)
        retention = f"{group.get('retentionInDays', 'Forever ❌')} days"
        
        # Flag "Forever" retention on large groups
        if 'retentionInDays' not in group:
            retention = "\033[91mForever ❌\033[0m" # Red text for emphasis if supported
        
        print(f"   {group['logGroupName'][-50:]:<50} | {size_gb:<10.2f} | {retention}")

    # =========================================================
    # 2. Audit Log Ingestion (Real-time "Write" Costs)
    # =========================================================
    print(f"\n2️⃣  Checking Ingestion Volume (Last {DAYS_TO_ANALYZE} Days)...")
    print("   (Querying 'IncomingBytes' metric - this drives ingestion costs)")
    
    start_time = datetime.utcnow() - timedelta(days=DAYS_TO_ANALYZE)
    end_time = datetime.utcnow()
    
    print(f"   {'Log Group Name':<50} | {'Ingested (GB)':<10} | {'Est. Cost ($0.50/GB)'}")
    print("   " + "-"*85)

    for group in sorted_groups[:5]: # Check top 5 largest groups for ingestion activity
        group_name = group['logGroupName']
        
        try:
            response = cw_client.get_metric_statistics(
                Namespace='AWS/Logs',
                MetricName='IncomingBytes',
                Dimensions=[{'Name': 'LogGroupName', 'Value': group_name}],
                StartTime=start_time,
                EndTime=end_time,
                Period=DAYS_TO_ANALYZE * 86400, # Single datapoint for the whole period
                Statistics=['Sum']
            )
            
            if response['Datapoints']:
                bytes_ingested = response['Datapoints'][0]['Sum']
                gb_ingested = bytes_ingested / (1024 ** 3)
                est_cost = gb_ingested * 0.50 # roughly $0.50/GB ingestion in most regions
                print(f"   {group_name[-50:]:<50} | {gb_ingested:<10.2f} | ${est_cost:.2f}")
            else:
                print(f"   {group_name[-50:]:<50} | {'0.00':<10} | $0.00")
        except Exception as e:
            print(f"   Error checking {group_name}: {e}")

    # =========================================================
    # 3. Solve "EC2-Other" Mystery (NAT Gateway Throughput)
    # =========================================================
    print("\n3️⃣  Solving 'EC2 - Other': Checking NAT Gateway Throughput...")
    
    nat_gateways = ec2_client.describe_nat_gateways()['NatGateways']
    
    if not nat_gateways:
        print("   ✅ No NAT Gateways found.")
    else:
        for nat in nat_gateways:
            nat_id = nat['NatGatewayId']
            state = nat['State']
            
            if state != 'available':
                continue

            response = cw_client.get_metric_statistics(
                Namespace='AWS/NATGateway',
                MetricName='BytesProcessed',
                Dimensions=[{'Name': 'NatGatewayId', 'Value': nat_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=DAYS_TO_ANALYZE * 86400,
                Statistics=['Sum']
            )
            
            if response['Datapoints']:
                bytes_processed = response['Datapoints'][0]['Sum']
                gb_processed = bytes_processed / (1024 ** 3)
                cost_processing = gb_processed * 0.045 # $0.045 per GB processed
                print(f"   NAT ID: {nat_id} | Processed: {gb_processed:.2f} GB | Est. Cost: ${cost_processing:.2f}")
            else:
                print(f"   NAT ID: {nat_id} | Processed: 0 GB")

    print("\n--- Audit Complete ---")

if __name__ == "__main__":
    audit_cloudwatch()