"""Offline original-source validation. No provider or source-retrieval client.

Call with an existing authorized extraction, never model-generated source text.
Receipts preserve the original retrieval identity/time. No freshness is fabricated.
"""
import hashlib
import re


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


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
