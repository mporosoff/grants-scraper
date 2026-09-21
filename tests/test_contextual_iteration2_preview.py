import base64
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import build_contextual_iteration2_preview as preview


class PreviewCatalogCohortTests(unittest.TestCase):
    def test_stale_product_catalog_or_metadata_cannot_replace_locked_preview(self):
        base = json.loads((preview.ROOT/'workers/researcher-intake/config/contextual-preview-v1.json').read_bytes())
        output = preview.ROOT/'workers/researcher-intake/config/contextual-iteration2-preview-v1.json'
        before = output.read_bytes()
        original_read = Path.read_bytes
        for name, error in [('opportunities.js', 'locked_catalog_required'),
                            ('catalog-metadata.js', 'metadata_cohort_mismatch')]:
            with self.subTest(asset=name):
                target = preview.ROOT/'data'/name
                stale = gzip.decompress(base64.b64decode(base['files']['data/'+name]['gzip_base64']))
                def read(path):
                    return stale if path == target else original_read(path)
                with patch.object(Path, 'read_bytes', read), patch.object(preview, 'atomic_json') as write:
                    with self.assertRaisesRegex(ValueError, error):
                        preview.build()
                    write.assert_not_called()
                self.assertEqual(output.read_bytes(), before)
