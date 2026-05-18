/* ===========================================
   PhuongAnh TTS - Main JavaScript
   Enhanced with chunked generation support
   =========================================== */

// API Configuration
const API_BASE_URL = 'http://localhost:8000';
const TTS_API_URL = 'http://localhost:8000';

// ===========================================
// Auth Functions
// ===========================================

function getAuthToken() {
    return localStorage.getItem('auth_token');
}

function setAuthToken(token) {
    localStorage.setItem('auth_token', token);
}

function clearAuthToken() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user');
}

function getCurrentUser() {
    const userStr = localStorage.getItem('user');
    return userStr ? JSON.parse(userStr) : null;
}

function setCurrentUser(user) {
    localStorage.setItem('user', JSON.stringify(user));
}

function isLoggedIn() {
    return !!getAuthToken();
}

function logout() {
    clearAuthToken();
    window.location.href = '/login';
}

// ===========================================
// API Functions
// ===========================================

async function apiRequest(endpoint, options = {}) {
    const token = getAuthToken();
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            ...options,
            headers
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Request failed');
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// ===========================================
// Auth API
// ===========================================

async function login(email, password) {
    const data = await apiRequest('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password })
    });

    if (data.access_token) {
        setAuthToken(data.access_token);
        setCurrentUser(data.user);
    }

    return data;
}

function isAdmin() {
    const user = getCurrentUser();
    return user && user.role === 'admin';
}

function getLoginRedirectUrl() {
    const user = getCurrentUser();
    if (user && user.role === 'admin') {
        return '/admin';
    }
    return '/';
}

async function register(email, password, username = null) {
    const body = { email, password };
    if (username) body.username = username;

    const data = await apiRequest('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify(body)
    });

    return data;
}

async function logoutApi() {
    const token = getAuthToken();
    if (token) {
        try {
            await apiRequest('/api/auth/logout', {
                method: 'POST',
                body: JSON.stringify({ refresh_token: token })
            });
        } catch (e) {
            console.log('Logout API error (ignored)');
        }
    }
    clearAuthToken();
}

// ===========================================
// TTS Functions (Enhanced)
// ===========================================

// Generation state
let currentJobId = null;
let isGenerating = false;
let generationController = null;

/**
 * Generate speech with progress tracking
 * @param {string} text - Text to synthesize
 * @param {string} voiceId - Voice ID
 * @param {function} onProgress - Progress callback (chunk, total, message)
 * @param {function} onComplete - Completion callback
 * @param {function} onError - Error callback
 * @returns {Promise<Blob>} Audio blob
 */
async function generateSpeechWithProgress(text, voiceId = 'Ly', onProgress, onComplete, onError) {
    if (!text.trim()) {
        throw new Error('Vui lòng nhập văn bản');
    }

    isGenerating = true;
    currentJobId = null;

    const formData = new FormData();
    formData.append('text', text);
    formData.append('voice_id', voiceId);
    formData.append('format', 'wav');

    const token = getAuthToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
        // For better UX, use the async job-based approach
        const jobResponse = await fetch(`${TTS_API_URL}/api/audio/generate-async`, {
            method: 'POST',
            body: formData,
            headers
        });

        if (!jobResponse.ok) {
            const error = await jobResponse.json().catch(() => ({ detail: 'Tạo audio thất bại' }));
            throw new Error(error.detail || `Lỗi HTTP ${jobResponse.status}`);
        }

        const jobData = await jobResponse.json();
        currentJobId = jobData.job_id;

        // Poll for job status
        const audioBlob = await pollForJobComplete(currentJobId, onProgress);

        if (onComplete) {
            onComplete(audioBlob);
        }

        return audioBlob;

    } catch (error) {
        if (onError) {
            onError(error);
        }
        throw error;
    } finally {
        isGenerating = false;
        currentJobId = null;
    }
}

/**
 * Poll for job completion with progress updates
 */
async function pollForJobComplete(jobId, onProgress, pollInterval = 1000, maxAttempts = 300) {
    let attempts = 0;

    while (attempts < maxAttempts) {
        try {
            const response = await fetch(`${TTS_API_URL}/api/audio/job/${jobId}`);
            
            if (!response.ok) {
                throw new Error('Failed to get job status');
            }

            const job = await response.json();

            // Update progress
            if (onProgress && job.progress !== undefined) {
                onProgress(job.progress, 100, job.status);
            }

            if (job.status === 'completed' && job.result) {
                // Download the audio file
                const audioResponse = await fetch(`${TTS_API_URL}/api/audio/job/${jobId}/audio`);
                
                if (!audioResponse.ok) {
                    throw new Error('Failed to download audio');
                }

                return await audioResponse.blob();
            }

            if (job.status === 'failed') {
                throw new Error(job.error || 'Generation failed');
            }

            if (job.status === 'cancelled') {
                throw new Error('Generation was cancelled');
            }

            // Wait before next poll
            await new Promise(resolve => setTimeout(resolve, pollInterval));
            attempts++;

        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error('Generation was cancelled');
            }
            throw error;
        }
    }

    throw new Error('Generation timed out');
}

