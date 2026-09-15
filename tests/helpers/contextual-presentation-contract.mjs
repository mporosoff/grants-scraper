import assert from 'node:assert/strict';

// Contextual Stage B explicitly authorizes this separate deliberate action for
// an unassessed person. Compare every other renderer byte to the old freeze.
// Keep the historical baseline untouched, and reject any broader exception.
const authorizedAction = `      (current.engine.contextual&&view.replacements.some(function(item){return item.assessment_state==='unassessed'&&current.engine.canAssessPerson?.(item.profile.id);})
        ? '<button type="button" class="button secondary" data-contextual-assess disabled>Assess this person’s contribution</button>' : '') +
`;
export function withoutContextualAssessmentAction(source) {
  assert.equal(source.split(authorizedAction).length, 2, 'exactly one authorized assessment control');
  return source.replace(authorizedAction, '');
}

const authorizedStates = `      contextual_unassessed: "This scope has not been contextually assessed. Use Build a team to request an assessment.",
      contextual_insufficient_source: "The retained source does not provide enough context for this assessment. This is not a judgment about the researchers.",
      contextual_budget_limited: "The bounded assessment allowance or request capacity is unavailable. Current profiles remain available for manual selection.",
      contextual_recovery_required: "A prior assessment request needs recovery. It will not be sent again automatically.",
      contextual_unsuitable: "The source assessment did not establish a coherent supported scope for this team workflow.",
      contextual_action_blocked: "This opportunity is no longer current. Its assessment is not displayed.",
      contextual_failed: "The assessment could not be completed. This is an execution failure, not a scientific rejection.",
`;
export function preservedPresentation(source, name) {
  if (name === 'renderProposal') return withoutContextualAssessmentAction(source);
  if (name === 'renderUnavailable') {
    assert.equal(source.split(authorizedStates).length, 2, 'exactly the seven authorized contextual status messages');
    return source.replace(authorizedStates, '');
  }
  return source;
}
