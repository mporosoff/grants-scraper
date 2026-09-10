"""Bounded public official-source gap retrieval; no models or credentials."""
from datetime import datetime, timezone
import io
import json
import requests
from pypdf import PdfReader
from tools.team_recommender_real_prep import OUT, sha, write

URLS={
 'hwo':'https://nspires.nasaprs.com/external/viewrepositorydocument?cmdocumentid=1162128&solicitationId=%7BBE2AA4DC-81E7-2AF3-B465-8AA6478270A4%7D&viewSolicitationDocument=1',
 'tcan':'https://nspires.nasaprs.com/external/viewrepositorydocument?cmdocumentid=1046259&solicitationId=%7B5509DEBF-B8B4-2F3D-0EFB-350EFE67DCD5%7D&viewSolicitationDocument=1',
 'quantum':'https://www.army.mil/article/261533'}

def main():
    for name,url in URLS.items():
        path=OUT/'source-retrieval'/f'{name}.json'
        if path.exists():print(name,'retained exact local fetch');continue
        receipt={'source_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'paid_calls':0}
        try:
            with requests.get(url,timeout=40,stream=True,allow_redirects=False) as response:
                receipt['http_status']=response.status_code
                response.raise_for_status()
                if response.status_code!=200:raise ValueError('redirect_not_followed')
                content=bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content)>4*1024*1024:raise ValueError('source_bound')
            raw=bytes(content);receipt.update({'document_sha256':sha(raw),'bytes':len(raw)})
            target=OUT/'source-retrieval'/(sha(raw)+('.pdf' if name!='quantum' else '.html'))
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            if name!='quantum':
                reader=PdfReader(io.BytesIO(raw));receipt['pages']=[p.extract_text() for p in reader.pages]
                receipt['text_sha256']=sha('\n'.join(receipt['pages']))
            receipt['status']='retrieved'
        except Exception as exc:receipt.update({'status':'unresolved','error':type(exc).__name__+':'+str(exc)[:180]})
        write(path,receipt);print(name,receipt['status'],receipt.get('bytes'),receipt.get('error',''))
if __name__=='__main__':main()
