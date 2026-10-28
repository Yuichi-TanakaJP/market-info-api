import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_check', ROOT / 'scripts/verify_cloud_run_release.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    service = {'metadata': {'generation': 2}, 'status': {'observedGeneration': 2, 'conditions': [{'type': 'Ready', 'status': 'True'}], 'latestCreatedRevisionName': 'new', 'traffic': [{'revisionName': 'new', 'percent': 100}]}}
    revision = {'metadata': {'name': 'new', 'labels': {'commit-sha': 'abc'}},
                'status': {'imageDigest': 'image@sha256:123', 'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    return service, revision


def test_manual_ci_preserves_checks():
    config = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    assert config['on'] == {'workflow_dispatch': ''}
    steps = config['jobs']['ci']['steps']
    assert {x['name'] for x in steps if 'name' in x} >= {'Lint', 'Test', 'App import check'}


def test_matches():
    assert module.verify(*fixture(), 'abc', 'sha256:123')['traffic_percent'] == 100


@pytest.mark.parametrize('failure', ['sha', 'digest', 'not_ready', 'old_traffic', 'split', 'concurrent'])
def test_rejects_bad_release(failure):
    service, revision = copy.deepcopy(fixture())
    if failure == 'sha':
        revision['metadata']['labels']['commit-sha'] = 'old'
    elif failure == 'digest':
        revision['status']['imageDigest'] = 'image@sha256:old'
    elif failure == 'not_ready':
        revision['status']['conditions'][0]['status'] = 'False'
    elif failure == 'old_traffic':
        service['status']['traffic'][0]['revisionName'] = 'old'
    elif failure == 'split':
        service['status']['traffic'] = [{'revisionName': 'new', 'percent': 90}, {'revisionName': 'old', 'percent': 10}]
    else:
        service['status']['latestCreatedRevisionName'] = 'another'
    with pytest.raises(ValueError):
        module.verify(service, revision, 'abc', 'sha256:123')


def test_cli_resolves_executable_and_rereads_service(monkeypatch, capsys):
    import json
    import sys

    service, revision = fixture()
    calls = []

    def read(args, **kwargs):
        calls.append(args)
        return json.dumps(revision if args[2] == 'revisions' else service)

    monkeypatch.setattr(module.shutil, 'which', lambda name: 'C:/SDK/gcloud.cmd')
    monkeypatch.setattr(module.subprocess, 'check_output', read)
    monkeypatch.setattr(sys, 'argv', ['check', '--project', 'p', '--region', 'r', '--service', 's', '--commit', 'abc', '--digest', 'sha256:123'])
    module.main()
    assert [c[2] for c in calls] == ['services', 'revisions', 'services']
    assert all(c[0] == 'C:/SDK/gcloud.cmd' for c in calls)
    assert json.loads(capsys.readouterr().out)['traffic_percent'] == 100


@pytest.mark.parametrize('state', ['pending', 'unknown', 'not_ready'])
def test_rejects_unreconciled_service(state):
    service, revision = fixture()
    if state == 'pending':
        service['status']['observedGeneration'] = 1
    elif state == 'unknown':
        del service['status']['observedGeneration']
    else:
        service['status']['conditions'][0]['status'] = 'False'
    with pytest.raises(ValueError):
        module.verify(service, revision, 'abc', 'sha256:123')
