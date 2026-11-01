/**
 * app.js — Tiện ích dùng chung cho các trang: header, toast, gọi API.
 */

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── Header ──────────────────────────────────────────────────────────────────

function mountHeader() {
  const el = document.getElementById('app-header');
  if (!el) return;
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  const links = [
    ['/', 'Tạo video', 'M15 10l4.553-2.069A1 1 0 0121 8.87V15.13a1 1 0 01-1.447.9L15 14M3 8a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z'],
    ['/memes', 'Thư viện', 'M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z'],
    ['/settings', 'Cài đặt', 'M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4'],
  ];
  el.className = 'border-b border-zinc-800 bg-zinc-950 sticky top-0 z-40';
  el.innerHTML = `
    <div class="max-w-4xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="/" class="flex items-center gap-2 font-bold text-lg tracking-tight">
        <span class="w-7 h-7 rounded-lg bg-brand flex items-center justify-center text-sm">▶</span>
        <span>Threads<span class="text-brand-light">Video</span></span>
      </a>
      <nav class="flex items-center gap-1">
        ${links.map(([href, label, icon]) => `
          <a href="${href}" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition
             ${path === href ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white hover:bg-zinc-800'}">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${icon}"/></svg>
            <span class="hidden sm:inline">${label}</span>
          </a>`).join('')}
      </nav>
    </div>`;
}

// ── Toast ───────────────────────────────────────────────────────────────────

function showToast(message, type = 'success', timeout = 5000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const colors = { success: 'border-green-500', error: 'border-red-500', info: 'border-blue-500', warning: 'border-yellow-500' };
  const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
  const toast = document.createElement('div');
  toast.className = `flex items-start gap-3 bg-zinc-900 text-white text-sm px-4 py-3 rounded-lg shadow-lg border-l-4
    ${colors[type] || colors.info} toast-slide-in max-w-sm w-full pointer-events-auto`;
  toast.innerHTML = `<span class="font-bold">${icons[type] || icons.info}</span>
    <span class="flex-1 leading-snug whitespace-pre-line">${escapeHtml(message)}</span>
    <button class="text-zinc-500 hover:text-white ml-1">✕</button>`;
  toast.querySelector('button').onclick = () => toast.remove();
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-fade-out');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  }, type === 'error' ? Math.max(timeout, 9000) : timeout);
}

// ── API ─────────────────────────────────────────────────────────────────────

/**
 * apiCall(path, method, body, {silent}) — trả về JSON, hoặc null nếu lỗi (đã hiện toast).
 */
async function apiCall(path, method = 'GET', body = null, opts = {}) {
  const req = { method, headers: {} };
  if (body instanceof FormData) {
    req.body = body;
  } else if (body !== null) {
    req.headers['Content-Type'] = 'application/json';
    req.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(path, req);
    const ct = res.headers.get('content-type') || '';
    const data = ct.includes('application/json') ? await res.json() : null;
    if (!res.ok) {
      let msg = data?.detail ?? `Lỗi ${res.status}`;
      if (Array.isArray(msg)) msg = 'Dữ liệu gửi lên không hợp lệ: ' + msg.map(d => d.msg).join('; ');
      if (!opts.silent) showToast(msg, 'error');
      if (opts.throwOnError) throw new Error(msg);
      return null;
    }
    return data;
  } catch (err) {
    if (opts.throwOnError) throw err;
    if (!opts.silent) showToast('Không kết nối được tới tool. Kiểm tra cửa sổ chạy server (run.bat / run.sh) còn mở không.', 'error');
    return null;
  }
}

function formatSeconds(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} giây`;
  const m = Math.floor(s / 60), sec = s % 60;
  return sec ? `${m} phút ${sec} giây` : `${m} phút`;
}

/** Đặt nút vào trạng thái đang chạy; trả về hàm khôi phục. */
function busy(btn, text = 'Đang xử lý…') {
  if (!btn) return () => {};
  const html = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> ${escapeHtml(text)}`;
  return () => { btn.disabled = false; btn.innerHTML = html; };
}

document.addEventListener('DOMContentLoaded', mountHeader);
