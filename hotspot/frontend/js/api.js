// API调用模块

// 请求管理器
const RequestManager = {
    pending: new Map(),
    cache: new Map(),
    cacheTime: CONFIG.VALIDATION.CACHE_TIME,  // 5分钟
    
    async request(url, options = {}) {
        const key = `${options.method || 'GET'}_${url}`;
        
        // 检查是否有相同请求正在进行
        if (this.pending.has(key)) {
            return this.pending.get(key);
        }
        
        // 检查缓存
        if (options.method === 'GET' && this.cache.has(key)) {
            const cached = this.cache.get(key);
            if (Date.now() - cached.time < this.cacheTime) {
                return cached.data;
            }
        }
        
        // 发起请求
        const fetchOptions = {
            ...options,
            cache: 'no-store',
            keepalive: true
        };
        
        const promise = fetch(url, fetchOptions)
            .then(response => {
                this.pending.delete(key);
                if (!response.ok) {
                    // 检查是否是拦截响应
                    if (response.status === 403) {
                        return response.json().then(errorData => {
                            const error = new Error(`HTTP错误: ${response.status}`);
                            error.isIntercepted = true;
                            error.interceptData = errorData;
                            throw error;
                        }).catch(() => {
                            const error = new Error(`HTTP错误: ${response.status}`);
                            error.isIntercepted = true;
                            throw error;
                        });
                    }
                    throw new Error(`HTTP错误: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                // 缓存GET请求
                if (options.method === 'GET') {
                    this.cache.set(key, { data, time: Date.now() });
                }
                return data;
            })
            .catch(error => {
                this.pending.delete(key);
                throw error;
            });
        
        this.pending.set(key, promise);
        return promise;
    }
};

// API调用函数
async function loadButtonsFromServer() {
    try {
        const result = await RequestManager.request(CONFIG.API_ENDPOINTS.LIST);
        return result.buttons || [];
    } catch (error) {
        Logger.error('加载按钮失败:', error);
        // 失败时返回空数组，不阻塞界面
        return [];
    }
}

async function saveButtonToServer(buttonData) {
    try {
        const result = await RequestManager.request(CONFIG.API_ENDPOINTS.ADD, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buttonData)
        });
        return result.button;
    } catch (error) {
        Logger.error('保存按钮失败:', error);
        throw error;
    }
}

async function updateButtonOnServer(buttonId, buttonData) {
    try {
        const result = await RequestManager.request(`${CONFIG.API_ENDPOINTS.UPDATE}/${buttonId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buttonData)
        });
        return result.button;
    } catch (error) {
        Logger.error('更新按钮失败:', error);
        throw error;
    }
}

async function deleteButtonOnServer(buttonId) {
    try {
        await RequestManager.request(`${CONFIG.API_ENDPOINTS.DELETE}/${buttonId}`, {
            method: 'DELETE'
        });
        return true;
    } catch (error) {
        Logger.error('删除按钮失败:', error);
        throw error;
    }
}

async function getButtonFromServer(buttonId) {
    try {
        const result = await RequestManager.request(`${CONFIG.API_ENDPOINTS.GET}/${buttonId}`);
        return result.button;
    } catch (error) {
        Logger.error('获取按钮失败:', error);
        throw error;
    }
}

async function executeShortcutOnServer(shortcut, actionType = 'single') {
    try {
        const normalizedShortcut = normalizeShortcut(shortcut);
        if (typeof window !== 'undefined' && window.__kpsr_lan_ws && window.__kpsr_lan_ws.readyState === 1 && window.__kpsr_send_lan_command) {
            return await window.__kpsr_send_lan_command('shortcut', { shortcut: normalizedShortcut, action_type: actionType });
        }
        const result = await RequestManager.request(CONFIG.API_ENDPOINTS.EXECUTE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                shortcut: normalizedShortcut,
                action_type: actionType
            })
        });
        return result;
    } catch (error) {
        Logger.error('执行快捷键失败:', error);
        throw error;
    }
}

