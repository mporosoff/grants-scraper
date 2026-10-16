import assert from "node:assert/strict";
import test from "node:test";
import {digest} from "../../tools/embedding_contract.mjs";
import {corpusHash, verifyOrderedCorpus} from "../../tools/catalog_schedule_package.mjs";

function fixture() {
  const corpus = [
    {passage_id:"parent:1", parent_id:"1", record_id:"1", passage_kind:"parent", text:"Quantum sensing research"},
    {passage_id:"child:2", parent_id:"1", record_id:"2", passage_kind:"child", text:"Atomic sensor development"},
  ];
  return {originalCorpus:corpus, corpus:structuredClone(corpus), manifest:{
    passage_count:corpus.length, corpus_sha256:corpusHash(corpus),
    passages:corpus.map(({text, ...identity}) => ({...identity, text_sha256:digest(text)})),
  }};
}

test("schedule package accepts an identical complete ordered scientific corpus", () => {
  assert.doesNotThrow(() => verifyOrderedCorpus(fixture()));
});

test("schedule projection rejects changed text, membership, order, and parent ownership", () => {
  const mutations = [
    rows => { rows[0].text = "Different scientific topic"; },
    rows => { rows.pop(); },
    rows => { rows.reverse(); },
    rows => { rows[1].parent_id = "other"; },
  ];
  for (const mutate of mutations) {
    const input = fixture();
    mutate(input.corpus);
    assert.throws(() => verifyOrderedCorpus(input), /exact_ordered_corpus_identity/);
  }
});

test("parent corpus must independently match every manifest passage and text hash", () => {
  for (const field of ["text_sha256", "record_id", "passage_kind", "parent_id", "passage_id"]) {
    const input = fixture();
    input.manifest.passages[0][field] = "different";
    assert.throws(() => verifyOrderedCorpus(input), /parent_passage/, field);
  }
  const incomplete = fixture();
  incomplete.manifest.passage_count++;
  assert.throws(() => verifyOrderedCorpus(incomplete), /parent_corpus/);
});
