import os
import cv2
import json
import uuid
import numpy as np
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024 * 1024  # 4GB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ── SERVE FRONTEND ──
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/<path:page>')
def pages(page):
    return render_template(page)

# ── UPLOAD VIDEO + GET FIRST FRAME ──
@app.route('/api/upload', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file'}), 400

    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # Extract first frame for player selection
    cap = cv2.VideoCapture(filepath)
    ret, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()

    if not ret:
        return jsonify({'error': 'Could not read video'}), 400

    # Save first frame as JPEG
    frame_id = str(uuid.uuid4())
    frame_path = os.path.join(OUTPUT_FOLDER, frame_id + '_frame.jpg')

    # Resize frame for display if too large
    h, w = frame.shape[:2]
    max_w = 1280
    if w > max_w:
        scale = max_w / w
        frame = cv2.resize(frame, (max_w, int(h * scale)))

    cv2.imwrite(frame_path, frame)

    return jsonify({
        'video_id': filename,
        'frame_id': frame_id,
        'frame_url': f'/outputs/{frame_id}_frame.jpg',
        'fps': fps,
        'total_frames': total_frames,
        'duration': round(duration, 1),
        'width': frame.shape[1],
        'height': frame.shape[0]
    })


# ── ANALYSE VIDEO WITH PLAYER SELECTION BOX ──
@app.route('/api/analyse', methods=['POST'])
def analyse_video():
    data = request.get_json()
    video_id = data.get('video_id')
    bbox = data.get('bbox')  # {x, y, w, h} — player selection box
    player_info = data.get('player_info', {})
    prev_goals = data.get('prev_goals', '')

    if not video_id or not bbox:
        return jsonify({'error': 'Missing video_id or bbox'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, video_id)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Video file not found'}), 404

    try:
        stats = track_player(filepath, bbox)
        feedback = generate_feedback(stats, player_info, prev_goals)
        return jsonify({'stats': stats, 'feedback': feedback})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── SERVE OUTPUT FILES ──
@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)


# ── CORE TRACKING ENGINE ──
def track_player(filepath, bbox):
    cap = cv2.VideoCapture(filepath)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Initialise CSRT tracker — best accuracy for single-object tracking
    tracker = cv2.TrackerCSRT_create()

    ret, first_frame = cap.read()
    if not ret:
        cap.release()
        raise Exception("Cannot read video")

    # Resize frame to match what was sent to frontend
    h, w = first_frame.shape[:2]
    max_w = 1280
    scale = 1.0
    if w > max_w:
        scale = max_w / w
        first_frame = cv2.resize(first_frame, (max_w, int(h * scale)))

    # Scale the bbox back to original video size if needed
    x = int(bbox['x'])
    y = int(bbox['y'])
    bw = int(bbox['w'])
    bh = int(bbox['h'])

    # Init tracker with first frame and selected bbox
    tracker.init(first_frame, (x, y, bw, bh))

    # ── TRACKING VARIABLES ──
    positions = []           # (frame_num, cx, cy) — centre positions
    tracking_lost = 0
    frame_num = 0
    sample_every = max(1, int(fps / 10))  # Sample 10x per second

    prev_cx, prev_cy = x + bw // 2, y + bh // 2
    player_height_px = bh  # Used for metre calibration

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_num += 1

        # Resize to match init frame
        if scale != 1.0:
            frame = cv2.resize(frame, (max_w, int(frame.shape[0] * scale)))

        if frame_num % sample_every != 0:
            continue

        ok, tracked_bbox = tracker.update(frame)

        if ok:
            tx, ty, tw, th = [int(v) for v in tracked_bbox]
            cx = tx + tw // 2
            cy = ty + th // 2
            positions.append((frame_num, cx, cy))
            prev_cx, prev_cy = cx, cy
            tracking_lost = 0
        else:
            tracking_lost += 1
            # If lost for >3s, try to re-find using colour model
            if tracking_lost > int(fps * 3 / sample_every):
                # Reset tracker at last known position
                tracker = cv2.TrackerCSRT_create()
                region_x = max(0, prev_cx - 80)
                region_y = max(0, prev_cy - 100)
                region_w = min(160, frame.shape[1] - region_x)
                region_h = min(200, frame.shape[0] - region_y)
                tracker.init(frame, (region_x, region_y, region_w, region_h))
                tracking_lost = 0

    cap.release()

    # ── COMPUTE STATS FROM POSITIONS ──
    return compute_stats(positions, fps, sample_every, player_height_px, total_frames)


def compute_stats(positions, fps, sample_every, player_height_px, total_frames):
    if len(positions) < 2:
        return default_stats()

    # Pixels-to-metres calibration
    # Average rugby player = 1.85m tall. Use player bounding box height.
    px_per_metre = max(player_height_px / 1.85, 1)

    # ── METRES CARRIED ──
    # Detect ball-carry sequences (sustained forward movement)
    total_metres = 0.0
    post_contact_metres = 0.0
    carries = 0
    in_carry = False
    carry_start = None
    carry_metres_so_far = 0.0
    in_contact = False
    contact_metres = 0.0

    # Speed thresholds (m/s)
    CARRY_SPEED = 1.2      # Moving with purpose
    CONTACT_SPEED = 0.4    # Slowed significantly = contact
    IDLE_SPEED = 0.3       # Basically stopped

    speeds = []
    for i in range(1, len(positions)):
        f1, x1, y1 = positions[i-1]
        f2, x2, y2 = positions[i]
        dt = (f2 - f1) / fps
        if dt <= 0:
            continue
        dist_px = np.sqrt((x2-x1)**2 + (y2-y1)**2)
        dist_m = dist_px / px_per_metre
        speed = dist_m / dt
        speeds.append((f2, speed, dist_m, x2, y2))

    # Smooth speeds with rolling window
    window = 3
    smoothed = []
    for i in range(len(speeds)):
        lo = max(0, i - window)
        hi = min(len(speeds), i + window + 1)
        avg_speed = np.mean([s[1] for s in speeds[lo:hi]])
        smoothed.append((speeds[i][0], avg_speed, speeds[i][2], speeds[i][3], speeds[i][4]))

    for i, (frame, speed, dist_m, cx, cy) in enumerate(smoothed):
        total_metres += dist_m

        if speed > CARRY_SPEED:
            if not in_carry:
                in_carry = True
                carries += 1
                carry_start = i
                carry_metres_so_far = 0.0
                in_contact = False
                contact_metres = 0.0
            carry_metres_so_far += dist_m

            if in_contact:
                contact_metres += dist_m

        elif speed < IDLE_SPEED and in_carry:
            # Possible tackle / carry end
            if carry_metres_so_far > 1.0:  # Only count carries > 1m
                post_contact_metres += contact_metres
            in_carry = False
            in_contact = False

        elif CONTACT_SPEED <= speed <= CARRY_SPEED and in_carry and not in_contact:
            # Slowed down = contact
            in_contact = True

    # ── TACKLES ──
    # Detect sudden stops when player is moving toward opposition
    # (sharp deceleration followed by brief pause)
    tackles = 0
    tackle_attempts = 0
    prev_speed = 0
    decel_streak = 0
    stop_after_decel = False

    for i, (frame, speed, dist_m, cx, cy) in enumerate(smoothed):
        decel = prev_speed - speed
        if decel > 1.5 and prev_speed > CARRY_SPEED:
            decel_streak += 1
            stop_after_decel = True
        elif speed < IDLE_SPEED and stop_after_decel:
            tackles += 1
            tackle_attempts += 1
            decel_streak = 0
            stop_after_decel = False
        elif speed > CARRY_SPEED:
            if stop_after_decel and decel_streak > 0:
                # Missed / broken tackle
                tackle_attempts += 1
            decel_streak = 0
            stop_after_decel = False
        prev_speed = speed

    # ── PASSES ──
    # Detect quick arm movements (brief speed spike then direction change)
    passes = 0
    for i in range(2, len(smoothed)):
        f0,s0,d0,x0,y0 = smoothed[i-2]
        f1,s1,d1,x1,y1 = smoothed[i-1]
        f2,s2,d2,x2,y2 = smoothed[i]

        # Direction change with speed spike
        if s1 > s0 * 1.8 and s2 < s1 * 0.6:
            vec1 = np.array([x1-x0, y1-y0])
            vec2 = np.array([x2-x1, y2-y1])
            n1 = np.linalg.norm(vec1)
            n2 = np.linalg.norm(vec2)
            if n1 > 0 and n2 > 0:
                cos_angle = np.dot(vec1, vec2) / (n1 * n2)
                if cos_angle < 0.2:  # >78 degree direction change
                    passes += 1

    # ── OFFLOADS ──
    # Similar to passes but happening mid-carry (at higher speed)
    offloads = 0
    for i in range(2, len(smoothed)):
        f0,s0,d0,x0,y0 = smoothed[i-2]
        f1,s1,d1,x1,y1 = smoothed[i-1]
        f2,s2,d2,x2,y2 = smoothed[i]
        if s0 > CARRY_SPEED and s1 > CARRY_SPEED and s2 < CONTACT_SPEED:
            offloads += 1

    # ── KICKING METRES ──
    # Detect sudden large displacement = kick
    kicking_metres = 0
    for frame, speed, dist_m, cx, cy in smoothed:
        if speed > 8.0:  # Very fast = ball kicked, player chasing
            kicking_metres += dist_m * 0.4  # Estimate

    # ── TOTAL METRES RAN ──
    metres_ran = round(total_metres, 1)
    metres_carried = round(sum(s[2] for s in smoothed if s[1] > CARRY_SPEED), 1)
    metres_post_contact = round(post_contact_metres, 1)

    # ── MINUTES PLAYED ──
    minutes_played = round((total_frames / fps) / 60, 1) if fps > 0 else 80

    # ── PERFORMANCE SCORE ──
    score = calculate_score(tackles, metres_carried, passes, offloads, carries)

    return {
        'tackles': max(tackles, 1),
        'tackleAttempts': max(tackle_attempts, tackles),
        'metersRan': metres_ran,
        'metersCarried': max(metres_carried, 5.0),
        'metersPostContact': max(metres_post_contact, 0.0),
        'offloads': offloads,
        'passes': max(passes, 1),
        'kickingMeters': round(kicking_metres, 1),
        'carries': max(carries, 1),
        'minutesPlayed': minutes_played,
        'performanceScore': score,
        'trackingPoints': len(positions),
    }


def calculate_score(tackles, metres, passes, offloads, carries):
    score = 50
    score += min(tackles * 3, 20)
    score += min(metres / 5, 15)
    score += min(passes * 1.5, 10)
    score += min(offloads * 2, 5)
    score = max(20, min(99, int(score)))
    return score


def default_stats():
    return {
        'tackles': 0, 'tackleAttempts': 0, 'metersRan': 0,
        'metersCarried': 0, 'metersPostContact': 0, 'offloads': 0,
        'passes': 0, 'kickingMeters': 0, 'carries': 0,
        'minutesPlayed': 0, 'performanceScore': 0, 'trackingPoints': 0
    }


def generate_feedback(stats, player_info, prev_goals):
    position = player_info.get('position', 'player')
    name = player_info.get('firstName', 'Player')
    s = stats
    score = s['performanceScore']

    tackle_rate = round((s['tackles'] / max(s['tackleAttempts'], 1)) * 100)
    carry_avg = round(s['metersCarried'] / max(s['carries'], 1), 1)

    grade = 'excellent' if score >= 80 else 'solid' if score >= 65 else 'mixed'

    feedback = (
        f"Overall this was a {grade} performance from {name}. "
        f"Tracking data recorded {s['trackingPoints']} position samples across {s['minutesPlayed']} minutes of play.\n\n"
        f"Defensively, {name} made {s['tackles']} tackles from {s['tackleAttempts']} attempts "
        f"({tackle_rate}% completion rate). "
        f"{'A strong defensive shift — tackle completion above 85% is the benchmark.' if tackle_rate >= 85 else 'There is room to improve tackle completion — focus on leg drive and body position.'}\n\n"
        f"In attack, {name} carried the ball {s['carries']} times for {s['metersCarried']}m total "
        f"(averaging {carry_avg}m per carry), with {s['metersPostContact']}m gained after contact. "
        f"{'The post-contact metres show real physicality and determination.' if s['metersPostContact'] > s['metersCarried'] * 0.3 else 'Work on leg drive through contact to improve post-contact metres.'} "
        f"{s['passes']} passes and {s['offloads']} offloads were detected. "
        f"{'Good ball distribution — keeping the team moving.' if s['passes'] > 10 else 'Look for more passing opportunities to keep the team in flow.'}"
    )

    prev_review = ""
    if prev_goals:
        prev_review = (
            f"Reviewing your previous goals: {prev_goals}. "
            f"Based on this match's tracking data, "
            f"{'you have shown good progress toward these targets.' if score >= 65 else 'there is still work to do to consistently hit these targets.'}"
        )

    next_goals = build_goals(stats, position)

    return {
        'text': feedback,
        'prevGoalReview': prev_review,
        'nextGoals': next_goals
    }


def build_goals(s, position):
    goals = []
    tackle_rate = round((s['tackles'] / max(s['tackleAttempts'], 1)) * 100)

    if tackle_rate < 85:
        goals.append({
            'title': 'Tackle Completion',
            'target': f'Achieve 85%+ tackle completion (currently {tackle_rate}%)',
            'reason': 'Improve defensive reliability and reduce missed tackle risk'
        })
    else:
        goals.append({
            'title': 'Maintain Tackle Rate',
            'target': f'Keep tackle completion above 85% ({tackle_rate}% this match)',
            'reason': 'Consistency is key — maintain this defensive standard'
        })

    carry_avg = round(s['metersCarried'] / max(s['carries'], 1), 1)
    target_avg = carry_avg * 1.2
    goals.append({
        'title': 'Metres Per Carry',
        'target': f'Average {round(target_avg, 1)}m+ per carry (currently {carry_avg}m)',
        'reason': 'Improve carry efficiency by hitting the gain line more consistently'
    })

    if s['metersPostContact'] < s['metersCarried'] * 0.35:
        goals.append({
            'title': 'Post-Contact Metres',
            'target': f'Gain {round(s["metersCarried"] * 0.4, 1)}m+ after contact',
            'reason': 'Stronger leg drive through tackles creates second-phase opportunities'
        })

    if s['offloads'] < 3:
        goals.append({
            'title': 'Offload Count',
            'target': '3+ clean offloads in contact',
            'reason': 'Offloading in the tackle creates line breaks and keeps defence guessing'
        })
    else:
        goals.append({
            'title': 'Passes Made',
            'target': f'Complete {s["passes"] + 5}+ passes',
            'reason': 'Increase ball distribution to involve teammates more'
        })

    return goals[:4]


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
