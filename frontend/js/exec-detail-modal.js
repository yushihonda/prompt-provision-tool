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
        const tokenStr = execution.tokens_used != null ? (typeof formatCompact === 'function' ? formatCompact(execution.tokens_used) : String(execution.tokens_used)) : '-';
        const copyId = 'skill-out-' + (execution.id || Date.now());

        let html = '<div style="text-align:left;">';

        // --- ヘッダー: サマリーチップ ---
        html += `<div style="display:flex; flex-wrap:wrap; gap:12px; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid rgba(0,0,0,0.06);">`;
        summaryChips.forEach(c => {
            html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:#aaa;">${esc(c.label)}</span><span style="font-size:12px; color:var(--content-text);">${c.valueHtml}</span></div>`;
        });
        html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:#aaa;">実行時間</span><span style="font-size:12px; color:var(--content-text);">${esc(timeStr)}</span></div>`;
        html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:#aaa;">トークン</span><span style="font-size:12px; color:var(--content-text);">${esc(tokenStr)}</span></div>`;
        if (showOutputFormat) {
            html += `<div style="display:flex; align-items:center; gap:6px;"><span style="font-size:11px; color:#aaa;">出力形式</span><span style="font-size:12px; color:var(--content-text);">${esc((execution.output_format || 'txt').toUpperCase())}</span></div>`;
        }
        html += `</div>`;

        // --- スキルノード（ワークフロー風） ---
        html += `<div style="margin:4px 0; border:1px solid rgba(0,0,0,0.06); border-radius:8px; overflow:hidden;">`;
        html += `<div style="padding:10px 14px;">`;
        html += `<div style="padding:8px 10px; background:rgba(0,0,0,0.03); border-radius:6px; border-left:3px solid ${sc(sStatus)};">`;
        html += `<div style="display:flex; align-items:center; gap:10px;">`;
        html += `<span style="color:${sc(sStatus)}; font-size:12px;">${si(sStatus)}</span>`;
        html += `<div style="flex:1; min-width:0;"><div style="font-size:12px; font-weight:bold; color:var(--content-text);">${esc(skillName)}</div><div style="font-size:10px; color:#bbb;">${esc(modelStr)}</div></div>`;
        html += `</div>`;

        // 入力データ（トグル）
        if (inputStr && inputStr !== '-') {
            html += `<details style="margin-top:6px;"><summary style="font-size:10px; color:#aaa; cursor:pointer; user-select:none;">入力データを表示</summary><div style="margin-top:4px; padding:8px; background:rgba(0,0,0,0.04); border-radius:4px; max-height:150px; overflow-y:auto;"><pre style="color:var(--content-text); white-space:pre-wrap; word-wrap:break-word; font-size:11px; line-height:1.5; margin:0;">${inputStr}</pre></div></details>`;
        }

        html += `</div></div></div>`;

        // --- 矢印 ---
        html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(0,0,0,0.08);"></div></div>`;

        // --- 出力（結果統合風） ---
        html += `<div style="background:rgba(40,167,69,0.08); border:1px solid rgba(40,167,69,0.25); border-radius:8px; overflow:hidden;">`;
        html += `<div style="display:flex; align-items:center; gap:10px; padding:12px 16px;">`;
        html += `<div style="width:28px; height:28px; border-radius:50%; background:${sc(sStatus)}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${si(sStatus)}</div>`;
        html += `<div style="flex:1;"><div style="font-size:13px; font-weight:bold; color:var(--content-text);">出力結果</div><div style="font-size:11px; color:#aaa;">${esc(timeStr)} | ${esc(tokenStr)} tokens</div></div>`;
        if (outputRaw) {
            html += `<button type="button" onclick="execDetailModal._copyText(this)" data-copy-target="${copyId}" title="出力をコピー" style="display:flex; align-items:center; justify-content:center; padding:6px; background:none; border:none; cursor:pointer; opacity:0.5; transition:opacity 0.2s;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" style="fill:var(--content-text-secondary, #7a7a7a);"><path d="M16 10c3.469 0 2 4 2 4s4-1.594 4 2v6h-10v-12h4zm.827-2h-6.827v16h14v-8.842c0-2.392-4.011-7.158-7.173-7.158zm-8.827 12h-6v-16h4l2.102 2h3.898l2-2h4v2.145c.656.143 1.327.391 2 .754v-4.899h-3c-1.229 0-2.18-1.084-3-2h-8c-.82.916-1.771 2-3 2h-3v20h8v-2zm2-18c.553 0 1 .448 1 1s-.447 1-1 1-1-.448-1-1 .447-1 1-1zm4 18h6v-1h-6v1zm0-2h6v-1h-6v1zm0-2h6v-1h-6v1z"/></svg></button>`;
        }
        html += `</div>`;

        if (execution.error_message) {
            html += `<div style="padding:0 16px 12px 16px;"><div style="padding:8px 12px; background:rgba(220,53,69,0.15); border-radius:6px; font-size:12px; color:#dc3545;">${esc(execution.error_message)}</div></div>`;
        }
        if (outputRaw) {
            html += `<div style="padding:0 16px 12px 16px;"><div id="${copyId}" style="padding:12px; background:rgba(0,0,0,0.04); border-radius:6px; max-height:400px; overflow-y:auto;"><div style="color:var(--content-text); white-space:pre-wrap; word-wrap:break-word; font-size:12px; line-height:1.6;">${esc(outputRaw)}</div></div></div>`;
        } else if (!execution.error_message) {
            html += `<div style="padding:0 16px 12px 16px;"><div style="color:#bbb; font-size:12px;">出力なし</div></div>`;
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
            // clipboard API 失敗時のフォールバック
            try {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                if (typeof showAlert === 'function') showAlert('クリップボードにコピーしました', 'success');
            } catch (fallbackErr) {
                if (typeof showAlert === 'function') showAlert('コピーに失敗しました', 'error');
            }
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
        const { finalOutput, allStepResults, workflowName, groups, stageMeta, leaderModel } = opts;
        const esc = escapeHtml;
        const sc = (s) => s === 'success' ? '#28a745' : s === 'processing' ? '#7c3aed' : s === 'error' ? '#dc3545' : '#ccc';
        const si = (s) => s === 'success' ? '&#10003;' : s === 'processing' ? '&#9679;' : s === 'error' ? '&#10007;' : '&#9711;';
        const wfName = workflowName || 'ワークフロー';
        const formatProfile = (profile) => ({
            default: 'Leader',
            explore: 'Explore',
            plan: 'Plan',
            implement: 'Implement',
            verification: 'Verification',
        }[profile] || profile || '-');
        const profileColor = (profile) => ({
            default: '#9c27b0', explore: '#2196f3', plan: '#ff9800',
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

        // キューブ下のボタン（クリックでポップアップ表示）
        function cubeIOHtml(step, stepName) {
            if (!step) return '';
            let html = '<div style="display:flex; flex-direction:column; gap:3px; margin-top:6px; align-items:center;">';

            // 入力データ — アクセント色リンク風
            if (step.inputData) {
                try {
                    const inp = typeof step.inputData === 'string' ? JSON.parse(step.inputData) : step.inputData;
                    const filtered = {};
                    for (const [k, v] of Object.entries(inp)) {
                        if (!k.startsWith('_nexmagi_')) filtered[k] = v;
                    }
                    if (Object.keys(filtered).length > 0) {
                        const inputId = 'cube-input-' + (step.stepOrder || Math.random().toString(36).slice(2));
                        html += `<span onclick="execDetailModal._showIOPopup('${esc(stepName)} - 入力', '${inputId}')" style="font-size:9px; color:var(--accent, #7c3aed); cursor:pointer; font-weight:500;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">入力を表示</span>`;
                        html += `<div id="${inputId}" style="display:none;"><pre style="white-space:pre-wrap; word-wrap:break-word; font-size:12px; line-height:1.6; margin:0; color:#2d2d2d;">${esc(JSON.stringify(filtered, null, 2))}</pre></div>`;
                    }
                } catch {}
            }

            // 出力データ — アクセント色リンク風
            const sStatus = step.status || 'pending';
            if (sStatus === 'success' && step.output) {
                const outputId = 'cube-output-' + (step.stepOrder || Math.random().toString(36).slice(2));
                const metaLine = step.model ? `${step.time ? step.time + 'ms' : '-'} | ${typeof formatCompact === 'function' ? formatCompact(step.tokens) : (step.tokens || '-')} tokens` : '';
                html += `<span onclick="execDetailModal._showIOPopup('${esc(stepName)} - 出力', '${outputId}')" style="font-size:9px; color:var(--accent, #7c3aed); cursor:pointer; font-weight:500;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">出力を表示</span>`;
                html += `<div id="${outputId}" style="display:none;">${metaLine ? `<div style="font-size:10px; color:#888; margin-bottom:6px;">${metaLine}</div>` : ''}<div style="white-space:pre-wrap; word-wrap:break-word; font-size:12px; line-height:1.6; color:#2d2d2d;">${esc(step.output)}</div></div>`;
            } else if (sStatus === 'error' && step.errorMessage) {
                const errId = 'cube-err-' + (step.stepOrder || Math.random().toString(36).slice(2));
                html += `<span onclick="execDetailModal._showIOPopup('${esc(stepName)} - エラー', '${errId}')" style="font-size:9px; color:#dc3545; cursor:pointer; font-weight:500;" onmouseover="this.style.textDecoration='underline'" onmouseout="this.style.textDecoration='none'">エラー</span>`;
                html += `<div id="${errId}" style="display:none;"><div style="color:#dc3545; font-size:12px; line-height:1.6;">${esc(step.errorMessage)}</div></div>`;
            }

            html += '</div>';
            return html;
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

        let html = `<div style="padding:10px 14px; background:rgba(0,0,0,0.03); border:1px solid rgba(0,0,0,0.06); border-radius:8px; margin-bottom:10px;">`;
        // 1行目: Stage + Verdict + 進捗
        html += `<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:8px;">`;
        html += `<span style="font-size:11px; color:#999;">Stage</span>`;
        html += `<span style="font-size:12px; font-weight:bold; color:${profileColor(stage)};">${esc(formatProfile(stage))}</span>`;
        if (verdict !== '-') {
            html += `<span style="font-size:11px; color:#999; margin-left:8px;">Verdict</span>`;
            html += `<span style="font-size:12px; font-weight:bold; color:${verdict === 'PASS' ? '#28a745' : verdict === 'FAIL' ? '#dc3545' : verdict === 'PARTIAL' ? '#ffc107' : 'var(--content-text-secondary, #7a7a7a)'};">${esc(verdict)}</span>`;
        }
        html += `<span style="font-size:10px; color:#bbb; margin-left:auto;">${completedCount}/${totalExecs} steps</span>`;
        if (failedStage) {
            html += `<span style="font-size:12px; font-weight:bold; color:#ff8a80;">${esc(formatProfile(failedStage))} failed</span>`;
        }
        html += `</div>`;
        // coordinator summary
        if (latestSummary) {
            html += `<div style="font-size:11px; color:var(--content-text); margin-bottom:6px;">${esc(latestSummary)}</div>`;
        }
        // synthesis events タイムライン
        if (events.length > 0) {
            html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:6px;">`;
            const recentEvents = events.slice(-8);
            for (const ev of recentEvents) {
                const evIcon = { 'workflow_start': '▶', 'group_complete': '◆', 'leader_start': '⟳', 'step_complete': '✓', 'judge_complete': '⚖', 'supervisor_decision': '👁', 'quality_gate_pass': '🔍', 'leader_complete': '★', 'step_error': '✗' }[ev.event_type] || '•';
                const evColor = (ev.event_type || '').includes('error') ? '#dc3545' : '#28a745';
                html += `<span style="font-size:10px; padding:2px 8px; background:rgba(0,0,0,0.04); border-radius:10px; color:var(--content-text-secondary, #7a7a7a); display:inline-flex; align-items:center; gap:3px;"><span style="color:${evColor};">${evIcon}</span>${esc(ev.summary || ev.step_name || '')}</span>`;
            }
            html += `</div>`;
        }
        // key_points
        if (keyPoints.length > 0) {
            html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:4px;">`;
            keyPoints.forEach(kp => { html += `<span style="font-size:10px; padding:2px 8px; background:rgba(76,175,80,0.12); border-radius:10px; color:var(--content-text-secondary, #7a7a7a);">${esc(kp)}</span>`; });
            html += `</div>`;
        }
        // blackboard refs
        if (handoffRefs.length) {
            html += `<div style="display:flex; flex-wrap:wrap; gap:4px;">${handoffRefs.map(ref => `<span style="font-size:10px; padding:2px 8px; background:rgba(33,150,243,0.15); border-radius:10px; color:var(--content-text-secondary, #7a7a7a);">${esc(ref)}</span>`).join('')}</div>`;
        }
        html += `</div>`;

        // --- 3Dキューブ パイプライン (ワークフロー実行画面と同じ見た目) ---
        // 全ステップを収集
        const allSteps = [];
        if (groups && groups.length > 0) {
            groups.forEach(grp => { (grp.skills || []).forEach(sk => allSteps.push(sk)); });
        } else {
            allStepResults.forEach((s, i) => allSteps.push({ skill_name: s.stepName, skill_order: s.stepOrder, workflow_skill_id: s.workflowSkillId, skill_id: s.skillId, agent_profile: s.agentProfile || 'default', model_type: s.model || '' }));
        }

        // SVGアイコン (workflow-execute.js と統一)
        const _tagSvgs = {
            explore: '<svg viewBox="0 0 512 512" style="width:12px;height:12px;fill:currentColor;stroke:currentColor;"><path d="M465.6,24H46.4C20.8,24,0,44.8,0,70.5V441.6c0,25.7,20.8,46.4,46.4,46.4h419.2c25.6,0,46.4-20.7,46.4-46.4V70.5C512,44.8,491.2,24,465.6,24zM464,440H48V120h416V440z"/><path d="M368,348.2H144v52.7h224V348.2zM160,384.8v-20.7h192v20.7H160z"/><circle cx="241.6" cy="225.6" r="30.2" fill="none" stroke-width="20"/><path d="M300.8,268.7l16.7,16.8c7,7,18.4,7,25.4,0c7-7,7-18.5,0-25.5l-17-17L300.8,268.7z"/></svg>',
            plan: '<svg viewBox="0 0 512 512" style="width:12px;height:12px;fill:currentColor;"><path d="M473.2,39.6c-5.2-18.2-19.2-32.1-37.1-37.3C431.1,0.8,426,0,420.4,0H91.6c-30.3,0-55,24.7-55,55v403.4c0.9,29.6,24.7,53.2,54.3,53.6h205.1c10.6,0,20.8-2.2,30.6-6.6c8.2-3.8,15.5-8.9,21.7-15.1L453.8,384.8c6.3-6.3,11.6-13.9,15.1-21.9c4.3-9.4,6.5-19.9,6.5-30.5V55C475.4,49.4,474.7,44.3,473.2,39.6zM303.6,356.5V466.5c-2.5,0.7-5,1-7.6,1H91.4c-5.6-0.1-10.2-4.7-10.3-10.2V55c0-5.8,4.7-10.5,10.5-10.5h328.9c1,0,1.6,0.1,2.9,0.5c3.5,0.9,6.3,3.7,7.4,7.9c0.2,0.5,0.3,1.1,0.3,2.1v277.4c0,2.6-0.3,5.2-1,7.7H320C311,340.1,303.6,347.5,303.6,356.5z"/><rect x="166.5" y="115.3" width="178.9" height="19.9" rx="2.2"/><rect x="166.5" y="192.8" width="178.9" height="19.9" rx="2.2"/><rect x="166.5" y="270.3" width="178.9" height="19.7" rx="2.2"/><rect x="166.5" y="347.9" width="94.5" height="19.9" rx="2.2"/></svg>',
            implement: '<svg viewBox="0 0 512 512" style="width:12px;height:12px;fill:currentColor;"><path d="M362,300.9v-0.2l-33.3,33.3v78.4c0,12.9-10.5,23.4-23.5,23.4H156c-8.6,0-16.9-0.9-25-2.5V353.2c0-8.4-6.8-15.1-15.1-15.1H35.9c-1.7-8.1-2.5-16.4-2.5-25V99.7c0-12.9,10.5-23.4,23.4-23.4h248.4c13,0,23.5,10.5,23.5,23.4v11l-0.1,7.8l0.1-0.1v0.2l31.8-31.8c-5.9-25-28.4-43.8-55.3-43.8H56.8C25.5,42.9,0,68.4,0,99.7v213.5c0,10.7,1.1,21.4,3.2,31.8c12.7,60.8,60.1,108.3,121.1,120.9c10.3,2.1,21,3.3,31.7,3.3h149.2c31.4,0,56.8-25.5,56.8-56.8v-65.5l0.1-46L362,300.9z"/><path d="M508.4,99.9L455,46.5c-2.8-2.8-6.7-4-10.5-3.5c-0.9-0.1-1.9,0-2.9,0.2c-0.4,0.1-0.8,0.2-1.3,0.3c-1,0.3-1.9,0.6-2.9,1.2c-0.4,0.3-0.9,0.5-1.4,0.9c-0.4,0.3-0.9,0.5-1.3,0.9L202.7,282.1l-28.1,90c-1.3,4.2,2.1,8.4,6.3,8.4c0.6,0,1.2-0.1,1.9-0.3l90-28.1L508.8,116.1C513.2,111.7,513,104.5,508.4,99.9z"/></svg>',
            verification: '<svg viewBox="0 0 512 512" style="width:12px;height:12px;fill:currentColor;"><path d="M492.7,41l-5-5.4L250.9,252.3l-39.5-42.3c-13.9-14.8-33.5-23.4-53.8-23.4c-18.7,0-36.6,7-50.3,19.8l-5.3,5L218.2,336c7.9,8.4,19,13.3,30.6,13.3c10.5,0,20.5-3.9,28.2-11L488.1,145.1C518.1,117.7,520.1,71,492.7,41z"/><path d="M454.2,231.7v-0.1l-52,47.6v117.7c0,18.9-15.4,34.2-34.2,34.2H86.2c-18.9,0-34.2-15.3-34.2-34.2V115.1c0-18.8,15.3-34.2,34.2-34.2h281.7c2.9,0,5.7,0.4,8.4,1l40.9-37.4c-14-9.9-31-15.6-49.4-15.6H86.2C38.7,28.9,0,67.6,0,115.1v281.7c0,47.6,38.7,86.2,86.2,86.2h281.7c47.5,0,86.2-38.7,86.2-86.2v-97.6l0.1-67.7L454.2,231.7z"/></svg>',
            default: '<svg viewBox="0 0 512 512" style="width:12px;height:12px;fill:currentColor;"><path d="M484.1,176.9H350.3c-12,0-22.7-7.8-26.4-19.2L282.4,30.4c-8.3-25.6-44.6-25.6-52.9,0l-41.4,127.3c-3.7,11.5-14.4,19.2-26.4,19.2H27.9c-26.9,0-38.1,34.5-16.3,50.3l108.3,78.7c9.7,7.1,13.8,19.6,10.1,31.1L88.6,464.3c-8.3,25.6,21,46.9,42.8,31.1l108.3-78.7c9.7-7.1,22.9-7.1,32.7,0l108.3,78.7c21.8,15.8,51.1-5.5,42.8-31.1L382.1,337c-3.7-11.5,0.4-24,10.1-31.1l108.3-78.7C522.3,211.4,511.1,176.9,484.1,176.9z"/></svg>',
        };
        // キューブ用SVG (中サイズ)
        const _cubeSvgs = {};
        for (const [k, v] of Object.entries(_tagSvgs)) {
            _cubeSvgs[k] = v.replace(/width:12px;height:12px/g, 'width:22px;height:22px');
        }

        // ミニキューブ用CSS変数のオーバーライド
        html += `<div class="wf-pipeline wf-pipeline-mini" style="perspective:600px; padding:20px 8px 30px; justify-content:center; margin:0 auto; --cube-size:50px;">`;

        allSteps.forEach((sk, idx) => {
            const step = stepByWsId[sk.workflow_skill_id] || stepBySkillId[sk.skill_id] || stepByOrder[sk.skill_order];
            const sStatus = step?.status || 'pending';
            const profile = sk.agent_profile || 'default';
            const pColor = profileColor(profile);
            const pLabel = formatProfile(profile);
            // キューブ内は常にロールアイコン（processing時のみローダー）
            const cubeIcon = sStatus === 'processing' ? '<div class="wf-node-loader"><span></span><span></span><span></span></div>' : (_cubeSvgs[profile] || _cubeSvgs.default);

            html += `
                <div class="wf-node" style="padding:4px 8px; width:110px;">
                    <div class="wf-node-step" style="margin-bottom:3px; font-size:9px;"><span class="wf-node-status-indicator status-${sStatus}" style="font-size:9px;">${sStatus === 'success' ? '✓' : sStatus === 'error' ? '✗' : ''}</span>STEP ${idx + 1}</div>
                    <span class="wf-node-profile-tag" style="color:${pColor}; background:${pColor}12; border:1px solid ${pColor}30; margin-bottom:8px; font-size:9px; padding:1px 6px 1px 3px;"><span class="wf-profile-icon" style="color:${pColor};">${_tagSvgs[profile] || _tagSvgs.default}</span>${esc(pLabel)}</span>
                    <div class="wf-node-card-wrap status-${sStatus}" style="--cube-color:${pColor}; --cube-size:50px; width:50px; height:50px;">
                        <div class="wf-node-face-right"></div>
                        <div class="wf-node-face-top"></div>
                        <div class="wf-node-card">
                            <div class="wf-node-icon status-${sStatus}" style="color:${pColor}; width:28px; height:28px; font-size:14px;">${cubeIcon}</div>
                        </div>
                    </div>
                    <div class="wf-node-label" style="margin-top:10px;">
                        <div class="wf-node-name" style="font-size:10px; max-width:100px;">${esc(sk.skill_name || 'Step ' + (idx+1))}</div>
                        <div class="wf-node-model" style="font-size:9px;">${typeof formatModelDisplay === 'function' ? formatModelDisplay(sk.model_type || '', null, sk) : esc(sk.model_type || '')}</div>
                    </div>
                    ${cubeIOHtml(step, sk.skill_name || 'Step ' + (idx+1))}
                </div>
            `;

            if (idx < allSteps.length - 1) {
                const connCls = sStatus === 'success' ? 'active' : '';
                html += `<div class="wf-connector" style="width:24px; margin-top:calc(4px + 12px + 3px + 18px + 8px + 25px);"><div class="wf-connector-line ${connCls}"></div></div>`;
            }
        });

        // Leader (FINAL)
        const finalText = finalOutput || (allStepResults.length > 0 ? allStepResults[allStepResults.length - 1]?.output : '');
        const leaderStatus = finalText ? 'success' : 'pending';
        const leaderColor = '#9c27b0';
        const leaderIcon = leaderStatus === 'processing' ? '<div class="wf-node-loader"><span></span><span></span><span></span></div>' : (_cubeSvgs.default);

        if (allSteps.length > 0) {
            const lastStep = stepByWsId[allSteps[allSteps.length-1]?.workflow_skill_id] || stepByOrder[allSteps[allSteps.length-1]?.skill_order];
            const connCls = (lastStep?.status === 'success') ? 'active' : '';
            html += `<div class="wf-connector" style="width:24px; margin-top:calc(4px + 12px + 3px + 18px + 8px + 25px);"><div class="wf-connector-line ${connCls}"></div></div>`;
        }

        html += `
            <div class="wf-node" style="padding:4px 8px; width:110px;">
                <div class="wf-node-step" style="margin-bottom:3px; font-size:9px;"><span class="wf-node-status-indicator status-${leaderStatus}" style="font-size:9px;">${leaderStatus === 'success' ? '✓' : leaderStatus === 'error' ? '✗' : ''}</span>FINAL</div>
                <span class="wf-node-profile-tag" style="color:${leaderColor}; background:${leaderColor}12; border:1px solid ${leaderColor}30; margin-bottom:8px; font-size:9px; padding:1px 6px 1px 3px;"><span class="wf-profile-icon" style="color:${leaderColor};">${_tagSvgs.default}</span>Leader</span>
                <div class="wf-node-card-wrap status-${leaderStatus}" style="--cube-color:${leaderColor}; --cube-size:50px; width:50px; height:50px;">
                    <div class="wf-node-face-right"></div>
                    <div class="wf-node-face-top"></div>
                    <div class="wf-node-card">
                        <div class="wf-node-icon status-${leaderStatus}" style="color:${leaderColor}; width:28px; height:28px; font-size:14px;">${leaderIcon}</div>
                    </div>
                </div>
                <div class="wf-node-label" style="margin-top:10px;">
                    <div class="wf-node-name" style="font-size:10px; max-width:100px;">結果統合</div>
                    <div class="wf-node-model" style="font-size:9px;">${typeof formatModelDisplay === 'function' ? formatModelDisplay(leaderModel || allSteps[0]?.model_type || '', null, {}) : esc(leaderModel || allSteps[0]?.model_type || '')}</div>
                </div>
            </div>
        `;
        html += `</div>`;

        // --- 出力（切り抜きカード + コピーアイコン円） ---
        const leaderCopyId = 'wf-modal-leader-' + Date.now();
        html += `<div style="margin-top:8px; border-top:1px solid rgba(0,0,0,0.06); padding-top:12px;">`;
        html += `<div class="card-cutout-wrapper">`;
        html += `<div class="card-cutout" style="background:#fff; padding:16px 20px; border-radius:30px;">`;
        html += `<div style="font-size:11px; font-weight:700; color:var(--content-text-muted); text-transform:uppercase; letter-spacing:0.3px; margin-bottom:8px;">出力</div>`;
        if (finalText) {
            html += `<div id="${leaderCopyId}" style="padding:10px; background:rgba(0,0,0,0.02); border-radius:6px; max-height:400px; overflow-y:auto;">
                <div style="color:var(--content-text); white-space:pre-wrap; word-wrap:break-word; font-size:11px; line-height:1.6;">${esc(finalText)}</div>
            </div>`;
        } else {
            html += `<div style="color:var(--content-text-muted); font-size:11px;">出力なし</div>`;
        }
        html += `</div>`;
        if (finalText) {
            html += `<div class="card-cutout-circle" onclick="execDetailModal._copyText(document.getElementById('${leaderCopyId}'))" title="出力をコピー">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            </div>`;
        }
        html += `</div>`;
        html += `</div>`;
        return html;
    }

    async function _copyText(btnOrEl) {
        let el = btnOrEl;
        // ボタンの場合はdata-copy-targetからIDで要素を取得
        if (btnOrEl && btnOrEl.getAttribute && btnOrEl.getAttribute('data-copy-target')) {
            el = document.getElementById(btnOrEl.getAttribute('data-copy-target'));
        }
        const text = el ? (el.textContent || '') : '';
        if (!text || text === '-') {
            if (typeof showAlert === 'function') showAlert('コピーする内容がありません', 'warning');
            return;
        }
        try {
            await navigator.clipboard.writeText(text);
            if (typeof showAlert === 'function') showAlert('クリップボードにコピーしました', 'success');
        } catch (e) {
            try {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                if (typeof showAlert === 'function') showAlert('クリップボードにコピーしました', 'success');
            } catch (fallbackErr) {
                if (typeof showAlert === 'function') showAlert('コピーに失敗しました', 'error');
            }
        }
    }

    function _showIOPopup(title, contentId) {
        const el = document.getElementById(contentId);
        if (!el) return;
        const text = el.textContent || '';
        const content = el.innerHTML;

        // 既存のオーバーレイがあれば削除
        const existing = document.getElementById('io-overlay-modal');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'io-overlay-modal';
        overlay.style.cssText = 'position:fixed; inset:0; z-index:100000; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.3);';

        const modal = document.createElement('div');
        modal.style.cssText = 'background:var(--content-bg, #DFDFD7); border-radius:16px; width:min(90vw,700px); max-height:80vh; display:flex; flex-direction:column; box-shadow:0 8px 32px rgba(0,0,0,0.15); border:1px solid rgba(0,0,0,0.08); overflow:hidden;';

        // タイトル
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'padding:18px 24px 0; font-size:18px; font-weight:600; color:var(--content-text); text-align:center;';
        titleEl.textContent = title;

        // コンテンツ — showNodeOutputPopup と同じデザイン
        const body = document.createElement('div');
        body.style.cssText = 'padding:16px 24px; overflow-y:auto; flex:1;';
        body.innerHTML = `<div style="text-align:left; max-height:60vh; overflow-y:auto; padding:16px; background:#f8f8f6; border-radius:10px; font-size:12px; line-height:1.6; white-space:pre-wrap; word-wrap:break-word; color:#2d2d2d;">${content}</div>`;

        // ボタン — showNodeOutputPopup と同じレイアウト
        const footer = document.createElement('div');
        footer.style.cssText = 'padding:12px 24px 18px; display:flex; justify-content:center; gap:10px;';
        footer.innerHTML = `
            <button id="io-modal-copy-btn" style="padding:8px 24px; font-size:14px; font-weight:600; background:#6c757d; border:none; border-radius:8px; cursor:pointer; color:#fff; min-width:80px;">コピー</button>
            <button id="io-modal-close-btn" style="padding:8px 24px; font-size:14px; font-weight:600; background:#7c3aed; border:none; border-radius:8px; cursor:pointer; color:#fff; min-width:80px;">閉じる</button>
        `;

        modal.appendChild(titleEl);
        modal.appendChild(body);
        modal.appendChild(footer);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // 閉じるボタン
        document.getElementById('io-modal-close-btn').onclick = () => overlay.remove();

        // オーバーレイクリックで閉じる
        overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

        // コピーボタン
        document.getElementById('io-modal-copy-btn').onclick = () => {
            navigator.clipboard.writeText(text).then(() => {
                if (typeof showAlert === 'function') showAlert('コピーしました', 'success');
            }).catch(() => {});
        };

        // Escで閉じる
        const escHandler = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); } };
        document.addEventListener('keydown', escHandler);
    }

    /**
     * ワークフロー実行詳細ポップアップを表示（共通）
     * ユーザー側・管理画面の両方から呼べる。
     *
     * @param {object} opts
     * @param {string} opts.workflowName
     * @param {Array}  opts.allStepResults
     * @param {object} opts.leaderExec - リーダーExecution（null可）
     * @param {Array}  opts.groups - ワークフローグループ構造（null可）
     * @param {object} opts.stageMeta - coordinatorView等
     * @param {string} [opts.leaderModel] - リーダーモデル名
     * @param {number} [opts.stepCount] - ステップ数
     * @param {number} [opts.totalTime] - 合計実行時間(ms)
     * @param {number} [opts.totalTokens] - 合計トークン数
     * @param {string} [opts.extraInfo] - 追加情報HTML（管理画面のAccount ID等）
     */
    async function showWorkflowDetailPopup(opts) {
        const {
            workflowName, allStepResults, leaderExec, groups,
            stageMeta, leaderModel,
            stepCount, totalTime, totalTokens, extraInfo
        } = opts;
        const esc = escapeHtml;
        const finalOutput = leaderExec?.output_data || '';
        const resultHtml = buildWorkflowFlowHTML({
            finalOutput, allStepResults, workflowName, groups,
            leaderModel: leaderModel || leaderExec?.model_used || '',
            stageMeta: stageMeta || {},
        });

        const modelHtml = typeof formatModelDisplay === 'function'
            ? formatModelDisplay(leaderExec?.model_used || '', null, {})
            : esc(leaderExec?.model_used || '-');

        const detailHTML = `
            <div style="text-align: left;">
                <div style="margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(0,0,0,0.08);">
                    <div style="color: var(--content-text); font-weight: 700; font-size: 18px; margin-bottom: 8px;">${esc(workflowName)}</div>
                    <div style="display: flex; gap: 16px; color: var(--content-text-muted); font-size: 12px; align-items: center; flex-wrap: wrap;">
                        ${extraInfo || ''}
                        <span style="color: var(--accent); font-weight: 600;">${stepCount || allStepResults.length} ステップ</span>
                        <span>${modelHtml}</span>
                        <span>合計 ${totalTime || 0}ms</span>
                        <span>${typeof formatCompact === 'function' ? formatCompact(totalTokens) : (totalTokens || 0)} tokens</span>
                    </div>
                </div>
                ${resultHtml}
            </div>
        `;

        await Swal.fire({
            title: 'ワークフロー実行詳細',
            html: detailHTML,
            width: '880px',
            showConfirmButton: false,
            customClass: { popup: 'swal-wide swal-exec-detail' },
        });
    }

    global.execDetailModal = { escapeHtml, buildHtml, execDetailCopyOutput, buildWorkflowFlowHTML, _copyText, _showIOPopup, showWorkflowDetailPopup };
    global.execDetailCopyOutput = execDetailCopyOutput;
})(typeof window !== 'undefined' ? window : globalThis);
