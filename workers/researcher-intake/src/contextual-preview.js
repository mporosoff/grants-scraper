// Exact reviewed application assets, available only after existing admin Access.
// No external asset proxy, arbitrary path loading, provider cache or new binding.
import bundle from '../config/contextual-preview-v1.json' with {type:'json'};
export function previewResponse(path){
  if(!path.startsWith(bundle.base_path))return null;
  const name=path.slice(bundle.base_path.length)||'match_explorer.html';
  const file=Object.hasOwn(bundle.files,name)?bundle.files[name]:null;
  if(!file)return new Response('Preview asset unavailable',{status:404,headers:{'Cache-Control':'no-store'}});
  const bytes=Uint8Array.from(atob(file.gzip_base64),c=>c.charCodeAt(0));
  // These bytes are already gzip encoded. Workers otherwise compress them again.
  return new Response(bytes,{encodeBody:'manual',headers:{'Content-Type':file.content_type,'Content-Encoding':'gzip',
    'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
    'X-Contextual-Preview':bundle.bundle_id,'X-Content-SHA256':file.sha256,
    'Content-Security-Policy':"connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"}});
}
