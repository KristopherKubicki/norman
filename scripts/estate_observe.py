#!/usr/bin/env python3
"""Collect bounded, read-only app evidence; never run remediation or read secrets."""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile

from estate_metric_history import attach_history

OUTPUT = Path("/var/lib/norman/state/application-observations.json")
TARGETS = Path("/var/lib/norman/state/estate-observation-targets.json")
HOST_UNITS = {
    "work-special": {
        "scout": ["scout-agent-mcp-http.service", "scout-superworker-web.service"],
        "earlybird": ["user:earlybird.service"],
    },
    "toy-box": {
        "housebot": [
            "housebot.service",
            "housebot-hubitat-site-health.service",
            "housebot-beach-eufy-health-sync.service",
            "housebot-overnight-light-sentinel.service",
            "housebot-pfsense-sync.service",
            "housebot-power-accounting-sync.service",
        ],
        "phone-ops": ["phoneops-ssh-alert-collector.service"],
    },
    "hal": {"autocamera": ["autocamera-webcam.service"]},
}

REMOTE = r"""
import datetime,json,os,pathlib,subprocess,sys
spec=json.loads(sys.argv[1]); now=datetime.datetime.now(datetime.timezone.utc).isoformat(); rows=[]
for app,units in spec.items():
 for unit in units:
  scope=['--user'] if unit.startswith('user:') else []
  actual=unit.removeprefix('user:')
  env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid())}
  raw=subprocess.check_output(['systemctl',*scope,'show',actual,'-p','LoadState','-p','ActiveState','-p','SubState','-p','Result','-p','Type'],text=True,env=env)
  d=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
  if d.get('LoadState')!='loaded':state='missing';level='unknown'
  elif d.get('Result') not in (None,'','success') or d.get('ActiveState')=='failed':state='failed';level='bad'
  elif d.get('ActiveState')=='active':state='process-running';level='ok'
  elif d.get('Type')=='oneshot':state='idle';level='ok'
  else:state='inactive';level='bad'
  rows.append({'application':app,'id':unit,'name':unit,'checked_at':now,'state':state,'level':level,
               'detail':'systemd '+d.get('ActiveState','unknown')+'/'+d.get('SubState','unknown')+'; result '+d.get('Result','unknown'),
               'evidence_kind':'process'})
paths=[('scout','/home/kristopher/code/control_plane/audit/scout_superworker/latest_summary.json'),
       ('housebot','/opt/housebot/out/hubitat_site_health/latest.json')]
for app,filename in paths:
 if app not in spec:continue
 p=pathlib.Path(filename)
 if not p.is_file():
  rows.append({'application':app,'id':app+'-output','state':'missing','level':'unknown','detail':'Expected status artifact absent'})
  continue
 try:d=json.loads(p.read_text())
 except (OSError,ValueError):
  rows.append({'application':app,'id':app+'-output','state':'unreadable','level':'unknown','detail':'Status artifact unreadable'})
  continue
 if app=='scout':
  tasks=d.get('tasks',{});stamp=d.get('finished_at_utc');level='bad' if tasks.get('error',0) else 'ok'
  metrics=[{'id':'last_cycle_successful_tasks','value':tasks.get('ok'),'unit':'tasks','source_timestamp':stamp},
           {'id':'last_cycle_failed_tasks','value':tasks.get('error'),'unit':'tasks','source_timestamp':stamp}]
  detail='Last recorded worker cycle; cadence must be confirmed'
 else:
  summary=d.get('summary',{});stamp=d.get('generated_at');level=summary.get('level','unknown')
  metrics=[{'id':'sites_reporting_ok','value':summary.get('ok_count'),'unit':'sites','source_timestamp':stamp},
           {'id':'sites_with_warnings','value':summary.get('warn_count'),'unit':'sites','source_timestamp':stamp}]
  detail='; '.join(str(s.get('name','site'))+': '+str(s.get('level','unknown')) for s in d.get('sites',[]))
 rows.append({'application':app,'id':app+'-output','name':app+' status artifact','checked_at':stamp,
              'state':'artifact-report','level':level,'max_age_seconds':7200,'detail':detail,
              'evidence_kind':'output','metrics':metrics})
print(json.dumps(rows))
"""