// 获取平台信息
async function getPlatformInfo() {
    try {
        const result = await RequestManager.request('/api/shortcut/platform', {
            method: 'GET'
        });
        return result;
    } catch (error) {
        Logger.error('获取平台信息失败:', error);
        throw error;
    }
}

// 鼠标按钮相关API
async function loadMouseButtonsFromServer() {
    try {
        const result = await RequestManager.request(CONFIG.API_ENDPOINTS.MOUSE_LIST);
        return result.buttons || [];
    } catch (error) {
        Logger.error('加载鼠标按钮失败:', error);
        // 失败时返回空数组，不阻塞界面
        return [];
    }
}

async function saveMouseButtonToServer(buttonData) {
    try {
        const result = await RequestManager.request(CONFIG.API_ENDPOINTS.MOUSE_ADD, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buttonData)
        });
        return result.button;
    } catch (error) {
        Logger.error('保存鼠标按钮失败:', error);
        throw error;
    }
}

async function updateMouseButtonOnServer(buttonId, buttonData) {
    try {
        const result = await RequestManager.request(`${CONFIG.API_ENDPOINTS.MOUSE_UPDATE}/${buttonId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buttonData)
        });
        return result.button;
    } catch (error) {
        Logger.error('更新鼠标按钮失败:', error);
        throw error;
    }
}

async function deleteMouseButtonOnServer(buttonId) {
    try {
        await RequestManager.request(`${CONFIG.API_ENDPOINTS.MOUSE_DELETE}/${buttonId}`, {
            method: 'DELETE'
        });
        return true;
    } catch (error) {
        Logger.error('删除鼠标按钮失败:', error);
        throw error;
    }
}

async function getMouseButtonFromServer(buttonId) {
    try {
        const result = await RequestManager.request(`${CONFIG.API_ENDPOINTS.MOUSE_GET}/${buttonId}`);
        return result.button;
    } catch (error) {
        Logger.error('获取鼠标按钮失败:', error);
        throw error;
    }
}

async function executeMouseOnServer(action) {
    try {
        const normalizedAction = action.toLowerCase().trim();
        if (typeof window !== 'undefined' && window.__kpsr_lan_ws && window.__kpsr_lan_ws.readyState === 1 && window.__kpsr_send_lan_command) {
            return await window.__kpsr_send_lan_command('mouse', { action: normalizedAction });
        }
        const result = await RequestManager.request(CONFIG.API_ENDPOINTS.MOUSE_EXECUTE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: normalizedAction
            })
        });
        return result;
    } catch (error) {
        Logger.error('执行鼠标操作失败:', error);
        throw error;
    }
}

// 导出API函数
const API = {
    loadButtonsFromServer,
    saveButtonToServer,
    updateButtonOnServer,
    deleteButtonOnServer,
    getButtonFromServer,
    executeShortcutOnServer,
    getPlatformInfo,
    loadMouseButtonsFromServer,
    saveMouseButtonToServer,
    updateMouseButtonOnServer,
    deleteMouseButtonOnServer,
    getMouseButtonFromServer,
    executeMouseOnServer,
    RequestManager
};

// 导出常量
if (typeof module !== 'undefined' && module.exports) {
    module.exports = API;
} else if (typeof window !== 'undefined') {
    window.API = API;
    window.loadButtonsFromServer = loadButtonsFromServer;
    window.saveButtonToServer = saveButtonToServer;
    window.updateButtonOnServer = updateButtonOnServer;
    window.deleteButtonOnServer = deleteButtonOnServer;
    window.getButtonFromServer = getButtonFromServer;
    window.executeShortcutOnServer = executeShortcutOnServer;
    window.getPlatformInfo = getPlatformInfo;
    window.loadMouseButtonsFromServer = loadMouseButtonsFromServer;
    window.saveMouseButtonToServer = saveMouseButtonToServer;
    window.updateMouseButtonOnServer = updateMouseButtonOnServer;
    window.deleteMouseButtonOnServer = deleteMouseButtonOnServer;
    window.getMouseButtonFromServer = getMouseButtonFromServer;
    window.executeMouseOnServer = executeMouseOnServer;
    window.RequestManager = RequestManager;
}
