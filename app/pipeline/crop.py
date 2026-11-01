"""
crop.py — Cắt các thẻ bài/bình luận Threads từ ảnh chụp màn hình.

Thuật toán: tìm các vùng chữ nhật nền trắng/sáng lớn (threshold → morphology → findContours),
lọc theo diện tích (> 15% ảnh), độ rộng và tỉ lệ khung; một ảnh có thể chứa nhiều thẻ,
sắp xếp từ trên xuống dưới. Vùng ngoài thẻ (viền đen, nền game, thanh trạng thái) bị loại.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

from app.utils import imread, imwrite

Box = Tuple[int, int, int, int]  # x, y, w, h

MIN_AREA_FRAC = 0.15        # theo spec
FALLBACK_AREA_FRAC = 0.05   # thử lại với ngưỡng nhỏ hơn nếu không thấy thẻ nào
MIN_WIDTH_FRAC = 0.5        # thẻ thường rộng gần hết màn hình
MIN_FILL = 0.80             # vùng sáng phải "đặc" như hình chữ nhật
STATUS_BAR_FRAC = 0.045     # thanh trạng thái điện thoại ~4.5% chiều cao


def _bright_mask(img: np.ndarray, thresh: int) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # sáng và ít bão hòa màu (nền trắng/xám nhạt của thẻ)
    mask = ((gray >= thresh) & (hsv[:, :, 1] <= 40)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return mask


def _find_boxes(img: np.ndarray, thresh: int, min_area_frac: float) -> List[Box]:
    h_img, w_img = img.shape[:2]
    total = h_img * w_img
    mask = _bright_mask(img, thresh)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: List[Box] = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w * h < total * min_area_frac:
            continue
        if w < w_img * MIN_WIDTH_FRAC:
            continue
        aspect = w / max(h, 1)
        if not (0.3 <= aspect <= 12):
            continue
        if cv2.contourArea(cnt) / float(w * h) < MIN_FILL:
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[1])
    return boxes


def _trim_phone_chrome(box: Box, h_img: int, w_img: int) -> Box:
    """Nếu vùng chạm mép trên/dưới của ảnh chụp điện thoại → bỏ thanh trạng thái / thanh điều hướng."""
    x, y, w, h = box
    if h_img / max(w_img, 1) < 1.5:
        return box
    cut = int(h_img * STATUS_BAR_FRAC)
    if y < cut:
        h -= cut - y
        y = cut
    bottom_cut = int(h_img * 0.035)
    if y + h > h_img - bottom_cut:
        h = h_img - bottom_cut - y
    return (x, y, w, max(h, 1))


def detect_card_boxes(img: np.ndarray) -> List[Box]:
    """Trả về danh sách khung thẻ (x, y, w, h) từ trên xuống. Không thấy thẻ → cả ảnh."""
    h_img, w_img = img.shape[:2]
    best: List[Box] = []
    for min_frac in (MIN_AREA_FRAC, FALLBACK_AREA_FRAC):
        for thresh in (240, 215, 190):
            boxes = _find_boxes(img, thresh, min_frac)
            if len(boxes) > len(best):
                best = boxes
        if best:
            break
    if not best:
        best = [_content_box(img)]
    return [_trim_phone_chrome(b, h_img, w_img) for b in best]


def _content_box(img: np.ndarray) -> Box:
    """Bỏ viền đen quanh ảnh (khi không tìm được thẻ sáng)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(gray > 20)
    if len(xs) == 0:
        h, w = gray.shape
        return (0, 0, w, h)
    return (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def crop_cards(image_path: str, output_dir: str, prefix: str) -> List[dict]:
    """Cắt ảnh thành các thẻ, lưu PNG vào *output_dir*.

    Returns:
        [{"path": ".../prefix_1.png", "box": [x1, y1, x2, y2]}, ...] theo thứ tự trên → dưới.
    """
    img = imread(image_path)
    if img is None:
        raise ValueError(f"Không đọc được ảnh '{Path(image_path).name}' (định dạng không hỗ trợ?).")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, (x, y, w, h) in enumerate(detect_card_boxes(img), start=1):
        out = out_dir / f"{prefix}_{i}.png"
        imwrite(out, img[y:y + h, x:x + w])
        results.append({"path": str(out), "box": [x, y, x + w, y + h]})
    return results


def manual_crop(image_path: str, box: list[int] | tuple, output_path: str) -> str:
    """Cắt tay một vùng [x1, y1, x2, y2] (theo pixel ảnh gốc)."""
    img = imread(image_path)
    if img is None:
        raise ValueError(f"Không đọc được ảnh: {Path(image_path).name}")
    h_img, w_img = img.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, x2 = sorted((max(0, x1), min(w_img, x2)))
    y1, y2 = sorted((max(0, y1), min(h_img, y2)))
    if x2 - x1 < 20 or y2 - y1 < 20:
        raise ValueError("Vùng cắt quá nhỏ. Hãy kéo một khung lớn hơn.")
    imwrite(output_path, img[y1:y2, x1:x2])
    return output_path


def _ink_mask(img: np.ndarray, thresh: int = 35) -> np.ndarray:
    """Điểm ảnh khác màu nền thẻ (chữ, avatar...). Nền lấy theo trung vị viền ảnh → chạy cả dark mode."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.int16)
    border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    bg = int(np.median(border))
    return (np.abs(gray - bg) > thresh).astype(np.uint8)


def detect_author_regions(img: np.ndarray) -> list[list[int]]:
    """Tìm avatar (khối tròn/vuông ở góc trên trái) và dòng tên + thời gian ngay bên phải nó.

    Trả về [] nếu không chắc chắn (để không làm mờ nhầm thân bài).
    """
    h, w = img.shape[:2]
    ink = _ink_mask(img)
    lim_y, lim_x = min(h, int(0.30 * w)), int(0.22 * w)
    region = cv2.morphologyEx(ink[:lim_y, :lim_x], cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(region, connectivity=8)
    avatar = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (0.035 * w <= bw <= 0.16 * w and 0.75 <= bw / max(bh, 1) <= 1.33):
            continue
        if area < 0.55 * bw * bh:  # avatar là khối đặc (hình tròn ≈ 0,785)
            continue
        if avatar is None or y < avatar[1]:
            avatar = (int(x), int(y), int(bw), int(bh))
    if avatar is None:
        return []
    ax, ay, aw, ah = avatar
    regions = [[ax, ay, ax + aw, ay + ah]]

    # Dòng tên: dải chữ đầu tiên bên phải avatar, bắt đầu gần mép trên avatar
    x0 = ax + aw + int(0.01 * w)
    y_from = max(0, ay - int(0.02 * w))
    y_to = min(h, ay + ah + int(0.02 * w))
    rows = ink[y_from:y_to, x0:].sum(axis=1)
    start = next((i for i, v in enumerate(rows) if v > 2), None)
    if start is not None:
        end, blank = start, 0
        for i in range(start, len(rows)):
            if rows[i] > 2:
                end, blank = i, 0
            else:
                blank += 1
                if blank >= 3:
                    break
        band_h = end - start + 1
        if band_h <= 0.08 * w:
            y1, y2 = y_from + start, y_from + end + 1
            cols = np.where(ink[y1:y2, x0:].sum(axis=0) > 0)[0]
            if len(cols):
                regions.append([x0 + int(cols.min()), y1, x0 + int(cols.max()) + 1, y2])
    return regions


def clamp_llm_box(box: list[int] | None, w: int, h: int) -> list[list[int]]:
    """Dự phòng khi không tự dò được: chỉ nhận vùng AI khoanh nếu nằm ở phần đầu thẻ và đủ nhỏ."""
    if not box:
        return []
    x1, y1, x2, y2 = box
    if y1 > 0.3 * h or (y2 - y1) > 0.12 * w or (x2 - x1) > 0.8 * w:
        return []
    return [box]


def mask_regions(image_path: str, boxes: list[list[int]], pad: int = 6) -> None:
    """Che (pixel hóa + làm mờ) các vùng tên/avatar trong ảnh thẻ, ghi đè file."""
    img = imread(image_path)
    if img is None:
        return
    h_img, w_img = img.shape[:2]
    for box in boxes:
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        x1, x2 = sorted((max(0, x1 - pad), min(w_img, x2 + pad)))
        y1, y2 = sorted((max(0, y1 - pad), min(h_img, y2 + pad)))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        roi = img[y1:y2, x1:x2]
        small = cv2.resize(roi, (max(1, (x2 - x1) // 12), max(1, (y2 - y1) // 12)), interpolation=cv2.INTER_AREA)
        roi = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
        img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (0, 0), 5)
    imwrite(image_path, img)
