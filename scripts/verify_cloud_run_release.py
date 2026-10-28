"""Read-only Cloud Run release check. Does not change traffic."""
import argparse
import json
import shutil
import subprocess


def verify(service, revision, commit, digest):
    generation = service['metadata'].get('generation')
    observed = service['status'].get('observedGeneration')
    if generation is None or observed is None or str(generation) != str(observed):
        raise ValueError('Service reconciliation pending or unknown')
    if not any(c.get('type') == 'Ready' and c.get('status') == 'True'
               for c in service['status'].get('conditions', [])):
        raise ValueError('Service not Ready')
    if revision['metadata'].get('labels', {}).get('commit-sha') != commit:
        raise ValueError('Revision commit mismatch')
    if revision['status'].get('imageDigest', '').split('@')[-1] != digest:
        raise ValueError('Revision image digest mismatch')
    if not any(c.get('type') == 'Ready' and c.get('status') == 'True'
               for c in revision['status'].get('conditions', [])):
        raise ValueError('Revision not Ready')
    name = revision['metadata']['name']
    traffic = [t for t in service['status'].get('traffic', []) if t.get('percent', 0)]
    if len(traffic) != 1 or traffic[0].get('revisionName') != name or traffic[0]['percent'] != 100:
        raise ValueError('Expected revision not serving 100%')
    if service['status'].get('latestCreatedRevisionName') != name:
        raise ValueError('Concurrent revision change; recheck deployment')
    return {'revision': name, 'commit': commit, 'digest': digest, 'traffic_percent': 100}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('project', 'region', 'service', 'commit', 'digest'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    gcloud = shutil.which('gcloud')
    if not gcloud:
        parser.error('gcloud CLI is not installed or not on PATH')
    common = ['--project', args.project, '--region', args.region, '--format=json']

    def read(kind, name):
        return json.loads(subprocess.check_output(
            [gcloud, 'run', kind, 'describe', name, *common], text=True, encoding="utf-8", timeout=60))

    service = read('services', args.service)
    revision = read('revisions', service['status']['latestCreatedRevisionName'])
    print(json.dumps(verify(read('services', args.service), revision, args.commit, args.digest)))


if __name__ == '__main__':
    main()
