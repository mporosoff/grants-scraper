"""Finite contextual wire bounds, without credentials or provider dispatch.

The provider prompt cache is disabled. Our own durable result cache is separate.
These bounds reject oversize generated packets; they never clip source evidence.
"""
import json
from tools.offline_spend import encoded, Deferred

TASK_MICROUSD = 5_000_000
TASK_ATTEMPTS = 40
INTERPRETATION_WIRE_BYTES = 12_000
PROPOSED_EDGES_WIRE_BYTES = 4_096
JUDGE_BODY_BYTES = 44_000
QUERY_TOKEN_BOUND = 25_000
# One operational capacity correction after an observed 8,000-token reasoning
# exhaustion. Scientific contracts and logical request keys remain unchanged.
CAPACITY_VERSION = 'contextual-output-capacity-v2'
ASSESSMENT_OUTPUT_TOKENS = 16_000


def output_capacity(body, stage):
    if stage != 'adjudication':
        return body, 0
    original = len(encoded(body))
    revised = body | {'max_tokens': ASSESSMENT_OUTPUT_TOKENS}
    return revised, len(encoded(revised)) - original


def wire_bytes(value):
    # Inputs are serialized into a JSON string by the existing transport, then
    # escaped once more in the wire envelope. Bound exactly that representation.
    return len(encoded(json.dumps(value, ensure_ascii=False)))


def no_provider_cache(body):
    def visit(value):
        if isinstance(value, dict):
            if 'cache_control' in value or 'cache_creation' in value:
                raise ValueError('contextual_provider_cache_not_authorized')
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(body)
    if body.get('model') != 'claude-sonnet-5':
        raise ValueError('contextual_fixed_text_model_required')


def text_reservation(body):
    no_provider_cache(body)
    bound = len(encoded(body)) + 1024
    return bound, bound * 2 + body['max_tokens'] * 10


def generated_input_bounds(interpretation, proposed_edges=None):
    if wire_bytes(interpretation) > INTERPRETATION_WIRE_BYTES:
        raise Deferred('interpretation_packet_resource_bound_no_truncation')
    if proposed_edges is not None and wire_bytes(proposed_edges) > PROPOSED_EDGES_WIRE_BYTES:
        raise Deferred('verification_identity_packet_resource_bound_no_truncation')
