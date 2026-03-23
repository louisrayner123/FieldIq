// ── FIELDIQ SHARED DATA STORE ──
// Shared across all pages via localStorage

const FieldIQ = {
  // Save data
  save(key, value) {
    try { localStorage.setItem('fieldiq_' + key, JSON.stringify(value)); } catch(e) {}
  },
  // Load data
  load(key, fallback = null) {
    try {
      const v = localStorage.getItem('fieldiq_' + key);
      return v ? JSON.parse(v) : fallback;
    } catch(e) { return fallback; }
  },

  // Get all players
  getPlayers() {
    return this.load('players', [
      { id: 1, firstName: 'Jamie', lastName: 'Davies', position: 'Openside Flanker', number: 7, minutesPlayed: 480, matches: 6, avgScore: 74, tackles: 9.2, meters: 38, passes: 14, offloads: 2.1, kicks: 8 },
      { id: 2, firstName: 'Tom', lastName: 'Richards', position: 'Scrum-Half', number: 9, minutesPlayed: 520, matches: 7, avgScore: 81, tackles: 4.1, meters: 28, passes: 42, offloads: 1.8, kicks: 65 },
      { id: 3, firstName: 'Marcus', lastName: 'Webb', position: 'Number 8', number: 8, minutesPlayed: 440, matches: 6, avgScore: 68, tackles: 8.5, meters: 52, passes: 11, offloads: 3.2, kicks: 4 },
      { id: 4, firstName: 'Connor', lastName: 'Price', position: 'Fly-Half', number: 10, minutesPlayed: 560, matches: 7, avgScore: 77, tackles: 3.2, meters: 35, passes: 38, offloads: 1.4, kicks: 120 },
      { id: 5, firstName: 'Ryan', lastName: 'Fletcher', position: 'Hooker', number: 2, minutesPlayed: 380, matches: 5, avgScore: 71, tackles: 10.4, meters: 22, passes: 9, offloads: 1.2, kicks: 0 },
      { id: 6, firstName: 'Liam', lastName: 'Okafor', position: 'Outside Centre', number: 13, minutesPlayed: 600, matches: 8, avgScore: 85, tackles: 5.8, meters: 68, passes: 22, offloads: 4.1, kicks: 30 },
    ]);
  },

  // Get match history
  getMatches() {
    return this.load('matches', [
      { id: 1, playerId: 1, opposition: 'Saracens RFC', date: '2026-03-01', competition: 'National League 1', result: 'win', score: '28–17', stats: { tackles: 11, tackleAttempts: 13, metersCarried: 42, metersPostContact: 19, offloads: 2, passes: 16, kickingMeters: 0, carries: 9, performanceScore: 78 } },
      { id: 2, playerId: 1, opposition: 'Leicester Tigers', date: '2026-02-15', competition: 'National League 1', result: 'loss', score: '14–22', stats: { tackles: 8, tackleAttempts: 11, metersCarried: 28, metersPostContact: 11, offloads: 1, passes: 12, kickingMeters: 0, carries: 7, performanceScore: 61 } },
      { id: 3, playerId: 2, opposition: 'Bath RFC', date: '2026-03-08', competition: 'National League 1', result: 'win', score: '31–24', stats: { tackles: 5, tackleAttempts: 6, metersCarried: 30, metersPostContact: 12, offloads: 2, passes: 44, kickingMeters: 75, carries: 11, performanceScore: 84 } },
      { id: 4, playerId: 6, opposition: 'Harlequins', date: '2026-03-12', competition: 'Cup', result: 'win', score: '19–15', stats: { tackles: 6, tackleAttempts: 7, metersCarried: 72, metersPostContact: 28, offloads: 5, passes: 24, kickingMeters: 35, carries: 14, performanceScore: 89 } },
    ]);
  },

  // Get current player
  getCurrentPlayer() {
    return this.load('currentPlayer', null);
  },

  setCurrentPlayer(id) {
    this.save('currentPlayer', id);
  },

  getInitials(p) {
    return (p.firstName[0] || '') + (p.lastName[0] || '');
  },

  // Nav highlight
  setActiveNav(page) {
    document.querySelectorAll('.nav-item').forEach(n => {
      n.classList.toggle('active', n.dataset.page === page);
    });
  }
};
