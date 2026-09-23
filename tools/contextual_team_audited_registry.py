"""Opt-in audited registry format for local staging; ordinary registry rules stay unchanged.

The optional source-observation fields use the existing audited product contract.
No editing, migration, team restoration, publication, or provider entry point exists here.
"""
from collections import Counter
import copy
from datetime import datetime
import re
from urllib.parse import urlsplit

from scripts import researcher_registry as legacy
from scripts.faculty_match import _pi_domains

VERSION = 'contextual-audited-registry-stage-contract-v1'
MATERIAL_FIELDS = ('status', 'label', 'category', 'categories', 'type', 'evidence',
                   'source_urls', 'evidence_level')
REGISTRY_FIELDS = {'schema_version', 'registry_generation', 'researchers'}
PERSON_TEXT = {'researcher_id', 'display_name', 'sort_name', 'home_unit', 'relationship',
               'pool_visibility', 'status', 'orcid_id', 'research_summary', 'source_checked_date'}
PERSON_LISTS = {'legacy_ids', 'aliases', 'source_urls'}
PERSON_OPTIONAL = {'official_interests', 'institution', 'external_ids', 'metrics',
                   'pool_assignment', 'source_audit', 'summary_evidence'}
CLAIM_TEXT = {'claim_id', 'status', 'label', 'category', 'type', 'evidence',
              'evidence_level', 'verified_on', 'material_hash'}
CLAIM_LISTS = {'categories', 'source_urls', 'legacy_claim_ids'}
CLAIM_FIELDS = CLAIM_TEXT | CLAIM_LISTS | {'revision'}
CLAIM_OPTIONAL = {'evidence_records', 'history', 'retired_on', 'retirement_reason'}
OBSERVATION_FIELDS = {'form', 'url', 'source_type', 'response_sha256', 'text_sha256',
                      'locator', 'reviewed_on', 'retrieved_at'}
AUDIT_FIELDS = {'version', 'baseline_material', 'disposition', 'issues', 'limitations', 'reviewed_on'}
FORWARD_CLAIM_FIELDS = tuple(sorted(CLAIM_FIELDS | (CLAIM_OPTIONAL - {'history'})))
# These are compact authored summaries and identifiers, never raw source bodies.
# Measure stored bytes' text length before the ordinary validator trims values.
PERSON_LIMITS = {'researcher_id': 10, 'display_name': 120, 'sort_name': 140,
                 'home_unit': 180, 'relationship': 40, 'pool_visibility': 30,
                 'status': 10, 'orcid_id': 19, 'research_summary': 1200,
                 'source_checked_date': 10, 'pool_assignment': 7}
CLAIM_LIMITS = {'claim_id': 15, 'status': 7, 'label': 180, 'category': 140,
                'type': 80, 'evidence': 500, 'evidence_level': 22,
                'verified_on': 10, 'material_hash': 64, 'retired_on': 10,
                'retirement_reason': 500}


def _fields(value, required, optional, label):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError(f'{label} has missing or unsupported fields')


def _texts(value, fields, label):
    if any(not isinstance(value[key], str) for key in fields if key in value):
        raise ValueError(f'{label} fields must contain text, not nested data')


def _bounded_text(value, label, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f'{label} must contain bounded text (maximum {maximum})')


def _bounds(value, limits, label):
    for key, maximum in limits.items():
        if key in value:
            _bounded_text(value[key], label + '.' + key, maximum)


def _strings(value, label, maximum=64, item_maximum=500):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f'{label} must contain at most {maximum} text values')
    for item in value:
        _bounded_text(item, label, item_maximum, required=True)


def _urls(value, label):
    _strings(value, label, item_maximum=500)
    legacy._validate_urls(value, label)
    for url in value:
        # Existing retained outer whitespace stays byte-identical; embedded
        # whitespace, missing hosts and credential-bearing URLs are not sources.
        try:
            parsed = urlsplit(url.strip())
            if (parsed.scheme.lower() != 'https' or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None or parsed.port == 0
                    or re.search(r'\\|\s|[\x00-\x1f\x7f]', url.strip())):
                raise ValueError
        except ValueError:
            raise ValueError(f'{label} contains an invalid HTTPS source URL') from None