AWS_REMOTE = r"""
import concurrent.futures,datetime,json,subprocess,sys
targets=json.loads(sys.argv[1])
def collect(t):
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 try:
  names=list(t['services']);rows=[]
  for offset in range(0,len(names),10):
   if t.get('kind')=='asg':
    cmd=['/usr/local/bin/aws','--profile',t['profile'],'--region',t.get('region','us-east-2'),'--no-cli-pager','autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',*names[offset:offset+10],'--query','AutoScalingGroups[].{name:AutoScalingGroupName,arn:AutoScalingGroupARN,desired:DesiredCapacity,instances:Instances[].{state:LifecycleState,health:HealthStatus}}']
    for group in json.loads(subprocess.check_output(cmd,text=True,stderr=subprocess.DEVNULL,timeout=12)):
     if group['arn'].split(':')[4]!=t['account']:raise ValueError('account mismatch')
     name=group['name'];healthy=sum(i['state']=='InService' and i['health']=='Healthy' for i in group['instances']);desired=group['desired']
     rows.append({**t['services'][name],'id':t['profile']+':'+name,'name':name,'checked_at':now,
                  'state':'scaled-to-zero' if not desired else 'capacity-met' if healthy>=desired else 'capacity-shortfall',
                  'level':'unknown' if not desired else 'ok' if healthy>=desired else 'bad','evidence_kind':'runtime',
                  'detail':str(healthy)+'/'+str(desired)+' healthy ASG instances; not an application output check',
                  'metrics':[{'id':'asg_healthy_instances','value':healthy,'unit':'instances','source_timestamp':now},
                             {'id':'asg_desired_instances','value':desired,'unit':'instances','source_timestamp':now}]})
    continue
   if t.get('kind')=='ec2':
    cmd=['/usr/local/bin/aws','--profile',t['profile'],'--region',t.get('region','us-east-2'),'--no-cli-pager','ec2','describe-instances','--filters','Name=instance-id,Values='+','.join(names[offset:offset+10]),'--query','Reservations[].{account:OwnerId,instances:Instances[].{id:InstanceId,state:State.Name}}']
    reservations=json.loads(subprocess.check_output(cmd,text=True,stderr=subprocess.DEVNULL,timeout=12))
    for reservation in reservations:
     if reservation['account']!=t['account']:raise ValueError('account mismatch')
     for instance in reservation['instances']:
      name=instance['id'];target=t['services'][name];running=instance['state']=='running'
      rows.append({**target,'id':t['account']+':'+name,'name':name,'checked_at':now,'level':'ok' if running else 'unknown',
                   'state':'instance-running' if running else instance['state'],'evidence_kind':'runtime',
                   'detail':'EC2 '+instance['state']+'; does not establish application health',
                   'metrics':[{'id':'ec2_running','value':int(running),'unit':'boolean','source_timestamp':now}]})
    continue
   cmd=['/usr/local/bin/aws','--profile',t['profile'],'--region','us-east-2','--no-cli-pager','ecs','describe-services','--cluster',t['cluster'],'--services',*names[offset:offset+10],'--query','{services:services[].{name:serviceName,arn:serviceArn,desired:desiredCount,running:runningCount,status:status},failures:failures}']
   d=json.loads(subprocess.check_output(cmd,text=True,stderr=subprocess.DEVNULL,timeout=12))
   for s in d['services']:
    if s['arn'].split(':')[4]!=t['account']:raise ValueError('account mismatch')
    target=t['services'][s['name']];desired=s['desired'];running=s['running']
    level='unknown' if desired==0 else 'ok' if running>=desired else 'bad'
    rows.append({**target,'id':s['arn'],'name':s['name'],'checked_at':now,'level':level,
                 'state':'scaled-to-zero' if desired==0 else 'capacity-met' if running>=desired else 'capacity-shortfall',
                 'evidence_kind':'runtime','detail':str(running)+'/'+str(desired)+' ECS tasks; not an output check',
                 'metrics':[{'id':'ecs_running_tasks','value':running,'unit':'tasks','source_timestamp':now},
                            {'id':'ecs_desired_tasks','value':desired,'unit':'tasks','source_timestamp':now}]})
  found={r['name'] for r in rows}
  for name,target in t['services'].items():
   if name not in found:rows.append({**target,'id':name,'state':'resource-missing','level':'unknown','checked_at':now})
  return rows
 except (subprocess.SubprocessError,ValueError,KeyError):
  return [{**target,'id':name,'state':'observer-unavailable','level':'unknown','detail':'AWS metadata unavailable; verify SSO and resource identity'} for name,target in t['services'].items()]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 print(json.dumps([row for group in pool.map(collect,targets) for row in group]))
"""


