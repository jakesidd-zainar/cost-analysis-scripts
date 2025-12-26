import boto3
from datetime import datetime, timezone

# --- CONFIGURATION ---
# Set to 'default' or a specific named profile from your ~/.aws/credentials
AWS_PROFILE = 'default' 
# Region to check (you may need to run this for multiple regions if you operate globally)
REGION = 'us-west-2' 
# Threshold for "Old" snapshots
SNAPSHOT_AGE_DAYS = 30 

def audit_ebs_waste():
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    ec2 = session.resource('ec2')

    print(f"--- Starting Audit for Profile: {AWS_PROFILE} | Region: {REGION} ---\n")

    # 1. Audit Unattached Volumes
    print("🔎 Scanning for Available (Unattached) EBS Volumes...")
    
    volumes = ec2.volumes.filter(
        Filters=[{'Name': 'status', 'Values': ['available']}]
    )

    total_waste_gb = 0
    volume_count = 0
    
    # Pricing estimation (rough estimate based on gp3 generic pricing, varies by region)
    # $0.08 per GB-month is a standard ballpark for gp3
    PRICE_PER_GB = 0.08 

    for vol in volumes:
        volume_count += 1
        total_waste_gb += vol.size
        print(f"  - [WASTE] Vol ID: {vol.id} | Size: {vol.size} GB | Type: {vol.volume_type} | Created: {vol.create_time.date()}")

    if volume_count == 0:
        print("  ✅ No unattached volumes found.")
    else:
        est_cost = total_waste_gb * PRICE_PER_GB
        print(f"\n  ⚠️  SUMMARY: {volume_count} unattached volumes found.")
        print(f"  📉 Total Wasted Storage: {total_waste_gb} GB")
        print(f"  💸 Est. Monthly Waste: ${est_cost:.2f} (assuming gp2/gp3 pricing)")

    print("-" * 40)

    # 2. Audit Old Snapshots
    print(f"\n🔎 Scanning for Snapshots older than {SNAPSHOT_AGE_DAYS} days...")
    
    # We filter for snapshots owned by *self* to avoid seeing public AWS snapshots
    account_id = session.client('sts').get_caller_identity().get('Account')
    snapshots = ec2.snapshots.filter(OwnerIds=[account_id])
    
    old_snapshot_count = 0
    total_snap_size_gb = 0

    now = datetime.now(timezone.utc)

    for snap in snapshots:
        age_days = (now - snap.start_time).days
        if age_days > SNAPSHOT_AGE_DAYS:
            old_snapshot_count += 1
            total_snap_size_gb += snap.volume_size
            # Only printing first 10 to avoid spamming console if you have thousands
            if old_snapshot_count <= 10:
                print(f"  - [OLD] Snap ID: {snap.id} | Age: {age_days} days | Size: {snap.volume_size} GB | Desc: {snap.description[:50]}")

    if old_snapshot_count > 10:
        print(f"  ... and {old_snapshot_count - 10} more.")

    if old_snapshot_count == 0:
        print("  ✅ No old snapshots found.")
    else:
        print(f"\n  ⚠️  SUMMARY: {old_snapshot_count} old snapshots found.")
        print(f"  📉 Total Snapshot Reference Size: {total_snap_size_gb} GB (Actual billing varies due to compression/incremental nature)")

    print("\n--- Audit Complete ---")

if __name__ == "__main__":
    audit_ebs_waste()