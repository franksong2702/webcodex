"""Print project hook configuration for review; never install or overwrite it."""
import argparse
import json
import shlex
import sys
from pathlib import Path


def configuration(project, binary, source_config=None):
    if not project.is_absolute() or not binary.is_absolute():
        raise ValueError("project and binary must be absolute")
    adapter = Path(__file__).with_name("handoff_hook.py").resolve(strict=True)
    command = shlex.join([sys.executable, str(adapter), "--project", str(project), "--binary", str(binary)])
    if source_config is not None:
        if not source_config.is_absolute(): raise ValueError("source configuration must be absolute")
        command += " --source-config " + shlex.quote(str(source_config))
    return {"hooks": {event:[{"hooks":[{"type":"command","command":command,"timeout":30}]}]
                      for event in ["SessionStart","UserPromptSubmit","PostToolUse","Stop"]}}


def universal_configuration(binary, source_config=None):
    if not binary.is_absolute():
        raise ValueError("binary must be absolute")
    adapter = Path(__file__).with_name("universal_hook.py").resolve(strict=True)
    command = shlex.join([sys.executable, str(adapter), "--binary", str(binary)])
    if source_config is not None:
        if not source_config.is_absolute():
            raise ValueError("source configuration must be absolute")
        command += " --source-config " + shlex.quote(str(source_config))
    return {"hooks": {event: [{"hooks": [{"type": "command", "command": command, "timeout": 30}]}]
                      for event in ["SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"]}}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--project",type=Path)
    mode.add_argument("--universal",action="store_true")
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--source-config",type=Path)
    args=parser.parse_args()
    result = universal_configuration(args.binary, args.source_config) if args.universal else configuration(args.project,args.binary,args.source_config)
    print(json.dumps(result,indent=2))
