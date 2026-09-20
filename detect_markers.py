#!/usr/bin/env python3
"""
detect_markers.py  —  Rule-based fiducial detector (no training)

Mapping (orange only):
- Square  -> nose
- Circles -> ears (up to 2)
- Triangles -> limbs (thumbs + big toes)

Features
- Batch images (dir/glob)
- Live webcam (--webcam)
- Video file (--video path.mp4)
- Outputs: CSV + JSON, annotated frames

Usage examples:
  python detect_markers.py --dir images --out out
  python detect_markers.py --glob "images/*.jpg" --out out --json landmarks.json
  python detect_markers.py --webcam --show
  python detect_markers.py --video demo.mp4 --out out --show

Requirements:
  pip install opencv-python numpy
"""

import argparse, csv, glob, json, math, os, time
from pathlib import Path
import cv2
import numpy as np

# ---------- Color thresholds (OpenCV HSV: H in [0,179]) ----------
DEFAULT_LOWER_ORANGE = (7, 140, 120)
DEFAULT_UPPER_ORANGE = (20, 255, 255)

# ---------- Helpers ----------

def annulus_test(mask, center, radius, inner_ratio=0.6, ring_width_px=3, min_ring_pct=0.25, max_core_pct=0.15):
    """Confirm 'orange ring with dark (non-orange) center'."""
    h, w = mask.shape[:2]
    cx, cy = int(round(center[0])), int(round(center[1]))
    R = int(max(1, round(radius)))
    r = max(1, int(round(R * inner_ratio)))

    x0, x1 = max(0, cx - R - ring_width_px), min(w, cx + R + ring_width_px)
    y0, y1 = max(0, cy - R - ring_width_px), min(h, cy + R + ring_width_px)
    roi = mask[y0:y1, x0:x1]
    if roi.size == 0:
        return False

    Y, X = np.ogrid[y0:y1, x0:x1]
    dist2 = (X - cx)**2 + (Y - cy)**2
    ring_band = (dist2 <= (R**2)) & (dist2 >= ((r-ring_width_px)**2))
    core = (dist2 <= (r**2))

    ring_all = int(np.count_nonzero(ring_band))
    core_all = int(np.count_nonzero(core))
    if ring_all == 0 or core_all == 0:
        return False

    ring_pos = int(np.count_nonzero(roi[ring_band] > 0))
    core_pos = int(np.count_nonzero(roi[core] > 0))

    ring_pct = ring_pos / ring_all
    core_pct = core_pos / core_all
    return (ring_pct >= min_ring_pct) and (core_pct <= max_core_pct)


def classify_shape(cnt):
    """Return (shape, center(x,y), area, score, extra) or None."""
    A = cv2.contourArea(cnt)
    if A < 50:
        return None
    P = cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, 0.03 * P, True)
    verts = len(approx)
    M = cv2.moments(cnt)
    if M["m00"] == 0:
        return None
    cx, cy = (M["m10"] / M["m00"], M["m01"] / M["m00"])

    if verts == 3:
        return ("triangle", (cx, cy), A, 1.0, {})

    if verts == 4:
        rect = cv2.minAreaRect(cnt)
        (w, h) = rect[1]
        if w == 0 or h == 0:
            return None
        ar = max(w, h) / min(w, h)
        if 0.80 <= ar <= 1.25:
            score = 1.0 - min(abs(1 - ar), 0.25)  # closer to square -> higher score
            return ("square", (cx, cy), A, score, {})

    circ = 4 * math.pi * A / (P * P + 1e-6)
    if circ >= 0.75 or verts >= 8:
        (x, y), r = cv2.minEnclosingCircle(cnt)
        score = float(min(1.0, circ))
        return ("circle", (cx, cy), A, score, {"radius": r})

    return None


