"""Finite original-source gap retrieval; no credentials or metered providers."""
from datetime import datetime, timezone
from pathlib import Path
import io
import requests
from pypdf import PdfReader
from tools.team_recommender_real_prep import ROOT, sha, write

URLS = {
    'rtrp-concept': 'https://cdmrp.health.mil/funding/pa/HT942526RTRPCA_GG2.pdf',
    'vision-investigator': 'https://cdmrp.health.mil/funding/pa/HT942526VRPIIRA_GG.pdf',
    'vision-translational': 'https://cdmrp.health.mil/funding/pa/HT942526VRPTRA_GG.pdf',
    'nasa-atmosphere': 'https://science.nasa.gov/researchers/solicitations/roses-2025/amendment-63-new-opportunity-a-14-atmosphere/',
}

def main():
    out = ROOT/'outputs/team-recommender-stage3/source-retrieval'
    out.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        target = out/(name+'.json')
        if target.exists():
            print(name, 'existing attempt retained'); continue
        receipt = {'source_url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'paid_calls': 0}
        try:
            with requests.get(url, timeout=40, stream=True, allow_redirects=False,
                              headers={'User-Agent':'grants-scraper-source-validation/1.0', 'Accept':'application/pdf,text/html'}) as response:
                receipt['http_status'] = response.status_code
                response.raise_for_status()
                if response.status_code != 200: raise ValueError('redirect_not_followed')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 4*1024*1024: raise ValueError('source_size_bound')
            raw = bytes(data); digest = sha(raw)
            suffix = '.pdf' if url.endswith('.pdf') else '.html'
            (out/(digest+suffix)).write_bytes(raw)
            receipt.update(status='retrieved', document_sha256=digest, bytes=len(raw))
            if suffix == '.pdf':
                receipt['pages'] = [page.extract_text() for page in PdfReader(io.BytesIO(raw)).pages]
                receipt['text_sha256'] = sha('\n'.join(receipt['pages']))
        except Exception as exc:
            receipt.update(status='unresolved', error=type(exc).__name__+':'+str(exc)[:200])
        write(target, receipt)
        print(name, receipt['status'], receipt.get('bytes'), receipt.get('error',''))

if __name__ == '__main__': main()
