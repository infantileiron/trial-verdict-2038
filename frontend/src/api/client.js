export async function api(path,options={}){const token=localStorage.getItem('token');let r=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{}),...options.headers}});if(!r.ok){let e=await r.json().catch(()=>({detail:r.statusText}));throw Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail))}return r.json()}
export const post=(path,data)=>api(path,{method:'POST',body:JSON.stringify(data)});
export const put=(path,data)=>api(path,{method:'PUT',body:JSON.stringify(data)});
/* 名册整版导入：直接提交文本，前端只做 CSV 解析与行号提示，校验仍在服务端。 */
export function parseRoster(text){const rows=text.split(/\r?\n/).map((line,i)=>({line:i+1,text:line.trim()})).filter(r=>r.text&&!r.text.startsWith('#'));if(rows.length&&/user|用户/i.test(rows[0].text.split(',')[0]))rows.shift();return rows.map(r=>{let [user_key,group,...rest]=r.text.split(',').map(x=>x.trim());return {line:r.line,user_key,group:(group||'').toUpperCase()}});}