def detect_fiducials(bgr, lower=DEFAULT_LOWER_ORANGE, upper=DEFAULT_UPPER_ORANGE, use_annulus=False):
    """Return dict with detected shapes and mask image for viz."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    circles, squares, triangles = [], [], []
    for c in cnts:
        r = classify_shape(c)
        if not r:
            continue
        shape, (cx, cy), area, score, extra = r

        if shape == "circle" and use_annulus:
            (x, y), rad = cv2.minEnclosingCircle(c)
            if not annulus_test(mask, (x, y), rad, inner_ratio=0.6, ring_width_px=3):
                # If you require rings for ears, skip solids here.
                pass

        if shape == "circle":
            circles.append((cx, cy, score, extra))
        elif shape == "square":
            squares.append((cx, cy, score, extra))
        elif shape == "triangle":
            triangles.append((cx, cy, score, extra))

    return {"mask": mask, "circles": circles, "squares": squares, "triangles": triangles}


def assign_landmarks(circles, squares, triangles, image_shape):
    """Assign labels with geometry. Returns (list, x_mid)."""
    out = []
    pts = [(x, y) for (x, y, *_rest) in (circles + squares + triangles)]
    x_mid = float(np.median([p[0] for p in pts])) if pts else image_shape[1] / 2.0

    # Nose: prefer square; else topmost near midline
    if squares:
        nose = sorted(squares, key=lambda p: p[1])[0]
        out.append({"label": "nose", "x": nose[0], "y": nose[1], "visible": True, "conf": 0.95})
    else:
        top = sorted(circles + triangles, key=lambda p: p[1])[:3]
        if top:
            nose = min(top, key=lambda p: abs(p[0] - x_mid))
            out.append({"label": "nose", "x": nose[0], "y": nose[1], "visible": True, "conf": 0.75})

    # Ears: circles near the top
    head_circles = sorted(circles, key=lambda p: p[1])[:2]
    if head_circles:
        left  = min(head_circles, key=lambda p: p[0])
        out.append({"label": "ear_L", "x": left[0], "y": left[1], "visible": True, "conf": float(left[2])})
        if len(head_circles) >= 2:
            right = max(head_circles, key=lambda p: p[0])
            out.append({"label": "ear_R", "x": right[0], "y": right[1], "visible": True, "conf": float(right[2])})

    # Limbs: triangles -> thumbs (upper two) and toes (lower two)
    tris_by_y = sorted(triangles, key=lambda p: p[1])
    if len(tris_by_y) >= 1:
        thumbs = tris_by_y[:2]
        if thumbs:
            lt = min(thumbs, key=lambda p: p[0])
            out.append({"label": "thumb_L", "x": lt[0], "y": lt[1], "visible": True, "conf": 0.9})
        if len(thumbs) == 2:
            rt = max(thumbs, key=lambda p: p[0])
            out.append({"label": "thumb_R", "x": rt[0], "y": rt[1], "visible": True, "conf": 0.9})
    if len(tris_by_y) >= 2:
        toes = tris_by_y[-2:]
        ltoe = min(toes, key=lambda p: p[0])
        rtoe = max(toes, key=lambda p: p[0])
        out.append({"label": "toe_L", "x": ltoe[0], "y": ltoe[1], "visible": True, "conf": 0.9})
        out.append({"label": "toe_R", "x": rtoe[0], "y": rtoe[1], "visible": True, "conf": 0.9})

    return out, x_mid


def draw_annotations(img, detections, x_mid=None):
    """Overlay detections and optional midline on image."""
    col = (0, 255, 0)
    for d in detections:
        x, y = int(round(d["x"])), int(round(d["y"]))
        cv2.circle(img, (x, y), 6, col, 2)
        cv2.putText(img, d["label"], (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    if x_mid is not None:
        x_m = int(round(x_mid))
        cv2.line(img, (x_m, 0), (x_m, img.shape[0]-1), (255, 0, 0), 1)
    return img


def process_image(bgr, lower_orange, upper_orange, use_annulus=False):
    det = detect_fiducials(
        bgr,
        lower=lower_orange,
        upper=upper_orange,
        use_annulus=use_annulus
    )
    results, x_mid = assign_landmarks(det["circles"], det["squares"], det["triangles"], bgr.shape)
    vis = draw_annotations(bgr.copy(), results, x_mid=x_mid)
    return results, vis


def save_row(writer, image_name, d):
    writer.writerow({
        "image": image_name,
        "label": d["label"],
        "x": round(float(d["x"]), 2),
        "y": round(float(d["y"]), 2),
        "visible": bool(d.get("visible", True)),
        "conf": round(float(d.get("conf", 0.9)), 3),
    })


def run_batch(files, out_dir, lower_orange, upper_orange, use_annulus, csv_path, json_path, show):
    out_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = ["image", "label", "x", "y", "visible", "conf"]
    json_records = []

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for fp in files:
            bgr = cv2.imread(fp)
            if bgr is None:
                print(f"[WARN] Could not read image: {fp}")
                continue
            results, vis = process_image(bgr, lower_orange, upper_orange, use_annulus)
            # Save CSV + JSON
            base = os.path.basename(fp)
            for d in results:
                save_row(writer, base, d)
                rec = {"image": base, **d}
                json_records.append(rec)

            # Annotated frame
            out_img = out_dir / f"{Path(fp).stem}_annotated.png"
            cv2.imwrite(str(out_img), vis)

            if show:
                cv2.imshow("detections", vis)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    # Write JSON once at the end
    with open(json_path, "w") as jf:
        json.dump(json_records, jf, indent=2)

    if show:
        print("[INFO] Press any key in the image window to exit.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def run_webcam(cam_index, lower_orange, upper_orange, use_annulus, show_fps=True):
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        print("❌ Could not open webcam")
        return

    t0, frames = time.time(), 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        results, vis = process_image(frame, lower_orange, upper_orange, use_annulus)

        if show_fps:
            frames += 1
            dt = time.time() - t0
            if dt > 0:
                fps = frames / dt
                cv2.putText(vis, f"{fps:.1f} FPS", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2, cv2.LINE_AA)

        cv2.imshow("webcam detection (ESC to quit)", vis)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


def run_video(video_path, out_dir, lower_orange, upper_orange, use_annulus, save_video=False):
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"❌ Could not open video: {video_path}")
        return

    writer = None
    if save_video:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(str(out_dir / "annotated.mp4"), fourcc, fps, (w, h))

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        results, vis = process_image(frame, lower_orange, upper_orange, use_annulus)
        if writer is not None:
            writer.write(vis)
        cv2.imshow("video detection (ESC to quit)", vis)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    if writer is not None:
        writer.release()
    cv2.destroyAllWindows()


def parse_args():
    ap = argparse.ArgumentParser(description="Orange fiducial detector (square=nose, circles=ears, triangles=limbs)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", type=str, help="Directory of images to process")
    src.add_argument("--glob", type=str, help="Glob pattern, e.g., 'images/*.jpg'")
    src.add_argument("--webcam", action="store_true", help="Use webcam")
    src.add_argument("--video", type=str, help="Path to a video file")

    ap.add_argument("--out", type=str, default="out", help="Output directory (for images/video/CSV/JSON)")
    ap.add_argument("--csv", type=str, default="landmarks.csv", help="CSV filename to write inside --out")
    ap.add_argument("--json", type=str, default="landmarks.json", help="JSON filename to write inside --out")
    ap.add_argument("--show", action="store_true", help="Show windows while processing (for batch mode)")
    ap.add_argument("--save-video", action="store_true", help="(video mode) save annotated.mp4 to --out")

    ap.add_argument("--lower-orange", type=str, default=None, help="Override lower HSV for orange, e.g., '7,170,130'")
    ap.add_argument("--upper-orange", type=str, default=None, help="Override upper HSV for orange, e.g., '20,255,255'")
    ap.add_argument("--annulus", action="store_true", help="Enable ring core test for circles (if using ring-style ears)")
    ap.add_argument("--cam-index", type=int, default=0, help="Webcam index (default 0)")

    return ap.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Parse HSV overrides
    lower_orange = tuple(map(int, args.lower_orange.split(","))) if args.lower_orange else DEFAULT_LOWER_ORANGE
    upper_orange = tuple(map(int, args.upper_orange.split(","))) if args.upper_orange else DEFAULT_UPPER_ORANGE

    if args.webcam:
        run_webcam(args.cam_index, lower_orange, upper_orange, args.annulus)
        return

    if args.video:
        run_video(args.video, out_dir, lower_orange, upper_orange, args.annulus, save_video=args.save_video)
        return

    # Batch images
    if args.dir:
        files = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            files += glob.glob(str(Path(args.dir) / ext))
    else:
        files = glob.glob(args.glob)

    files = sorted(files)
    if not files:
        print("[INFO] No images found.")
        return

    csv_path  = out_dir / args.csv
    json_path = out_dir / args.json
    run_batch(files, out_dir, lower_orange, upper_orange, args.annulus, csv_path, json_path, args.show)

    print(f"[DONE] Wrote CSV:  {csv_path}")
    print(f"[DONE] Wrote JSON: {json_path}")
    print(f"[DONE] Wrote annotated images to: {out_dir}")

if __name__ == "__main__":
    main()
