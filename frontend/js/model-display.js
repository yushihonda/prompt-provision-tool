/**
 * モデル表示用の共通ユーティリティ
 *
 * 全画面（admin/user）で統一されたモデルバッジ表示を提供する。
 * 使用例: formatModelDisplay('gpt-5.2-pro', execution, skillDetail)
 */

function formatModelDisplay(modelType, execution, skillDetail) {
    if (!modelType) return '-';

    let modelDisplay = modelType;
    let isDeepThinkModel = false;
    let isThinkingModel = false;

    // Deep Thinkモデルの場合はサフィックスを削除
    if (modelDisplay.includes('deep-think')) {
        modelDisplay = modelDisplay.replace('-deep-think', '');
        isDeepThinkModel = true;
    }

    // Thinkingモデルの場合はサフィックスを削除
    if (modelDisplay.includes('thinking')) {
        modelDisplay = modelDisplay.replace('-thinking', '');
        isThinkingModel = true;
    }

    // Proモデルの場合は「-pro」を削除してProバッジを追加
    const isProModel = modelType.includes('-pro') || modelType.endsWith('-pro');
    if (isProModel) {
        modelDisplay = modelDisplay.replace(/-pro(?=-|$)/g, '');
        modelDisplay += '<span class="pro-badge">Pro</span>';
    }

    // 「-preview」を削除
    modelDisplay = modelDisplay.replace(/-preview/g, '');

    // Deep Thinkバッジを追加
    let isDeepThinkEnabled = isDeepThinkModel;
    if (!isDeepThinkEnabled && execution) {
        if (execution.enable_deep_think !== undefined && execution.enable_deep_think !== null) {
            isDeepThinkEnabled = execution.enable_deep_think === true || execution.enable_deep_think === 1 || execution.enable_deep_think === 'true';
        } else if (skillDetail) {
            isDeepThinkEnabled = skillDetail.enable_deep_think === true || skillDetail.enable_deep_think === 1 || skillDetail.enable_deep_think === 'true';
        }
    } else if (!isDeepThinkEnabled && skillDetail) {
        isDeepThinkEnabled = skillDetail.enable_deep_think === true || skillDetail.enable_deep_think === 1 || skillDetail.enable_deep_think === 'true';
    }

    if (isDeepThinkEnabled && modelType.startsWith('gemini-')) {
        modelDisplay += '<span class="deep-think-badge">Deep Think</span>';
    }

    // Thinkingバッジを追加
    if (isThinkingModel || modelType === 'gpt-5.1-thinking') {
        modelDisplay += '<span class="thinking-badge">Thinking</span>';
    }

    // NEWバッジを追加
    const NEW_MODELS = ['gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-pro', 'gpt-5.4-thinking', 'gemini-3.1-pro-preview', 'gemini-3.1-pro-preview-deep-think'];
    if (NEW_MODELS.includes(modelType)) {
        modelDisplay += '<span class="new-badge">NEW</span>';
    }

    return modelDisplay;
}
