"""Single source of the customer IAM policies (kept in sync with aws/cloudformation-role.yaml by a test)."""
READ_ONLY_ACTIONS = [
    "ec2:DescribeInstances", "ec2:DescribeInstanceTypes", "ec2:DescribeInstanceAttribute",
    "ec2:DescribeInstanceStatus", "ec2:DescribeRegions", "ec2:DescribeVolumes", "ec2:DescribeTags",
    "ec2:DescribeAddresses", "ec2:DescribeImages", "ec2:DescribeSnapshots",
    "autoscaling:DescribeAutoScalingInstances", "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
]
REMEDIATION_ACTIONS = [
    "ec2:StopInstances", "ec2:StartInstances", "ec2:TerminateInstances", "ec2:ModifyInstanceAttribute",
    "ec2:ModifyInstanceCreditSpecification", "ec2:CreateTags", "ec2:CreateSnapshot", "ec2:CreateImage",
]
PLATFORM_PRINCIPAL_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": "sts:AssumeRole", "Resource": "arn:aws:iam::*:role/EC2OptimizerAccessRole*"},
        {"Effect": "Allow", "Action": "pricing:GetProducts", "Resource": "*"},
    ],
}


def trust_policy(principal_arn: str, external_id: str) -> dict:
    return {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"AWS": principal_arn}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"sts:ExternalId": external_id}}}]}


def permissions_policy(enable_actions: bool) -> dict:
    statements = [{"Sid": "ReadOnlyAnalysis", "Effect": "Allow", "Action": READ_ONLY_ACTIONS, "Resource": "*"}]
    if enable_actions:
        statements.append({"Sid": "RemediationActions", "Effect": "Allow", "Action": REMEDIATION_ACTIONS,
                           "Resource": "*"})
    return {"Version": "2012-10-17", "Statement": statements}