def collect_aws() -> list[dict]:
    """Use existing Hal profiles in place; never copy AWS credentials to Norman."""
    import shlex

    if not TARGETS.is_file():
        return []
    targets = json.loads(TARGETS.read_text())
    command = (
        "python3 -c " + shlex.quote(AWS_REMOTE) + " " + shlex.quote(json.dumps(targets))
    )
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "hal", command],
            capture_output=True,
            text=True,
            timeout=110,
            check=True,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return [
            {
                "application": target["application"],
                "id": name,
                "state": "observer-unavailable",
                "level": "unknown",
                "detail": "AWS observer on Hal unavailable",
            }
            for group in targets
            for name, target in group["services"].items()
        ]


def collect_host(host: str, apps: dict) -> list[dict]:
    """Read allowlisted unit properties and summary counts over existing SSH."""
    import shlex

    command = "python3 -c " + shlex.quote(REMOTE) + " " + shlex.quote(json.dumps(apps))
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command],
            capture_output=True,
            text=True,
            timeout=25,
            check=True,
        )
        return [{**row, "host": host} for row in json.loads(result.stdout)]
    except (OSError, subprocess.SubprocessError, ValueError):
        return [
            {
                "application": app,
                "id": host + "-observer",
                "host": host,
                "state": "observer-unavailable",
                "level": "unknown",
                "detail": "Read-only host observation failed; check SSH and collector access",
            }
            for app in apps
        ]


WORKFLOW_TARGETS = {
    "work-special": "earlybird",
    "work-special-producers": "producers",
    "toy-box": "housebot",
    "192.168.2.151": "gateway",
    "192.168.2.150": "gateway",
}


def collect_workflow(pair: tuple[str, str]) -> list[dict]:
    """Run a versioned metadata-only probe without installing code on app hosts."""
    host, mode = pair
    if mode == "producers":
        host = "work-special"
    app = (
        "norllama"
        if mode == "gateway"
        else "leadership-kpis"
        if mode == "producers"
        else mode
    )
    try:
        source = Path(__file__).with_name("estate_workflow_probes.py").read_text()
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                *(
                    ["-i", str(Path.home() / ".ssh/estate_gateway_probe_ed25519")]
                    if mode == "gateway"
                    else []
                ),
                host,
                "python3 - " + mode,
            ],
            input=source,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        rows = json.loads(result.stdout)
        return [
            {
                **r,
                "id": r["id"] + ("-" + host if mode == "gateway" else ""),
                "name": r.get("name", app) + " on " + host,
                "host": host,
            }
            for r in rows
        ]
    except (OSError, subprocess.SubprocessError, ValueError):
        return [
            {
                "application": app,
                "id": host + "-workflow",
                "state": "observer-unavailable",
                "level": "unknown",
                "detail": "Workflow metadata probe unavailable",
                "host": host,
            }
        ]


