import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import build_contextual_iteration3_continuation_preview as preview


class ContinuationPreview(unittest.TestCase):
    def test_rebuild_is_exact_and_does_not_rewrite_any_historical_bundle(self):
        folder=preview.ROOT/'workers/researcher-intake/config'
        names=('contextual-preview-v1.json','contextual-iteration2-preview-v1.json','contextual-iteration3-preview-v1.json')
        before={n:(folder/n).read_bytes() for n in names}
        expected=json.loads((folder/'contextual-iteration3-continuation-preview-v1.json').read_bytes())
        with patch.object(preview,'atomic_json') as write:
            preview.build()
        self.assertEqual(write.call_count,1)
        self.assertEqual(write.call_args.args,(folder/'contextual-iteration3-continuation-preview-v1.json',expected))
        for name,raw in before.items():self.assertEqual((folder/name).read_bytes(),raw)

    def test_changed_scope_identity_fails_before_output_write(self):
        target=preview.ROOT/'config/contextual_team/iteration3-source-inputs-v1.json'
        source=json.loads(target.read_bytes());next(s for s in source['scopes'] if s['id']=='363268')['source_id']='f'*64
        original=Path.read_bytes
        with patch.object(Path,'read_bytes',lambda path:json.dumps(source).encode() if path==target else original(path)),patch.object(preview,'atomic_json') as write:
            with self.assertRaisesRegex(ValueError,'exact_ai_scope'):preview.build()
            write.assert_not_called()
