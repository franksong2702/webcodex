"""Real CLI and hook subprocess validation, with disposable code/notes projects.

No network, model, real Codex session, production configuration or service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    if args.report.exists():
        raise SystemExit('Refusing to replace an existing report')
    checks = []
    elapsed = []
    root = None
    report = {'entrance': 'real CLI and hook subprocesses; synthetic hook events',
              'not_verified': ['real Codex hooks', 'GPT web', 'MCP/HTTP', 'production'],
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    def call(project, request, ok=True):
        started = time.monotonic()
        p = subprocess.run([str(binary), 'handoff', '--project', str(project), '--request-stdin'],
            input=json.dumps(request), text=True, capture_output=True, env={}, timeout=12)
        elapsed.append(time.monotonic()-started)
        assert p.returncode == (0 if ok else 1), 'unexpected CLI exit'
        value = json.loads(p.stdout)
        assert value['success'] is ok
        return value['output'] if ok else value['error']
    def hook(project, event, **extra):
        payload = dict(hook_event_name=event, cwd=str(project), session_id='local-fixture', permission_mode='default', **extra)
        p = subprocess.run([sys.executable, str(Path(__file__).with_name('handoff_hook.py')),
             '--project', str(project), '--binary', str(binary)], input=json.dumps(payload), text=True,
             capture_output=True, timeout=30, env={'PYTHONDONTWRITEBYTECODE':'1'})
        assert p.returncode == 0
        output = json.loads(p.stdout)
        assert 'decision' not in output and 'continue' not in output
        return output
    try:
        with tempfile.TemporaryDirectory(prefix='webcodex-handoff-local-') as temp:
            root=Path(temp).resolve()
            for kind in ('code', 'notes'):
                project=root/kind; project.mkdir()
                related=project/('calc.py' if kind=='code' else 'Project.md')
                content='def add(a,b):\n    return a+b\n' if kind=='code' else '预算暂记 300 元，时间还没定。\n'
                related.write_text(content)
                other=project/'unrelated.txt';other.write_text('Other task must remain unchanged.\n')
                before=other.read_bytes()
                assert call(project,{'action':'status'})['enabled'] is False
                assert not (project/'handoff').exists()
                call(project,{'action':'create','task_id':'task-a','title':kind+' fixture'})
                call(project,{'action':'create','task_id':'task-b','title':'Other task'})
                discovery=hook(project,'SessionStart')
                assert 'task-a' in str(discovery) and 'task-b' in str(discovery)
                actor='local:'+hashlib.sha256(b'local-fixture').hexdigest()
                call(project,{'action':'bind','task_id':'task-a','client_id':actor})
                assert 'source_connection_not_configured' in str(hook(project,'SessionStart'))
                diagnostic=subprocess.run([sys.executable,'-c','raise SystemExit(7)'],cwd=project,env={'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,timeout=5)
                assert diagnostic.returncode==7
                hook(project,'PostToolUse',tool_use_id='operation-1',tool_name='Bash',tool_response={'exit_code':diagnostic.returncode,'stdout':'must-not-persist'})
                first=call(project,{'action':'read','task_id':'task-a'})
                fact=first['checkpoint']['events'][-1]
                assert fact['exit_code']==7 and fact['status']=='failed'
                assert 'must-not-persist' not in json.dumps(first)
                hook(project,'PostToolUse',tool_use_id='operation-1',tool_name='Bash',tool_response={'exit_code':7})
                assert call(project,{'action':'read','task_id':'task-a'})['revision']==first['revision']
                md=project/'handoff/task-a.md';md.write_text(md.read_text()+'\n用户补充：未确认，请保留。\n')
                hook(project,'PostToolUse',tool_use_id='operation-2',tool_name='Bash',tool_response={'job_id':'active-job','status':'running','success':True})
                saved=call(project,{'action':'read','task_id':'task-a'})
                assert saved['checkpoint']['events'][-1]['job_id']=='active-job'
                assert saved['checkpoint']['events'][-1]['status']=='unknown'
                assert '用户补充：未确认，请保留。' in md.read_text()
                assert related.read_text()==content and other.read_bytes()==before
                if kind=='code':
                    checked=subprocess.run([sys.executable,'-B','-c','from calc import add; assert add(2,3)==5'],cwd=project,env={'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,timeout=5)
                    assert checked.returncode==0

                assert not call(project,{'action':'read','task_id':'task-b'})['checkpoint']['events']
                hook(project,'Stop',stop_hook_active=True)
                call(project,{'action':'disable'})
                before=md.read_bytes()
                assert hook(project,'PostToolUse',tool_use_id='operation-3',tool_name='Bash',tool_response={'exit_code':0})=={}
                assert md.read_bytes()==before
                checks.append({'project':kind,'passed':True,'revision':saved['revision'],'diagnostic_exit_code':diagnostic.returncode,'diagnostic_executions':1,'code_check_exit_code':checked.returncode if kind=='code' else None,
                               'behaviors':['explicit multi-task selection','failed exit preserved','deduplication','unknown Job ID retained','Chinese notes and unrelated files preserved','disable stops writes','no Stop loop']})
        report.update(success=True,checks=checks,cleanup=not root.exists(),cli_calls=len(elapsed),
                      cli_latency_seconds={'max':max(elapsed),'mean':sum(elapsed)/len(elapsed)})
    except Exception as exc:
        report.update(success=False,checks=checks,error_type=type(exc).__name__,cleanup=root is not None and not root.exists())
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['success'] else 1

if __name__=='__main__':
    raise SystemExit(main())
