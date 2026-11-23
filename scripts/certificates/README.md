The Grants.gov HTTPS profile supplies the public HydrantID Server CA O1
intermediate omitted by the measured server chain on November 23, 2026.
It applies only to `grants.gov` and `www.grants.gov` on HTTPS port 443.
Hostname verification and a complete chain to the existing certifi roots are
required; `VERIFY_X509_PARTIAL_CHAIN` is cleared. This certificate does not add
a root or change system trust. The official extract's S3 archive uses ordinary
TLS verification without the supplement.

Issuer publication: http://validation.identrust.com/certs/hydrantidcaO1.p7c
(the leaf certificate's public Authority Information Access URI). The public
PKCS#7 download was authenticated by verifying the intermediate's signature
against the already trusted certifi IdenTrust Commercial Root CA 1, rather
than trusting the HTTP transport. OpenSSL `verify` returned `OK`.

- Intermediate SHA-256: `8bb2f6883fed289a521ba27c478482950874e143caccec6fc025990c0c46813e`
- Existing root SHA-256: `5d56499be4d2e08bcfcad08a3e38723d50503bde706948e42f55603019e528ae`
- Intermediate validity: December 12, 2019 through December 12, 2029.

The intermediate fingerprint is checked before constructing the TLS context.
Its bytes are included in the source generation dependency fingerprint.
