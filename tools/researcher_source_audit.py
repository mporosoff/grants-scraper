"""Fetch bounded public roster sources and retain honest retrieval receipts.

This tool does not review evidence or write researcher claims. Completion of a
fetch is deliberately separate from the per-person authored audit disposition.
"""
from __future__ import annotations
import argparse, concurrent.futures, datetime, hashlib, io, json, pathlib, re
from urllib.parse import urlparse, urljoin
from html.parser import HTMLParser
import requests

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/researcher-profile-repair'

def sha(data): return hashlib.sha256(data).hexdigest()
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())

class PageText(HTMLParser):
    """Retain all substantive page text; use the declared main region if any."""
    def __init__(self,url):
        super().__init__(convert_charrefs=True)
        self.url=url;self.text=[];self.links=[];self.stack=[];self.suppressed=[];self.anchor=None;self.main_start=None;self.main_end=None;self.main_depth=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in {'script','style','noscript','nav','footer','form'}:self.suppressed.append(tag)
        if tag not in {'meta','link','img','br','hr','input','source','wbr','area','embed','param','col','base'}:self.stack.append(tag)
        if (tag=='main' or attrs.get('id') in {'main','main-content'}) and self.main_start is None:
            self.main_start=len(self.text);self.main_depth=len(self.stack)
        if tag=='a' and not self.suppressed and attrs.get('href'):self.anchor={'url':urljoin(self.url,attrs['href']),'text':''}
        if tag in {'p','li','h1','h2','h3','h4','h5','div','section','br','tr','dt','dd'} and not self.suppressed:self.text.append('\n')
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor:self.links.append(self.anchor);self.anchor=None
        if not self.suppressed and tag in {'p','li','h1','h2','h3','h4','h5','div','section','tr','dt','dd'}:self.text.append('\n')
        if self.main_depth==len(self.stack) and self.stack and self.stack[-1]==tag and self.main_end is None:self.main_end=len(self.text)
        if tag in self.stack:self.stack=self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]
        if tag in self.suppressed:self.suppressed.remove(tag)
    def handle_data(self,data):
        if not self.suppressed:
            self.text.append(data)
            if self.anchor:self.anchor['text']+=data
    def result(self):
        parts=self.text[self.main_start:self.main_end] if self.main_start is not None else self.text
        # Some personal sites use id="main" for a two-button menu, with the
        # research text in a sibling element. Never mistake that for the page.
        if self.main_start is not None and len(''.join(parts).strip())<100 and len(''.join(self.text).strip())>500:
            parts=self.text
        return [re.sub(r'\s+',' ',x).strip() for x in ''.join(parts).splitlines() if x.strip()],self.links

def fetch(url):
    key=sha(url.encode());dest=OUT/'sources'/f'{key}.json'
    if dest.exists(): return json.loads(dest.read_bytes())
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTPS source URLs are accepted')
    when=datetime.datetime.now(datetime.timezone.utc).isoformat()
    receipt={'url':url,'attempted_at':when,'reviewed':False}
    try:
        response=requests.get(url,timeout=(15,35),headers={'User-Agent':'GrantsScraper-PublicResearcherAudit/1.0 (+https://github.com/mporosoff/grants-scraper)','Accept':'text/html,application/xhtml+xml','Accept-Language':'en-US,en;q=0.8'},stream=True)
        response.raise_for_status();data=b''
        for chunk in response.iter_content(65536):
            data+=chunk
            if len(data)>5_000_000:raise ValueError('Source exceeds 5 MB HTML bound; separate document handling required')
        if data.startswith(b'%PDF-'):
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data))
            if len(reader.pages)>100:raise ValueError('PDF exceeds 100-page bound')
            lines=[];links=[];extension='pdf';version=4
            for number,page in enumerate(reader.pages,1):
                lines.append(f'PDF PAGE {number}')
                lines.extend(re.sub(r'\s+',' ',s).strip() for s in (page.extract_text() or '').splitlines() if s.strip())
        else:
            if 'html' not in response.headers.get('Content-Type','').lower():raise ValueError('Unsupported source format; not counted as reviewed')
            parser=PageText(response.url);parser.feed(data.decode('utf-8',errors='replace'))
            lines,links=parser.result();extension='html';version=3
        receipt.update(status=response.status_code,final_url=response.url,fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),content_type=response.headers.get('Content-Type',''),response_sha256=sha(data),text_sha256=sha(('\n'.join(lines)+'\n').encode()),lines=lines,links=links,bytes=len(data),text_extraction_version=version)
        (OUT/'sources').mkdir(parents=True,exist_ok=True);(OUT/'sources'/f'{key}.{extension}').write_bytes(data)
    except (requests.RequestException,ValueError) as exc:
        receipt.update(error=str(exc),status=getattr(getattr(exc,'response',None),'status_code',None))
    write(dest,receipt);return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--extra',type=pathlib.Path);a=p.parse_args()
    registry=json.loads((ROOT/'config/researcher_registry.json').read_bytes());OUT.mkdir(parents=True,exist_ok=True)
    baseline=OUT/'baseline-registry.json'
    if not baseline.exists():baseline.write_bytes((ROOT/'config/researcher_registry.json').read_bytes())
    urls=json.loads(a.extra.read_bytes()) if a.extra else list(dict.fromkeys(r['source_urls'][0] for r in registry['researchers']))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(fetch,urls))
    write(OUT/('extra-retrievals.json' if a.extra else 'primary-retrievals.json'),{'registry_generation':registry['registry_generation'],'population':len(registry['researchers']),'sources':results})
    print(json.dumps({'population':len(registry['researchers']),'requests_or_cache_reads':len(results),'fetched':sum('fetched_at' in x for x in results),'unresolved':[{k:r.get(k) for k in ['url','status','error']} for r in results if 'fetched_at' not in r],'reviews_completed_by_fetcher':0}))

if __name__=='__main__':main()
