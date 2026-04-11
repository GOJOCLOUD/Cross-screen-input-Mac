// KPSR 电脑端控制台

console.log('desktop.js文件已加载');

let qrcode = null;
let refreshTimer = null;

// 立即执行初始化，不等待DOMContentLoaded
console.log('开始初始化...');
init();

async function init() {
    try {
        console.log('开始加载访问信息...');
        await loadAccessInfo();
        console.log('访问信息加载完成');
        
        console.log('开始加载状态...');
        await loadStatus();
        console.log('状态加载完成');
        
        console.log('开始加载激活状态...');
        await loadActivationStatus();
        console.log('激活状态加载完成');
        
        // 初始化按钮和其他功能
        initCopyBtn();
        console.log('复制按钮初始化完成');
        
        initActivationButtons();
        console.log('激活按钮初始化完成');
        
        initPortSave();
        console.log('端口保存初始化完成');
        
        // 初始化用户协议
        initAgreement();
        console.log('用户协议初始化完成');
        
        startRefresh();
        console.log('刷新定时器启动完成');
        console.log('初始化完成');
    } catch (error) {
        console.error('初始化失败:', error);
    }
}

// 加载状态
async function loadStatus() {
    try {
        const res = await fetch('/api/desktop/status');
        const data = await res.json();
        
        // 服务器状态
        const serverDot = document.getElementById('serverDot');
        const serverText = document.getElementById('serverText');
        if (serverDot && serverText) {
            if (data.server_running) {
                serverDot.className = 'status-dot online';
                serverText.textContent = '运行中';
            } else {
                serverDot.className = 'status-dot offline';
                serverText.textContent = '已停止';
            }
        }
        
        // 端口
        const portText = document.getElementById('portText');
        if (portText) {
            portText.textContent = data.port || '--';
        }
        
        // 鼠标监听状态（与 desktop.html 一致：权限已全部授予时亦为绿点）
        const mouseDot = document.getElementById('mouseDot');
        const mouseText = document.getElementById('mouseText');
        const mp = data.mouse_permission || {};
        const listenerOn = !!data.mouse_listener_status;
        const permsOk = !!mp.all_granted;
        const dotOk = listenerOn || permsOk;
        if (mouseDot) mouseDot.className = 'status-dot ' + (dotOk ? 'online' : 'offline');
        if (mouseText) {
            if (listenerOn) mouseText.textContent = '运行中';
            else if (permsOk) mouseText.textContent = mp.message || '权限已就绪';
            else mouseText.textContent = mp.message || data.mouse_permission_hint || '已停止';
        }
        
        // 当前监听端口
        const listeningPortText = document.getElementById('listeningPortText');
        if (listeningPortText) {
            listeningPortText.textContent = data.port || '--';
        }
    } catch (error) {
        console.error('加载状态失败:', error);
    }
}

// 加载访问信息
async function loadAccessInfo() {
    try {
        const res = await fetch('/api/desktop/access-info');
        const data = await res.json();
        
        const linkDisplay = document.getElementById('linkDisplay');
        if (linkDisplay) {
            if (data.phone_url) {
                linkDisplay.textContent = data.phone_url;
                generateQRCode(data.qrcode_url || data.phone_url);
            } else {
                linkDisplay.textContent = '未检测到可用网络';
            }
        }
        
        // 更新本机IPv4显示
        const hotspotDot = document.getElementById('hotspotDot');
        const hotspotText = document.getElementById('hotspotText');
        if (hotspotDot && hotspotText) {
            if (data.hotspot_ip) {
                hotspotDot.className = 'status-dot online';
                hotspotText.textContent = data.hotspot_ip;
            } else {
                hotspotDot.className = 'status-dot offline';
                hotspotText.textContent = '未检测到';
            }
        }
    } catch (error) {
        console.error('加载访问信息失败:', error);
    }
}