def routing_observation(rows: list[dict]) -> list[dict]:
    """Infer whether first-worker routing needs failover from both readiness probes."""
    workers = {r["host"]: r for r in rows if r.get("id", "").startswith("gateway-asr-")}
    if not {"192.168.2.151", "192.168.2.150"}.issubset(workers):
        return []
    primary = workers["192.168.2.151"]["state"] == "ready"
    secondary = workers["192.168.2.150"]["state"] == "ready"
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return [
        {
            "application": "norllama",
            "id": "asr-routing",
            "name": "ASR failover requirement",
            "checked_at": stamp,
            "state": "primary-ready"
            if primary
            else "failover-required"
            if secondary
            else "unavailable",
            "level": "ok"
            if primary and secondary
            else "warn"
            if primary or secondary
            else "bad",
            "evidence_kind": "workflow",
            "detail": "Inferred from worker readiness and Caddy first-worker policy; request counts show actual worker use separately.",
            "metrics": [
                {
                    "id": "failover_required",
                    "value": int(not primary and secondary),
                    "unit": "boolean",
                    "source_timestamp": stamp,
                }
            ],
        }
    ]


def collect_endpoints() -> list[dict]:
    """Probe confirmed application endpoints, not their operator consoles."""
    import urllib.request
    import time

    rows = []
    for app, url, kind in [
        ("norman", "https://norman.home.arpa/health", "health"),
        (
            "yhix-keys",
            "https://keys.yhix.com/.well-known/appspecific/com.tesla.3p.public-key.pem",
            "public-key",
        ),
    ]:
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        started = time.monotonic()
        failure = "unexpected response"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read(32768)
                ok = response.status == 200 and (
                    json.loads(body).get("status") == "ok"
                    if kind == "health"
                    else body.strip().startswith(b"-----BEGIN PUBLIC KEY-----")
                )
        except (OSError, ValueError) as exc:
            ok = False
            failure = type(getattr(exc, "reason", exc)).__name__
        rows.append(
            {
                "application": app,
                "id": app + "-endpoint",
                "name": "Application endpoint",
                "url": url,
                "checked_at": stamp,
                "state": "endpoint-ready" if ok else "endpoint-failed",
                "level": "ok" if ok else "bad",
                "evidence_kind": "reachability",
                "detail": (
                    "Expected application response verified"
                    if ok
                    else "Endpoint check failed: " + failure
                )
                + (
                    "; public-key retrieval does not establish vehicle authorization"
                    if kind == "public-key"
                    else ""
                ),
                "metrics": [
                    {
                        "id": "endpoint_ok",
                        "value": int(ok),
                        "unit": "boolean",
                        "source_timestamp": stamp,
                    },
                    {
                        "id": "probe_latency_ms",
                        "value": round((time.monotonic() - started) * 1000, 1),
                        "unit": "ms",
                        "source_timestamp": stamp,
                    },
                ],
            }
        )
    return rows


def main() -> None:
    """Atomically publish one metadata snapshot with bounded concurrency."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        groups = list(pool.map(lambda pair: collect_host(*pair), HOST_UNITS.items()))
        groups += list(pool.map(collect_workflow, WORKFLOW_TARGETS.items()))
    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "observations": [row for group in groups for row in group] + collect_aws(),
    }
    payload["observations"] += routing_observation(payload["observations"])
    payload["observations"] += collect_endpoints()
    attach_history(
        payload["observations"],
        OUTPUT.with_name("application-metric-history.sqlite3"),
        datetime.datetime.now(datetime.timezone.utc),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".application-observations-", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream)
            stream.write("\n")
        os.replace(temp, OUTPUT)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(
        json.dumps(
            {
                "observations": len(payload["observations"]),
                "generated_at": payload["generated_at"],
            }
        )
    )


if __name__ == "__main__":
    main()
