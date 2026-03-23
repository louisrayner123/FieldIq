# FieldIQ – Rugby Performance AI
## Step-by-Step Deployment Guide

---

## WHAT THIS IS
A full web application where rugby players:
1. Upload their match video
2. Draw a box around themselves on the first frame
3. The AI tracks them through the full match
4. Stats are generated: tackles, metres, post-contact metres, offloads, passes, kicking metres
5. AI feedback and next-match goals are given

---

## STEP 1 — Install Python (if you don't have it)
1. Go to https://python.org/downloads
2. Download Python 3.11 or higher
3. Install it — tick "Add Python to PATH" during install

---

## STEP 2 — Test it locally first
Open a terminal (Command Prompt on Windows, Terminal on Mac):

```bash
# Go into the project folder
cd fieldiq-app

# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py
```

Then open your browser and go to: http://localhost:5000
Your site is running! Test the full upload → select → analyse flow.

---

## STEP 3 — Deploy to Railway (free hosting, your own URL)

### A) Create your Railway account
1. Go to https://railway.app
2. Click "Start a New Project"
3. Sign up with GitHub (free)

### B) Push your code to GitHub
1. Go to https://github.com and create a free account if you don't have one
2. Create a new repository called "fieldiq"
3. Upload ALL the files from this folder to that repository

### C) Deploy on Railway
1. In Railway, click "New Project" → "Deploy from GitHub repo"
2. Select your "fieldiq" repository
3. Railway detects Python automatically and deploys it
4. Click "Generate Domain" — Railway gives you a free URL like:
   `https://fieldiq-production.up.railway.app`

That's your live website URL. Share it with your players!

---

## STEP 4 — Custom domain (optional, ~£10/year)
1. Buy a domain at Namecheap or GoDaddy (e.g. fieldiq.co.uk)
2. In Railway → Settings → Domains → Add Custom Domain
3. Follow Railway's DNS instructions (takes ~10 minutes)

---

## IMPORTANT NOTES

### Video requirements for best tracking accuracy:
- Fixed camera position (tripod preferred)
- Player visible for majority of match
- Good lighting
- Minimum 720p resolution

### Processing time:
- 80-minute match at 25fps ≈ 10–20 minutes to analyse
- Railway free tier may be slow for large files
- For faster processing, upgrade to Railway Starter ($5/month)

### The AI tracking:
- Uses OpenCV CSRT tracker — industry-standard single-object tracking
- Player selected in frame 1 is tracked by appearance (colour, shape, size)
- If tracking is lost (player goes off screen), it re-acquires automatically
- Stats are computed from movement patterns: speed, acceleration, direction changes

---

## FILE STRUCTURE
```
fieldiq-app/
├── app.py              ← Main server (Python/Flask)
├── requirements.txt    ← Python dependencies
├── Procfile            ← Tells Railway how to start the app
├── railway.toml        ← Railway configuration
├── templates/          ← All HTML pages
│   ├── index.html      ← Team Overview
│   ├── profile.html    ← Player Profile
│   ├── analysis.html   ← Analysis Room (main page)
│   ├── library.html    ← Video Library
│   └── leaderboard.html← Leaderboard
├── static/             ← CSS and JS files
├── uploads/            ← Uploaded videos (temporary)
└── outputs/            ← Processed frames
```

---

## NEED HELP?
If you get stuck at any step, take a screenshot of the error and ask Claude to help you fix it.
