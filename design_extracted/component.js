
class Component extends DCLogic {
  state = { page: null };

  // Use prop as the source of truth when set, otherwise local state default.
  _page() {
    return this.state.page ?? this.props.page ?? 'dashboard';
  }

  componentDidUpdate(prevProps) {
    if (prevProps.page !== this.props.page) {
      this.setState({ page: null }); // re-yield to prop
    }
  }

  // ── Deterministic helpers ───────────────────────────────────────
  _hash(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) | 0; }
    return Math.abs(h);
  }

  _avatarColors(name) {
    const palettes = [
      { bg: '#F4E4D6', fg: '#9A4B1A' },
      { bg: '#E0E8F4', fg: '#28457E' },
      { bg: '#E4EFE3', fg: '#2D6A3F' },
      { bg: '#F2E4EE', fg: '#7B2C8C' },
      { bg: '#F4EBD6', fg: '#8C6A1F' },
      { bg: '#E0EAEC', fg: '#2A5C66' },
      { bg: '#EFE3E1', fg: '#8C3E2C' },
    ];
    return palettes[this._hash(name) % palettes.length];
  }

  _initials(name) {
    const parts = name.split(/[\s-]+/).filter(Boolean);
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  // ── Employee data (used by Dashboard) ───────────────────────────
  _employees() {
    const raw = [
      { name: 'Ahmed Al-Rashid',  role: 'Operations Manager', hours: '8:42', activeMin: 412, idleMin: 38, nonProdMin: 12, nonprod: '0:12', score: 94, odoo: 287, tag: 'good',  pattern: 'steady' },
      { name: 'Noura Al-Qasim',   role: 'Sales Lead',         hours: '8:18', activeMin: 388, idleMin: 52, nonProdMin: 22, nonprod: '0:22', score: 89, odoo: 412, tag: 'good',  pattern: 'spiky' },
      { name: 'Layla Ibrahim',    role: 'Accounts',           hours: '8:05', activeMin: 372, idleMin: 71, nonProdMin: 14, nonprod: '0:14', score: 86, odoo: 198, tag: 'good',  pattern: 'morning' },
      { name: 'Yusuf Hakim',      role: 'Fleet Coordinator',  hours: '7:54', activeMin: 354, idleMin: 88, nonProdMin: 16, nonprod: '0:16', score: 82, odoo: 224, tag: 'good',  pattern: 'steady' },
      { name: 'Sara Mansour',     role: 'HR Specialist',      hours: '8:12', activeMin: 366, idleMin: 92, nonProdMin: 24, nonprod: '0:24', score: 79, odoo: 156, tag: 'good',  pattern: 'afternoon' },
      { name: 'Khaled Faris',     role: 'Procurement',        hours: '7:48', activeMin: 322, idleMin: 96, nonProdMin: 28, nonprod: '0:28', score: 74, odoo: 174, tag: 'good',  pattern: 'steady' },
      { name: 'Fatima Saeed',     role: 'Customer Service',   hours: '8:00', activeMin: 296, idleMin: 124, nonProdMin: 36, nonprod: '0:36', score: 66, odoo: 248, tag: 'warn',  pattern: 'morning' },
      { name: 'Hala Naser',       role: 'Finance',            hours: '7:34', activeMin: 268, idleMin: 142, nonProdMin: 34, nonprod: '0:34', score: 62, odoo: 119, tag: 'warn',  pattern: 'spiky' },
      { name: 'Tareq Salem',      role: 'Fleet Maintenance',  hours: '6:58', activeMin: 232, idleMin: 144, nonProdMin: 48, nonprod: '0:48', score: 54, odoo: 87,  tag: 'warn',  pattern: 'afternoon' },
      { name: 'Mohammed Khalil',  role: 'Dispatch',           hours: '7:20', activeMin: 196, idleMin: 184, nonProdMin: 60, nonprod: '1:00', score: 42, odoo: 64,  tag: 'danger',pattern: 'gappy' },
      { name: 'Reem Hadi',        role: 'Marketing',          hours: '6:42', activeMin: 168, idleMin: 168, nonProdMin: 66, nonprod: '1:06', score: 38, odoo: 41,  tag: 'danger',pattern: 'gappy' },
      { name: 'Omar Ziyad',       role: 'IT Support',         hours: '—',    activeMin: 0,   idleMin: 0,   nonProdMin: 0,  nonprod: '—',    score: 0,  odoo: 0,   tag: 'absent',pattern: 'absent' },
    ];

    const tagStyles = {
      good:   { bg: '#E5F0EA', fg: '#1F5C42', dot: '#2A7F5C', label: 'Healthy' },
      warn:   { bg: '#FBF1DB', fg: '#7C5310', dot: '#B7791F', label: 'Warn' },
      danger: { bg: '#FAE4E1', fg: '#7B281F', dot: '#B23A2F', label: 'High idle' },
      absent: { bg: '#F2F0EA', fg: '#8B8E99', dot: '#B5B7BD', label: 'Absent' },
    };

    const patterns = {
      steady:    [70, 78, 84, 82, 72, 88, 90, 82, 75],
      spiky:     [55, 92, 48, 88, 35, 95, 62, 90, 50],
      morning:   [92, 95, 88, 80, 60, 50, 42, 38, 30],
      afternoon: [42, 48, 55, 60, 70, 82, 90, 88, 85],
      gappy:     [60, 25, 50, 20, 70, 18, 45, 22, 38],
      absent:    [0, 0, 0, 0, 0, 0, 0, 0, 0],
    };

    return raw.map((e) => {
      const total = Math.max(e.activeMin + e.idleMin + e.nonProdMin, 1);
      const aw = (e.activeMin / total) * 100;
      const iw = (e.idleMin / total) * 100;
      const nw = (e.nonProdMin / total) * 100;
      const ac = this._avatarColors(e.name);
      const st = tagStyles[e.tag];

      // Score band → color
      let scoreRing = '#2A7F5C', scoreBg = '#E5F0EA', scoreFg = '#1F5C42', scoreLetter = 'A';
      if (e.score === 0)           { scoreRing = '#B5B7BD'; scoreBg = '#F2F0EA'; scoreFg = '#8B8E99'; scoreLetter = '—'; }
      else if (e.score >= 85)      { scoreRing = '#2A7F5C'; scoreBg = '#E5F0EA'; scoreFg = '#1F5C42'; scoreLetter = 'A'; }
      else if (e.score >= 70)      { scoreRing = '#4D9E72'; scoreBg = '#EAF3EE'; scoreFg = '#2F6249'; scoreLetter = 'B'; }
      else if (e.score >= 55)      { scoreRing = '#B7791F'; scoreBg = '#FBF1DB'; scoreFg = '#7C5310'; scoreLetter = 'C'; }
      else if (e.score >= 40)      { scoreRing = '#C77A0E'; scoreBg = '#FBE7D4'; scoreFg = '#7C4A0D'; scoreLetter = 'D'; }
      else                          { scoreRing = '#B23A2F'; scoreBg = '#FAE4E1'; scoreFg = '#7B281F'; scoreLetter = 'F'; }

      // Bars: intensity → height + color
      const intensities = patterns[e.pattern] || patterns.steady;
      const bars = intensities.map((v) => {
        let color = '#E5C46A';
        if (v === 0) color = '#F2F0EA';
        else if (v >= 75) color = '#2A7F5C';
        else if (v >= 50) color = '#4D9E72';
        else if (v >= 30) color = '#B7791F';
        else if (v > 0)   color = '#D67E5E';
        const h = v === 0 ? '12%' : `${Math.max(15, v)}%`;
        return { h, color };
      });

      const fmt = (m) => {
        if (m === 0 && e.tag === 'absent') return '—';
        const h = Math.floor(m / 60), mm = m % 60;
        return `${h}:${String(mm).padStart(2, '0')}`;
      };

      return {
        name: e.name,
        role: e.role,
        initials: this._initials(e.name),
        avatarBg: ac.bg,
        avatarFg: ac.fg,
        statusBg: st.bg,
        statusFg: st.fg,
        statusDot: st.dot,
        statusLabel: st.label,
        hours: e.hours,
        hoursColor: e.tag === 'absent' ? '#B5B7BD' : '#15192A',
        activeW: `${aw.toFixed(1)}%`,
        idleW: `${iw.toFixed(1)}%`,
        nonProdW: `${nw.toFixed(1)}%`,
        activeLabel: e.tag === 'absent' ? '—' : fmt(e.activeMin),
        idleLabel: e.tag === 'absent' ? '—' : fmt(e.idleMin),
        nonprod: e.nonprod,
        nonprodColor: e.nonProdMin >= 40 ? '#B23A2F' : (e.nonProdMin >= 20 ? '#B7791F' : '#4A5060'),
        score: e.score === 0 ? '—' : String(e.score),
        scoreRing, scoreBg, scoreFg, scoreLetter,
        bars,
        odoo: e.odoo === 0 ? '—' : String(e.odoo),
        odooColor: e.odoo === 0 ? '#B5B7BD' : '#15192A',
      };
    });
  }

  // ── Reports data ────────────────────────────────────────────────
  _weekBars() {
    const days = [
      { day: 'Mon', total: '298h', active: 218, idle: 62, nonProd: 18 },
      { day: 'Tue', total: '312h', active: 234, idle: 58, nonProd: 20 },
      { day: 'Wed', total: '289h', active: 211, idle: 60, nonProd: 18 },
      { day: 'Thu', total: '305h', active: 232, idle: 54, nonProd: 19 },
      { day: 'Fri', total: '266h', active: 192, idle: 56, nonProd: 18 },
      { day: 'Sat', total: '224h', active: 168, idle: 42, nonProd: 14 },
      { day: 'Today', total: '153h', active: 116, idle: 28, nonProd: 9, current: true },
    ];
    const max = 320;
    return days.map((d) => ({
      day: d.day,
      total: d.total,
      activeH: `${(d.active / max * 100).toFixed(1)}%`,
      idleH: `${(d.idle / max * 100).toFixed(1)}%`,
      nonProdH: `${(d.nonProd / max * 100).toFixed(1)}%`,
      weight: d.current ? '600' : '500',
    }));
  }

  _attention() {
    const list = [
      { name: 'Mohammed Khalil', note: 'Dispatch · 3-day idle trend ↑',     idle: '3:04', nonprod: '1:00', score: 42 },
      { name: 'Reem Hadi',       note: 'Marketing · gaps 11:00–14:30',      idle: '2:48', nonprod: '1:06', score: 38 },
      { name: 'Tareq Salem',     note: 'Fleet Maint. · low afternoon',       idle: '2:24', nonprod: '0:48', score: 54 },
      { name: 'Hala Naser',      note: 'Finance · spiky activity',          idle: '2:22', nonprod: '0:34', score: 62 },
      { name: 'Fatima Saeed',    note: 'Customer Service · 4-day trend ↓',   idle: '2:04', nonprod: '0:36', score: 66 },
    ];
    return list.map((e) => {
      const ac = this._avatarColors(e.name);
      let scoreBg = '#FAE4E1', scoreFg = '#7B281F';
      if (e.score >= 60) { scoreBg = '#FBF1DB'; scoreFg = '#7C5310'; }
      if (e.score >= 70) { scoreBg = '#FBE7D4'; scoreFg = '#7C4A0D'; }
      return { ...e, initials: this._initials(e.name), avatarBg: ac.bg, avatarFg: ac.fg, scoreBg, scoreFg };
    });
  }

  _topPerformers() {
    const list = [
      { rank: '1', name: 'Ahmed Al-Rashid',  role: 'Operations Manager', pct: '94%' },
      { rank: '2', name: 'Noura Al-Qasim',   role: 'Sales Lead',         pct: '91%' },
      { rank: '3', name: 'Layla Ibrahim',    role: 'Accounts',           pct: '88%' },
      { rank: '4', name: 'Yusuf Hakim',      role: 'Fleet Coordinator',  pct: '85%' },
      { rank: '5', name: 'Sara Mansour',     role: 'HR Specialist',      pct: '82%' },
    ];
    return list.map((e) => ({ ...e, initials: this._initials(e.name), ...this._avatarColors(e.name) }))
               .map((e) => ({ ...e, avatarBg: e.bg, avatarFg: e.fg }));
  }

  _heatmap() {
    const heat = ['#F2F0EA', '#D0E1D6', '#8FBE9F', '#4D9E72', '#1E6E4A'];
    const names = ['Ahmed Al-Rashid', 'Noura Al-Qasim', 'Layla Ibrahim', 'Yusuf Hakim', 'Sara Mansour', 'Fatima Saeed', 'Mohammed Khalil', 'Reem Hadi'];
    const intensities = [
      [3, 4, 4, 3, 2, 4, 4, 3, 3, 2],
      [2, 3, 4, 3, 2, 1, 4, 4, 3, 3],
      [4, 4, 3, 2, 1, 3, 4, 3, 2, 1],
      [3, 3, 3, 2, 2, 3, 3, 4, 3, 2],
      [3, 4, 3, 2, 2, 2, 3, 3, 4, 3],
      [4, 3, 2, 1, 1, 2, 3, 2, 1, 0],
      [2, 1, 1, 0, 0, 0, 2, 1, 0, 0],
      [1, 2, 0, 0, 1, 0, 1, 2, 1, 0],
    ];
    return names.map((n, i) => ({
      name: n,
      cells: intensities[i].map((v) => heat[v]),
    }));
  }

  _odooDetail() {
    const list = [
      { name: 'Ahmed Al-Rashid',  email: 'ahmed.r@ashwheelz.com',     actions: '287', modules: ['Sales', 'Inventory', 'Fleet'] },
      { name: 'Noura Al-Qasim',   email: 'noura.q@ashwheelz.com',     actions: '412', modules: ['CRM', 'Sales'] },
      { name: 'Layla Ibrahim',    email: 'layla.i@ashwheelz.com',     actions: '198', modules: ['Accounting', 'Invoicing'] },
      { name: 'Yusuf Hakim',      email: 'yusuf.h@ashwheelz.com',     actions: '224', modules: ['Fleet', 'Maintenance'] },
      { name: 'Sara Mansour',     email: 'sara.m@ashwheelz.com',      actions: '156', modules: ['HR', 'Recruitment'] },
      { name: 'Khaled Faris',     email: 'khaled.f@ashwheelz.com',    actions: '174', modules: ['Purchase', 'Inventory'] },
    ];
    return list.map((u) => {
      const ac = this._avatarColors(u.name);
      return { ...u, initials: this._initials(u.name), avatarBg: ac.bg, avatarFg: ac.fg };
    });
  }

  // ── Settings: mapping lists ─────────────────────────────────────
  _odooMappingUsers() {
    const list = [
      { name: 'Ahmed Al-Rashid',  email: 'ahmed.r@ashwheelz.com',     linkedTo: 'Ahmed Rashid' },
      { name: 'Noura Al-Qasim',   email: 'noura.q@ashwheelz.com',     linkedTo: 'Noura AlQasim',  selected: true },
      { name: 'Layla Ibrahim',    email: 'layla.i@ashwheelz.com',     linkedTo: 'Layla I.' },
      { name: 'Yusuf Hakim',      email: 'yusuf.h@ashwheelz.com',     linkedTo: 'Yusuf H' },
      { name: 'Sara Mansour',     email: 'sara.m@ashwheelz.com',      linkedTo: 'Sara M.' },
      { name: 'Khaled Faris',     email: 'khaled.f@ashwheelz.com',    linkedTo: null },
      { name: 'Fatima Saeed',     email: 'fatima.s@ashwheelz.com',    linkedTo: 'Fatima Saeed' },
      { name: 'Omar Ziyad',       email: 'omar.z@ashwheelz.com',      linkedTo: null },
    ];
    return list.map((u) => {
      const ac = this._avatarColors(u.name);
      const isLinked = !!u.linkedTo;
      return {
        name: u.name,
        email: u.email,
        initials: this._initials(u.name),
        avatarBg: ac.bg,
        avatarFg: ac.fg,
        linkedTo: u.linkedTo,
        bg: u.selected ? '#FCEEDF' : (isLinked ? '#FBFCFA' : '#FFFFFF'),
        nameColor: isLinked ? '#1F5C42' : '#15192A',
        weight: u.selected ? '600' : '500',
      };
    });
  }

  _tdMappingUsers() {
    const list = [
      { name: 'Ahmed Rashid',      linkedTo: 'ahmed.r@ashwheelz.com' },
      { name: 'Noura AlQasim',     linkedTo: 'noura.q@ashwheelz.com', selected: true },
      { name: 'Layla I.',          linkedTo: 'layla.i@ashwheelz.com' },
      { name: 'Yusuf H',           linkedTo: 'yusuf.h@ashwheelz.com' },
      { name: 'Sara M.',           linkedTo: 'sara.m@ashwheelz.com' },
      { name: 'Fatima Saeed',      linkedTo: 'fatima.s@ashwheelz.com' },
      { name: 'M. Khalil',         linkedTo: null, unlinked: true },
      { name: 'reem.h',            linkedTo: null, unlinked: true },
    ];
    return list.map((u) => {
      const ac = this._avatarColors(u.name);
      const isLinked = !!u.linkedTo;
      return {
        name: u.name,
        initials: this._initials(u.name),
        avatarBg: ac.bg,
        avatarFg: ac.fg,
        linkedTo: u.linkedTo,
        unlinked: !!u.unlinked,
        bg: u.selected ? '#FCEEDF' : (isLinked ? '#FBFCFA' : '#FFFFFF'),
        nameColor: isLinked ? '#1F5C42' : '#15192A',
        weight: u.selected ? '600' : '500',
      };
    });
  }

  // ── renderVals ──────────────────────────────────────────────────
  renderVals() {
    const page = this._page();
    const go = (p) => () => this.setState({ page: p });

    const navIconDash = React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' },
      React.createElement('rect', { x: 3, y: 3, width: 7, height: 9, rx: 1 }),
      React.createElement('rect', { x: 14, y: 3, width: 7, height: 5, rx: 1 }),
      React.createElement('rect', { x: 14, y: 12, width: 7, height: 9, rx: 1 }),
      React.createElement('rect', { x: 3, y: 16, width: 7, height: 5, rx: 1 })
    );
    const navIconReports = React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' },
      React.createElement('path', { d: 'M3 17l6-6 4 4 8-8' }),
      React.createElement('path', { d: 'M14 7h7v7' })
    );
    const navIconSettings = React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' },
      React.createElement('circle', { cx: 12, cy: 12, r: 3 }),
      React.createElement('path', { d: 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z' })
    );

    const navItem = (id, label, icon, badge) => ({
      label, icon, badge,
      onClick: go(id),
      bg: page === id ? '#1A2748' : 'transparent',
      color: page === id ? '#FFFFFF' : '#A8B2CC',
      weight: page === id ? '600' : '500',
    });

    // Filter chips
    const filters = [
      { label: 'All',          count: '42', hasDot: false, active: true,  tag: null },
      { label: 'Healthy',      count: '32', hasDot: true,  active: false, tag: 'good',   dotColor: '#2A7F5C' },
      { label: 'Warn',         count: '3',  hasDot: true,  active: false, tag: 'warn',   dotColor: '#B7791F' },
      { label: 'High idle',    count: '2',  hasDot: true,  active: false, tag: 'danger', dotColor: '#B23A2F' },
      { label: 'Absent',       count: '5',  hasDot: true,  active: false, tag: 'absent', dotColor: '#B5B7BD' },
    ];
    const filterChips = filters.map((f) => ({
      label: f.label,
      count: f.count,
      hasDot: f.hasDot,
      dotColor: f.dotColor || '#B5B7BD',
      onClick: () => {},
      bg: f.active ? '#15192A' : '#FFFFFF',
      color: f.active ? '#FFFFFF' : '#4A5060',
      borderColor: f.active ? '#15192A' : '#ECE9E2',
      countColor: f.active ? '#A8B2CC' : '#8B8E99',
      weight: f.active ? '600' : '500',
    }));

    return {
      isDashboard: page === 'dashboard',
      isReports:   page === 'reports',
      isSettings:  page === 'settings',
      navItems: [
        navItem('dashboard', 'Dashboard', navIconDash),
        navItem('reports',   'Reports',   navIconReports),
        navItem('settings',  'Settings',  navIconSettings, '5'),
      ],
      filters: filterChips,
      employees: this._employees(),
      weekBars: this._weekBars(),
      attention: this._attention(),
      topPerformers: this._topPerformers(),
      hourLabels: ['09', '10', '11', '12', '13', '14', '15', '16', '17', '18'],
      heatmapRows: this._heatmap(),
      odooDetail: this._odooDetail(),
      odooUsers: this._odooMappingUsers(),
      tdUsers: this._tdMappingUsers(),
    };
  }
}
