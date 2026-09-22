// Exact reviewed application assets, available only after existing admin Access.
// No external asset proxy, arbitrary path loading, provider cache or new binding.
import bundle from '../config/contextual-preview-v1.json' with {type:'json'};
import iteration2 from '../config/contextual-iteration2-preview-v1.json' with {type:'json'};
import iteration3 from '../config/contextual-iteration3-preview-v1.json' with {type:'json'};
export function previewResponse(path){
  const selected=path.startsWith(iteration3.base_path)?iteration3:path.startsWith(iteration2.base_path)?iteration2:bundle;
  if(!path.startsWith(selected.base_path))return null;
  const name=path.slice(selected.base_path.length)||'match_explorer.html';
  const file=Object.hasOwn(selected.files,name)?selected.files[name]:Object.hasOwn(bundle.files,name)?bundle.files[name]:null;
  if(!file)return new Response('Preview asset unavailable',{status:404,headers:{'Cache-Control':'no-store'}});
  const bytes=Uint8Array.from(atob(file.gzip_base64),c=>c.charCodeAt(0));
  // These bytes are already gzip encoded. Workers otherwise compress them again.
  return new Response(bytes,{encodeBody:'manual',headers:{'Content-Type':file.content_type,'Content-Encoding':'gzip',
    'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
    'X-Contextual-Preview':selected.bundle_id,'X-Content-SHA256':file.sha256,
    'Content-Security-Policy':"connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"}});
}