// 生成二维码
function generateQRCode(url) {
    const qrcodeDiv = document.getElementById('qrcode');
    if (!qrcodeDiv) return;
    
    qrcodeDiv.innerHTML = '';
    
    try {
        qrcode = new QRCode(qrcodeDiv, {
            text: url,
            width: 200,
            height: 200,
            colorDark: '#1a1a1a',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    } catch (error) {
        console.error('生成二维码失败:', error);
        qrcodeDiv.innerHTML = '<p style="color: #999;">二维码生成失败</p>';
    }
}

// 初始化复制按钮
function initCopyBtn() {
    const copyBtn = document.getElementById('copyBtn');
    const linkDisplay = document.getElementById('linkDisplay');
    const copyFeedback = document.getElementById('copyFeedback');
    
    if (!copyBtn || !linkDisplay) return;
    
    copyBtn.addEventListener('click', async () => {
        const url = linkDisplay.textContent;
        if (!url || url === '获取中...' || url === '未检测到可用网络') {
            return;
        }
        
        try {
            await navigator.clipboard.writeText(url);
            if (copyFeedback) {
                copyFeedback.classList.add('show');
                setTimeout(() => {
                    copyFeedback.classList.remove('show');
                }, 2000);
            }
        } catch (error) {
            console.error('复制失败:', error);
            // 降级方案
            const textarea = document.createElement('textarea');
            textarea.value = url;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                if (copyFeedback) {
                    copyFeedback.classList.add('show');
                    setTimeout(() => {
                        copyFeedback.classList.remove('show');
                    }, 2000);
                }
            } catch (e) {
                console.error('复制失败:', e);
            }
            document.body.removeChild(textarea);
        }
    });
}

// 加载激活状态
async function loadActivationStatus() {
    try {
        const res = await fetch('/api/activation/status');
        const data = await res.json();
        
        const activationDot = document.getElementById('activationDot');
        const activationText = document.getElementById('activationText');
        const activatedStatus = document.getElementById('activatedStatus');
        const activatedAction = document.getElementById('activatedAction');
        const unactivatedStatus = document.getElementById('unactivatedStatus');
        const uuidRow = document.getElementById('uuidRow');
        const licenseRow = document.getElementById('licenseRow');
        const uuidDisplay = document.getElementById('uuidDisplay');
        
        if (data.activated) {
            // 已激活
            if (activationDot) activationDot.className = 'status-dot online';
            if (activationText) activationText.textContent = '已激活';
            if (activatedStatus) activatedStatus.style.display = 'flex';
            if (activatedAction) activatedAction.style.display = 'flex';
            if (unactivatedStatus) unactivatedStatus.style.display = 'none';
            if (uuidRow) uuidRow.style.display = 'none';
            if (licenseRow) licenseRow.style.display = 'none';
        } else {
            // 未激活
            if (activationDot) activationDot.className = 'status-dot offline';
            if (activationText) activationText.textContent = '未激活';
            if (activatedStatus) activatedStatus.style.display = 'none';
            if (activatedAction) activatedAction.style.display = 'none';
            if (unactivatedStatus) unactivatedStatus.style.display = 'flex';
            if (uuidRow) uuidRow.style.display = 'flex';
            if (licenseRow) licenseRow.style.display = 'flex';
            
            // 加载UUID
            if (uuidDisplay) {
                try {
                    const uuidRes = await fetch('/api/activation/uuid');
                    const uuidData = await uuidRes.json();
                    uuidDisplay.textContent = uuidData.uuid || '获取失败';
                } catch (e) {
                    uuidDisplay.textContent = '获取失败';
                }
            }
        }
    } catch (error) {
        console.error('加载激活状态失败:', error);
    }
}

// 初始化激活按钮
function initActivationButtons() {
    const activateBtn = document.getElementById('activateBtn');
    const deactivateBtn = document.getElementById('deactivateBtn');
    const copyUuidBtn = document.getElementById('copyUuidBtn');
    
    // 激活按钮
    if (activateBtn) {
        activateBtn.addEventListener('click', async () => {
            const licenseInput = document.getElementById('licenseInput');
            const licenseKey = licenseInput ? licenseInput.value.trim() : '';
            
            if (!licenseKey) {
                alert('请输入激活码');
                return;
            }
            
            try {
                const res = await fetch('/api/activation/activate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ license_key: licenseKey })
                });
                
                const data = await res.json();
                
                if (res.ok && (data.activated || data.status === 'success')) {
                    alert('激活成功！');
                    loadActivationStatus();
                } else {
                    let msg = data.message || data.detail || '激活码无效';
                    if (Array.isArray(data.detail)) {
                        msg = data.detail.map(function (x) { return x.msg || JSON.stringify(x); }).join('; ');
                    }
                    alert('激活失败：' + msg);
                }
            } catch (error) {
                console.error('激活失败:', error);
                alert('激活失败，请检查网络连接');
            }
        });
    }
    
    // 取消激活按钮
    if (deactivateBtn) {
        deactivateBtn.addEventListener('click', async () => {
            if (!confirm('确定要取消激活吗？')) {
                return;
            }
            
            try {
                const res = await fetch('/api/activation/deactivate', {
                    method: 'POST'
                });
                
                const data = await res.json();
                
                if (data.success) {
                    alert('已取消激活');
                    loadActivationStatus();
                } else {
                    alert('操作失败：' + (data.message || '未知错误'));
                }
            } catch (error) {
                console.error('取消激活失败:', error);
                alert('操作失败，请检查网络连接');
            }
        });
    }
    
    // 复制UUID按钮
    if (copyUuidBtn) {
        copyUuidBtn.addEventListener('click', async () => {
            const uuidDisplay = document.getElementById('uuidDisplay');
            if (!uuidDisplay) return;
            
            const uuid = uuidDisplay.textContent;
            if (!uuid || uuid === '获取中...' || uuid === '获取失败') {
                return;
            }
            
            try {
                await navigator.clipboard.writeText(uuid);
                const originalText = copyUuidBtn.textContent;
                copyUuidBtn.textContent = '已复制';
                setTimeout(() => {
                    copyUuidBtn.textContent = originalText;
                }, 2000);
            } catch (error) {
                console.error('复制失败:', error);
            }
        });
    }
}

