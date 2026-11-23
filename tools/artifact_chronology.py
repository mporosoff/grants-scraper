"""Order authenticated artifact metadata by original creation, never opaque IDs."""
from datetime import datetime, timezone


def created(artifact):
    if not isinstance(artifact, dict):
        raise ValueError('Artifact creation metadata is invalid')
    values = [artifact[key] for key in ('created_at', 'createdAt')
              if artifact.get(key) is not None]
    if not values:
        raise ValueError('Original artifact creation time is missing')
    parsed = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError('Original artifact creation time is invalid')
        try:
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('Original artifact creation time is invalid') from None
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError('Original artifact creation time requires a timezone')
        parsed.append(moment.astimezone(timezone.utc))
    if any(moment != parsed[0] for moment in parsed[1:]):
        raise ValueError('Conflicting original artifact creation times')
    return parsed[0]


def ordered(artifacts, *, newest_first=False):
    keyed = [(created(row), row) for row in artifacts]
    if len({moment for moment, _ in keyed}) != len(keyed):
        raise ValueError('Original artifact creation order is ambiguous')
    return [row for _, row in sorted(keyed, key=lambda item: item[0], reverse=newest_first)]


def latest(artifacts):
    values = ordered(artifacts)
    if not values:
        raise ValueError('No artifact creation evidence is available')
    return values[-1]
