import os
import cv2
import uuid
import numpy as np
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ── FIX 1: Handle favicon so it doesn't crash the app ──
@app.route('/favicon.ico')
def favicon():
    return '', 204

# ── SERVE PAGES ──
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/<path:page>')
def pages(page):
    allowed = ['profile.html', 'analysis.html', 'library.html', 'leaderboard.html']
    if page in allowed:
        return render_template(page)
    return '', 404

# ── UPLOAD VIDEO ──
@app.route('/api/upload', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    filename = str(uuid.uuid4()) + '_' + secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    cap = cv2.VideoCapture(filepath)
    ret, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()

    if not ret:
        return jsonify({'error': 'Could not read video — please check the file is a valid MP4 or MOV'}), 400

    h, w = frame.shape[:2]
    max_w = 1280
    if w > max_w:
        scale = max_w / w
        frame = cv2.resize(frame, (max_w, int(h * scale)))

    frame_id = str(uuid.uuid4())
    frame_path = os.path.join(OUTPUT_FOLDER, frame_id + '_frame.jpg')
    cv2.imwrite(frame_path, frame)

    return jsonify({
        'video_id': filename,
        'frame_id': frame_id,
        'frame_url': f'/frame/{frame_id}_frame.jpg',
        'fps': fps,
        'total_frames': total_frames,
        'duration': round(duration, 1),
        'width': frame.shape[1],
        'height': frame.shape[0]
    })

# ── SERVE FRAMES ──
@app.route('/frame/<filename>')
def serve_frame(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)

# ── ANALYSE VIDEO ──
@app.route('/api/analyse', methods=['POST'])
def analyse_video():
    data = request.get_json()
    video_id = data.get('video_id')
    bbox = data.get('bbox')
    player_info = data.get('player_info', {})
    prev_goals = data.get('prev_goals', '')

    if not video_id or not bbox:
        return jsonify({'error': 'Missing video_id or player selection box'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, video_id)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Video not found — please re-upload'}), 404

    try:
        stats = track_player(filepath, bbox)
        feedback = generate_feedback(stats, player_info, prev_goals)
        return jsonify({'stats': stats, 'feedback': feedback})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── TRACKING ──
def track_player(filepath, bbox):
    cap = cv2.VideoCapture(filepath)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    tracker = cv2.TrackerCSRT_create()
    ret, first_frame = cap.read()
    if not ret:
        cap.release()
        raise Exception("Cannot read video file")

    h, w = first_frame.shape[:2]
    max_w = 1280
    scale = 1.0
    if w > max_w:
        scale = max_w / w
        first_frame = cv2.resize(first_frame, (max_w, int(h * scale)))

    x, y, bw, bh = int(bbox['x']), int(bbox['y']), int(bbox['w']), int(bbox['h'])
    tracker.init(first_frame, (x, y, bw, bh))

    positions = []
    frame_num = 0
    tracking_lost = 0
    prev_cx, prev_cy = x + bw // 2, y + bh // 2
    player_height_px = bh
    sample_every = max(1, int(fps / 10))

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_num += 1
        if scale != 1.0:
            frame = cv2.resize(frame, (max_w, int(frame.shape[0] * scale)))
        if frame_num % sample_every != 0:
            continue

        ok, tb = tracker.update(frame)
        if ok:
            tx, ty, tw, th = [int(v) for v in tb]
            cx, cy = tx + tw // 2, ty + th // 2
            positions.append((frame_num, cx, cy))
            prev_cx, prev_cy = cx, cy
            tracking_lost = 0
        else:
            tracking_lost += 1
            if tracking_lost > int(fps * 3 / sample_every):
                tracker = cv2.TrackerCSRT_create()
                rx = max(0, prev_cx - 80)
                ry = max(0, prev_cy - 100)
                rw = min(160, frame.shape[1] - rx)
                rh = min(200, frame.shape[0] - ry)
                tracker.init(frame, (rx, ry, rw, rh))
                tracking_lost = 0

    cap.release()
    return compute_stats(positions, fps, sample_every, player_height_px, total_frames)

def compute_stats(positions, fps, sample_every, player_height_px, total_frames):
    if len(positions) < 2:
        return default_stats()

    px_per_metre = max(player_height_px / 1.85, 1)
    CARRY_SPEED, CONTACT_SPEED, IDLE_SPEED = 1.2, 0.4, 0.3

    speeds = []
    for i in range(1, len(positions)):
        f1, x1, y1 = positions[i-1]
        f2, x2, y2 = positions[i]
        dt = (f2 - f1) / fps
        if dt <= 0: continue
        dist_m = np.sqrt((x2-x1)**2 + (y2-y1)**2) / px_per_metre
        speeds.append((f2, dist_m / dt, dist_m, x2, y2))

    window = 3
    smoothed = []
    for i in range(len(speeds)):
        lo, hi = max(0, i-window), min(len(speeds), i+window+1)
        avg_s = float(np.mean([s[1] for s in speeds[lo:hi]]))
        smoothed.append((speeds[i][0], avg_s, speeds[i][2], speeds[i][3], speeds[i][4]))

    total_m = metres_carried = post_contact_m = 0.0
    carries = 0
    in_carry = in_contact = False
    carry_m = contact_m = 0.0

    for _, speed, dist_m, cx, cy in smoothed:
        total_m += dist_m
        if speed > CARRY_SPEED:
            if not in_carry:
                in_carry, carries, carry_m, in_contact, contact_m = True, carries+1, 0.0, False, 0.0
            carry_m += dist_m
            metres_carried += dist_m
            if in_contact: contact_m += dist_m
        elif speed < IDLE_SPEED and in_carry:
            if carry_m > 1.0: post_contact_m += contact_m
            in_carry = in_contact = False
        elif CONTACT_SPEED <= speed <= CARRY_SPEED and in_carry and not in_contact:
            in_contact = True

    tackles = tackle_att = 0
    prev_s = stop_after_decel = False
    decel_streak = 0
    prev_speed_val = 0

    for _, speed, _, _, _ in smoothed:
        decel = prev_speed_val - speed
        if decel > 1.5 and prev_speed_val > CARRY_SPEED:
            decel_streak += 1
            stop_after_decel = True
        elif speed < IDLE_SPEED and stop_after_decel:
            tackles += 1; tackle_att += 1
            decel_streak = 0; stop_after_decel = False
        elif speed > CARRY_SPEED:
            if stop_after_decel and decel_streak > 0: tackle_att += 1
            decel_streak = 0; stop_after_decel = False
        prev_speed_val = speed

    passes = 0
    for i in range(2, len(smoothed)):
        _,s0,_,x0,y0 = smoothed[i-2]; _,s1,_,x1,y1 = smoothed[i-1]; _,s2,_,x2,y2 = smoothed[i]
        if s1 > s0 * 1.8 and s2 < s1 * 0.6:
            v1 = np.array([x1-x0, y1-y0], dtype=float); v2 = np.array([x2-x1, y2-y1], dtype=float)
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 > 0 and n2 > 0 and np.dot(v1,v2)/(n1*n2) < 0.2: passes += 1

    offloads = sum(1 for i in range(2, len(smoothed)) if smoothed[i-2][1] > CARRY_SPEED and smoothed[i-1][1] > CARRY_SPEED and smoothed[i][1] < CONTACT_SPEED)
    kicking_m = sum(d * 0.4 for _,s,d,_,_ in smoothed if s > 8.0)
    minutes = round((total_frames / fps) / 60, 1) if fps > 0 else 80

    return {
        'tackles': max(int(tackles), 1), 'tackleAttempts': max(int(tackle_att), int(tackles)),
        'metersRan': round(total_m, 1), 'metersCarried': round(max(metres_carried, 5.0), 1),
        'metersPostContact': round(max(post_contact_m, 0.0), 1), 'offloads': int(offloads),
        'passes': max(int(passes), 1), 'kickingMeters': round(kicking_m, 1),
        'carries': max(int(carries), 1), 'minutesPlayed': minutes,
        'performanceScore': calculate_score(tackles, metres_carried, passes, offloads, carries),
        'trackingPoints': len(positions),
    }

def calculate_score(tackles, metres, passes, offloads, carries):
    return max(20, min(99, int(50 + min(tackles*3,20) + min(metres/5,15) + min(passes*1.5,10) + min(offloads*2,5))))

def default_stats():
    return {'tackles':0,'tackleAttempts':0,'metersRan':0,'metersCarried':0,'metersPostContact':0,
            'offloads':0,'passes':0,'kickingMeters':0,'carries':0,'minutesPlayed':0,'performanceScore':0,'trackingPoints':0}

def generate_feedback(stats, player_info, prev_goals):
    name = player_info.get('firstName', 'Player')
    s = stats
    score = s['performanceScore']
    tackle_rate = round((s['tackles'] / max(s['tackleAttempts'], 1)) * 100)
    carry_avg = round(s['metersCarried'] / max(s['carries'], 1), 1)
    grade = 'excellent' if score >= 80 else 'solid' if score >= 65 else 'mixed'

    text = (
        f"Overall this was a {grade} performance from {name}. "
        f"Tracking recorded {s['trackingPoints']} position samples across {s['minutesPlayed']} minutes.\n\n"
        f"Defensively, {name} made {s['tackles']} tackles from {s['tackleAttempts']} attempts ({tackle_rate}% completion). "
        f"{'Great defensive work — above the 85% benchmark.' if tackle_rate >= 85 else 'Tackle completion needs work — focus on technique and body position.'}\n\n"
        f"In attack, {name} carried {s['carries']} times for {s['metersCarried']}m ({carry_avg}m/carry), "
        f"gaining {s['metersPostContact']}m after contact. "
        f"{'Strong leg drive through contact.' if s['metersPostContact'] > s['metersCarried']*0.3 else 'Improve leg drive to gain more post-contact metres.'} "
        f"{s['passes']} passes and {s['offloads']} offloads recorded."
    )

    prev_review = f"Goals review: {prev_goals}. {'Good progress shown.' if score >= 65 else 'More work needed to hit these targets.'}" if prev_goals else ""

    return {'text': text, 'prevGoalReview': prev_review, 'nextGoals': build_goals(stats, player_info.get('position',''))}

def build_goals(s, position):
    tackle_rate = round((s['tackles'] / max(s['tackleAttempts'], 1)) * 100)
    carry_avg = round(s['metersCarried'] / max(s['carries'], 1), 1)
    goals = []
    goals.append({'title': 'Tackle Completion', 'target': f'{"Maintain" if tackle_rate>=85 else "Achieve"} 85%+ tackle completion (currently {tackle_rate}%)', 'reason': 'Defensive reliability is the foundation of a strong performance'})
    goals.append({'title': 'Metres Per Carry', 'target': f'Average {round(carry_avg*1.2,1)}m+ per carry (currently {carry_avg}m)', 'reason': 'Consistently hit the gain line to create attacking momentum'})
    goals.append({'title': 'Post-Contact Metres', 'target': f'{round(s["metersCarried"]*0.4,1)}m+ after contact', 'reason': 'Drive through tackles to create second-phase opportunities'} if s['metersPostContact'] < s['metersCarried']*0.35 else {'title': 'Offloads', 'target': '3+ offloads in contact', 'reason': 'Keep defence guessing with offloads in the tackle'})
    goals.append({'title': 'Ball Carries', 'target': f'{s["carries"]+2}+ carries', 'reason': 'Demand the ball more — higher carry count means more impact'})
    return goals[:4]

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
