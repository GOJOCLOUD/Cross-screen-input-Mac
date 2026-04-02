// 激活状态检查模块
// 用于检查设备激活状态并处理拦截情况

// 全局变量：存储激活状态
let activationStatus = {
    activated: false,
    checked: false,
    uuid: '',
    message: ''
};

// 检查激活状态
async function checkActivationStatus() {
    try {
        const response = await fetch('/api/activation/status');
        if (response.ok) {
            const data = await response.json();
            activationStatus = {
                activated: data.activated,
                checked: true,
                uuid: data.uuid || '',
                message: data.message || ''
            };
            return activationStatus;
        } else {
            throw new Error(`HTTP错误: ${response.status}`);
        }
    } catch (error) {
        Logger.error('检查激活状态失败:', error);
        // 网络错误时假设未激活
        activationStatus = {
            activated: false,
            checked: true,
            uuid: '',
            message: '检查激活状态失败'
        };
        return activationStatus;
    }
}

// 显示拦截状态消息
function showInterceptedMessage(content) {
    const messageList = document.getElementById('messageList');
    if (!messageList) return;
    
    // 隐藏欢迎信息
    const welcomeContainer = document.getElementById('welcomeContainer');
    if (welcomeContainer) {
        welcomeContainer.style.display = 'none';
    }
    
    // 创建拦截消息行
    const row = document.createElement('div');
    row.className = 'message-row intercepted';
    
    const bubble = document.createElement('div');
    bubble.className = 'bubble intercepted';
    bubble.innerHTML = `
        <div class="intercepted-icon">🚫</div>
        <div class="intercepted-content">
            <div class="intercepted-title">请求被拦截</div>
            <div class="intercepted-text">设备未激活，已拦截您的输入</div>
            <div class="intercepted-input">"${content}"</div>
            <div class="intercepted-hint">请联系管理员激活设备</div>
        </div>
    `;
    
    row.appendChild(bubble);
    messageList.appendChild(row);
    
    // 滚动到底部
    const scrollTarget = document.getElementById('scrollTarget');
    if (scrollTarget) {
        scrollTarget.scrollTo({ top: scrollTarget.scrollHeight, behavior: 'smooth' });
    }
    
    return row;
}

// 添加拦截状态样式
function addInterceptedStyles() {
    // 检查是否已添加样式
    if (document.getElementById('intercepted-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'intercepted-styles';
    style.textContent = `
        .message-row.intercepted {
            justify-content: flex-end;
        }
        
        .bubble.intercepted {
            background: #FFF3F3;
            color: #D32F2F;
            border-bottom-right-radius: 4px;
            max-width: 90%;
            padding: 12px 16px;
            border-left: 3px solid #D32F2F;
        }
        
        .intercepted-icon {
            font-size: 24px;
            margin-bottom: 8px;
            text-align: center;
        }
        
        .intercepted-content {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        
        .intercepted-title {
            font-weight: 600;
            font-size: 16px;
        }
        
        .intercepted-text {
            font-size: 14px;
            opacity: 0.9;
        }
        
        .intercepted-input {
            font-family: monospace;
            background: rgba(0, 0, 0, 0.05);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            word-break: break-all;
            margin: 4px 0;
        }
        
        .intercepted-hint {
            font-size: 12px;
            opacity: 0.7;
            font-style: italic;
        }
        
        /* 激活状态指示器 */
        .activation-indicator {
            position: fixed;
            top: 16px;
            right: 16px;
            background: rgba(0, 0, 0, 0.7);
            color: white;
            padding: 6px 12px;
            border-radius: 16px;
            font-size: 12px;
            z-index: 100;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .activation-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }
        
        .activation-dot.active {
            background-color: #4CAF50;
        }
        
        .activation-dot.inactive {
            background-color: #F44336;
        }
    `;
    
    document.head.appendChild(style);
}

// 显示激活状态指示器
function showActivationIndicator() {
    // 移除旧的指示器
    const oldIndicator = document.querySelector('.activation-indicator');
    if (oldIndicator) {
        oldIndicator.remove();
    }
    
    // 创建新的指示器
    const indicator = document.createElement('div');
    indicator.className = 'activation-indicator';
    indicator.innerHTML = `
        <div class="activation-dot ${activationStatus.activated ? 'active' : 'inactive'}"></div>
        <span>${activationStatus.activated ? '已激活' : '未激活'}</span>
    `;
    
    document.body.appendChild(indicator);
}

// 初始化激活状态检查
async function initializeActivationCheck() {
    // 添加样式
    addInterceptedStyles();
    
    // 检查激活状态
    await checkActivationStatus();
    
    // 显示激活状态指示器
    showActivationIndicator();
    
    // 每30秒重新检查一次激活状态
    setInterval(checkActivationStatus, 30000);
}

// 导出函数
if (typeof window !== 'undefined') {
    window.checkActivationStatus = checkActivationStatus;
    window.showInterceptedMessage = showInterceptedMessage;
    window.initializeActivationCheck = initializeActivationCheck;
    window.activationStatus = activationStatus;
}