def _claim_fields(claim, *, historical=False):
    optional = CLAIM_OPTIONAL - ({'history'} if historical else set())
    _fields(claim, CLAIM_FIELDS, optional, 'audited_claim')
    _texts(claim, CLAIM_TEXT | {'retired_on', 'retirement_reason'}, 'audited_claim')
    _bounds(claim, CLAIM_LIMITS, 'audited_claim')
    if type(claim['revision']) is not int or not 1 <= claim['revision'] <= 2**53 - 1:
        raise ValueError('audited_claim revision must be a positive safe integer')
    _strings(claim['categories'], 'audited_claim.categories', 12, 140)
    _strings(claim['legacy_claim_ids'], 'audited_claim.legacy_claim_ids', 10, 80)
    _urls(claim['source_urls'], 'audited_claim.source_urls')
    if {'retired_on', 'retirement_reason'} & claim.keys():
        if (not {'retired_on', 'retirement_reason'} <= claim.keys()
                or claim['status'] != 'retired' or not legacy._valid_date(claim['retired_on'])):
            raise ValueError('audited_claim invalid retirement metadata')
        _bounded_text(claim['retirement_reason'], 'audited_claim.retirement_reason', 500, required=True)
    if 'evidence_records' in claim:
        _evidence_records(claim['evidence_records'], 'evidence_records')
    if 'history' in claim:
        if not isinstance(claim['history'], list) or len(claim['history']) > 128:
            raise ValueError('audited_claim history must contain claim snapshots')
        for prior in claim['history']:
            _claim_fields(prior, historical=True)
            if prior['claim_id'] != claim['claim_id'] or prior['material_hash'] != material_claim_hash(prior):
                raise ValueError('audited_claim historical identity changed')
        revisions = [prior['revision'] for prior in claim['history']]
        if len(set(revisions)) != len(revisions) or any(revision >= claim['revision'] for revision in revisions):
            raise ValueError('audited_claim historical revisions must be unique and older')


def _person_fields(person):
    _fields(person, PERSON_TEXT | PERSON_LISTS | {'claims', 'auto_proposable'}, PERSON_OPTIONAL, 'audited_researcher')
    _texts(person, PERSON_TEXT | {'pool_assignment'}, 'audited_researcher')
    _bounds(person, PERSON_LIMITS, 'audited_researcher')
    for key in ('legacy_ids', 'aliases'):
        _strings(person[key], 'audited_researcher.' + key, item_maximum=120)
    _urls(person['source_urls'], 'audited_researcher.source_urls')
    if 'official_interests' in person:
        _strings(person['official_interests'], 'audited_researcher.official_interests')
    for key, fields in (('institution', {'name', 'ror_id'}), ('external_ids', {'openalex'}),
                        ('source_audit', AUDIT_FIELDS)):
        if key in person:
            _fields(person[key], fields, set(), 'audited_researcher.' + key)
            _texts(person[key], fields, 'audited_researcher.' + key)
    if 'institution' in person:
        _bounds(person['institution'], {'name': 300, 'ror_id': 25}, 'audited_researcher.institution')
    if 'external_ids' in person:
        value = person['external_ids']['openalex']
        if value and not re.fullmatch(r'https://openalex\.org/A[0-9]{1,20}', value):
            raise ValueError('audited_researcher invalid OpenAlex identity')
    if 'source_audit' in person:
        audit = person['source_audit']
        if (audit['version'] != 'full-profile-repair-v1'
                or not re.fullmatch(r'[a-f0-9]{64}', audit['baseline_material'])
                or audit['disposition'] not in {'corrected', 'unresolved'}
                or not legacy._valid_date(audit['reviewed_on'])):
            raise ValueError('audited_researcher invalid source audit provenance')
        _bounded_text(audit['issues'], 'audited_researcher.source_audit.issues', 500, required=True)
        _bounded_text(audit['limitations'], 'audited_researcher.source_audit.limitations', 500)
    if 'metrics' in person:
        _fields(person['metrics'], {'openalex_works_count'}, set(), 'audited_researcher.metrics')
        count = person['metrics']['openalex_works_count']
        if count is not None and (type(count) is not int or not 0 <= count <= 2**53 - 1):
            raise ValueError('audited_researcher works count must be a nonnegative integer or null')


