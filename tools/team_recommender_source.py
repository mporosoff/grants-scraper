"""Offline original-source validation. No provider or source-retrieval client.

Call with an existing authorized extraction, never model-generated source text.
Receipts preserve the original retrieval identity/time. No freshness is fabricated.
"""
import hashlib
import re
import json
from urllib.parse import urlsplit


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def translate_official_export(*, artifact_bytes, record, scope_id, parent_id, excerpts, snapshot_at, source_url, export_identity):
    """Category A: verify retained official fields, without inventing retrieval.

    The export artifact and exact field identity are the retained provenance.
    Its creation time is an observation, not an HTTP retrieval timestamp. No
    claim is made about unread annexes or the latest remote notice revision.
    """
    raw=artifact_bytes.decode('utf-8')
    data=json.loads(raw[raw.index('{'):raw.rfind('}')+1])
    canonical_nsf = re.fullmatch(r'nsf-funding:https://www\.nsf\.gov/funding/opportunities/[a-z0-9]+(?:-[a-z0-9]+)*/nsf(\d{2}-\d{3})',scope_id)
    alias = bool(canonical_nsf and record.get('opportunity_number') == canonical_nsf[1]
        and record.get('agency_code')=='NSF' and record.get('funding_opportunity_url') == 'https://www.nsf.gov/publications/pub_summ.jsp?ods_key=nsf'+canonical_nsf[1].replace('-',''))
    if (record.get('opportunity_id') != parent_id and not alias) or scope_id != parent_id:
        raise ValueError('retained_export_parent_ownership')
    actual=next((r for r in data.get('opportunities',[]) if r.get('opportunity_id')==record['opportunity_id']),None)
    if actual != record or data.get('generated_at')!=snapshot_at:
        raise ValueError('retained_export_record_mismatch')
    if data.get('source',{}).get('extract_file')!=export_identity or not re.fullmatch(r'GrantsDBExtract\d{8}v\d+\.zip',export_identity):
        raise ValueError('unidentified_official_export')
    host=urlsplit(source_url).hostname
    if record.get('source')!='Grants.gov' or host not in ('www.grants.gov','grants.gov'):
        raise ValueError('not_original_official_synopsis')
    if record.get('description_source'):
        raise ValueError('separate_enriched_description_provenance_required')
    fields=[]
    for e in excerpts:
        field=e['locator']
        if field not in ('title','description','eligibility_text') or e['text']!=record.get(field) or e['offset']!=0 or digest(e['text'])!=e['sha256']:
            raise ValueError('retained_export_field_mismatch')
        fields.append({'field':field,'sha256':e['sha256']})
    return {'validation':'retained-official-fields-verified','scope_id':scope_id,'parent_id':parent_id,
        'document_sha256':digest(artifact_bytes),'text_sha256':digest(record['description']),
        'retrieved_at':None,'observed_at':snapshot_at,'new_retrieval':False,
        'excerpt_count':len(excerpts),'excerpt_hashes':[e['sha256'] for e in excerpts],
        'semantic_judgment':False,'provenance':{'kind':'official-export-fields-v1','artifact_sha256':digest(artifact_bytes),
            'export_identity':export_identity,'source_url':source_url,'fields':fields},
        'limitations':'Exact retained official export fields, not a newly retrieved notice or complete annex validation. Original HTTP retrieval time is not retained; observed_at is the catalog export creation time. Unknown notice restrictions remain unknown.'}


def translate_nsf_page(*, artifact_bytes, record, excerpts):
    """Translate the existing independently dated official NSF page cache."""
    from scripts.build_catalog import clean_text
    artifact=json.loads(artifact_bytes)
    entry=artifact['records'][record['opportunity_id']]['agency_funding_page']
    url=record['description_source_url']
    if (record.get('description_source')!='Official NSF funding page' or entry['source_url']!=url
        or not re.fullmatch(r'https://www\.nsf\.gov/funding/opportunities/[a-z0-9-]+',url)
        or entry['fetched_at']!=record['description_enriched_at']
        or clean_text(entry['text'])[:12000]!=record['description']):
        raise ValueError('nsf_retained_page_mismatch')
    if len(excerpts)!=1 or excerpts[0]['text']!=record['description'] or excerpts[0]['sha256']!=digest(record['description']):
        raise ValueError('nsf_retained_span_mismatch')
    return {'validation':'retained-nsf-page-verified','scope_id':record['opportunity_id'],'parent_id':record['opportunity_id'],
        'document_sha256':digest(artifact_bytes),'text_sha256':digest(record['description']),
        'retrieved_at':entry['fetched_at'],'new_retrieval':False,'excerpt_count':1,'excerpt_hashes':[excerpts[0]['sha256']],
        'semantic_judgment':False,'provenance':{'kind':'official-nsf-page-v1','artifact_sha256':digest(artifact_bytes),
        'source_url':url,'parser_version':entry['parser_version'],'original_text_sha256':digest(entry['text'])},
        'limitations':'Original dated official NSF page extraction, deterministic existing text cleanup. No new HTTP verification; linked full-notice restrictions remain unknown.'}


def validate_source(source, scope, *, original_bytes, extracted_text, extraction_receipt):
    required = {'scope_id': scope['id'], 'parent_id': scope['parent_id'],
                'document_sha256': digest(original_bytes), 'text_sha256': digest(extracted_text)}
    if any(extraction_receipt.get(k) != v for k, v in required.items()):
        raise ValueError('original_extraction_identity_or_ownership_mismatch')
    if extraction_receipt.get('method') not in {'native-source-structure', 'retained-document-extraction'}:
        raise ValueError('model_approval_is_not_source_validation')
    if not re.fullmatch(r'[a-f0-9]{64}', extraction_receipt.get('extraction_code_sha256', '')):
        raise ValueError('unidentified_extraction')
    if source['document_sha256'] != required['document_sha256']:
        raise ValueError('source_document_changed')
    if extraction_receipt.get('source_url') != source['source_url']:
        raise ValueError('source_url_mismatch')
    for excerpt in source['excerpts']:
        start = excerpt['offset']
        if type(start) is not int or start < 0 or extracted_text[start:start + len(excerpt['text'])] != excerpt['text']:
            raise ValueError('original_source_span_mismatch')
        if digest(excerpt['text']) != excerpt['sha256']:
            raise ValueError('source_span_hash_mismatch')
    source_receipt = source.get('receipt') or {}
    if source_receipt.get('checked_at') != extraction_receipt.get('retrieved_at'):
        raise ValueError('old_retrieval_misrepresented_as_new')
    if source_receipt.get('approach_id') != scope['approach_id']:
        raise ValueError('source_approach_mismatch')
    # Coherence is a separate audited preparation decision, not inferred from a valid quote.
    if extraction_receipt.get('coherent_scope') is not True or extraction_receipt.get('conditions_preserved') is not True:
        raise ValueError('scope_or_conditions_not_validated')
    return {'validation':'original-source-spans-verified', **required,
            'retrieved_at':extraction_receipt['retrieved_at'], 'new_retrieval':False,
            'excerpt_count':len(source['excerpts']), 'excerpt_hashes':[e['sha256'] for e in source['excerpts']],
            'semantic_judgment':False}
