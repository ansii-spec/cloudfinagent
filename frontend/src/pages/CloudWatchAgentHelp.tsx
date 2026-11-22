import { PageHeader } from '@/components/States'
import { Card, CardContent } from '@/components/ui/card'

const CONFIG = `{"metrics":{"append_dimensions":{"InstanceId":"\${aws:InstanceId}"},
 "metrics_collected":{"mem":{"measurement":["mem_used_percent"],"metrics_collection_interval":60}}}}`

export default function CloudWatchAgentHelp() {
  return (
    <div className="max-w-3xl">
      <PageHeader title="How to install the CloudWatch agent" description="EC2 does not report memory by default. Without it, right-sizing can't check that the smaller size has enough RAM, so confidence is lower." />
      <Card><CardContent className="space-y-4 pt-5 text-sm">
        <ol className="list-decimal space-y-3 pl-5">
          <li>Attach an instance profile (IAM role) with the AWS managed policy <code className="rounded bg-muted px-1">CloudWatchAgentServerPolicy</code> to the instance.</li>
          <li>Install the agent (Amazon Linux 2023):<pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 text-xs">sudo dnf install -y amazon-cloudwatch-agent</pre></li>
          <li>Write a config that collects <code className="rounded bg-muted px-1">mem_used_percent</code>:
            <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 text-xs">{`cat <<'EOF' | sudo tee /opt/aws/amazon-cloudwatch-agent/etc/config.json\n${CONFIG}\nEOF`}</pre></li>
          <li>Start it:<pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 text-xs">sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json -s</pre></li>
          <li>Wait for at least 7 days of data, then run a new scan.</li>
        </ol>
      </CardContent></Card>
    </div>
  )
}
