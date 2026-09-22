"""Read-only source probe using an explicitly selected existing API token.

Configuration is trusted hook configuration, never project checkpoint content.
No redirects, proxy inheritance, credential creation, or insecure TLS options.
"""
import ipaddress
import json
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('oversized configuration')
    return data


def validate_config(config, project):
    legacy = {'project_path', 'project_id', 'server_url', 'token_file'}
    universal = {'client_id', 'server_url', 'token_file'}
    if not isinstance(config, dict) or set(config) not in (legacy, universal):
        raise ValueError('invalid source configuration')
    if 'project_path' in config and Path(config['project_path']).resolve(strict=True) != project.resolve(strict=True):
        raise ValueError('source project mismatch')
    if 'project_id' in config and (not isinstance(config['project_id'], str) or not config['project_id'].startswith('agent:')):
        raise ValueError('full registered project ID required')
    if 'client_id' in config and (not isinstance(config['client_id'], str) or not config['client_id'] or len(config['client_id']) > 128):
        raise ValueError('invalid Runner identity')
    token_file = Path(config['token_file'])
    if not token_file.is_absolute():
        raise ValueError('absolute token file required')
    parsed = urllib.parse.urlsplit(config['server_url'])
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('invalid source URL')
    if parsed.scheme == 'http':
        # Cleartext credentials never leave a numeric loopback destination.
        if not ipaddress.ip_address(parsed.hostname).is_loopback:
            raise ValueError('HTTPS required')
    elif parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('HTTPS required')
    return config


def probe(config_path, project, task, checkpoint, *, deadline=None):
    if config_path is None:
        return {'status': 'unavailable', 'reason': 'source_connection_not_configured'}
    try:
        config = validate_config(json.loads(read_bounded(config_path, 16384)), project)
        token = read_bounded(config['token_file'], 4096).decode().strip()
        if not token or any(ord(c) < 32 for c in token):
            raise ValueError('invalid token')
        # The configuration is supplied by the trusted entry, never the project.
        # Resolve every project through the current authorized Runner inventory.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        budget = min(deadline, time.monotonic() + 6) if deadline is not None else time.monotonic() + 6
        def call(tool, params):
            remaining = budget - time.monotonic()
            if remaining <= 0:
                raise ValueError('source deadline exceeded')
            body = json.dumps({'tool': tool, 'params': params}).encode()
            request = urllib.request.Request(config['server_url'].rstrip('/') + '/api/tools/call',
                data=body, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
            with opener.open(request, timeout=remaining) as response:
                raw = response.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError('oversized response')
            value = json.loads(raw)
            output = value.get('output') if isinstance(value, dict) and value.get('success') is True else None
            if not isinstance(output, dict):
                raise ValueError('unconfirmed response')
            return output
        project_id = config.get('project_id')
        if project_id is None:
            canonical = str(project.resolve(strict=True))
            inventory = call('list_projects', {'client_id': config['client_id'], 'query': canonical[:200],
                                                'limit': 100, 'summary_only': False})
            if inventory.get('truncated') is not False or not isinstance(inventory.get('projects'), list):
                raise ValueError('incomplete inventory')
            matches = [entry for entry in inventory['projects'] if isinstance(entry, dict)
                       and entry.get('path') == canonical and entry.get('client_id') == config['client_id']
                       and entry.get('enabled') is True]
            if len(matches) != 1:
                raise ValueError('project identity missing or ambiguous')
            project_id = matches[0].get('id')
            if not isinstance(project_id, str) or not project_id.startswith('agent:' + config['client_id'] + ':'):
                raise ValueError('invalid project identity')
        output = call('project_handoff_read', {'project': project_id, 'task_id': task})
        if not isinstance(output, dict) or output.get('task_id') != task:
            raise ValueError('unconfirmed response')
        expected = checkpoint.get('checkpoint', {}).get('project_identity', {}).get('root_fingerprint')
        actual = output.get('checkpoint', {}).get('project_identity', {}).get('root_fingerprint')
        if not expected or actual != expected:
            raise ValueError('source target mismatch')
        local_revision = checkpoint.get('revision')
        source_revision = output.get('revision')
        if type(local_revision) is not int or type(source_revision) is not int:
            raise ValueError('unconfirmed revision')
        if source_revision != local_revision:
            return {'status': 'unavailable', 'reason': 'checkpoint_changed_during_probe'}
        status = output.get('source_status')
        if not isinstance(status, dict) or status.get('status') not in ('caught_up', 'pending', 'incomplete', 'unbound'):
            raise ValueError('source status unavailable')
        if any(type(status.get(key)) is not int or status[key] < 0 for key in ('pending', 'capture_gaps')):
            raise ValueError('invalid counts')
        # Return only fixed metadata. Never inject remote prose or response logs.
        return {key: status[key] for key in ('status', 'pending', 'capture_gaps')}
    except urllib.error.HTTPError as exc:
        return {'status': 'unavailable', 'reason': 'source_http_' + str(exc.code)}
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return {'status': 'unavailable', 'reason': 'source_unconfirmed'}