/**
 * Cancel the current generation
 */
async function cancelGeneration() {
    if (!currentJobId) {
        console.log('No active job to cancel');
        return;
    }

    try {
        const response = await fetch(`${TTS_API_URL}/api/audio/job/${currentJobId}/cancel`, {
            method: 'POST'
        });

        if (response.ok) {
            console.log('Generation cancelled');
            isGenerating = false;
            currentJobId = null;
        }
    } catch (error) {
        console.error('Failed to cancel:', error);
    }
}

/**
 * Check if currently generating
 */
function isCurrentlyGenerating() {
    return isGenerating;
}

/**
 * Get current job ID
 */
function getCurrentJobId() {
    return currentJobId;
}

// Legacy function for simple generation
async function generateSpeech(text, voiceId = 'Ly') {
    if (!text.trim()) {
        throw new Error('Vui lòng nhập văn bản');
    }

    const formData = new FormData();
    formData.append('text', text);
    formData.append('voice_id', voiceId);
    formData.append('format', 'wav');

    const token = getAuthToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${TTS_API_URL}/api/audio/generate-form`, {
        method: 'POST',
        body: formData,
        headers
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Tạo audio thất bại' }));
        throw new Error(error.detail || `Lỗi HTTP ${response.status}`);
    }

    return await response.blob();
}

// ===========================================
// Voice List
// ===========================================

async function getVoices() {
    try {
        const data = await apiRequest('/api/audio/voices');
        return data.voices || [];
    } catch {
        return [
            { id: 'Ly', name: 'Ly (Nữ miền Bắc)' },
            { id: 'Binh', name: 'Bình (Nam miền Bắc)' },
            { id: 'Tuyen', name: 'Tuyên (Nam miền Bắc)' },
            { id: 'Vinh', name: 'Vĩnh (Nam miền Nam)' },
            { id: 'Doan', name: 'Đoan (Nữ miền Nam)' },
            { id: 'Ngoc', name: 'Ngọc (Nữ miền Bắc)' }
        ];
    }
}

// ===========================================
// UI Functions
// ===========================================

function showAlert(message, type = 'success') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;
    
    const container = document.querySelector('.auth-card') || document.querySelector('.tts-editor');
    if (container) {
        container.insertBefore(alertDiv, container.firstChild);
        setTimeout(() => alertDiv.remove(), 5000);
    }
}

function showLoading(button, text = 'Đang xử lý...') {
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="loading"></span> ' + text;
    }
}

function hideLoading(button, originalText) {
    if (button) {
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

function updateNavbarAuth() {
    const authLinks = document.querySelector('.navbar-actions');
    if (!authLinks) return;

    if (isLoggedIn()) {
        const user = getCurrentUser();
        authLinks.innerHTML = `
            <span style="font-size: 14px; color: var(--text-gray);">Xin chào, ${user?.username || user?.email || 'User'}</span>
            <button class="btn btn-outline" onclick="handleLogout()">Đăng xuất</button>
        `;
    }
}

async function handleLogout() {
    await logoutApi();
    logout();
}

// ===========================================
// Navbar Scroll Effect
// ===========================================

function initNavbarScroll() {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });
}

// ===========================================
// Mobile Menu Toggle
// ===========================================

function initMobileMenu() {
    const toggle = document.querySelector('.menu-toggle');
    const mobileMenu = document.querySelector('.mobile-menu');
    
    if (!toggle || !mobileMenu) return;

    toggle.addEventListener('click', () => {
        mobileMenu.classList.toggle('active');
    });

    mobileMenu.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', () => {
            mobileMenu.classList.remove('active');
        });
    });
}

// ===========================================
// Active Nav Link
// ===========================================

function setActiveNavLink() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.navbar-menu a, .mobile-menu a');
    
    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href === currentPath || 
            (currentPath === '/' && href === '/') ||
            (currentPath.includes(href) && href !== '/')) {
            link.classList.add('active');
        }
    });
}

// ===========================================
// Character Counter
// ===========================================

function initCharCounter(textarea, counter, max = 5000) {
    if (!textarea || !counter) return;

    textarea.addEventListener('input', () => {
        const count = textarea.value.length;
        counter.textContent = `${count} / ${max}`;
        
        if (count > max * 0.9) {
            counter.style.color = '#EF4444';
        } else {
            counter.style.color = '';
        }
    });
}

// ===========================================
// Audio Player
// ===========================================

function playAudio(audioUrl) {
    const audio = new Audio(audioUrl);
    audio.play();
}

function downloadAudio(audioUrl, filename = 'phuonganh-tts.mp3') {
    const link = document.createElement('a');
    link.href = audioUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ===========================================
// Progress UI for TTS
// ===========================================

class TTSProgressUI {
    constructor(options = {}) {
        this.progressBar = options.progressBar || document.getElementById('ttsProgressBar');
        this.progressText = options.progressText || document.getElementById('ttsProgressText');
        this.statusText = options.statusText || document.getElementById('ttsStatusText');
        this.cancelBtn = options.cancelBtn || document.getElementById('cancelBtn');
        
        this.totalChunks = 0;
        this.currentChunk = 0;
    }

    start(totalChunks) {
        this.totalChunks = totalChunks;
        this.currentChunk = 0;
        this.updateUI();
    }

    update(current, total, message) {
        this.currentChunk = current;
        this.totalChunks = total;
        this.updateUI(message);
    }

    updateUI(statusMessage) {
        if (this.progressBar) {
            const percent = this.totalChunks > 0 
                ? Math.round((this.currentChunk / this.totalChunks) * 100) 
                : 0;
            this.progressBar.style.width = `${percent}%`;
            this.progressBar.setAttribute('aria-valuenow', percent);
        }

        if (this.progressText) {
            this.progressText.textContent = `Đang xử lý chunk ${this.currentChunk}/${this.totalChunks}`;
        }

        if (this.statusText && statusMessage) {
            this.statusText.textContent = statusMessage;
        }
    }

    complete(message = 'Hoàn thành!') {
        if (this.progressBar) {
            this.progressBar.style.width = '100%';
        }
        if (this.progressText) {
            this.progressText.textContent = message;
        }
        if (this.statusText) {
            this.statusText.textContent = '';
        }
        if (this.cancelBtn) {
            this.cancelBtn.style.display = 'none';
        }
    }

    error(message) {
        if (this.progressBar) {
            this.progressBar.style.backgroundColor = '#EF4444';
        }
        if (this.progressText) {
            this.progressText.textContent = 'Lỗi';
        }
        if (this.statusText) {
            this.statusText.textContent = message;
        }
    }

    reset() {
        this.currentChunk = 0;
        this.totalChunks = 0;
        if (this.progressBar) {
            this.progressBar.style.width = '0%';
            this.progressBar.style.backgroundColor = '';
        }
        if (this.progressText) {
            this.progressText.textContent = '';
        }
        if (this.statusText) {
            this.statusText.textContent = '';
        }
        if (this.cancelBtn) {
            this.cancelBtn.style.display = 'none';
        }
    }

    showCancelButton() {
        if (this.cancelBtn) {
            this.cancelBtn.style.display = 'inline-block';
        }
    }
}

// ===========================================
// Initialize on Load
// ===========================================

document.addEventListener('DOMContentLoaded', () => {
    initNavbarScroll();
    initMobileMenu();
    setActiveNavLink();
    updateNavbarAuth();
});

// ===========================================
// Form Validation
// ===========================================

function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validatePassword(password) {
    if (password.length < 8) {
        return 'Mật khẩu phải có ít nhất 8 ký tự';
    }
    if (!/[A-Z]/.test(password)) {
        return 'Mật khẩu phải có ít nhất 1 chữ hoa (A-Z)';
    }
    if (!/[a-z]/.test(password)) {
        return 'Mật khẩu phải có ít nhất 1 chữ thường (a-z)';
    }
    if (!/[0-9]/.test(password)) {
        return 'Mật khẩu phải có ít nhất 1 số (0-9)';
    }
    return null;
}

// ===========================================
// Export functions for use in HTML
// ===========================================

window.PhuongAnhTTS = {
    // Auth
    login,
    register,
    logout: handleLogout,
    
    // TTS
    generateSpeech,
    generateSpeechWithProgress,
    cancelGeneration,
    isCurrentlyGenerating,
    getCurrentJobId,
    
    // Voices
    getVoices,
    
    // UI
    showAlert,
    showLoading,
    hideLoading,
    isLoggedIn,
    isAdmin,
    getCurrentUser,
    getLoginRedirectUrl,
    validateEmail,
    validatePassword,
    playAudio,
    downloadAudio,
    initCharCounter,
    apiRequest,
    
    // Progress UI
    TTSProgressUI,
};
