"""Validate a bounded Docker save archive before the daemon imports it.

Archives contain only the two CI images. Server certificates and configuration
are never inputs to this archive or to the GitHub builds.
"""
import hashlib
import json
import tarfile
from pathlib import PurePosixPath

from deploy import DeploymentError

MAX_COMPRESSED = 512 * 1024**2
MAX_EXPANDED = 2 * 1024**3
MAX_METADATA = 16 * 1024**2


def inspect_archive(file, commit, schema):
    small, names, total, kept = {}, set(), 0, 0
    try:
        with tarfile.open(file, 'r|gz') as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or '..' in path.parts or member.name in names
                        or not (member.isfile() or member.isdir()) or len(names) >= 4096):
                    raise DeploymentError('INVALID_IMAGE_ARCHIVE_MEMBER')
                names.add(member.name)
                total += member.size + 512
                if total > MAX_EXPANDED:
                    raise DeploymentError('IMAGE_ARCHIVE_EXPANDED_TOO_LARGE')
                if member.isfile() and member.size <= 1024**2:
                    kept += member.size
                    if kept > MAX_METADATA:
                        raise DeploymentError('IMAGE_ARCHIVE_METADATA_TOO_LARGE')
                    small[member.name] = archive.extractfile(member).read()
        manifest = json.loads(small['manifest.json'])
        if not isinstance(manifest, list) or len(manifest) != 2:
            raise DeploymentError('TWO_RELEASE_IMAGES_REQUIRED')
        images = {}
        for item in manifest:
            tag, = item['RepoTags']
            service = next((key for key in ('backend', 'edge') if tag == f'mcp-hub-ci-{key}:{commit}'), None)
            if service is None or service in images or not item['Layers'] or any(p not in names for p in item['Layers']):
                raise DeploymentError('UNEXPECTED_IMAGE_TAG_OR_LAYER')
            raw = small[item['Config']]
            config = json.loads(raw)
            labels = config['config'].get('Labels', {})
            if (labels.get('org.opencontainers.image.revision') != commit
                    or labels.get('biz.texcel.mcp-hub.schema') != schema
                    or config['os'] != 'linux' or config['architecture'] != 'amd64'):
                raise DeploymentError('IMAGE_COMMIT_SCHEMA_OR_PLATFORM_MISMATCH')
            images[service] = 'sha256:' + hashlib.sha256(raw).hexdigest()
        return images, total
    except (KeyError, ValueError, TypeError, OSError, tarfile.TarError) as error:
        raise DeploymentError('INVALID_DOCKER_IMAGE_ARCHIVE') from error
