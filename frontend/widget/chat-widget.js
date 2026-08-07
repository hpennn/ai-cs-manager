(function() {
    'use strict';

    // ===== 配置 =====
    const API_BASE = window.__CS_WIDGET_API__ || 'http://localhost:8600';
    const STORAGE_KEY = 'cs_widget_session_id';
    const WIDGET_WIDTH = 380;
    const WIDGET_HEIGHT = 520;

    // ===== 生成或获取 session_id =====
    function getSessionId() {
        let sid = localStorage.getItem(STORAGE_KEY);
        if (!sid) {
            sid = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 10);
            localStorage.setItem(STORAGE_KEY, sid);
        }
        return sid;
    }

    // ===== 客服图标 SVG =====
    function getChatIcon() {
        return '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>' +
            '</svg>';
    }

    // ===== 关闭图标 SVG =====
    function getCloseIcon() {
        return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<line x1="18" y1="6" x2="6" y2="18"/>' +
            '<line x1="6" y1="6" x2="18" y2="18"/>' +
            '</svg>';
    }

    // ===== 最小化图标 SVG =====
    function getMinimizeIcon() {
        return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<line x1="5" y1="12" x2="19" y2="12"/>' +
            '</svg>';
    }

    // ===== 发送图标 SVG =====
    function getSendIcon() {
        return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<line x1="22" y1="2" x2="11" y2="13"/>' +
            '<polygon points="22 2 15 22 11 13 2 9 22 2"/>' +
            '</svg>';
    }

    // ===== 创建 Widget =====
    function createWidget() {
        const sessionId = getSessionId();
        let isOpen = false;
        let companyName = 'AI客服';
        let welcomeMsg = '您好！我是AI客服，请问有什么可以帮您？';
        let messages = [];

        // 获取公司名称和欢迎语
        fetchConfig();

        // 创建 Shadow DOM
        const host = document.createElement('div');
        host.id = 'cs-widget-host';
        host.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:2147483647;font-family:system-ui,-apple-system,sans-serif;';
        document.body.appendChild(host);

        const shadow = host.attachShadow({ mode: 'open' });

        // 样式
        const style = document.createElement('style');
        style.textContent = getWidgetStyles();
        shadow.appendChild(style);

        // 容器
        const container = document.createElement('div');
        container.className = 'cs-widget-container';
        shadow.appendChild(container);

        // 渲染按钮
        function renderButton() {
            container.innerHTML = `
                <div class="cs-chat-btn" id="csBtn">
                    ${getChatIcon()}
                </div>
            `;
            container.querySelector('#csBtn').addEventListener('click', function() {
                if (!isOpen) openChat();
            });
        }

        // 渲染聊天窗口
        function renderChat() {
            container.innerHTML = `
                <div class="cs-chat-window">
                    <!-- 标题栏 -->
                    <div class="cs-chat-header">
                        <div class="cs-header-info">
                            <div class="cs-avatar">AI</div>
                            <div>
                                <div class="cs-company-name">${escapeHtml(companyName)}</div>
                                <div class="cs-status"><span class="cs-dot"></span> 在线客服</div>
                            </div>
                        </div>
                        <div class="cs-header-actions">
                            <button class="cs-header-btn" id="csMinimize" title="最小化">${getMinimizeIcon()}</button>
                            <button class="cs-header-btn" id="csClose" title="关闭">${getCloseIcon()}</button>
                        </div>
                    </div>

                    <!-- 消息区 -->
                    <div class="cs-messages" id="csMessages">
                        ${renderMessages()}
                    </div>

                    <!-- 输入区 -->
                    <div class="cs-input-area">
                        <input type="text" class="cs-input" id="csInput" placeholder="输入消息..." autocomplete="off">
                        <button class="cs-send-btn" id="csSendBtn" title="发送">
                            ${getSendIcon()}
                        </button>
                    </div>
                </div>
            `;

            // 绑定事件
            container.querySelector('#csMinimize').addEventListener('click', function() {
                isOpen = false;
                renderButton();
            });

            container.querySelector('#csClose').addEventListener('click', function() {
                isOpen = false;
                renderButton();
            });

            const input = container.querySelector('#csInput');
            const sendBtn = container.querySelector('#csSendBtn');

            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                }
            });

            sendBtn.addEventListener('click', handleSend);

            // 滚动到底部
            scrollToBottom();
            input.focus();
        }

        // 渲染消息列表
        function renderMessages() {
            if (messages.length === 0) {
                return `<div class="cs-msg cs-msg-ai"><div class="cs-bubble-ai">${escapeHtml(welcomeMsg)}</div></div>`;
            }
            return messages.map(function(m) {
                if (m.role === 'user') {
                    return `<div class="cs-msg cs-msg-user"><div class="cs-bubble-user">${escapeHtml(m.content)}</div></div>`;
                } else {
                    return `<div class="cs-msg cs-msg-ai"><div class="cs-bubble-ai">${escapeHtml(m.content)}</div></div>`;
                }
            }).join('');
        }

        // 打开聊天
        function openChat() {
            isOpen = true;
            renderChat();
        }

        // 发送消息
        async function handleSend() {
            const input = container.querySelector('#csInput');
            const sendBtn = container.querySelector('#csSendBtn');
            const text = input.value.trim();
            if (!text) return;

            // 添加用户消息
            messages.push({ role: 'user', content: text });
            input.value = '';
            refreshMessages();
            scrollToBottom();

            // 显示 loading
            sendBtn.disabled = true;
            addLoadingBubble();

            try {
                const res = await fetch(API_BASE + '/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: sessionId,
                        message: text
                    })
                });

                removeLoadingBubble();

                if (!res.ok) throw new Error('请求失败');

                const data = await res.json();
                const reply = data.reply || data.message || data.content || data.response || '抱歉，暂时无法回复。';

                messages.push({ role: 'assistant', content: reply });
            } catch (e) {
                removeLoadingBubble();
                messages.push({ role: 'assistant', content: '抱歉，网络异常，请稍后再试。' });
            } finally {
                sendBtn.disabled = false;
                refreshMessages();
                scrollToBottom();
                container.querySelector('#csInput').focus();
            }
        }

        // 添加 loading 气泡
        function addLoadingBubble() {
            const msgContainer = container.querySelector('#csMessages');
            if (!msgContainer) return;
            const loading = document.createElement('div');
            loading.className = 'cs-msg cs-msg-ai cs-loading-bubble';
            loading.innerHTML = '<div class="cs-bubble-ai"><div class="cs-dots"><span></span><span></span><span></span></div></div>';
            msgContainer.appendChild(loading);
            scrollToBottom();
        }

        // 移除 loading 气泡
        function removeLoadingBubble() {
            const loading = container.querySelector('.cs-loading-bubble');
            if (loading) loading.remove();
        }

        // 刷新消息列表
        function refreshMessages() {
            const msgContainer = container.querySelector('#csMessages');
            if (msgContainer) {
                msgContainer.innerHTML = renderMessages();
            }
        }

        // 滚动到底部
        function scrollToBottom() {
            setTimeout(function() {
                const msgContainer = container.querySelector('#csMessages');
                if (msgContainer) {
                    msgContainer.scrollTop = msgContainer.scrollHeight;
                }
            }, 50);
        }

        // 获取配置
        async function fetchConfig() {
            try {
                const res = await fetch(API_BASE + '/api/config');
                if (res.ok) {
                    const data = await res.json();
                    if (data.company_name) companyName = data.company_name;
                    if (data.welcome_message) welcomeMsg = data.welcome_message;
                }
            } catch (e) {
                // 使用默认配置
            }
        }

        // HTML 转义
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 初始渲染
        renderButton();
    }

    // ===== Widget 样式 =====
    function getWidgetStyles() {
        return `
            .cs-widget-container { position: relative; }

            /* 聊天按钮 */
            .cs-chat-btn {
                width: 56px; height: 56px; border-radius: 50%;
                background: linear-gradient(135deg, #4f46e5, #7c3aed);
                display: flex; align-items: center; justify-content: center;
                cursor: pointer; box-shadow: 0 4px 20px rgba(79, 70, 229, 0.4);
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .cs-chat-btn:hover {
                transform: scale(1.08);
                box-shadow: 0 6px 28px rgba(79, 70, 229, 0.5);
            }

            /* 聊天窗口 */
            .cs-chat-window {
                width: ${WIDGET_WIDTH}px; height: ${WIDGET_HEIGHT}px;
                background: #1a1a2e; border-radius: 16px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.5);
                display: flex; flex-direction: column;
                overflow: hidden; animation: csSlideUp 0.3s ease;
                position: absolute; bottom: 0; right: 0;
            }
            @keyframes csSlideUp {
                from { opacity: 0; transform: translateY(16px) scale(0.95); }
                to { opacity: 1; transform: translateY(0) scale(1); }
            }

            /* 标题栏 */
            .cs-chat-header {
                padding: 14px 16px;
                background: linear-gradient(135deg, #4f46e5, #7c3aed);
                display: flex; align-items: center; justify-content: space-between;
                flex-shrink: 0;
            }
            .cs-header-info { display: flex; align-items: center; gap: 10px; }
            .cs-avatar {
                width: 36px; height: 36px; border-radius: 50%;
                background: rgba(255,255,255,0.2); display: flex;
                align-items: center; justify-content: center;
                font-size: 12px; font-weight: 700; color: #fff;
            }
            .cs-company-name { color: #fff; font-size: 14px; font-weight: 600; }
            .cs-status { color: rgba(255,255,255,0.7); font-size: 11px; display: flex; align-items: center; gap: 4px; }
            .cs-dot { width: 6px; height: 6px; border-radius: 50%; background: #4ade80; display: inline-block; }
            .cs-header-actions { display: flex; gap: 4px; }
            .cs-header-btn {
                width: 28px; height: 28px; border: none; border-radius: 6px;
                background: rgba(255,255,255,0.15); color: #fff;
                cursor: pointer; display: flex; align-items: center; justify-content: center;
                transition: background 0.2s;
            }
            .cs-header-btn:hover { background: rgba(255,255,255,0.25); }

            /* 消息区 */
            .cs-messages {
                flex: 1; overflow-y: auto; padding: 16px;
                display: flex; flex-direction: column; gap: 10px;
                background: #0f0f1a;
            }
            .cs-messages::-webkit-scrollbar { width: 4px; }
            .cs-messages::-webkit-scrollbar-track { background: transparent; }
            .cs-messages::-webkit-scrollbar-thumb { background: #4f46e5; border-radius: 2px; }

            /* 消息气泡 */
            .cs-msg { display: flex; }
            .cs-msg-user { justify-content: flex-end; }
            .cs-msg-ai { justify-content: flex-start; }
            .cs-bubble-user {
                max-width: 75%; padding: 10px 14px; border-radius: 14px 14px 4px 14px;
                background: #4f46e5; color: #fff; font-size: 13px; line-height: 1.5;
                word-wrap: break-word;
            }
            .cs-bubble-ai {
                max-width: 75%; padding: 10px 14px; border-radius: 14px 14px 14px 4px;
                background: #2a2a3e; color: #d1d5db; font-size: 13px; line-height: 1.5;
                word-wrap: break-word;
            }

            /* Loading 动画 */
            .cs-dots { display: flex; gap: 4px; padding: 4px 0; }
            .cs-dots span {
                width: 6px; height: 6px; border-radius: 50%;
                background: #6b7280; animation: csDotPulse 1.4s infinite ease-in-out;
            }
            .cs-dots span:nth-child(1) { animation-delay: 0s; }
            .cs-dots span:nth-child(2) { animation-delay: 0.2s; }
            .cs-dots span:nth-child(3) { animation-delay: 0.4s; }
            @keyframes csDotPulse {
                0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
                40% { opacity: 1; transform: scale(1); }
            }

            /* 输入区 */
            .cs-input-area {
                padding: 12px; display: flex; gap: 8px;
                border-top: 1px solid #2a2a3e; flex-shrink: 0;
                background: #1a1a2e;
            }
            .cs-input {
                flex: 1; padding: 10px 14px; border-radius: 10px;
                background: #2a2a3e; border: 1px solid #333;
                color: #fff; font-size: 13px; outline: none;
                transition: border-color 0.2s;
            }
            .cs-input::placeholder { color: #6b7280; }
            .cs-input:focus { border-color: #4f46e5; }
            .cs-send-btn {
                width: 38px; height: 38px; border-radius: 10px;
                background: linear-gradient(135deg, #4f46e5, #7c3aed);
                border: none; cursor: pointer; display: flex;
                align-items: center; justify-content: center;
                transition: opacity 0.2s; flex-shrink: 0;
            }
            .cs-send-btn:hover { opacity: 0.9; }
            .cs-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        `;
    }

    // ===== 初始化 =====
    window.addEventListener('load', function() {
        createWidget();
    });

})();
