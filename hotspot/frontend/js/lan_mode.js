/**
 * 手机端局域网模式：通过中转站 WebSocket 与电脑通信
 * 若 URL 带 mode=lan&relay_ws=...&pc_id=... 则自动连接中转站并走 WS 发指令
 * 支持心跳：收到服务端 ping 回 pong，避免长时间不用被 NAT/休眠断连；超时未收到任何消息则主动重连
 */
(function () {
    var params = new URLSearchParams(window.location.search);
    var mode = params.get('mode');
    var relayWs = params.get('relay_ws');
    var pcId = params.get('pc_id');

    if (mode !== 'lan' || !relayWs || !pcId) {
        window.__kpsr_lan_ws = null;
        window.__kpsr_lan_phone_id = null;
        return;
    }

    var phoneId = 'ph_' + Math.random().toString(36).slice(2, 12);
    var ws = null;
    var reconnectTimer = null;
    var idleCheckTimer = null;
    var lastReceivedAt = 0;
    var IDLE_RECONNECT_SEC = 60;  // 超过 60 秒未收到任何消息则视为断线，主动关闭以触发重连

    function clearIdleCheck() {
        if (idleCheckTimer) {
            clearInterval(idleCheckTimer);
            idleCheckTimer = null;
        }
    }

    function startIdleCheck() {
        clearIdleCheck();
        lastReceivedAt = Date.now();
        idleCheckTimer = setInterval(function () {
            if (!ws || ws.readyState !== 1) {
                clearIdleCheck();
                return;
            }
            if ((Date.now() - lastReceivedAt) / 1000 > IDLE_RECONNECT_SEC) {
                clearIdleCheck();
                ws.close();
            }
        }, 10000);
    }

    function connect() {
        try {
            ws = new WebSocket(relayWs);
            ws.onopen = function () {
                ws.send(JSON.stringify({
                    type: 'register',
                    role: 'phone',
                    id: phoneId,
                    pair_code: pcId
                }));
                startIdleCheck();
            };
            ws.onmessage = function (e) {
                lastReceivedAt = Date.now();
                try {
                    var data = JSON.parse(e.data);
                    if (data.type === 'ping') {
                        ws.send(JSON.stringify({ type: 'pong' }));
                        return;
                    }
                    if (data.type === 'paired' || data.type === 'phone_paired') {
                        console.log('[KPSR LAN] 已配对电脑:', data.pc_id || data.phone_id);
                    }
                } catch (err) {}
            };
            ws.onclose = function () {
                window.__kpsr_lan_ws = null;
                clearIdleCheck();
                if (reconnectTimer) clearTimeout(reconnectTimer);
                reconnectTimer = setTimeout(connect, 3000);
            };
            ws.onerror = function () {
                ws && ws.close();
            };
            ws.addEventListener('open', function once() {
                window.__kpsr_lan_ws = ws;
                window.__kpsr_lan_phone_id = phoneId;
                ws.removeEventListener('open', once);
            });
        } catch (e) {
            console.error('[KPSR LAN] 连接失败:', e);
            reconnectTimer = setTimeout(connect, 3000);
        }
    }

    connect();

    window.__kpsr_send_lan_command = function (commandType, payload) {
        if (!window.__kpsr_lan_ws || window.__kpsr_lan_ws.readyState !== 1) return Promise.reject(new Error('未连接'));
        var msg = { type: 'command', command_type: commandType, payload: payload || {} };
        window.__kpsr_lan_ws.send(JSON.stringify(msg));
        return Promise.resolve({ status: 'success' });
    };
})();
