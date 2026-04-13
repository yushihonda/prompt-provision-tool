/**
 * ミニ3Dキューブ HTML生成（共通 — ユーザー・管理画面で使用）
 * user-common.js から分離した共通関数
 */
function renderMiniCube(profile, opts) {
    opts = opts || {};
    var size = opts.size || 24;
    var half = size / 2;
    var colors = {
        default: '#9c27b0',
        explore: '#2196f3',
        plan: '#ff9800',
        implement: '#4caf50',
        verification: '#e91e63',
        design_builder: '#00acc1'
    };
    var labels = {
        default: 'Leader',
        explore: 'Explore',
        plan: 'Plan',
        implement: 'Implement',
        verification: 'Verification',
        design_builder: 'Design Builder'
    };
    var icons = {
        explore: '<svg viewBox="0 0 512 512" style="width:__S__;height:__S__;fill:currentColor;stroke:currentColor;"><path d="M465.6,24H46.4C20.8,24,0,44.8,0,70.5V441.6c0,25.7,20.8,46.4,46.4,46.4h419.2c25.6,0,46.4-20.7,46.4-46.4V70.5C512,44.8,491.2,24,465.6,24zM464,440H48V120h416V440z"/><path d="M368,348.2H144v52.7h224V348.2zM160,384.8v-20.7h192v20.7H160z"/><circle cx="241.6" cy="225.6" r="30.2" fill="none" stroke-width="20"/><path d="M300.8,268.7l16.7,16.8c7,7,18.4,7,25.4,0c7-7,7-18.5,0-25.5l-17-17L300.8,268.7z"/></svg>',
        plan: '<svg viewBox="0 0 512 512" style="width:__S__;height:__S__;fill:currentColor;"><path d="M473.2,39.6c-5.2-18.2-19.2-32.1-37.1-37.3C431.1,0.8,426,0,420.4,0H91.6c-30.3,0-55,24.7-55,55v403.4c0.9,29.6,24.7,53.2,54.3,53.6h205.1c10.6,0,20.8-2.2,30.6-6.6c8.2-3.8,15.5-8.9,21.7-15.1L453.8,384.8c6.3-6.3,11.6-13.9,15.1-21.9c4.3-9.4,6.5-19.9,6.5-30.5V55C475.4,49.4,474.7,44.3,473.2,39.6zM303.6,356.5V466.5c-2.5,0.7-5,1-7.6,1H91.4c-5.6-0.1-10.2-4.7-10.3-10.2V55c0-5.8,4.7-10.5,10.5-10.5h328.9c1,0,1.6,0.1,2.9,0.5c3.5,0.9,6.3,3.7,7.4,7.9c0.2,0.5,0.3,1.1,0.3,2.1v277.4c0,2.6-0.3,5.2-1,7.7H320C311,340.1,303.6,347.5,303.6,356.5z"/><rect x="166.5" y="115.3" width="178.9" height="19.9" rx="2.2"/><rect x="166.5" y="192.8" width="178.9" height="19.9" rx="2.2"/><rect x="166.5" y="270.3" width="178.9" height="19.7" rx="2.2"/><rect x="166.5" y="347.9" width="94.5" height="19.9" rx="2.2"/></svg>',
        implement: '<svg viewBox="0 0 512 512" style="width:__S__;height:__S__;fill:currentColor;"><path d="M362,300.9v-0.2l-33.3,33.3v78.4c0,12.9-10.5,23.4-23.5,23.4H156c-8.6,0-16.9-0.9-25-2.5V353.2c0-8.4-6.8-15.1-15.1-15.1H35.9c-1.7-8.1-2.5-16.4-2.5-25V99.7c0-12.9,10.5-23.4,23.4-23.4h248.4c13,0,23.5,10.5,23.5,23.4v11l-0.1,7.8l0.1-0.1v0.2l31.8-31.8c-5.9-25-28.4-43.8-55.3-43.8H56.8C25.5,42.9,0,68.4,0,99.7v213.5c0,10.7,1.1,21.4,3.2,31.8c12.7,60.8,60.1,108.3,121.1,120.9c10.3,2.1,21,3.3,31.7,3.3h149.2c31.4,0,56.8-25.5,56.8-56.8v-65.5l0.1-46L362,300.9z"/><path d="M508.4,99.9L455,46.5c-2.8-2.8-6.7-4-10.5-3.5c-0.9-0.1-1.9,0-2.9,0.2c-0.4,0.1-0.8,0.2-1.3,0.3c-1,0.3-1.9,0.6-2.9,1.2c-0.4,0.3-0.9,0.5-1.4,0.9c-0.4,0.3-0.9,0.5-1.3,0.9L202.7,282.1l-28.1,90c-1.3,4.2,2.1,8.4,6.3,8.4c0.6,0,1.2-0.1,1.9-0.3l90-28.1L508.8,116.1C513.2,111.7,513,104.5,508.4,99.9z"/></svg>',
        verification: '<svg viewBox="0 0 512 512" style="width:__S__;height:__S__;fill:currentColor;"><path d="M492.7,41l-5-5.4L250.9,252.3l-39.5-42.3c-13.9-14.8-33.5-23.4-53.8-23.4c-18.7,0-36.6,7-50.3,19.8l-5.3,5L218.2,336c7.9,8.4,19,13.3,30.6,13.3c10.5,0,20.5-3.9,28.2-11L488.1,145.1C518.1,117.7,520.1,71,492.7,41z"/><path d="M454.2,231.7v-0.1l-52,47.6v117.7c0,18.9-15.4,34.2-34.2,34.2H86.2c-18.9,0-34.2-15.3-34.2-34.2V115.1c0-18.8,15.3-34.2,34.2-34.2h281.7c2.9,0,5.7,0.4,8.4,1l40.9-37.4c-14-9.9-31-15.6-49.4-15.6H86.2C38.7,28.9,0,67.6,0,115.1v281.7c0,47.6,38.7,86.2,86.2,86.2h281.7c47.5,0,86.2-38.7,86.2-86.2v-97.6l0.1-67.7L454.2,231.7z"/></svg>',
        design_builder: '<svg viewBox="0 0 512 512" style="width:__S__;height:__S__;fill:currentColor;"><path d="M56 72h400c30.9 0 56 25.1 56 56v224c0 30.9-25.1 56-56 56H304l-56 56-56-56H56c-30.9 0-56-25.1-56-56V128c0-30.9 25.1-56 56-56zm0 48c-4.4 0-8 3.6-8 8v224c0 4.4 3.6 8 8 8h156l36 36 36-36h172c4.4 0 8-3.6 8-8V128c0-4.4-3.6-8-8-8H56z"/><path d="M96 168h320v32H96zm0 72h320v32H96zm0 72h224v32H96z"/></svg>',
        default: '<svg viewBox="0 0 512 512" style="width:__S__;height:__S__;fill:currentColor;"><path d="M484.1,176.9H350.3c-12,0-22.7-7.8-26.4-19.2L282.4,30.4c-8.3-25.6-44.6-25.6-52.9,0l-41.4,127.3c-3.7,11.5-14.4,19.2-26.4,19.2H27.9c-26.9,0-38.1,34.5-16.3,50.3l108.3,78.7c9.7,7.1,13.8,19.6,10.1,31.1L88.6,464.3c-8.3,25.6,21,46.9,42.8,31.1l108.3-78.7c9.7-7.1,22.9-7.1,32.7,0l108.3,78.7c21.8,15.8,51.1-5.5,42.8-31.1L382.1,337c-3.7-11.5,0.4-24,10.1-31.1l108.3-78.7C522.3,211.4,511.1,176.9,484.1,176.9z"/></svg>',
    };
    var c = colors[profile] || colors['default'];
    var l = labels[profile] || profile || '-';
    var iconSize = Math.round(size * 0.45) + 'px';
    var icon = (icons[profile] || icons['default']).replace(/__S__/g, iconSize);
    var bc = opts.borderColor || 'color-mix(in srgb, ' + c + ' 20%, rgba(255,255,255,0.3))';

    var label = opts.showLabel !== false
        ? '<div style="font-size:' + Math.max(8, Math.round(size * 0.32)) + 'px; font-weight:600; color:' + c + '; text-align:center; margin-bottom:2px; white-space:nowrap;">' + l + '</div>'
        : '';

    return '<div style="display:inline-flex; flex-direction:column; align-items:center; vertical-align:top;">'
        + label
        + '<div style="width:' + size + 'px; height:' + size + 'px; position:relative; transform-style:preserve-3d; transform:rotateX(-15deg) rotateY(-25deg);">'
        + '<div style="position:absolute; width:' + size + 'px; height:' + size + 'px; background:color-mix(in srgb, ' + c + ' 22%, rgba(255,255,255,0.18)); border:1px solid ' + bc + '; transform:translateZ(' + half + 'px); display:flex; align-items:center; justify-content:center; color:' + c + ';">' + icon + '</div>'
        + '<div style="position:absolute; width:' + size + 'px; height:' + size + 'px; background:color-mix(in srgb, ' + c + ' 35%, rgba(255,255,255,0.12)); border:1px solid color-mix(in srgb, ' + c + ' 15%, rgba(255,255,255,0.1)); transform:rotateY(90deg) translateZ(' + half + 'px);"></div>'
        + '<div style="position:absolute; width:' + size + 'px; height:' + size + 'px; background:color-mix(in srgb, ' + c + ' 18%, rgba(255,255,255,0.22)); border:1px solid color-mix(in srgb, ' + c + ' 15%, rgba(255,255,255,0.15)); transform:rotateX(90deg) translateZ(' + half + 'px);"></div>'
        + '</div></div>';
}
