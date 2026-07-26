# Browser parser dependencies

These files are committed so CV parsing does not load code from a third-party
CDN at runtime.

| File | Package/version | SHA-256 |
|---|---|---|
| `pdf.mjs` | Mozilla PDF.js (`pdfjs-dist` 6.1.200) | `D7F44E075A8FA47AC165362D404DE2DABF61F64F3D98C9180162C5F71F54980A` |
| `pdf.worker.mjs` | Mozilla PDF.js (`pdfjs-dist` 6.1.200) | `F9ED6A050771AD74C228A1CBFC8EDB3271249F2E2EFA29ED4692468ECB001733` |
| `mammoth.browser.min.js` | Mammoth 1.12.0 | `5D4C0E7C9165D70B78F789C5274A2C7846D9E1C06EC19B69AFA6EF45F789A3B9` |

License texts are retained as `pdfjs.LICENSE` and `mammoth.LICENSE`.

When updating a dependency, replace the matching browser distribution file,
refresh its license notice and hash, run the profile contract tests, and
exercise a real upload through the local site.
