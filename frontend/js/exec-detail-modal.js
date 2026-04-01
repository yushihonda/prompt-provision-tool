/**
 * 実行詳細 SweetAlert 用の共通 HTML（管理 / ユーザー共通）
 */
(function (global) {
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function statusClass(status) {
        const m = {
            success: 'exec-detail-status--success',
            error: 'exec-detail-status--error',
            cancelled: 'exec-detail-status--cancelled',
            pending: 'exec-detail-status--pending',
            processing: 'exec-detail-status--processing',
        };
        return m[status] || 'exec-detail-status--muted';
    }

    function safeFormatJson(formatJSON, inputData) {
        try {
            const r = formatJSON(inputData);
            if (typeof r === 'string') return r;
            if (r != null && typeof r === 'object') return JSON.stringify(r, null, 2);
            return String(r != null ? r : '');
        } catch {
            return String(inputData != null ? inputData : '');
        }
    }

    /**
     * @param {object} execution API の execution オブジェクト
     * @param {object} opts
     * @param {function} opts.formatJSON
     * @param {Array<{label:string,valueHtml:string}>} [opts.summaryChips] 先頭に並べるチップ（valueHtml はモデル行など HTML 可）
     * @param {string} [opts.afterSummaryHtml] サマリー直下に挿入（ワークフロー名ブロック等）
     * @param {boolean} [opts.showOutputFormat]
     * @param {string|null} [opts.outputCopyId] 付与時は出力 pre に id とコピーボタン
     */
    function buildHtml(execution, opts) {
        const {
            formatJSON,
            summaryChips = [],
            afterSummaryHtml = '',
            showOutputFormat = false,
            outputCopyId = null,
        } = opts;

        const esc = escapeHtml;
        const sc = (s) => s === 'success' ? '#28a745' : s === 'processing' ? '#7c3aed' : s === 'error' ? '#dc3545' : 'rgba(255,255,255,0.2)';
        const si = (s) => s === 'success' ? '&#10003;' : s === 'processing' ? '&#9679;' : s === 'error' ? '&#10007;' : '&#9711;';

        const inputStr = esc(safeFormatJson(formatJSON, execution.input_data));
        const outputRaw = execution.output_data == null || execution.output_data === '' ? '' : String(execution.output_data);
        const sStatus = execution.status || 'pending';
        const skillName = execution.skill_name || '-';
        const modelStr = execution.model_used || '-';
        const timeStr = execution.execution_time != null ? `${execution.execution_time}ms` : '-';
        const tokenStr = execution.tokens_used != null ? String(execution.tokens_used) : '-';
        const copyId = 'skill-out-' + (execution.id || Date.now());

        let html = '<div style="text-align:left;">';

        // --- ヘッダー: サマリーチップ ---
        html += `<div style="display:flex; flex-wrap:wrap; gap:12px; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid rgba(255,255,255,0.1);">`;
        summaryChips.forEach(c => {
            html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:rgba(255,255,255,0.5);">${esc(c.label)}</span><span style="font-size:12px; color:rgba(255,255,255,0.9);">${c.valueHtml}</span></div>`;
        });
        html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:rgba(255,255,255,0.5);">実行時間</span><span style="font-size:12px; color:rgba(255,255,255,0.9);">${esc(timeStr)}</span></div>`;
        html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:rgba(255,255,255,0.5);">トークン</span><span style="font-size:12px; color:rgba(255,255,255,0.9);">${esc(tokenStr)}</span></div>`;
        if (showOutputFormat) {
            html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:rgba(255,255,255,0.5);">出力形式</span><span style="font-size:12px; color:rgba(255,255,255,0.9);">${esc((execution.output_format || 'txt').toUpperCase())}</span></div>`;
        }
        html += `</div>`;

        // --- スキルノード（ワークフロー風） ---
        html += `<div style="margin:4px 0; border:1px solid rgba(255,255,255,0.1); border-radius:8px; overflow:hidden;">`;
        html += `<div style="padding:10px 14px;">`;
        html += `<div style="padding:8px 10px; background:rgba(0,0,0,0.15); border-radius:6px; border-left:3px solid ${sc(sStatus)};">`;
        html += `<div style="display:flex; align-items:center; gap:10px;">`;
        html += `<span style="color:${sc(sStatus)}; font-size:12px;">${si(sStatus)}</span>`;
        html += `<div style="flex:1; min-width:0;"><div style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.9);">${esc(skillName)}</div><div style="font-size:10px; color:rgba(255,255,255,0.4);">${esc(modelStr)}</div></div>`;
        html += `</div>`;

        // 入力データ（トグル）
        if (inputStr && inputStr !== '-') {
            html += `<details style="margin-top:6px;"><summary style="font-size:10px; color:rgba(255,255,255,0.5); cursor:pointer; user-select:none;">入力データを表示</summary><div style="margin-top:4px; padding:8px; background:rgba(0,0,0,0.3); border-radius:4px; max-height:150px; overflow-y:auto;"><pre style="color:rgba(255,255,255,0.8); white-space:pre-wrap; word-wrap:break-word; font-size:11px; line-height:1.5; margin:0;">${inputStr}</pre></div></details>`;
        }

        html += `</div></div></div>`;

        // --- 矢印 ---
        html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;

        // --- 出力（結果統合風） ---
        html += `<div style="background:rgba(40,167,69,0.08); border:1px solid rgba(40,167,69,0.25); border-radius:8px; overflow:hidden;">`;
        html += `<div style="display:flex; align-items:center; gap:10px; padding:12px 16px;">`;
        html += `<div style="width:28px; height:28px; border-radius:50%; background:${sc(sStatus)}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${si(sStatus)}</div>`;
        html += `<div style="flex:1;"><div style="font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9);">出力結果</div><div style="font-size:11px; color:rgba(255,255,255,0.5);">${esc(timeStr)} | ${esc(tokenStr)} tokens</div></div>`;
        if (outputRaw) {
            html += `<button type="button" onclick="execDetailModal._copyText(this)" data-copy-target="${copyId}" title="出力をコピー" style="display:flex; align-items:center; justify-content:center; padding:6px; background:none; border:none; cursor:pointer; opacity:0.5; transition:opacity 0.2s;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" style="fill:rgba(255,255,255,0.7);"><path d="M16 10c3.469 0 2 4 2 4s4-1.594 4 2v6h-10v-12h4zm.827-2h-6.827v16h14v-8.842c0-2.392-4.011-7.158-7.173-7.158zm-8.827 12h-6v-16h4l2.102 2h3.898l2-2h4v2.145c.656.143 1.327.391 2 .754v-4.899h-3c-1.229 0-2.18-1.084-3-2h-8c-.82.916-1.771 2-3 2h-3v20h8v-2zm2-18c.553 0 1 .448 1 1s-.447 1-1 1-1-.448-1-1 .447-1 1-1zm4 18h6v-1h-6v1zm0-2h6v-1h-6v1zm0-2h6v-1h-6v1z"/></svg></button>`;
        }
        html += `</div>`;

        if (execution.error_message) {
            html += `<div style="padding:0 16px 12px 16px;"><div style="padding:8px 12px; background:rgba(220,53,69,0.15); border-radius:6px; font-size:12px; color:#dc3545;">${esc(execution.error_message)}</div></div>`;
        }
        if (outputRaw) {
            html += `<div style="padding:0 16px 12px 16px;"><div id="${copyId}" style="padding:12px; background:rgba(0,0,0,0.3); border-radius:6px; max-height:400px; overflow-y:auto;"><div style="color:rgba(255,255,255,0.9); white-space:pre-wrap; word-wrap:break-word; font-size:12px; line-height:1.6;">${esc(outputRaw)}</div></div></div>`;
        } else if (!execution.error_message) {
            html += `<div style="padding:0 16px 12px 16px;"><div style="color:rgba(255,255,255,0.4); font-size:12px;">出力なし</div></div>`;
        }
        html += `</div>`;

        html += '</div>';
        return html;
    }

    async function execDetailCopyOutput(id, btn) {
        const el = document.getElementById('exec-detail-out-' + id);
        if (!el) return;
        const text = el.textContent || '';
        if (!text || text === '-') {
            if (typeof showAlert === 'function') showAlert('コピーする内容がありません', 'warning');
            return;
        }
        try {
            await navigator.clipboard.writeText(text);
            if (typeof showAlert === 'function') showAlert('クリップボードにコピーしました', 'success');
            if (btn) {
                const t = btn.textContent;
                btn.textContent = '済';
                setTimeout(() => {
                    btn.textContent = t;
                }, 1000);
            }
        } catch (e) {
            if (typeof showAlert === 'function') showAlert('コピーに失敗しました', 'error');
        }
    }

    /**
     * ワークフロー実行結果のフロービューHTML（ポップアップ・パネル共通）
     *
     * @param {object} opts
     * @param {string}  opts.finalOutput       リーダー（結果統合）出力
     * @param {Array}   opts.allStepResults    [{stepOrder,stepName,status,output,errorMessage,model,time,tokens,workflowSkillId}]
     * @param {string}  opts.workflowName
     * @param {Array}   [opts.groups]          ワークフローのグループ構造（あれば並列表示対応）
     */
    function buildWorkflowFlowHTML(opts) {
        const { finalOutput, allStepResults, workflowName, groups, stageMeta } = opts;
        const esc = escapeHtml;
        const sc = (s) => s === 'success' ? '#28a745' : s === 'processing' ? '#7c3aed' : s === 'error' ? '#dc3545' : 'rgba(255,255,255,0.2)';
        const si = (s) => s === 'success' ? '&#10003;' : s === 'processing' ? '&#9679;' : s === 'error' ? '&#10007;' : '&#9711;';
        const wfName = workflowName || 'ワークフロー';
        const formatProfile = (profile) => ({
            default: 'Default',
            explore: 'Explore',
            plan: 'Plan',
            implement: 'Implement',
            verification: 'Verification',
        }[profile] || profile || '-');
        const profileColor = (profile) => ({
            default: '#9e9e9e', explore: '#2196f3', plan: '#ff9800',
            implement: '#4caf50', verification: '#e91e63',
        }[(profile || '').toLowerCase()] || '#9e9e9e');

        // stepOrder → stepResult のマップ
        const stepByOrder = {};
        const stepByWsId = {};
        const stepBySkillId = {};
        allStepResults.forEach(s => {
            if (s.stepOrder) stepByOrder[s.stepOrder] = s;
            if (s.workflowSkillId) stepByWsId[s.workflowSkillId] = s;
            if (s.skillId) stepBySkillId[s.skillId] = s;
        });

        // スキルノードの出力+入力HTML（details トグル）
        function skillBody(step) {
            if (!step) return '';
            const sStatus = step.status || 'pending';
            let bodyHtml = '';
            if (sStatus === 'success' && step.output) {
                bodyHtml = `<div style="padding:8px; background:rgba(0,0,0,0.3); border-radius:4px; max-height:150px; overflow-y:auto;"><div style="color:rgba(255,255,255,0.8); white-space:pre-wrap; word-wrap:break-word; font-size:11px; line-height:1.5;">${esc(step.output)}</div></div>`;
            } else if (sStatus === 'error' && step.errorMessage) {
                bodyHtml = `<div style="padding:6px 8px; background:rgba(220,53,69,0.15); border-radius:4px; font-size:11px; color:#dc3545;">${esc(step.errorMessage)}</div>`;
            }
            // profile 解決元バッジ
            let profileSourceHtml = '';
            if (step.inputData) {
                try {
                    const metaInp = typeof step.inputData === 'string' ? JSON.parse(step.inputData) : step.inputData;
                    const src = metaInp?._ppt_profile_source;
                    if (src && src !== 'fallback') {
                        const srcLabel = { skill_default: 'inherited', workflow_override: 'override' }[src] || src;
                        profileSourceHtml = `<span style="font-size:9px; padding:1px 6px; background:rgba(255,255,255,0.06); border-radius:8px; color:rgba(255,255,255,0.4); margin-left:4px;">${esc(srcLabel)}</span>`;
                    }
                } catch {}
            }
            // 入力表示（_ppt_ メタを除外）
            let inputHtml = '';
            if (step.inputData) {
                try {
                    const inp = typeof step.inputData === 'string' ? JSON.parse(step.inputData) : step.inputData;
                    const filtered = {};
                    for (const [k, v] of Object.entries(inp)) {
                        if (!k.startsWith('_ppt_')) filtered[k] = v;
                    }
                    if (Object.keys(filtered).length > 0) {
                        inputHtml = `<details style="margin-top:4px;"><summary style="font-size:10px; color:rgba(255,255,255,0.4); cursor:pointer; user-select:none;">入力を表示</summary><div style="margin-top:4px; padding:6px; background:rgba(0,0,0,0.2); border-radius:4px; max-height:100px; overflow-y:auto;"><pre style="color:rgba(255,255,255,0.6); white-space:pre-wrap; word-wrap:break-word; font-size:10px; line-height:1.4; margin:0;">${esc(JSON.stringify(filtered, null, 2))}</pre></div></details>`;
                    }
                } catch {}
            }
            // profileSource → 入力 → 出力 の順で表示
            return `${profileSourceHtml}${inputHtml}<details style="margin-top:6px;"><summary style="font-size:10px; color:rgba(255,255,255,0.5); cursor:pointer; user-select:none;">▶ 出力を表示</summary><div style="margin-top:4px;">${step.model ? `<div style="font-size:10px; color:#888; margin-bottom:4px;">${step.time ? step.time + 'ms' : '-'} | ${step.tokens || '-'} tokens</div>` : ''}${bodyHtml || '<div style="color:rgba(255,255,255,0.4); font-size:11px;">出力なし</div>'}</div></details>`;
        }

        const cv = stageMeta?.coordinatorView;
        const events = stageMeta?.synthesisEvents || [];
        const stage = stageMeta?.currentStage || '-';
        const verdict = stageMeta?.finalVerdict || '-';
        const handoffSummary = stageMeta?.handoffSummary?.summary || '';
        const keyPoints = stageMeta?.handoffSummary?.key_points || [];
        const handoffRefs = Array.isArray(stageMeta?.handoffSummary?.blackboard_refs) ? stageMeta.handoffSummary.blackboard_refs : [];
        const failedStep = allStepResults.find(step => step.status === 'error');
        const failedStage = failedStep?.agentProfile || null;
        const completedCount = cv?.completed_count || allStepResults.filter(s => s.status === 'success').length;
        const totalExecs = cv?.total_executions || allStepResults.length;
        const latestSummary = cv?.latest_summary || '';

        let html = `<div style="padding:10px 14px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); border-radius:8px; margin-bottom:10px;">`;
        // 1行目: Stage + Verdict + 進捗
        html += `<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:8px;">`;
        html += `<span style="font-size:11px; color:rgba(255,255,255,0.55);">Stage</span>`;
        html += `<span style="font-size:12px; font-weight:bold; color:${profileColor(stage)};">${esc(formatProfile(stage))}</span>`;
        if (verdict !== '-') {
            html += `<span style="font-size:11px; color:rgba(255,255,255,0.55); margin-left:8px;">Verdict</span>`;
            html += `<span style="font-size:12px; font-weight:bold; color:${verdict === 'PASS' ? '#28a745' : verdict === 'FAIL' ? '#dc3545' : verdict === 'PARTIAL' ? '#ffc107' : 'rgba(255,255,255,0.7)'};">${esc(verdict)}</span>`;
        }
        html += `<span style="font-size:10px; color:rgba(255,255,255,0.4); margin-left:auto;">${completedCount}/${totalExecs} steps</span>`;
        if (failedStage) {
            html += `<span style="font-size:12px; font-weight:bold; color:#ff8a80;">${esc(formatProfile(failedStage))} failed</span>`;
        }
        html += `</div>`;
        // coordinator summary
        if (latestSummary) {
            html += `<div style="font-size:11px; color:rgba(255,255,255,0.8); margin-bottom:6px;">${esc(latestSummary)}</div>`;
        }
        // synthesis events タイムライン
        if (events.length > 0) {
            html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:6px;">`;
            const recentEvents = events.slice(-8);
            for (const ev of recentEvents) {
                const evIcon = { 'workflow_start': '▶', 'group_complete': '◆', 'leader_start': '⟳', 'step_complete': '✓', 'judge_complete': '⚖', 'supervisor_decision': '👁', 'quality_gate_pass': '🔍', 'leader_complete': '★', 'step_error': '✗' }[ev.event_type] || '•';
                const evColor = (ev.event_type || '').includes('error') ? '#dc3545' : '#28a745';
                html += `<span style="font-size:10px; padding:2px 8px; background:rgba(255,255,255,0.06); border-radius:10px; color:rgba(255,255,255,0.65); display:inline-flex; align-items:center; gap:3px;"><span style="color:${evColor};">${evIcon}</span>${esc(ev.summary || ev.step_name || '')}</span>`;
            }
            html += `</div>`;
        }
        // key_points
        if (keyPoints.length > 0) {
            html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:4px;">`;
            keyPoints.forEach(kp => { html += `<span style="font-size:10px; padding:2px 8px; background:rgba(76,175,80,0.12); border-radius:10px; color:rgba(255,255,255,0.7);">${esc(kp)}</span>`; });
            html += `</div>`;
        }
        // blackboard refs
        if (handoffRefs.length) {
            html += `<div style="display:flex; flex-wrap:wrap; gap:4px;">${handoffRefs.map(ref => `<span style="font-size:10px; padding:2px 8px; background:rgba(33,150,243,0.15); border-radius:10px; color:rgba(255,255,255,0.7);">${esc(ref)}</span>`).join('')}</div>`;
        }
        html += `</div>`;

        // --- 親スキル: タスク振り分け ---
        html += `<div style="display:flex; align-items:center; gap:10px; padding:12px 16px; background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-bottom:4px;">
            <div style="width:28px; height:28px; border-radius:50%; background:#28a745; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">&#10003;</div>
            <div><div style="font-size:13px; font-weight:bold; color:#ce93d8;">親スキル: タスク振り分け</div><div style="font-size:11px; color:rgba(255,255,255,0.5);">${esc(wfName)}</div></div>
        </div>`;
        html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;

        // --- グループ構造がある場合 ---
        if (groups && groups.length > 0) {
            groups.forEach((grp, gi) => {
                const isParallel = grp.execution_type === 'parallel';
                const skills = grp.skills || [];
                const gColor = isParallel ? '#2196f3' : '#ff9800';
                const gLabel = isParallel ? '並列' : '直列';
                const gName = grp.group_name || ('Group ' + (gi + 1));

                html += `<div style="margin:4px 0; border:1px solid ${gColor}33; border-radius:8px; overflow:hidden;">`;
                html += `<div style="padding:8px 14px; background:${gColor}15; display:flex; align-items:center; gap:8px;">
                    <span style="font-size:10px; font-weight:bold; color:${gColor}; background:${gColor}22; padding:2px 8px; border-radius:10px;">${gLabel}</span>
                    <span style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.8);">${esc(gName)}</span>
                </div>`;

                if (isParallel && skills.length > 1) {
                    html += `<div style="display:flex; gap:6px; padding:10px 14px;">`;
                    skills.forEach(sk => {
                        const step = stepByWsId[sk.workflow_skill_id] || stepBySkillId[sk.skill_id] || stepByOrder[sk.skill_order];
                        const sStatus = step?.status || 'pending';
                        html += `<div style="flex:1; padding:10px; background:rgba(0,0,0,0.2); border-radius:6px; border-left:3px solid ${sc(sStatus)}; min-width:0;">
                            <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                                <span style="color:${sc(sStatus)}; font-size:12px;">${si(sStatus)}</span>
                                <span style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.9); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(sk.skill_name || sk.skill_display_name || '?')}</span>
                            </div>
                            <div style="font-size:10px; color:rgba(255,255,255,0.4);">${esc(sk.model_type || '')}</div>
                            <div style="margin-top:4px;"><span style="font-size:10px; padding:2px 8px; background:${profileColor(sk.agent_profile || step?.agentProfile || 'default')}22; border-radius:10px; color:${profileColor(sk.agent_profile || step?.agentProfile || 'default')};">${esc(formatProfile(sk.agent_profile || step?.agentProfile || 'default'))}</span></div>
                            ${skillBody(step)}
                        </div>`;
                    });
                    html += `</div>`;
                } else {
                    html += `<div style="padding:8px 14px;">`;
                    skills.forEach((sk, si_idx) => {
                        const step = stepByWsId[sk.workflow_skill_id] || stepBySkillId[sk.skill_id] || stepByOrder[sk.skill_order];
                        const sStatus = step?.status || 'pending';
                        html += `<div style="padding:8px 10px; background:rgba(0,0,0,0.15); border-radius:6px; border-left:3px solid ${sc(sStatus)}; ${si_idx > 0 ? 'margin-top:6px;' : ''}">
                            <div style="display:flex; align-items:center; gap:10px;">
                                <span style="color:${sc(sStatus)}; font-size:12px;">${si(sStatus)}</span>
                                <div style="flex:1; min-width:0;">
                                    <div style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.9);">${esc(sk.skill_name || sk.skill_display_name || '?')}</div>
                                    <div style="font-size:10px; color:rgba(255,255,255,0.4);">${esc(sk.model_type || '')}</div>
                                    <div style="margin-top:4px;"><span style="font-size:10px; padding:2px 8px; background:${profileColor(sk.agent_profile || step?.agentProfile || 'default')}22; border-radius:10px; color:${profileColor(sk.agent_profile || step?.agentProfile || 'default')};">${esc(formatProfile(sk.agent_profile || step?.agentProfile || 'default'))}</span></div>
                                </div>
                            </div>
                            ${skillBody(step)}
                        </div>`;
                        if (si_idx < skills.length - 1 && !isParallel) {
                            html += `<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(255,255,255,0.1);"></div></div>`;
                        }
                    });
                    html += `</div>`;
                }
                html += `</div>`;
                if (gi < groups.length - 1) {
                    html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;
                }
            });
        } else {
            // グループ情報なし: フラットリスト
            html += `<div style="margin:4px 0; border:1px solid rgba(255,255,255,0.1); border-radius:8px; overflow:hidden;"><div style="padding:8px 14px;">`;
            allStepResults.forEach((step, i) => {
                const sStatus = step.status || 'pending';
                const statusColor = sc(sStatus);
                html += `<div style="padding:8px 10px; background:rgba(0,0,0,0.15); border-radius:6px; border-left:3px solid ${statusColor}; ${i > 0 ? 'margin-top:6px;' : ''}">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span style="color:${statusColor}; font-size:12px;">${si(sStatus)}</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.9);">${esc(step.stepName || 'Step ' + step.stepOrder)}</div>
                            ${step.model ? `<div style="font-size:10px; color:rgba(255,255,255,0.4);">${esc(step.model)}</div>` : ''}
                        </div>
                    </div>
                    ${skillBody(step)}
                </div>`;
                if (i < allStepResults.length - 1) {
                    html += `<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(255,255,255,0.1);"></div></div>`;
                }
            });
            html += `</div></div>`;
        }

        // --- 矢印 ---
        html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;

        // --- 親スキル: 結果統合 ---
        const finalText = finalOutput || (allStepResults.length > 0 ? allStepResults[allStepResults.length - 1]?.output : '');
        const leaderStatus = finalText ? 'success' : 'pending';
        html += `<div style="background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-top:4px; overflow:hidden;">`;
        html += `<div style="display:flex; align-items:center; gap:10px; padding:12px 16px;">`;
        html += `<div style="width:28px; height:28px; border-radius:50%; background:${sc(leaderStatus)}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${si(leaderStatus)}</div>`;
        html += `<div style="flex:1;"><div style="font-size:13px; font-weight:bold; color:#ce93d8;">親スキル: 結果統合</div><div style="font-size:11px; color:rgba(255,255,255,0.5);">全結果を統合して最終出力を生成</div></div>`;
        const leaderCopyId = 'wf-modal-leader-' + Date.now();
        if (finalText) {
            html += `<button type="button" onclick="execDetailModal._copyText(this)" data-copy-target="${leaderCopyId}" title="出力をコピー" style="display:flex; align-items:center; justify-content:center; padding:6px; background:none; border:none; cursor:pointer; opacity:0.5; transition:opacity 0.2s;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" style="fill:rgba(255,255,255,0.7);"><path d="M16 10c3.469 0 2 4 2 4s4-1.594 4 2v6h-10v-12h4zm.827-2h-6.827v16h14v-8.842c0-2.392-4.011-7.158-7.173-7.158zm-8.827 12h-6v-16h4l2.102 2h3.898l2-2h4v2.145c.656.143 1.327.391 2 .754v-4.899h-3c-1.229 0-2.18-1.084-3-2h-8c-.82.916-1.771 2-3 2h-3v20h8v-2zm2-18c.553 0 1 .448 1 1s-.447 1-1 1-1-.448-1-1 .447-1 1-1zm4 18h6v-1h-6v1zm0-2h6v-1h-6v1zm0-2h6v-1h-6v1z"/></svg></button>`;
        }
        html += `</div>`;
        if (finalText) {
            html += `<div style="padding:0 16px 12px 16px;"><div id="${leaderCopyId}" style="padding:12px; background:rgba(0,0,0,0.3); border-radius:6px; max-height:400px; overflow-y:auto;"><div style="color:rgba(255,255,255,0.9); white-space:pre-wrap; word-wrap:break-word; font-size:12px; line-height:1.6;">${esc(finalText)}</div></div></div>`;
        }
        html += `</div>`;
        return html;
    }

    async function _copyText(btn) {
        const targetId = btn.getAttribute('data-copy-target');
        const el = targetId ? document.getElementById(targetId) : null;
        const text = el ? (el.textContent || '') : '';
        if (!text || text === '-') {
            if (typeof showAlert === 'function') showAlert('コピーする内容がありません', 'warning');
            return;
        }
        try {
            await navigator.clipboard.writeText(text);
            if (typeof showAlert === 'function') showAlert('クリップボードにコピーしました', 'success');
        } catch (e) {
            if (typeof showAlert === 'function') showAlert('コピーに失敗しました', 'error');
        }
    }

    global.execDetailModal = { escapeHtml, buildHtml, execDetailCopyOutput, buildWorkflowFlowHTML, _copyText };
    global.execDetailCopyOutput = execDetailCopyOutput;
})(typeof window !== 'undefined' ? window : globalThis);
