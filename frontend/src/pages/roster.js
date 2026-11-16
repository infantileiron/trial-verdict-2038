import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {badge} from '../components/common/status.js';import {ROSTER_STATES,DENOMINATOR_LABEL} from '../constants/enums.js';import {time} from '../utils/format.js';

const status=v=>`<span class="tag ${v.state==='locked'?'good':v.state==='conflict'?'warning':''}">${ROSTER_STATES[v.state]||v.state}</span>`;
function people(title,rows,render){if(!rows||!rows.length)return `<p class="muted">${title}：无</p>`;return `<h3>${title} · ${rows.length} 人</h3><div class="scroll roster-list">${rows.map(render).join('')}</div>`}

export function render(){
  let rosterExps=state.experiments.filter(e=>e.denominator==='roster');
  let chosen=rosterExps.find(e=>e.id===state.rosterFocus)||rosterExps[0];
  return `<div class="split"><section><h2>名册分母 · 让漏报曝光无所遁形</h2>
  <p class="notice">名册实验以整版分组名册的<b>全体成员</b>为激活分母，而不是只统计已上报曝光的人。事件先暂存，名册锁定后唯一归属；名册与曝光日志逐人对账，缺报、未入册与跨组冲突单独列出。既有实验仍按曝光人数统计，不受影响。</p>
  ${rosterExps.length?`<div class="records">${rosterExps.map(e=>`<button data-roster-exp="${e.id}" class="${chosen&&e.id===chosen.id?'active':''}">${esc(e.code)} · ${esc(DENOMINATOR_LABEL[e.denominator]||e.denominator)}</button>`).join('')}</div>${panel(chosen)}`:'<p class="notice">暂无新实验使用名册分母。请先在「实验档案」建立实验并选择“名册全员”。</p>'}
  </section><aside><h2>导入整版名册</h2>${chosen?importForm(chosen):'<p class="muted">先选择或建立名册实验。</p>'}</aside></div>`;
}

function panel(exp){
  let versions=state.rosterVersions[exp.id]||[];
  let active=exp.roster_version,latest=exp.roster_latest;
  let focus=versions.find(x=>x.id===state.rosterVersionFocus)||active||latest||versions[0];
  let rec=focus&&state.rosterReconciliation&&state.rosterReconciliation.version_id===focus.id?state.rosterReconciliation:null;
  let blockers=exp.analysis_blockers||[];
  return `<article class="experiment"><div class="eyebrow">${esc(exp.code)} · ${badge(DENOMINATOR_LABEL[exp.denominator])}</div>
  <h3>${esc(exp.name)}</h3>
  <div class="comparison roster-counters">
    <div><span>名册 ${focus?'v'+focus.version_no:'—'} 全员</span><strong>${focus?focus.member_count:0}</strong><small>A ${focus?focus.group_a_count:0} / B ${focus?focus.group_b_count:0} · 激活分母</small></div>
    <div><span>曝光日志人数</span><strong>${rec?rec.exposure_total:exp.exposures}</strong><small>A ${rec?rec.exposure_a:'—'} / B ${rec?rec.exposure_b:'—'} · 仅用于对账</small></div>
    <div><span>待归属暂存</span><strong>${exp.staged_pending??0}</strong><small>${active?'生效名册可直接归属':'锁定后统一归属'}</small></div>
  </div>
  <h3>名册版本</h3>
  <div class="scroll"><table><thead><tr><th>版本</th><th>状态</th><th>人数</th><th>校验和</th><th>创建 / 锁定</th><th>操作</th></tr></thead><tbody>${versions.map(x=>`<tr><td>v${x.version_no}</td><td>${status(x)}</td><td>${x.member_count}（A ${x.group_a_count} / B ${x.group_b_count}）</td><td title="${esc(x.checksum)}">${esc(x.checksum.slice(0,12))}…</td><td>${time(x.created_at)}<br>${x.locked_at?time(x.locked_at):'—'}</td><td><button data-roster-version="${x.id}">查看对账</button>${x.state==='pending'&&state.user.role!=='viewer'?` <button data-roster-verify="${x.id}">核对</button>`:''}${x.state==='ready'&&state.user.role!=='viewer'?` <button class="primary" data-roster-lock="${x.id}">锁定生效</button>`:''}</td></tr>`).join('')||'<tr><td colspan="6">尚未导入名册。</td></tr>'}</tbody></table></div>
  ${focus&&focus.conflict_reason?`<p class="notice warning">冲突拒绝分析：${esc(focus.conflict_reason)}</p>`:''}
  <h3>分析阻因（${blockers.length}）</h3>
  ${blockers.length?`<ul class="muted">${blockers.map(b=>`<li>${esc(b)}</li>`).join('')}</ul>`:'<p class="notice good">门禁已通过：名册已锁定且对账无跨组冲突，可提交裁决。</p>'}
  ${rec?reconcile(rec):`<p class="muted">选择名册版本后展示与曝光日志的对账结果。</p>`}
  </article>`;
}

function reconcile(rec){
  let cap=n=>n>200?`（仅列前 200，共 ${n} 人）`:'';
  return `<h3>对账结果 · 名册 v${rec.version_no} 与曝光日志</h3>
  <p class="muted">名册 ${rec.roster_total} 人（A ${rec.roster_a} / B ${rec.roster_b}）；曝光日志去重 ${rec.exposure_total} 人（A ${rec.exposure_a} / B ${rec.exposure_b}）；激活 A ${rec.activated_a} / B ${rec.activated_b}；暂存未归属 ${rec.staged_pending} 条。</p>
  <div class="recon"><span>缺报曝光 ${rec.missing_report_total}</span><span>未入册事件 ${rec.unrostered_total}</span><span>跨组冲突 ${rec.cross_group_total}</span></div>
  ${people('缺报曝光'+cap(rec.missing_report_total),rec.missing_report,m=>`<span>${esc(m.user_key)} · ${esc(m.group)} 组</span>`)}
  ${people('未入册事件'+cap(rec.unrostered_total),rec.unrostered,m=>`<span>${esc(m.user_key)} · ${esc(m.group)} 组 · ${m.kind==='exposure'?'曝光':'激活'} · ${esc(m.source)}</span>`)}
  ${rec.cross_group_total?`<h3>跨组冲突 · ${rec.cross_group_total} 人</h3><div class="scroll roster-list">${rec.cross_group.map(m=>`<span>${esc(m.user_key)} · ${esc(m.detail)}</span>`).join('')}</div>`:''}
  ${rec.staged_events&&rec.staged_events.length?`<h3>暂存队列 · 最近 ${rec.staged_events.length} 条</h3><div class="scroll roster-list">${rec.staged_events.map(e=>`<span>#${e.id} ${esc(e.user_key)} · ${esc(e.group)} · ${e.kind==='exposure'?'曝光':'激活'} · ${e.applied?'已归属':(e.attributed?'已归属':'未归属')}</span>`).join('')}</div>`:''}`;
}

function importForm(exp){
  return `<form id="roster-import" data-exp="${exp.id}"><label>整版名册（每行 用户,组别）<textarea name="roster_text" rows="10" placeholder="用户,组别&#10;RN-0001,A&#10;RN-0002,B" required></textarea></label><label>导入键（重试沿用同一键，不新增成员）<input name="import_key" placeholder="如 1116-v2"></label><label>备注<input name="note" placeholder="来源、人数与差异说明"></label><button class="primary">整版导入</button></form><p class="muted">导入后为“待核对”；核对通过变“可用”；管理员锁定后才生效。重复提交同一导入键或同一内容不会新增成员。</p>`;
}
