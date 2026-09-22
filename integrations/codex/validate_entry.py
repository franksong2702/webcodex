"""Offline real-CLI entry acceptance; all project data is disposable."""
import argparse
import json
import tempfile
from pathlib import Path
from enter_work import enter
from handoff_hook import call_writer, CheckpointError
from universal_hook import dispatch


def validate(binary):
    checks = []
    with tempfile.TemporaryDirectory(prefix='handoff-entry-') as temp:
        base = Path(temp).resolve()
        for name, git, docs in [('code', True, False), ('中文笔记', False, False), ('existing-docs', True, True)]:
            root = base / name
            root.mkdir()
            if git: (root / '.git').mkdir()
            if docs:
                (root / 'AGENTS.md').write_text('用户已有规则，不覆盖。')
                (root / 'PLAN.md').write_text('用户已有计划与未完成事项。')
            writer = lambda req: call_writer(binary, root, req)
            enter(root, name, '用户确认的测试工作', writer)
            assert not (root / 'handoff').exists()
            first = enter(root, name, '用户确认的测试工作', writer, confirmed=True,
                          related=[str(root / 'PLAN.md')] if docs else [])
            task = first['task_id']
            assert first['status'] == 'bound'
            workdir = root
            if git:
                workdir = root / 'src'; workdir.mkdir()
            payload = dict(cwd=str(workdir), session_id=name, hook_event_name='PostToolUse',
                           permission_mode='default', tool_name='Bash', tool_use_id='probe',
                           tool_response={'exit_code': 0})
            dispatch(payload, binary); dispatch(payload, binary)
            cp = writer({'action':'read','task_id':task})['checkpoint']
            facts = [e for e in cp['events'] if e['type']=='tool_finished']
            assert len(facts)==1 and facts[0]['status']=='completed'
            selected = enter(root, name+'-next', '用户确认的测试工作', writer, confirmed=True)
            assert selected['status']=='agent_task_selection_required'
            enter(root, name+'-next', '用户确认的测试工作', writer, confirmed=True, task_id=task)
            another = enter(root, name+'-other', '另一项明确工作', writer, confirmed=True, new_task=True)
            assert another['task_id'] != task
            cp2 = writer({'action':'read','task_id':task})['checkpoint']
            assert cp2==cp
            if docs:
                assert (root/'AGENTS.md').read_text()=='用户已有规则，不覆盖。'
                assert (root/'PLAN.md').read_text()=='用户已有计划与未完成事项。'
            checks.append({'scenario':name, 'discovery_no_write':True,'atomic_create_bind':True,
                           'capture_and_dedup':True,'explicit_resume':True,'separate_task_preserved':True})
    assert not base.exists()
    return {'scenarios':checks,'cleanup':True,'real_codex_hook':False,'real_gpt_mcp':False}


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();result=validate(args.binary.resolve(strict=True))
    with args.report.open('x') as f:json.dump(result,f,indent=2,ensure_ascii=False)
    print('PASS: 3 isolated real-writer scenarios; cleanup verified; real GPT/Codex entrances not exercised')