def material_claim_hash(claim):
    material = {key: claim.get(key) for key in MATERIAL_FIELDS}
    if 'evidence_records' in claim:
        material['evidence_records'] = claim['evidence_records']
    return legacy.content_hash(material)


def _evidence_records(records, label):
    if not isinstance(records, list) or not 1 <= len(records) <= 64:
        raise ValueError(f'{label} must contain source observations')
    for record in records:
        _fields(record, OBSERVATION_FIELDS, set(), label)
        _texts(record, OBSERVATION_FIELDS - {'retrieved_at'}, label)
        if not isinstance(record, dict) or record.get('form') not in {'quotation', 'paraphrase'}:
            raise ValueError(f'{label} must distinguish quotation from paraphrase')
        _urls([record.get('url')], label)
        if record.get('source_type') not in {'official_profile', 'researcher_group',
                                            'attributed_publication', 'institutional_research_report'}:
            raise ValueError(f'{label} has an unsupported source type')
        for key in ('response_sha256', 'text_sha256'):
            if not re.fullmatch(r'[a-f0-9]{64}', str(record.get(key) or '')):
                raise ValueError(f'{label} has an invalid source identity')
        _bounded_text(record.get('locator'), label, 500, required=True)
        if not legacy._valid_date(str(record.get('reviewed_on') or '')):
            raise ValueError(f'{label} has an invalid review date')
        retrieved_at = record.get('retrieved_at')
        try:
            if not isinstance(retrieved_at, str) or len(retrieved_at) > 64 or not re.fullmatch(
                    r'[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]'
                    r'(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', retrieved_at):
                raise ValueError
            datetime.fromisoformat(retrieved_at)
        except ValueError:
            raise ValueError(f'{label} has an invalid retrieval timestamp') from None


def validate(registry):
    """Validate original audited identities plus unchanged common ownership rules.

    A detached copy adapts only the material-hash field for the legacy structural
    validator. Original audited material hashes and generation are checked first;
    neither the caller's object nor any on-disk input is rewritten.
    """
    _fields(registry, REGISTRY_FIELDS, set(), 'audited_registry')
    if type(registry['schema_version']) is not int or not isinstance(registry['registry_generation'], str):
        raise ValueError('audited_registry scalar fields')
    if not isinstance(registry.get('researchers'), list):
        raise ValueError('audited_registry_shape')
    if registry.get('registry_generation') != legacy.registry_generation(registry):
        raise ValueError('audited_registry_generation')
    structural = copy.deepcopy(registry)
    for person, structural_person in zip(registry['researchers'], structural['researchers']):
        _person_fields(person)
        if not isinstance(person, dict) or not isinstance(person.get('claims'), list):
            raise ValueError('audited_researcher_shape')
        if 'pool_assignment' in person and person['pool_assignment'] not in {'main', 'standby'}:
            raise ValueError('audited_pool_assignment')
        if 'summary_evidence' in person:
            _evidence_records(person['summary_evidence'], 'summary_evidence')
        for claim, structural_claim in zip(person['claims'], structural_person['claims']):
            _claim_fields(claim)
            if claim.get('material_hash') != material_claim_hash(claim):
                raise ValueError('audited_claim_material_hash')
            structural_claim['material_hash'] = legacy.material_claim_hash(claim)
            for prior in claim.get('history', []):
                # Revisions legitimately reuse their owner's legacy claim IDs.
                # Validate each snapshot independently with all normal claim
                # semantics, substituting only its audited material hash.
                historical_claim = dict(prior, material_hash=legacy.material_claim_hash(prior))
                historical_person = dict(structural_person, claims=[historical_claim])
                legacy.validate_registry({'schema_version': registry['schema_version'],
                                          'researchers': [historical_person]}, require_generation=False)
    legacy.validate_registry(structural, require_generation=False)
    return registry


