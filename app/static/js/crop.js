/**
 * crop.js — Canvas-based manual crop tool
 * Cho phép kéo chọn vùng crop trên ảnh
 * Xuất tọa độ x1,y1,x2,y2 để gọi API /api/crop
 * Hiển thị trong overlay modal
 */

(function () {
  "use strict";

  // ─── State ───────────────────────────────────────────────────────────────

  let canvas = null;
  let ctx = null;
  let img = null;
  let isDrawing = false;
  let startX = 0;
  let startY = 0;
  let currentRect = null; // { x, y, w, h } in canvas coords
  let scaleX = 1;
  let scaleY = 1;
  let onConfirmCallback = null;

  // ─── Public API ──────────────────────────────────────────────────────────

  /**
   * Mở modal crop với ảnh được truyền vào.
   * @param {string} imageSrc - URL hoặc data URL của ảnh cần crop
   * @param {function} onConfirm - callback(x1, y1, x2, y2) khi user nhấn Crop
   */
  window.CropTool = {
    open(imageSrc, onConfirm) {
      onConfirmCallback = onConfirm;
      _initModal(imageSrc);
    },
    close: _closeModal,
  };

  // ─── Modal init ──────────────────────────────────────────────────────────

  function _initModal(imageSrc) {
    // Tạo overlay nếu chưa có
    let overlay = document.getElementById("crop-overlay");
    if (!overlay) {
      overlay = _buildOverlayHTML();
      document.body.appendChild(overlay);
      _bindOverlayEvents(overlay);
    }

    overlay.style.display = "flex";
    document.body.style.overflow = "hidden";
    document.removeEventListener("keydown", _onKeyDown);
    document.addEventListener("keydown", _onKeyDown);

    canvas = overlay.querySelector("#crop-canvas");
    ctx = canvas.getContext("2d");

    img = new Image();
    img.onload = () => {
      _fitImageToCanvas(img);
    };
    img.src = imageSrc;
  }

  function _buildOverlayHTML() {
    const overlay = document.createElement("div");
    overlay.id = "crop-overlay";
    overlay.innerHTML = `
      <div class="crop-modal">
        <div class="crop-header">
          <span>Chọn vùng crop — kéo để khoanh vùng</span>
          <button id="crop-close-btn" title="Đóng">✕</button>
        </div>
        <div class="crop-canvas-wrapper">
          <canvas id="crop-canvas"></canvas>
        </div>
        <div class="crop-footer">
          <span id="crop-coords">Chưa chọn vùng nào</span>
          <div class="crop-actions">
            <button id="crop-reset-btn" class="btn-secondary">Đặt lại</button>
            <button id="crop-confirm-btn" class="btn-primary" disabled>Crop vùng này</button>
          </div>
        </div>
      </div>
    `;
    _injectStyles();
    return overlay;
  }

  function _bindOverlayEvents(overlay) {
    const canvas = overlay.querySelector("#crop-canvas");
    const confirmBtn = overlay.querySelector("#crop-confirm-btn");
    const resetBtn = overlay.querySelector("#crop-reset-btn");
    const closeBtn = overlay.querySelector("#crop-close-btn");
    const coordsLabel = overlay.querySelector("#crop-coords");

    // Canvas mouse events
    canvas.addEventListener("mousedown", (e) => _onMouseDown(e, canvas));
    canvas.addEventListener("mousemove", (e) => _onMouseMove(e, canvas, coordsLabel, confirmBtn));
    canvas.addEventListener("mouseup", (e) => _onMouseUp(e, canvas, coordsLabel, confirmBtn));
    canvas.addEventListener("mouseleave", () => {
      if (isDrawing) {
        isDrawing = false;
        _redraw();
      }
    });

    // Touch support
    canvas.addEventListener("touchstart", (e) => {
      e.preventDefault();
      _onMouseDown(_touchToMouse(e, canvas), canvas);
    }, { passive: false });
    canvas.addEventListener("touchmove", (e) => {
      e.preventDefault();
      _onMouseMove(_touchToMouse(e, canvas), canvas, coordsLabel, confirmBtn);
    }, { passive: false });
    canvas.addEventListener("touchend", (e) => {
      e.preventDefault();
      _onMouseUp(_touchToMouse(e, canvas), canvas, coordsLabel, confirmBtn);
    }, { passive: false });

    confirmBtn.addEventListener("click", _onConfirm);
    resetBtn.addEventListener("click", () => {
      currentRect = null;
      confirmBtn.disabled = true;
      coordsLabel.textContent = "Chưa chọn vùng nào";
      _redraw();
    });
    closeBtn.addEventListener("click", _closeModal);
  }

  // ─── Canvas helpers ───────────────────────────────────────────────────────

  function _fitImageToCanvas(image) {
    const wrapper = canvas.parentElement;
    const maxW = wrapper.clientWidth - 32;
    const maxH = wrapper.clientHeight - 32;

    const ratio = Math.min(maxW / image.naturalWidth, maxH / image.naturalHeight, 1);
    canvas.width = Math.round(image.naturalWidth * ratio);
    canvas.height = Math.round(image.naturalHeight * ratio);

    scaleX = image.naturalWidth / canvas.width;
    scaleY = image.naturalHeight / canvas.height;

    currentRect = null;
    _redraw();
  }

  function _redraw() {
    if (!ctx || !img) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    if (!currentRect) return;

    const { x, y, w, h } = currentRect;

    // Vùng tối bên ngoài selection
    ctx.save();
    ctx.fillStyle = "rgba(0, 0, 0, 0.45)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Xóa vùng được chọn
    ctx.clearRect(x, y, w, h);
    ctx.drawImage(img, x * scaleX, y * scaleY, w * scaleX, h * scaleY, x, y, w, h);
    ctx.restore();

    // Viền selection
    ctx.save();
    ctx.strokeStyle = "#4F8EF7";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 3]);
    ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
    ctx.restore();

    // Handles ở 4 góc
    _drawHandles(x, y, w, h);
  }

  function _drawHandles(x, y, w, h) {
    const size = 8;
    const corners = [
      [x, y],
      [x + w - size, y],
      [x, y + h - size],
      [x + w - size, y + h - size],
    ];
    ctx.save();
    ctx.fillStyle = "#4F8EF7";
    corners.forEach(([cx, cy]) => {
      ctx.fillRect(cx, cy, size, size);
    });
    ctx.restore();
  }

  // ─── Mouse event handlers ─────────────────────────────────────────────────

  function _getCanvasPos(e, canvas) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function _onMouseDown(e, canvas) {
    const pos = _getCanvasPos(e, canvas);
    isDrawing = true;
    startX = pos.x;
    startY = pos.y;
    currentRect = null;
  }

  function _onMouseMove(e, canvas, coordsLabel, confirmBtn) {
    if (!isDrawing) return;
    const pos = _getCanvasPos(e, canvas);

    const x = Math.min(startX, pos.x);
    const y = Math.min(startY, pos.y);
    const w = Math.abs(pos.x - startX);
    const h = Math.abs(pos.y - startY);

    if (w > 4 && h > 4) {
      currentRect = { x, y, w, h };
      _updateCoords(coordsLabel, confirmBtn);
    }

    _redraw();
  }

  function _onMouseUp(e, canvas, coordsLabel, confirmBtn) {
    if (!isDrawing) return;
    isDrawing = false;

    if (currentRect && currentRect.w > 10 && currentRect.h > 10) {
      confirmBtn.disabled = false;
      _updateCoords(coordsLabel, confirmBtn);
    } else {
      currentRect = null;
      confirmBtn.disabled = true;
      if (coordsLabel) coordsLabel.textContent = "Chưa chọn vùng nào";
    }
    _redraw();
  }

  function _updateCoords(coordsLabel, confirmBtn) {
    if (!currentRect || !coordsLabel) return;
    const { x, y, w, h } = currentRect;
    const x1 = Math.round(x * scaleX);
    const y1 = Math.round(y * scaleY);
    const x2 = Math.round((x + w) * scaleX);
    const y2 = Math.round((y + h) * scaleY);
    coordsLabel.textContent = `Vùng chọn: (${x1}, ${y1}) → (${x2}, ${y2})  |  ${x2 - x1}×${y2 - y1}px`;
  }

  // ─── Confirm & close ──────────────────────────────────────────────────────

  function _onConfirm() {
    if (!currentRect) return;
    const { x, y, w, h } = currentRect;
    const x1 = Math.round(x * scaleX);
    const y1 = Math.round(y * scaleY);
    const x2 = Math.round((x + w) * scaleX);
    const y2 = Math.round((y + h) * scaleY);

    _closeModal();

    if (typeof onConfirmCallback === "function") {
      onConfirmCallback(x1, y1, x2, y2);
    }
  }

  function _closeModal() {
    const overlay = document.getElementById("crop-overlay");
    if (overlay) overlay.style.display = "none";
    document.body.style.overflow = "";
    document.removeEventListener("keydown", _onKeyDown);
    isDrawing = false;
    currentRect = null;
    onConfirmCallback = null;
  }

  function _onKeyDown(e) {
    if (e.key === "Escape") _closeModal();
    if (e.key === "Enter") _onConfirm();
  }

  // ─── Touch helpers ────────────────────────────────────────────────────────

  function _touchToMouse(e, canvas) {
    const touch = e.touches[0] || e.changedTouches[0];
    return { clientX: touch.clientX, clientY: touch.clientY };
  }

  // ─── Styles ───────────────────────────────────────────────────────────────

  function _injectStyles() {
    if (document.getElementById("crop-tool-styles")) return;
    const style = document.createElement("style");
    style.id = "crop-tool-styles";
    style.textContent = `
      #crop-overlay {
        display: none;
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.75);
        z-index: 9999;
        align-items: center;
        justify-content: center;
      }
      .crop-modal {
        background: #1e1e2e;
        border-radius: 12px;
        display: flex;
        flex-direction: column;
        width: min(95vw, 960px);
        height: min(92vh, 760px);
        box-shadow: 0 24px 80px rgba(0,0,0,0.6);
        overflow: hidden;
      }
      .crop-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 20px;
        background: #2a2a3e;
        color: #cdd6f4;
        font-size: 14px;
        font-weight: 500;
      }
      #crop-close-btn {
        background: none;
        border: none;
        color: #cdd6f4;
        font-size: 18px;
        cursor: pointer;
        line-height: 1;
        padding: 4px 8px;
        border-radius: 4px;
      }
      #crop-close-btn:hover { background: rgba(255,255,255,0.1); }
      .crop-canvas-wrapper {
        flex: 1;
        overflow: auto;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #12121e;
        padding: 16px;
      }
      #crop-canvas {
        cursor: crosshair;
        display: block;
        max-width: 100%;
        max-height: 100%;
        border-radius: 4px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.4);
      }
      .crop-footer {
        padding: 12px 20px;
        background: #2a2a3e;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
      }
      #crop-coords {
        font-size: 13px;
        color: #a6adc8;
        font-family: monospace;
      }
      .crop-actions { display: flex; gap: 8px; }
      .btn-primary {
        padding: 8px 20px;
        border: none;
        border-radius: 8px;
        background: #4F8EF7;
        color: white;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
      }
      .btn-primary:hover:not(:disabled) { background: #3b7de8; }
      .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
      .btn-secondary {
        padding: 8px 16px;
        border: 1px solid #45475a;
        border-radius: 8px;
        background: transparent;
        color: #cdd6f4;
        font-size: 14px;
        cursor: pointer;
        transition: background 0.15s;
      }
      .btn-secondary:hover { background: rgba(255,255,255,0.07); }
    `;
    document.head.appendChild(style);
  }
})();
