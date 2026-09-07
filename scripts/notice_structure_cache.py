"""Private, content-addressed normalized notice cache.

Only a compact dependency identity belongs in public evidence. Neither raw
documents nor these full normalized containers may enter generated site data.
Corruption/eviction is a recoverable miss, never permission to trust old facts.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse

from scripts.notice_structure import STRUCTURE_VERSION

SCHEMA_VERSION = 1
DEFAULT_ROOT = Path('.cache/notice-structure')
MAX_ENTRY_BYTES = 40 * 1024 * 1024
MAX_CONTAINERS = 250


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def identity(document, scope_identity):
    version = STRUCTURE_VERSION
    if urlparse(document.get('url') or '').hostname in {'www.nsf.gov', 'nsf.gov'}:
        version += ':nsf-submission-component-1'
    return {'document_sha256': document.get('sha256'), 'source_url': document.get('url'),
            'structure_version': version, 'source_scope_identity': scope_identity}


def cache_key(dependencies):
    return hashlib.sha256(canonical_bytes(dependencies)).hexdigest()


def valid_containers(containers):
    if not isinstance(containers, list) or len(containers) > MAX_CONTAINERS:
        return False
    for container in containers:
        if not isinstance(container, dict) or not isinstance(container.get('text'), str) or len(container['text']) > 30000:
            return False
        blocks = container.get('structure', [])
        if not isinstance(blocks, list) or len(blocks) > 30000:
            return False
        prior_end = 0
        for block in blocks:
            span = block.get('span') if isinstance(block, dict) else None
            if (not isinstance(span, (tuple, list)) or len(span) != 2 or any(type(n) is not int for n in span)
                or not 0 <= prior_end <= span[0] <= span[1] <= len(container['text'])
                or container['text'][span[0]:span[1]] != block.get('text')):
                return False
            prior_end = span[1]
    return True


class StructureCache:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.counters = {'hits': 0, 'misses': 0, 'invalid': 0, 'writes': 0, 'coalesced_writes': 0, 'write_failures': 0}

    def quarantine(self, document, facts, changed_families):
        """Bounded, immutable private evidence receipt, never a public fact store."""
        payload = {'document': document, 'facts': facts[:80],
                   'changed_families': sorted(changed_families),
                   'reason': 'Previous interpretation requires original source structure'}
        raw = canonical_bytes(payload)
        if len(raw) > 512 * 1024:
            return None
        digest = hashlib.sha256(raw).hexdigest()
        directory = self.root / 'quarantine'
        temporary = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / (digest + '.json')
            if target.exists():
                return digest if target.read_bytes() == raw else None
            # The source budget bounds new receipts per run; this also bounds
            # lifetime retained receipts in the existing evictable runner cache.
            if sum(1 for _ in directory.glob('*.json')) >= 2000:
                return None
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.quarantine-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
            temporary.replace(target)
            return digest
        except OSError:
            return None
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def read(self, dependencies):
        path = self.root / (cache_key(dependencies) + '.json')
        try:
            if path.stat().st_size > MAX_ENTRY_BYTES:
                raise ValueError('oversized structure cache')
            envelope = json.loads(path.read_bytes())
            value = envelope['payload']
            if (envelope.get('schema_version') != SCHEMA_VERSION
                or value.get('dependencies') != dependencies
                or hashlib.sha256(canonical_bytes(value)).hexdigest() != envelope.get('sha256')
                or not valid_containers(value.get('containers')) or not isinstance(value.get('extraction'), dict)):
                raise ValueError('invalid structure cache')
            self.counters['hits'] += 1
            return deepcopy(value['containers']), deepcopy(value['extraction'])
        except FileNotFoundError:
            self.counters['misses'] += 1
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            self.counters['misses'] += 1
            self.counters['invalid'] += 1
        return None

    def write(self, dependencies, containers, extraction):
        temporary = None
        try:
            if not valid_containers(containers) or not isinstance(extraction, dict):
                raise ValueError('invalid source structure')
            # Temporary parser flags must not become normalized source content.
            containers = [{key: value for key, value in container.items() if not key.startswith('_')}
                          for container in containers]
            value = {'dependencies': dependencies, 'containers': containers, 'extraction': extraction}
            raw = canonical_bytes({'schema_version': SCHEMA_VERSION, 'payload': value,
                                   'sha256': hashlib.sha256(canonical_bytes(value)).hexdigest()})
            if len(raw) > MAX_ENTRY_BYTES:
                raise ValueError('oversized source structure')
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.root, prefix='.notice-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
            for attempt in range(4):
                try:
                    temporary.replace(self.root / (cache_key(dependencies) + '.json'))
                    break
                except OSError:
                    # Windows briefly locks a destination during concurrent
                    # reads/replacements. Retry this atomic write, not a partial
                    # overwrite. A validated identical winner also suffices.
                    winner = self.read(dependencies)
                    if winner is not None and canonical_bytes(winner) == canonical_bytes([containers, extraction]):
                        self.counters['coalesced_writes'] += 1
                        return True
                    if attempt == 3:
                        raise
                    time.sleep(0.01 * (2 ** attempt))
            self.counters['writes'] += 1
            return True
        except (OSError, ValueError, TypeError, RecursionError):
            self.counters['write_failures'] += 1
            return False
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