def pool_state(person):
    if (person['status'] == 'active' and person['pool_visibility'] not in {'reference_only', 'hidden'}
            and any(claim['status'] == 'active' for claim in person['claims'])
            and person.get('pool_assignment') == 'standby'):
        return 'standby'
    return legacy.pool_state(person)


def counts(registry):
    value = legacy.registry_counts(registry)
    pools = Counter(pool_state(person) for person in registry['researchers'])
    value['pool_counts'] = {key: pools.get(key, 0) for key in ('main', 'standby', 'unadmitted')}
    return value


def matching_domains(person):
    claims = [claim for claim in person['claims'] if claim['status'] == 'active']
    categories = {category for claim in claims for category in
                  (claim.get('categories') or [claim['category']]) if category}
    terms = [text for claim in claims for text in (claim['label'], claim['evidence'])]
    return sorted(categories | set(_pi_domains({'key_terms': terms})))


def directory(registry):
    validate(registry)
    value = legacy.directory_projection(registry)
    value['counts'] = counts(registry)
    for person, projected in zip(registry['researchers'], value['researchers']):
        projected['pool_state'] = pool_state(person)
        projected['matching_domains'] = matching_domains(person)
        if 'summary_evidence' in person:
            projected['summary_evidence'] = copy.deepcopy(person['summary_evidence'])
        for claim, target in zip(person['claims'], projected['claims']):
            target['verified_on'] = claim['verified_on']
            if 'evidence_records' in claim:
                target['evidence_records'] = copy.deepcopy(claim['evidence_records'])
    return copy.deepcopy(value)


def faculty(registry):
    validate(registry)
    value = legacy.legacy_faculty_projection(registry)
    for person, projected in zip(registry['researchers'], value):
        projected.update(pool_state=pool_state(person), research_summary=person['research_summary'],
                         matching_domains=matching_domains(person))
        if 'summary_evidence' in person:
            projected['summary_evidence'] = copy.deepcopy(person['summary_evidence'])
        active = [claim for claim in person['claims'] if claim['status'] == 'active']
        for claim, target in zip(active, projected['terms']):
            target['verified_on'] = claim['verified_on']
            if 'evidence_records' in claim:
                target['evidence_records'] = copy.deepcopy(claim['evidence_records'])
    return copy.deepcopy(value)


def matching_profiles(registry):
    validate(registry)
    people = {person['researcher_id']: person for person in registry['researchers']}
    value = legacy.matching_profiles(registry)
    for target in value:
        person = people[target['researcher_id']]
        target['summary_evidence'] = copy.deepcopy(person.get('summary_evidence', []))
        target['claims'] = [{key: copy.deepcopy(claim[key]) for key in FORWARD_CLAIM_FIELDS if key in claim}
                            for claim in person['claims'] if claim['status'] == 'active']
        target['domains'] = matching_domains(person)
    return copy.deepcopy(value)


def preserve_forward_evidence(matches, profiles):
    """Attach exact evidence to existing deterministic matches without changing scores."""
    result = copy.deepcopy(matches)
    by_name = {profile['name']: profile for profile in profiles}
    if len(by_name) != len(profiles) or not set(result['faculty']).issubset(by_name):
        raise ValueError('forward_profile_identity_mismatch')
    if any(by_name[name]['claims'] or by_name[name]['domains']
           for name in set(by_name) - set(result['faculty'])):
        raise ValueError('forward_profile_evidence_omitted')
    for name, target in result['faculty'].items():
        profile = by_name[name]
        if target.get('researcher_id') != profile['researcher_id']:
            raise ValueError('forward_researcher_identity_mismatch')
        target['summary_evidence'] = copy.deepcopy(profile['summary_evidence'])
        target['claims'] = copy.deepcopy(profile['claims'])
    return result