// 初始化端口保存
function initPortSave() {
    const savePortBtn = document.getElementById('savePortBtn');
    const portInput = document.getElementById('portInput');
    const portSaveMsg = document.getElementById('portSaveMsg');
    
    if (!savePortBtn || !portInput) return;
    
    savePortBtn.addEventListener('click', async () => {
        const port = parseInt(portInput.value);
        
        if (!port || port < 1024 || port > 65535) {
            if (portSaveMsg) {
                portSaveMsg.textContent = '请输入 1024-65535 之间的端口号';
                portSaveMsg.style.color = '#dc2626';
                portSaveMsg.classList.add('show');
                setTimeout(() => {
                    portSaveMsg.classList.remove('show');
                }, 2000);
            }
            return;
        }
        
        try {
            const res = await fetch('/api/desktop/port', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ http_port: port })
            });
            
            const data = await res.json();
            
            if (res.ok) {
                if (portSaveMsg) {
                    portSaveMsg.textContent = '保存成功，请完全退出并重启后生效';
                    portSaveMsg.style.color = '#16a34a';
                    portSaveMsg.classList.add('show');
                    setTimeout(() => {
                        portSaveMsg.classList.remove('show');
                    }, 3000);
                }
                portInput.value = '';
            } else {
                if (portSaveMsg) {
                    portSaveMsg.textContent = '保存失败: ' + (data.detail || data.message || '未知错误');
                    portSaveMsg.style.color = '#dc2626';
                    portSaveMsg.classList.add('show');
                    setTimeout(() => {
                        portSaveMsg.classList.remove('show');
                    }, 4000);
                }
            }
        } catch (error) {
            console.error('保存端口失败:', error);
            if (portSaveMsg) {
                portSaveMsg.textContent = '保存失败，请检查网络连接';
                portSaveMsg.style.color = '#dc2626';
                portSaveMsg.classList.add('show');
                setTimeout(() => {
                    portSaveMsg.classList.remove('show');
                }, 4000);
            }
        }
    });
}

// 用户协议相关
const AGREEMENT_KEY = 'kpsr_agreement_accepted';

function initAgreement() {
    const modal = document.getElementById('agreementModal');
    const agreeBtn = document.getElementById('agreeBtn');
    const disagreeBtn = document.getElementById('disagreeBtn');
    const linkBtn = document.getElementById('agreementLinkBtn');
    
    if (!modal) return;
    
    // 检查是否已经同意过协议
    const hasAgreed = localStorage.getItem(AGREEMENT_KEY) === 'true';
    
    // 首次启动显示协议
    if (!hasAgreed) {
        showAgreementModal();
    }
    
    // 同意按钮
    if (agreeBtn) {
        agreeBtn.addEventListener('click', () => {
            localStorage.setItem(AGREEMENT_KEY, 'true');
            hideAgreementModal();
        });
    }
    
    // 不同意按钮
    if (disagreeBtn) {
        disagreeBtn.addEventListener('click', () => {
            // 关闭窗口或退出
            if (confirm('您必须同意用户协议才能使用本软件。是否退出？')) {
                window.close();
                // 如果无法关闭窗口，显示提示
                setTimeout(() => {
                    alert('请手动关闭本页面');
                }, 100);
            }
        });
    }
    
    // 链接按钮（手动打开协议）
    if (linkBtn) {
        linkBtn.addEventListener('click', () => {
            showAgreementModal();
        });
    }
}

function showAgreementModal() {
    const modal = document.getElementById('agreementModal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
}

function hideAgreementModal() {
    const modal = document.getElementById('agreementModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
    }
}

// 定时刷新状态
function startRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    refreshTimer = setInterval(() => {
        loadStatus();
        loadAccessInfo();
        loadActivationStatus();
    }, 5000);
}
