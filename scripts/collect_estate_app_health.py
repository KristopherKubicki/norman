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

OUTPUT = Path("/var/lib/norman/state/application-observations.json")
TARGETS = Path("/var/lib/norman/state/estate-observation-targets.json")
HOST_UNITS = {
    "work-special": {
        "scout": ["scout-agent-mcp-http.service", "scout-superworker-web.service"],
        "earlybird": ["earlybird.service"],
    },
    "toy-box": {
        "housebot": [
            "housebot.service",
            "housebot-beach-eufy-health-sync.service",
            "housebot-overnight-light-sentinel.service",
            "housebot-pfsense-sync.service",
            "housebot-power-accounting-sync.service",
        ],
        "phone-ops": ["phoneops-ssh-alert-collector.service"],
    },
    "hal": {"autocamera": ["autocamera.service"]},
}

REMOTE = r"""
import datetime,json,pathlib,subprocess,sys
spec=json.loads(sys.argv[1]); now=datetime.datetime.now(datetime.timezone.utc).isoformat(); rows=[]
for app,units in spec.items():
 for unit in units:
  raw=subprocess.check_output(['systemctl','show',unit,'-p','LoadState','-p','ActiveState','-p','SubState','-p','Result','-p','Type'],text=True)
  d=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
  if d.get('LoadState')!='loaded':state='missing';level='unknown'
  elif d.get('Result') not in (None,'','success') or d.get('ActiveState')=='failed':state='failed';level='bad'
  elif d.get('ActiveState')=='active':state='process-running';level='ok'
  elif d.get('Type')=='oneshot':state='idle';level='unknown'
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
    except (subprocess.SubprocessError, ValueError):
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
    except (subprocess.SubprocessError, ValueError):
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


def main() -> None:
    """Atomically publish one metadata snapshot with bounded concurrency."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        groups = list(pool.map(lambda pair: collect_host(*pair), HOST_UNITS.items()))
    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "observations": [row for group in groups for row in group] + collect_aws(),
    }
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
