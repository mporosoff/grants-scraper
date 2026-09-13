import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import bundle from '../../workers/researcher-intake/config/contextual-preview-v1.json' with {type:'json'};
import {previewResponse} from '../../workers/researcher-intake/src/contextual-preview.js';

test('every precompressed preview asset disables Worker re-encoding and decodes to exact reviewed bytes',async t=>{
  const NativeResponse=globalThis.Response;let mode;
  // Node does not implement the Workers encodeBody extension. Capture that
  // boundary explicitly; the retained local workerd HTTP receipt checks it too.
  t.mock.method(globalThis,'Response',function(body,init){mode=init?.encodeBody;return new NativeResponse(body,init);});
  for(const [name,file] of Object.entries(bundle.files)){
    const response=previewResponse(bundle.base_path+name);
    assert.equal(mode,'manual',name);
    assert.equal(response.headers.get('Content-Encoding'),'gzip',name);
    assert.equal(response.headers.get('Content-Type'),file.content_type,name);
    const raw=gunzipSync(Buffer.from(await response.arrayBuffer()));
    assert.equal(raw.length,file.bytes,name);
    assert.equal(createHash('sha256').update(raw).digest('hex'),file.sha256,name);
  }
  assert.equal(previewResponse(bundle.base_path+'missing').status,404);
  assert.equal(previewResponse('/elsewhere'),null);
});
